"""Read and normalize source data from EPUB into >= 30 traceable units (>= 1500 chars each)."""
import json
import re
import unicodedata
from datetime import datetime, timezone
import ebooklib
from ebooklib import epub
from bs4 import BeautifulSoup
from pathlib import Path
from .models import DocumentPage


def normalize_text(text: str) -> str:
    """Normalize Unicode (NFC) and whitespace while preserving paragraph breaks (\n\n)."""
    text = unicodedata.normalize("NFC", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    cleaned = "\n".join(lines)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def load_epub_units(
    path: Path,
    document_id: str,
    source: str,
    target_parts: tuple[str, ...] = ("h-3", "h-4"),
    min_unit_chars: int = 1500,
    manifest_out: Path | None = None,
) -> list[DocumentPage]:
    """Extract chapters from EPUB and split sequentially into traceable units >= 1500 chars."""
    if not path.exists():
        raise FileNotFoundError(f"Corpus file not found: {path}")

    book = epub.read_epub(str(path))
    doc_items = [
        item for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT)
        if any(part in item.get_name() for part in target_parts)
    ]

    if not doc_items:
        raise ValueError(f"No matching XHTML items found for parts: {target_parts}")

    # split each chapter into a block of text, preserving paragraph breaks
    chapter_blocks: list[dict[str, str]] = []
    for item in doc_items:
        part_name = "part_3" if "h-3" in item.get_name() else "part_4"
        soup = BeautifulSoup(item.get_content(), "html.parser")
        current_chapter = "UNKNOWN"
        current_paragraphs: list[str] = []

        for tag in soup.find_all(["h1", "h2", "p"]):
            if tag.name in ("h1", "h2"):
                if current_paragraphs:
                    chapter_blocks.append({
                        "part": part_name,
                        "chapter": current_chapter,
                        "file_item": item.get_name(),
                        "text": normalize_text("\n\n".join(current_paragraphs)),
                    })
                    current_paragraphs = []
                current_chapter = normalize_text(tag.get_text(" ", strip=True))
            elif tag.name == "p":
                p_text = normalize_text(tag.get_text(" ", strip=True))
                if p_text:
                    current_paragraphs.append(p_text)

        if current_paragraphs:
            chapter_blocks.append({
                "part": part_name,
                "chapter": current_chapter,
                "file_item": item.get_name(),
                "text": normalize_text("\n\n".join(current_paragraphs)),
            })

    # chapter_blocks now contains a list of dicts with part, chapter, file_item, and text for each chapter
    pages: list[DocumentPage] = []
    unit_counter = 1

    for block in chapter_blocks:
        paragraphs = [p.strip() for p in block["text"].split("\n\n") if p.strip()]
        chapter_units: list[str] = []
        buf: list[str] = []
        buf_len = 0

        for p in paragraphs:
            buf.append(p)
            buf_len += len(p) + 2
            if buf_len >= min_unit_chars:
                chapter_units.append("\n\n".join(buf))
                buf = []
                buf_len = 0

        # if there are leftover paragraphs that didn't reach the min_unit_chars threshold, append them to the last unit
        if buf:
            leftover = "\n\n".join(buf)
            if chapter_units:
                chapter_units[-1] = chapter_units[-1] + "\n\n" + leftover
            else:
                chapter_units.append(leftover)

        for idx_in_ch, unit_text in enumerate(chapter_units, start=1):
            unit_id = f"{block['chapter'].lower().replace(' ', '_')}_u{idx_in_ch:02d}"
            pages.append(
                DocumentPage(
                    document_id=document_id,
                    source=source,
                    page=unit_counter, 
                    text=unit_text,
                    metadata={
                        "unit_id": unit_id,
                        "chapter": block["chapter"],
                        "part": block["part"],
                        "file_item": block["file_item"],
                        "char_count": len(unit_text),
                    },
                )
            )
            unit_counter += 1

    if manifest_out:
        manifest_out.parent.mkdir(parents=True, exist_ok=True)
        manifest_data = {
            "source_id": document_id,
            "title": "Project Gutenberg EBook #27963 (Selected Parts h-3 & h-4: Chapters XXX - XLII)",
            "source_path_or_url": source,
            "license_or_permission": "Project Gutenberg Public Domain License (verified in h-7.htm.xhtml)",
            "accessed_at": datetime.now(timezone.utc).isoformat(),
            "unit_rule": f"Sequential paragraph-boundary units >= {min_unit_chars} normalized characters; excluded TOC, cover, and license.",
            "total_units": len(pages),
            "total_characters": sum(len(p.text) for p in pages),
            "units": [
                {
                    "page": p.page,
                    "unit_id": p.metadata["unit_id"],
                    "chapter": p.metadata["chapter"],
                    "part": p.metadata["part"],
                    "char_count": p.metadata["char_count"],
                }
                for p in pages
            ],
        }
        manifest_out.write_text(json.dumps(manifest_data, ensure_ascii=False, indent=2), encoding="utf-8")

    return pages