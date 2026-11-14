"""Real embedding provider using OpenAI API."""
import os
from typing import Protocol
from openai import OpenAI


class Embedder(Protocol):
    model_name: str
    dimensions: int

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        ...

    def embed_query(self, question: str) -> list[float]:
        ...


class OpenAIEmbedder:
    """OpenAI embedding adapter with token/cost tracking and strict error propagation."""

    def __init__(self, model_name: str = "text-embedding-3-small", dimensions: int = 1536) -> None:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("Missing OPENAI_API_KEY in environment (.env)")
        self.model_name = model_name
        self.dimensions = dimensions
        self.client = OpenAI(api_key=api_key)
        self.total_tokens_used = 0

    @property
    def estimated_cost_usd(self) -> float:
        return (self.total_tokens_used / 1_000_000) * 0.02

    def embed_documents(self, texts: list[str], batch_size: int = 64) -> list[list[float]]:
        if not texts:
            return []
        all_vectors: list[list[float]] = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            resp = self.client.embeddings.create(input=batch, model=self.model_name)
            if resp.usage:
                self.total_tokens_used += resp.usage.total_tokens
            ordered = sorted(resp.data, key=lambda d: d.index)
            all_vectors.extend([item.embedding for item in ordered])
        return all_vectors

    def embed_query(self, question: str) -> list[float]:
        resp = self.client.embeddings.create(input=[question], model=self.model_name)
        if resp.usage:
            self.total_tokens_used += resp.usage.total_tokens
        return resp.data[0].embedding