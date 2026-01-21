from google.oauth2 import service_account
from googleapiclient.discovery import build

urls_to_ping = {
    'https://domain.pk/mining-earthmoving/': 'URL_UPDATED',
    'https://domain.pk/power-generation-2/': 'URL_UPDATED'
}

JSON_KEY = "credentials.json"
SCOPES = ["https://www.googleapis.com/auth/indexing"]

# 1. Authorize credentials
credentials = service_account.Credentials.from_service_account_info(
    JSON_KEY, scopes=SCOPES
)

# 2. Build service
# The build() function accepts the modern credentials object directly.
service = build('indexing', 'v3', credentials=credentials)

# 3. Define Callback
def insert_event(request_id, response, exception):
    # Response DataType
    #  {'urlNotificationMetadata': {'url': 'https://domain.pk/power-generation-2/'}}
    if exception is not None:
        print(f"Request ID {request_id} Failed: {exception}")
    else:
        print(f"Request ID {request_id} Success: {response}")


# 4. Create Batch
batch = service.new_batch_http_request(callback=insert_event)

# 5. Add requests to batch
for url, api_type in urls_to_ping.items():
    batch.add(service.urlNotifications().publish(
        body={"url": url, "type": api_type}
    ))

# 6. Execute
print("Executing batch request...")
batch.execute()