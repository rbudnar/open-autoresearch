"""Drift check between BOOTSTRAP_QUESTIONS.yaml and template/config/*.yaml.example.

The bootstrap questionnaire (BOOTSTRAP_QUESTIONS.yaml) has hand-maintained
``maps_to`` strings that name the config keys each question is responsible for
filling. Those strings drift silently when an .example config file gets a new
``<FILL_ME>`` placeholder or renames a key — the questionnaire keeps shipping
the old map and an integrating agent silently leaves placeholders behind.

This script catches both drift directions:

1. Forward drift: every key cited by a question's ``maps_to`` must exist in the
   corresponding ``template/config/<file>.yaml.example``. If a question still
   claims to fill ``budgets.compute.max_wall_clock_seconds`` but the example
   config renamed it to ``budgets.compute.max_wall_clock_hours``, that's drift.

2. Reverse drift: every ``<FILL_ME>`` placeholder in an .example config must be
   covered by at least one question. If someone adds a new ``<FILL_ME>`` key
   without updating the questionnaire, the agent leaves the placeholder in
   the host repo and the loop later fails on a CONFIG ERROR.

The parser is intentionally simple: it looks for tokens appearing after
``::`` or ``→`` markers in ``maps_to`` strings (the two key-introducers used
in the current YAML). Keys that look like dotted identifiers
(``budgets.llm.max_tokens_total``) are matched directly; questions whose
``maps_to`` describes list-shaped fields (``guardrails``,
``secondary_metrics``) match the head of any ``<FILL_ME>`` path under that
key. Questions that point at non-.example targets (e.g.
``data/splits/MANIFEST.json``, ``<host>/...``) are skipped — those are
agent-derived or operational, not template-file keys.

Exit codes:
    0 = no drift
    1 = drift detected (printed report)
    2 = invocation/parse error
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]


# Keys that appear after these markers in a ``maps_to`` string are config keys
# the question is responsible for filling. Two markers are recognized:
#   ``::`` anywhere — inline single-key form, e.g. ``config/x.yaml :: foo.bar``.
#   ``→`` at the START of a line — explicit list-of-keys form, used when one
#     question fills multiple keys (the enforcement_params multi-mechanism case).
# Requiring ``→`` to be line-leading prevents prose like ``(No → marker because)``
# from being mis-parsed as a key reference. The {3,} length minimum is a
# secondary guard against stopword false-positives.
KEY_PATTERN = re.compile(
    r"(?:::|^\s*→)\s*([A-Za-z_][\w.]{2,})",
    re.MULTILINE,
)

# A ``config/...`` mention anchors which .example file the subsequent keys
# refer to. Multiple `config/...` references in one maps_to are uncommon but
# handled: the parser tracks the most-recent anchor as it scans.
CONFIG_FILE_PATTERN = re.compile(r"config/([a-z_]+)\.yaml(?:\.example)?")

# True list-shaped keys: the .example config has these as YAML lists, and
# questions cover the list head rather than indexing into elements. For these,
# the forward-drift check verifies the head exists at top level; sub-path
# validation doesn't make sense.
#
# `primary_metric` and `budgets` are NOT here — they are nested mappings in
# the config, and questions claim specific sub-paths (`primary_metric.name`,
# `budgets.llm.max_tokens_total`). Those resolve through the normal dotted
# walk, so the forward-drift check catches sub-key renames.
LIST_SHAPED_KEYS: set[str] = {
    "guardrails",
    "secondary_metrics",
    "subgroups",
}


def load_questionnaire(path: Path) -> dict[str, Any]:
    """Load BOOTSTRAP_QUESTIONS.yaml and return the parsed dict."""
    # An unreadable (OSError), non-UTF-8 (UnicodeDecodeError), or malformed
    # (yaml.YAMLError) questionnaire is a clean exit-2 SystemExit, never a
    # traceback.
    try:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise SystemExit(f"{path}: not readable/parseable: {exc}")
    if not isinstance(data, dict) or "groups" not in data:
        raise SystemExit(f"{path}: not a valid questionnaire (missing 'groups' key)")
    return data  # type: ignore[no-any-return]


def collect_questions(questionnaire: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten all questions across all groups."""
    questions: list[dict[str, Any]] = []
    # `groups` is untrusted YAML. A truthy non-list (e.g. `groups: 42` or a bare
    # string) would survive `or []` and then either crash iteration with
    # TypeError or silently iterate string characters. Coerce to a list so a
    # malformed questionnaire yields zero questions rather than a traceback (the
    # 'groups' KEY presence is already asserted in load_questionnaire).
    groups = questionnaire.get("groups")
    groups = groups if isinstance(groups, list) else []
    for group in groups:
        if not isinstance(group, dict):
            continue
        group_questions = group.get("questions")
        group_questions = group_questions if isinstance(group_questions, list) else []
        for q in group_questions:
            if isinstance(q, dict):
                questions.append(q)
    return questions


