import json
import uuid
import socket
import asyncio
import logging
import redis.asyncio as redis
from typing import Dict, List
from collections import defaultdict
from datetime import datetime, timezone

from sqlalchemy.orm import load_only
from sqlalchemy import desc, select, String
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
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


# CONFIG
AUTH_CACHE: Dict[str, Auth] = {}
CentralAsyncSession: async_sessionmaker[AsyncSession]

DATABASE_URL = "postgresql+asyncpg://postgres:123456789@localhost:5432/my_new_db"

REDIS_PORT: int = 6379
REDIS_PASS: str = "strongpassword123"
REDIS_HOST: str = "localhost"

HASH_PATH: str = "data-prep-msg"
NEXT_HASH_PATH: str = "indexing-workers-msg"

STREAM_PREFIX = "stream:data-prep-agents"
NEXT_STREAM_PREFIX = "stream:indexing-workers"

JOB_LIMIT = asyncio.Semaphore(2)
GROUP = "job-workers"


# Layer Specific


engine = create_async_engine(
    DATABASE_URL,
    pool_size=2,
    max_overflow=10,
    pool_pre_ping=True,
)

CentralAsyncSession = async_sessionmaker(engine, expire_on_commit=False)


# Set up logging for better visibility
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

r = redis.Redis(
    host=REDIS_HOST, port=REDIS_PORT, password=REDIS_PASS, decode_responses=True
)


CONSUMER = socket.gethostname()


async def process_job(job_id, job, stream_name, msg_id):
    async with JOB_LIMIT:
        # logger.info(f"Job {job_id} started | Available slots: {JOB_LIMIT._value}")
        try:
            shop = job.get("shop", None)
            if not shop:
                logger.error("Invalid Request 'shop' not present in job")
                return

            auth = AUTH_CACHE.get(shop, None)
            async with CentralAsyncSession() as session:
                # Example query (adjust table/columns as needed)
                if not auth:
                    stmt = select(Auth).where(Auth.shop == shop)
                    result = await session.execute(stmt)

                    auth = result.scalar_one_or_none()

                    if not auth:
                        logger.error(f"No Auth found for shop: {shop}")
                        return

                print("Shop:", shop)
                bing_index_limit = auth.settings.get("bingLimit", 200)
                google_index_limit = auth.settings.get("googleLimit", 200)

                final_limit = max(bing_index_limit, google_index_limit)
                final_limit = int(
                    final_limit * 1.05
                )  # Adding 5% more to test exceed limits and for reject cases while indexing

                stmt = (
                    select(UrlEntry)
                    .where(
                        UrlEntry.shop == shop,
                        # UrlEntry.status.cast(String) == "PENDING",
                        UrlEntry.status.cast(String) == UrlStatus.PENDING.value,
                        # UrlEntry.indexAction.cast(String) != "IGNORE",
                        UrlEntry.indexAction.cast(String) != IndexAction.IGNORE.value,
                    )
                    .order_by(
                        desc(UrlEntry.attempts),
                        # asc(UrlEntry.submittedAt),
                        # asc(UrlEntry.id),
                    )
                    .limit(final_limit)
                    .options(
                        load_only(
                            UrlEntry.originalUrl,  # type: ignore
                            UrlEntry.indexAction,  # type: ignore
                            UrlEntry.attempts,     # type: ignore
                        )
                    )
                )

            result = await session.execute(stmt)
            url_entries = result.scalars().all()

            # DEBUG PURPOSE
            print(f"URLS: {len(url_entries)}\n")
            print([url.originalUrl for url in url_entries])
            print([url.indexAction.value for url in url_entries])
            print([url.attempts for url in url_entries])
            print("\n")

            actions: Dict[IndexActionStr, List[UrlItem]] = defaultdict(list)

            for row in url_entries:
                action = row.indexAction.value  # Enum → string
                if action not in ("INDEX", "DELETE"):
                    # TODO: Add Flag to see
                    continue

                actions[action].append(
                    UrlItem(originalUrl=row.originalUrl, attempts=row.attempts)  # type: ignore
                )

            next_job_hash = UrlIndexBatchJob(
                jobType="URL_INDEXING_BATCH",
                version=1,  # Need to define ...
                actions=dict(actions),
                shop=shop,
            )
            print("job \n\n")
            print(next_job_hash)

            next_job_id = str(uuid.uuid4())

            await r.hset(
                f"{NEXT_HASH_PATH}:{next_job_id}",
                mapping={
                    "data": json.dumps(next_job_hash, default=lambda o: o.__dict__),
                    "status": "queued",
                    "created_at": datetime.now(timezone.utc).isoformat(),
                },
            )  # type: ignore

            # Push ONLY routing data to stream
            await r.xadd(
                f"{NEXT_STREAM_PREFIX}",
                {"job_id": next_job_id, "shop": shop},
            )

            # 1. Update status to completed in the Hash
            await r.hset(
                f"{HASH_PATH}:{job_id}",
                mapping={
                    "status": "completed",
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                },
            )  # type: ignore

            # ACK only after successful processing
            await r.xack(stream_name, GROUP, msg_id)

        except Exception as e:
            logger.error(f"Job {job_id} failed: {e}")

            # Optional: retry / dead-letter logic here
            # For now, ACK to avoid poison-pill loops
            await r.xack(stream_name, GROUP, msg_id)


async def setup_groups():
    """Ensure consumer group exists for the single stream."""
    try:
        # 0 means create group pointing to the beginning of stream
        await r.xgroup_create(STREAM_PREFIX, GROUP, id="0", mkstream=True)
        logger.info(f"Group {GROUP} checked/created for {STREAM_PREFIX}")
    except redis.ResponseError as e:
        if "BUSYGROUP" in str(e):
            pass
        else:
            logger.error(f"Error creating group: {e}")


async def main():
    await setup_groups()
    logger.info(f"Worker {CONSUMER} started listening on {STREAM_PREFIX}")

    while True:
        try:
            # This returns immediately if stream has data.
            messages = await r.xreadgroup(
                GROUP,
                CONSUMER,
                {STREAM_PREFIX: ">"},
                count=1,
                block=2000,
            )

            if not messages:
                continue

            for stream_name, entries in messages:
                for msg_id, data in entries:
                    job_id = data.get("job_id")

                    if not job_id:
                        # Malformed message in stream, ACK and skip
                        await r.xack(stream_name, GROUP, msg_id)
                        continue

                    # Fetch actual job data from Hash
                    job_raw = await r.hget(f"{HASH_PATH}:{job_id}", "data")  # type: ignore

                    if job_raw is None:
                        logger.warning(
                            f"Hash {HASH_PATH}:{job_id} not found (Ghost Job). Cleaning up stream."
                        )
                        # Critical: ACK this so we don't loop forever on a missing job
                        await r.xack(stream_name, GROUP, msg_id)
                        continue

                    job = json.loads(job_raw)

                    # Fire and forget (Concurrency)
                    # This allows the loop to go back to xreadgroup immediately
                    asyncio.create_task(process_job(job_id, job, stream_name, msg_id))

        except redis.ConnectionError:
            logger.error("Connection lost. Retrying in 5 seconds...")
            await asyncio.sleep(5)
        except Exception as e:
            logger.error(f"Critical Loop Error: {e}")
            await asyncio.sleep(1)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Worker stopped manually.")
    finally:
        asyncio.run(engine.dispose())
