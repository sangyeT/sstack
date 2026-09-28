import argparse
import hashlib
import json
import math
from pathlib import Path

PLAN_FIELDS = {"schema_version", "issue", "author", "implementer", "acceptance_ids", "cases"}
CASE_FIELDS = {"id", "acceptance_id", "input", "expected", "phase", "surface", "route"}
RESULT_FIELDS = {
    "schema_version",
    "issue",
    "plan_digest",
    "head",
    "base",
    "fingerprint",
    "phase",
    "verifier",
    "cases",
}
PHASES = {"premerge", "postmerge"}


def _object(value, fields, name):
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError(f"{name}: incorrect fields")


def _text(value, name):
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ValueError(f"{name}: nonempty trimmed text required")
    if value.lower() in {"n/a", "na", "tbd", "unknown"}:
        raise ValueError(f"{name}: unresolved value")


def _json(value):
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise ValueError("JSON object keys must be strings")
        for item in value.values():
            _json(item)
    elif isinstance(value, list):
        for item in value:
            _json(item)
    elif type(value) not in (str, bool, int, float, type(None)):
        raise ValueError("JSON value required")
    elif isinstance(value, float) and not math.isfinite(value):
        raise ValueError("Non-finite numbers are not JSON values")
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def validate_plan(plan):
    _object(plan, PLAN_FIELDS, "plan")
    if type(plan["schema_version"]) is not int or plan["schema_version"] != 1:
        raise ValueError("plan: unsupported schema_version")
    for key in ("issue", "author", "implementer"):
        _text(plan[key], key)
    acceptance = plan["acceptance_ids"]
    if not isinstance(acceptance, list) or not acceptance:
        raise ValueError("plan: acceptance_ids required")
    for identifier in acceptance:
        _text(identifier, "acceptance_id")
    if len(set(acceptance)) != len(acceptance):
        raise ValueError("plan: duplicate acceptance_id")
    if not isinstance(plan["cases"], list) or not plan["cases"]:
        raise ValueError("plan: cases required")
    identifiers, covered = set(), set()
    for case in plan["cases"]:
        _object(case, CASE_FIELDS, "case")
        for key in ("id", "acceptance_id", "phase", "surface", "route"):
            _text(case[key], f"case.{key}")
        if case["id"] in identifiers:
            raise ValueError("plan: duplicate case id")
        identifiers.add(case["id"])
        if case["acceptance_id"] not in acceptance:
            raise ValueError("plan: unknown acceptance_id")
        covered.add(case["acceptance_id"])
        if case["phase"] not in PHASES or case["surface"] not in {"local", "live", "ui"}:
            raise ValueError("plan: invalid phase or surface")
        _json(case["input"])
        _json(case["expected"])
    if covered != set(acceptance):
        raise ValueError("plan: uncovered acceptance_id")


def plan_digest(plan):
    validate_plan(plan)
    return hashlib.sha256(_json(plan).encode()).hexdigest()


def evaluate(plan, result, *, head, base, fingerprint, phase="premerge"):
    report = {"status": "blocked", "reasons": [], "checked": [], "limitations": []}
    try:
        digest = plan_digest(plan)
        for name, value in (("head", head), ("base", base), ("fingerprint", fingerprint)):
            _text(value, name)
        if phase not in PHASES:
            raise ValueError("invalid requested phase")
        _object(result, RESULT_FIELDS, "result")
        if type(result["schema_version"]) is not int or result["schema_version"] != 1:
            raise ValueError("result: unsupported schema_version")
        bindings = {
            "issue": plan["issue"],
            "plan_digest": digest,
            "head": head,
            "base": base,
            "fingerprint": fingerprint,
            "phase": phase,
        }
        for name, value in bindings.items():
            if result[name] != value:
                raise ValueError(f"result: stale or mismatched {name}")
        _text(result["verifier"], "verifier")
        if result["verifier"] == plan["implementer"]:
            raise ValueError("result: verifier must be independent of implementer")
        expected = {case["id"]: case for case in plan["cases"] if case["phase"] == phase}
        if not isinstance(result["cases"], list):
            raise ValueError("result: cases must be a list")
        actual = {}
        for case in result["cases"]:
            _object(case, {"id", "observed", "evidence"}, "result case")
            _text(case["id"], "result case.id")
            if case["id"] in actual:
                raise ValueError("result: duplicate case id")
            actual[case["id"]] = case
            _json(case["observed"])
            if not isinstance(case["evidence"], list) or not case["evidence"]:
                raise ValueError("result: evidence references required")
            for reference in case["evidence"]:
                _text(reference, "evidence reference")
        if set(expected) != set(actual):
            raise ValueError("result: missing or extra cases for phase")
        if not expected:
            report.update(status="not_required", reasons=["no_cases_for_phase"])
            return report
        for identifier, case in expected.items():
            report["checked"].append(identifier)
            if _json(actual[identifier]["observed"]) != _json(case["expected"]):
                report["reasons"].append(f"outcome_mismatch:{identifier}")
        report["status"] = "failed" if report["reasons"] else "passed"
        report["limitations"] = [
            "Scoring checks supplied observations and bindings; it does not authenticate identities, "
            "fetch evidence references, run routes, or prove a UI journey or deployment. "
            "The independent verifier must inspect the referenced evidence."
        ]
        report.update(plan_digest=digest, phase=phase)
    except (ValueError, TypeError) as error:
        report["reasons"].append(str(error))
    return report


