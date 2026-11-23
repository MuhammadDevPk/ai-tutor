import os
from typing import Any, Protocol


class BaseEmbedder(Protocol):
    """Protocol for embedding providers so tests can easily substitute fakes."""

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        ...


class FastEmbedder:
    """CPU-batched text embedder using fastembed with BAAI/bge-small-en-v1.5."""

    def __init__(
        self,
        model_name: str = "BAAI/bge-small-en-v1.5",
        batch_size: int = 32,
    ):
        self.model_name = model_name
        self.batch_size = batch_size
        self._model: Any = None

    def _get_model(self) -> Any:
        if self._model is None:
            # Defensive clean for httpx IPv6 port parsing bug with no_proxy
            for var in ("NO_PROXY", "no_proxy"):
                val = os.environ.get(var)
                if val:
                    os.environ[var] = ",".join(
                        p.strip() for p in val.split(",") if ":" not in p and p.strip()
                    )
            from fastembed import TextEmbedding

            self._model = TextEmbedding(model_name=self.model_name)
        return self._model

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        model = self._get_model()
        generator = model.embed(texts, batch_size=self.batch_size)
        return [emb.tolist() for emb in generator]


class FakeEmbedder:
    """Deterministic fake embedder producing zero vectors of specified dimension."""

    def __init__(self, dim: int = 384):
        self.dim = dim

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [[0.0] * self.dim for _ in texts]
