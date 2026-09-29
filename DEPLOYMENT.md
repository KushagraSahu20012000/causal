# Deployment

The production topology is intentionally split:

- **Web:** Vercel, rooted at `apps/web`
- **API:** Railway or Render, rooted at `apps/api`
- **Checkpoints and anonymous sessions:** Neon Postgres
- **Model:** Groq

## 1. Rotate development credentials

Before the first production deployment, rotate the GitHub token and Neon database password that were used during local setup. Never copy `apps/api/.env` into a deployment or commit it.

## 2. Deploy the API

### Railway

1. Create a service from this GitHub repository.
2. Set the service root directory to `apps/api`.
3. Railway will use `apps/api/railway.toml` and `apps/api/Dockerfile`.
4. Add every variable in the API environment table below.
5. Generate a public API domain and verify `GET /api/v1/health`.

### Render

Create a Blueprint from this repository. The root `render.yaml` configures the Docker service. Fill every variable marked `sync: false`.

### API environment

| Variable | Value |
| --- | --- |
| `ENVIRONMENT` | `production` |
| `GROQ_API_KEY` | Rotated Groq secret |
| `DATABASE_URL` | Neon pooled URL; hostname normally contains `-pooler` |
| `LANGGRAPH_AES_KEY` | A random 16, 24, or 32-character secret; keep it stable |
| `ALLOWED_ORIGINS` | Final Vercel web origin, without a trailing slash |
| `CAUSAL_MODEL` | `openai/gpt-oss-120b` |
| `SESSION_TTL_HOURS` | `24` |
| `DATABASE_POOL_SIZE` | `5` |

The API creates the LangGraph checkpoint tables and the `causal_sessions` index during startup. Production startup fails closed if `DATABASE_URL` or `LANGGRAPH_AES_KEY` is absent.

## 3. Deploy the web app to Vercel

1. Import the same GitHub repository as a new Vercel project.
2. Set **Root Directory** to `apps/web`.
3. Keep the detected framework as **Next.js**.
4. Add `CAUSAL_API_ORIGIN=https://<your-api-domain>` to Production and Preview environments.
5. Deploy, then add the final Vercel origin to the API's `ALLOWED_ORIGINS` and redeploy the API.

The browser uses same-origin `/api/*` requests. `apps/web/next.config.ts` securely rewrites them to `CAUSAL_API_ORIGIN`, so no model or database secrets enter the browser bundle.

## 4. Smoke test

1. Open `https://<your-web-domain>`.
2. Start a reflection and verify a public result or follow-up question appears.
3. Refresh and verify the anonymous session is restored.
4. Select **Delete session**, then refresh and verify it is gone.
5. Confirm API logs do not contain raw checkpoint state or credentials.

Anonymous session IDs are random 192-bit capability tokens. Sessions expire after 24 hours. LangGraph checkpoint payloads are encrypted before being written to Neon.