def extract_claimed_keys(
    questions: list[dict[str, Any]],
) -> dict[str, set[str]]:
    """Return {config_file_basename: set_of_dotted_keys} the questionnaire claims to fill.

    Skips questions whose maps_to references non-config targets
    (``data/splits/MANIFEST.json``, ``<host>/...``, operational).
    """
    claimed: dict[str, set[str]] = {}
    for q in questions:
        maps_to = q.get("maps_to", "")
        if not isinstance(maps_to, str):
            continue

        # Run the two module-level patterns separately, then interleave
        # matches by start position so a key reference inherits the most-
        # recent config-file anchor that precedes it. This keeps the regex
        # definitions in one place (the module constants) without smuggling
        # nested capture groups through a combined alternation.
        anchors: list[tuple[int, str, str]] = []
        for m in CONFIG_FILE_PATTERN.finditer(maps_to):
            anchors.append((m.start(), "file", m.group(1)))
        for m in KEY_PATTERN.finditer(maps_to):
            anchors.append((m.start(), "key", m.group(1)))
        anchors.sort(key=lambda x: x[0])

        current_file: str | None = None
        for _, kind, value in anchors:
            if kind == "file":
                current_file = value
            elif kind == "key" and current_file is not None:
                claimed.setdefault(current_file, set()).add(value)
    return claimed


