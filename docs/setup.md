# Setup

## API runner

Use macOS or Linux, Python 3.12 and Node 20+. The factual runner uses POSIX file locking. From the repository root:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
npm ci
npx playwright install chromium
```

Set `OPENAI_API_KEY` in your shell; `.env.example` lists names only. The factual transport reads process environment variables; it does not automatically load `.env` files. Never put keys in JSON configuration or Git. Review all settings in `configs/factual.json`, including budget and recorded price assumptions, before making requests. `configs/historical-cohort.json` retains the historical all-GPT settings for provenance; both public configurations now use that provider assignment.

Use the command in the root README, with `--no-sam` to run without a segmentation service. Skill mode instead uses its own bundled requirements and the calling assistant: see [Skill setup](skill.md).

## Optional SAM3

The API runner expects an **existing local SAM3 service** at `http://127.0.0.1:18080`. It calls `POST /v1/segment/proposals` for `picture`, `icon` and `arrow` proposals. Model weights and service deployment are external dependencies, not files shipped in this repository. Only omit `--no-sam` after confirming the service is healthy:

```bash
curl http://127.0.0.1:18080/health
```

One compatible service is the SAM3-only mode of [DrawAI](https://github.com/Renaissance-Mind/DrawAI-dev). Follow its current setup instructions, use legitimately obtained weights, and start its local SAM3 server on the expected port. Service failure stops SAM-assisted preparation rather than silently changing the experimental condition. The separate `scripts/fal_sam3_adapter.py` is an optional external-provider adapter; it is not selected automatically.

For existing browser installations and vector-runtime overrides, see [runtime configuration](runtime-setup.md).
