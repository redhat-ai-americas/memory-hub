"""Semantic chunker for oversized memory content.

Splits text into chunks at paragraph and sentence boundaries,
targeting ~256 tokens per chunk for embedding with all-MiniLM-L6-v2.
"""

import re

# Conservative estimate matching _CHARS_PER_TOKEN in search_memory.py
_CHARS_PER_TOKEN: float = 4.0
_DEFAULT_TARGET_TOKENS: int = 256

# Sentence boundary: period, question mark, or exclamation followed by
# whitespace or end of string. Lookbehind keeps the punctuation with
# the preceding sentence.
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")


def semantic_chunk(
    content: str,
    target_tokens: int = _DEFAULT_TARGET_TOKENS,
) -> list[str]:
    """Split content into semantically coherent chunks.

    Strategy:
    1. Split on paragraph boundaries (double newline).
    2. If a paragraph exceeds the target, split on sentence boundaries.
    3. Greedily accumulate units until the next would exceed the target.

    Returns a list of non-empty chunk strings. A single-chunk result means
    the content was small enough to fit in one chunk (caller should skip
    creating chunk children in this case).
    """
    if not content or not content.strip():
        return []

    max_chars = int(target_tokens * _CHARS_PER_TOKEN)

    # Step 1: split into paragraphs
    paragraphs = re.split(r"\n\n+", content.strip())

    # Step 2: split oversized paragraphs into sentences
    units: list[str] = []
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        if len(para) <= max_chars:
            units.append(para)
        else:
            sentences = _SENTENCE_RE.split(para)
            units.extend(s.strip() for s in sentences if s.strip())

    if not units:
        return []

    # Step 3: greedily accumulate into chunks
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    for unit in units:
        unit_len = len(unit)
        # separator length: "\n\n" between units in a chunk
        sep_len = 2 if current else 0

        if current and (current_len + sep_len + unit_len) > max_chars:
            chunks.append("\n\n".join(current))
            current = [unit]
            current_len = unit_len
        else:
            current.append(unit)
            current_len += sep_len + unit_len

    if current:
        chunks.append("\n\n".join(current))

    return chunks
