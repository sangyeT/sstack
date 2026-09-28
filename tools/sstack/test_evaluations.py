import copy
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

import evaluations


class EvaluationTests(unittest.TestCase):
    def setUp(self):
        self.plan = {
            "schema_version": 1,
            "issue": "FME-example",
            "author": "pm-session",
            "implementer": "engineer-session",
            "acceptance_ids": ["AC1", "AC2"],
            "cases": [
                {
                    "id": "valid",
                    "acceptance_id": "AC1",
                    "input": {"value": 5},
                    "expected": {"value": 10},
                    "phase": "premerge",
                    "surface": "local",
                    "route": "existing_test.py::test_double",
                },
                {
                    "id": "deployed",
                    "acceptance_id": "AC2",
                    "input": {"record": "synthetic"},
                    "expected": {"status": "complete"},
                    "phase": "postmerge",
                    "surface": "live",
                    "route": "read back exact execution and its synthetic record",
                },
            ],
        }
        self.result = {
            "schema_version": 1,
            "issue": self.plan["issue"],
            "plan_digest": evaluations.plan_digest(self.plan),
            "head": "head-sha",
            "base": "base-sha",
            "fingerprint": "source-digest",
            "phase": "premerge",
            "verifier": "verifier-session",
            "cases": [{"id": "valid", "observed": {"value": 10}, "evidence": ["ci://run/1"]}],
        }

    def score(self, **kwargs):
        return evaluations.evaluate(
            self.plan,
            self.result,
            head="head-sha",
            base="base-sha",
            fingerprint="source-digest",
            **kwargs,
        )

    def test_exact_observation_passes_without_executing_route(self):
        self.assertEqual(self.score()["status"], "passed")
        self.assertIn("does not authenticate", self.score()["limitations"][0])
        self.assertEqual(self.score()["checked"], ["valid"])

    def test_plan_is_stable_under_object_key_reordering_and_changes_on_amendment(self):
        original = evaluations.plan_digest(self.plan)
        reordered = dict(reversed(list(self.plan.items())))
        self.assertEqual(original, evaluations.plan_digest(reordered))
        self.plan["cases"][0]["expected"] = {"value": 11}
        self.assertNotEqual(original, evaluations.plan_digest(self.plan))
        self.assertEqual(self.score()["status"], "blocked")

    def test_missing_duplicate_unknown_and_uncovered_acceptance_are_invalid(self):
        for mutation in ("empty", "duplicate", "unknown", "uncovered"):
            with self.subTest(mutation=mutation):
                plan = copy.deepcopy(self.plan)
                if mutation == "empty":
                    plan["cases"] = []
                elif mutation == "duplicate":
                    plan["cases"].append(plan["cases"][0])
                elif mutation == "unknown":
                    plan["cases"][0]["acceptance_id"] = "AC3"
                else:
                    plan["acceptance_ids"].append("AC3")
                with self.assertRaises(ValueError):
                    evaluations.validate_plan(plan)

    def test_missing_extra_duplicate_cases_block(self):
        original = copy.deepcopy(self.result)
        for cases in (
            [],
            original["cases"] * 2,
            original["cases"] + [{"id": "extra", "observed": True, "evidence": ["ci://2"]}],
        ):
            with self.subTest(cases=cases):
                self.result["cases"] = cases
                self.assertEqual(self.score()["status"], "blocked")

    def test_binding_and_independence_failures_block(self):
        original = copy.deepcopy(self.result)
        for key in ("issue", "plan_digest", "head", "base", "fingerprint", "phase", "verifier"):
            with self.subTest(key=key):
                self.result = copy.deepcopy(original)
                self.result[key] = self.plan["implementer"] if key == "verifier" else "stale"
                self.assertEqual(self.score()["status"], "blocked")

    def test_mismatch_fails_and_boolean_does_not_equal_number(self):
        self.plan["cases"][0]["expected"] = 1
        self.result["plan_digest"] = evaluations.plan_digest(self.plan)
        self.result["cases"][0]["observed"] = True
        self.assertEqual(self.score()["status"], "failed")
        self.assertEqual(self.score()["reasons"], ["outcome_mismatch:valid"])

    def test_a_passed_flag_cannot_replace_an_observation(self):
        self.result["cases"][0] = {"id": "valid", "passed": True, "evidence": ["ci://1"]}
        self.assertEqual(self.score()["status"], "blocked")

    def test_empty_na_or_missing_evidence_blocks(self):
        for evidence in ([], ["N/A"], [""], [False], None):
            with self.subTest(evidence=evidence):
                self.result["cases"][0]["evidence"] = evidence
                self.assertEqual(self.score()["status"], "blocked")

    def test_postmerge_does_not_accept_premerge_case(self):
        self.result["phase"] = "postmerge"
        self.assertEqual(self.score(phase="postmerge")["status"], "blocked")
        self.result["cases"] = [
            {"id": "deployed", "observed": {"status": "complete"}, "evidence": ["kizen://run/1"]}
        ]
        self.assertEqual(self.score(phase="postmerge")["status"], "passed")

    def test_empty_phase_is_not_a_pass(self):
        self.plan["cases"][0]["phase"] = "postmerge"
        self.result["plan_digest"] = evaluations.plan_digest(self.plan)
        self.result["cases"] = []
        self.assertEqual(self.score()["status"], "not_required")

    def test_bad_json_and_boolean_schema_version_are_rejected(self):
        for value in (float("nan"), float("inf"), {2: "non-string key"}, {1, 2}):
            with self.subTest(value=value):
                self.plan["cases"][0]["expected"] = value
                with self.assertRaises(ValueError):
                    evaluations.validate_plan(self.plan)
        self.setUp()
        self.plan["schema_version"] = True
        with self.assertRaises(ValueError):
            evaluations.validate_plan(self.plan)

    def test_cli_duplicate_json_keys_block(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "plan.json"
            path.write_text('{"issue":"one","issue":"two"}')
            output = io.StringIO()
            with redirect_stdout(output):
                code = evaluations.main(["validate", str(path)])
            self.assertEqual(code, 1)
            self.assertEqual(json.loads(output.getvalue())["status"], "blocked")


class MetricsTests(unittest.TestCase):
    def audit(self, issue, done=True, correct=True, recovery=False, recovered=None):
        return {
            "issue": issue,
            "implementer": "engineer",
            "auditor": "independent",
            "claimed_done": done,
            "outcome_correct": correct,
            "recovery_required": recovery,
            "recovered": recovered,
            "unnecessary_interventions": 0,
        }

    def test_measured_denominators_and_missing_samples(self):
        empty = evaluations.metrics([])
        self.assertIsNone(empty["false_done_rate"])
        self.assertIsNone(empty["recovery_rate"])
        result = evaluations.metrics(
            [
                self.audit("A"),
                self.audit("B", correct=False),
                self.audit("C", done=False, correct=False, recovery=True, recovered=True),
            ]
        )
        self.assertEqual(result["audited"], 3)
        self.assertEqual(result["correct_completions"], 1)
        self.assertEqual(result["false_done_rate"], 0.5)
        self.assertEqual(result["recovery_rate"], 1)

    def test_unaudited_duplicate_and_ambiguous_records_fail(self):
        for mutation in ("self", "unknown", "boolean_count", "duplicate"):
            with self.subTest(mutation=mutation):
                audit = self.audit("A")
                audits = [audit]
                if mutation == "self":
                    audit["auditor"] = audit["implementer"]
                elif mutation == "unknown":
                    audit["outcome_correct"] = None
                elif mutation == "boolean_count":
                    audit["unnecessary_interventions"] = True
                else:
                    audits.append(audit)
                with self.assertRaises(ValueError):
                    evaluations.metrics(audits)


if __name__ == "__main__":
    unittest.main()
