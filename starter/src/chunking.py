"""Implement fixed-size and structure-aware chunking."""
from .models import Chunk, DocumentPage


def fixed_size(page: DocumentPage, size: int = 500, overlap: int = 50) -> list[Chunk]:
    """Strategy A: split text into overlapping character windows and retain metadata."""
    if overlap >= size:
        raise ValueError("overlap must be smaller than size")

    text = page.text
    chunks: list[Chunk] = []
    start = 0
    idx = 0
    step = size - overlap

    while start < len(text):
        end = min(start + size, len(text))
        piece = text[start:end].strip()
        if piece:
            chunk_id = f"{page.document_id}::A::p{page.page:03d}::c{idx:03d}"
            meta = dict(page.metadata)
            meta.update({
                "strategy": "A",
                "chunk_index": idx,
                "char_start": start,
                "char_end": end,
            })
            chunks.append(
                Chunk(
                    chunk_id=chunk_id,
                    document_id=page.document_id,
                    source=page.source,
                    page=page.page,
                    text=piece,
                    metadata=meta,
                )
            )
            idx += 1
        if end == len(text):
            break
        start += step

    return chunks


def by_paragraph(page: DocumentPage, max_size: int = 800, strategy_tag: str = "B") -> list[Chunk]:
    """Strategy B/C: group paragraphs up to max_size; split oversized paragraphs cleanly."""
    paragraphs = [p.strip() for p in page.text.split("\n\n") if p.strip()]
    raw_pieces: list[str] = []
    current_group: list[str] = []
    current_len = 0

    for para in paragraphs:
        # if a single paragraph exceeds max_size, split it into smaller pieces
        if len(para) > max_size:
            if current_group:
                raw_pieces.append("\n\n".join(current_group))
                current_group = []
                current_len = 0
            for i in range(0, len(para), max_size - 50):
                sub = para[i : i + max_size].strip()
                if sub:
                    raw_pieces.append(sub)
            continue

        added_len = len(para) + (2 if current_group else 0)
        if current_len + added_len <= max_size:
            current_group.append(para)
            current_len += added_len
        else:
            raw_pieces.append("\n\n".join(current_group))
            current_group = [para]
            current_len = len(para)

    if current_group:
        raw_pieces.append("\n\n".join(current_group))

    chunks: list[Chunk] = []
    for idx, piece in enumerate(raw_pieces):
        chunk_id = f"{page.document_id}::{strategy_tag}::p{page.page:03d}::c{idx:03d}"
        meta = dict(page.metadata)
        meta.update({
            "strategy": strategy_tag,
            "chunk_index": idx,
        })
        chunks.append(
            Chunk(
                chunk_id=chunk_id,
                document_id=page.document_id,
                source=page.source,
                page=page.page,
                text=piece,
                metadata=meta,
            )
        )

    return chunks