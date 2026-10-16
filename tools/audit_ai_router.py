"""Auditoría offline de recall del router, sin inferencia ni comandos BDS."""
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from gui_backend.services.ai_assistant import score_tools, select_tools


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("datasets", nargs="+", type=Path)
    args = parser.parse_args()
    for path in args.datasets:
        counts, misses = Counter(), defaultdict(list)
        sizes = Counter()
        fallbacks = defaultdict(list)
        fallback_counts = Counter()
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                row = json.loads(line)
                prompt = next(m["content"] for m in row["messages"] if m["role"] == "user")
                calls = next(m for m in row["messages"] if m["role"] == "assistant").get("tool_calls", [])
                expected = calls[0]["function"]["name"] if calls else "no_call"
                names = [t["function"]["name"] for t in select_tools(prompt)]
                sizes[len(names)] += 1
                if len(names) > 4:
                    fallback_counts[expected] += 1
                    if len(fallbacks[expected]) < 15:
                        fallbacks[expected].append(prompt)
                counts[expected] += 1
                if expected != "no_call" and expected not in names:
                    misses[expected].append({"prompt": prompt, "scores": score_tools(prompt)})
        print(json.dumps({"path": str(path), "counts": counts, "miss_counts": {k: len(v) for k, v in misses.items()}, "sizes": sizes, "examples": {k: v[:30] for k, v in misses.items()}, "fallback_counts": fallback_counts, "fallback_examples": fallbacks}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
