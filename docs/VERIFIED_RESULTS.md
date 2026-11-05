# SADA Voice AI | Verified test evidence

This report is drawn from **actual GitHub Actions output**, not from illustrative presentation graphics or manually invented results.

**Source:** [CI run #42124554466](https://github.com/FaizanAKhan786/sada-voice-ai/actions/runs/42124554466)  
**Workflow:** `.github/workflows/ci.yml`  
**Commit:** `0224ac357968a8e944e6169f43d414416735e3f2`  
**Execution:** 2026-11-05 (GitHub Actions; Python 3.11 on Ubuntu)

| Check | Observed result | Evidence |
| --- | --- | --- |
| Python pytest suite | **37 passed, 1 warning** | `python -m pytest -q` step |
| Synthetic bilingual intent fixtures | **30 correct / 30 cases** | `python -m scripts.evaluate` step |
| Synthetic intent agreement | **100% of the supplied 30 fixtures** | Reported `intent_accuracy_pct` from evaluation script |
| Rule processing | **0.03 ms mean as reported by this particular CI run** | Evaluator reports `mean_rule_processing_ms`; excludes all networking, speech and hosted models |
| JavaScript syntax | **Passed** | `node --check web/app.js` and `web/pcm-worklet.js` steps |

The CI log is the primary source of these figures. The 30-case fixture evaluation tests **scripted intent classification and support workflows**, not audio perception, production user traffic or LLM correctness.

## Genuine browser and hosted integration evidence

- [Real browser screenshot workflow, successful run #42123933720](https://github.com/FaizanAKhan786/sada-voice-ai/actions/runs/42123933720) verifies local FastAPI startup, browser-to-server WebSocket connection and an `ORD-1001` synthetic order exchange; this run wrote real desktop/mobile screenshots and a browser-recorded WebM walkthrough.
- [Public hosted-chat smoke run #42124554553](https://github.com/FaizanAKhan786/sada-voice-ai/actions/runs/42124554553) succeeded when checked. Its client connects to the public `/ws/live` endpoint, confirms an active model-backed response and observes streamed `answer_delta` events; it does not inspect provider correctness or voice interruption performance.

## What is not measured

No verified benchmark for real microphone recognition, Arabic dialect WER, audio round-trip latency, user satisfaction, reliability SLA, prompt safety or real customer data. Public hosting can change after the smoke test, so use the live workflow history for the latest state.

## Reproduce

```bash
pip install -r requirements-dev.txt
python -m pytest -q
python -m scripts.evaluate
node --check web/app.js
node --check web/pcm-worklet.js
```

For a user-visible demonstration, follow [DEMO_WALKTHROUGH.md](DEMO_WALKTHROUGH.md).
