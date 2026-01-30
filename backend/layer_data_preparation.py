import json
import uuid
import socket
import asyncio
import logging
import logging.handlers
import signal
import sys
import os
from typing import Dict, List, Optional, Tuple
from collections import defaultdict
from datetime import datetime, timezone
# from contextlib import asynccontextmanager

import redis.asyncio as redis
from supabase import create_client, Client
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)

from db_model import (
    Auth,
    UrlItem,
    UrlEntry,
    UrlStatus,
    IndexAction,
    IndexActionStr,
    UrlIndexBatchJob,
)
from config import (
    settings,
    L1_GROUP,
    L1_HASH_PATH,
    L1_JOB_LIMIT,
    L1_STREAM_PREFIX,
    L2_HASH_PATH,
    L2_STREAM_PREFIX,
)

# ============================================================================
# CONFIGURATION
# ============================================================================
AUTH_CACHE: Dict[str, Auth] = {}
AUTH_CACHE_MAX_SIZE = 10000  # Prevent unbounded memory growth
SUPABASE_URL: str = settings.SUPABASE_URL
SUPABASE_KEY: str = settings.SUPABASE_KEY
REDIS_PORT: int = settings.REDIS_PORT
REDIS_PASS: str = settings.REDIS_PASS
REDIS_HOST: str = settings.REDIS_HOST
HASH_PATH: str = L1_HASH_PATH
NEXT_HASH_PATH: str = L2_HASH_PATH
STREAM_PREFIX = L1_STREAM_PREFIX
NEXT_STREAM_PREFIX = L2_STREAM_PREFIX
JOB_LIMIT = asyncio.Semaphore(L1_JOB_LIMIT)
GROUP = L1_GROUP
CONSUMER = f"{socket.gethostname()}-{uuid.uuid4().hex[:8]}"  # Unique consumer ID
LOG_FILE = os.path.join("./logs", "worker_l1.log")

# Timeouts
SUPABASE_TIMEOUT = 30  # seconds
REDIS_TIMEOUT = 10  # seconds
GRACEFUL_SHUTDOWN_TIMEOUT = 30  # seconds

# ============================================================================
# LOGGING SETUP
# ============================================================================
os.makedirs("./logs", exist_ok=True)  # Make Sure it Exists
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        # Add file handler for production
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
        max_connections=50,  # Connection pool
        # retry_on_timeout=True, #  TimeoutError is retried by default
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
def fetch_auth_and_urls(shop: str) -> Tuple[Optional[Auth], List[UrlEntry]]:
    """
    Fetch auth and URL entries from Supabase with retry logic.

    Returns:
        Tuple of (Auth object or None, List of UrlEntry objects)
    """
    if supabase:
        try:
            # Fetch auth
            auth_response = (
                supabase.table("Auth").select("*").eq("shop", shop).execute()
            )

            if not auth_response.data:
                logger.warning(f"No auth found for shop: {shop}")
                return None, []

            auth_data = auth_response.data[0]
            auth = Auth(**auth_data)  # type: ignore

            # Calculate limits
            bing_index_limit = auth.settings.get("bingLimit", 200)
            google_index_limit = auth.settings.get("googleLimit", 200)
            final_limit = int(max(bing_index_limit, google_index_limit) * 1.05)

            # Fetch URLs with all required fields
            urls_response = (
                supabase.table("UrlEntry")
                .select("webUrl, indexAction, attempts")
                .eq("shop", shop)
                .eq("status", UrlStatus.PENDING.value)
                .eq("isGoogleIndexed", False)
                .neq("indexAction", IndexAction.IGNORE.value)
                .order("attempts", desc=True)
                .limit(final_limit)
                .execute()
            )

            # Convert to UrlEntry objects
            url_entries = []
            for url_data in urls_response.data:
                try:
                    url_entry = UrlEntry(
                        webUrl=url_data.get("webUrl"),  # type: ignore
                        indexAction=IndexAction(url_data.get("indexAction")),  # type: ignore
                        attempts=url_data.get("attempts", 1),  # type: ignore
                    )
                    url_entries.append(url_entry)
                except (ValueError, TypeError) as e:
                    logger.warning(
                        f"Skipping invalid URL entry: {url_data}, error: {e}"
                    )
                    continue

            logger.info(f"Fetched {len(url_entries)} URLs for shop {shop}")
            return auth, url_entries

        except Exception as e:
            logger.error(
                f"Error fetching auth and urls for shop {shop}: {e}", exc_info=True
            )
            raise
    raise


