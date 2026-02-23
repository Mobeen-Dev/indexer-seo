# Indexer SEO

**Indexer SEO** is a high-performance Shopify App designed to accelerate search engine indexing for your store's pages. By leveraging the **Google Indexing API** and **Bing Webmaster Tools**, it ensures that your product updates, new collections, and content changes are reflected in search results almost instantly.

This project is architected as a hybrid application consisting of a **Shopify Remix Frontend** for the merchant interface and a robust **FastAPI Backend** for handling heavy indexing jobs, background workers, and API integrations.

---

## 🚀 Key Features

*   **Instant Indexing**: Real-time submission of URLs to Google and Bing immediately after they are created or updated.
*   **Background Workers**: Dedicated Python workers to handle bulk indexing requests without blocking the user interface.
*   **Automatic Sync**: Listens to Shopify Webhooks (Products, Collections) to automatically trigger indexing updates.
*   **Status Monitoring**: Track the status of your submissions and view API quotas directly.
*   **Dual-Stack Architecture**: optimized for performance with a React-based Admin UI and a Python-based processing engine.

---

## 🛠 Tech Stack

### Frontend (Shopify App)
*   **Framework**: [Remix](https://remix.run/) (React Router v7)
*   **Platform**: Shopify App Bridge & Polaris UI
*   **Build Tool**: Vite
*   **Database (App Support)**: Prisma with SQLite/PostgreSQL
*   **Language**: TypeScript / JavaScript

### Backend (Indexing Engine)
*   **Framework**: [FastAPI](https://fastapi.tiangolo.com/) (Python)
*   **Queue/Broker**: Redis
*   **Database**: PostgreSQL (local Docker or managed) via asyncpg/SQLAlchemy
*   **APIs**: Google Indexing API, Bing Webmaster API
*   **Task Management**: Asyncio Background Tasks

---

## 📦 Project Structure

The project is divided into two main directories:

*   **`/app`**: Contains the Shopify App frontend code (Remix/React). This is where the merchant UI lives.
*   **`/backend`**: Contains the Python FastAPI service, worker scripts, and indexing logic.

---

## 📋 Prerequisites

Before you begin, ensure you have the following installed:

*   **Node.js** (v20.19+ recommended)
*   **Python** (v3.10+)
*   **Docker & Docker Compose** (Optional, for easier backend execution)
*   **Shopify Partner Account**: To create an app and get API credentials.
*   **Google Cloud Service Account**: A JSON key file with permission to the Indexing API.

---

## ⚡ Installation & Setup

### 1. Clone the Repository
```bash
git clone <repository-url>
cd indexer-seo
```

### 2. Backend Setup (Python)

The backend handles the actual API communication with search engines.

#### **Option A: Using Docker (Recommended)**
Ensure you have your Google credentials saved as `backend/credentials.json`.

```bash
cd backend
docker-compose up --build
```

#### **Option B: Manual Setup**
1.  Navigate to the backend directory:
    ```bash
    cd backend
    ```
2.  Create a virtual environment:
    ```bash
    python -m venv .venv
    # Windows
    .venv\Scripts\activate
    # Mac/Linux
    source .venv/bin/activate
    ```
3.  Install dependencies:
    ```bash
    pip install -r requirements.txt
    ```
4.  Configure Environment:
    Create a `.env` file in `/backend` (see `.env.example` if available) and add your database/redis configs.
5.  **Important**: Place your Google Service Account key file in `backend/credentials.json`.
6.  Run the server:
    ```bash
    python server.py
    ```

### 3. Frontend Setup (Shopify App)

1.  Navigate to the project root (if not already there):
    ```bash
    cd ..
    ```
2.  Install Node dependencies:
    ```bash
    npm install
    ```
3.  Generate Prisma Client:
    ```bash
    npm run setup
    ```

### 4. Running the Complete App

To start the Shopify App development server (which connects to your development store):

```bash
npm run dev
```

*   Press `p` in the terminal to open your provider's preview URL.
*   Install the app on your Shopify Development Store.

---

## 🔧 Google Indexing API Setup (Critical)

1.  Go to the [Google Cloud Console](https://console.cloud.google.com/).
2.  Create a new project.
3.  Enable the **Indexing API**.
4.  Create a **Service Account** and download the JSON key.
5.  **Rename** this file to `credentials.json` and place it in the `backend/` folder.
6.  **Verify Ownership**: Go to [Google Search Console](https://search.google.com/search-console), add your property, and **add the Service Account email** (found in the JSON file) as an **Owner** or **Full User** in the Search Console settings.

---

## 🛡 License

This project is licensed for private use. Contact the author for distribution rights.
