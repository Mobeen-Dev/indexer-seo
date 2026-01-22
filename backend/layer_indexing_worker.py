import json
import uuid
import socket
import asyncio
import logging
import logging.handlers
import signal
import sys
from typing import Optional
from datetime import datetime, timezone

import redis.asyncio as redis
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)

from indexing_google import process_indexing_job
from indexing_bing import process_bing_indexing_job
from auth import decrypt

from config import (
    settings,
    L2_GROUP,
    L2_HASH_PATH,
    L2_JOB_LIMIT,
    L2_STREAM_PREFIX,
    L3_HASH_PATH,
    L3_STREAM_PREFIX,
)

# ============================================================================
# CONFIGURATION
# ============================================================================
REDIS_PORT: int = settings.REDIS_PORT
REDIS_PASS: str = settings.REDIS_PASS
REDIS_HOST: str = settings.REDIS_HOST

HASH_PATH: str = L2_HASH_PATH
NEXT_HASH_PATH: str = L3_HASH_PATH

STREAM_PREFIX = L2_STREAM_PREFIX
NEXT_STREAM_PREFIX = L3_STREAM_PREFIX

JOB_LIMIT = asyncio.Semaphore(L2_JOB_LIMIT)
GROUP = L2_GROUP
CONSUMER = f"{socket.gethostname()}-{uuid.uuid4().hex[:8]}"  # Unique consumer ID

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
            "worker_l2.log", maxBytes=50_000_000, backupCount=5
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
# INDEXING OPERATIONS
# ============================================================================
@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type((ConnectionError, TimeoutError)),
)
async def execute_bing_indexing(job_data: dict) -> Optional[dict]:
    """Execute Bing indexing with retry logic."""
    try:
        result = await process_bing_indexing_job(
            job_data=job_data, decode_function=decrypt
        )
        logger.info(
            f"Bing indexing completed: "
            f"Successful={result['results']['successful_urls']}, "
            f"Failed={result['results']['failed_urls']}"
        )
        return result
    except Exception as e:
        logger.error(f"Bing indexing failed: {e}", exc_info=True)
        raise


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type((ConnectionError, TimeoutError)),
)
def execute_google_indexing(job_data: dict) -> Optional[dict]:
    """Execute Google indexing with retry logic."""
    try:
        result = process_indexing_job(job_data=job_data, decode_function=decrypt)
        logger.info(
            f"Google indexing completed: "
            f"Total={result['results']['total_urls']}, "
            f"Successful={result['results']['successful']}, "
            f"Failed={result['results']['failed']}"
        )
        return result
    except Exception as e:
        logger.error(f"Google indexing failed: {e}", exc_info=True)
        raise


# ============================================================================
# JOB PROCESSING
# ============================================================================
async def process_job(job_id: str, job: dict, stream_name: str, msg_id: str):
    """Process a single indexing job with comprehensive error handling."""
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

            # Extract authentication credentials
            auth = job.get("auth", {})
            google_auth = auth.get("googleConfig")
            bing_auth = auth.get("bingApiKey")

            # Validate at least one auth is present
            has_google = google_auth and len(str(google_auth)) > 10
            has_bing = bing_auth and len(str(bing_auth)) > 10

            if not has_google and not has_bing:
                logger.warning(f"Job {job_id}: No valid credentials for shop {shop}")
                await r.hset(
                    f"{HASH_PATH}:{job_id}",
                    mapping={
                        "status": "completed",
                        "completed_at": datetime.now(timezone.utc).isoformat(),
                        "message": "No valid credentials",
                    },
                )  # type: ignore
                await r.xack(stream_name, GROUP, msg_id)
                return

            # Execute indexing operations
            bing_result = None
            google_result = None

            if has_bing:
                try:
                    bing_result = await execute_bing_indexing(job)
                except Exception as e:
                    logger.error(f"Job {job_id}: Bing indexing error: {e}")
                    # Continue to try Google even if Bing fails

            if has_google:
                try:
                    google_result = await asyncio.to_thread(
                        execute_google_indexing, job
                    )
                except Exception as e:
                    logger.error(f"Job {job_id}: Google indexing error: {e}")
                    # Continue even if Google fails

            # Build response
            response = {
                "shop": shop,
                "job_id": job_id,
                "processed_at": datetime.now(timezone.utc).isoformat(),
            }

            if google_result:
                response["google"] = {
                    "executed": True,
                    "success": google_result["success"],
                    "result": google_result,
                }
            else:
                response["google"] = {
                    "executed": False,
                    "reason": "missing_credentials" if not has_google else "failed",
                }

            if bing_result:
                response["bing"] = {
                    "executed": True,
                    "success": bing_result["success"],
                    "result": bing_result,
                }
            else:
                response["bing"] = {
                    "executed": False,
                    "reason": "missing_credentials" if not has_bing else "failed",
                }

            # Create next job
            next_job_id = str(uuid.uuid4())

            # Store next job in Redis Hash
            await r.hset(
                f"{NEXT_HASH_PATH}:{next_job_id}",
                mapping={
                    "data": json.dumps(response),
                    "status": "queued",
                    "created_at": datetime.now(timezone.utc).isoformat(),
                },
            )  # type: ignore

            # Set expiration on hash (7 days)
            await r.expire(f"{NEXT_HASH_PATH}:{next_job_id}", 43200)

            # Push to next stream
            await r.xadd(
                NEXT_STREAM_PREFIX,
                {"job_id": next_job_id, "shop": shop},
            )

            # Update current job status
            processing_time = (datetime.now(timezone.utc) - start_time).total_seconds()

            # Calculate total URLs processed
            total_urls = 0
            if google_result:
                total_urls += google_result.get("results", {}).get("total_urls", 0)
            if bing_result:
                total_urls += bing_result.get("results", {}).get(
                    "successful_urls", 0
                ) + bing_result.get("results", {}).get("failed_urls", 0)

            await r.hset(
                f"{HASH_PATH}:{job_id}",
                mapping={
                    "status": "completed",
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                    "processing_time_seconds": str(processing_time),
                    "urls_processed": str(total_urls),
                    "google_executed": str(has_google),
                    "bing_executed": str(has_bing),
                },
            )  # type: ignore

            # Set expiration on completed job (7 days)
            await r.expire(f"{HASH_PATH}:{job_id}", 43200)

            # ACK message
            await r.xack(stream_name, GROUP, msg_id)

            logger.info(
                f"Job {job_id} completed successfully in {processing_time:.2f}s "
                f"(processed {total_urls} URLs)"
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
                await r.expire(f"{HASH_PATH}:{job_id}", 43200)
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
