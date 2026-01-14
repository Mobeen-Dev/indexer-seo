import prisma from "../db.server";
import { useFetcher } from "react-router";
import { useState, useEffect, useRef } from "react";
import { authenticate } from "../shopify.server";
import { useAppBridge } from "@shopify/app-bridge-react";
import { useLoaderData, useRouteError } from "react-router";

export const loader = async ({ request }) => {
  const { admin, session } = await authenticate.admin(request);

  const auth = await prisma.auth.findUnique({
    where: { shop: session.shop },
  });

  return { shop: session.shop };
};

export async function action({ request }) {
  const { session } = await authenticate.admin(request);
  const formData = await request.formData();

  const urlsRaw = formData.get("urls") || "";
  const urls = urlsRaw
    .split("\n")
    .map((u) => u.trim())
    .filter(Boolean);

  const uniqueUrls = [...new Set(urls)];

  // fetch existing URLs for this shop
  const existing = await prisma.indexTask.findMany({
    where: {
      shop: session.shop,
      url: { in: uniqueUrls },
    },
    select: { url: true },
  });

  const existingSet = new Set(existing.map((e) => e.url));

  // split into create vs update
  const toCreate = uniqueUrls
    .filter((u) => !existingSet.has(u))
    .map((url) => ({
      shop: session.shop,
      url,
      isCompleted: false,
    }));

  const toUpdate = uniqueUrls.filter((u) => existingSet.has(u));

  // run as a single transaction
  const [created, updated] = await prisma.$transaction([
    prisma.indexTask.createMany({
      data: toCreate,
    }),

    prisma.indexTask.updateMany({
      where: {
        shop: session.shop,
        url: { in: toUpdate },
      },
      data: {
        isCompleted: false, // or true depending on meaning
        completedAt: null, // reset if re-queued
      },
    }),
  ]);

  return new Response(
    JSON.stringify({
      success: true,
      enqueuedNew: created.count,
      updatedExisting: updated.count,
      totalInput: uniqueUrls.length,
      message: "URLs queued / updated successfully",
    }),
    {
      status: 200,
      headers: { "Content-Type": "application/json" },
    },
  );
}

