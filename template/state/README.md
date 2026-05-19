# state/ — runtime state files

This directory is empty in the template. The agent populates it during the campaign. The files below are the canonical state surface.

## Files the agent creates

### `experiment_ledger.jsonl`
Append-only record of every iteration. Each line is a JSON object matching `PROTOCOL.md` §14.1. Rotated every `ledger_rotation_iterations` entries (default 200) into `experiment_ledger.archive/`.

### `experiment_ledger.archive/`
Rotated chunks. The Reflection Analyst distills durable lessons into `playbook.md` before each rotation.

### `research_tree.json`
The active research tree (`PROTOCOL.md` §15). One root, N branches, each branch has children, status, lessons, budget_spent.

### `playbook.md`
Compact, curated lessons. Bounded by `metrics.yaml.memory.max_playbook_tokens`. This is what gets loaded into every future agent context.

### `open_questions.md`
Unanswered questions surfaced during the campaign.

### `known_failures.md`
Patterns that have been ruled out and should not be retried without new evidence.

### `eval_manifest.signed`
Tamper-evident hash list of `evaluation/` contents. Re-verified at every iteration. A drift here invalidates the iteration's result.

### `val_exposure.json`
Cumulative validation-set query counter (`PROTOCOL.md` §17.6). Schema:

```json
{
  "protocol_version": "0.4",
  "val_set_version": 1,
  "queries": 47,
  "last_incremented_by_iteration": "20260518-130045-a3f7d2"
}
```

### `budget_ledger.jsonl`
Per-iteration LLM tokens, tool calls, GPU hours, wall clock, provider cost estimates. Maintained by the Experiment Runner (non-LLM, `PROTOCOL.md` §5.5, §17.7.2).

## Files the verifier creates

When the agent emits a `promotion_request`, the verifier (`autoresearch/scripts/verifier/verify_request.py`) reads the request, re-hashes referenced ledger entries, and writes the signed `promotion_packet` into `reports/`. The verifier itself does NOT write to `state/` — `state/` is the agent's working memory.
