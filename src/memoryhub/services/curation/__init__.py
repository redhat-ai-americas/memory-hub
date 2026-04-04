"""Inline curation pipeline for MemoryHub write operations.

The pipeline runs synchronously inside write_memory before any persistence occurs.
All checks are deterministic — regex in Tier 1, embedding similarity in Tier 2.
No LLM calls happen on the write path.

Primary entry point: run_curation_pipeline
"""

from memoryhub.services.curation.pipeline import run_curation_pipeline
from memoryhub.services.curation.rules import create_rule, load_rules, seed_default_rules
from memoryhub.services.curation.scanner import ScanResult, scan_content, scan_with_custom_patterns
from memoryhub.services.curation.similarity import SimilarityResult, check_similarity, get_similar_memories

__all__ = [
    "ScanResult",
    "SimilarityResult",
    "check_similarity",
    "create_rule",
    "get_similar_memories",
    "load_rules",
    "run_curation_pipeline",
    "scan_content",
    "scan_with_custom_patterns",
    "seed_default_rules",
]
