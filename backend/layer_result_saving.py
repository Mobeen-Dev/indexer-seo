import json
import uuid
import socket
import asyncio
import logging
import logging.handlers
import signal
import sys
import os
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any

from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)

import redis.asyncio as redis

from db import db_session, test_db_connection
from db_model import UrlEntry, UrlStatus
from config import (
    settings,
    L3_GROUP,
    L3_HASH_PATH,
    L3_JOB_LIMIT,
    L3_STREAM_PREFIX,
)

# ============================================================================
# CONFIGURATION
# ============================================================================
REDIS_PORT: int = settings.REDIS_PORT
REDIS_PASS: str = settings.REDIS_PASS
REDIS_HOST: str = settings.REDIS_HOST

HASH_PATH: str = L3_HASH_PATH
STREAM_PREFIX = L3_STREAM_PREFIX

JOB_LIMIT = asyncio.Semaphore(L3_JOB_LIMIT)
GROUP = L3_GROUP
CONSUMER = f"{socket.gethostname()}-{uuid.uuid4().hex[:8]}"  # Unique consumer ID

LOG_FILE = os.path.join("./logs", "worker_l3.log")


# Timeouts
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
            LOG_FILE, maxBytes=50_000_000, backupCount=5
        ),
    ],
)
logger = logging.getLogger(__name__)

# ============================================================================
# GLOBAL STATE
# ============================================================================
shutdown_event = asyncio.Event()
active_tasks: set = set()
r: Optional[redis.Redis] = None


# ============================================================================
# INITIALIZATION
# ============================================================================
async def init_connections():
    """Initialize Redis connection with retry logic."""
    global r

    logger.info("Initializing Redis connection...")
    r = redis.Redis(
        host=REDIS_HOST,
        port=REDIS_PORT,
        password=REDIS_PASS,
        decode_responses=True,
        socket_connect_timeout=REDIS_TIMEOUT,
        socket_keepalive=True,
        health_check_interval=30,
        max_connections=50,  # Connection pool
    )

    # Test Redis connection
    try:
        await r.ping()  # type: ignore
        logger.info("Redis connection established")
    except Exception as e:
        logger.error(f"Failed to connect to Redis: {e}")
        raise

    # Validate database connectivity
    logger.info("Validating PostgreSQL connection...")
    try:
        await asyncio.to_thread(test_db_connection)
        logger.info("PostgreSQL connection established")
    except Exception as e:
        logger.error(f"Failed to connect to PostgreSQL: {e}")
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
# URL EXTRACTION
# ============================================================================


def get_successful_google_urls(google: Dict[str, Any]) -> List[str]:
    """
    Returns URLs successfully updated by Google indexing.
    """
    if not google.get("executed") or not google.get("success"):
        return []

    results = google.get("result", {}).get("results", {}).get("results", [])

    successful_urls = [
        item["url"]
        for item in results
        if item.get("status") == "success" and item.get("http_status") == 200
    ]

    return successful_urls


def get_successful_bing_urls(bing: Dict[str, Any]) -> List[str]:
    """
    Returns URLs successfully updated by Bing indexing.
    """
    if not bing.get("executed") or not bing.get("success"):
        return []

    batches = bing.get("result", {}).get("results", {}).get("results", [])

    successful_urls: List[str] = []

    for batch in batches:
        if batch.get("status") == "success" and batch.get("http_status") == 200:
            successful_urls.extend(batch.get("urls", []))

    return successful_urls


# ============================================================================
# UPDATE DATABASE STATUS
# ============================================================================
def split_google_bing_urls(google_urls: list[str], bing_urls: list[str]):
    google_set = set(google_urls)
    bing_set = set(bing_urls)

    both = list(google_set & bing_set)
    google_only = list(google_set - bing_set)
    bing_only = list(bing_set - google_set)

    return both, google_only, bing_only


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=4, max=10),
    retry=retry_if_exception_type((ConnectionError, TimeoutError)),
)
def update_google_and_bing(shop: str, urls: list[str]):
    if not urls:
        return 0

    with db_session() as session:
        updated = (
            session.query(UrlEntry)
            .filter(UrlEntry.shop == shop, UrlEntry.webUrl.in_(urls))
            .update(
                {
                    UrlEntry.isGoogleIndexed: True,
                    UrlEntry.isBingIndexed: True,
                    UrlEntry.status: UrlStatus.COMPLETED,
                    UrlEntry.lastIndexedAt: datetime.now(timezone.utc),
                },
                synchronize_session=False,
            )
        )
    return updated


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=4, max=10),
    retry=retry_if_exception_type((ConnectionError, TimeoutError)),
)
def update_google_only(shop: str, urls: list[str]):
    if not urls:
        return 0

    with db_session() as session:
        updated = (
            session.query(UrlEntry)
            .filter(
                UrlEntry.shop == shop,
                UrlEntry.isGoogleIndexed.is_(False),
                UrlEntry.webUrl.in_(urls),
            )
            .update(
                {
                    UrlEntry.isGoogleIndexed: True,
                    UrlEntry.lastIndexedAt: datetime.now(timezone.utc),
                },
                synchronize_session=False,
            )
        )
    return updated


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=4, max=10),
    retry=retry_if_exception_type((ConnectionError, TimeoutError)),
)
def update_bing_only(shop: str, urls: list[str]):
    if not urls:
        return 0

    with db_session() as session:
        updated = (
            session.query(UrlEntry)
            .filter(
                UrlEntry.shop == shop,
                UrlEntry.isBingIndexed.is_(False),
                UrlEntry.webUrl.in_(urls),
            )
            .update(
                {
                    UrlEntry.isBingIndexed: True,
                },
                synchronize_session=False,
            )
        )
    return updated


