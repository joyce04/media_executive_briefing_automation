#!/usr/bin/env python3
"""Verify all configured RSS sources are reachable and return articles."""
import asyncio
import sys
from collectors.registry import build_registry


async def _test_all_sources() -> bool:
    collectors = build_registry()
    print(f"Testing {len(collectors)} configured sources...\n")
    total_ok = 0
    total_fail = 0
    for collector in collectors:
        try:
            articles = await collector.collect()
            if articles:
                print(f"  ✓ {collector.source_id}: {len(articles)} articles")
                total_ok += 1
            else:
                print(f"  ✗ {collector.source_id}: 0 articles (empty feed)")
                total_fail += 1
        except Exception as e:
            print(f"  ✗ {collector.source_id}: ERROR — {e}")
            total_fail += 1

    print(f"\nResults: {total_ok} OK, {total_fail} failed")
    return total_fail == 0


def cli():
    success = asyncio.run(_test_all_sources())
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    cli()
