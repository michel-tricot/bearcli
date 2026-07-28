"""Secret detection over note text, powered by detect-secrets (Yelp) plus
note-specific detectors.

A first line of defense before notes leave the machine via export. Everything
runs offline — note content is never sent anywhere. detect-secrets provides
the format detectors (AWS, GitHub, Slack, Stripe, private keys, JWTs, keyword
assignments, …); two gaps matter for prose notes and are covered here:

- detect-secrets' entropy plugins only match *quoted* strings, which pasted
  keys in notes never are — so unquoted token runs get their own entropy scan.
- Credentials in notes often sit on the line *below* a label ("Client
  secret:" then the value, often inside a code fence) — a look-ahead rule
  catches those.

Secrets written as prose are still undetectable; for deeper auditing run
gitleaks over an --allow-secrets export.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

from detect_secrets.core.plugins.util import get_mapping_from_secret_type_to_class
from detect_secrets.filters import heuristic
from detect_secrets.plugins.base import BasePlugin

from bearcli.db import Note

# IPPublicDetector: an IP address in a note is not a credential.
# The entropy plugins only match quoted strings — replaced by _scan_entropy.
_EXCLUDED_PLUGINS = {"IPPublicDetector", "Base64HighEntropyString", "HexHighEntropyString"}

_BASE64_ENTROPY_LIMIT = 4.5  # detect-secrets' default
_HEX_ENTROPY_LIMIT = 3.5  # above default (3.0): notes are full of UUID/hash fragments

# A contiguous credential-looking run: base64/urlsafe chars plus the '.' that
# joins JWT segments. 20+ chars keeps ordinary words and short ids out.
_TOKEN_RUN = re.compile(r"[A-Za-z0-9+/\-_=.]{20,}")
_HEX_ONLY = re.compile(r"^[0-9a-fA-F]+$")

# "Client secret:" / "Access token" style label with nothing after it — the
# value is expected on the next content line (code fences skipped).
_LABEL_ONLY = re.compile(
    r"(?i)^\s*\**(?:client\s+secret|secret\s+access\s+key|access\s+token|auth\s+token|refresh\s+token"
    r"|api\s*-?\s*key|access\s+key|private\s+key|secret|password|passwd|pwd|token)\s*\**\s*[:=]?\s*$"
)
_FENCE = re.compile(r"^\s*(?:```|~~~)")
_TRIM_PUNCT = "()[]{}<>«»\"'`,;|"


def _build_plugins() -> list[BasePlugin]:
    return [cls() for cls in get_mapping_from_secret_type_to_class().values() if cls.__name__ not in _EXCLUDED_PLUGINS]


def _entropy(value: str) -> float:
    counts = {char: value.count(char) for char in set(value)}
    return -sum(n / len(value) * math.log2(n / len(value)) for n in counts.values())


def _is_false_positive(value: str, line: str) -> bool:
    return (
        heuristic.is_potential_uuid(value)
        or heuristic.is_sequential_string(value)
        or heuristic.is_templated_secret(value)
        or heuristic.is_likely_id_string(value, line)
        or heuristic.is_not_alphanumeric_string(value)
    )


def _expand_to_token(line: str, value: str) -> str:
    """Grow a detected value to the full unbroken token around it.

    Format detectors can match only part of a longer credential (a JWT's
    first two segments, say); redacting the partial match would leave the
    rest behind.
    """
    start = line.find(value)
    if start < 0:
        return value
    end = start + len(value)
    while start > 0 and not line[start - 1].isspace():
        start -= 1
    while end < len(line) and not line[end].isspace():
        end += 1
    return line[start:end].strip(_TRIM_PUNCT)


def _in_url(line: str, start: int) -> bool:
    """Whether the token starting at `start` is part of a URL.

    Long ids inside links (Google Docs, Notion, …) are high-entropy but are
    shareable references, not credentials — flagging them would drown real
    findings. Token-bearing URLs with known formats (Slack webhooks, …) are
    still caught by their format detectors.
    """
    token_start = start
    while token_start > 0 and not line[token_start - 1].isspace():
        token_start -= 1
    return "://" in line[token_start : start + 3]


def _scan_entropy(line: str) -> list[str]:
    hits = []
    for match in _TOKEN_RUN.finditer(line):
        if _in_url(line, match.start()):
            continue
        value = match.group().strip(_TRIM_PUNCT + ".=")
        limit = _HEX_ENTROPY_LIMIT if _HEX_ONLY.fullmatch(value) else _BASE64_ENTROPY_LIMIT
        if len(value) >= 20 and _entropy(value) >= limit:
            hits.append(match.group())
    return hits


def _labeled_value(lines: list[str], label_index: int) -> tuple[int, str] | None:
    """The first content line after a bare credential label, if it looks like a value."""
    for offset in range(1, 4):
        index = label_index + offset
        if index >= len(lines):
            return None
        candidate = lines[index].strip()
        if not candidate or _FENCE.match(candidate):
            continue
        candidate = candidate.strip(_TRIM_PUNCT)
        if " " not in candidate and 8 <= len(candidate) <= 200:
            return index, candidate
        return None
    return None


@dataclass
class SecretFinding:
    note_id: str
    note_title: str
    rule: str
    line: int
    excerpt: str
    secret: str  # raw value, for redaction only — never print this


def _redact(value: str) -> str:
    """Show enough to locate the secret in the note, never the secret itself."""
    return f"{value[:8]}…" if len(value) > 12 else "…"


def _scan_note(note: Note, plugins: list[BasePlugin]) -> list[SecretFinding]:
    lines = list((note.text or "").splitlines())
    seen: set[str] = set()
    findings: list[SecretFinding] = []

    def add(lineno: int, value: str, rule: str) -> None:
        if value and value not in seen and not _is_false_positive(value, lines[lineno - 1]):
            seen.add(value)
            findings.append(
                SecretFinding(
                    note_id=note.id,
                    note_title=note.title,
                    rule=rule,
                    line=lineno,
                    excerpt=_redact(value),
                    secret=value,
                )
            )

    for lineno, line in enumerate(lines, start=1):
        for plugin in plugins:
            # The yaml filetype hint makes KeywordDetector accept unquoted
            # `password: value` assignments, which is how notes write them.
            for secret in plugin.analyze_line(filename="note.yaml", line=line, line_number=lineno):
                add(lineno, _expand_to_token(line, secret.secret_value or ""), secret.type)
        for value in _scan_entropy(line):
            add(lineno, value, "High Entropy String")
        if _LABEL_ONLY.match(line):
            if labeled := _labeled_value(lines, lineno - 1):
                value_index, value = labeled
                add(value_index + 1, value, "Labeled Credential")
    return findings


def scan_notes(notes: list[Note]) -> list[SecretFinding]:
    plugins = _build_plugins()
    findings = []
    for note in notes:
        findings.extend(_scan_note(note, plugins))
    return findings


def redaction_map(findings: list[SecretFinding]) -> dict[str, dict[str, str]]:
    """Per note id, the secret values to replace and the rule that found them."""
    by_note: dict[str, dict[str, str]] = {}
    for finding in findings:
        if finding.secret:
            by_note.setdefault(finding.note_id, {}).setdefault(finding.secret, finding.rule)
    return by_note
