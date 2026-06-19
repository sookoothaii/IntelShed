#!/usr/bin/env python3
"""Export WorldBase connector manifest to stdout or a file.

Usage (from repo root):
  python scripts/export_connectors.py
  python scripts/export_connectors.py --format yaml --runtime -o backend/data/connectors.yaml
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import connector_registry  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Export connector manifest")
    parser.add_argument("--format", choices=("json", "yaml"), default="json")
    parser.add_argument("--runtime", action="store_true", help="Include feed_cache overlay")
    parser.add_argument("-o", "--output", type=Path, help="Write to file instead of stdout")
    args = parser.parse_args()

    if args.format == "yaml":
        body = connector_registry.export_manifest_yaml(include_runtime=args.runtime)
    else:
        body = connector_registry.export_manifest_json(include_runtime=args.runtime)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(body, encoding="utf-8")
        print(f"Wrote {args.output} ({len(body)} bytes)", file=sys.stderr)
    else:
        sys.stdout.write(body)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
