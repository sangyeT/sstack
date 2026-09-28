"""Durable local delivery gates; workers supply host-specific actions and evidence."""

import argparse
import contextlib
import hashlib
import json
import os
import platform
import re
import signal
import sqlite3
import subprocess
import sys
import time
import uuid
from pathlib import Path

import evaluations

STATES = (
    "ready",
    "building",
    "validating",
    "reviewing",
    "merge_ready",
    "merged",
    "rollout_verified",
    "done",
)
NEXT = dict(zip(STATES, STATES[1:]))


class Blocked(ValueError):
    pass


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def require(condition, reason):
    if not condition:
        raise Blocked(reason)


def text(value):
    return isinstance(value, str) and bool(value.strip())


def validate_contract(contract):
    require(isinstance(contract, dict), "contract_invalid")
    for key in ("issue", "project", "repository", "base_branch", "environment", "checkout"):
        require(text(contract.get(key)), "contract_missing:" + key)
    require(re.fullmatch(r"[\w.-]+/[\w.-]+", contract["repository"]), "repository_invalid")
    require(isinstance(contract.get("allow_merge"), bool), "merge_authorization_missing")
    require(isinstance(contract.get("rollout_required"), bool), "rollout_policy_missing")
    require(Path(contract["checkout"]).is_absolute(), "checkout_must_be_absolute")
    resources = contract.get("resources")
    checks = contract.get("required_checks")
    require(
        isinstance(resources, list) and resources and all(map(text, resources)), "resources_missing"
    )
    require(len(resources) == len(set(resources)), "resources_duplicate")
    require(
        isinstance(checks, list) and checks and all(map(text, checks)), "required_checks_missing"
    )
    evaluations.validate_plan(contract.get("evaluations"))
    require(contract["evaluations"]["issue"] == contract["issue"], "evaluation_issue_mismatch")
    phases = {case["phase"] for case in contract["evaluations"]["cases"]}
    require("premerge" in phases, "premerge_acceptance_missing")
    require(("postmerge" in phases) == contract["rollout_required"], "rollout_acceptance_mismatch")


def evidence_file(reference):
    require(isinstance(reference, dict), "evidence_reference_missing")
    require(
        text(reference.get("path")) and text(reference.get("sha256")), "evidence_reference_invalid"
    )
    content = Path(reference["path"]).read_bytes()
    require(hashlib.sha256(content).hexdigest() == reference["sha256"], "evidence_digest_mismatch")
    result = json.loads(content)
    require(isinstance(result, dict), "evidence_object_required")
    return result


def github(contract, pr):
    require(isinstance(pr, int) and not isinstance(pr, bool) and pr > 0, "pr_invalid")
    result = subprocess.run(
        [
            "gh",
            "pr",
            "view",
            str(pr),
            "--repo",
            contract["repository"],
            "--json",
            "headRefOid,baseRefOid,baseRefName,state,isDraft,mergeStateStatus,statusCheckRollup,mergeCommit,autoMergeRequest,url",
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    value = json.loads(result.stdout)
    require(isinstance(value, dict), "github_response_invalid")
    return value


def check_remote(contract, artifact, *, merged=False, reader=github):
    remote = reader(contract, artifact["pr"])
    require(remote.get("headRefOid") == artifact["head"], "remote_head_changed")
    require(remote.get("baseRefName") == contract["base_branch"], "remote_base_branch_changed")
    if merged:
        require(remote.get("state") == "MERGED", "merge_not_confirmed")
        require(text((remote.get("mergeCommit") or {}).get("oid")), "merge_sha_missing")
        return remote
    require(remote.get("baseRefOid") == artifact["base"], "remote_base_changed")
    require(remote.get("state") == "OPEN" and remote.get("isDraft") is False, "pr_not_ready")
    require(remote.get("mergeStateStatus") == "CLEAN", "remote_merge_gate_blocked")
    checks = remote.get("statusCheckRollup")
    require(isinstance(checks, list), "ci_missing")
    for name in contract["required_checks"]:
        matches = [c for c in checks if c.get("name", c.get("context")) == name]
        require(bool(matches), "ci_missing:" + name)
        require(
            all(c.get("conclusion", c.get("state")) == "SUCCESS" for c in matches),
            "ci_not_passed:" + name,
        )
    return remote


def validate_artifact(value):
    require(isinstance(value, dict), "artifact_missing")
    for key in ("head", "base"):
        require(
            isinstance(value.get(key), str) and re.fullmatch(r"[0-9a-f]{40,64}", value[key]),
            "artifact_invalid:" + key,
        )
    require(
        isinstance(value.get("fingerprint"), str)
        and re.fullmatch(r"[0-9a-f]{64}", value["fingerprint"]),
        "artifact_fingerprint_invalid",
    )
    require(type(value.get("pr")) is int and value["pr"] > 0, "artifact_pr_invalid")


def check_sources(contract, artifact):
    import control

    root = Path(contract["checkout"])
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=True
    )
    require(result.stdout.strip() == artifact["head"], "checkout_head_changed")
    require(control.fingerprint(root) == artifact["fingerprint"], "checkout_inputs_changed")
    dirty = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    )
    require(not dirty.stdout.strip(), "checkout_not_committed")


