"""Run repeatable bilingual intent and order tests without an external model.

Usage: python -m scripts.evaluate
"""
import json
import pathlib
import time
from collections import Counter
from app.engine import Session, route_message

PATH = pathlib.Path(__file__).resolve().parent / "eval_cases.jsonl"


def evaluate():
    cases = [json.loads(line) for line in PATH.read_text(encoding="utf-8").splitlines() if line.strip()]
    counts = Counter()
    failures = []
    total_ms = 0
    for sample in cases:
        started = time.perf_counter()
        answer = route_message(sample["text"], Session())
        total_ms += (time.perf_counter() - started) * 1000
        counts["total"] += 1
        if answer.intent == sample["intent"]:
            counts["correct"] += 1
        else:
            failures.append({"text": sample["text"], "expected": sample["intent"], "actual": answer.intent})
        if sample.get("language") and answer.language != sample["language"]:
            failures.append({"text": sample["text"], "expected_language": sample["language"], "actual_language": answer.language})
        if sample.get("order_id") and answer.order_id != sample["order_id"]:
            failures.append({"text": sample["text"], "expected_order": sample["order_id"], "actual_order": answer.order_id})
    print(json.dumps({"cases": counts["total"], "intent_correct": counts["correct"],
                      "intent_accuracy_pct": round(100 * counts["correct"] / counts["total"], 1),
                      "mean_rule_processing_ms": round(total_ms / counts["total"], 3),
                      "failures": failures}, ensure_ascii=False, indent=2))
    return not failures


if __name__ == "__main__":
    raise SystemExit(0 if evaluate() else 1)
