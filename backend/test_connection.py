from google.oauth2 import service_account
from google.auth.transport.requests import AuthorizedSession
import json

# Configuration
target_url = "https://weldingsolution.pk/contact-us/"
JSON_KEY_FILE = "credentials.json"

# Paste your full JSON content inside these triple quotes
JSON_KEY = {
  "type": "service_account",
  "project_id": "your-project-id",
  "private_key_id": "your-private-key-id",
  "private_key": "-----BEGIN PRIVATE KEY-----\n...YOUR_KEY_HERE...\n-----END PRIVATE KEY-----\n",
  "client_email": "your-email@your-project.iam.gserviceaccount.com",
  "client_id": "123456789",
  "auth_uri": "https://accounts.google.com/o/oauth2/auth",
  "token_uri": "https://oauth2.googleapis.com/token",
  "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
  "client_x509_cert_url": "https://www.googleapis.com/robot/v1/metadata/x509/your-email"
}


# Note: The new library expects a LIST of scopes, not a string
SCOPES = ["https://www.googleapis.com/auth/indexing"]
ENDPOINT = "https://indexing.googleapis.com/v3/urlNotifications:publish"

try:
    # 1. Load and Authorize Credentials
    # We use from_service_account_file instead of from_json_keyfile_name
    # credentials = service_account.Credentials.from_service_account_file(
    #     JSON_KEY_FILE,
    #     scopes=SCOPES
    # )

    credentials = service_account.Credentials.from_service_account_info(
        JSON_KEY, scopes=SCOPES
    )

    # 2. Build the Authorized Session
    # This replaces credentials.authorize(httplib2.Http()).
    # It acts exactly like a standard 'requests' session but handles auth automatically.
    http = AuthorizedSession(credentials)

    # 3. Build the request body
    print(f"Notifying for: {target_url}")
    content = {"url": target_url, "type": "URL_UPDATED"}

    # 4. Make the Request
    # Note: We use .post() with the 'json' parameter.
    # This automatically handles json.dumps and setting Content-Type headers.
    response = http.post(ENDPOINT, json=content)

    # 5. Parse Response
    # The response object has a .status_code and .json() method built-in
    print(f"Status Code: {response.status_code}")
    result = response.json()

    print("Result:")
    print(json.dumps(result, indent=2))

except Exception as e:
    print(f"An error occurred: {e}")
