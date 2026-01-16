import prisma from "../db.server";
import { StatBox } from "../components/StatBox";
import { authenticate } from "../shopify.server";
import { useState, useEffect, useRef } from "react";
import { ClientOnly } from "../components/ClientOnly";
import { SetupGuide } from "../components/SetupGuide";
import { useLoaderData, useFetcher } from "react-router";
import { boundary } from "@shopify/shopify-app-react-router/server";
import {
  timeAgo,
  getToneFromStatus,
  getActionLabel,
  getTypeFromPath,
  extractPath,
} from "../functions/home";

import { useCallback } from "react";
import { useAppBridge } from "@shopify/app-bridge-react";
import { Redirect } from "@shopify/app-bridge/actions";

export const loader = async ({ request }) => {
  const { session } = await authenticate.admin(request);

  const states = await prisma.shopFeatureStates.findUnique({
    where: { shop: session.shop },
  });

  const pageStates = states?.home ?? {};

  const latest_changes = await prisma.urlEntry.findMany({
    where: {
      shop: session.shop,
    },
    orderBy: {
      lastEventAt: "desc",
    },
    take: 5,
  });
  return { shop: session.shop, entries: latest_changes, states: pageStates };
};

export async function action({ request }) {
  const { session } = await authenticate.admin(request);
  const formData = await request.formData();

  const jsonString = formData.get("states") || "";
  const value = JSON.parse(jsonString);

  const states = await prisma.shopFeatureStates.upsert({
    where: { shop: session.shop },
    update: {
      home: value, // dynamic key to update the page
    },
    create: {
      shop: session.shop,
      home: value, // initial value if shop doesn't exist
    },
  });

  console.log(value);
  return null;
}

