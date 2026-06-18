#!/usr/bin/env python3
"""behavioral_equivalence.py — PROTOCOL.md §17.1.1 tolerance-based fixture check.

This script is a reference implementation of the evaluator behavioral-equivalence
test. It is intentionally small and explicit so that a port to another language
(Go, Rust, Bash) is straightforward.

Usage
-----
    python behavioral_equivalence.py \\
        --metrics autoresearch/config/metrics.yaml \\
        --fixtures evaluation/fixtures \\
        --evaluator evaluation.metric_defs:compute

Exit codes
----------
    0  — every fixture passed within declared tolerance
    1  — at least one fixture failed tolerance (treat as a real behavioral
         change; goes to human review per §3.1 unless an approved refactor)
    2  — configuration error

Fixture format
--------------
Each fixture is a JSON file under ``--fixtures`` (recursive). Required fields:

    {
      "fixture_id": "...",
      "description": "<one-line>",
      "input": <opaque — passed to the evaluator's compute()>,
      "golden_outputs": {
        "<metric_name>": <number>,
        ...
      }
    }

Evaluator interface
-------------------
``--evaluator`` is a ``module:function`` selector. The function is called as
``compute(fixture_input)`` and MUST return a ``dict[str, float]`` keyed by
metric name. The keys MUST match those in ``golden_outputs``.

Tolerance rule
--------------
Per §17.1.1, equality is checked via ``abs(new - golden) <= atol + rtol * abs(golden)``.
Tolerances come from ``metrics.yaml``:

    evaluator_equivalence:
      defaults_by_dtype:
        fp32: {rtol: 1.0e-4, atol: 1.0e-6}
        ...
      per_metric:
        validation_nll: {rtol: 1.0e-4, atol: 1.0e-6}
        ...

For each metric, the per-metric override wins; otherwise the dtype default is
used. The metric's ``eval_dtype`` is read from ``primary_metric`` /
``secondary_metrics`` / ``guardrails`` in ``metrics.yaml``.

Tolerance sanity check
----------------------
Per §17.1.1, ``atol + rtol * abs(golden) <= 0.1 * minimum_meaningful_delta``
for the primary metric. The script enforces this and exits 2 on violation.
"""

from __future__ import annotations

import argparse
import importlib
import json
import math
import sys
from pathlib import Path
from typing import Any, Callable

# PyYAML ships its own type stubs in `types-PyYAML`; this script does not
# require that package, so we suppress the missing-import diagnostic.
try:
    import yaml  # type: ignore[import-untyped]
except ImportError:
    sys.stderr.write("ERROR: PyYAML is required. Install with: pip install pyyaml\n")
    sys.exit(2)


# The user-supplied evaluator SHOULD return dict[str, float] per the protocol's
# §17.1.1 fixture contract, but mypy cannot verify a user-supplied callable —
# the runtime isinstance check in check_fixture() is the actual enforcement.
EvaluatorFn = Callable[[Any], Any]


def _is_number(value: Any) -> bool:
    """True iff ``value`` is a real int/float metric value.

    The single numeric-membership predicate for this script: every site that
    feeds an untrusted value into ``abs()``/``math.isnan()``/``float()`` (golden
    fixture values, the evaluator's returns, minimum_meaningful_delta, declared
    tolerances) routes through here, so the "what counts as a number" rule is
    defined once. ``bool`` is excluded — it is an ``int`` subclass but a stray
    ``true``/``false`` is never a valid metric value or tolerance.
    """
    return isinstance(value, (int, float)) and not isinstance(value, bool)


# --- Tolerance lookup ---------------------------------------------------------


