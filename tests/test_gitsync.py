import subprocess

import pytest

from bearcli.gitsync import GitError, export_and_push


def git(cwd, *args):
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path):
    remote = tmp_path / "remote.git"
    clone = tmp_path / "clone"
    subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
    subprocess.run(["git", "clone", "-q", str(remote), str(clone)], check=True, capture_output=True)
    for k, v in (("user.email", "t@t"), ("user.name", "t")):
        git(clone, "config", k, v)
    return remote, clone


def clone2(tmp_path, remote):
    other = tmp_path / "other"
    subprocess.run(["git", "clone", "-q", str(remote), str(other)], check=True, capture_output=True)
    for k, v in (("user.email", "o@o"), ("user.name", "o")):
        git(other, "config", k, v)
    return other


def test_not_a_repo_errors(populated, tmp_path):
    db = populated.open()
    with pytest.raises(GitError, match="not a git repository"):
        export_and_push(db, tmp_path / "plain")


def test_first_push_and_noop(populated, repo):
    db = populated.open()
    _, clone = repo
    result, outcome = export_and_push(db, clone)
    assert outcome == "pushed" and result.written == 3

    result, outcome = export_and_push(db, clone)
    assert outcome == "pushed" and result.written == 0 and result.unchanged == 3


def test_remote_edit_is_overwritten_but_kept_in_history(populated, repo, tmp_path):
    db = populated.open()
    remote, clone = repo
    export_and_push(db, clone)

    other = clone2(tmp_path, remote)
    target = other / "groceries-aaaa1111" / "README.md"
    target.write_text(target.read_text() + "REMOTE EDIT\n")
    git(other, "commit", "-aqm", "remote edit")
    git(other, "push", "-q")

    export_and_push(db, clone)
    assert "REMOTE EDIT" not in (clone / "groceries-aaaa1111" / "README.md").read_text()
    log = subprocess.run(["git", "-C", str(clone), "log", "--oneline"], capture_output=True, text=True).stdout
    assert "remote edit" in log


def test_divergence_converges(populated, repo, tmp_path):
    db = populated.open()
    remote, clone = repo
    export_and_push(db, clone)

    local = clone / "groceries-aaaa1111" / "README.md"
    local.write_text(local.read_text() + "LOCAL EDIT\n")
    git(clone, "commit", "-aqm", "local edit")

    other = clone2(tmp_path, remote)
    target = other / "project-plan-bbbb2222" / "README.md"
    target.write_text(target.read_text() + "REMOTE EDIT\n")
    git(other, "commit", "-aqm", "remote edit")
    git(other, "push", "-q")

    _, outcome = export_and_push(db, clone)
    assert outcome == "pushed"
    assert "LOCAL EDIT" not in local.read_text()
    status = subprocess.run(["git", "-C", str(clone), "status", "--porcelain"], capture_output=True, text=True).stdout
    assert status == ""
