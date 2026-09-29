# Causal

A guided reflection workspace for examining the conditions that may shape a thought or feeling.

## Applications

- `apps/web`: Next.js interface
- `apps/api`: FastAPI and LangGraph backend
- `manual_prompt.txt`: original product and reasoning reference

## Status

The graph, public API, model runtime, and encrypted anonymous session persistence are implemented. Sessions use Neon Postgres and expire after 24 hours.

## Production topology

- Deploy `apps/web` to Vercel.
- Deploy `apps/api` to Railway or Render using its Dockerfile.
- Configure Neon Postgres and Groq through deployment secrets.

See [DEPLOYMENT.md](DEPLOYMENT.md) for the complete deployment checklist.