export default function AddURLsPage() {
  const { shop } = useLoaderData();
  const fetcher = useFetcher();
  const shopify = useAppBridge();

  const shownRef = useRef(false);
  const [urlCount, setUrlCount] = useState(0);
  const [urls, setUrls] = useState("");
  const [validated, setValidated] = useState(false);
  const [visible, setVisible] = useState({
    banner: true,
    helpCard: true,
  });

  useEffect(() => {
    setUrlCount(
      urls.trim()
        ? urls
            .trim()
            .split("\n")
            .filter((url) => url.trim()).length
        : 0,
    );
  }, [urls]);

  useEffect(() => {
    if (!fetcher) return;

    if (fetcher.state === "loading" || fetcher.state === "submitting") {
      shownRef.current = false;
      return;
    }

    const data = fetcher.data;

    if (!data || shownRef.current) return;

    if (data.success) {
      const total = (data.enqueuedNew ?? 0) + (data.updatedExisting ?? 0);

      shopify.toast.show(`${total} URLs saved successfully`);
      handleClearAll();
    } else if (data.message) {
      shopify.toast.show(data.message);
    }

    shownRef.current = true;
  }, [fetcher.state, fetcher.data, shopify]);

  const handleValidateURLs = () => {
    console.log("Validating URLs...");

    const lines = urls
      .split(/[\s,]+|(?=https?:\/\/)/) // Split on whitespace/comma OR just before 'http(s)'
      .map((l) => l.trim()) // Trim whitespace
      .filter(Boolean); // Remove blanks

    const cleaned = [];
    const invalid = [];

    for (const line of lines) {
      try {
        // RFC-3986 parsing
        const u = new URL(line);

        // must match current shop domain exactly
        if (u.hostname !== shop) {
          invalid.push(line);
          continue;
        }

        // strip query params and fragment
        const normalized = `${u.protocol}//${u.hostname}${u.pathname}`;

        cleaned.push(normalized);
      } catch {
        // failed RFC-3986 parsing = invalid
        invalid.push(line);
      }
    }

    // make URLs unique while preserving order
    const unique = [...new Set(cleaned)];
    // update textarea with cleaned URLs
    setUrls(unique.join("\n"));

    // optional debug
    console.log("Valid:", cleaned);
    console.log("Invalid:", invalid);

    setValidated(true);
  };

  const handleSubmitForIndexing = () => {
    console.log("Submitting URLs for indexing...");

    const fd = new FormData();
    fd.append("urls", urls);

    fetcher.submit(fd, { method: "POST" });
  };

  const handleClearAll = () => {
    setUrls("");
    console.log("Cleared all URLs");
  };

  const handleImportFromFile = () => {
    console.log("Opening file import dialog...");
    // Your file import logic here
  };

  const handleExportTemplate = () => {
    console.log("Exporting template...");
    // Your template export logic here
  };

  return (
    <s-page>
      <s-button slot="primary-action" onClick={handleSubmitForIndexing}>
        Submit for Indexing
      </s-button>
      <s-button slot="secondary-actions" onClick={handleValidateURLs}>
        Validate URLs
      </s-button>

      <s-stack gap="base">
        {/* Info Banner */}
        {visible.banner && (
          <s-banner
            tone="info"
            dismissible
            onDismiss={() => setVisible({ ...visible, banner: false })}
          >
            Add one URL per line. You can add up to 500 URLs at once.{" "}
            <s-link href="#">Learn more about URL requirements</s-link>
          </s-banner>
        )}

        {/* Main Input Section */}
        <fetcher.Form
          method="post"
          // onSubmit={handleSubmitForIndexing}
          // onReset={handleFormReset}
          // data-save-bar
        >
          <s-section heading="Add URLs for Indexing">
            <s-stack gap="base" direction="vertical">
              <s-paragraph>
                Enter the URLs you want to submit for indexing. Each URL should
                be on a separate line. Make sure URLs are properly formatted
                (e.g., https://example.com/page).
              </s-paragraph>

              {/* URL Counter */}
              <s-box padding="small" background="subdued" borderRadius="base">
                <s-stack gap="small-200" direction="inline" align="center">
                  <s-text weight="bold">URLs entered:</s-text>
                  <s-badge tone={urlCount > 0 ? "success" : "info"}>
                    {urlCount} {urlCount === 1 ? "URL" : "URLs"}
                  </s-badge>
                  {urlCount > 500 && (
                    <s-badge tone="critical">Exceeds limit (500 max)</s-badge>
                  )}
                </s-stack>
              </s-box>

              {/* Textarea */}
              <s-text-area
                label="URLs"
                name="urls"
                value={urls}
                onInput={(e) => setUrls(e.currentTarget.value)}
                placeholder="https://example.com/products/item-1&#10;https://example.com/collections/collection-1&#10;https://example.com/blog/post-1&#10;https://example.com/page/about"
                rows="12"
                helpText="Enter one URL per line. Paste multiple URLs at once."
              />

              {/* Action Buttons */}
              <s-stack gap="small-200" direction="inline">
                <s-button
                  variant="primary"
                  onClick={handleSubmitForIndexing}
                  disabled={!validated || urlCount === 0 || urlCount > 500}
                >
                  Submit{" "}
                  {urlCount > 0 &&
                    `${urlCount} URL${urlCount !== 1 ? "s" : ""}`}{" "}
                  for Indexing
                </s-button>
                <s-button
                  onClick={handleValidateURLs}
                  disabled={urlCount === 0}
                >
                  Validate URLs
                </s-button>
                <s-button
                  variant="tertiary"
                  tone="critical"
                  onClick={handleClearAll}
                  disabled={urlCount === 0}
                >
                  Clear All
                </s-button>
              </s-stack>
            </s-stack>
          </s-section>
        </fetcher.Form>

        {/* Quick Tips */}
        <s-section heading="Tips for Better Indexing">
          <s-grid
            gridTemplateColumns="repeat(auto-fit, minmax(240px, 1fr))"
            gap="base"
          >
            {/* Tip 1 */}
            {/* <s-box
            background="subdued"
            border="base"
            borderRadius="base"
            padding="base"
          >
            <s-stack gap="small-200" direction="vertical">
              <s-stack gap="small-300" direction="inline" align="center">
                <s-icon name="check-circle" tone="success" />
                <s-text weight="bold">Use Full URLs</s-text>
              </s-stack>
              <s-text size="small">
                Always include the protocol (https://) and complete domain name
                in your URLs.
              </s-text>
            </s-stack>
          </s-box> */}

            {/* Tip 1 */}
            <s-box
              background="subdued"
              border="base"
              borderRadius="base"
              padding="base"
            >
              <s-stack gap="small-200" direction="vertical">
                {/* HEADING: Added justify="center" to center the row */}
                <s-stack gap="small-300" direction="inline">
                  <s-icon type="check-circle" tone="success" />
                  {/* Text is already bold, but ensure it's not overridden */}
                  <s-text weight="bold">Use Full URLs</s-text>
                </s-stack>

                {/* Description: Added align="center" to center the text below */}
                <s-text size="small" align="center">
                  Always include the protocol (https://) and complete domain
                  name in your URLs.
                </s-text>
              </s-stack>
            </s-box>

            {/* Tip 3 */}
            <s-box
              background="subdued"
              border="base"
              borderRadius="base"
              padding="base"
            >
              <s-stack gap="small-200" direction="vertical">
                <s-stack gap="small-300" direction="inline" align="center">
                  <s-icon type="image-magic" tone="warning" />
                  <s-text weight="bold">Page Visibility</s-text>
                </s-stack>
                <s-text size="small">
                  Rich media improve your page discovery rates & priorities by
                  Search engines
                </s-text>
              </s-stack>
            </s-box>

            {/* Tip 2 */}
            <s-box
              background="subdued"
              border="base"
              borderRadius="base"
              padding="base"
            >
              <s-stack gap="small-200" direction="vertical">
                <s-stack gap="small-300" direction="inline" align="center">
                  <s-icon type="clock" tone="info" />
                  <s-text weight="bold">Processing Time</s-text>
                </s-stack>
                <s-text size="small">
                  URLs typically process within 24-48 hours. Check the dashboard
                  for status updates.
                </s-text>
              </s-stack>
            </s-box>
          </s-grid>
        </s-section>
      </s-stack>
    </s-page>
  );
}
