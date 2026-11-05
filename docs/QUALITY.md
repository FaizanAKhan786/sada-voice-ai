# SADA Voice AI | Quality & reproducibility

> **Status rule:** Check the [live GitHub Actions history](https://github.com/FaizanAKhan786/sada-voice-ai/actions) for real workflow conclusions. This document does not invent benchmark scores or imply every feature was tested.

## Automated verification

Pytest, deterministic bilingual intent evaluation, JavaScript syntax checks; separate public demo smoke workflows.

- [View the CI workflow](https://github.com/FaizanAKhan786/sada-voice-ai/actions/workflows/ci.yml)
- Any failing run is an unresolved result until corrected; a green syntax/unit-check workflow is not proof of deployment readiness.

## Reproduce the checks

Run these commands from the **repository root**, unless the commands change directories:

```bash
pip install -r requirements-dev.txt
python -m pytest -q
python -m scripts.evaluate
node --check web/app.js
node --check web/pcm-worklet.js
```

## How to interpret the results

**Relevant metrics:** Synthetic bilingual intent match rate and deterministic flow behavior from scripts/eval_cases.jsonl.

**Requirements and limitations:** The evaluation uses mock order data and scripted pathways. It is not a voice recognition accuracy benchmark, a human-call quality survey or a production SLA.

Before comparing results, save the commit SHA, command, dataset and split (including seed), model revision, dependency environment, hardware/CPU/GPU, and the raw result file. Use the same evaluation set for all compared runs and distinguish **synthetic tests** from **real-world measurements**.

## Publication policy

Only publish numeric scores alongside the run configuration and raw evidence. A threshold, code assertion or example report must **not** be presented as a measured production result.

[Project README](../README.md) · [GitHub Actions](https://github.com/FaizanAKhan786/sada-voice-ai/actions)
