# Narrative evaluations

Rumor Mill keeps exact safety and consistency rules separate from subjective writing grades.
The versioned baseline dataset at `evals/lighthouse-v1.json` covers voice fidelity, belief
grounding, secret containment, canon consistency, rumor traceability, and plot progression.

## Deterministic CI run

```bash
make eval
```

This uses reviewed fixture outputs, writes JSON and Markdown reports under `artifacts/evals/`,
and exits nonzero when any exact rule fails. Secret containment findings are critical and block
the run regardless of aggregate scoring.

## Recorded outputs

Recorded output files are JSON objects mapping case IDs to generated text:

```bash
uv run python -m rumor_mill.evals evals/lighthouse-v1.json \
  --mode recorded --recorded artifacts/recorded-outputs.json
```

This mode makes provider output regressions reproducible without network access.

## Live provider and model grading

Configure `RUMOR_MILL_MODEL_PROVIDER=openai` and `RUMOR_MILL_OPENAI_API_KEY`, then run:

```bash
uv run python -m rumor_mill.evals evals/lighthouse-v1.json \
  --mode live --model-grade --max-total-tokens 12000
```

The live generator and grader both use typed provider responses. The runner stops if recorded
usage would exceed the configured token ceiling. Model grades assess voice, coherence, and
engagement from 1–5; the default blocking threshold is 3.0. Deterministic critical-leak rules
remain authoritative even when a model grader gives the writing a passing score.