def load_example_config(example_path: Path) -> dict[str, Any]:
    """Load a template/config/<file>.yaml.example file."""
    # An unreadable (OSError), non-UTF-8 (UnicodeDecodeError), or malformed
    # (yaml.YAMLError) .example config is a clean SystemExit, never a traceback.
    try:
        with open(example_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise SystemExit(f"{example_path}: not readable/parseable: {exc}")
    if not isinstance(data, dict):
        raise SystemExit(
            f"{example_path}: top-level YAML must be a mapping, got "
            f"{type(data).__name__}"
        )
    return data  # type: ignore[no-any-return]


def walk_dotted_key(data: dict[str, Any], dotted: str) -> bool:
    """Return True if ``dotted`` resolves to a value in ``data``.

    Handles list members under list-shaped keys by allowing the dotted path
    to terminate at the list (e.g. ``secondary_metrics`` resolves to the list,
    and the list's contents may contain ``<FILL_ME>`` placeholders).
    """
    cur: Any = data
    for part in dotted.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return False
    return True


def enumerate_fill_me_paths(example_path: Path) -> list[str]:
    """Return dotted paths in the .example file containing ``<FILL_ME>``.

    Walks the parsed YAML and reports every leaf-or-list path whose value
    contains the placeholder. List items contribute the parent path only
    (we don't distinguish ``secondary_metrics[0].name`` from
    ``secondary_metrics[1].name``).
    """
    data = load_example_config(example_path)
    paths: list[str] = []

    def contains_fill_me(value: Any) -> bool:
        """True if ``<FILL_ME>`` appears anywhere in ``value`` or its descendants."""
        if isinstance(value, str):
            return "<FILL_ME>" in value
        if isinstance(value, dict):
            return any(contains_fill_me(v) for v in value.values())
        if isinstance(value, list):
            return any(contains_fill_me(item) for item in value)
        return False

    def walk(value: Any, prefix: str) -> None:
        if isinstance(value, str) and "<FILL_ME>" in value:
            paths.append(prefix)
        elif isinstance(value, dict):
            for k, v in value.items():
                walk(v, f"{prefix}.{k}" if prefix else k)
        elif isinstance(value, list):
            # Report the list-level path once if any descendant contains
            # `<FILL_ME>`. The recursive `contains_fill_me` covers nested
            # dicts and lists inside elements (not just immediate dict values).
            if any(contains_fill_me(item) for item in value):
                paths.append(prefix)

    walk(data, "")
    return paths


def key_is_covered(path: str, claimed: set[str]) -> bool:
    """True if any claimed key matches ``path`` or a list-shaped head of it."""
    if path in claimed:
        return True
    head = path.split(".")[0]
    if head in LIST_SHAPED_KEYS and head in claimed:
        return True
    # Also true if a claimed key is a strict prefix of the path (e.g. claimed
    # 'primary_metric.name' covers path 'primary_metric.name').
    for c in claimed:
        if path.startswith(c + "."):
            return True
    return False


def check_forward_drift(
    claimed: dict[str, set[str]],
    config_dir: Path,
) -> list[str]:
    """For each claimed key, verify it exists in the corresponding .example file."""
    errors: list[str] = []
    for file_base, keys in sorted(claimed.items()):
        example_path = config_dir / f"{file_base}.yaml.example"
        if not example_path.exists():
            errors.append(
                f"FORWARD: questionnaire references config/{file_base}.yaml "
                f"but {example_path} does not exist"
            )
            continue
        data = load_example_config(example_path)
        for key in sorted(keys):
            head = key.split(".")[0]
            if head in LIST_SHAPED_KEYS:
                # For list-shaped keys, verify the head exists; list contents
                # are documented inside the .example file's comments.
                if head not in data:
                    errors.append(
                        f"FORWARD: questionnaire claims to fill "
                        f"config/{file_base}.yaml :: {key}, but key "
                        f"'{head}' does not exist at top level of "
                        f"{example_path.name}"
                    )
                continue
            if not walk_dotted_key(data, key):
                errors.append(
                    f"FORWARD: questionnaire claims to fill "
                    f"config/{file_base}.yaml :: {key}, but that key path "
                    f"does not exist in {example_path.name}"
                )
    return errors


def check_reverse_drift(
    claimed: dict[str, set[str]],
    config_dir: Path,
) -> list[str]:
    """For each <FILL_ME> in each .example file, verify some question covers it."""
    errors: list[str] = []
    for example_path in sorted(config_dir.glob("*.yaml.example")):
        file_base = example_path.stem.split(".")[0]
        fill_me_paths = enumerate_fill_me_paths(example_path)
        questionnaire_keys = claimed.get(file_base, set())
        for path in fill_me_paths:
            if not key_is_covered(path, questionnaire_keys):
                errors.append(
                    f"REVERSE: {example_path.name} has <FILL_ME> at "
                    f"key '{path}' but no question in BOOTSTRAP_QUESTIONS.yaml "
                    f"claims to fill it"
                )
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Drift check between BOOTSTRAP_QUESTIONS.yaml and "
            "template/config/*.yaml.example. Exits 0 on clean, 1 on drift, "
            "2 on invocation error."
        ),
    )
    parser.add_argument(
        "--scaffold-root",
        type=Path,
        default=None,
        help=(
            "Scaffold root holding BOOTSTRAP_QUESTIONS.yaml and config/ "
            "(`template/` upstream, `autoresearch/` in a host install). "
            "Default: the scaffold this script lives in (one level up from "
            "scripts/)."
        ),
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=None,
        help=(
            "DEPRECATED. The REPOSITORY root that CONTAINS the scaffold under "
            "`template/` (i.e. the scaffold is `<repo-root>/template`). Retained "
            "for old callers; prefer --scaffold-root, which names the scaffold "
            "directory directly."
        ),
    )
    args = parser.parse_args()

    # The scaffold root is the directory that holds BOOTSTRAP_QUESTIONS.yaml and
    # config/. It is `template/` in this upstream repo and `autoresearch/` once
    # the scaffold is vendored into a host. Three resolutions, most-specific first:
    #   1. --scaffold-root X : X IS the scaffold (new, explicit).
    #   2. --repo-root X     : DEPRECATED alias — X is the REPOSITORY root that
    #      contains the scaffold under `template/`, so the scaffold is X/template.
    #      This preserves the ORIGINAL --repo-root contract (old callers pass the
    #      repo root, not the scaffold) instead of silently repointing it.
    #   3. default (no flag) : the scaffold this script lives in (one level up
    #      from scripts/) — works identically in `template/` upstream and
    #      `autoresearch/` in a host install.
    scaffold: Path
    if args.scaffold_root is not None:
        scaffold = args.scaffold_root
    elif args.repo_root is not None:
        scaffold = args.repo_root / "template"
    else:
        scaffold = Path(__file__).resolve().parent.parent

    questionnaire_path = scaffold / "BOOTSTRAP_QUESTIONS.yaml"
    config_dir = scaffold / "config"

    if not questionnaire_path.exists():
        print(f"error: questionnaire not found at {questionnaire_path}")
        return 2
    if not config_dir.is_dir():
        print(f"error: config dir not found at {config_dir}")
        return 2

    questionnaire = load_questionnaire(questionnaire_path)
    questions = collect_questions(questionnaire)
    claimed = extract_claimed_keys(questions)

    forward = check_forward_drift(claimed, config_dir)
    reverse = check_reverse_drift(claimed, config_dir)

    if not forward and not reverse:
        n_q = len(questions)
        n_files = len(list(config_dir.glob("*.yaml.example")))
        print(f"OK: {n_q} questions ↔ {n_files} .example config files, no drift.")
        return 0

    print(f"DRIFT DETECTED: {len(forward)} forward + {len(reverse)} reverse")
    print()
    for e in forward:
        print(f"  {e}")
    for e in reverse:
        print(f"  {e}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
