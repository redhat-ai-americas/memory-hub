"""Tier 1: Deterministic regex scanning for secrets and PII."""

import re
from dataclasses import dataclass


@dataclass
class ScanResult:
    matched: bool
    rule_name: str | None = None
    pattern_name: str | None = None
    detail: str | None = None


# Secrets patterns — these should catch common API key formats
# without being so broad that they flag normal text.
SECRET_PATTERNS: dict[str, re.Pattern] = {
    "aws_access_key": re.compile(r"AKIA[0-9A-Z]{16}"),
    "github_token": re.compile(r"gh[ps]_[A-Za-z0-9_]{36,}"),
    "generic_api_key": re.compile(r"sk-[A-Za-z0-9]{32,}"),
    "private_key_header": re.compile(r"-----BEGIN\s+(RSA\s+)?PRIVATE\s+KEY-----"),
    "bearer_token": re.compile(r"Bearer\s+[A-Za-z0-9\-._~+/]+=*", re.IGNORECASE),
    "generic_secret": re.compile(
        r"""(?:password|passwd|pwd|secret|token|api_key|apikey)\s*[:=]\s*['"][^\s'"]{8,}['"]""",
        re.IGNORECASE,
    ),
}

PII_PATTERNS: dict[str, re.Pattern] = {
    "ssn": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    "email": re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"),
    "phone_us": re.compile(r"\b(?:\+1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b"),
}


def scan_content(content: str, pattern_set: str = "all") -> list[ScanResult]:
    """Scan content for secrets and PII patterns.

    Args:
        content: The text to scan.
        pattern_set: Which patterns to run. One of "secrets", "pii", or "all"
            (default). Callers that know they need only one category should pass
            the specific value to avoid running irrelevant patterns.

    Returns a list of ScanResult for each match found. An empty list means clean.
    """
    results = []

    if pattern_set in ("secrets", "all"):
        for name, pattern in SECRET_PATTERNS.items():
            match = pattern.search(content)
            if match:
                matched_text = match.group()
                redacted = matched_text[:4] + "..." + matched_text[-4:] if len(matched_text) > 12 else "***"
                results.append(
                    ScanResult(
                        matched=True,
                        rule_name="secrets_scan",
                        pattern_name=name,
                        detail=f"Content matches {name} pattern ({redacted})",
                    )
                )

    if pattern_set in ("pii", "all"):
        for name, pattern in PII_PATTERNS.items():
            if pattern.search(content):
                results.append(
                    ScanResult(
                        matched=True,
                        rule_name="pii_scan",
                        pattern_name=name,
                        detail=f"Content matches {name} pattern",
                    )
                )

    return results


def scan_with_custom_patterns(content: str, patterns: dict[str, str]) -> list[ScanResult]:
    """Scan content with custom regex patterns from curation rules.

    patterns: mapping of {pattern_name: regex_string}

    Invalid regex strings are silently skipped — a bad rule config should not
    crash the write pipeline.
    """
    results = []
    for name, regex_str in patterns.items():
        try:
            pattern = re.compile(regex_str)
        except re.error:
            continue
        if pattern.search(content):
            results.append(
                ScanResult(
                    matched=True,
                    rule_name="custom_regex",
                    pattern_name=name,
                    detail=f"Content matches custom pattern: {name}",
                )
            )
    return results
