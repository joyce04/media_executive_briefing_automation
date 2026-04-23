#!/usr/bin/env python3
"""Reprocess a date range of pipelines."""
import asyncio
import argparse
from datetime import date, timedelta
from pipeline.orchestrator import run_pipeline


def _date_range(start: str, end: str) -> list[str]:
    s = date.fromisoformat(start)
    e = date.fromisoformat(end)
    result = []
    current = s
    while current <= e:
        result.append(current.isoformat())
        current += timedelta(days=1)
    return result


async def _run():
    parser = argparse.ArgumentParser(description="Backfill KFA pipeline for a date range")
    parser.add_argument("--start", required=True, help="Start date YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="End date YYYY-MM-DD")
    parser.add_argument("--dry-run", action="store_true", help="Skip email delivery")
    args = parser.parse_args()

    dates = _date_range(args.start, args.end)
    print(f"Backfilling {len(dates)} dates: {args.start} → {args.end}")

    for d in dates:
        print(f"\n--- Processing {d} ---")
        try:
            await run_pipeline(run_date=d, dry_run=args.dry_run)
            print(f"  ✓ {d} complete")
        except Exception as e:
            print(f"  ✗ {d} failed: {e}")


def cli():
    asyncio.run(_run())


if __name__ == "__main__":
    cli()
