import { redirect, Form, useLoaderData } from "react-router";
import { login } from "../../shopify.server";
import styles from "./styles.module.css";

export const loader = async ({ request }) => {
  const url = new URL(request.url);

  if (url.searchParams.get("shop")) {
    throw redirect(`/app?${url.searchParams.toString()}`);
  }

  return { showForm: Boolean(login) };
};

export default function App() {
  const { showForm } = useLoaderData();

  const features = [
    {
      icon: "🤖",
      title: "Automatic URL Submission",
      description: "Submit up to 10,000 URLs daily with intelligent automation",
    },
    {
      icon: "🔄",
      title: "Smart Retry Logic",
      description:
        "Automatically retry failed submissions with exponential backoff",
    },
    {
      icon: "⚡",
      title: "AI-Powered Strategy",
      description:
        "Machine learning optimizes submission timing and prioritization",
    },
    {
      icon: "📊",
      title: "Real-time Analytics",
      description: "Track submission success rates and indexing performance",
    },
    {
      icon: "🌐",
      title: "Multi-Platform Support",
      description: "Works with Google Search Console and Bing Webmaster Tools",
    },
    {
      icon: "🕐",
      title: "24/7 Support",
      description: "Round-the-clock assistance for your indexing needs",
    },
  ];

  const steps = [
    {
      step: "1",
      title: "Connect Your Search Console",
      description:
        "Securely link your Google Search Console or Bing Webmaster Tools account",
      icon: "🔗",
    },
    {
      step: "2",
      title: "Submit Your URLs",
      description:
        "Upload URLs manually or import from sitemap. Our AI prioritizes based on content freshness",
      icon: "📤",
    },
    {
      step: "3",
      title: "Monitor & Analyze",
      description:
        "Track submission status, indexing progress, and performance metrics in real-time",
      icon: "📈",
    },
  ];

  return (
    <div className="landing-page">
      <style>{`
        * {
          margin: 0;
          padding: 0;
          box-sizing: border-box;
        }

        .landing-page {
          font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
          color: #202223;
          background: #f6f6f7;
          line-height: 1.6;
        }

        .container {
          max-width: 1200px;
          margin: 0 auto;
          padding: 0 20px;
        }

        /* Hero Section */
        .hero-section {
          background: linear-gradient(135deg, #008060 0%, #004c3f 100%);
          color: white;
          padding: 80px 20px;
          text-align: center;
        }

        .hero-content {
          display: flex;
          flex-direction: column;
          align-items: center;
          gap: 32px;
        }

        .badge {
          display: inline-flex;
          align-items: center;
          gap: 8px;
          background: rgba(255, 255, 255, 0.2);
          backdrop-filter: blur(10px);
          padding: 8px 16px;
          border-radius: 24px;
          font-size: 14px;
          font-weight: 600;
          border: 1px solid rgba(255, 255, 255, 0.3);
        }

        .badge-icon {
          font-size: 18px;
        }

        .hero-title {
          font-size: 56px;
          font-weight: 700;
          line-height: 1.1;
          margin: 0;
          max-width: 800px;
        }

        .hero-description {
          font-size: 20px;
          max-width: 600px;
          opacity: 0.95;
          line-height: 1.6;
        }

        /* Login Form Styles */
        .login-form-wrapper {
          width: 100%;
          max-width: 480px;
          margin: 0 auto;
        }

        .login-form {
          background: white;
          padding: 32px;
          border-radius: 12px;
          box-shadow: 0 4px 24px rgba(0, 0, 0, 0.15);
        }

        .form-group {
          margin-bottom: 20px;
        }

        .form-label {
          display: block;
        }

        .label-text {
          display: block;
          font-weight: 600;
          color: #202223;
          margin-bottom: 8px;
          font-size: 14px;
        }

        .form-input {
          width: 100%;
          padding: 12px 16px;
          border: 1.5px solid #c9cccf;
          border-radius: 8px;
          font-size: 16px;
          transition: all 0.2s ease;
          background: white;
          color: #202223;
        }

        .form-input:focus {
          outline: none;
          border-color: #008060;
          box-shadow: 0 0 0 3px rgba(0, 128, 96, 0.1);
        }

        .form-input::placeholder {
          color: #8c9196;
        }

        .helper-text {
          display: block;
          font-size: 13px;
          color: #6d7175;
          margin-top: 8px;
        }

        /* Stats Grid */
        .stats-grid {
          display: grid;
          grid-template-columns: repeat(3, 1fr);
          gap: 24px;
          width: 100%;
          max-width: 900px;
        }

        .stat-card {
          background: rgba(255, 255, 255, 0.15);
          backdrop-filter: blur(10px);
          padding: 32px;
          border-radius: 12px;
          border: 1px solid rgba(255, 255, 255, 0.2);
          text-align: center;
        }

        .stat-value {
          font-size: 48px;
          font-weight: 700;
          margin-bottom: 8px;
        }

        .stat-label {
          font-size: 16px;
          opacity: 0.9;
        }

        /* Features Section */
        .features-section {
          padding: 80px 20px;
          background: white;
        }

        .section-title {
          font-size: 40px;
          font-weight: 700;
          text-align: center;
          margin-bottom: 48px;
          color: #202223;
        }

        .features-grid {
          display: grid;
          grid-template-columns: repeat(3, 1fr);
          gap: 32px;
        }

        .feature-card {
          padding: 32px;
          background: #f6f6f7;
          border-radius: 12px;
          border: 1px solid #e1e3e5;
          transition: all 0.3s ease;
        }

        .feature-card:hover {
          transform: translateY(-4px);
          box-shadow: 0 8px 24px rgba(0, 0, 0, 0.1);
          border-color: #008060;
        }

        .feature-icon {
          font-size: 48px;
          margin-bottom: 16px;
        }

        .feature-title {
          font-size: 20px;
          font-weight: 600;
          margin-bottom: 12px;
          color: #202223;
        }

        .feature-description {
          color: #6d7175;
          font-size: 16px;
          line-height: 1.6;
        }

        /* How It Works Section */
        .how-it-works-section {
          padding: 80px 20px;
          background: #f6f6f7;
        }

        .steps-container {
          display: flex;
          flex-direction: column;
          gap: 24px;
          max-width: 900px;
          margin: 0 auto;
        }

        .step-card {
          display: flex;
          gap: 24px;
          background: white;
          padding: 32px;
          border-radius: 12px;
          border: 1px solid #e1e3e5;
          align-items: center;
        }

        .step-number {
          min-width: 60px;
          height: 60px;
          background: #008060;
          color: white;
          border-radius: 12px;
          display: flex;
          align-items: center;
          justify-content: center;
          font-size: 28px;
          font-weight: 700;
        }

        .step-content {
          flex: 1;
        }

        .step-header {
          display: flex;
          align-items: center;
          gap: 12px;
          margin-bottom: 12px;
        }

        .step-icon {
          font-size: 24px;
        }

        .step-title {
          font-size: 20px;
          font-weight: 600;
          color: #202223;
        }

        .step-description {
          color: #6d7175;
          font-size: 16px;
          line-height: 1.6;
        }

        /* Benefits Section */
        .benefits-section {
          padding: 80px 20px;
          background: white;
        }

        .benefits-banner {
          background: linear-gradient(135deg, #e3f5f0 0%, #d4f1e8 100%);
          padding: 48px;
          border-radius: 12px;
          border: 2px solid #b3e0d4;
        }

        .benefits-title {
          font-size: 28px;
          font-weight: 700;
          margin-bottom: 24px;
          color: #202223;
        }

        .benefits-list {
          list-style: none;
          display: flex;
          flex-direction: column;
          gap: 16px;
        }

        .benefit-item {
          display: flex;
          align-items: flex-start;
          gap: 12px;
          font-size: 16px;
          color: #202223;
        }

        .check-icon {
          color: #008060;
          font-weight: 700;
          font-size: 20px;
          flex-shrink: 0;
        }

        /* CTA Section */
        .cta-section {
          padding: 80px 20px;
          background: #f6f6f7;
        }

        .cta-card {
          background: linear-gradient(135deg, #f6f6f7 0%, #e8e9eb 100%);
          padding: 64px 48px;
          border-radius: 16px;
          text-align: center;
          border: 1px solid #e1e3e5;
        }

        .cta-title {
          font-size: 40px;
          font-weight: 700;
          margin-bottom: 16px;
          color: #202223;
        }

        .cta-description {
          font-size: 18px;
          color: #6d7175;
          max-width: 600px;
          margin: 0 auto 32px;
        }

        .cta-buttons {
          display: flex;
          gap: 16px;
          justify-content: center;
          margin-bottom: 32px;
        }

        /* Buttons */
        .btn {
          padding: 14px 24px;
          border: none;
          border-radius: 8px;
          font-size: 16px;
          font-weight: 600;
          cursor: pointer;
          transition: all 0.2s ease;
          font-family: inherit;
        }

        .btn-primary {
          background: #008060;
          color: white;
        }

        .btn-primary:hover {
          background: #006e52;
          transform: translateY(-2px);
          box-shadow: 0 4px 12px rgba(0, 128, 96, 0.3);
        }

        .btn-secondary {
          background: white;
          color: #202223;
          border: 1.5px solid #c9cccf;
        }

        .btn-secondary:hover {
          background: #f6f6f7;
          border-color: #8c9196;
        }

        .btn-large {
          padding: 16px 32px;
          font-size: 18px;
        }

        .cta-features {
          display: flex;
          gap: 32px;
          justify-content: center;
          flex-wrap: wrap;
        }

        .cta-feature {
          display: flex;
          align-items: center;
          gap: 8px;
          color: #6d7175;
          font-size: 14px;
        }

        /* Responsive */
        @media (max-width: 768px) {
          .hero-title {
            font-size: 36px;
          }

          .stats-grid,
          .features-grid {
            grid-template-columns: 1fr;
          }

          .step-card {
            flex-direction: column;
            text-align: center;
          }

          .step-header {
            justify-content: center;
          }

          .cta-buttons {
            flex-direction: column;
          }

          .cta-features {
            flex-direction: column;
            gap: 12px;
          }
        }
      `}</style>

      {/* Hero Section */}
      <section className="hero-section">
        <div className="container">
          <div className="hero-content">
            <div className="badge">
              <span className="badge-icon">⚡</span>
              AI-Powered
            </div>

            <h1 className="hero-title">Intelligent URL Indexing Engine</h1>

            <p className="hero-description">
              Automate your SEO workflow with our advanced AI-powered indexing
              platform. Submit thousands of URLs daily and track performance in
              real-time.
            </p>

            {/* Add your login form here with showForm condition */}
            <div className="login-form-wrapper">
              {showForm && (
                <Form method="post" action="/auth/login">
                  <div className="login-form">
                    <div className="form-group">
                      <label className="form-label">
                        <span className="label-text">Shop domain</span>
                        <input
                          className="form-input"
                          type="text"
                          name="shop"
                          placeholder="my-shop-domain.myshopify.com"
                          required
                        />
                        <span className="helper-text">
                          e.g: my-shop-domain.myshopify.com
                        </span>
                      </label>
                    </div>

                    <button className="btn btn-primary" type="submit">
                      Log in
                    </button>
                  </div>
                </Form>
              )}
            </div>

            {/* Stats Grid */}
            <div className="stats-grid">
              <div className="stat-card">
                <div className="stat-value">10K</div>
                <div className="stat-label">URLs per day</div>
              </div>
              <div className="stat-card">
                <div className="stat-value">99.9%</div>
                <div className="stat-label">Success Rate</div>
              </div>
              <div className="stat-card">
                <div className="stat-value">24/7</div>
                <div className="stat-label">Monitoring</div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* Features Section */}
      <section className="features-section">
        <div className="container">
          <h2 className="section-title">Powerful Features</h2>

          <div className="features-grid">
            {features.map((feature, index) => (
              <div key={index} className="feature-card">
                <div className="feature-icon">{feature.icon}</div>
                <h3 className="feature-title">{feature.title}</h3>
                <p className="feature-description">{feature.description}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* How It Works */}
      <section className="how-it-works-section">
        <div className="container">
          <h2 className="section-title">How It Works</h2>

          <div className="steps-container">
            {steps.map((step, index) => (
              <div key={index} className="step-card">
                <div className="step-number">{step.step}</div>
                <div className="step-content">
                  <div className="step-header">
                    <span className="step-icon">{step.icon}</span>
                    <h3 className="step-title">{step.title}</h3>
                  </div>
                  <p className="step-description">{step.description}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Benefits Banner */}
      <section className="benefits-section">
        <div className="container">
          <div className="benefits-banner">
            <h3 className="benefits-title">Why Choose Our Platform?</h3>
            <ul className="benefits-list">
              <li className="benefit-item">
                <span className="check-icon">✓</span>
                <span>
                  <strong>Unlimited URL indexing</strong> until your search
                  engine quota is reached
                </span>
              </li>
              <li className="benefit-item">
                <span className="check-icon">✓</span>
                <span>
                  <strong>AI-powered optimization</strong> learns from your
                  site's indexing patterns
                </span>
              </li>
              <li className="benefit-item">
                <span className="check-icon">✓</span>
                <span>
                  <strong>Automatic retry logic</strong> ensures maximum success
                  rate
                </span>
              </li>
              <li className="benefit-item">
                <span className="check-icon">✓</span>
                <span>
                  <strong>Detailed analytics</strong> to track performance and
                  ROI
                </span>
              </li>
            </ul>
          </div>
        </div>
      </section>

      {/* CTA Section */}
      <section className="cta-section">
        <div className="container">
          <div className="cta-card">
            <h2 className="cta-title">Ready to Accelerate Your Indexing?</h2>
            <p className="cta-description">
              Join thousands of SEO professionals who trust our AI-powered
              platform to get their content indexed faster.
            </p>

            <div className="cta-buttons">
              <button className="btn btn-primary btn-large">
                Get Started Free
              </button>
              <button className="btn btn-secondary btn-large">View Demo</button>
            </div>

            <div className="cta-features">
              <div className="cta-feature">
                <span className="check-icon">✓</span>
                <span>No credit card required</span>
              </div>
              <div className="cta-feature">
                <span className="check-icon">✓</span>
                <span>Free 14-day trial</span>
              </div>
              <div className="cta-feature">
                <span className="check-icon">✓</span>
                <span>Cancel anytime</span>
              </div>
            </div>
          </div>
        </div>
      </section>
    </div>
  );
}
