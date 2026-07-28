"""Secret detection over note text, powered by detect-secrets (Yelp).

A first line of defense before notes leave the machine via export. Everything
runs offline — note content is never sent anywhere. Format detectors cover
known token shapes (AWS, GitHub, Slack, Stripe, OpenAI, private keys, JWTs,
keyword assignments, …) and the entropy detectors catch random-looking
strings with no known format. Secrets written as prose are undetectable; for
deeper auditing run gitleaks over an --allow-secrets export.

Implementation note: detect-secrets' `scan_line` helper is unsuitable — it
enables eager search, which makes entropy plugins report every token — so
plugins are instantiated and run directly, with the heuristic false-positive
filters applied by hand.
"""

from __future__ import annotations

from dataclasses import dataclass

from detect_secrets.core.plugins.util import get_mapping_from_secret_type_to_class
from detect_secrets.filters import heuristic
from detect_secrets.plugins.base import BasePlugin

from bearcli.db import Note

# An IP address in a note is not a credential.
_EXCLUDED_PLUGINS = {"IPPublicDetector"}
_BASE64_ENTROPY_LIMIT = 4.5  # detect-secrets' default
_HEX_ENTROPY_LIMIT = 3.5  # above default (3.0): notes are full of UUID/hash fragments


def _build_plugins() -> list[BasePlugin]:
    plugins: list[BasePlugin] = []
    for cls in get_mapping_from_secret_type_to_class().values():
        name = cls.__name__
        if name in _EXCLUDED_PLUGINS:
            continue
        if name == "Base64HighEntropyString":
            plugins.append(cls(_BASE64_ENTROPY_LIMIT))
        elif name == "HexHighEntropyString":
            plugins.append(cls(_HEX_ENTROPY_LIMIT))
        else:
            plugins.append(cls())
    return plugins


def _is_false_positive(value: str, line: str) -> bool:
    return (
        heuristic.is_potential_uuid(value)
        or heuristic.is_sequential_string(value)
        or heuristic.is_templated_secret(value)
        or heuristic.is_likely_id_string(value, line)
        or heuristic.is_not_alphanumeric_string(value)
    )


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


def scan_notes(notes: list[Note]) -> list[SecretFinding]:
    plugins = _build_plugins()
    findings = []
    for note in notes:
        seen: set[tuple[int, str]] = set()
        for lineno, line in enumerate((note.text or "").splitlines(), start=1):
            for plugin in plugins:
                # The yaml filetype hint makes KeywordDetector accept unquoted
                # `password: value` assignments, which is how notes write them.
                for secret in plugin.analyze_line(filename="note.yaml", line=line, line_number=lineno):
                    value = secret.secret_value or ""
                    if _is_false_positive(value, line) or (lineno, value) in seen:
                        continue
                    seen.add((lineno, value))
                    findings.append(
                        SecretFinding(
                            note_id=note.id,
                            note_title=note.title,
                            rule=secret.type,
                            line=lineno,
                            excerpt=_redact(value),
                            secret=value,
                        )
                    )
    return findings


def redaction_map(findings: list[SecretFinding]) -> dict[str, dict[str, str]]:
    """Per note id, the secret values to replace and the rule that found them."""
    by_note: dict[str, dict[str, str]] = {}
    for finding in findings:
        if finding.secret:
            by_note.setdefault(finding.note_id, {}).setdefault(finding.secret, finding.rule)
    return by_note
