"""One-shot fetcher: pulls models.dev/api.json and writes a minimal snapshot
into src/poor_code/provider/_models_snapshot.json.

Run manually when adding support for new models:
    python scripts/generate_models.py

We extract only the fields poor-code uses:
    id, limit.context, limit.output, cost.input, cost.output,
    cost.cache_read, cost.cache_write

models.dev returns: {<provider_id>: {models: {<model_id>: {...}}}}
We flatten to: {<model_id>: ModelMeta-like dict}, keyed by model id.
Provider attribution is dropped because lookup() in registry.py is
model-name-only — provider switching doesn't change context/pricing
for a given model id.
"""
from __future__ import annotations

import json
import urllib.request
from pathlib import Path

URL = "https://models.dev/api.json"
OUT = Path(__file__).parent.parent / "src" / "poor_code" / "provider" / "_models_snapshot.json"


def fetch() -> dict:
    # models.dev rejects the default urllib User-Agent with 403,
    # so we send a browser-style UA.
    req = urllib.request.Request(
        URL,
        headers={"User-Agent": "Mozilla/5.0 (poor-code generate_models)"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def flatten(data: dict) -> dict:
    out: dict[str, dict] = {}
    for provider in data.values():
        models = provider.get("models") or {}
        for model_id, m in models.items():
            limit = m.get("limit") or {}
            cost = m.get("cost") or {}
            entry: dict = {
                "context_size": limit.get("context", 0),
                "max_output": limit.get("output", 0),
            }
            if cost:
                entry["pricing"] = {
                    "input_per_1m": cost.get("input", 0),
                    "output_per_1m": cost.get("output", 0),
                    "cache_read_per_1m": cost.get("cache_read"),
                    "cache_write_per_1m": cost.get("cache_write"),
                }
            out[model_id] = entry
    return out


def main() -> None:
    data = fetch()
    flat = flatten(data)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(flat, indent=2, sort_keys=True))
    print(f"Wrote {len(flat)} model entries to {OUT}")


if __name__ == "__main__":
    main()