export default function Index() {
  const { shop, entries, states } = useLoaderData();

  const fetcher = useFetcher();

  if (!states || Object.keys(states).length === 0) {
    states.setupGuide = true;
    states.featuredApps = true;
  }
  const ITEMS = [
    {
      id: 0,
      title: "Configure Google Service Account",
      description:
        "Enable automated Google indexing and real-time data syncing. Upload your Google Cloud JSON key to start Indexing.",
      image: {
        url: "https://assets.techrepublic.com/uploads/2024/10/tr_20241028-google-cloud-platform-the-smart-persons-guide.jpg",
        alt: "Illustration of secure Google Cloud integration",
      },
      primaryButton: {
        content: "Setup Instructions",
        props: {
          href: "https://www.jcchouinard.com/google-indexing-api-with-python/", // Link to your specific guide
          external: true,
        },
      },
      secondaryButton: {
        content: "Watch Tutorial",
        props: {
          href: "https://youtu.be/_FmsEkF72M0?si=dGqxN-eCIlYueJ9z",
          external: true,
        },
      },
    },
    {
      id: 1,
      title: "Connect Bing Webmaster API",
      description:
        "Enable automated Bing indexing and site insights. Add your Bing Webmaster API key so our app can securely access your Bing data.",
      image: {
        url: "https://cdn.botpenguin.com/assets/website/b6449474_f1fd_4c43_abde_210207c0fe5b_cca210c48a.png",
        alt: "Illustration of secure Bing Webmaster integration",
      },
      primaryButton: {
        content: "Setup Instructions",
        props: {
          href: "https://medium.com/@trungpv1601/how-to-get-your-bing-webmaster-tools-api-key-and-why-you-need-it-e0d791941b5a",
          external: true,
        },
      },
      // secondaryButton: {
      //   content: "Watch Tutorial",
      //   props: {
      //     url: "https://youtube.com/your-bing-webmaster-video",
      //     external: true,
      //   },
      // },
    },

    {
      id: 3,
      title: "Connect your search engine credentials",
      description:
        "Enable automated indexing by finalizing your configuration. Navigate to the app settings to securely upload your Google Service Account JSON, add your Bing API key, and save your preferences.",
      image: {
        href: "https://static.vecteezy.com/system/resources/previews/047/627/764/non_2x/system-settings-icon-perfect-for-configuration-and-preferences-vector.jpg",
        alt: "Illustration of secure settings configuration",
      },
      complete: false,
      primaryButton: {
        content: "Go to Settings",
        props: {
          href: "/app/settings", // Update this to your actual internal settings route
          external: false,
        },
      },
    },
    {
      id: 2,
      title: "Update Product Descriptions",
      description:
        "Improve discoverability by updating the descriptions for your collections and products. After you save changes, visit your Home page to see them appear in Recent Submissions.",
      image: {
        url: "https://static.vecteezy.com/system/resources/previews/063/203/257/non_2x/description-product-dual-tone-icon-sleek-and-modern-icon-for-websites-and-mobile-apps-vector.jpg",
        alt: "Illustration of editing product and collection details",
      },
      // primaryButton: {
      //   content: "Edit Products",
      //   props: {
      //     as: "a",
      //     href: `https://admin.shopify.com/store/${storeName}/products?selectedView=all`,
      //     target: "_top",
      //   },
      // },

      statusBadge: {
        content: "App connected",
        tone: "pending",
      },
      ctaHelperText:
        "Allow a few minutes for updates to propagate to the Home page.",
    },
  ];
  const stats = {
    orders: [13, 20, 18, 50, 8, 15, 23],
    reviews: [13, 3, 5, 6, 5, 2, 8],
    returns: [5, 6, 5, 8, 4, 3, 1],
  };

  // States
  const isInitialized = useRef(false);
  const [visible, setVisible] = useState({
    setupGuide: states.setupGuide,
    featuredApps: states.featuredApps,
  });
  const [guideProgress, setGuideProgress] = useState(
    states?.guideProgress ?? {},
  );
  const [items, setItems] = useState(() => {
    const values = states?.guideProgress ?? {};
    return ITEMS.map((item) => ({
      ...item,
      complete: values[item.id] ?? false,
    }));
  });

  useEffect(() => {
    if (!isInitialized.current) {
      isInitialized.current = true;
      return;
    }

    if (!guideProgress || Object.keys(guideProgress).length === 0) return;

    const fd = new FormData();
    const data = { ...visible, guideProgress: guideProgress };
    fd.append("states", JSON.stringify(data));

    fetcher.submit(fd, { method: "POST" });
  }, [visible, guideProgress]);

  const onStepComplete = async (id) => {
    try {
      // Update state and get latest items
      setItems((prev) => {
        const newItems = prev.map((item) =>
          item.id === id ? { ...item, complete: !item.complete } : item,
        );

        // Build updatedStates from the latest state
        const updatedStates = {};
        newItems.forEach((item) => {
          updatedStates[item.id] = item.complete ?? false;
        });

        // Save to guide progress or DB
        setGuideProgress(updatedStates);

        return newItems;
      });
    } catch (e) {
      console.error(e);
    }
  };

  return (
    <s-page>
      {/* <s-button slot="primary-action">Create puzzle</s-button> */}
      {/* === */}
      {/* Setup Guide */}
      {/* Keep instructions brief and direct. Only ask merchants for required information. */}
      {/* If dismissed, use local storage or a database entry to avoid showing this section again to the same user. */}
      {/* === */}

      {visible.setupGuide && (
        <s-section padding="none">
          <SetupGuide
            onDismiss={() => {
              setVisible({ ...visible, setupGuide: false });
              setItems(ITEMS);
            }}
            onStepComplete={onStepComplete}
            items={items}
          />
        </s-section>
      )}
      {/* === */}
      {/* Metrics cards */}
      {/* Your app homepage should provide merchants with quick statistics or status updates that help them understand how the app is performing for them. */}
      {/* === */}
      <s-section padding="base" paddingBlockStart="large">
        <s-grid gridTemplateColumns="repeat(4, 1fr)" gap="small">
          {/* Card 1 */}
          <s-clickable
            href="#"
            paddingBlock="small-400"
            paddingInline="small-100"
            borderRadius="base"
          >
            <s-grid gap="small-300">
              <s-heading>Total URLs</s-heading>
              <s-stack direction="inline" gap="small-200">
                <s-text>1,247</s-text>
                <s-badge tone="success" icon="arrow-up">
                  12%
                </s-badge>
              </s-stack>
            </s-grid>
          </s-clickable>

          {/* Card 2 */}
          <s-clickable
            href="#"
            paddingBlock="small-400"
            paddingInline="small-100"
            borderRadius="base"
          >
            <s-grid gap="small-300">
              <s-heading>Indexed</s-heading>
              <s-stack direction="inline" gap="small-200">
                <s-text>1,089</s-text>
                <s-badge tone="success" icon="arrow-up">
                  8%
                </s-badge>
              </s-stack>
            </s-grid>
          </s-clickable>

          {/* Card 3 */}
          <s-clickable
            href="#"
            paddingBlock="small-400"
            paddingInline="small-100"
            borderRadius="base"
          >
            <s-grid gap="small-300">
              <s-heading>Pending</s-heading>
              <s-stack direction="inline" gap="small-200">
                <s-text>124</s-text>
                <s-badge tone="warning">15%</s-badge>
              </s-stack>
            </s-grid>
          </s-clickable>

          {/* Card 4 */}
          <s-clickable
            href="#"
            paddingBlock="small-400"
            paddingInline="small-100"
            borderRadius="base"
          >
            <s-grid gap="small-300">
              <s-heading>Failed</s-heading>
              <s-stack direction="inline" gap="small-200">
                <s-text>34</s-text>
                <s-badge tone="critical" icon="arrow-down">
                  5%
                </s-badge>
              </s-stack>
            </s-grid>
          </s-clickable>
        </s-grid>
      </s-section>
      {/* === */}
      {/* Callout Card */}
      {/* If dismissed, use local storage or a database entry to avoid showing this section again to the same user. */}
      {/* === */}
      <s-section
        padding="base"
        accessibilityLabel="URLs table section"
        heading="Recent Submissions"
      >
        <s-table>
          <s-grid slot="filters" gap="small-200" gridTemplateColumns="1fr auto">
            <s-text-field
              label="Search URLs"
              labelAccessibilityVisibility="exclusive"
              icon="search"
              placeholder="Search all URLs"
            />
            <s-button
              icon="sort"
              variant="secondary"
              accessibilityLabel="Sort"
              interestFor="sort-tooltip"
              commandFor="sort-actions"
            />
            <s-tooltip id="sort-tooltip">
              <s-text>Sort</s-text>
            </s-tooltip>
            <s-popover id="sort-actions">
              <s-stack gap="none">
                <s-box padding="small">
                  <s-choice-list label="Sort by" name="Sort by">
                    <s-choice value="url" selected>
                      URL
                    </s-choice>
                    <s-choice value="event">Event</s-choice>
                    <s-choice value="occur-at">Occurred at</s-choice>
                    <s-choice value="status">Status</s-choice>
                  </s-choice-list>
                </s-box>
                <s-divider />
                <s-box padding="small">
                  <s-choice-list label="Order by" name="Order by">
                    <s-choice value="asc" selected>
                      A-Z
                    </s-choice>
                    <s-choice value="desc">Z-A</s-choice>
                  </s-choice-list>
                </s-box>
              </s-stack>
            </s-popover>
          </s-grid>
          <s-table-header-row>
            <s-table-header listSlot="primary">URL</s-table-header>
            <s-table-header>Event</s-table-header>
            <s-table-header>Occurred at</s-table-header>
            <s-table-header listSlot="secondary">Status</s-table-header>
          </s-table-header-row>
          <s-table-body>
            {entries.map((e, i) => {
              const path = extractPath(e.webUrl, e.shop);
              const action = getActionLabel(path, e.indexAction);
              const occurred = timeAgo(new Date(e.lastEventAt));
              const toneInfo = getToneFromStatus(e.status);

              return (
                <s-table-row
                  key={e.id ?? `${path}-${i}`}
                  clickDelegate={`url-${i + 1}-checkbox`}
                >
                  <s-table-cell>
                    <s-stack direction="inline" gap="small" alignItems="center">
                      <s-link>{path}</s-link>
                    </s-stack>
                  </s-table-cell>

                  <s-table-cell>
                    <s-text>{action}</s-text>
                  </s-table-cell>

                  <s-table-cell>{occurred}</s-table-cell>

                  <s-table-cell>
                    <s-badge color="base" tone={toneInfo.tone}>
                      {toneInfo.label}
                    </s-badge>
                  </s-table-cell>
                </s-table-row>
              );
            })}
          </s-table-body>
        </s-table>
        <s-divider />
        <s-stack
          direction="inline"
          alignItems="center"
          justifyContent="center"
          paddingBlockStart="base"
        >
          <s-link href="/app/coming-soon">View all submissions</s-link>
        </s-stack>
      </s-section>
      {false && (
        <ClientOnly>
          <s-box paddingBlock="large">
            <s-stack gap="large">
              {/* Header */}
              <s-stack direction="block" gap="small-500">
                <s-heading>Daily Stats Example</s-heading>
                <s-text color="subdued">
                  Shows rate of change from first entry of chart data to today
                </s-text>
              </s-stack>

              {/* Stats */}
              <s-grid gridTemplateColumns="repeat(3, 1fr)" columnGap="base">
                <s-grid-item>
                  <StatBox
                    title="Orders"
                    value={stats.orders.at(-1)}
                    data={stats.orders}
                  />
                </s-grid-item>

                <s-grid-item>
                  <StatBox
                    title="Reviews"
                    value={stats.reviews.at(-1)}
                    data={stats.reviews}
                  />
                </s-grid-item>

                <s-grid-item>
                  <StatBox
                    title="Returns"
                    value={stats.returns.at(-1)}
                    data={stats.returns}
                  />
                </s-grid-item>
              </s-grid>
            </s-stack>
          </s-box>
        </ClientOnly>
      )}
      {/* === */}
      {/* News */}
      {/* === */}
      <s-section>
        <s-heading>News</s-heading>
        <s-grid
          gridTemplateColumns="repeat(auto-fit, minmax(240px, 1fr))"
          gap="base"
        >
          {/* News item 1 */}
          <s-grid
            background="base"
            border="base"
            borderRadius="base"
            padding="base"
            gap="small-400"
          >
            <s-text>Jan 17, 2026</s-text>
            <s-link href="/app/coming-soon">
              <s-heading>Content Type Selection in Settings</s-heading>
            </s-link>
            <s-paragraph>
              In settings, you can choose the types of content you prefer. Your
              selections will be used when indexing updates, helping the system
              prioritize and organize content.
            </s-paragraph>
          </s-grid>
          {/* News item 2 */}
          <s-grid
            background="base"
            border="base"
            borderRadius="base"
            padding="base"
            gap="small-400"
          >
            <s-text>Dec 31, 2025</s-text>
            <s-link href="/app/coming-soon">
              <s-heading>Full Control via Manual Submission</s-heading>
            </s-link>
            <s-paragraph>
              Take control by manually submitting the URLs that matter most to
              you. Add any important links directly through the URL Submission
              section of the app
            </s-paragraph>
          </s-grid>
        </s-grid>
        <s-stack
          direction="inline"
          alignItems="center"
          justifyContent="center"
          paddingBlockStart="base"
        >
          <s-link href="/app/coming-soon">See all news items</s-link>
        </s-stack>
      </s-section>
      {/* === */}
      {/* Featured apps */}
      {/* If dismissed, use local storage or a database entry to avoid showing this section again to the same user. */}
      {/* === */}
      {visible.featuredApps && (
        <s-section>
          <s-grid
            gridTemplateColumns="1fr auto"
            alignItems="center"
            paddingBlockEnd="small-400"
          >
            <s-heading>Featured apps</s-heading>
            <s-button
              onClick={() => setVisible({ ...visible, featuredApps: false })}
              icon="x"
              tone="neutral"
              variant="tertiary"
              accessibilityLabel="Dismiss featured apps section"
            ></s-button>
          </s-grid>
          <s-grid
            gridTemplateColumns="repeat(auto-fit, minmax(240px, 1fr))"
            gap="base"
          >
            {/* Featured app 1 */}
            <s-clickable
              href="https://apps.shopify.com/flow"
              border="base"
              borderRadius="base"
              padding="base"
              inlineSize="100%"
              accessibilityLabel="Download Shopify Flow"
            >
              <s-grid
                gridTemplateColumns="auto 1fr auto"
                alignItems="stretch"
                gap="base"
              >
                <s-thumbnail
                  size="small"
                  src="https://cdn.shopify.com/app-store/listing_images/15100ebca4d221b650a7671125cd1444/icon/CO25r7-jh4ADEAE=.png"
                  alt="Shopify Flow icon"
                />
                <s-box>
                  <s-heading>Shopify Flow</s-heading>
                  <s-paragraph>Free</s-paragraph>
                  <s-paragraph>
                    Automate everything and get back to business.
                  </s-paragraph>
                </s-box>
                <s-stack justifyContent="start">
                  <s-button
                    href="https://apps.shopify.com/flow"
                    icon="download"
                    accessibilityLabel="Download Shopify Flow"
                  />
                </s-stack>
              </s-grid>
            </s-clickable>
            {/* Featured app 2 */}
            <s-clickable
              href="https://apps.shopify.com/planet"
              border="base"
              borderRadius="base"
              padding="base"
              inlineSize="100%"
              accessibilityLabel="Download Shopify Planet"
            >
              <s-grid
                gridTemplateColumns="auto 1fr auto"
                alignItems="stretch"
                gap="base"
              >
                <s-thumbnail
                  size="small"
                  src="https://cdn.shopify.com/app-store/listing_images/87176a11f3714753fdc2e1fc8bbf0415/icon/CIqiqqXsiIADEAE=.png"
                  alt="Shopify Planet icon"
                />
                <s-box>
                  <s-heading>Shopify Planet</s-heading>
                  <s-paragraph>Free</s-paragraph>
                  <s-paragraph>
                    Offer carbon-neutral shipping and showcase your commitment.
                  </s-paragraph>
                </s-box>
                <s-stack justifyContent="start">
                  <s-button
                    href="https://apps.shopify.com/planet"
                    icon="download"
                    accessibilityLabel="Download Shopify Planet"
                  />
                </s-stack>
              </s-grid>
            </s-clickable>
          </s-grid>
        </s-section>
      )}
    </s-page>
  );
}

export const headers = (headersArgs) => {
  return boundary.headers(headersArgs);
};