def gate(task, packet, *, reader=github):
    require(isinstance(packet, dict), "packet_invalid")
    contract, context, state = task["contract"], dict(task["context"]), task["state"]
    if state == "ready":
        require(
            packet.get("plan_digest") == evaluations.plan_digest(contract["evaluations"]),
            "plan_not_acknowledged",
        )
    elif state == "building":
        artifact = packet.get("artifact")
        validate_artifact(artifact)
        check_sources(contract, artifact)
        context = {"artifact": artifact}
    elif state == "validating":
        artifact = context["artifact"]
        check_sources(contract, artifact)
        require(packet.get("artifact") == artifact, "artifact_changed")
        coverage = evidence_file(packet.get("coverage"))
        require(coverage.get("status") == "passed", "coverage_not_passed")
        require(
            coverage.get("head") == artifact["head"] and coverage.get("base") == artifact["base"],
            "coverage_revision_mismatch",
        )
        require(
            coverage.get("source_fingerprint") == artifact["fingerprint"],
            "coverage_fingerprint_mismatch",
        )
        require(contract["project"] in coverage.get("projects", []), "project_not_covered")
        require(coverage.get("unknown_paths") == [], "unknown_coverage")
        import control

        current_coverage = control.coverage(Path(contract["checkout"]), artifact["base"])
        require(coverage == current_coverage, "coverage_changed_or_incomplete")
        references = packet.get("verification")
        suites = control.suites_for(Path(contract["checkout"]))
        required = {check[0]: check for suite in coverage["suites"] for check in suites[suite]}
        require(
            isinstance(references, list) and (references or not required),
            "verification_reports_missing",
        )
        proven = set()
        reports = []
        for reference in references:
            report = evidence_file(reference)
            require(report.get("git_revision") == artifact["head"], "verification_head_mismatch")
            require(report.get("base_revision") == artifact["base"], "verification_base_mismatch")
            require(
                report.get("source_fingerprint_before") == artifact["fingerprint"]
                and report.get("source_fingerprint_after") == artifact["fingerprint"],
                "verification_inputs_changed",
            )
            require(
                report.get("sources_changed_during_run") is False, "verification_mutated_sources"
            )
            require(
                isinstance(report.get("checks"), list) and report["checks"],
                "verification_checks_missing",
            )
            for check in report["checks"]:
                require(isinstance(check, dict), "verification_check_invalid")
                name = check.get("name")
                if name in required:
                    _, cwd, command = required[name]
                    require(check.get("status") == "passed", "required_check_not_passed:" + name)
                    require(
                        check.get("cwd") == cwd and check.get("command") == command,
                        "verification_command_mismatch:" + name,
                    )
                    require(check.get("exit_code") == 0, "verification_exit_code_invalid")
                    require(text(check.get("log")), "verification_log_missing")
                    log = Path(contract["checkout"]) / check["log"]
                    require(
                        hashlib.sha256(log.read_bytes()).hexdigest() == check.get("log_sha256"),
                        "verification_log_changed",
                    )
                    require(name not in proven, "duplicate_verification_check:" + name)
                    proven.add(name)
            reports.append(report)
        require(
            set(required) <= proven,
            "required_offline_checks_missing:" + ",".join(sorted(set(required) - proven)),
        )
        result = evidence_file(packet.get("evaluation"))
        verdict = evaluations.evaluate(
            contract["evaluations"],
            result,
            head=artifact["head"],
            base=artifact["base"],
            fingerprint=artifact["fingerprint"],
            phase="premerge",
        )
        require(
            verdict["status"] == "passed", "premerge_evaluation_not_passed:" + canonical(verdict)
        )
        routes = {case["route"] for case in contract["evaluations"]["cases"]}
        for check in coverage.get("external_checks", []):
            require(check.get("recipe") in routes, "external_acceptance_route_missing")
        context.update(coverage=coverage, evaluation=result, verification=reports)
    elif state == "reviewing":
        artifact = context["artifact"]
        check_sources(contract, artifact)
        review = evidence_file(packet.get("review"))
        require(review.get("artifact") == artifact, "review_stale")
        require(
            review.get("plan_digest") == evaluations.plan_digest(contract["evaluations"]),
            "review_plan_stale",
        )
        require(
            text(review.get("reviewer"))
            and review["reviewer"] != contract["evaluations"]["implementer"],
            "review_not_independent",
        )
        require(
            review.get("decision") == "approved" and review.get("blocking_findings") == [],
            "review_not_approved",
        )
        check_remote(contract, artifact, reader=reader)
        context["review"] = review
    elif state == "merge_ready":
        require(contract["allow_merge"], "merge_not_authorized")
        remote = check_remote(contract, context["artifact"], merged=True, reader=reader)
        context["merge_sha"] = remote["mergeCommit"]["oid"]
    elif state == "merged":
        artifact = context["artifact"]
        require(packet.get("merge_sha") == context["merge_sha"], "rollout_merge_mismatch")
        require(
            packet.get("environment") == contract["environment"], "rollout_environment_mismatch"
        )
        if contract["rollout_required"]:
            rollout = evidence_file(packet.get("rollout"))
            require(
                rollout.get("merge_sha") == context["merge_sha"]
                and rollout.get("environment") == contract["environment"],
                "rollout_observation_binding_mismatch",
            )
            require(
                text(rollout.get("deployment_ref"))
                and isinstance(rollout.get("execution_refs"), list)
                and rollout["execution_refs"]
                and all(map(text, rollout["execution_refs"])),
                "deployment_execution_identity_missing",
            )
            result = rollout.get("result")
            verdict = evaluations.evaluate(
                contract["evaluations"],
                result,
                head=artifact["head"],
                base=artifact["base"],
                fingerprint=artifact["fingerprint"],
                phase="postmerge",
            )
            require(
                verdict["status"] == "passed", "rollout_evaluation_not_passed:" + canonical(verdict)
            )
            context["rollout"] = rollout
        else:
            require(text(packet.get("not_required_reason")), "rollout_not_required_reason_missing")
            context["rollout"] = {"not_required_reason": packet["not_required_reason"]}
    elif state == "rollout_verified":
        closure = evidence_file(packet.get("closure"))
        require(
            closure.get("issue") == contract["issue"]
            and closure.get("merge_sha") == context["merge_sha"],
            "closure_mismatch",
        )
        require(
            closure.get("status") == "done" and text(closure.get("readback_ref")),
            "jira_completion_not_confirmed",
        )
        context["closure"] = closure
    else:
        raise Blocked("task_already_done")
    return context


