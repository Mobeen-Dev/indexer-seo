"""
Bing Indexing API Async Batch Processor Module

This module handles async batch URL indexing for Shopify stores using
Bing's IndexNow API with proper error handling, rate limiting, and result tracking.
"""

import asyncio
import logging
from typing import Dict, List, Tuple, Optional, Callable, cast
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import json
import aiohttp
from aiohttp import ClientSession, ClientTimeout, ClientError


# Configure module logger
logger = logging.getLogger(__name__)


class BingAction(Enum):
    """Supported Bing Indexing actions"""

    SUBMIT = "SUBMIT"  # Bing only supports URL submission, not deletion


class ResultStatus(Enum):
    """Result status for each batch submission"""

    SUCCESS = "success"
    FAILED = "failed"
    QUOTA_EXCEEDED = "quota_exceeded"
    RATE_LIMITED = "rate_limited"
    SKIPPED = "skipped"


@dataclass
class BatchURLResult:
    """Result of a single batch submission"""

    batch_number: int
    urls: List[str]
    url_count: int
    status: ResultStatus
    attempts: int
    error_message: Optional[str] = None
    http_status: Optional[int] = None
    response_data: Optional[dict] = None
    timestamp: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> dict:
        """Convert result to dictionary"""
        return {
            "batch_number": self.batch_number,
            "urls": self.urls,
            "url_count": self.url_count,
            "status": self.status.value,
            "attempts": self.attempts,
            "error_message": self.error_message,
            "http_status": self.http_status,
            "response_data": self.response_data,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class BingBatchResult:
    """Aggregated results from Bing batch processing"""

    total_urls: int = 0
    total_batches: int = 0
    successful_batches: int = 0
    failed_batches: int = 0
    successful_urls: int = 0
    failed_urls: int = 0
    quota_exceeded: int = 0
    rate_limited: int = 0
    skipped: int = 0
    results: List[BatchURLResult] = field(default_factory=list)
    start_time: datetime = field(default_factory=datetime.utcnow)
    end_time: Optional[datetime] = None

    def add_result(self, result: BatchURLResult):
        """Add a batch result and update counters"""
        self.results.append(result)

        if result.status == ResultStatus.SUCCESS:
            self.successful_batches += 1
            self.successful_urls += result.url_count
        elif result.status == ResultStatus.FAILED:
            self.failed_batches += 1
            self.failed_urls += result.url_count
        elif result.status == ResultStatus.QUOTA_EXCEEDED:
            self.quota_exceeded += 1
            self.failed_urls += result.url_count
        elif result.status == ResultStatus.RATE_LIMITED:
            self.rate_limited += 1
            self.failed_urls += result.url_count
        elif result.status == ResultStatus.SKIPPED:
            self.skipped += 1

    def finalize(self):
        """Mark batch as complete"""
        self.end_time = datetime.utcnow()

    def to_dict(self) -> dict:
        """Convert batch result to dictionary"""
        return {
            "total_urls": self.total_urls,
            "total_batches": self.total_batches,
            "successful_batches": self.successful_batches,
            "failed_batches": self.failed_batches,
            "successful_urls": self.successful_urls,
            "failed_urls": self.failed_urls,
            "quota_exceeded": self.quota_exceeded,
            "rate_limited": self.rate_limited,
            "skipped": self.skipped,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "results": [r.to_dict() for r in self.results],
        }


class BingIndexingProcessor:
    """
    Production-ready async Bing Indexing API batch processor
    """

    # Bing API Constants
    BING_API_ENDPOINT = "https://ssl.bing.com/webmaster/api.svc/json/SubmitUrlbatch"
    BATCH_SIZE = 225  # Bing recommends max 225-250 URLs per batch
    MAX_CONCURRENT_REQUESTS = 5  # Limit concurrent API calls
    REQUEST_TIMEOUT = 30  # Seconds
    RETRY_DELAYS = [1, 12, 24]  # Exponential backoff delays in seconds

    def __init__(
        self,
        bing_api_key: str,
        site_url: str,
        batch_size: int = BATCH_SIZE,
        retry_limit: int = 3,
        max_concurrent: int = MAX_CONCURRENT_REQUESTS,
    ):
        """
        Initialize the Bing indexing processor

        Args:
            bing_api_key: Bing Webmaster API key
            site_url: Base site URL (e.g., "https://example.com")
            batch_size: Number of URLs per batch (max 250)
            retry_limit: Maximum retry attempts for failed requests
            max_concurrent: Maximum concurrent API requests
        """
        self.bing_api_key = bing_api_key
        self.site_url = self._normalize_site_url(site_url)
        self.batch_size = min(batch_size, 250)  # Enforce Bing's limit
        self.retry_limit = retry_limit
        self.max_concurrent = max_concurrent
        self.semaphore = asyncio.Semaphore(max_concurrent)

    @staticmethod
    def _normalize_site_url(url: str) -> str:
        """
        Normalize site URL to format Bing expects

        Args:
            url: Raw URL from shop domain

        Returns:
            Normalized URL (e.g., "http://www.example.com")
        """
        # Remove protocol if present
        url = url.replace("https://", "").replace("http://", "")

        # Remove trailing slash
        url = url.rstrip("/")

        # Remove .myshopify.com and use main domain if available
        # This is a simplification - in production, you'd want proper domain mapping
        if ".myshopify.com" in url:
            # For Shopify stores, you might want to use custom domain
            # For now, we'll keep the myshopify domain
            pass

        # Add protocol and www prefix if not present
        if not url.startswith("www."):
            url = f"www.{url}"
            
        return f"http://{url}"

    def _prepare_urls_from_actions(
        self, actions: dict, bing_limit: int
    ) -> Tuple[List[str], int]:
        """
        Prepare URLs from actions dict with limit enforcement
        Note: Bing API only supports URL submission, DELETE actions are logged but not processed

        Args:
            actions: Dictionary with INDEX and DELETE lists
            bing_limit: Maximum URLs allowed per day

        Returns:
            Tuple of (url_list, total_urls)
        """
        url_list = []

        # Calculate 10% buffer
        effective_limit = int(bing_limit * 1.10)

        # Process INDEX actions (Bing supports submission)
        for item in actions.get("INDEX", []):
            if len(url_list) >= effective_limit:
                break
            url_list.append(item["webUrl"])

        # Log DELETE actions (Bing doesn't have a delete endpoint)
        delete_count = len(actions.get("DELETE", []))
        if delete_count > 0:
            logger.warning(
                f" Bing API doesn't support URL deletion. "
                f"{delete_count} DELETE actions will be skipped."
            )

        total_available = len(actions.get("INDEX", []))

        logger.info(
            f" Prepared {len(url_list)} URLs from {total_available} "
            f"(limit: {bing_limit}, with buffer: {effective_limit})"
        )

        return url_list, total_available

    async def _submit_batch(
        self,
        session: ClientSession,
        batch_urls: List[str],
        batch_number: int,
        attempt: int = 1,
    ) -> BatchURLResult:
        """
        Submit a single batch of URLs to Bing

        Args:
            session: aiohttp ClientSession
            batch_urls: List of URLs to submit
            batch_number: Batch number for tracking
            attempt: Current attempt number

        Returns:
            BatchURLResult with submission results
        """
        async with self.semaphore:  # Limit concurrent requests
            url = f"{self.BING_API_ENDPOINT}?apikey={self.bing_api_key}"

            payload = {"siteUrl": self.site_url, "urlList": batch_urls}

            headers = {"Content-Type": "application/json; charset=utf-8"}

            try:
                logger.info(
                    f" Submitting batch {batch_number} "
                    f"({len(batch_urls)} URLs, attempt {attempt})"
                )

                async with session.post(
                    url,
                    json=payload,
                    headers=headers,
                    timeout=ClientTimeout(total=self.REQUEST_TIMEOUT),
                ) as response:
                    status_code = response.status

                    try:
                        response_data = await response.json()
                    except:
                        response_text = await response.text()
                        response_data = {"raw_response": response_text}

                    # Handle different status codes
                    if status_code == 200:
                        logger.info(
                            f" Batch {batch_number} submitted successfully "
                            f"({len(batch_urls)} URLs)"
                        )
                        return BatchURLResult(
                            batch_number=batch_number,
                            urls=batch_urls,
                            url_count=len(batch_urls),
                            status=ResultStatus.SUCCESS,
                            attempts=attempt,
                            http_status=status_code,
                            response_data=response_data,
                        )

                    elif status_code == 429:
                        # Rate limited
                        logger.warning(f" Rate limited on batch {batch_number}")

                        # Retry with exponential backoff
                        if attempt < self.retry_limit:
                            delay = self.RETRY_DELAYS[
                                min(attempt, len(self.RETRY_DELAYS) - 1)
                            ]
                            logger.info(f" Retrying after {delay}s...")
                            await asyncio.sleep(delay)
                            return await self._submit_batch(
                                session, batch_urls, batch_number, attempt + 1
                            )

                        return BatchURLResult(
                            batch_number=batch_number,
                            urls=batch_urls,
                            url_count=len(batch_urls),
                            status=ResultStatus.RATE_LIMITED,
                            attempts=attempt,
                            http_status=status_code,
                            error_message="Rate limit exceeded",
                            response_data=response_data,
                        )

                    elif status_code == 403:
                        # Quota exceeded or invalid API key
                        logger.error(
                            f" Quota exceeded or invalid API key for batch {batch_number}"
                        )
                        return BatchURLResult(
                            batch_number=batch_number,
                            urls=batch_urls,
                            url_count=len(batch_urls),
                            status=ResultStatus.QUOTA_EXCEEDED,
                            attempts=attempt,
                            http_status=status_code,
                            error_message="Quota exceeded or invalid API key",
                            response_data=response_data,
                        )

                    else:
                        # Other error
                        error_msg = f"HTTP {status_code}: {response_data}"
                        logger.error(f" Batch {batch_number} failed: {error_msg}")

                        # Retry on server errors (5xx)
                        if status_code >= 500 and attempt < self.retry_limit:
                            delay = self.RETRY_DELAYS[
                                min(attempt, len(self.RETRY_DELAYS) - 1)
                            ]
                            logger.info(f" Retrying after {delay}s...")
                            await asyncio.sleep(delay)
                            return await self._submit_batch(
                                session, batch_urls, batch_number, attempt + 1
                            )

                        return BatchURLResult(
                            batch_number=batch_number,
                            urls=batch_urls,
                            url_count=len(batch_urls),
                            status=ResultStatus.FAILED,
                            attempts=attempt,
                            http_status=status_code,
                            error_message=error_msg,
                            response_data=response_data,
                        )

            except asyncio.TimeoutError:
                logger.error(f" Timeout on batch {batch_number}")

                # Retry on timeout
                if attempt < self.retry_limit:
                    delay = self.RETRY_DELAYS[min(attempt, len(self.RETRY_DELAYS) - 1)]
                    logger.info(f" Retrying after {delay}s...")
                    await asyncio.sleep(delay)
                    return await self._submit_batch(
                        session, batch_urls, batch_number, attempt + 1
                    )

                return BatchURLResult(
                    batch_number=batch_number,
                    urls=batch_urls,
                    url_count=len(batch_urls),
                    status=ResultStatus.FAILED,
                    attempts=attempt,
                    error_message="Request timeout",
                )

            except ClientError as e:
                logger.error(f" Client error on batch {batch_number}: {e}")

                # Retry on client errors
                if attempt < self.retry_limit:
                    delay = self.RETRY_DELAYS[min(attempt, len(self.RETRY_DELAYS) - 1)]
                    logger.info(f" Retrying after {delay}s...")
                    await asyncio.sleep(delay)
                    return await self._submit_batch(
                        session, batch_urls, batch_number, attempt + 1
                    )

                return BatchURLResult(
                    batch_number=batch_number,
                    urls=batch_urls,
                    url_count=len(batch_urls),
                    status=ResultStatus.FAILED,
                    attempts=attempt,
                    error_message=f"Client error: {str(e)}",
                )

            except Exception as e:
                logger.error(
                    f" Unexpected error on batch {batch_number}: {e}", exc_info=True
                )
                return BatchURLResult(
                    batch_number=batch_number,
                    urls=batch_urls,
                    url_count=len(batch_urls),
                    status=ResultStatus.FAILED,
                    attempts=attempt,
                    error_message=f"Unexpected error: {str(e)}",
                )

    async def process_job(self, job_data: dict) -> BingBatchResult:
        """
        Process a complete Bing indexing job asynchronously

        Args:
            job_data: Complete job data including actions and auth

        Returns:
            BingBatchResult with complete processing results
        """
        logger.info(f" Starting Bing indexing job for shop: {job_data.get('shop')}")

        batch_result = BingBatchResult()

        # Extract configuration
        auth = job_data.get("auth", {})
        bing_limit = auth.get("settings", {}).get("bingLimit", 10)
        actions = job_data.get("actions", {})

        # Prepare URLs with limit
        url_list, total_available = self._prepare_urls_from_actions(actions, bing_limit)

        if not url_list:
            logger.warning(" No URLs to process")
            batch_result.finalize()
            return batch_result

        batch_result.total_urls = len(url_list)

        # Split into batches
        batches = [
            url_list[i : i + self.batch_size]
            for i in range(0, len(url_list), self.batch_size)
        ]

        batch_result.total_batches = len(batches)

        logger.info(
            f" Processing {len(batches)} batches ({len(url_list)} total URLs)"
        )

        # Process batches asynchronously
        async with aiohttp.ClientSession() as session:
            tasks = [
                self._submit_batch(session, batch, idx + 1)
                for idx, batch in enumerate(batches)
            ]

            # Execute all tasks concurrently with progress tracking
            results = await asyncio.gather(*tasks, return_exceptions=True)

            # Process results
            for result in results:
                if isinstance(result, Exception):
                    logger.error(f" Task failed with exception: {result}")
                    # Create a failed result
                    failed_result = BatchURLResult(
                        batch_number=0,
                        urls=[],
                        url_count=0,
                        status=ResultStatus.FAILED,
                        attempts=1,
                        error_message=str(result),
                    )
                    batch_result.add_result(failed_result)
                else:
                    batch_result.add_result(cast(BatchURLResult, result))

        # Finalize results
        batch_result.finalize()

        logger.info(
            f"-- Job completed: {batch_result.successful_batches}/{batch_result.total_batches} "
            f"batches successful ({batch_result.successful_urls} URLs submitted)"
        )

        return batch_result


async def process_bing_indexing_job(job_data: dict, decode_function: Callable) -> dict:
    """
    Main async entry point for processing a Bing indexing job

    Args:
        job_data: Complete job data structure
        decode_function: Optional function to decode bingApiKey

    Returns:
        Dictionary containing processing results
    """
    try:
        # Extract and decode Bing API key
        auth = job_data.get("auth", {})
        bing_api_key_encoded = auth.get("bingApiKey")

        if not bing_api_key_encoded:
            raise ValueError("Missing bingApiKey in auth data")

        # Decode if function provided
        if decode_function:
            bing_api_key = decode_function(bing_api_key_encoded)
        else:
            # Assume it's already decoded
            bing_api_key = bing_api_key_encoded

        # Extract settings
        settings = auth.get("settings", {})
        bing_limit = settings.get("bingLimit", 10)
        retry_limit = settings.get("retryLimit", 3)

        # Get shop URL
        shop = job_data.get("shop", "")

        # Initialize processor
        processor = BingIndexingProcessor(
            bing_api_key=bing_api_key, site_url=shop, retry_limit=retry_limit
        )

        # Process job
        batch_result = await processor.process_job(job_data)

        # Return results
        return {
            "success": True,
            "job_type": job_data.get("jobType"),
            "shop": job_data.get("shop"),
            "results": batch_result.to_dict(),
        }

    except Exception as e:
        logger.error(f" Job processing failed: {e}", exc_info=True)
        return {
            "success": False,
            "error": str(e),
            "job_type": job_data.get("jobType"),
            "shop": job_data.get("shop"),
        }


def process_bing_indexing_job_sync(job_data: dict, decode_function: Callable) -> dict:
    """
    Synchronous wrapper for async processing

    Args:
        job_data: Complete job data structure
        decode_function: Optional function to decode bingApiKey

    Returns:
        Dictionary containing processing results
    """
    return asyncio.run(process_bing_indexing_job(job_data, decode_function))


# Example usage
if __name__ == "__main__":
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    # Example job data
    example_job = {
        "jobType": "URL_INDEXING_BATCH",
        "version": 1,
        "shop": "app-development-store-grow.myshopify.com",
        "actions": {
            "INDEX": [
                {"webUrl": "https://example.com/product-1", "attempts": 1},
                {"webUrl": "https://example.com/product-2", "attempts": 1},
            ],
            "DELETE": [
                {"webUrl": "https://example.com/deleted-product", "attempts": 1}
            ],
        },
        "auth": {
            "bingApiKey": "your-api-key-here",
            "settings": {"bingLimit": 10, "retryLimit": 3},
        },
    }

    # Example decode function
    def decode_bing_api_key(encoded_key):
        # Your decoding logic here
        return encoded_key

    # Process job (sync wrapper)
    result = process_bing_indexing_job_sync(
        example_job, decode_function=decode_bing_api_key
    )

    print(f"\n{'=' * 60}")
    print("FINAL RESULTS")
    print("=" * 60)
    print(json.dumps(result, indent=2))
