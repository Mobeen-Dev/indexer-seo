import json
import uuid
import asyncio
import logging
import logging.handlers
import signal
import sys
from typing import Dict, List, Optional, Set
from datetime import datetime, timezone, timedelta
from collections import defaultdict
from db_model import Auth
import redis.asyncio as redis
from supabase import create_client, Client
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)

from config import (
    settings,
    L1_HASH_PATH,
    L1_STREAM_PREFIX,
)

# ============================================================================
# CONFIGURATION
# ============================================================================
SUPABASE_URL: str = settings.SUPABASE_URL
SUPABASE_KEY: str = settings.SUPABASE_KEY
REDIS_PORT: int = settings.REDIS_PORT
REDIS_PASS: str = settings.REDIS_PASS
REDIS_HOST: str = settings.REDIS_HOST

HASH_PATH: str = L1_HASH_PATH
STREAM_PREFIX = L1_STREAM_PREFIX

# Scheduling configuration
SCHEDULE_INTERVAL_SECONDS = 3600  # Run every hour
MIN_HOURS_BETWEEN_RUNS = 12  # Minimum 12 hours between runs for same shop
MAX_RUNS_PER_DAY = 2  # Maximum runs per shop per day
JOBS_PER_BATCH = 300  # Max jobs to schedule in one batch

# State storage keys
SCHEDULE_STATE_KEY = "scheduler:state"  # Hash: shop -> last_run_timestamp
DAILY_RUN_COUNT_KEY = "scheduler:daily_runs"  # Hash: shop:date -> run_count
SCHEDULER_STATS_KEY = "scheduler:stats"  # Hash: various stats

# Timeouts
SUPABASE_TIMEOUT = 30  # seconds
REDIS_TIMEOUT = 10  # seconds
GRACEFUL_SHUTDOWN_TIMEOUT = 30  # seconds

# ============================================================================
# LOGGING SETUP
# ============================================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.handlers.RotatingFileHandler(
            "scheduler.log", maxBytes=50_000_000, backupCount=5
        ),
    ],
)
logger = logging.getLogger(__name__)

# ============================================================================
# GLOBAL STATE
# ============================================================================
shutdown_event = asyncio.Event()
r: Optional[redis.Redis] = None
supabase: Optional[Client] = None


# ============================================================================
# INITIALIZATION
# ============================================================================
async def init_connections():
    """Initialize all external connections with retry logic."""
    global r, supabase

    # Initialize Redis with connection pool
    logger.info("Initializing Redis connection...")
    r = redis.Redis(
        host=REDIS_HOST,
        port=REDIS_PORT,
        password=REDIS_PASS,
        decode_responses=True,
        socket_connect_timeout=REDIS_TIMEOUT,
        socket_keepalive=True,
        health_check_interval=30,
        max_connections=50,
    )

    # Test Redis connection
    try:
        await r.ping()  # type: ignore
        logger.info("Redis connection established")
    except Exception as e:
        logger.error(f"Failed to connect to Redis: {e}")
        raise

    # Initialize Supabase
    logger.info("Initializing Supabase connection...")
    try:
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
        # Test connection with a simple query
        supabase.table("Auth").select("shop").limit(1).execute()
        logger.info("Supabase connection established")
    except Exception as e:
        logger.error(f"Failed to connect to Supabase: {e}")
        raise


async def cleanup_connections():
    """Cleanup all connections gracefully."""
    global r

    logger.info("Cleaning up connections...")

    if r:
        try:
            await r.aclose()
            logger.info("Redis connection closed")
        except Exception as e:
            logger.error(f"Error closing Redis connection: {e}")


# ============================================================================
# DATA FETCHING
# ============================================================================
@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type((ConnectionError, TimeoutError)),
)
def fetch_active_shops() -> List[str]:
    """
    Fetch all unique active shop names from Supabase.

    Returns:
        List of shop names (strings)
    """
    if supabase is None:
        raise RuntimeError("Supabase connection not initialized")

    try:
        response = supabase.table("Auth").select("shop").execute()
        data = response.data

        if not isinstance(data, list) or not data:
            logger.warning("No shops found in database")
            return []

        shops: List[str] = []

        for row in data:
            if not isinstance(row, dict):
                continue

            shop = row.get("shop")
            if isinstance(shop, str):
                shops.append(shop)

        logger.info(f"Fetched {len(shops)} unique shops from database")
        return shops

    except Exception:
        logger.error("Error fetching shops", exc_info=True)
        raise


