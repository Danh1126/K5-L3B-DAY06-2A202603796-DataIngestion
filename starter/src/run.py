"""Main entry point for Day 06 Data Ingestion & Benchmark Pipeline."""
import argparse
import csv
import json
import statistics
import time
from pathlib import Path
from dotenv import load_dotenv

from .chunking import by_paragraph, fixed_size
from .embeddings import OpenAIEmbedder
from .evaluation import evaluate_query, summarize
from .ingestion import load_epub_units
from .store import QdrantLocalStore


def main() -> None:
    load_dotenv(".env")
    parser = argparse.ArgumentParser(description="Day 06 Ingestion & Benchmark Pipeline")
    parser.add_argument("--ingest-only", action="store_true", help="Only extract units and export manifest/preview for benchmark authoring")
    args = parser.parse_args()

    epub_path = Path("data/book.epub") if Path("data/book.epub").exists() else Path("../data/book.epub")
    results_dir = Path("results")
    results_dir.mkdir(parents=True, exist_ok=True)

    # 1. Load EPUB and split into traceable units (>= 1500 chars each)
    pages = load_epub_units(
        path=epub_path,
        document_id="gutenberg-27963",
        source="data/book.epub",
        target_parts=("h-3", "h-4"),
        min_unit_chars=1500,
        manifest_out=results_dir / "corpus_manifest.json",
    )
    print(f"[1/4] Loaded {len(pages)} content units (total {sum(len(p.text) for p in pages):,} chars).")
    if len(pages) < 30:
        raise RuntimeError(f"Corpus has only {len(pages)} units; minimum 30 required.")

    # 2. Export text preview for each page to facilitate benchmark question authoring
    preview_path = results_dir / "units_preview.json"
    preview_path.write_text(
        json.dumps(
            [{"page": p.page, "chapter": p.metadata["chapter"], "unit_id": p.metadata["unit_id"], "text": p.text} for p in pages],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    if args.ingest_only:
        print(f"Exported manifest to {results_dir / 'corpus_manifest.json'} and text preview to {preview_path}.")
        print("Next step: Create data/benchmark.json (15 dev + 5 test questions) BEFORE running full evaluation!")
        return

    benchmark_path = Path("data/benchmark.json")
    if not benchmark_path.exists():
        raise FileNotFoundError(
            "Missing data/benchmark.json! Run 'python -m src.run --ingest-only' first, "
            "author >= 20 questions (15 dev / 5 test), and save to starter/data/benchmark.json."
        )

    questions = json.loads(benchmark_path.read_text(encoding="utf-8"))
    print(f"[2/4] Loaded {len(questions)} benchmark questions.")

    embedder = OpenAIEmbedder(model_name="text-embedding-3-small", dimensions=1536)
    store = QdrantLocalStore(storage_path="qdrant_db", dimensions=embedder.dimensions)

    # 3. Build 3 strategies: A (fixed 500/50), B (paragraph max 800, no filter), C (paragraph max 800 + metadata filter)
    chunks_A = [c for p in pages for c in fixed_size(p, size=500, overlap=50)]
    chunks_B = [c for p in pages for c in by_paragraph(p, max_size=800, strategy_tag="B")]
    chunks_C = [c for p in pages for c in by_paragraph(p, max_size=800, strategy_tag="C")]

    strategies = {
        "A": {"chunks": chunks_A, "use_filter": False, "desc": "Fixed-size (500 chars, overlap 50), no filter"},
        "B": {"chunks": chunks_B, "use_filter": False, "desc": "By-paragraph (max 800 chars), no filter"},
        "C": {"chunks": chunks_C, "use_filter": True, "desc": "By-paragraph (max 800 chars) + chapter metadata filter"},
    }

    # 4. Embed query vectors for all questions to be used across all strategies
    q_vectors = {q["id"]: embedder.embed_query(q["question"]) for q in questions}

    all_metrics = {}
    for strat_key, cfg in strategies.items():
        t0 = time.perf_counter()
        tokens_before = embedder.total_tokens_used
        chunks = cfg["chunks"]
        vectors = embedder.embed_documents([c.text for c in chunks])

        # Idempotency check: upsert the same chunks twice and verify the count remains the same
        count_1 = store.upsert(strat_key, chunks, vectors)
        count_2 = store.upsert(strat_key, chunks, vectors)
        assert count_1 == count_2 == len(chunks), f"Duplicate check failed for {strat_key}: {count_1} vs {count_2}"

        elapsed = round(time.perf_counter() - t0, 3)
        tokens_strat = embedder.total_tokens_used - tokens_before
        cost_strat = round((tokens_strat / 1_000_000) * 0.02, 6)
        lengths = [len(c.text) for c in chunks]

        traces = []
        for q in questions:
            applied_filter = q.get("filter") if cfg["use_filter"] else None
            hits = store.search(strat_key, q_vectors[q["id"]], top_k=3, filters=applied_filter)
            traces.append(evaluate_query(q, hits, applied_filter))

        summary = summarize(traces)
        all_metrics[strat_key] = {
            "description": cfg["desc"],
            "chunk_count": len(chunks),
            "min_chunk_chars": min(lengths),
            "median_chunk_chars": int(statistics.median(lengths)),
            "max_chunk_chars": max(lengths),
            "ingest_time_sec": elapsed,
            "tokens_used": tokens_strat,
            "estimated_cost_usd": cost_strat,
            "idempotency_verified": True,
            "metrics": summary,
        }

        trace_file = results_dir / f"trace_strategy_{strat_key}.json"
        trace_file.write_text(json.dumps(traces, ensure_ascii=False, indent=2), encoding="utf-8")
        print(
            f"[3/4] Strategy {strat_key}: {len(chunks)} chunks | {elapsed}s | "
            f"Dev Hit@1={summary['dev']['hit_at_1_count']}/{summary['dev']['total']}, "
            f"Hit@3={summary['dev']['hit_at_3_count']}/{summary['dev']['total']} | "
            f"Test Hit@1={summary['test']['hit_at_1_count']}/{summary['test']['total']}, "
            f"Hit@3={summary['test']['hit_at_3_count']}/{summary['test']['total']}"
        )

    (results_dir / "metrics_summary.json").write_text(json.dumps(all_metrics, ensure_ascii=False, indent=2), encoding="utf-8")

    # 4. Export CSV file to support manual scoring of 3 criteria (Coherence 10 top positions, Metadata & Grounding 5 test questions)
    coherence_csv = results_dir / "manual_coherence_template.csv"
    with coherence_csv.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["sample_page", "strategy", "chunk_id", "chunk_text_preview", "coherence_score_0_1_2", "reason"])
        for sample_page in range(1, 11):
            for strat_key, cfg in strategies.items():
                matching = [c for c in cfg["chunks"] if c.page == sample_page]
                first_chunk = matching[0] if matching else None
                writer.writerow([
                    sample_page,
                    strat_key,
                    first_chunk.chunk_id if first_chunk else "",
                    (first_chunk.text[:250].replace("\n", " ") + "...") if first_chunk else "",
                    "",
                    "",
                ])

    print(f"[4/4] Done! All traces, summary, and manual audit templates saved to {results_dir}/.")


if __name__ == "__main__":
    main()