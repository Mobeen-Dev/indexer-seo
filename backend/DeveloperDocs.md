### **The 2025 Guide to Getting `credentials.json`**

#### **Step 1: Create Project & Enable API**

1. Go to the [Google Cloud Console](https://console.cloud.google.com/).
2. Click the project dropdown (top left) and select **"New Project"**. Give it a name and click **Create**.
3. Select your new project.
4. Go to **APIs & Services > Library** (left menu).
5. Search for **"Indexing API"** (specifically "Web Search Indexing API").
6. Click **Enable**.

#### **Step 2: Create Service Account & Key**

1. Go to **APIs & Services > Credentials**.
2. Click **+ CREATE CREDENTIALS** (top bar) → **Service account**.
3. **Details:** Enter a name (e.g., `indexing-bot`) and click **Create and Continue**.
4. **Permissions:** Select Role: **Current Project > Owner**. Click **Continue** → **Done**.
5. **Generate Key:**
* In the list of service accounts, click the **email address** of the account you just created (e.g., `indexing-bot@project-id.iam.gserviceaccount.com`).
* Go to the **KEYS** tab (top menu).
* Click **ADD KEY** → **Create new key**.
* Select **JSON** and click **Create**.
* **The file will download automatically.** Rename it to `credentials.json` and put it in your script folder.



#### **Step 3: The Critical Step (Google Search Console)**

*If you skip this, you will get a "403 Permission Denied" error.*

1. Open your `credentials.json` file and copy the `client_email` address inside it.
2. Go to [Google Search Console](https://search.google.com/search-console).
3. Select your property (website).
4. Go to **Settings** (bottom left) → **Users and permissions**.
5. Click **Add User**.
6. **Paste the Service Account email** you copied.
7. **Permission:** Set to **Owner**. (Note: "Full" permission often fails for the Indexing API; "Owner" is required).
8. Click **Add**.

---

### **Recommended Reference Articles**

If you prefer a visual guide with screenshots, these are the most reliable current resources:

* **RankMath Guide:** [How to Setup Google Indexing API](https://rankmath.com/blog/google-indexing-api/) (Excellent screenshots even if you don't use WordPress).
* **Detailed Python Guide:** [Step-by-step guide to using the Google Indexing API](https://malyna.top/using-the-google-indexing-api-with-python/)
