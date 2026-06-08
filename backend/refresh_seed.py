"""Regenerate the committed cold-start scan seed (backend/data/scan.json).

Run on demand by the GitHub Action (.github/workflows/refresh-seed.yml), which
the in-app "scan" button dispatches via the backend. GitHub's runners (7GB RAM)
run the heavy scan the 512MB Render dyno can't; the regenerated seed is committed
and pushed, and Render auto-deploys it so the app serves fresh data.

Exits non-zero WITHOUT writing if the scan yields nothing, so a transient data
outage can never overwrite a good seed with an empty one.

Usage (from the repo root):
    python backend/refresh_seed.py
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

# Make the backend package importable whether run from the repo root or backend/.
BACKEND = Path(__file__).resolve().parent
sys.path.insert(0, str(BACKEND))

import scanner  # noqa: E402  (path set above)
from universe import get_universe  # noqa: E402


def main() -> int:
    # Best-effort: refresh the S&P 500 / Nasdaq-100 constituent list too. It
    # changes rarely, and a Wikipedia hiccup here must not abort the scan, so
    # swallow failures and keep the existing universe seed.
    try:
        universe = get_universe(force=True)
        print(f"universe refreshed: {len(universe)} symbols")
    except Exception as exc:  # noqa: BLE001 - best effort
        print(f"universe refresh skipped: {exc}", file=sys.stderr)

    data = scanner.run_scan(refresh_momentum=True)
    evaluated = int(data.get("evaluated_count", 0)) if data else 0
    if not data or evaluated <= 0:
        print(
            "scan produced no evaluations — leaving the existing seed untouched",
            file=sys.stderr,
        )
        return 1

    seed_path = Path(scanner.SCAN_CACHE_FILE)
    seed_path.parent.mkdir(parents=True, exist_ok=True)
    seed_path.write_text(
        json.dumps({"ts": time.time(), "data": data}, ensure_ascii=False),
        encoding="utf-8",
    )
    top = [t.get("symbol") for t in data.get("top", [])]
    print(f"seed updated: evaluated={evaluated} top={top}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
