#!/usr/bin/env python3
"""Manual one-shot pipeline trigger."""
import asyncio
import argparse
import structlog
from pipeline.orchestrator import run_pipeline

log = structlog.get_logger()


def _parse_args():
    parser = argparse.ArgumentParser(description="Run KFA media intelligence pipeline")
    parser.add_argument("--date", type=str, default=None,
                        help="Run date YYYY-MM-DD (default: today KST)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Run pipeline but skip email delivery")
    return parser.parse_args()


async def _run():
    args = _parse_args()
    print(f"Starting KFA pipeline: date={args.date or 'today'}, dry_run={args.dry_run}")
    state = await run_pipeline(run_date=args.date, dry_run=args.dry_run)
    print(f"\nPipeline complete!")
    print(f"  Articles collected:  {len(state.get('raw_article_ids', []))}")
    print(f"  Articles analyzed:   {len(state.get('analyzed_article_ids', []))}")
    print(f"  Emails sent:         {state.get('emails_sent', [])}")
    if state.get("report_paths"):
        print(f"  Report HTML:         {state['report_paths'].get('html')}")
        print(f"  Report PDF:          {state['report_paths'].get('pdf')}")
    if state.get("errors"):
        print("\nErrors encountered:")
        for err in state["errors"]:
            print(f"  - {err}")


def cli():
    asyncio.run(_run())


if __name__ == "__main__":
    cli()
