from bearcli.db import Note
from bearcli.secrets import redact_text, redaction_map, scan_notes


def note(text: str) -> Note:
    return Note(
        id="N1",
        title="t",
        created=None,
        modified=None,
        pinned=False,
        encrypted=False,
        archived=False,
        trashed=False,
        text=text,
    )


def rules(text: str) -> set[str]:
    return {f.rule for f in scan_notes([note(text)])}


def test_aws_key_detected():
    assert "AWS Access Key" in rules("key AKIAIOSFODNN7EXAMPLE here")


def test_unquoted_password_assignment():
    assert "Secret Keyword" in rules("password: hunter2secret99")


def test_unquoted_high_entropy_token():
    assert "High Entropy String" in rules("Secret Access Key: pmqUeFvz8kQ3+xY7wA2rTn5cJ9dLbG1hVs4mPoZ6")


def test_entropy_skips_urls():
    assert rules("see https://docs.google.com/document/d/1qQzX9v8kR3yW2tUiPo7LmNhBcVfGdSaEjK4x5H6T8Y0/edit") == set()


def test_uuid_not_flagged():
    assert rules("note ref AAAA1111-2222-3333-4444-555566667777 done") == set()


def test_labeled_credential_on_next_line():
    text = "Client secret:\n```\na7UU3upfQ92mchze81xNagJtK0lezV9x\n```\n"
    findings = scan_notes([note(text)])
    assert any(f.rule == "Labeled Credential" for f in findings)


def test_partial_match_expands_to_full_token():
    jwt = "eyJhbGciOiJIUzI1NiJ9." + "eyJzdWIiOiIxMjM0NTY3ODkwIn0." + "x" * 50
    findings = scan_notes([note(f"token {jwt} end")])
    assert any(f.secret == jwt for f in findings)


def test_excerpt_never_contains_full_secret():
    findings = scan_notes([note("key AKIAIOSFODNN7EXAMPLE here")])
    for f in findings:
        assert "AKIAIOSFODNN7EXAMPLE" not in f.excerpt


def test_redact_text_replaces_all_and_longest_first():
    n = note("key AKIAIOSFODNN7EXAMPLE here")
    secrets = redaction_map(scan_notes([n]))["N1"]
    redacted = redact_text(n.text, secrets)
    assert "AKIAIOSFODNN7EXAMPLE" not in redacted
    assert "[redacted: AWS Access Key]" in redacted


def test_prose_is_not_flagged():
    assert rules("the wifi password is written on the router downstairs") == set()