def metric_index(metrics_yaml: dict[str, Any]) -> dict[str, dict[str, str]]:
    """Build {metric_name: {direction, aggregation, eval_dtype}} index."""
    out: dict[str, dict[str, str]] = {}
    primary = metrics_yaml.get("primary_metric")
    primary = primary if isinstance(primary, dict) else {}
    primary_name = primary.get("name")
    if primary_name:
        if not isinstance(primary_name, str):
            raise SystemExit("CONFIG ERROR: primary_metric.name must be a string")
        out[primary_name] = {
            "direction": primary.get("direction", ""),
            "aggregation": primary.get("aggregation", ""),
            "eval_dtype": primary.get("eval_dtype", "fp32"),
        }
    for group in ("secondary_metrics", "guardrails"):
        entries = metrics_yaml.get(group)
        entries = entries if isinstance(entries, list) else []
        for entry in entries:
            if not isinstance(entry, dict) or not isinstance(entry.get("name"), str):
                raise SystemExit(
                    f"CONFIG ERROR: {group} metric entry not a mapping / "
                    "missing 'name' (or non-string name)"
                )
            out[entry["name"]] = {
                "direction": entry.get("direction", ""),
                "aggregation": entry.get("aggregation", ""),
                "eval_dtype": entry.get("eval_dtype", "fp32"),
            }
    return out


def _tolerance_float(metric_name: str, kind: str, value: Any) -> float:
    """Coerce a declared rtol/atol to float, failing with a clean CONFIG ERROR
    (not a raw ValueError/TypeError traceback) when the metrics.yaml value is
    non-numeric (e.g. ``rtol: "abc"`` or a list/mapping)."""
    if not _is_number(value):
        raise SystemExit(
            f"CONFIG ERROR: tolerance for '{metric_name}' {kind} must be numeric "
            f"(got {value!r})"
        )
    return float(value)


def tolerance_for_metric(
    metric_name: str,
    eval_dtype: str,
    equivalence_cfg: dict[str, Any],
) -> tuple[float, float]:
    """Return (rtol, atol) for the named metric.

    Per §17.1.1, every metric MUST declare ``eval_dtype`` and ``metrics.yaml``
    MUST provide either a ``per_metric`` override or a ``defaults_by_dtype``
    entry for that dtype. Missing config is a hard error.
    """
    per_metric_cfg = equivalence_cfg.get("per_metric")
    per_metric_cfg = per_metric_cfg if isinstance(per_metric_cfg, dict) else {}
    per_metric = per_metric_cfg.get(metric_name)
    if per_metric:
        if (
            not isinstance(per_metric, dict)
            or "rtol" not in per_metric
            or "atol" not in per_metric
        ):
            raise SystemExit(
                f"CONFIG ERROR: tolerance for '{metric_name}' missing rtol/atol"
            )
        return (
            _tolerance_float(metric_name, "rtol", per_metric["rtol"]),
            _tolerance_float(metric_name, "atol", per_metric["atol"]),
        )
    defaults_by_dtype = equivalence_cfg.get("defaults_by_dtype")
    defaults_by_dtype = defaults_by_dtype if isinstance(defaults_by_dtype, dict) else {}
    dtype_defaults = defaults_by_dtype.get(eval_dtype)
    if dtype_defaults is None:
        raise SystemExit(
            f"CONFIG ERROR: metric '{metric_name}' declares eval_dtype="
            f"{eval_dtype!r} but metrics.yaml.evaluator_equivalence has no "
            f"defaults_by_dtype.{eval_dtype} entry and no per_metric.{metric_name} "
            f"override. Add one or the other (§17.1.1)."
        )
    if (
        not isinstance(dtype_defaults, dict)
        or "rtol" not in dtype_defaults
        or "atol" not in dtype_defaults
    ):
        raise SystemExit(
            f"CONFIG ERROR: tolerance for '{metric_name}' missing rtol/atol"
        )
    return (
        _tolerance_float(metric_name, "rtol", dtype_defaults["rtol"]),
        _tolerance_float(metric_name, "atol", dtype_defaults["atol"]),
    )


