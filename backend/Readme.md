# Google Indexing API – Overview

The Google Indexing API allows you to notify Google about changes to specific URLs and retrieve metadata about previously submitted URLs. It is primarily designed for pages with **job postings** or **live stream content**, but it can be used experimentally for other URL types.

## What You Can Do with the Indexing API

The Indexing API supports the following actions:

* **Publish updates** for specific URLs
* **Retrieve information** about the latest changes to a URL
* **Send batch requests** for multiple URLs at once

---

## API Endpoints

### Publishing Endpoint

Use this endpoint to notify Google of URL updates or deletions.

**HTTP Method:** `POST`
**Endpoint:**

```
https://indexing.googleapis.com/v3/urlNotifications:publish
```

#### Request Body Parameters

* `URL_UPDATED` — Notifies Google that the URL has been updated and should be reindexed
* `URL_DELETED` — Requests removal of the URL from Google’s index

---

### Metadata Endpoint

Use this endpoint to retrieve information about the most recent indexing request made for a specific URL.

**HTTP Method:** `GET`
**Endpoint:**

```
https://indexing.googleapis.com/v3/urlNotifications/metadata
```

---

### Batch Requests Endpoint

Use this endpoint to send multiple indexing requests in a single batch.

**HTTP Method:** `POST`
**Endpoint:**

```
https://indexing.googleapis.com/batch
```

Batch requests can include up to **100 URLs per batch**.

---

## Indexing API Quotas

Google enforces daily usage limits on the Indexing API:

* **Default quota:** 200 requests per day
* **Batch requests:** Up to 100 URLs per request
* **Effective maximum:** 20,000 URLs per day using batch requests

If you need a higher quota, you must submit a quota increase request through the Google Cloud Console.

---

## Common Indexing API Errors

Below are the most frequently encountered errors when working with the Indexing API:

* **403 – PERMISSION_DENIED**
  Possible causes:

  * Insufficient access permissions
  * Indexing API not enabled in the Google Cloud Console

* **429 – RESOURCE_EXHAUSTED**

  * Rate limit exceeded or daily quota exhausted

* **400 – INVALID_ARGUMENT**

  * The request body is malformed or does not follow the required format

Refer to Google’s official documentation for a complete list of Indexing API errors.

---

## Indexing API ≠ Guaranteed Indexing

Submitting a URL via the Indexing API **does not guarantee** that the URL will be indexed.

While URLs submitted through the API are typically prioritized over standard crawling, Google still applies its own evaluation criteria. Some URLs may be delayed, deprioritized, or ignored altogether—especially if they are considered low quality or spammy.

As Google’s Martin Splitt explained during the *Future of SEO – Search Off the Record* session:

> *“Pushing it to the API doesn’t mean that it gets indexed right away or indexed at all. There will be delays, there will be scheduling, and there will be dismissal of spammy or bad URLs.”*
> — **Martin Splitt, Google**

### Practical Observation

To validate this behavior, a small experiment was conducted using the Indexing API to force updates on pages marked as **“Crawled – currently not indexed.”**
The results confirmed that API submission alone does not guarantee immediate or eventual indexing.