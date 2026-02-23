# Copilot instructions for `indexer-seo`

## Build, lint, and test commands

### Frontend / Shopify app (repo root)
- Install deps: `npm install`
- Prisma client + migrations: `npm run setup`
- Dev server: `npm run dev`
- Lint: `npm run lint`
- Type-check: `npm run typecheck`
- Production build: `npm run build`
- Serve built app: `npm run start`

### Backend (Python workers in `backend/`)
- Start Redis + workers with Docker Compose: `cd backend && docker-compose up --build`
- Run all backend processes via supervisor image: `cd backend && docker build -t indexer-seo-backend . && docker run --rm indexer-seo-backend`
- Manual connectivity smoke script: `cd backend && python test_connection.py`

### Test notes
- There is no configured `npm test` script or `pytest` suite in this repository.
- For a single targeted backend check, use `python backend\\test_connection.py`.

## High-level architecture

- This repo is a dual-stack Shopify app:
  - `app/`: embedded Shopify admin app using React Router v7, Shopify App Bridge, and Prisma.
  - `backend/`: async Python pipeline for indexing jobs (Redis streams + workers + PostgreSQL access).
- The embedded app entry (`app/shopify.server.js`) centralizes Shopify auth, billing plans, webhook registration helpers, and Prisma session storage.
- Route pattern: most `app/routes/*.jsx` files use loader/action functions that start with `authenticate.admin(request)` for app pages or `authenticate.webhook(request)` for webhook routes.
- Webhooks (for example `webhooks.products.jsx`) upsert `UrlEntry` rows and mark items as `PENDING` with `indexAction` (`INDEX`/`DELETE`) for downstream processing.
- Data model in `prisma/schema.prisma` defines operational tables (`Auth`, `UrlEntry`, `IndexTask`, `ShopFeatureStates`, `Session`) and shared status enums.
- Backend processing is a 3-layer stream pipeline configured in `backend/config.py`:
  - Scheduler writes shop jobs to `stream:data-prep-agents` (`scheduler.py`)
  - L1 data prep reads Auth + pending URLs, groups actions, and writes to `stream:indexing-workers` (`layer_data_preparation.py`)
  - L2 indexing worker executes Google/Bing indexing and writes summarized results to `stream:status-sync-worker` (`layer_indexing_worker.py`)
  - L3 result saver updates URL index flags/status back to data store (`layer_result_saving.py`)

## Key repository conventions

- Keep Shopify auth at route boundaries: use `authenticate.admin`/`authenticate.webhook` in loaders/actions rather than ad-hoc token handling.
- UI uses Shopify Web Components (`<s-page>`, `<s-section>`, `<s-button>`, etc.) instead of Polaris React component APIs.
- Persist shop-scoped records with unique constraints (`shop + webUrl`, `shop + baseId`, `shop + url`) and rely on upserts for idempotent webhook/event handling.
- Credential secrets are stored encrypted in app DB fields (see `app/functions/auth.ts`): payload format is `iv.tag.ciphertext`, with keys from env vars.
- Backend workers use Redis consumer groups and ack semantics; jobs are stored in hash keys and stream entries carry routing metadata (`job_id`, `shop`).
