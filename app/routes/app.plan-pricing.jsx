import { useFetcher, useLoaderData } from "react-router";
import { authenticate, MONTHLY_PLAN, ANNUAL_PLAN } from "../shopify.server";

import { PricingCard } from "../components/PricingCard";
import { Accordion } from "../components/Accordion";

export const loader = async ({ request }) => {
  const { session, billing } = await authenticate.admin(request);

  const { hasActivePayment, appSubscriptions } = await billing.check({
    plans: [MONTHLY_PLAN, ANNUAL_PLAN],
    isTest: true,
  });

  return {
    shop: session.shop,
    hasActivePayment,
    activePlan: appSubscriptions?.[0]?.name ?? null,
  };
};

export const action = async ({ request }) => {
  const { billing } = await authenticate.admin(request);
  const formData = await request.formData();
  const plan = formData.get("plan");

  if (plan !== MONTHLY_PLAN && plan !== ANNUAL_PLAN) {
    return { error: "Invalid plan selected" };
  }

  await billing.request({
    plan,
    isTest: true,
  });

  // billing.request() throws a Response redirect to Shopify's confirmation
  // page, so code below this point is not reached.
  return null;
};

export default function PricingPage() {
  const { hasActivePayment, activePlan } = useLoaderData();
  const fetcher = useFetcher();
  const isSubmitting = fetcher.state !== "idle";

  const selectPlan = (plan) => {
    fetcher.submit({ plan }, { method: "POST" });
  };

  const isMonthlyActive = activePlan === MONTHLY_PLAN;
  const isAnnualActive = activePlan === ANNUAL_PLAN;

  const faqData = [
    {
      id: 1,
      title: "Are there limits on how many URLs I can index?",
      content: (
        <s-text>
          All plans include unlimited URL indexing until your indexing engine
          quota is reached. Quotas vary by search engine provider.
        </s-text>
      ),
    },
    {
      id: 2,
      title: "What happens if a URL fails to submit?",
      content: (
        <s-text>
          Our system automatically retries failed URLs. If problems persist,
          contact us at <s-text fontWeight="bold">info@digilogsoftwares.com</s-text> and
          we will help.
        </s-text>
      ),
    },
    {
      id: 3,
      title: "Which types of pages are submitted?",
      content: (
        <s-text>
          We support Products, Collections, Blog Posts, and Shopify Pages.
        </s-text>
      ),
    },
    {
      id: 4,
      title: "Can I switch plans later?",
      content: (
        <s-text>
          Yes. You can upgrade or downgrade at any time. Shopify handles
          prorating automatically.
        </s-text>
      ),
    },
    {
      id: 5,
      title: "Who can I contact for support?",
      content: (
        <s-text>
          Reach our support team at{" "}
          <s-text fontWeight="bold">info@digilogsoftwares.com</s-text>.
        </s-text>
      ),
    },
  ];

  return (
    <s-page
      heading="Choose your plan"
      subheading="Unlock all features and start your 21-day free trial."
    >
      {/* Active plan banner */}
      {hasActivePayment ? (
        <s-banner
          heading={`You're on the ${activePlan} plan`}
          tone="success"
        />
      ) : null}

      {/* Plan cards */}
      <s-box paddingBlockStart="large" paddingBlockEnd="large">
        <s-grid gridTemplateColumns="1fr 1fr 1fr" gap="large">
          <PricingCard
            title="Standard"
            description="Great for stores just starting out with SEO indexing."
            features={[
              "Automatic URL submissions",
              "Retry failed submissions",
              "Manual URL submissions",
              "Submission records",
            ]}
            price="$5"
            frequency="month"
            button={{
              content: isMonthlyActive
                ? "Current plan"
                : isSubmitting
                  ? "Redirecting…"
                  : "Select plan",
              props: {
                variant: isMonthlyActive ? "secondary" : "primary",
                disabled: isMonthlyActive || isSubmitting,
                onClick: () => selectPlan(MONTHLY_PLAN),
              },
            }}
          />
          <PricingCard
            title="Advanced"
            featuredText="Most Popular"
            description="For growing stores that need long-term reliable indexing."
            features={[
              "Up to 10,000 URLs per day",
              "Google and Bing indexing",
              "Submission analytics",
              "AI-powered indexing strategy",
              "24/7 customer support",
            ]}
            price="$50"
            frequency="year"
            button={{
              content: isAnnualActive
                ? "Current plan"
                : isSubmitting
                  ? "Redirecting…"
                  : "Select plan",
              props: {
                variant: isAnnualActive ? "secondary" : "primary",
                disabled: isAnnualActive || isSubmitting,
                onClick: () => selectPlan(ANNUAL_PLAN),
              },
            }}
          />
          <PricingCard
            title="Premium"
            unfeaturedText="Coming Soon"
            description="For high-volume stores with the highest update frequency."
            features={[
              "Up to 100,000 URLs per day",
              "AI-powered SEO strategy",
              "Media content optimization",
              "Advanced ad and audience suggestions",
            ]}
            price="$120"
            frequency="month"
            button={{
              content: "Coming soon",
              props: {
                variant: "primary",
                disabled: true,
              },
            }}
          />
        </s-grid>
      </s-box>

      {/* FAQs */}
      <s-divider />
      <s-box paddingBlockStart="large" paddingBlockEnd="large">
        <s-stack direction="block" gap="large">
          <s-stack direction="block" gap="small">
            <s-heading>Frequently asked questions</s-heading>
            <s-text color="subdued">
              Common questions about plans, indexing quotas, and technical setup.
            </s-text>
          </s-stack>
          <Accordion items={faqData} />
        </s-stack>
      </s-box>
    </s-page>
  );
}