def sanity_check_tolerance(
    metric_name: str,
    rtol: float,
    atol: float,
    minimum_meaningful_delta: float,
    golden_value: float,
) -> None:
    """Per §17.1.1: tolerance must be ≤ 0.1 × minimum_meaningful_delta at the golden value."""
    effective_tol = atol + rtol * abs(golden_value)
    if effective_tol > 0.1 * abs(minimum_meaningful_delta):
        raise SystemExit(
            f"CONFIG ERROR: metric '{metric_name}' tolerance is too loose. "
            f"effective_tol at golden={golden_value} is {effective_tol}; "
            f"PROTOCOL.md §17.1.1 requires ≤ 0.1 × minimum_meaningful_delta "
            f"(= {0.1 * abs(minimum_meaningful_delta)}). Tighten tolerances "
            f"or raise minimum_meaningful_delta."
        )


# --- Fixture loading ----------------------------------------------------------


def load_fixtures(fixtures_dir: Path) -> list[dict[str, Any]]:
    fixtures: list[dict[str, Any]] = []
    if not fixtures_dir.exists():
        raise SystemExit(f"CONFIG ERROR: fixtures dir does not exist: {fixtures_dir}")
    for path in sorted(fixtures_dir.rglob("*.json")):
        # The open() is INSIDE the guard: an unreadable fixture (OSError —
        # permission denied, transient FS, is-a-directory) is as clean an error
        # as a non-UTF-8 (UnicodeDecodeError) or malformed (json.JSONDecodeError)
        # one, never a traceback.
        try:
            with path.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except OSError as exc:
            raise SystemExit(f"CONFIG ERROR: fixture {path} not readable: {exc}")
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise SystemExit(f"CONFIG ERROR: fixture {path} is not valid JSON: {exc}")
        if not isinstance(data, dict):
            raise SystemExit(
                f"CONFIG ERROR: fixture {path} top-level must be an object"
            )
        for key in ("fixture_id", "input", "golden_outputs"):
            if key not in data:
                raise SystemExit(
                    f"CONFIG ERROR: fixture {path} is missing required key '{key}'"
                )
        data["_path"] = str(path)
        fixtures.append(data)
    if not fixtures:
        raise SystemExit(
            f"CONFIG ERROR: no fixtures found under {fixtures_dir}. "
            f"§17.1.1 requires at least 3-5 golden fixtures."
        )
    return fixtures


# --- Evaluator loading --------------------------------------------------------


def load_evaluator(spec: str) -> EvaluatorFn:
    """spec is 'module.path:function_name'."""
    if ":" not in spec:
        raise SystemExit(
            f"CONFIG ERROR: --evaluator must be 'module:function' (got {spec!r})"
        )
    module_path, func_name = spec.split(":", 1)
    try:
        module = importlib.import_module(module_path)
    except ImportError as e:
        raise SystemExit(f"CONFIG ERROR: cannot import {module_path}: {e}") from e
    func = getattr(module, func_name, None)
    if func is None or not callable(func):
        raise SystemExit(f"CONFIG ERROR: {module_path} has no callable {func_name!r}")
    return func  # type: ignore[no-any-return]


# --- Equivalence check --------------------------------------------------------


def within_tolerance(observed: float, golden: float, rtol: float, atol: float) -> bool:
    """numpy.allclose's rule, for a single scalar."""
    if math.isnan(observed) or math.isnan(golden):
        return False
    return abs(observed - golden) <= atol + rtol * abs(golden)


