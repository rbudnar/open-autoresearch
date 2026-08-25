#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "check_repo_harness.py"
SPEC = importlib.util.spec_from_file_location("check_repo_harness", SCRIPT)
check_repo_harness = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = check_repo_harness
SPEC.loader.exec_module(check_repo_harness)


class PrAgentInboxHarnessTests(unittest.TestCase):
    def test_wiring_accepts_hosted_event_contract_and_rejects_obsolete_surfaces(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            files = {
                ".github/workflows/pr-agent-inbox-signal.yml": """name: PR Agent Inbox Signal
permissions: {}
on:
  pull_request_review:
    types: [submitted, edited, dismissed]
  pull_request_review_comment:
    types: [created, edited, deleted]
jobs:
  signal:
    name: Agent inbox
    runs-on: ubuntu-latest
    timeout-minutes: 5
    steps:
      - run: echo signal
""",
                ".github/workflows/pr-agent-inbox.yml": """name: PR Agent Inbox
permissions: {}
on:
  pull_request_target:
    types: [opened, edited, reopened, synchronize, ready_for_review, converted_to_draft]
  issue_comment:
    types: [created]
  workflow_dispatch:
  workflow_run:
    workflows: [check-drift, protect-protocol, validate-examples, validate-ledger, PR Agent Inbox Signal]
    types: [completed]
jobs:
  route:
    runs-on: ubuntu-latest
    timeout-minutes: 5
    permissions:
      actions: read
      contents: read
      pull-requests: read
  publish:
    runs-on: ubuntu-latest
    timeout-minutes: 5
    permissions:
      contents: read
      pull-requests: write
      issues: write
      statuses: write
    steps:
      - run: node scripts/pr-agent-inbox.mjs --assert-no-agent-attention
    concurrency:
      group: pr-agent-inbox-pr-${{ matrix.pr }}
      cancel-in-progress: false
""",
                "scripts/pr-agent-inbox.mjs": """const inboxState = clean ? 'clean'
const statusState = agentAttention ? 'failure' : 'success'
Agent check state: ${result.statusState}
inbox_state=${displayInboxState(result)}
""",
                "scripts/pr-agent-inbox.test.mjs": """waiting markdown distinguishes inbox state from agent check state
assert.equal(result.inboxState, 'waiting')
assert.equal(result.statusState, 'success')
""",
            }
            for relative, content in files.items():
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")

            original_root = check_repo_harness.REPO_ROOT
            try:
                check_repo_harness.REPO_ROOT = root
                self._run_wiring_check()
                for forbidden in ("schedule:", "status:", "check_run:", "self-hosted"):
                    inbox = root / ".github/workflows/pr-agent-inbox.yml"
                    baseline = files[".github/workflows/pr-agent-inbox.yml"]
                    injected = (
                        "  runs-on: [self-hosted]"
                        if forbidden == "self-hosted"
                        else f"  {forbidden}"
                    )
                    inbox.write_text(f"{baseline}\n{injected}\n", encoding="utf-8")
                    check_repo_harness.failures.clear()
                    check_repo_harness.check_pr_agent_inbox_wiring()
                    self.assertTrue(check_repo_harness.failures, forbidden)
            finally:
                check_repo_harness.REPO_ROOT = original_root
                check_repo_harness.failures.clear()

    def _run_wiring_check(self) -> None:
        check_repo_harness.failures.clear()
        check_repo_harness.check_pr_agent_inbox_wiring()
        self.assertEqual(check_repo_harness.failures, [])


if __name__ == "__main__":
    unittest.main()
