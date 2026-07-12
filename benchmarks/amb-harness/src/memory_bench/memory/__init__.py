from .base import MemoryProvider
from .bm25 import BM25MemoryProvider
from .memoryhub import MemoryHubProvider

REGISTRY: dict[str, type[MemoryProvider]] = {
    "bm25": BM25MemoryProvider,
    "memoryhub": MemoryHubProvider,
}


def get_memory_provider(name: str) -> MemoryProvider:
    if name not in REGISTRY:
        raise ValueError(f"Unknown memory provider: '{name}'. Available: {list(REGISTRY)}")
    return REGISTRY[name]()
