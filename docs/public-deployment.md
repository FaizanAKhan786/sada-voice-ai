# Deploy the public SADA demo

SADA is a full-stack FastAPI app, **not** a static website. Deploy the **Web Service** on Render using the root `render.yaml` Blueprint:

1. Connect your GitHub repository to your Render account.
2. Open [Deploy SADA to Render](https://render.com/deploy?repo=https://github.com/FaizanAKhan786/sada-voice-ai) and approve the Blueprint.
3. After deployment succeeds, open the `https://...onrender.com` URL that Render actually assigns. Do **not** assume the service has a particular URL before deployment.
4. Visit `/api/health` and test English and Arabic chat, fake order `ORD-1001`, and speech recognition/output on Chrome or Edge.

## What publicly works

* Text conversations, fixed bilingual support workflows, sample orders, simulated handoff and browser-based spoken input/output on supported browsers.
* Real-time WebSocket connection over HTTPS (`wss://`) through Render.
* No accounts, real CRM, real orders, payment data or financial operations.

## Not yet implemented in this hosting profile

* Server-side faster-whisper, server-side streaming VAD, and Ollama/Qwen inference are **disabled** to fit the lightweight demo.
* Browser speech recognition may be provided by the browser vendor and is not guaranteed in every browser or locale. Do not enter real customer, order, or personal information.
* This is a public prototype, **not production-ready customer support software**.

## Operational notes

* The `PUBLIC_DEMO_MODE=1` setting enforces same-origin WebSocket connections from browsers and a per-session 30-turns/minute cap. Those are **basic guardrails, not comprehensive abuse protection**.
* For a real public customer service product, add centralized rate limits, identity and order authorization, HTTPS-only transport, observability, privacy and data retention rules, and tested real speech/LLM infrastructure before onboarding customers.
* Render's free service can sleep after inactivity and takes time to restart. Use a paid service for dependable responsiveness. See [Render free-tier docs](https://render.com/docs/free).
* Keep GitHub connected as a Git provider to enable automatic updates upon code changes.