# ============================================================================
# SCHEDULING STATE MANAGEMENT
# ============================================================================
async def get_last_run_time(shop: str) -> Optional[datetime]:
    """Get the last run timestamp for a shop."""
    if not r:
        raise RuntimeError("Redis connection not initialized")

    try:
        timestamp_str = await r.hget(SCHEDULE_STATE_KEY, shop)  # type: ignore
        if timestamp_str:
            return datetime.fromisoformat(timestamp_str)
        return None
    except Exception as e:
        logger.error(f"Error getting last run time for {shop}: {e}")
        return None


async def set_last_run_time(shop: str, timestamp: datetime):
    """Set the last run timestamp for a shop."""
    if not r:
        raise RuntimeError("Redis connection not initialized")

    try:
        await r.hset(SCHEDULE_STATE_KEY, shop, timestamp.isoformat())  # type: ignore
    except Exception as e:
        logger.error(f"Error setting last run time for {shop}: {e}")


async def get_daily_run_count(shop: str, date: datetime) -> int:
    """Get the number of times a shop has run today."""
    if not r:
        raise RuntimeError("Redis connection not initialized")

    date_str = date.strftime("%Y-%m-%d")
    key = f"{shop}:{date_str}"

    try:
        count_str = await r.hget(DAILY_RUN_COUNT_KEY, key)  # type: ignore
        return int(count_str) if count_str else 0
    except Exception as e:
        logger.error(f"Error getting daily run count for {shop}: {e}")
        return 0


async def increment_daily_run_count(shop: str, date: datetime):
    """Increment the daily run count for a shop."""
    if not r:
        raise RuntimeError("Redis connection not initialized")

    date_str = date.strftime("%Y-%m-%d")
    key = f"{shop}:{date_str}"

    try:
        await r.hincrby(DAILY_RUN_COUNT_KEY, key, 1)  # type: ignore
        # Set expiration on the daily count hash (keep for 2 days)
        await r.expire(DAILY_RUN_COUNT_KEY, 172800)
    except Exception as e:
        logger.error(f"Error incrementing daily run count for {shop}: {e}")


async def is_shop_eligible(shop: str, now: datetime) -> bool:
    """
    Check if a shop is eligible to run based on:
    1. Minimum 12 hours since last run
    2. Maximum 2 runs per day
    """
    # Check last run time
    last_run = await get_last_run_time(shop)
    if last_run:
        hours_since_last_run = (now - last_run).total_seconds() / 3600
        if hours_since_last_run < MIN_HOURS_BETWEEN_RUNS:
            logger.debug(
                f"Shop {shop} not eligible: Only {hours_since_last_run:.1f} hours "
                f"since last run (min: {MIN_HOURS_BETWEEN_RUNS})"
            )
            return False

    # Check daily run count
    daily_count = await get_daily_run_count(shop, now)
    if daily_count >= MAX_RUNS_PER_DAY:
        logger.debug(
            f"Shop {shop} not eligible: Already ran {daily_count} times today "
            f"(max: {MAX_RUNS_PER_DAY})"
        )
        return False

    return True


# ============================================================================
# JOB SCHEDULING
# ============================================================================
async def schedule_job(
    shop: str,
    action: str = "index.urls",
    priority: str = "normal",
) -> str:
    """
    Schedule a single job for a shop.

    Returns:
        job_id of the scheduled job
    """
    if not r:
        raise RuntimeError("Redis connection not initialized")

    job_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    job = {
        "shop": shop,
        "action": action,
        "priority": priority,
        "scheduled_at": now.isoformat(),
    }

    # Store full job in Hash
    await r.hset(
        f"{HASH_PATH}:{job_id}",
        mapping={
            "data": json.dumps(job),
            "status": "queued",
            "created_at": now.isoformat(),
        },
    )  # type: ignore

    # Set expiration on hash (1 day)
    await r.expire(f"{HASH_PATH}:{job_id}", 87000)

    # Push ONLY routing data to stream
    await r.xadd(
        STREAM_PREFIX,
        {"job_id": job_id, "shop": shop, "action": action},
    )

    logger.info(f"Scheduled job {job_id} for shop {shop}")
    return job_id


