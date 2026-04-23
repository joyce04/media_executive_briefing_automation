"""Legacy single-org scheduler — kept for backward compat. See pipeline/multi_scheduler.py."""
import asyncio
import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from pipeline.orchestrator import run_pipeline

logger = structlog.get_logger()

_DEFAULT_CRON = "0 6 * * *"   # 06:00 UTC; override via org schedule_cron in DB
_DEFAULT_TZ = "UTC"


async def scheduled_job():
    logger.info("scheduler_job_triggered")
    try:
        await run_pipeline()
    except Exception as e:
        logger.error("scheduler_job_failed", error=str(e))


def start_scheduler(cron: str = _DEFAULT_CRON, timezone: str = _DEFAULT_TZ) -> AsyncIOScheduler:
    minute, hour, dom, month, dow = cron.split()
    scheduler = AsyncIOScheduler(timezone=timezone)
    scheduler.add_job(
        scheduled_job,
        trigger=CronTrigger(
            minute=minute, hour=hour, day=dom, month=month,
            day_of_week=dow, timezone=timezone,
        ),
        id="daily_pipeline",
        name="Daily Media Intelligence Pipeline",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=3600,
    )
    scheduler.start()
    logger.info("scheduler_started", cron=cron, timezone=timezone)
    return scheduler


async def main():
    scheduler = start_scheduler()
    try:
        while True:
            await asyncio.sleep(60)
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()
        logger.info("scheduler_stopped")


if __name__ == "__main__":
    asyncio.run(main())
