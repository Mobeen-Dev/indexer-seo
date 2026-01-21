import json
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# --- Configuration ---
SCOPES = ["https://www.googleapis.com/auth/indexing"]

# Ideally, load this from a secure environment variable or a file
key_dict = {
}


def get_indexing_service(key_info):
    """
    Authenticates and builds the Google Indexing Service.
    """
    try:
        credentials = service_account.Credentials.from_service_account_info(
            key_info, scopes=SCOPES
        )
        # Build the service object
        service = build("indexing", "v3", credentials=credentials)
        return service
    except Exception as e:
        print(f"❌ Auth Failed: {e}")
        return None


def batch_callback(request_id, response, exception):
    """
    Callback function to handle the response for each request in the batch.
    """
    if exception is not None:
        # Handle specific API errors here
        if isinstance(exception, HttpError):
            print(
                f"⚠️ Request ID {request_id} Failed: {exception.resp.status} - {exception.content}"
            )
        else:
            print(f"⚠️ Request ID {request_id} Failed: {exception}")
    else:
        # Success response
        url = response.get("urlNotificationMetadata", {}).get("url", "Unknown URL")
        print(f"✅ Success: {url}")


def process_batch(service, url_data):
    """
    Splits data into chunks and executes batch requests.
    """
    # Google Batch Limit is generally 1000 requests per batch.
    # We use 100 to be safe and manageable.
    BATCH_SIZE = 100

    # Convert dictionary items to a list for chunking
    items = list(url_data.items())

    for i in range(0, len(items), BATCH_SIZE):
        chunk = items[i : i + BATCH_SIZE]
        print(
            f"--- Processing Batch Chunk {i // BATCH_SIZE + 1} ({len(chunk)} URLs) ---"
        )

        batch = service.new_batch_http_request(callback=batch_callback)

        for url, api_type in chunk:
            # Create the request object (don't execute it yet)
            request = service.urlNotifications().publish(
                body={"url": url, "type": api_type}
            )
            # Add to batch
            batch.add(request)

        # Execute the batch (Blocks until all requests in this chunk are done)
        try:
            batch.execute()
        except Exception as e:
            print(f"❌ Batch Execution Error: {e}")


# --- Main Execution ---
if __name__ == "__main__":
    # 1. Mock Data (Replace with your actual data source)
    # Ensure your JSON_KEY is loaded into a dictionary variable named 'key_dict'

    urls_to_ping = {
        "https://weldingsolution.pk/power-generation-1/": "URL_UPDATED",
        "https://weldingsolution.pk/power-generation-2/": "URL_UPDATED",
        "https://weldingsolution.pk/deleted-page/": "URL_DELETED",
        # ... imagine 500 more URLs here
    }

    # 2. Build Service
    print("🔑 Authenticating...")
    service = get_indexing_service(key_dict)

    if "service" in locals() and service:
        # 3. Process
        process_batch(service, urls_to_ping)
        print("🎉 All batches completed.")
    else:
        print("⚠️ Service not initialized. Check credentials.")