def metrics(audits):
    if not isinstance(audits, list):
        raise ValueError("audits must be a list")
    seen = set()
    fields = {
        "issue",
        "implementer",
        "auditor",
        "claimed_done",
        "outcome_correct",
        "recovery_required",
        "recovered",
        "unnecessary_interventions",
    }
    for audit in audits:
        _object(audit, fields, "audit")
        for key in ("issue", "implementer", "auditor"):
            _text(audit[key], key)
        if audit["issue"] in seen:
            raise ValueError("duplicate audited issue")
        seen.add(audit["issue"])
        if audit["implementer"] == audit["auditor"]:
            raise ValueError("independent auditor required")
        for key in ("claimed_done", "outcome_correct", "recovery_required"):
            if type(audit[key]) is not bool:
                raise ValueError(f"audit: {key} must be boolean")
        if audit["recovery_required"]:
            if type(audit["recovered"]) is not bool:
                raise ValueError("audit: recovery outcome required")
        elif audit["recovered"] is not None:
            raise ValueError("audit: recovery outcome must be null when not attempted")
        count = audit["unnecessary_interventions"]
        if type(count) is not int or count < 0:
            raise ValueError("audit: nonnegative intervention count required")
    done = sum(audit["claimed_done"] for audit in audits)
    correct = sum(audit["claimed_done"] and audit["outcome_correct"] for audit in audits)
    recovery = sum(audit["recovery_required"] for audit in audits)
    recovered = sum(audit["recovered"] is True for audit in audits)
    return {
        "audited": len(audits),
        "claimed_done": done,
        "correct_completions": correct,
        "correct_completion_rate": correct / len(audits) if audits else None,
        "false_done": done - correct,
        "false_done_rate": (done - correct) / done if done else None,
        "recovery_required": recovery,
        "recovered": recovered,
        "recovery_rate": recovered / recovery if recovery else None,
        "unnecessary_interventions": sum(audit["unnecessary_interventions"] for audit in audits),
        "unnecessary_interventions_per_audited_issue": (
            sum(audit["unnecessary_interventions"] for audit in audits) / len(audits)
            if audits
            else None
        ),
    }


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _load(path):
    return json.loads(Path(path).read_text(), object_pairs_hook=_unique_object)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Validate PM evaluation plans and score observations"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate")
    validate.add_argument("plan")
    score = commands.add_parser("score")
    score.add_argument("plan")
    score.add_argument("result")
    for flag in ("head", "base", "fingerprint"):
        score.add_argument(f"--{flag}", required=True)
    score.add_argument("--phase", choices=sorted(PHASES), default="premerge")
    audit = commands.add_parser("metrics")
    audit.add_argument("audits")
    args = parser.parse_args(argv)
    try:
        if args.command == "validate":
            report = {"status": "valid", "plan_digest": plan_digest(_load(args.plan))}
        elif args.command == "metrics":
            report = metrics(_load(args.audits))
        else:
            report = evaluate(
                _load(args.plan),
                _load(args.result),
                head=args.head,
                base=args.base,
                fingerprint=args.fingerprint,
                phase=args.phase,
            )
    except (OSError, ValueError) as error:
        report = {"status": "blocked", "reasons": [str(error)]}
    print(json.dumps(report, indent=2, allow_nan=False))
    return 1 if report.get("status") in {"blocked", "failed"} else 0


if __name__ == "__main__":
    raise SystemExit(main())
