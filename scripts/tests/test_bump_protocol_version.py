#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "bump_protocol_version.py"
SPEC = importlib.util.spec_from_file_location("bump_protocol_version", SCRIPT)
bump_protocol_version = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = bump_protocol_version
SPEC.loader.exec_module(bump_protocol_version)


class BumpProtocolVersionTests(unittest.TestCase):
    def test_bump_updates_current_surfaces_without_rewriting_protocol_changelog(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_minimal_repo(root)

            result = bump_protocol_version.run_bump(
                root,
                "0.7",
                from_version="0.6",
                release_date="2026-08-01",
            )

            self.assertIn("template/PROTOCOL_VERSION", result.changed)
            self.assertEqual((root / "template/PROTOCOL_VERSION").read_text(encoding="utf-8"), "0.7\n")

            protocol = (root / "PROTOCOL.md").read_text(encoding="utf-8")
            self.assertIn("**Version:** 0.7", protocol)
            self.assertIn("**Date:** 2026-08-01", protocol)
            self.assertIn('- **v0.6:** Historical entry with `protocol_version: "0.6"`.', protocol)
            self.assertIn('protocol_version: "0.7"', protocol)
            self.assertIn("AutoResearch++ Protocol v0.7", protocol)

            schema = json.loads((root / "template/schema/experiment_record.schema.json").read_text(encoding="utf-8"))
            self.assertEqual(schema["properties"]["protocol_version"]["enum"], ["0.5", "0.6", "0.7"])
            self.assertIn("Current writers MUST emit \"0.7\"", schema["properties"]["protocol_version"]["description"])

            verifier = (root / "template/scripts/verifier/verify_request.py").read_text(encoding="utf-8")
            self.assertIn('PROTOCOL_VERSION = "0.7"', verifier)
            self.assertIn('SUPPORTED_PROTOCOL_VERSIONS = {"0.5", "0.6", PROTOCOL_VERSION}', verifier)

            request = json.loads(
                (root / "examples/demo/proposals/iter01-promotion-request.json").read_text(encoding="utf-8")
            )
            self.assertEqual(request["protocol_version"], "0.7")
            ledger_hash = self._canonical_hash(root / "examples/demo/state/ledger/rec001.json")
            self.assertEqual(request["references"]["baseline_run"]["content_sha256"], ledger_hash)
            report_hash = bump_protocol_version.sha256_bytes(
                (root / "examples/demo/reports/skeptic.md").read_bytes()
            )
            self.assertEqual(request["references"]["skeptic_review"]["content_sha256"], report_hash)

    def test_check_mode_reports_pending_changes_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_minimal_repo(root)

            result = bump_protocol_version.run_bump(root, "0.7", from_version="0.6", write=False)

            self.assertIn("template/PROTOCOL_VERSION", result.changed)
            self.assertEqual((root / "template/PROTOCOL_VERSION").read_text(encoding="utf-8"), "0.6\n")

    def _canonical_hash(self, path: Path) -> str:
        entry = json.loads(path.read_text(encoding="utf-8"))
        return bump_protocol_version.sha256_bytes(bump_protocol_version.canonical_record_bytes(entry))

    def _write_minimal_repo(self, root: Path) -> None:
        self._write(root / "template/PROTOCOL_VERSION", "0.6\n")
        self._write(
            root / "README.md",
            "Centerpiece: AutoResearch++ v0.6\n**Protocol version shipped:** `0.6`\n",
        )
        self._write(
            root / "PROTOCOL.md",
            """# Protocol

**Version:** 0.6
**Date:** 2026-07-03

### Changelog

- **v0.6:** Historical entry with `protocol_version: "0.6"`.

## 0. Versioning policy

```yaml
protocol_version: "0.6"
```

Your goal is to improve the model under the AutoResearch++ Protocol v0.6.
""",
        )
        self._write(root / "docs/host-bootstrap-agents.md", 'Keep `protocol_version: "0.6"` exactly.\n')
        self._write(root / "examples/README.md", "AutoResearch++ v0.6 examples.\n")
        self._write(root / "template/README.md", 'PROTOCOL_VERSION              # contains "0.6"\n')
        self._write(root / "template/config/metrics.yaml.example", 'protocol_version: "0.6"\n')
        self._write(root / "template/scripts/log_experiment.py", 'def default():\n    return "0.6"\n')
        self._write(
            root / "template/scripts/verifier/verify_request.py",
            'PROTOCOL_VERSION = "0.6"\nSUPPORTED_PROTOCOL_VERSIONS = {"0.5", PROTOCOL_VERSION}\n',
        )
        self._write(
            root / "template/schema/experiment_record.schema.json",
            json.dumps(
                {
                    "title": "Experiment Record (Protocol 0.6)",
                    "properties": {
                        "protocol_version": {
                            "enum": ["0.5", "0.6"],
                            "description": 'Current writers MUST emit "0.6"; "0.5" remains accepted.',
                        }
                    },
                },
                indent=2,
            )
            + "\n",
        )
        self._write(
            root / "template/schema/split_manifest.schema.json",
            json.dumps(
                {
                    "title": "Split Manifest (Protocol 0.6)",
                    "anyOf": [
                        {"properties": {"protocol_version": {"enum": ["0.5", "0.6"]}}},
                        {"properties": {"protocol_version": {"enum": ["0.5", "0.6"]}}},
                    ],
                },
                indent=2,
            )
            + "\n",
        )

        self._write(
            root / "examples/demo/state/ledger/rec001.json",
            json.dumps(
                {
                    "protocol_version": "0.6",
                    "id": "rec001",
                    "timestamp": "2026-07-03T00:00:00Z",
                    "branch": "baseline",
                    "hypothesis": "baseline",
                    "parent_ids": [],
                    "status": "baseline",
                    "metrics": {},
                },
                indent=2,
            )
            + "\n",
        )
        self._write(root / "examples/demo/reports/skeptic.md", '---\nprotocol_version: "0.6"\n---\n')
        ledger_hash = self._canonical_hash(root / "examples/demo/state/ledger/rec001.json")
        report_hash = bump_protocol_version.sha256_bytes((root / "examples/demo/reports/skeptic.md").read_bytes())
        self._write(
            root / "examples/demo/proposals/iter01-promotion-request.json",
            json.dumps(
                {
                    "protocol_version": "0.6",
                    "references": {
                        "baseline_run": {
                            "ledger_id": "rec001",
                            "content_sha256": ledger_hash,
                        },
                        "skeptic_review": {
                            "path": "reports/skeptic.md",
                            "content_sha256": report_hash,
                        },
                    },
                },
                indent=2,
            )
            + "\n",
        )

    def _write(self, path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
