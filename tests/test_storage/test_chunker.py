"""Unit tests for the semantic chunker.

Pure function tests — no mocking needed.
"""

import pytest

from memoryhub_core.storage.chunker import (
    _CHARS_PER_TOKEN,
    _DEFAULT_TARGET_TOKENS,
    semantic_chunk,
)

# --- Empty / whitespace input ---

@pytest.mark.parametrize("input_text", ["", "   ", "\n\n\n", None])
def test_empty_or_whitespace_returns_empty(input_text):
    assert semantic_chunk(input_text) == []


# --- Short content ---

def test_short_content_returns_single_chunk():
    text = "This is a short memory."
    chunks = semantic_chunk(text)
    assert len(chunks) == 1
    assert chunks[0] == text


# --- Multiple paragraphs ---

def test_multiple_paragraphs_split_into_chunks():
    # Each paragraph is ~200 chars, target is 256 tokens * 4 = 1024 chars.
    # Two paragraphs fit; third should start a new chunk.
    para = "A" * 500
    text = f"{para}\n\n{para}\n\n{para}"
    chunks = semantic_chunk(text)
    assert len(chunks) == 2
    # First chunk has two paragraphs, second has one
    assert para + "\n\n" + para == chunks[0]
    assert para == chunks[1]


# --- Long paragraph splits on sentences ---

def test_long_paragraph_splits_on_sentences():
    # Build a paragraph of many sentences that exceeds the default max_chars
    sentence = "This is a test sentence with enough words to be meaningful. "
    # ~60 chars per sentence; default max_chars = 1024; need ~20 sentences
    para = sentence * 25  # ~1500 chars, single paragraph (no double newlines)
    chunks = semantic_chunk(para)
    assert len(chunks) > 1
    # Verify all content is preserved (modulo whitespace normalization)
    rejoined = " ".join(" ".join(c.split()) for c in chunks)
    original_normalized = " ".join(para.split())
    assert rejoined == original_normalized


# --- Chunks respect max_chars approximately ---

def test_chunks_respect_max_chars():
    max_chars = int(_DEFAULT_TARGET_TOKENS * _CHARS_PER_TOKEN)
    para = "Word. " * 300  # ~1800 chars
    chunks = semantic_chunk(para)
    for chunk in chunks:
        # Allow some slack — a single sentence can push slightly over
        assert len(chunk) <= max_chars * 1.5, (
            f"Chunk too large: {len(chunk)} chars (max_chars={max_chars})"
        )


# --- Content preservation ---

def test_all_content_preserved():
    paragraphs = [f"Paragraph {i} with some content." for i in range(10)]
    text = "\n\n".join(paragraphs)
    chunks = semantic_chunk(text)

    # Every original paragraph should appear somewhere in the chunks
    rejoined = "\n\n".join(chunks)
    for para in paragraphs:
        assert para in rejoined, f"Lost paragraph: {para}"


# --- Custom target_tokens ---

def test_custom_target_tokens():
    # Very small target → more chunks
    text = "First sentence. Second sentence. Third sentence. Fourth sentence."
    small_chunks = semantic_chunk(text, target_tokens=8)  # 8*4 = 32 chars max
    large_chunks = semantic_chunk(text, target_tokens=256)
    assert len(small_chunks) > len(large_chunks)


# --- Single very long sentence ---

def test_single_long_sentence_becomes_own_chunk():
    # A sentence with no internal boundaries still becomes a chunk
    long_sentence = "A" * 2000  # No periods, no paragraph breaks
    chunks = semantic_chunk(long_sentence)
    assert len(chunks) == 1
    assert chunks[0] == long_sentence