# ============================================================================
# CACHE MANAGEMENT
# ============================================================================
def manage_cache_size():
    """Prevent unbounded cache growth using LRU eviction."""
    if len(AUTH_CACHE) > AUTH_CACHE_MAX_SIZE:
        # Remove oldest 10% of entries
        remove_count = AUTH_CACHE_MAX_SIZE // 10
        keys_to_remove = list(AUTH_CACHE.keys())[:remove_count]
        for key in keys_to_remove:
            AUTH_CACHE.pop(key, None)
        logger.info(f"Evicted {remove_count} entries from AUTH_CACHE")


# ============================================================================
# JOB PROCESSING
# ============================================================================
async def process_job(job_id: str, job: dict, stream_name: str, msg_id: str):
    """Process a single job with comprehensive error handling."""
    if not r:
        raise
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

            # Fetch or retrieve cached auth
            # auth = AUTH_CACHE.get(shop)
            auth = None
            if not auth:
                auth, url_entries = await asyncio.to_thread(fetch_auth_and_urls, shop)
                if not auth:
                    logger.error(f"Job {job_id}: No Auth found for shop {shop}")
                    await r.xack(stream_name, GROUP, msg_id)
                    return

                # AUTH_CACHE[shop] = auth
                # manage_cache_size()
            else:
                _, url_entries = await asyncio.to_thread(fetch_auth_and_urls, shop)

            # Validate URL entries
            if not url_entries:
                logger.info(f"Job {job_id}: No pending URLs for shop {shop}")
                await r.hset(
                    f"{HASH_PATH}:{job_id}",
                    mapping={
                        "status": "completed",
                        "completed_at": datetime.now(timezone.utc).isoformat(),
                        "message": "No URLs to process",
                    },
                )  # type: ignore
                await r.xack(stream_name, GROUP, msg_id)
                return

            # Build actions dictionary
            actions: Dict[IndexActionStr, List[dict]] = defaultdict(list)
            for row in url_entries:
                action = row.indexAction.value
                if action not in ("INDEX", "DELETE"):
                    continue

                actions[action].append(
                    UrlItem(
                        webUrl=row.webUrl,  # type: ignore
                        attempts=row.attempts,  # type: ignore
                    ).to_dict()
                )

            # Create next job
            next_job = UrlIndexBatchJob(
                jobType="URL_INDEXING_BATCH",
                version=1,
                actions=dict(actions),
                shop=shop,
                auth=auth.to_dict(),
            )
            next_job_id = str(uuid.uuid4())

            # Store next job in Redis Hash
            await r.hset(
                f"{NEXT_HASH_PATH}:{next_job_id}",
                mapping={
                    "data": json.dumps(next_job.to_dict()),
                    "status": "queued",
                    "created_at": datetime.now(timezone.utc).isoformat(),
                },
            )  # type: ignore

            # Set expiration on hash to prevent memory leaks (7 days)
            await r.expire(f"{NEXT_HASH_PATH}:{next_job_id}", 86400)

            # Push to next stream
            await r.xadd(
                NEXT_STREAM_PREFIX,
                {"job_id": next_job_id, "shop": shop},
            )

            # Update current job status
            processing_time = (datetime.now(timezone.utc) - start_time).total_seconds()
            await r.hset(
                f"{HASH_PATH}:{job_id}",
                mapping={
                    "status": "completed",
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                    "processing_time_seconds": str(processing_time),
                    "urls_processed": str(len(url_entries)),
                },
            )  # type: ignore

            # Set expiration on completed job (7 days)
            await r.expire(f"{HASH_PATH}:{job_id}", 86400)

            # ACK message
            await r.xack(stream_name, GROUP, msg_id)

            logger.info(
                f"Job {job_id} completed successfully in {processing_time:.2f}s "
                f"(processed {len(url_entries)} URLs)"
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
        raise
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
            raise
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
