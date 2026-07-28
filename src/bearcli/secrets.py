"""Best-effort secret detection over note text.

A first line of defense before notes leave the machine via export: curated,
high-signal patterns for structured credentials (token formats, key blocks,
credential assignments). It cannot catch secrets written as prose — for
deeper scanning, run a dedicated tool such as gitleaks over an export.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from bearcli.db import Note

RULES: list[tuple[str, re.Pattern[str]]] = [
    ("private key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY( BLOCK)?-----")),
    ("AWS access key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("GitHub token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{22,})\b")),
    ("GitLab token", re.compile(r"\bglpat-[A-Za-z0-9_-]{20,}\b")),
    ("Slack token", re.compile(r"\bxox[baprs]-[0-9A-Za-z-]{10,}\b")),
    ("Slack webhook", re.compile(r"hooks\.slack\.com/services/T[A-Za-z0-9_/]+")),
    ("Stripe key", re.compile(r"\b[sr]k_(?:live|test)_[0-9a-zA-Z]{20,}\b")),
    ("OpenAI/Anthropic key", re.compile(r"\bsk-(?:ant-|proj-)?[A-Za-z0-9_-]{32,}\b")),
    ("Google API key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("SendGrid key", re.compile(r"\bSG\.[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{16,}\b")),
    ("npm token", re.compile(r"\bnpm_[A-Za-z0-9]{36}\b")),
    ("PyPI token", re.compile(r"\bpypi-AgEI[A-Za-z0-9_-]{20,}\b")),
    ("DigitalOcean token", re.compile(r"\bdop_v1_[a-f0-9]{64}\b")),
    ("JWT", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{5,}\b")),
    (
        "credential assignment",
        re.compile(r"(?i)\b(?:password|passwd|pwd|secret|token|api[_-]?key|apikey)\b\s*[:=]\s*[\"']?[^\s\"']{8,}"),
    ),
]


@dataclass
class SecretFinding:
    note_id: str
    note_title: str
    rule: str
    line: int
    excerpt: str


def _redact(match: str) -> str:
    """Show enough to locate the secret in the note, never the secret itself."""
    return f"{match[:8]}…" if len(match) > 12 else "…"


def scan_notes(notes: list[Note]) -> list[SecretFinding]:
    findings = []
    for note in notes:
        text = note.text or ""
        for rule, pattern in RULES:
            for match in pattern.finditer(text):
                line = text.count("\n", 0, match.start()) + 1
                findings.append(
                    SecretFinding(
                        note_id=note.id,
                        note_title=note.title,
                        rule=rule,
                        line=line,
                        excerpt=_redact(match.group()),
                    )
                )
    return findings
