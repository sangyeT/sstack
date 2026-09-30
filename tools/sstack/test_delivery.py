import contextlib
import copy
import hashlib
import io
import json
import os
import shutil
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
    LOG = "artifacts/sstack/fixture-run/check.log"  # where verify() writes a check log

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
            log = self.root / self.LOG
            log.parent.mkdir(parents=True, exist_ok=True)
            log.write_text(json.dumps({"synthetic_test": "passed"}))
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
                        "log": self.LOG,
                        "log_sha256": control.file_digest(log),
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
        (self.root / self.LOG).write_text("changed")
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

    def run_dir_suite(self):
        """Make the covered suite one check whose command writes into its run directory."""
        script = "import sys; open(sys.argv[sys.argv.index('--json') + 1], 'w').write('{}')"
        command = [sys.executable, "-c", script, "--json", control.RUN_DIR + "/evals.json"]
        suites = patch.dict(control.BUILTIN_SUITES, {"stack": [("run-dir-evals", ".", command)]})
        suites.start()
        self.addCleanup(suites.stop)
        return command

    def verified_packet(self):
        """A validating packet whose verification report comes from a real verify() run."""
        report = control.verify("changed", root=self.root, base=self.base)
        self.assertEqual(report["status"], "passed")
        path = self.root / report["report"]
        packet = self.packet("validating")
        packet["verification"] = [
            {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        ]
        return report, packet

    def refuse(self, packet, report, reason):
        packet["verification"] = [self.ref("forged.json", report)]
        with self.assertRaisesRegex(delivery.Blocked, reason):
            delivery.gate(self.store.status(self.issue), packet)

    def test_verify_report_bound_to_its_own_run_dir_passes_validation(self):
        self.run_dir_suite()
        self.reach("validating")
        report, packet = self.verified_packet()
        run_dir = (self.root / report["report"]).parent.resolve()
        self.assertEqual(report["checks"][0]["command"][-1], str(run_dir / "evals.json"))
        self.assertTrue((run_dir / "evals.json").is_file())
        operation = self.store.begin(self.issue, self.owner, self.epoch)
        result = self.store.complete(self.issue, self.owner, self.epoch, operation["id"], packet)
        self.assertEqual(result["state"], "reviewing")

    def test_run_dir_bound_to_another_run_is_not_verification(self):
        self.run_dir_suite()
        self.reach("validating")
        other, _ = self.verified_packet()
        report, packet = self.verified_packet()
        delivery.gate(self.store.status(self.issue), packet)  # the unforged report passes
        check, root = report["checks"][0], self.root.resolve()
        elsewhere = str(root.parent / "another-checkout")
        moved = [part.replace(str(root), elsewhere) for part in check["command"]]
        self.assertNotEqual(moved, check["command"])
        for label, update in (
            ("another run's command", {"command": other["checks"][0]["command"]}),
            ("another run's log", {key: other["checks"][0][key] for key in ("log", "log_sha256")}),
            ("another checkout", {"command": moved}),
            ("unbound placeholder", {"command": control.BUILTIN_SUITES["stack"][0][2]}),
        ):
            with self.subTest(label):
                forged = {**report, "checks": [{**check, **update}]}
                self.refuse(packet, forged, "verification_command_mismatch:run-dir-evals")

    def test_run_dir_command_that_differs_otherwise_is_not_verification(self):
        self.run_dir_suite()
        self.reach("validating")
        report, packet = self.verified_packet()
        check = report["checks"][0]
        command = check["command"]
        for label, update in (
            ("changed flag", {"command": [*command[:3], "--yaml", command[4]]}),
            ("extra argument", {"command": [*command, "--skip-failures"]}),
            ("changed script", {"command": [*command[:2], "pass", *command[3:]]}),
            ("other output", {"command": [*command[:4], command[4].replace("evals", "other")]}),
            ("other cwd", {"cwd": "tools"}),
        ):
            with self.subTest(label):
                forged = {**report, "checks": [{**check, **update}]}
                self.refuse(packet, forged, "verification_command_mismatch:run-dir-evals")

    def test_run_dir_report_keeps_every_other_binding(self):
        self.run_dir_suite()
        self.reach("validating")
        report, packet = self.verified_packet()
        check = report["checks"][0]
        for reason, update in (
            ("verification_head_mismatch", {"git_revision": "0" * 40}),
            ("verification_base_mismatch", {"base_revision": "0" * 40}),
            ("verification_inputs_changed", {"source_fingerprint_after": "0" * 64}),
            ("verification_exit_code_invalid", {"checks": [{**check, "exit_code": 1}]}),
            ("verification_log_changed", {"checks": [{**check, "log_sha256": "0" * 64}]}),
        ):
            with self.subTest(reason):
                self.refuse(packet, {**report, **update}, reason)

    def outside(self):
        """A directory outside the checkout, removed after the test."""
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        return Path(temp.name)

    def relogged(self, report, log):
        """The report with every check naming this log and the digest of the file it reaches."""
        digest = control.file_digest(self.root / log)
        checks = [{**check, "log": log, "log_sha256": digest} for check in report["checks"]]
        return {**report, "checks": checks}

    def assert_logs_refused(self, logs):
        """Each log path is refused even though its digest matches the file the gate reads."""
        self.reach("validating")
        packet = self.packet("validating")
        report = delivery.evidence_file(packet["verification"][0])
        delivery.gate(self.store.status(self.issue), packet)  # the unaltered report passes
        for label, log in logs.items():
            with self.subTest(label):
                self.refuse(packet, self.relogged(report, log), "verification_log_invalid")

    def test_absolute_log_is_not_verification(self):
        outside = self.outside() / "check.log"
        outside.write_text("{}")
        self.assert_logs_refused(
            {
                "the run log spelled absolutely": str(self.root / self.LOG),
                "a log outside the checkout": str(outside),
            }
        )

    def test_log_with_parent_segments_is_not_verification(self):
        outside = self.outside() / "check.log"
        outside.write_text("{}")
        (self.root / "artifacts").mkdir()
        (self.root / "artifacts/check.log").write_text("{}")
        self.assert_logs_refused(
            {
                "out of the checkout": os.path.relpath(outside, self.root),
                "out of the run artifacts": "artifacts/sstack/fixture-run/../../check.log",
                "in place of the run id": "artifacts/sstack/../check.log",
                "back into its run": "artifacts/sstack/../sstack/fixture-run/check.log",
            }
        )

    def test_log_must_be_a_file_directly_in_a_run_directory(self):
        nested = self.root / "artifacts/sstack/fixture-run/nested"
        nested.mkdir(parents=True)
        for path in (nested / "check.log", self.root / "artifacts/sstack/check.log"):
            path.write_text("{}")
        (self.root / "artifacts/check.log").write_text("{}")
        self.assert_logs_refused(
            {
                "under artifacts only": "artifacts/check.log",
                "without a run directory": "artifacts/sstack/check.log",
                "nested in a run directory": "artifacts/sstack/fixture-run/nested/check.log",
                "a tracked source file": "sample.py",
            }
        )

    def test_symlinked_log_resolving_outside_its_run_directory_is_not_verification(self):
        runs, outside = self.root / "artifacts/sstack", self.outside()
        (outside / "check.log").write_text("{}")
        (runs / "fixture-run/nested").mkdir(parents=True)
        (runs / "fixture-run/nested/check.log").write_text("{}")
        (self.root / "artifacts/elsewhere").mkdir()
        (self.root / "artifacts/elsewhere/check.log").write_text("{}")
        links = {
            "log-out/check.log": outside / "check.log",
            "log-in/check.log": self.root / "artifacts/elsewhere/check.log",
            "run-out": self.root / "artifacts/elsewhere",
            "log-other-run/check.log": runs / "fixture-run/check.log",
            "run-nested": runs / "fixture-run/nested",
        }
        for link, target in links.items():
            (runs / link).parent.mkdir(parents=True, exist_ok=True)
            (runs / link).symlink_to(target, target_is_directory=target.is_dir())
        self.assert_logs_refused(
            {
                "log linked outside the checkout": "artifacts/sstack/log-out/check.log",
                "log linked outside the run artifacts": "artifacts/sstack/log-in/check.log",
                "run directory linked outside the run artifacts": (
                    "artifacts/sstack/run-out/check.log"
                ),
                "log linked into another run": "artifacts/sstack/log-other-run/check.log",
                "run directory linked below another run": ("artifacts/sstack/run-nested/check.log"),
            }
        )

    def test_linked_run_artifacts_root_is_not_verification(self):
        """A link at artifacts/ or artifacts/sstack/ would move the root logs sit under."""
        self.reach("validating")
        delivery.gate(self.store.status(self.issue), self.packet("validating"))  # unlinked
        with (self.root / ".git/info/exclude").open("a") as exclude:
            exclude.write("/artifacts\n")  # so a linked artifacts/ is ignored like the directory
        outside = self.outside()
        (outside / "system/etc").mkdir(parents=True)
        (outside / "system/etc/hosts").write_text("{}")
        artifacts, runs = self.root / "artifacts", self.root / "artifacts/sstack"

        def link_runs_outside():
            shutil.rmtree(runs)
            runs.symlink_to(outside / "system", target_is_directory=True)
            return "artifacts/sstack/etc/hosts"

        def link_runs_to_tracked_tools():
            shutil.rmtree(runs)
            runs.symlink_to(self.root / "tools", target_is_directory=True)
            return "artifacts/sstack/sstack/projects.json"

        def move_artifacts_outside_and_link_back():
            moved = outside / "artifacts"
            shutil.move(str(artifacts), str(moved))
            artifacts.symlink_to(moved, target_is_directory=True)
            return self.LOG

        for label, arrange in (
            ("run artifacts linked outside the checkout", link_runs_outside),
            ("run artifacts linked to tracked sources", link_runs_to_tracked_tools),
            ("artifacts linked outside the checkout", move_artifacts_outside_and_link_back),
        ):
            with self.subTest(label):
                packet = self.packet("validating")
                report = delivery.evidence_file(packet["verification"][0])
                try:
                    forged = self.relogged(report, arrange())
                    self.refuse(packet, forged, "verification_log_invalid")
                finally:
                    for path in (artifacts, runs):
                        if path.is_symlink():
                            path.unlink()

    def test_hardlinked_log_is_not_verification(self):
        outside = self.outside() / "check.log"
        outside.write_text("{}")
        run = self.root / "artifacts/sstack/fixture-run"
        run.mkdir(parents=True)
        os.link(outside, run / "outside.log")
        os.link(self.root / "sample.py", run / "sample.log")
        self.assert_logs_refused(
            {
                "linked outside the checkout": "artifacts/sstack/fixture-run/outside.log",
                "linked to a tracked source": "artifacts/sstack/fixture-run/sample.log",
            }
        )

    def test_reused_report_cannot_carry_an_escaping_log_past_the_gate(self):
        """verify --reuse only keeps a log inside the checkout; the gate still confines it."""
        path = self.root / "tools/sstack/projects.json"
        document = json.loads(path.read_text())
        document["projects"][0]["paths"].append("tools/sstack/projects.json")
        document["projects"][0]["suites"] = ["reusable"]
        check = {"name": "reusable-check", "cwd": ".", "command": ["$PYTHON", "-c", "pass"]}
        document["suites"] = {"reusable": [{**check, "reuse_safe": True}]}
        path.write_text(json.dumps(document))
        self.commit()
        self.artifact.update(
            head=self.git("rev-parse", "HEAD"), fingerprint=control.fingerprint(self.root)
        )
        options = {"base": self.base, "root": self.root, "environment_key": "test"}
        report = control.verify("changed", **options)
        self.assertEqual(report["status"], "passed")
        report_path = self.root / report["report"]
        (self.root / report["checks"][0]["log"]).rename(self.root / "artifacts/moved.log")
        report["checks"][0]["log"] = "artifacts/moved.log"
        report_path.write_text(json.dumps(report, indent=2) + "\n")
        reused = control.verify("changed", reuse=report_path, **options)
        self.assertEqual(reused["reuse"]["status"], "hit")
        packet = self.packet("validating")
        packet["verification"] = [
            {"path": str(report_path), "sha256": control.file_digest(report_path)}
        ]
        task = {
            "state": "validating",
            "contract": self.contract,
            "context": {"artifact": self.artifact},
        }
        with self.assertRaisesRegex(delivery.Blocked, "verification_log_invalid"):
            delivery.gate(task, packet)

    def test_report_from_the_verify_cli_passes_validation(self):
        """Run the real control.py CLI from a copy in the checkout, so it resolves its own root."""
        command = self.run_dir_suite()
        stack = self.root / "tools/sstack"
        for name in ("control.py", "registry.py"):
            shutil.copy2(Path(control.__file__).with_name(name), stack / name)
        (self.root / ".git/info").mkdir(exist_ok=True)
        with (self.root / ".git/info/exclude").open("a") as exclude:
            exclude.write("/tools/sstack/*.py\n")  # the tool copy is not a checkout input
        self.reach("validating")
        driver = (
            "import json, os, sys\n"
            "sys.path.insert(0, sys.argv[1])\n"
            "import control\n"
            "assert control.__file__ == os.path.join(sys.argv[1], 'control.py'), control.__file__\n"
            "control.BUILTIN_SUITES['stack'] = [('run-dir-evals', '.', json.loads(sys.argv[2]))]\n"
            "sys.argv = [control.__file__, *sys.argv[3:]]\n"
            "raise SystemExit(control.main())\n"
        )
        arguments = [str(stack), json.dumps(command), "verify", "changed", "--base", self.base]
        result = subprocess.run(
            [sys.executable, "-c", driver, *arguments],
            cwd=self.root,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        report = json.loads(result.stdout)
        run_dir = self.root.resolve() / Path(report["report"]).parent
        self.assertEqual(report["checks"][0]["command"][-1], str(run_dir / "evals.json"))
        self.assertTrue((run_dir / "evals.json").is_file())
        path = self.root / report["report"]
        packet = self.packet("validating")
        packet["verification"] = [{"path": str(path), "sha256": control.file_digest(path)}]
        alias = self.outside() / "checkout"
        alias.symlink_to(self.root, target_is_directory=True)
        task = self.store.status(self.issue)
        task["contract"]["checkout"] = str(alias)
        delivery.gate(task, packet)  # the same report, with the checkout spelled through a link
        operation = self.store.begin(self.issue, self.owner, self.epoch)
        result = self.store.complete(self.issue, self.owner, self.epoch, operation["id"], packet)
        self.assertEqual(result["state"], "reviewing")

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

    def events(self, name):
        with contextlib.closing(self.store.connect()) as db:
            rows = db.execute(
                "SELECT data FROM events WHERE issue=? AND event=? ORDER BY id", (self.issue, name)
            ).fetchall()
        return [json.loads(row["data"]) for row in rows]

    def test_pr_merged_before_begin_is_adopted_and_completes_delivery(self):
        self.reach("merge_ready")
        self.merged = True  # a person merged the reviewed PR in the GitHub UI
        with self.assertRaisesRegex(delivery.Blocked, "pr_not_ready"):
            self.store.begin(self.issue, self.owner, self.epoch, reader=self.remote)
        (self.root / "after-merge.txt").write_text("the checkout is not the merge input\n")
        operation = self.store.adopt(self.issue, self.owner, self.epoch, reader=self.remote)
        self.assertEqual(
            {key: operation[key] for key in ("from", "to", "adopted")},
            {"from": "merge_ready", "to": "merged", "adopted": True},
        )
        self.assertEqual(self.store.status(self.issue)["pending"], operation)
        self.assertEqual(self.events("merge_adopted"), [{**operation, "merge_sha": "f" * 40}])
        result = self.store.complete(
            self.issue, self.owner, self.epoch, operation["id"], {}, reader=self.remote
        )
        self.assertEqual((result["state"], result["context"]["merge_sha"]), ("merged", "f" * 40))
        self.reach("done")
        with contextlib.closing(self.store.connect()) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM resources").fetchone()[0], 0)

    def test_adoption_refuses_a_merge_it_cannot_bind_to_the_reviewed_head(self):
        self.reach("merge_ready")
        self.merged = True
        for reason, update in (
            ("remote_head_changed", {"headRefOid": "0" * 40}),
            ("remote_base_branch_changed", {"baseRefName": "release"}),
            ("merge_not_confirmed", {"state": "CLOSED", "mergeCommit": None}),
            ("merge_not_confirmed", {"state": "OPEN", "mergeCommit": None}),
            ("merge_sha_missing", {"mergeCommit": None}),
        ):
            with self.subTest(update=update), self.assertRaisesRegex(delivery.Blocked, reason):
                self.store.adopt(
                    self.issue,
                    self.owner,
                    self.epoch,
                    reader=lambda c, p, update=update: {**self.remote(c, p), **update},
                )
        task = self.store.status(self.issue)
        self.assertEqual((task["state"], task["pending"]), ("merge_ready", None))
        self.assertEqual(self.events("merge_adopted"), [])

    def test_adoption_requires_merge_authorization(self):
        self.contract["allow_merge"] = False
        self.store = delivery.Store(self.outside() / "delivery.sqlite3", clock=lambda: self.now[0])
        self.store.create(self.contract)
        self.epoch = self.store.claim(self.issue, self.owner, 300)["epoch"]
        self.reach("merge_ready")
        self.merged = True
        with self.assertRaisesRegex(delivery.Blocked, "merge_not_authorized"):
            self.store.adopt(self.issue, self.owner, self.epoch, reader=self.remote)
        self.assertIsNone(self.store.status(self.issue)["pending"])

    def test_merged_pr_cannot_skip_review_through_adoption(self):
        self.reach("reviewing")
        self.merged = True
        with self.assertRaisesRegex(delivery.Blocked, "adoption_requires_merge_ready"):
            self.store.adopt(self.issue, self.owner, self.epoch, reader=self.remote)
        operation = self.store.begin(self.issue, self.owner, self.epoch, reader=self.remote)
        with self.assertRaisesRegex(delivery.Blocked, "pr_not_ready"):
            self.store.complete(
                self.issue,
                self.owner,
                self.epoch,
                operation["id"],
                self.packet("reviewing"),
                reader=self.remote,
            )
        self.assertEqual(self.store.status(self.issue)["state"], "reviewing")
        self.assertEqual(self.events("merge_adopted"), [])

    def test_adopt_cli_refuses_a_task_before_merge_ready(self):
        epoch = delivery.Store(self.store.path).claim(self.issue, "cli-pm", 300)["epoch"]
        arguments = ["--root", str(self.root), "adopt", self.issue, "--owner", "cli-pm"]
        with contextlib.redirect_stdout(io.StringIO()) as output:
            code = delivery.main([*arguments, "--epoch", str(epoch)])
        self.assertEqual(
            (code, json.loads(output.getvalue())),
            (1, {"status": "blocked", "reason": "adoption_requires_merge_ready"}),
        )
        self.assertIsNone(self.store.status(self.issue)["pending"])

    def test_open_pr_keeps_the_merge_preflight(self):
        self.reach("merge_ready")
        for reason, update in (
            ("remote_merge_gate_blocked", {"mergeStateStatus": "BLOCKED"}),
            (
                "ci_not_passed:quality",
                {"statusCheckRollup": [{"name": "quality", "state": "FAILURE"}]},
            ),
        ):
            with self.subTest(reason), self.assertRaisesRegex(delivery.Blocked, reason):
                self.store.begin(
                    self.issue,
                    self.owner,
                    self.epoch,
                    reader=lambda c, p, update=update: {**self.remote(c, p), **update},
                )
        (self.root / "sample.py").write_text("value = 2\n")
        with self.assertRaisesRegex(delivery.Blocked, "checkout_inputs_changed"):
            self.store.begin(self.issue, self.owner, self.epoch, reader=self.remote)


if __name__ == "__main__":
    unittest.main()
