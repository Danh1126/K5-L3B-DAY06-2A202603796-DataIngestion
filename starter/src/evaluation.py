"""Evaluate retrieved evidence and preserve per-query traces."""
import re
from typing import Any


def _norm_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def _is_hit(question: dict[str, Any], hit: dict[str, Any]) -> bool:
    meta = hit.get("metadata", {})
    if meta.get("document_id") != question["gold_source_id"]:
        return False

    # accept any evidence_quote in the alt_evidence_quotes list (if present)
    gold_pages = question["gold_page"]
    if isinstance(gold_pages, int):
        gold_pages = [gold_pages]
    if meta.get("page") not in gold_pages:
        return False

    # accept any evidence_quote in the alt_evidence_quotes list (if present)
    evidences = [question["evidence_quote"]] + question.get("alt_evidence_quotes", [])
    chunk_norm = _norm_ws(hit.get("text", ""))
    return any(_norm_ws(ev) in chunk_norm for ev in evidences if ev)


def evaluate_query(question: dict[str, Any], hits: list[dict[str, Any]], applied_filter: dict[str, Any] | None) -> dict[str, Any]:
    hit_flags = [_is_hit(question, h) for h in hits]
    hit_at_1 = 1 if (hit_flags and hit_flags[0]) else 0
    hit_at_3 = 1 if any(hit_flags[:3]) else 0

    filter_compliant = None
    if applied_filter:
        filter_compliant = all(
            all(h.get("metadata", {}).get(k) == v for k, v in applied_filter.items())
            for h in hits
        )

    return {
        "question_id": question["id"],
        "split": question["split"],
        "type": question.get("type", ""),
        "question": question["question"],
        "applied_filter": applied_filter,
        "filter_compliant": filter_compliant,
        "gold_source_id": question["gold_source_id"],
        "gold_page": question["gold_page"],
        "evidence_quote": question["evidence_quote"],
        "hit_at_1": hit_at_1,
        "hit_at_3": hit_at_3,
        "top_k_hits": hits,
    }


def summarize(traces: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    summary: dict[str, dict[str, Any]] = {}
    for split in ("dev", "test"):
        subset = [t for t in traces if t["split"] == split]
        n = len(subset)
        h1 = sum(t["hit_at_1"] for t in subset)
        h3 = sum(t["hit_at_3"] for t in subset)
        filtered = [t for t in subset if t["applied_filter"]]
        f_ok = sum(1 for t in filtered if t["filter_compliant"])
        summary[split] = {
            "total": n,
            "hit_at_1_count": h1,
            "hit_at_1_rate": round(h1 / n, 4) if n else 0.0,
            "hit_at_3_count": h3,
            "hit_at_3_rate": round(h3 / n, 4) if n else 0.0,
            "filter_queries": len(filtered),
            "filter_compliant_count": f_ok,
        }
    return summary