# SADA hosted AI conversation setup

SADA supports optional streamed Groq responses, with server-side API calls only. A working API key is **required**.

## Enable a public AI demonstration

1. Create your own Groq API key at https://console.groq.com/keys. Review your account plan, limits and pricing.
2. In **Render Dashboard → sada-voice-ai → Environment**, add `GROQ_API_KEY` as a secret environment variable using the value generated in step 1. Set `ENABLE_HOSTED_LLM=1` (included in `render.yaml`). Never paste the key into GitHub, JavaScript, chat messages or screenshots.
3. Save and deploy. Open `https://sada-voice-ai.onrender.com/api/config`; `hosted_llm_enabled` should be `true` once the server has a key and the setting is enabled.
4. Test a generative question such as: "Could you walk me through the sample return policy in plain English?" and an Arabic follow-up. Confirm the assistant gives coherent answers, does not claim to know real order details and does not invent actions.

The default model is `openai/gpt-oss-120b` (overridable with `GROQ_MODEL`). The provider is called using the OpenAI-compatible streaming completions endpoint `https://api.groq.com/openai/v1/chat/completions`.

## Behavior and safeguards

- Only a small rolling conversation context (up to 4 previous messages) and a fixed fictional policy prompt leave your server to Groq. Users should not enter sensitive information.
- Sample order statuses and handoff requests are deterministic and never delegated to the language model.
- Responses are streamed as WebSocket events (`answer_start`, `answer_delta`, and `answer`). The existing client supports spoken replies in browser TTS.
- Rate limit is 12 hosted model requests per minute, 200 per day and 3 concurrent hosted calls per server process, in addition to per-WebSocket turn limiting. These are demonstration limits, not enterprise-grade distributed abuse prevention.
- On timeouts, quota errors or provider outages, the user receives deterministic fallback information rather than invented order information.
- The provider may incur charges. Configure spending limits and monitor provider usage. Never expose a paid API key directly to a browser.
- Public site is **not** real customer support. For production add authentication, robust rate limits and abuse defense, privacy consent, stronger evaluation, telemetry and a trusted knowledge base.
