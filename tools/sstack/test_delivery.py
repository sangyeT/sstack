import contextlib
import copy
import hashlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import control
import delivery
import evaluations


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.git("init", "-q")
        (self.root / ".gitignore").write_text("artifacts/\n")
        directory = self.root / "tools/sstack"
        directory.mkdir(parents=True)
        (directory / "projects.json").write_text(
            json.dumps(
                {
                    "version": 1,
                    "projects": [
                        {
                            "id": "sample",
                            "paths": ["sample.py"],
                            "suites": ["stack"],
                            "external": [],
                            "affects": [],
                        }
                    ],
                }
            )
        )
        self.commit()
        self.base = self.git("rev-parse", "HEAD")
        (self.root / "sample.py").write_text("value = 1\n")
        self.commit()
        self.artifact = {
            "head": self.git("rev-parse", "HEAD"),
            "base": self.base,
            "fingerprint": control.fingerprint(self.root),
            "pr": 18,
        }
        self.plan = {
            "schema_version": 1,
            "issue": "FME-EXAMPLE",
            "author": "pm",
            "implementer": "engineer",
            "acceptance_ids": ["stored-value"],
            "cases": [
                {
                    "id": "unit",
                    "acceptance_id": "stored-value",
                    "input": {"value": 1},
                    "expected": {"stored": 1},
                    "phase": "premerge",
                    "surface": "local",
                    "route": "existing-test",
                },
                {
                    "id": "live",
                    "acceptance_id": "stored-value",
                    "input": {"value": 1},
                    "expected": {"stored": 1},
                    "phase": "postmerge",
                    "surface": "live",
                    "route": "synthetic-readback",
                },
            ],
        }
        self.contract = {
            "issue": "FME-EXAMPLE",
            "project": "sample",
            "repository": "example/repo",
            "base_branch": "main",
            "environment": "synthetic-only",
            "checkout": str(self.root),
            "allow_merge": True,
            "rollout_required": True,
            "resources": ["environment:synthetic/automation:example"],
            "required_checks": ["quality"],
            "evaluations": self.plan,
        }
        self.now = [1000.0]
        self.store = delivery.Store(delivery.default_database(self.root), clock=lambda: self.now[0])
        self.store.create(self.contract)
        self.claim = self.store.claim(self.contract["issue"], "pm-session", 300)
        self.issue, self.owner, self.epoch = (
            self.contract["issue"],
            "pm-session",
            self.claim["epoch"],
        )
        self.merged = False

    def git(self, *args):
        return subprocess.run(
            ["git", *args], cwd=self.root, capture_output=True, text=True, check=True
        ).stdout.strip()

    def commit(self):
        self.git("add", ".")
        self.git(
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-qm",
            "fixture",
        )

    def remote(self, contract, pr):
        return {
            "headRefOid": self.artifact["head"],
            "baseRefOid": self.artifact["base"],
            "baseRefName": "main",
            "state": "MERGED" if self.merged else "OPEN",
            "isDraft": False,
            "mergeStateStatus": "CLEAN",
            "statusCheckRollup": [{"name": "quality", "conclusion": "SUCCESS"}],
            "mergeCommit": {"oid": "f" * 40} if self.merged else None,
            "autoMergeRequest": None,
        }

    def ref(self, name, value):
        directory = self.root / "artifacts"
        directory.mkdir(exist_ok=True)
        path = directory / name
        data = json.dumps(value).encode()
        path.write_bytes(data)
        return {"path": str(path), "sha256": hashlib.sha256(data).hexdigest()}

    def result(self, phase):
        return {
            "schema_version": 1,
            "issue": self.issue,
            "plan_digest": evaluations.plan_digest(self.plan),
            "head": self.artifact["head"],
            "base": self.artifact["base"],
            "fingerprint": self.artifact["fingerprint"],
            "phase": phase,
            "verifier": "independent-verifier",
            "cases": [
                {
                    "id": case["id"],
                    "observed": case["expected"],
                    "evidence": ["synthetic-observation:1"],
                }
                for case in self.plan["cases"]
                if case["phase"] == phase
            ],
        }

    def packet(self, state):
        if state == "ready":
            return {"plan_digest": evaluations.plan_digest(self.plan)}
        if state == "building":
            return {"artifact": self.artifact}
        if state == "validating":
            log = self.ref("check.log", {"synthetic_test": "passed"})
            report = {
                "git_revision": self.artifact["head"],
                "base_revision": self.artifact["base"],
                "source_fingerprint_before": self.artifact["fingerprint"],
                "source_fingerprint_after": self.artifact["fingerprint"],
                "sources_changed_during_run": False,
                "checks": [
                    {
                        "name": name,
                        "cwd": cwd,
                        "command": command,
                        "status": "passed",
                        "exit_code": 0,
                        "log": "artifacts/check.log",
                        "log_sha256": log["sha256"],
                    }
                    for name, cwd, command in control.SUITES["stack"]
                ],
            }
            return {
                "artifact": self.artifact,
                "coverage": self.ref("coverage.json", control.coverage(self.root, self.base)),
                "verification": [self.ref("verification.json", report)],
                "evaluation": self.ref("premerge.json", self.result("premerge")),
            }
        if state == "reviewing":
            return {
                "review": self.ref(
                    "review.json",
                    {
                        "artifact": self.artifact,
                        "plan_digest": evaluations.plan_digest(self.plan),
                        "reviewer": "independent-reviewer",
                        "decision": "approved",
                        "blocking_findings": [],
                    },
                )
            }
        if state == "merge_ready":
            return {}
        if state == "merged":
            return {
                "merge_sha": "f" * 40,
                "environment": "synthetic-only",
                "rollout": self.ref(
                    "postmerge.json",
                    {
                        "merge_sha": "f" * 40,
                        "environment": "synthetic-only",
                        "deployment_ref": "synthetic-deployment:1",
                        "execution_refs": ["synthetic-run:1"],
                        "result": self.result("postmerge"),
                    },
                ),
            }
        return {
            "closure": self.ref(
                "closure.json",
                {
                    "issue": self.issue,
                    "merge_sha": "f" * 40,
                    "status": "done",
                    "readback_ref": "synthetic-jira:done",
                },
            )
        }

    def advance(self):
        state = self.store.status(self.issue)["state"]
        operation = self.store.begin(self.issue, self.owner, self.epoch, reader=self.remote)
        if state == "merge_ready":
            self.merged = True
        return self.store.complete(
            self.issue,
            self.owner,
            self.epoch,
            operation["id"],
            self.packet(state),
            reader=self.remote,
        )

    def reach(self, target):
        while self.store.status(self.issue)["state"] != target:
            self.advance()

    def test_validation_accepts_embedded_coverage_without_duplicate_report(self):
        packet = self.packet("validating")
        report = delivery.evidence_file(packet["verification"][0])
        report.update(scope="offline", coverage=delivery.evidence_file(packet["coverage"]))
        reference = self.ref("combined.json", report)
        packet.update(coverage=reference, verification=[reference])
        task = {
            "state": "validating",
            "contract": self.contract,
            "context": {"artifact": self.artifact},
        }
        delivery.gate(task, packet)
        report["coverage"]["files"] = {}
        reference = self.ref("combined.json", report)
        packet.update(coverage=reference, verification=[reference])
        with self.assertRaisesRegex(delivery.Blocked, "coverage_changed_or_incomplete"):
            delivery.gate(task, packet)

    def test_validation_uses_engineer_checkout_suite_not_coordinator_registry(self):
        path = self.root / "tools/sstack/projects.json"
        document = json.loads(path.read_text())
        document["projects"][0]["paths"].append("tools/sstack/projects.json")
        document["projects"][0]["suites"] = ["engineer-only"]
        document["suites"] = {
            "engineer-only": [
                {
                    "name": "engineer-tests",
                    "cwd": ".",
                    "command": ["$PYTHON", "-c", "assert 2 + 2 == 4"],
                }
            ]
        }
        path.write_text(json.dumps(document))
        self.commit()
        self.artifact.update(
            head=self.git("rev-parse", "HEAD"), fingerprint=control.fingerprint(self.root)
        )
        self.assertNotIn("engineer-only", control.SUITES)
        report = control.verify("changed", base=self.base, root=self.root)
        self.assertEqual(report["status"], "passed")
        packet = self.packet("validating")
        packet["verification"] = [self.ref("engineer-report.json", report)]
        task = {
            "state": "validating",
            "contract": self.contract,
            "context": {"artifact": self.artifact},
        }
        delivery.gate(task, packet, reader=self.remote)
        report["checks"][0]["command"] = [sys.executable, "-c", "print('wrong command')"]
        packet["verification"] = [self.ref("engineer-report.json", report)]
        with self.assertRaisesRegex(delivery.Blocked, "verification_command_mismatch"):
            delivery.gate(task, packet, reader=self.remote)

    def test_complete_simulated_delivery_and_reopen_at_every_transition(self):
        for expected in delivery.STATES[1:]:
            self.assertEqual(self.advance()["state"], expected)
            self.store = delivery.Store(self.store.path, clock=lambda: self.now[0])
            self.assertEqual(self.store.status(self.issue)["state"], expected)
        with contextlib.closing(self.store.connect()) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM resources").fetchone()[0], 0)

    def test_atomic_claim_two_competing_pm_sessions(self):
        self.now[0] += 301

        def claim(owner):
            try:
                return delivery.Store(self.store.path, clock=lambda: self.now[0]).claim(
                    self.issue, owner, 300
                )["owner"]
            except delivery.Blocked:
                return None

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(claim, ["pm-a", "pm-b"]))
        self.assertEqual(sum(value is not None for value in results), 1)

    def test_expired_worker_is_fenced_out_after_takeover(self):
        self.now[0] += 301
        new = self.store.claim(self.issue, "new-pm", 300)
        self.assertGreater(new["epoch"], self.epoch)
        with self.assertRaisesRegex(delivery.Blocked, "ownership_lost"):
            self.store.begin(self.issue, self.owner, self.epoch)

    def test_shared_environment_resource_stays_locked_after_worker_expiry(self):
        contract = copy.deepcopy(self.contract)
        contract["issue"] = contract["evaluations"]["issue"] = "FME-OTHER"
        self.store.create(contract)
        self.now[0] += 301
        with self.assertRaisesRegex(delivery.Blocked, "resource_busy"):
            self.store.claim("FME-OTHER", "other", 300)

    def test_interrupted_merge_reconciles_observed_success_without_replay(self):
        self.reach("merge_ready")
        op = self.store.begin(self.issue, self.owner, self.epoch, reader=self.remote)
        self.merged = True
        self.assertEqual(self.store.status(self.issue)["next_action"], "reconcile")
        with self.assertRaisesRegex(delivery.Blocked, "reconcile_first"):
            self.store.begin(self.issue, self.owner, self.epoch, reader=self.remote)
        result = self.store.reconcile(
            self.issue,
            self.owner,
            self.epoch,
            op["id"],
            {"outcome": "completed", "packet": {}},
            reader=self.remote,
        )
        self.assertEqual(result["state"], "merged")

    def test_failed_worker_stays_pending_and_is_not_automatically_replayed(self):
        marker = self.root / "artifacts/attempts"
        marker.parent.mkdir()
        script = (
            "from pathlib import Path; p=Path("
            + repr(str(marker))
            + "); p.write_text(p.read_text()+'x' if p.exists() else 'x'); raise SystemExit(1)"
        )
        result = delivery.run_worker(
            self.store,
            self.issue,
            self.owner,
            self.epoch,
            [sys.executable, "-c", script],
            max_steps=1,
        )
        self.assertTrue(result["pending"])
        delivery.run_worker(
            self.store,
            self.issue,
            self.owner,
            self.epoch,
            [sys.executable, "-c", script],
            max_steps=1,
        )
        self.assertEqual(marker.read_text(), "x")

    def test_run_worker_uses_persisted_phase_and_operation_identity(self):
        script = (
            "import json,sys; p=json.load(sys.stdin); print(json.dumps({'operation_id':p['operation']['id'],'evidence':{'plan_digest':"
            + repr(evaluations.plan_digest(self.plan))
            + "}}))"
        )
        result = delivery.run_worker(
            self.store,
            self.issue,
            self.owner,
            self.epoch,
            [sys.executable, "-c", script],
            max_steps=1,
        )
        self.assertEqual(result["state"], "building")

    def test_unknown_coverage_and_modified_log_cannot_pass_validation(self):
        self.reach("validating")
        packet = self.packet("validating")
        (self.root / "artifacts/check.log").write_text("changed")
        op = self.store.begin(self.issue, self.owner, self.epoch)
        with self.assertRaisesRegex(delivery.Blocked, "log_changed"):
            self.store.complete(self.issue, self.owner, self.epoch, op["id"], packet)
        packet = self.packet("validating")
        coverage = control.coverage(self.root, self.base)
        coverage["suites"] = []
        packet["coverage"] = self.ref("false-coverage.json", coverage)
        with self.assertRaisesRegex(delivery.Blocked, "coverage_changed_or_incomplete"):
            self.store.complete(self.issue, self.owner, self.epoch, op["id"], packet)

    def test_toml_or_dirty_changes_invalidate_artifact(self):
        self.reach("building")
        (self.root / "settings.toml").write_text("enabled = false\n")
        with self.assertRaisesRegex(delivery.Blocked, "checkout_inputs_changed"):
            self.advance()

    def test_stale_base_and_missing_ci_prevent_merge_readiness(self):
        self.reach("reviewing")
        task = self.store.status(self.issue)
        for update in (
            {"baseRefOid": "0" * 40},
            {"statusCheckRollup": []},
            {"mergeStateStatus": "BLOCKED"},
        ):
            with self.subTest(update=update), self.assertRaises(delivery.Blocked):
                delivery.gate(
                    task,
                    self.packet("reviewing"),
                    reader=lambda c, p, update=update: {**self.remote(c, p), **update},
                )

    def test_self_review_and_failed_outcome_do_not_advance(self):
        self.reach("validating")
        packet = self.packet("validating")
        result = self.result("premerge")
        result["cases"][0]["observed"] = {"stored": 999}
        packet["evaluation"] = self.ref("wrong.json", result)
        with self.assertRaisesRegex(delivery.Blocked, "evaluation_not_passed"):
            delivery.gate(self.store.status(self.issue), packet)
        self.reach("reviewing")
        packet = {
            "review": self.ref(
                "self-review.json",
                {
                    "artifact": self.artifact,
                    "plan_digest": evaluations.plan_digest(self.plan),
                    "reviewer": "engineer",
                    "decision": "approved",
                    "blocking_findings": [],
                },
            )
        }
        with self.assertRaisesRegex(delivery.Blocked, "not_independent"):
            delivery.gate(self.store.status(self.issue), packet)

    def test_revised_head_clears_all_previous_evidence(self):
        self.reach("merge_ready")
        (self.root / "sample.py").write_text("value = 2\n")
        self.commit()
        new = {
            **self.artifact,
            "head": self.git("rev-parse", "HEAD"),
            "fingerprint": control.fingerprint(self.root),
        }
        result = self.store.revise(self.issue, self.owner, self.epoch, new, "fix review finding")
        self.assertEqual(result["state"], "validating")
        self.assertEqual(result["context"], {"artifact": new})

    def test_amending_eval_set_invalidates_old_evidence_and_restarts_dispatch(self):
        self.reach("reviewing")
        plan = copy.deepcopy(self.plan)
        plan["cases"][0]["expected"] = {"stored": 2}
        result = self.store.amend(
            self.issue,
            self.owner,
            self.epoch,
            plan,
            "PM changed acceptance after requirement clarification",
        )
        self.assertEqual(result["state"], "ready")
        self.assertEqual(result["context"], {})

    def test_rollout_failure_and_unconfirmed_jira_keep_issue_open(self):
        self.reach("merged")
        packet = self.packet("merged")
        packet["environment"] = "wrong-business"
        with self.assertRaisesRegex(delivery.Blocked, "environment_mismatch"):
            delivery.gate(self.store.status(self.issue), packet)
        self.reach("rollout_verified")
        with self.assertRaises(delivery.Blocked):
            delivery.gate(
                self.store.status(self.issue),
                {"closure": self.ref("no-jira.json", {"status": "done"})},
            )

    def test_worktrees_resolve_same_coordination_database(self):
        tree = self.root / "artifacts/worktree"
        tree.parent.mkdir()
        self.git("worktree", "add", "-qb", "worker", str(tree))
        self.assertEqual(delivery.default_database(self.root), delivery.default_database(tree))

    def test_moved_database_is_not_cross_host_coordination(self):
        with patch.object(delivery.platform, "node", return_value="another-host"):
            with self.assertRaisesRegex(delivery.Blocked, "different_host"):
                self.store.status(self.issue)

    def test_success_label_on_wrong_command_is_not_verification(self):
        self.reach("validating")
        packet = self.packet("validating")
        report = delivery.evidence_file(packet["verification"][0])
        report["checks"][0]["command"] = [sys.executable, "-c", "pass"]
        packet["verification"] = [self.ref("wrong-command.json", report)]
        with self.assertRaisesRegex(delivery.Blocked, "command_mismatch"):
            delivery.gate(self.store.status(self.issue), packet)

    def test_conflicting_failure_report_cannot_hide_behind_passing_report(self):
        self.reach("validating")
        packet = self.packet("validating")
        report = delivery.evidence_file(packet["verification"][0])
        report["checks"][0]["status"] = "failed"
        packet["verification"].append(self.ref("failed.json", report))
        with self.assertRaisesRegex(delivery.Blocked, "required_check_not_passed"):
            delivery.gate(self.store.status(self.issue), packet)

    def test_review_of_old_plan_cannot_approve_new_plan_at_same_head(self):
        self.reach("reviewing")
        packet = self.packet("reviewing")
        task = self.store.status(self.issue)
        task["contract"]["evaluations"]["cases"][0]["input"] = {"value": 2}
        with self.assertRaisesRegex(delivery.Blocked, "review_plan_stale"):
            delivery.gate(task, packet, reader=self.remote)

    def test_rollout_observation_must_bind_to_actual_merge_and_environment(self):
        self.reach("merged")
        packet = self.packet("merged")
        rollout = delivery.evidence_file(packet["rollout"])
        rollout["merge_sha"] = "0" * 40
        packet["rollout"] = self.ref("stale-rollout.json", rollout)
        with self.assertRaisesRegex(delivery.Blocked, "observation_binding_mismatch"):
            delivery.gate(self.store.status(self.issue), packet)

    def test_timeout_retains_operation_for_reconciliation(self):
        result = delivery.run_worker(
            self.store,
            self.issue,
            self.owner,
            self.epoch,
            [sys.executable, "-c", "import time; time.sleep(30)"],
            timeout=1,
            max_steps=1,
        )
        self.assertTrue(result["pending"])
        self.assertEqual(result["next_action"], "reconcile")

    def test_not_applied_requires_confirmed_old_worker_stop(self):
        operation = self.store.begin(self.issue, self.owner, self.epoch)
        with self.assertRaisesRegex(delivery.Blocked, "previous_worker_must_stop"):
            self.store.reconcile(
                self.issue,
                self.owner,
                self.epoch,
                operation["id"],
                {"outcome": "not_applied", "readback_ref": "observation:1"},
            )

    def test_unattended_worker_completes_simulated_delivery_with_independent_expectations(self):
        packets = {state: self.packet(state) for state in delivery.STATES[:-1]}
        packet_ref = self.ref("worker-packets.json", packets)
        marker = self.root / "artifacts/merged-marker"
        script = (
            "import json,sys; from pathlib import Path; p=json.load(sys.stdin); "
            "state=p['operation']['from']; "
            f"Path({str(marker)!r}).write_text('merged') if state=='merge_ready' else None; "
            f"packets=json.loads(Path({packet_ref['path']!r}).read_text()); "
            "print(json.dumps({'operation_id':p['operation']['id'],'evidence':packets[state]}))"
        )

        def remote(contract, pr):
            self.merged = marker.exists()
            return self.remote(contract, pr)

        result = delivery.run_worker(
            self.store,
            self.issue,
            self.owner,
            self.epoch,
            [sys.executable, "-c", script],
            reader=remote,
        )
        self.assertEqual(result["state"], "done")
        self.assertEqual(
            result["context"]["rollout"]["result"]["cases"][0]["observed"], {"stored": 1}
        )

    def test_documented_run_cli_parses_options_after_issue(self):
        script = (
            "import json,sys; p=json.load(sys.stdin); print(json.dumps({'operation_id':p['operation']['id'],'evidence':{'plan_digest':"
            + repr(evaluations.plan_digest(self.plan))
            + "}}))"
        )
        with contextlib.redirect_stdout(io.StringIO()) as output:
            code = delivery.main(
                [
                    "--root",
                    str(self.root),
                    "run",
                    self.issue,
                    "--owner",
                    "cli-pm",
                    "--max-steps",
                    "1",
                    "--",
                    sys.executable,
                    "-c",
                    script,
                ]
            )
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(output.getvalue())["state"], "building")

    def test_merge_refusal_after_base_moves_can_be_reconciled_then_revised(self):
        self.reach("merge_ready")
        operation = self.store.begin(self.issue, self.owner, self.epoch, reader=self.remote)

        def remote(contract, pr):
            return {
                **self.remote(contract, pr),
                "baseRefOid": "0" * 40,
                "mergeStateStatus": "BLOCKED",
            }

        result = self.store.reconcile(
            self.issue,
            self.owner,
            self.epoch,
            operation["id"],
            {
                "outcome": "not_applied",
                "readback_ref": "confirmed-open-pr",
                "previous_worker_stopped": True,
            },
            reader=remote,
        )
        self.assertIsNone(result["pending"])
        updated = self.store.revise(
            self.issue, self.owner, self.epoch, self.artifact, "revalidate against current base"
        )
        self.assertEqual(updated["state"], "validating")


if __name__ == "__main__":
    unittest.main()