class Store:
    def __init__(self, path, *, clock=time.time):
        self.path, self.clock = Path(path), clock
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with contextlib.closing(self.connect()) as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS tasks (
                    issue TEXT PRIMARY KEY, contract TEXT NOT NULL, state TEXT NOT NULL,
                    context TEXT NOT NULL, owner TEXT, epoch INTEGER NOT NULL DEFAULT 0,
                    lease REAL NOT NULL DEFAULT 0, pending TEXT, error TEXT, host TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS resources (name TEXT PRIMARY KEY, issue TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY, issue TEXT NOT NULL, at REAL NOT NULL,
                    event TEXT NOT NULL, data TEXT NOT NULL);
            """)

    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        return db

    @contextlib.contextmanager
    def transaction(self):
        db = self.connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        finally:
            if db.in_transaction:
                db.rollback()
            db.close()

    def event(self, db, issue, event, data):
        db.execute(
            "INSERT INTO events(issue,at,event,data) VALUES(?,?,?,?)",
            (issue, self.clock(), event, canonical(data)),
        )

    def load(self, db, issue):
        row = db.execute("SELECT * FROM tasks WHERE issue=?", (issue,)).fetchone()
        require(row is not None, "issue_unknown")
        task = dict(row)
        for key in ("contract", "context", "pending"):
            task[key] = json.loads(task[key]) if task[key] else None
        require(task["host"] == platform.node(), "different_host_requires_coordinator_migration")
        return task

    def create(self, contract):
        validate_contract(contract)
        with self.transaction() as db:
            require(
                not db.execute(
                    "SELECT 1 FROM tasks WHERE issue=?", (contract["issue"],)
                ).fetchone(),
                "issue_exists",
            )
            db.execute(
                "INSERT INTO tasks(issue,contract,state,context,host) VALUES(?,?,?,?,?)",
                (contract["issue"], canonical(contract), "ready", "{}", platform.node()),
            )
            self.event(
                db,
                contract["issue"],
                "created",
                {"plan_digest": evaluations.plan_digest(contract["evaluations"])},
            )
        return self.status(contract["issue"])

    def status(self, issue):
        with contextlib.closing(self.connect()) as db:
            task = self.load(db, issue)
        task["next_action"] = (
            "reconcile"
            if task["pending"]
            else "fix_or_unblock"
            if task["error"]
            else NEXT.get(task["state"], "complete")
        )
        task["lease_active"] = task["lease"] > self.clock()
        return task

    def owned(self, db, issue, owner, epoch):
        task = self.load(db, issue)
        require(
            task["owner"] == owner and task["epoch"] == epoch and task["lease"] > self.clock(),
            "ownership_lost",
        )
        return task

    def claim(self, issue, owner, ttl):
        require(text(owner) and type(ttl) is int and 1 <= ttl <= 3600, "claim_invalid")
        with self.transaction() as db:
            task = self.load(db, issue)
            require(task["state"] != "done", "task_already_done")
            require(task["lease"] <= self.clock(), "already_claimed_use_renew")
            for resource in task["contract"]["resources"]:
                claim = db.execute(
                    "SELECT issue FROM resources WHERE name=?", (resource,)
                ).fetchone()
                require(claim is None or claim["issue"] == issue, "resource_busy:" + resource)
                db.execute(
                    "INSERT OR IGNORE INTO resources(name,issue) VALUES(?,?)", (resource, issue)
                )
            db.execute(
                "UPDATE tasks SET owner=?,epoch=epoch+1,lease=? WHERE issue=?",
                (owner, self.clock() + ttl, issue),
            )
            self.event(db, issue, "claimed", {"owner": owner, "epoch": task["epoch"] + 1})
        return self.status(issue)

    def renew(self, issue, owner, epoch, ttl):
        require(type(ttl) is int and 1 <= ttl <= 3600, "lease_invalid")
        with self.transaction() as db:
            self.owned(db, issue, owner, epoch)
            db.execute("UPDATE tasks SET lease=? WHERE issue=?", (self.clock() + ttl, issue))
        return self.status(issue)

    def begin(self, issue, owner, epoch, *, reader=github):
        with self.transaction() as db:
            task = self.owned(db, issue, owner, epoch)
            require(not task["pending"], "uncertain_operation_reconcile_first")
            require(not task["error"], "blocked_repair_first")
            require(task["state"] in NEXT, "task_already_done")
            if task["state"] == "merge_ready":
                require(task["contract"]["allow_merge"], "merge_not_authorized")
                check_sources(task["contract"], task["context"]["artifact"])
                check_remote(task["contract"], task["context"]["artifact"], reader=reader)
            operation = {
                "id": str(uuid.uuid4()),
                "from": task["state"],
                "to": NEXT[task["state"]],
                "epoch": epoch,
            }
            db.execute("UPDATE tasks SET pending=? WHERE issue=?", (canonical(operation), issue))
            self.event(db, issue, "operation_started", operation)
        return operation

    def complete(self, issue, owner, epoch, operation_id, packet, *, reader=github):
        with self.transaction() as db:
            task = self.owned(db, issue, owner, epoch)
            require(task["pending"] and task["pending"]["id"] == operation_id, "operation_mismatch")
            context = gate(task, packet, reader=reader)
            require(task["lease"] > self.clock(), "ownership_expired_during_validation")
            target = NEXT[task["state"]]
            db.execute(
                "UPDATE tasks SET state=?,context=?,pending=NULL,error=NULL WHERE issue=?",
                (target, canonical(context), issue),
            )
            self.event(db, issue, "advanced", {"state": target, "operation": operation_id})
            if target == "done":
                db.execute("DELETE FROM resources WHERE issue=?", (issue,))
        return self.status(issue)

    def record_error(self, issue, owner, epoch, reason):
        with self.transaction() as db:
            self.owned(db, issue, owner, epoch)
            db.execute("UPDATE tasks SET error=? WHERE issue=?", (reason, issue))
            self.event(db, issue, "blocked", {"reason": reason})

    def reconcile(self, issue, owner, epoch, operation_id, observation, *, reader=github):
        require(isinstance(observation, dict), "reconciliation_invalid")
        if observation.get("outcome") == "completed":
            return self.complete(
                issue, owner, epoch, operation_id, observation.get("packet"), reader=reader
            )
        require(
            observation.get("outcome") == "not_applied" and text(observation.get("readback_ref")),
            "reconciliation_requires_observation",
        )
        require(observation.get("previous_worker_stopped") is True, "previous_worker_must_stop")
        with self.transaction() as db:
            task = self.owned(db, issue, owner, epoch)
            require(task["pending"] and task["pending"]["id"] == operation_id, "operation_mismatch")
            if task["state"] == "merge_ready":
                remote = reader(task["contract"], task["context"]["artifact"]["pr"])
                require(
                    remote.get("state") in {"OPEN", "CLOSED"} and not remote.get("mergeCommit"),
                    "merge_outcome_still_uncertain",
                )
                require(
                    "autoMergeRequest" in remote and remote["autoMergeRequest"] is None,
                    "queued_merge_must_be_resolved",
                )
            db.execute("UPDATE tasks SET pending=NULL,error=NULL WHERE issue=?", (issue,))
            self.event(db, issue, "reconciled_not_applied", observation)
        return self.status(issue)

    def revise(self, issue, owner, epoch, artifact, reason):
        validate_artifact(artifact)
        require(text(reason), "revision_reason_missing")
        with self.transaction() as db:
            task = self.owned(db, issue, owner, epoch)
            require(not task["pending"], "reconcile_before_revision")
            require(
                task["state"] in {"validating", "reviewing", "merge_ready"}, "revision_not_allowed"
            )
            db.execute(
                "UPDATE tasks SET state='validating',context=?,error=NULL WHERE issue=?",
                (canonical({"artifact": artifact}), issue),
            )
            self.event(db, issue, "evidence_invalidated", {"reason": reason, "artifact": artifact})
        return self.status(issue)

    def amend(self, issue, owner, epoch, plan, reason):
        evaluations.validate_plan(plan)
        require(text(reason), "amendment_reason_missing")
        with self.transaction() as db:
            task = self.owned(db, issue, owner, epoch)
            require(not task["pending"], "reconcile_before_amendment")
            require(task["state"] in STATES[:5], "amendment_after_merge_forbidden")
            contract = {**task["contract"], "evaluations": plan}
            validate_contract(contract)
            require(
                plan["author"] == task["contract"]["evaluations"]["author"], "pm_author_changed"
            )
            db.execute(
                "UPDATE tasks SET contract=?,state='ready',context='{}',error=NULL WHERE issue=?",
                (canonical(contract), issue),
            )
            self.event(
                db,
                issue,
                "plan_amended_evidence_invalidated",
                {"reason": reason, "plan_digest": evaluations.plan_digest(plan)},
            )
        return self.status(issue)


def default_database(root):
    result = subprocess.run(
        ["git", "rev-parse", "--git-common-dir"],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    )
    directory = Path(result.stdout.strip())
    if not directory.is_absolute():
        directory = root / directory
    return directory.resolve() / "sstack" / "delivery.sqlite3"


def run_worker(store, issue, owner, epoch, worker, *, timeout=120, max_steps=8, reader=github):
    require(worker and all(map(text, worker)), "worker_command_missing")
    require(1 <= timeout <= 600 and 1 <= max_steps <= 32, "worker_budget_invalid")
    for _ in range(max_steps):
        task = store.status(issue)
        if task["state"] == "done" or task["pending"] or task["error"]:
            return task
        store.renew(issue, owner, epoch, min(3600, timeout + 180))
        operation = store.begin(issue, owner, epoch, reader=reader)
        try:
            with subprocess.Popen(
                worker,
                cwd=task["contract"]["checkout"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                start_new_session=True,
            ) as process:
                try:
                    stdout, _ = process.communicate(
                        canonical({"task": task, "operation": operation}), timeout=timeout
                    )
                except (subprocess.TimeoutExpired, KeyboardInterrupt):
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    process.communicate()
                    raise
                require(process.returncode == 0, "worker_failed")
            packet = json.loads(stdout)
            require(isinstance(packet, dict), "worker_packet_invalid")
            require(packet.get("operation_id") == operation["id"], "worker_operation_mismatch")
            store.complete(
                issue, owner, epoch, operation["id"], packet.get("evidence"), reader=reader
            )
        except (OSError, subprocess.SubprocessError, ValueError) as error:
            store.record_error(
                issue,
                owner,
                epoch,
                str(error) if isinstance(error, Blocked) else type(error).__name__,
            )
            return store.status(issue)
    return store.status(issue)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    worker = []
    if "--" in argv:
        separator = argv.index("--")
        argv, worker = argv[:separator], argv[separator + 1 :]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("init")
    create.add_argument("contract", type=Path)
    for name in (
        "status",
        "resume",
        "claim",
        "renew",
        "begin",
        "complete",
        "reconcile",
        "revise",
        "amend",
        "run",
    ):
        command = sub.add_parser(name)
        command.add_argument("issue")
        if name not in {"status", "resume"}:
            command.add_argument("--owner", required=True)
        if name not in {"status", "resume", "claim"}:
            command.add_argument("--epoch", required=name != "run", type=int)
        if name in {"claim", "renew"}:
            command.add_argument("--ttl", type=int, default=300)
        if name in {"complete", "reconcile"}:
            command.add_argument("--operation", required=True)
        if name in {"complete", "reconcile", "revise", "amend"}:
            command.add_argument("--packet", type=Path, required=True)
        if name == "run":
            command.add_argument("--timeout", type=int, default=120)
            command.add_argument("--max-steps", type=int, default=8)
    args = parser.parse_args(argv)
    try:
        store = Store(default_database(args.root))
        if args.command == "init":
            result = store.create(json.loads(args.contract.read_text()))
        elif args.command in {"status", "resume"}:
            result = store.status(args.issue)
        elif args.command == "claim":
            result = store.claim(args.issue, args.owner, args.ttl)
        elif args.command == "renew":
            result = store.renew(args.issue, args.owner, args.epoch, args.ttl)
        elif args.command == "begin":
            result = store.begin(args.issue, args.owner, args.epoch)
        elif args.command == "run":
            require(worker and all(map(text, worker)), "worker_command_missing")
            if args.epoch is None:
                task = store.claim(args.issue, args.owner, min(3600, args.timeout + 180))
                args.epoch = task["epoch"]
            result = run_worker(
                store,
                args.issue,
                args.owner,
                args.epoch,
                worker,
                timeout=args.timeout,
                max_steps=args.max_steps,
            )
        else:
            packet = json.loads(args.packet.read_text())
            if args.command == "revise":
                result = store.revise(
                    args.issue, args.owner, args.epoch, packet.get("artifact"), packet.get("reason")
                )
            elif args.command == "amend":
                result = store.amend(
                    args.issue, args.owner, args.epoch, packet.get("plan"), packet.get("reason")
                )
            else:
                result = getattr(store, args.command)(
                    args.issue, args.owner, args.epoch, args.operation, packet
                )
    except (OSError, ValueError, sqlite3.Error, subprocess.SubprocessError) as error:
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "reason": str(error) if isinstance(error, Blocked) else type(error).__name__,
                }
            )
        )
        return 1
    print(json.dumps(result, indent=2))
    return int(
        bool(result.get("error")) or (args.command == "run" and result.get("state") != "done")
    )


if __name__ == "__main__":
    sys.exit(main())