async def schedule_eligible_shops(shops: List[str]) -> Dict[str, List[str]]:
    """
    Schedule jobs for all eligible shops.

    Returns:
        Dictionary with 'scheduled' and 'skipped' shop lists
    """
    now = datetime.now(timezone.utc)
    scheduled_shops = []
    skipped_shops = []

    logger.info(f"Evaluating {len(shops)} shops for scheduling...")

    for shop in shops:
        try:
            # Check if shop is eligible
            if await is_shop_eligible(shop, now):
                # Schedule the job
                job_id = await schedule_job(shop)

                # Update state
                await set_last_run_time(shop, now)
                await increment_daily_run_count(shop, now)

                scheduled_shops.append(shop)
                logger.info(f"✓ Scheduled shop: {shop}")
            else:
                skipped_shops.append(shop)
                logger.debug(f"⊘ Skipped shop: {shop} (not eligible)")

        except Exception as e:
            logger.error(f"Error scheduling shop {shop}: {e}", exc_info=True)
            skipped_shops.append(shop)

    return {
        "scheduled": scheduled_shops,
        "skipped": skipped_shops,
    }


# ============================================================================
# STATISTICS
# ============================================================================
async def update_scheduler_stats(result: Dict[str, List[str]]):
    """Update scheduler statistics in Redis."""
    if not r:
        raise RuntimeError("Redis connection not initialized")

    now = datetime.now(timezone.utc)

    stats = {
        "last_run_at": now.isoformat(),
        "last_scheduled_count": str(len(result["scheduled"])),
        "last_skipped_count": str(len(result["skipped"])),
        "total_shops_evaluated": str(len(result["scheduled"]) + len(result["skipped"])),
    }

    try:
        await r.hset(SCHEDULER_STATS_KEY, mapping=stats)  # type: ignore

        # Increment total runs counter
        await r.hincrby(SCHEDULER_STATS_KEY, "total_runs", 1)  # type: ignore

        logger.info(
            f"Stats updated: Scheduled={len(result['scheduled'])}, "
            f"Skipped={len(result['skipped'])}"
        )
    except Exception as e:
        logger.error(f"Error updating scheduler stats: {e}")


async def log_scheduling_summary(result: Dict[str, List[str]]):
    """Log a summary of the scheduling run."""
    separator = "=" * 80

    summary_lines = [
        "",
        separator,
        "SCHEDULING SUMMARY",
        separator,
        f"Timestamp: {datetime.now(timezone.utc).isoformat()}",
        f"Total Shops Evaluated: {len(result['scheduled']) + len(result['skipped'])}",
        f"Jobs Scheduled: {len(result['scheduled'])}",
        f"Shops Skipped: {len(result['skipped'])}",
        separator,
    ]

    if result["scheduled"]:
        summary_lines.append("Scheduled Shops:")
        for shop in result["scheduled"][:10]:  # Show first 10
            summary_lines.append(f"  ✓ {shop}")
        if len(result["scheduled"]) > 10:
            summary_lines.append(f"  ... and {len(result['scheduled']) - 10} more")

    summary_lines.append(separator)

    summary = "\n".join(summary_lines)
    print(summary)
    logger.info(
        f"Scheduling cycle completed: {len(result['scheduled'])} jobs scheduled"
    )


# ============================================================================
# CLEANUP TASKS
# ============================================================================
async def cleanup_old_state():
    """Clean up old state data to prevent unbounded growth."""
    if not r:
        raise RuntimeError("Redis connection not initialized")

    try:
        now = datetime.now(timezone.utc)
        cutoff_date = now - timedelta(days=2)

        # Clean up daily run counts older than 2 days
        all_keys = await r.hkeys(DAILY_RUN_COUNT_KEY)  # type: ignore
        removed_count = 0

        for key in all_keys:
            # Key format: "shop:YYYY-MM-DD"
            try:
                date_str = key.split(":")[-1]
                key_date = datetime.strptime(date_str, "%Y-%m-%d")

                if key_date.replace(tzinfo=timezone.utc) < cutoff_date:
                    await r.hdel(DAILY_RUN_COUNT_KEY, key)  # type: ignore
                    removed_count += 1
            except Exception as e:
                logger.warning(f"Error parsing date from key {key}: {e}")
                continue

        if removed_count > 0:
            logger.info(f"Cleaned up {removed_count} old daily run count entries")

    except Exception as e:
        logger.error(f"Error during cleanup: {e}", exc_info=True)