def check_fixture(
    fixture: dict[str, Any],
    evaluator: EvaluatorFn,
    metric_idx: dict[str, dict[str, str]],
    equivalence_cfg: dict[str, Any],
    primary_min_delta: float | None,
    primary_name: str | None,
) -> list[str]:
    """Return list of failure messages; empty list = pass."""
    failures: list[str] = []
    fixture_id = fixture["fixture_id"]
    # golden_outputs comes from an untrusted fixture file. load_fixtures asserts
    # the key is PRESENT but not its type; a non-mapping (e.g. a JSON list) would
    # crash the `.items()` below with AttributeError. Reject it as a clean CONFIG
    # ERROR (invalid fixture), exit 2.
    golden_outputs = fixture["golden_outputs"]
    if not isinstance(golden_outputs, dict):
        raise SystemExit(
            f"CONFIG ERROR: fixture {fixture_id} golden_outputs must be an object/"
            f"mapping, got {type(golden_outputs).__name__}"
        )
    observed_outputs = evaluator(fixture["input"])
    if not isinstance(observed_outputs, dict):
        return [
            f"{fixture_id}: evaluator returned {type(observed_outputs).__name__}, "
            f"expected dict[str, float]"
        ]
    for metric_name, golden in golden_outputs.items():
        # golden is an untrusted fixture value. load_fixtures validates
        # golden_outputs is a mapping but NOT that each VALUE is numeric; a
        # non-numeric golden (str/list/dict) flows into abs()/math.isnan() in
        # within_tolerance() and sanity_check_tolerance() and crashes with
        # TypeError. A malformed fixture VALUE is a CONFIG ERROR (exit 2),
        # consistent with the non-mapping golden_outputs rejection above.
        if not _is_number(golden):
            raise SystemExit(
                f"CONFIG ERROR: fixture {fixture_id} golden for metric "
                f"'{metric_name}' must be numeric, got {type(golden).__name__}"
            )
        observed = observed_outputs.get(metric_name)
        if observed is None:
            failures.append(
                f"{fixture_id}: evaluator did not return metric {metric_name!r}"
            )
            continue
        # observed is the evaluator's runtime return value. The dict-shape check
        # above does not constrain its VALUES; a non-numeric observed (the
        # evaluator misbehaving) flows into math.isnan(observed) and crashes.
        # Treat it as a behavioral FAILURE (exit 1), consistent with the
        # evaluator-returned-a-non-dict path above — not a CONFIG ERROR.
        if not _is_number(observed):
            failures.append(
                f"{fixture_id}.{metric_name}: evaluator returned non-numeric "
                f"value {observed!r} (expected a number)"
            )
            continue
        info = metric_idx.get(metric_name)
        if info is None:
            raise SystemExit(
                f"CONFIG ERROR: fixture {fixture_id} contains golden for "
                f"metric '{metric_name}' but metrics.yaml does not declare it. "
                f"Add it to primary_metric / secondary_metrics / guardrails "
                f"with direction, aggregation, and eval_dtype (§17.1.1)."
            )
        eval_dtype = info["eval_dtype"]
        if not eval_dtype:
            raise SystemExit(
                f"CONFIG ERROR: metric '{metric_name}' has empty eval_dtype "
                f"in metrics.yaml (§6.1 + §17.1.1 require it)."
            )
        rtol, atol = tolerance_for_metric(metric_name, eval_dtype, equivalence_cfg)

        # Sanity-check the tolerance against the primary's minimum_meaningful_delta.
        if metric_name == primary_name and primary_min_delta is not None:
            sanity_check_tolerance(metric_name, rtol, atol, primary_min_delta, golden)

        if not within_tolerance(observed, golden, rtol, atol):
            failures.append(
                f"{fixture_id}.{metric_name}: observed={observed} golden={golden} "
                f"rtol={rtol} atol={atol} delta={abs(observed - golden)}"
            )
    return failures