def update_indexing_results(shop: str, google_urls, bing_urls):
    both, google_only, bing_only = split_google_bing_urls(google_urls, bing_urls)

    update_google_and_bing(shop, both)
    update_google_only(shop, google_only)
    update_bing_only(shop, bing_only)


# ============================================================================
# JOB PROCESSING
# ============================================================================
async def process_job(job_id: str, job: dict, stream_name: str, msg_id: str):
    """Process a single job - print results and acknowledge."""
    if not r:
        raise RuntimeError("Redis connection not initialized")

    async with JOB_LIMIT:
        start_time = datetime.now(timezone.utc)
        logger.info(f"Processing job {job_id}")

        try:
            # Validate job structure
            shop = job.get("shop")
            if not shop:
                logger.error(f"Job {job_id}: Missing 'shop' field")
                await r.xack(stream_name, GROUP, msg_id)
                return

            # Process the results
            # print_job_results(job_id, job)
            google = job.get("google", {})
            google_urls = get_successful_google_urls(google)
            bing = job.get("bing", {})
            bing_urls = get_successful_bing_urls(bing)

            await asyncio.to_thread(update_indexing_results, shop, google_urls, bing_urls)

            # Update job status in hash
            processing_time = (datetime.now(timezone.utc) - start_time).total_seconds()

            await r.hset(
                f"{HASH_PATH}:{job_id}",
                mapping={
                    "status": "completed",
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                    "processing_time_seconds": str(processing_time),
                    "printed": "true",
                },
            )  # type: ignore

            # Set expiration on completed job (7 days)
            await r.expire(f"{HASH_PATH}:{job_id}", 86400)

            # ACK message
            await r.xack(stream_name, GROUP, msg_id)

            logger.info(
                f"Job {job_id} completed successfully in {processing_time:.2f}s"
            )

        except asyncio.CancelledError:
            logger.warning(f"Job {job_id} cancelled during shutdown")
            raise
        except Exception as e:
            logger.error(f"Job {job_id} failed: {e}", exc_info=True)

            # Mark job as failed
            try:
                await r.hset(
                    f"{HASH_PATH}:{job_id}",
                    mapping={
                        "status": "failed",
                        "failed_at": datetime.now(timezone.utc).isoformat(),
                        "error": str(e)[:500],  # Truncate error message
                    },
                )  # type: ignore
                await r.expire(f"{HASH_PATH}:{job_id}", 86400)
            except Exception as redis_error:
                logger.error(f"Failed to update job status: {redis_error}")

            # ACK to prevent reprocessing
            await r.xack(stream_name, GROUP, msg_id)


# ============================================================================
# STREAM SETUP
# ============================================================================
async def setup_groups():
    """Ensure consumer group exists for the stream."""
    if not r:
        raise RuntimeError("Redis connection not initialized")

    try:
        await r.xgroup_create(STREAM_PREFIX, GROUP, id="0", mkstream=True)
        logger.info(
            f"Consumer group '{GROUP}' created/verified for stream '{STREAM_PREFIX}'"
        )
    except redis.ResponseError as e:
        if "BUSYGROUP" in str(e):
            logger.info(f"Consumer group '{GROUP}' already exists")
        else:
            logger.error(f"Error creating consumer group: {e}")
            raise


