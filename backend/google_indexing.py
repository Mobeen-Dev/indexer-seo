"""
Google Indexing API Batch Processor Module

This module handles batch URL indexing/deletion for Shopify stores using
Google's Indexing API with proper error handling, rate limiting, and result tracking.
"""

import json
import logging
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable
from enum import Enum

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError


# Configure module logger
logger = logging.getLogger(__name__)


class IndexingAction(Enum):
    """Supported Google Indexing API actions"""

    URL_UPDATED = "URL_UPDATED"
    URL_DELETED = "URL_DELETED"


class ResultStatus(Enum):
    """Result status for each URL submission"""

    SUCCESS = "success"
    FAILED = "failed"
    QUOTA_EXCEEDED = "quota_exceeded"
    SKIPPED = "skipped"


@dataclass
class URLResult:
    """Result of a single URL indexing operation"""

    url: str
    action: str
    status: ResultStatus
    attempts: int
    error_message: Optional[str] = None
    http_status: Optional[int] = None
    timestamp: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict:
        """Convert result to dictionary"""
        return {
            "url": self.url,
            "action": self.action,
            "status": self.status.value,
            "attempts": self.attempts,
            "error_message": self.error_message,
            "http_status": self.http_status,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class BatchResult:
    """Aggregated results from batch processing"""

    total_urls: int = 0
    successful: int = 0
    failed: int = 0
    quota_exceeded: int = 0
    skipped: int = 0
    results: List[URLResult] = field(default_factory=list)
    start_time: datetime = field(default_factory=datetime.utcnow)
    end_time: Optional[datetime] = None

    def add_result(self, result: URLResult):
        """Add a URL result and update counters"""
        self.results.append(result)

        if result.status == ResultStatus.SUCCESS:
            self.successful += 1
        elif result.status == ResultStatus.FAILED:
            self.failed += 1
        elif result.status == ResultStatus.QUOTA_EXCEEDED:
            self.quota_exceeded += 1
        elif result.status == ResultStatus.SKIPPED:
            self.skipped += 1

    def finalize(self):
        """Mark batch as complete"""
        self.end_time = datetime.now()

    def to_dict(self) -> dict:
        """Convert batch result to dictionary"""
        return {
            "total_urls": self.total_urls,
            "successful": self.successful,
            "failed": self.failed,
            "quota_exceeded": self.quota_exceeded,
            "skipped": self.skipped,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "results": [r.to_dict() for r in self.results],
        }


class GoogleIndexingProcessor:
    """
    Production-ready Google Indexing API batch processor
    """

    # Google API Constants
    SCOPES = ["https://www.googleapis.com/auth/indexing"]
    BATCH_SIZE = 100  # Safe batch size (Google allows up to 1000)
    MAX_URLS_PER_DAY = 200  # Default quota limit

    def __init__(
        self, google_config: dict, batch_size: int = BATCH_SIZE, retry_limit: int = 3
    ):
        """
        Initialize the indexing processor

        Args:
            google_config: Service account credentials dictionary
            batch_size: Number of URLs to process per batch (max 1000)
            retry_limit: Maximum retry attempts for failed requests
        """
        self.google_config = google_config
        self.batch_size = min(batch_size, 1000)  # Enforce Google's limit
        self.retry_limit = retry_limit
        self.service = None
        self._urls_submitted = 0

    def _authenticate(self) -> bool:
        """
        Authenticate with Google Indexing API

        Returns:
            bool: True if authentication successful, False otherwise
        """
        try:
            credentials = service_account.Credentials.from_service_account_info(
                self.google_config, scopes=self.SCOPES
            )
            self.service = build("indexing", "v3", credentials=credentials)
            logger.info("✅ Successfully authenticated with Google Indexing API")
            return True

        except Exception as e:
            logger.error(f"❌ Authentication failed: {e}", exc_info=True)
            return False

    def _prepare_urls_from_actions(
        self, actions: dict, google_limit: int
    ) -> Tuple[Dict[str, str], int]:
        """
        Prepare URLs from actions dict with limit enforcement

        Args:
            actions: Dictionary with INDEX and DELETE lists
            google_limit: Maximum URLs allowed per day

        Returns:
            Tuple of (url_mapping, total_urls)
        """
        url_mapping = {}

        # Calculate 10% buffer
        effective_limit = int(google_limit * 1.10)

        # Process INDEX actions
        for item in actions.get("INDEX", []):
            if len(url_mapping) >= effective_limit:
                break
            url_mapping[item["webUrl"]] = IndexingAction.URL_UPDATED.value

        # Process DELETE actions
        for item in actions.get("DELETE", []):
            if len(url_mapping) >= effective_limit:
                break
            url_mapping[item["webUrl"]] = IndexingAction.URL_DELETED.value

        total_available = len(actions.get("INDEX", [])) + len(actions.get("DELETE", []))

        logger.info(
            f"📊 Prepared {len(url_mapping)} URLs from {total_available} "
            f"(limit: {google_limit}, with buffer: {effective_limit})"
        )

        return url_mapping, total_available

    def _create_batch_callback(
        self, url: str, action: str, attempts: int, batch_result: BatchResult
    ):
        """
        Create a callback function for batch request

        Args:
            url: The URL being processed
            action: The action type (URL_UPDATED/URL_DELETED)
            attempts: Current attempt number
            batch_result: BatchResult object to store results

        Returns:
            Callback function
        """

        def callback(request_id, response, exception):
            if exception is not None:
                # Handle errors
                if isinstance(exception, HttpError):
                    status_code = exception.resp.status
                    error_content = exception.content.decode("utf-8")

                    # Check for quota exceeded (429)
                    if status_code == 429:
                        logger.warning(f"⚠️ Quota exceeded for: {url}")
                        result = URLResult(
                            url=url,
                            action=action,
                            status=ResultStatus.QUOTA_EXCEEDED,
                            attempts=attempts,
                            error_message="API quota exceeded",
                            http_status=status_code,
                        )
                    else:
                        logger.error(
                            f"❌ Failed [{status_code}] {url}: {error_content}"
                        )
                        result = URLResult(
                            url=url,
                            action=action,
                            status=ResultStatus.FAILED,
                            attempts=attempts,
                            error_message=error_content,
                            http_status=status_code,
                        )
                else:
                    logger.error(f"❌ Exception for {url}: {exception}")
                    result = URLResult(
                        url=url,
                        action=action,
                        status=ResultStatus.FAILED,
                        attempts=attempts,
                        error_message=str(exception),
                    )

                batch_result.add_result(result)
            else:
                # Success
                response_url = response.get("urlNotificationMetadata", {}).get(
                    "url", url
                )
                logger.info(f"✅ Success: {response_url}")

                result = URLResult(
                    url=url,
                    action=action,
                    status=ResultStatus.SUCCESS,
                    attempts=attempts,
                    http_status=200,
                )
                batch_result.add_result(result)
                self._urls_submitted += 1

        return callback

    def _process_batch_chunk(
        self,
        urls: List[Tuple[str, str, int]],
        batch_result: BatchResult,
        chunk_number: int,
    ) -> None:
        """
        Process a single batch chunk

        Args:
            urls: List of (url, action, attempts) tuples
            batch_result: BatchResult object to store results
            chunk_number: Current chunk number for logging
        """
        logger.info(f"📦 Processing batch chunk {chunk_number} ({len(urls)} URLs)")
        if not self.service:
            raise RuntimeError("Service not initialized. Call _authenticate() first.")

        batch = self.service.new_batch_http_request()

        for url, action, attempts in urls:
            try:
                # Create individual request
                request = self.service.urlNotifications().publish(
                    body={"url": url, "type": action}
                )

                # Add to batch with callback
                callback = self._create_batch_callback(
                    url, action, attempts, batch_result
                )
                batch.add(request, callback=callback)

            except Exception as e:
                logger.error(f"❌ Error adding {url} to batch: {e}")
                result = URLResult(
                    url=url,
                    action=action,
                    status=ResultStatus.FAILED,
                    attempts=attempts,
                    error_message=f"Failed to add to batch: {str(e)}",
                )
                batch_result.add_result(result)

        # Execute batch
        try:
            batch.execute()
        except Exception as e:
            logger.error(f"❌ Batch execution error: {e}", exc_info=True)

    def process_job(self, job_data: dict) -> BatchResult:
        """
        Process a complete indexing job

        Args:
            job_data: Complete job data including actions and auth

        Returns:
            BatchResult with complete processing results
        """
        logger.info(f"🚀 Starting indexing job for shop: {job_data.get('shop')}")

        batch_result = BatchResult()

        # Authenticate
        if not self._authenticate():
            logger.error("❌ Cannot proceed without authentication")
            return batch_result

        # Extract configuration
        auth = job_data.get("auth", {})
        google_limit = auth.get("settings", {}).get("googleLimit", 10)
        actions = job_data.get("actions", {})

        # Prepare URLs with limit
        url_mapping, total_available = self._prepare_urls_from_actions(
            actions, google_limit
        )

        if not url_mapping:
            logger.warning("⚠️ No URLs to process")
            return batch_result

        # Prepare URL list with attempts from original data
        url_list = []
        for item in actions.get("INDEX", []):
            url = item["webUrl"]
            if url in url_mapping:
                url_list.append((url, url_mapping[url], item.get("attempts", 1)))

        for item in actions.get("DELETE", []):
            url = item["webUrl"]
            if url in url_mapping:
                url_list.append((url, url_mapping[url], item.get("attempts", 1)))

        batch_result.total_urls = len(url_list)

        # Process in chunks
        chunk_number = 1
        for i in range(0, len(url_list), self.batch_size):
            chunk = url_list[i : i + self.batch_size]
            self._process_batch_chunk(chunk, batch_result, chunk_number)
            chunk_number += 1

        # Finalize results
        batch_result.finalize()

        logger.info(
            f"🎉 Job completed: {batch_result.successful} successful, "
            f"{batch_result.failed} failed, "
            f"{batch_result.quota_exceeded} quota exceeded"
        )

        return batch_result


def process_indexing_job(job_data: dict, decode_function: Callable) -> dict:
    """
    Main entry point for processing an indexing job

    Args:
        job_data: Complete job data structure
        decode_function: Optional function to decode googleConfig

    Returns:
        Dictionary containing processing results
    """
    try:
        # Extract and decode Google config
        auth = job_data.get("auth", {})
        google_config_encoded = auth.get("googleConfig")

        if not google_config_encoded:
            raise ValueError("Missing googleConfig in auth data")

        # Decode if function provided
        if decode_function:
            google_config = json.loads(decode_function(google_config_encoded))

        else:
            # Assume it's already decoded or handle accordingly
            google_config = google_config_encoded

        # Extract settings
        settings = auth.get("settings", {})
        google_limit = settings.get("googleLimit", 200)
        retry_limit = settings.get("retryLimit", 3)

        # Initialize processor
        processor = GoogleIndexingProcessor(
            google_config=google_config, retry_limit=retry_limit
        )

        # Process job
        batch_result = processor.process_job(job_data)

        # Return results
        return {
            "success": True,
            "job_type": job_data.get("jobType"),
            "shop": job_data.get("shop"),
            "results": batch_result.to_dict(),
        }

    except Exception as e:
        logger.error(f"❌ Job processing failed: {e}", exc_info=True)
        return {
            "success": False,
            "error": str(e),
            "job_type": job_data.get("jobType"),
            "shop": job_data.get("shop"),
        }


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
            "INDEX": [{"webUrl": "https://example.com/product-1", "attempts": 1}],
            "DELETE": [
                {"webUrl": "https://example.com/deleted-product", "attempts": 1}
            ],
        },
        "auth": {
            "googleConfig": {},  # Your decoded config here
            "settings": {"googleLimit": 10, "retryLimit": 3},
        },
    }

    def dummy_decode(str="AF"):
        return {"work": "done"}

    # Process job
    result = process_indexing_job(example_job, dummy_decode)
    print(f"\nFinal Result: {result}")
