"""Persistent vector store using local Qdrant with Cosine distance and metadata filtering."""
import uuid
from typing import Any
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PointStruct,
    VectorParams,
)
from .models import Chunk


class QdrantLocalStore:
    def __init__(self, storage_path: str, dimensions: int) -> None:
        self.storage_path = storage_path
        self.dimensions = dimensions
        self.client = QdrantClient(path=storage_path)

    def _collection_name(self, strategy: str) -> str:
        return f"day06_strategy_{strategy.lower()}"

    def _deterministic_uuid(self, chunk_id: str) -> str:
        return str(uuid.uuid5(uuid.NAMESPACE_DNS, chunk_id))

    def ensure_collection(self, strategy: str) -> None:
        name = self._collection_name(strategy)
        existing = [c.name for c in self.client.get_collections().collections]
        if name not in existing:
            self.client.create_collection(
                collection_name=name,
                vectors_config=VectorParams(size=self.dimensions, distance=Distance.COSINE),
            )

    def upsert(self, strategy: str, chunks: list[Chunk], vectors: list[list[float]]) -> int:
        """Idempotent upsert: same chunk_id overwrites cleanly; obsolete chunks are pruned."""
        if len(chunks) != len(vectors):
            raise ValueError(f"Mismatch: {len(chunks)} chunks vs {len(vectors)} vectors")
        if vectors and len(vectors[0]) != self.dimensions:
            raise ValueError(f"Expected dim {self.dimensions}, got {len(vectors[0])}")

        self.ensure_collection(strategy)
        name = self._collection_name(strategy)

        # Prune obsolete chunks: if a chunk_id is not in the current batch, delete it from Qdrant
        valid_ids = {self._deterministic_uuid(c.chunk_id) for c in chunks}
        doc_ids = {c.document_id for c in chunks}
        existing_points, _ = self.client.scroll(collection_name=name, limit=10000, with_payload=True)
        obsolete_ids = [
            pt.id for pt in existing_points
            if pt.payload and pt.payload.get("document_id") in doc_ids and str(pt.id) not in valid_ids
        ]
        if obsolete_ids:
            self.client.delete(collection_name=name, points_selector=obsolete_ids)

        points = []
        for chunk, vec in zip(chunks, vectors):
            payload = dict(chunk.metadata)
            payload.update({
                "chunk_id": chunk.chunk_id,
                "document_id": chunk.document_id,
                "source": chunk.source,
                "page": chunk.page,
                "text": chunk.text,
            })
            points.append(
                PointStruct(
                    id=self._deterministic_uuid(chunk.chunk_id),
                    vector=vec,
                    payload=payload,
                )
            )

        if points:
            self.client.upsert(collection_name=name, points=points, wait=True)

        info = self.client.get_collection(collection_name=name)
        return info.points_count or 0

    def search(
        self,
        strategy: str,
        query_vector: list[float],
        top_k: int = 3,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        name = self._collection_name(strategy)
        qdrant_filter = None

        if filters:
            conditions = [
                FieldCondition(key=k, match=MatchValue(value=v))
                for k, v in filters.items()
                if v is not None
            ]
            if conditions:
                qdrant_filter = Filter(must=conditions)

        response = self.client.query_points(
            collection_name=name,
            query=query_vector,
            query_filter=qdrant_filter,
            limit=top_k,
            with_payload=True,
        )

        results = []
        for rank, hit in enumerate(response.points, start=1):
            payload = dict(hit.payload or {})
            text = payload.pop("text", "")
            chunk_id = payload.pop("chunk_id", str(hit.id))
            results.append({
                "rank": rank,
                "chunk_id": chunk_id,
                "score": round(float(hit.score), 6),
                "text": text,
                "metadata": payload,
            })
        return results