# ============================================================================
# MAIN SCHEDULING LOOP
# ============================================================================
async def scheduling_cycle():
    """Execute one scheduling cycle."""
    cycle_start = datetime.now(timezone.utc)
    logger.info("Starting scheduling cycle...")

    try:
        # Fetch active shops from Supabase
        shops = await asyncio.to_thread(fetch_active_shops)

        if not shops:
            logger.warning("No shops to schedule")
            return

        # Schedule eligible shops
        result = await schedule_eligible_shops(shops)

        # Update statistics
        await update_scheduler_stats(result)

        # Log summary
        await log_scheduling_summary(result)

        # Periodic cleanup (every cycle)
        await cleanup_old_state()

        cycle_duration = (datetime.now(timezone.utc) - cycle_start).total_seconds()
        logger.info(f"Scheduling cycle completed in {cycle_duration:.2f}s")

    except Exception as e:
        logger.error(f"Error in scheduling cycle: {e}", exc_info=True)


async def main_loop():
    """Main loop that runs scheduling cycles at regular intervals."""
    logger.info(
        f"Scheduler started. Running every {SCHEDULE_INTERVAL_SECONDS}s "
        f"({SCHEDULE_INTERVAL_SECONDS / 3600:.1f} hours)"
    )

    # Run first cycle immediately
    await scheduling_cycle()

    # Then run at regular intervals
    while not shutdown_event.is_set():
        try:
            # Wait for next interval or shutdown
            await asyncio.wait_for(
                shutdown_event.wait(), timeout=SCHEDULE_INTERVAL_SECONDS
            )
            # If we reach here, shutdown was triggered
            break
        except asyncio.TimeoutError:
            # Timeout means it's time for next cycle
            if not shutdown_event.is_set():
                await scheduling_cycle()

    logger.info("Main loop exiting due to shutdown event")


# ============================================================================
# SIGNAL HANDLERS
# ============================================================================
def setup_signal_handlers(loop):
    """Setup graceful shutdown on SIGTERM and SIGINT."""

    def signal_handler(sig, frame):
        logger.info(f"Received signal {sig}, initiating graceful shutdown...")
        shutdown_event.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, signal_handler)


# ============================================================================
# GRACEFUL SHUTDOWN
# ============================================================================
async def graceful_shutdown():
    """Gracefully shutdown the scheduler."""
    logger.info("Starting graceful shutdown...")

    # Cleanup connections
    await cleanup_connections()

    logger.info("Graceful shutdown complete")


# ============================================================================
# MANUAL TRIGGER (for testing)
# ============================================================================
async def manual_trigger(shop: str):
    """Manually trigger a job for a specific shop (bypass eligibility checks)."""
    if not r:
        raise RuntimeError("Redis connection not initialized")

    logger.info(f"Manual trigger for shop: {shop}")

    try:
        await init_connections()
        job_id = await schedule_job(shop)
        now = datetime.now(timezone.utc)
        await set_last_run_time(shop, now)
        await increment_daily_run_count(shop, now)
        logger.info(f"✓ Manually scheduled job {job_id} for shop {shop}")
    except Exception as e:
        logger.error(f"Error in manual trigger: {e}", exc_info=True)
    finally:
        await cleanup_connections()


# ============================================================================
# MAIN ENTRY POINT
# ============================================================================
async def main():
    """Main entry point with full lifecycle management."""
    try:
        # Initialize connections
        await init_connections()

        # Run main loop
        await main_loop()

    except Exception as e:
        logger.critical(f"Fatal error in main: {e}", exc_info=True)
        sys.exit(1)
    finally:
        await graceful_shutdown()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Job Scheduler")
    parser.add_argument(
        "--manual",
        type=str,
        help="Manually trigger a job for a specific shop",
        metavar="SHOP",
    )
    parser.add_argument(
        "--once", action="store_true", help="Run scheduling cycle once and exit"
    )

    args = parser.parse_args()

    try:
        if args.manual:
            # Manual trigger mode
            asyncio.run(manual_trigger(args.manual))
        elif args.once:
            # Run once mode
            async def run_once():
                try:
                    await init_connections()
                    await scheduling_cycle()
                finally:
                    await cleanup_connections()

            asyncio.run(run_once())
        else:
            # Normal continuous mode
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            setup_signal_handlers(loop)
            loop.run_until_complete(main())
    except KeyboardInterrupt:
        logger.info("Scheduler stopped by keyboard interrupt")
    except Exception as e:
        logger.critical(f"Unhandled exception: {e}", exc_info=True)
        sys.exit(1)
    finally:
        logger.info("Scheduler shutdown complete")