# ============================================================================
# MAIN LOOP
# ============================================================================
async def main_loop():
    """Main processing loop with graceful shutdown support."""
    logger.info(f"Worker '{CONSUMER}' started listening on '{STREAM_PREFIX}'")

    consecutive_errors = 0
    max_consecutive_errors = 10

    while not shutdown_event.is_set():
        if not r:
            raise RuntimeError("Redis connection not initialized")

        try:
            # Read from stream with timeout
            messages = await asyncio.wait_for(
                r.xreadgroup(
                    GROUP,
                    CONSUMER,
                    {STREAM_PREFIX: ">"},  # type: ignore
                    count=1,
                    block=2000,
                ),
                timeout=5,
            )

            # Reset error counter on successful read
            consecutive_errors = 0

            if not messages:
                continue

            for stream_name, entries in messages:
                for msg_id, data in entries:
                    # Check shutdown before processing
                    if shutdown_event.is_set():
                        logger.info("Shutdown initiated, stopping message processing")
                        return

                    job_id = data.get("job_id")
                    if not job_id:
                        logger.warning(f"Malformed message in stream: {data}")
                        await r.xack(stream_name, GROUP, msg_id)
                        continue

                    # Fetch job data from Hash
                    job_raw = await r.hget(f"{HASH_PATH}:{job_id}", "data")  # type: ignore
                    if job_raw is None:
                        logger.warning(
                            f"Hash {HASH_PATH}:{job_id} not found (Ghost Job). "
                            "Cleaning up stream."
                        )
                        await r.xack(stream_name, GROUP, msg_id)
                        continue

                    # Parse job data
                    try:
                        job = json.loads(job_raw)
                    except json.JSONDecodeError as e:
                        logger.error(f"Invalid JSON in job {job_id}: {e}")
                        await r.xack(stream_name, GROUP, msg_id)
                        continue

                    # Create task and track it
                    task = asyncio.create_task(
                        process_job(job_id, job, stream_name, msg_id)
                    )
                    active_tasks.add(task)
                    task.add_done_callback(active_tasks.discard)

        except asyncio.TimeoutError:
            # Normal timeout, continue loop
            continue

        except redis.ConnectionError as e:
            consecutive_errors += 1
            logger.error(
                f"Redis connection error ({consecutive_errors}/{max_consecutive_errors}): {e}"
            )

            if consecutive_errors >= max_consecutive_errors:
                logger.critical("Max consecutive errors reached. Shutting down.")
                shutdown_event.set()
                return

            await asyncio.sleep(5)

        except asyncio.CancelledError:
            logger.info("Main loop cancelled")
            return

        except Exception as e:
            consecutive_errors += 1
            logger.error(
                f"Critical loop error ({consecutive_errors}/{max_consecutive_errors}): {e}",
                exc_info=True,
            )

            if consecutive_errors >= max_consecutive_errors:
                logger.critical("Max consecutive errors reached. Shutting down.")
                shutdown_event.set()
                return

            await asyncio.sleep(1)

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
    """Gracefully shutdown the worker."""
    logger.info("Starting graceful shutdown...")

    # Wait for active tasks with timeout
    if active_tasks:
        logger.info(f"Waiting for {len(active_tasks)} active tasks to complete...")
        try:
            await asyncio.wait_for(
                asyncio.gather(*active_tasks, return_exceptions=True),
                timeout=GRACEFUL_SHUTDOWN_TIMEOUT,
            )
            logger.info("All active tasks completed")
        except asyncio.TimeoutError:
            logger.warning(
                f"Shutdown timeout reached, cancelling {len(active_tasks)} remaining tasks"
            )
            for task in active_tasks:
                task.cancel()
            await asyncio.gather(*active_tasks, return_exceptions=True)

    # Cleanup connections
    await cleanup_connections()

    logger.info("Graceful shutdown complete")


# ============================================================================
# MAIN ENTRY POINT
# ============================================================================
async def main():
    """Main entry point with full lifecycle management."""
    try:
        # Initialize connections
        await init_connections()

        # Setup consumer groups
        await setup_groups()

        # Run main loop
        await main_loop()

    except Exception as e:
        logger.critical(f"Fatal error in main: {e}", exc_info=True)
        sys.exit(1)
    finally:
        await graceful_shutdown()


async def recovery_loop():
    """Periodically check for messages that were never ACKed."""
    if not r:
        return

    while not shutdown_event.is_set():
        try:
            # Check for messages pending for more than 1 minute
            pending = await r.xpending_range(STREAM_PREFIX, GROUP, "-", "+", 10)  # type: ignore
            for item in pending:
                if item["idle"] > 60000:  # 60 seconds
                    # Re-claim the message to process it
                    await r.xclaim(  # type: ignore
                        STREAM_PREFIX, GROUP, CONSUMER, 60000, [item["message_id"]]
                    )
            await asyncio.sleep(60)
        except Exception as e:
            logger.error(f"Recovery error: {e}")


if __name__ == "__main__":
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        setup_signal_handlers(loop)
        loop.run_until_complete(main())
    except KeyboardInterrupt:
        logger.info("Worker stopped by keyboard interrupt")
    except Exception as e:
        logger.critical(f"Unhandled exception: {e}", exc_info=True)
        sys.exit(1)
    finally:
        logger.info("Worker shutdown complete")