# --- Main ---------------------------------------------------------------------


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "PROTOCOL.md §17.1.1 tolerance-based behavioral-equivalence "
            "check. Verifies that the live evaluator produces metric values "
            "within declared tolerance of recorded golden fixtures."
        )
    )
    parser.add_argument(
        "--metrics",
        required=True,
        type=Path,
        help="Path to autoresearch/config/metrics.yaml",
    )
    parser.add_argument(
        "--fixtures",
        required=True,
        type=Path,
        help="Path to evaluation/fixtures/ directory",
    )
    parser.add_argument(
        "--evaluator",
        required=True,
        help=(
            "Evaluator callable as 'module.path:function'. The function is "
            "called as compute(fixture_input) and must return dict[str, float]."
        ),
    )
    args = parser.parse_args(argv)

    if not args.metrics.exists():
        sys.stderr.write(f"CONFIG ERROR: {args.metrics} does not exist\n")
        return 2

    # An unreadable (OSError), non-UTF-8 (UnicodeDecodeError), or malformed
    # (yaml.YAMLError) metrics.yaml is a clean CONFIG ERROR (exit 2), never a
    # traceback.
    try:
        with args.metrics.open("r", encoding="utf-8") as f:
            metrics_yaml = yaml.safe_load(f)
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        sys.stderr.write(
            f"CONFIG ERROR: {args.metrics} not readable/parseable: {exc}\n"
        )
        return 2
    if not isinstance(metrics_yaml, dict):
        sys.stderr.write("CONFIG ERROR: metrics.yaml did not parse as a mapping\n")
        return 2
    equivalence_cfg = metrics_yaml.get("evaluator_equivalence") or {}
    if not equivalence_cfg:
        sys.stderr.write(
            "CONFIG ERROR: metrics.yaml has no evaluator_equivalence block. "
            "Add it per §17.1.1.\n"
        )
        return 2
    # A truthy non-mapping evaluator_equivalence (e.g. a YAML list or string) would
    # survive `or {}` and later crash tolerance_for_metric's `.get("per_metric")`
    # with AttributeError. Reject it as a clean CONFIG ERROR here.
    if not isinstance(equivalence_cfg, dict):
        sys.stderr.write(
            "CONFIG ERROR: metrics.yaml evaluator_equivalence must be a mapping, "
            f"got {type(equivalence_cfg).__name__}\n"
        )
        return 2

    metric_idx = metric_index(metrics_yaml)
    primary = metrics_yaml.get("primary_metric") or {}
    # A truthy non-mapping primary_metric would survive `or {}` and crash the
    # `.get()` calls below with AttributeError; coerce to {} so name/min_delta
    # default to None (metric_index already guards its own copy).
    primary = primary if isinstance(primary, dict) else {}
    primary_name = primary.get("name")
    primary_min_delta = primary.get("minimum_meaningful_delta")
    # minimum_meaningful_delta flows into sanity_check_tolerance's
    # abs(minimum_meaningful_delta) (the §17.1.1 tolerance ceiling). A present-
    # but-non-numeric value (str/list/dict from an untrusted metrics.yaml) would
    # crash abs() with TypeError; reject it here as a clean CONFIG ERROR. Absent
    # (None) is tolerated — the sanity check is then simply skipped.
    if primary_min_delta is not None and not _is_number(primary_min_delta):
        sys.stderr.write(
            "CONFIG ERROR: primary_metric.minimum_meaningful_delta must be "
            f"numeric, got {type(primary_min_delta).__name__}\n"
        )
        return 2

    fixtures = load_fixtures(args.fixtures)
    evaluator = load_evaluator(args.evaluator)

    total_failures: list[str] = []
    for fixture in fixtures:
        failures = check_fixture(
            fixture,
            evaluator,
            metric_idx,
            equivalence_cfg,
            primary_min_delta,
            primary_name,
        )
        total_failures.extend(failures)

    if total_failures:
        sys.stderr.write(
            f"FAIL: {len(total_failures)} fixture metric(s) outside tolerance:\n"
        )
        for msg in total_failures:
            sys.stderr.write(f"  - {msg}\n")
        sys.stderr.write(
            "\nPer §17.1.1, refactors that fail tolerance go to human review. "
            "Either the change is semantic (block promotion) or the golden "
            "fixtures need updating (archive old, document why in fixtures/archive/<date>/).\n"
        )
        return 1

    sys.stdout.write(
        f"OK: {len(fixtures)} fixture(s), "
        f"{sum(len(f['golden_outputs']) for f in fixtures)} metric check(s), "
        f"all within tolerance.\n"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
