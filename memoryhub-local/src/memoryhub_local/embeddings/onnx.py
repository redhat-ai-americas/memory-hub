"""ONNX-based embedding service using Granite embedding model."""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

import numpy as np
import onnxruntime as ort
from transformers import AutoTokenizer

from memoryhub_local.embeddings.base import EmbeddingService

logger = logging.getLogger(__name__)

REPO_ID = "onnx-community/granite-embedding-small-english-r2-ONNX"
MODEL_DIR_NAME = "granite-embedding-small-english-r2-onnx"
MODEL_FILENAME = "model_quantized.onnx"

_REQUIRED_FILES = [
    "onnx/model_quantized.onnx",
    "onnx/model_quantized.onnx_data",
    "tokenizer.json",
    "tokenizer_config.json",
    "config.json",
    "special_tokens_map.json",
]


def get_default_model_dir() -> Path:
    """Return the default model storage directory."""
    xdg_data = os.environ.get("XDG_DATA_HOME")
    if xdg_data:
        base = Path(xdg_data)
    else:
        base = Path.home() / ".local" / "share"
    return base / "memoryhub" / "models" / MODEL_DIR_NAME


def is_model_downloaded(model_dir: Path | None = None) -> bool:
    """Check if the ONNX model files are present."""
    if model_dir is None:
        model_dir = get_default_model_dir()
    return (model_dir / "onnx" / MODEL_FILENAME).exists()


def download_model(model_dir: Path | None = None) -> Path:
    """Download the ONNX model from HuggingFace Hub.

    Downloads individual files to avoid pulling the full repo.
    Shows progress via huggingface_hub's built-in progress bars (to stderr).
    """
    from huggingface_hub import hf_hub_download

    if model_dir is None:
        model_dir = get_default_model_dir()
    model_dir.mkdir(parents=True, exist_ok=True)

    print(  # noqa: T201
        f"Downloading embedding model ({REPO_ID})...",
        file=sys.stderr,
    )

    for repo_path in _REQUIRED_FILES:
        target = model_dir / repo_path
        if target.exists():
            continue
        logger.info("Downloading %s -> %s", repo_path, target)
        hf_hub_download(
            repo_id=REPO_ID,
            filename=repo_path,
            local_dir=str(model_dir),
        )

    print("Model downloaded successfully.", file=sys.stderr)  # noqa: T201
    return model_dir


class OnnxEmbeddingService(EmbeddingService):
    """Embedding service using ONNX Runtime with Granite embedding model.

    Generates 384-dimensional embeddings using CLS pooling and L2 normalization.
    Inference runs in a thread executor to avoid blocking the async event loop.
    """

    def __init__(self, model_dir: Path):
        model_path = model_dir / "onnx" / MODEL_FILENAME
        if not model_path.exists():
            raise FileNotFoundError(
                f"ONNX model not found at {model_path}. "
                "Run 'memoryhub doctor' or start the server to download it."
            )

        sess_options = ort.SessionOptions()
        sess_options.inter_op_num_threads = 1
        sess_options.intra_op_num_threads = 2

        self._session = ort.InferenceSession(
            str(model_path),
            sess_options,
            providers=["CPUExecutionProvider"],
        )
        self._tokenizer = AutoTokenizer.from_pretrained(str(model_dir))
        self._model_dir = model_dir

    def _embed_sync(self, text: str) -> list[float]:
        inputs = self._tokenizer(
            text,
            padding=True,
            truncation=True,
            max_length=8192,
            return_tensors="np",
        )
        input_feed = {
            k: v for k, v in inputs.items()
            if k in ("input_ids", "attention_mask")
        }
        outputs = self._session.run(None, input_feed)
        embedding = outputs[0][0, 0, :]
        norm = np.linalg.norm(embedding)
        if norm > 0:
            embedding = embedding / norm
        return embedding.tolist()

    def _embed_batch_sync(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        inputs = self._tokenizer(
            texts,
            padding=True,
            truncation=True,
            max_length=8192,
            return_tensors="np",
        )
        input_feed = {
            k: v for k, v in inputs.items()
            if k in ("input_ids", "attention_mask")
        }
        outputs = self._session.run(None, input_feed)
        embeddings = outputs[0][:, 0, :]
        norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
        norms = np.where(norms > 0, norms, 1.0)
        embeddings = embeddings / norms
        return embeddings.tolist()

    async def embed(self, text: str) -> list[float]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._embed_sync, text)

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._embed_batch_sync, texts)
