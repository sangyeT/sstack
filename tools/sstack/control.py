#!/usr/bin/env python3
"""Offline verification, deliberately separate from live Kizen operations."""

import argparse
import datetime
import hashlib
import importlib.metadata
import importlib.util
import json
import os
import shutil
import signal
import stat
import subprocess
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import registry

ROOT = Path(__file__).resolve().parents[2]
DOCS_CHECK = ("docs", ".", [sys.executable, "tools/sstack/check_contracts.py", "--include-readme"])
BUILTIN_SUITES = {
    "stack": [
        (
            "stack",
            ".",
            [
                sys.executable,
                "-m",
                "unittest",
                "discover",
                "-s",
                "tools/sstack",
                "-p",
                "test_*.py",
                "-v",
            ],
        ),
        ("stack-lint", ".", [sys.executable, "tools/sstack/lint.py", "--code-only"]),
        DOCS_CHECK,
    ],
    "docs": [DOCS_CHECK],
}
SUITES = registry.load_suites(ROOT, BUILTIN_SUITES)


def suites_for(root):
    if not (root / registry.REGISTRY_PATH).exists():
        return SUITES
    return registry.load_suites(root, BUILTIN_SUITES)


TEXT_SUFFIXES = {
    ".py",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".json",
    ".md",
    ".sh",
    ".yaml",
    ".yml",
    ".txt",
    ".html",
    ".css",
}


EXCLUDED_PARTS = {
    ".git",
    ".kizen",
    "artifacts",
    "node_modules",
    "dist",
    "__pycache__",
    ".venv",
    "venv",
    ".ruff_cache",
    ".pytest_cache",
    "credentials",
    "secrets",
}
EXCLUDED_NAMES = {".env", "credentials.json", "credentials.yaml", "credentials.yml"}
EXCLUDED_SUFFIXES = {".pem", ".key", ".p12", ".pfx", ".pyc", ".log"}
FINGERPRINT_POLICY = {
    "version": 2,
    "inputs": "git tracked plus nonignored untracked files, all extensions and sizes",
    "records": "path, type, executable mode, symlink target/content, missing marker, content SHA256",
    "excluded_parts": sorted(EXCLUDED_PARTS),
    "excluded_names": sorted(EXCLUDED_NAMES),
    "excluded_suffixes": sorted(EXCLUDED_SUFFIXES),
    "excluded_patterns": [".env.* except .env.example and .env.sample"],
    "limits": "excluded runtime/credential content and ignored untracked inputs are not attested; live environment requires separate evidence",
}


def excluded(name):
    path = Path(name)
    if any(part in EXCLUDED_PARTS for part in path.parts):
        return "runtime_or_credentials_directory"
    if (
        path.name in EXCLUDED_NAMES
        or (path.name.startswith(".env.") and path.name not in {".env.example", ".env.sample"})
        or path.suffix in EXCLUDED_SUFFIXES
    ):
        return "runtime_or_credentials_file"
    return None


def git_inputs(root):
    result = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=root,
        capture_output=True,
        check=True,
    )
    return sorted(set(os.fsdecode(result.stdout).split("\0")) - {""})


def source_files(root):
    for name in git_inputs(root):
        if not excluded(name):
            yield name, root / name


def file_digest(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def input_record(root, path):
    try:
        info = path.lstat()
    except FileNotFoundError:
        return {"type": "missing"}
    mode = stat.S_IFMT(info.st_mode) | (info.st_mode & 0o111)
    if path.is_symlink():
        target = os.readlink(path)
        try:
            resolved = path.resolve()
        except RuntimeError as error:
            raise ValueError("symlink loop: " + str(path.relative_to(root))) from error
        try:
            relative = resolved.relative_to(root.resolve())
        except ValueError as error:
            raise ValueError(
                "symlink escapes repository: " + str(path.relative_to(root))
            ) from error
        reason = excluded(str(relative))
        if reason:
            content = {"excluded": reason}
        elif resolved.is_dir():
            content = {"directory": str(relative), "content": "covered by git input records"}
        else:
            content = input_record(root, resolved)
        return {"type": "symlink", "mode": mode, "target": target, "content": content}
    if stat.S_ISREG(info.st_mode):
        return {"type": "file", "mode": mode, "sha256": file_digest(path)}
    raise ValueError("unsupported input type: " + str(path.relative_to(root)))


def fingerprint(root):
    root = root.resolve()
    digest = hashlib.sha256()
    digest.update(json.dumps(FINGERPRINT_POLICY, sort_keys=True).encode())
    for name in git_inputs(root):
        reason = excluded(name)
        record = {"excluded": reason} if reason else input_record(root, root / name)
        digest.update(json.dumps([name, record], sort_keys=True).encode() + b"\0")
    return digest.hexdigest()


def excluded_inputs(root):
    return [{"path": name, "reason": excluded(name)} for name in git_inputs(root) if excluded(name)]


def coverage(root, base):
    return {
        **registry.coverage(root, base, suites_for(root)),
        "source_fingerprint": fingerprint(root),
        "fingerprint_policy": FINGERPRINT_POLICY,
        "excluded_inputs": excluded_inputs(root),
    }


def executable_path(executable, directory):
    if os.path.dirname(executable):
        return shutil.which(str(directory / executable))
    search_path = os.pathsep.join(str(directory / part) for part in os.get_exec_path())
    return shutil.which(executable, path=search_path)


def check_readiness(name, cwd, command, *, root):
    """Inspect known suite contracts without importing or executing project code."""
    reasons = []
    directory = root / cwd
    if not directory.is_dir():
        reasons.append("working_directory_missing")
    if not executable_path(command[0], directory):
        reasons.append("executable_missing")
    if name in {"stack", "stack-lint", "docs"}:
        for module in ("ruff", "yaml"):
            if importlib.util.find_spec(module) is None:
                reasons.append(f"dev_dependency_missing:{module}")
    if name in {"stack-lint", "docs"} and not (directory / command[1]).is_file():
        reasons.append("check_script_missing")
    if command[1:4] == ["-m", "unittest", "discover"]:
        arguments = command[4:]
        tests = directory / (arguments[arguments.index("-s") + 1] if "-s" in arguments else ".")
        pattern = arguments[arguments.index("-p") + 1] if "-p" in arguments else "test*.py"
        if not tests.is_dir():
            reasons.append("test_directory_missing")
        elif not any(tests.rglob(pattern)):
            reasons.append("no_test_files")
    elif Path(command[0]).name == "npm" and len(command) == 3 and command[1] == "run":
        manifest = directory / "package.json"
        if not manifest.is_file():
            reasons.append("package_json_missing")
        else:
            try:
                package = json.loads(manifest.read_text())
                scripts = package.get("scripts", {}) if isinstance(package, dict) else {}
                script = scripts.get(command[-1]) if isinstance(scripts, dict) else None
                if not isinstance(script, str) or not script.strip():
                    reasons.append("npm_script_missing")
            except (ValueError, OSError, UnicodeError):
                reasons.append("package_json_invalid")
    return {
        "name": name,
        "cwd": cwd,
        "command": command,
        "status": "blocked" if reasons else "ready",
        "reasons": reasons,
    }


def readiness(root, suite="all"):
    suites = suites_for(root)
    return {
        key: [check_readiness(*check, root=root) for check in suites[key]]
        for key in (suites if suite == "all" else [suite])
    }


def doctor(root, suite="all"):
    conflicts = []
    for name, path in source_files(root):
        if (
            path.is_symlink()
            or not path.is_file()
            or path.suffix not in TEXT_SUFFIXES | {".toml"}
            or path.stat().st_size > 2_000_000
        ):
            continue
        for number, line in enumerate(path.read_text(errors="replace").splitlines(), 1):
            if line.startswith(("<<<<<<< ", ">>>>>>> ")):
                conflicts.append({"path": name, "line": number})
    manifest = "absent"
    if (root / "package.json").exists():
        try:
            json.loads((root / "package.json").read_text())
            manifest = "valid"
        except (ValueError, OSError) as error:
            manifest = type(error).__name__
    suites = readiness(root, suite)
    blocked = any(check["status"] == "blocked" for checks in suites.values() for check in checks)
    return {
        "status": "blocked"
        if conflicts or manifest not in {"valid", "absent"} or blocked
        else "passed",
        "suite": suite,
        "readiness": suites,
        "verification": "not_run",
        "scope": "local diagnostics only",
        "conflicts": conflicts,
        "package_json": manifest,
        "tools": {name: bool(shutil.which(name)) for name in ("git", "npm", "kizen")},
    }


def run_check(name, cwd, command, *, root, timeout):
    started = time.monotonic()
    result = {"name": name, "cwd": cwd, "command": command}
    try:
        process = subprocess.Popen(
            command,
            cwd=root / cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            errors="replace",
            start_new_session=True,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
    except OSError as error:
        return {
            **result,
            "status": "blocked",
            "exit_code": None,
            "duration_seconds": time.monotonic() - started,
        }, f"{type(error).__name__}: {error}\n"
    try:
        stdout, stderr = process.communicate(timeout=timeout)
        status = "passed" if process.returncode == 0 else "failed"
    except (subprocess.TimeoutExpired, KeyboardInterrupt) as error:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        stdout, stderr = process.communicate()
        if isinstance(error, KeyboardInterrupt):
            raise
        status = "timeout"
        stderr += f"\nTimed out after {timeout} seconds.\n"
    # Python versions differ in their exit code when discovery finds no tests.
    if (
        status in {"passed", "failed"}
        and "unittest" in command
        and "Ran 0 tests" in stdout + stderr
    ):
        status = "blocked"
        stderr += "\nNo tests discovered; this is not verification.\n"
    return {
        **result,
        "status": status,
        "exit_code": process.returncode,
        "duration_seconds": time.monotonic() - started,
    }, stdout + "\n--- stderr ---\n" + stderr


def approved_checks(root, flag):
    names = {"stack", "stack-lint", "docs"}
    path = root / registry.REGISTRY_PATH
    if path.exists():
        document = json.loads(path.read_text())
        names.update(
            check["name"]
            for checks in document.get("suites", {}).values()
            for check in checks
            if check.get(flag) is True
        )
    return names


def runtime_identity(checks, root):
    executables = sorted(
        {(".", sys.executable), *((cwd, command[0]) for _, cwd, command in checks)}
    )
    identities = []
    for cwd, executable in executables:
        located = executable_path(executable, root / cwd)
        path = Path(located).resolve() if located else None
        identities.append(
            {
                "command": executable,
                "cwd": cwd,
                "path": str(path) if path else None,
                "sha256": file_digest(path) if path and path.is_file() else None,
            }
        )
    return {
        "environment_sha256": hashlib.sha256(
            json.dumps(dict(os.environ), sort_keys=True).encode()
        ).hexdigest(),
        "python_version": sys.version,
        "executables": identities,
        "distributions": sorted(
            [distribution.metadata.get("Name", ""), distribution.version]
            for distribution in importlib.metadata.distributions()
        ),
    }


def check_contracts(checks):
    return [{"name": name, "cwd": cwd, "command": command} for name, cwd, command in checks]


def reused_report(path, *, root, expected, checks):
    try:
        report = json.loads(path.read_text())
        if not isinstance(report, dict):
            return None, "invalid_report"
        if any(report.get(key) != value for key, value in expected.items()):
            return None, "report_binding_mismatch"
        recorded = report.get("checks")
        if (
            not isinstance(recorded, list)
            or not recorded
            or any(
                not isinstance(check, dict)
                or check.get("status") != "passed"
                or check.get("exit_code") != 0
                for check in recorded
            )
        ):
            return None, "checks_not_passed"
        if [
            {key: check.get(key) for key in ("name", "cwd", "command")} for check in recorded
        ] != check_contracts(checks):
            return None, "check_contract_mismatch"
        for check in recorded:
            log = root / check["log"]
            log.resolve().relative_to(root.resolve())
            if file_digest(log) != check["log_sha256"]:
                return None, "log_digest_mismatch"
        report_path = root / report["report"]
        if report_path.resolve() != path.resolve():
            return None, "report_path_mismatch"
        return report, "exact_offline_match"
    except (OSError, ValueError, KeyError, TypeError, RuntimeError):
        return None, "invalid_or_missing_report_or_log"


def execute_checks(checks, *, root, timeout, jobs):
    def execute(check):
        started = time.monotonic()
        prerequisite = check_readiness(*check, root=root)
        if prerequisite["status"] == "blocked":
            return (
                {**prerequisite, "exit_code": None, "duration_seconds": time.monotonic() - started},
                "Blocked prerequisites: " + ", ".join(prerequisite["reasons"]) + "\n",
            )
        return run_check(*check, root=root, timeout=timeout)

    safe = approved_checks(root, "parallel_safe")
    with ThreadPoolExecutor(max_workers=jobs) as executor:
        pending = []
        for check in checks:
            if check[0] in safe:
                pending.append(executor.submit(execute, check))
            else:
                for future in pending:
                    yield future.result()
                pending = []
                yield execute(check)
        for future in pending:
            yield future.result()


def verify(
    suite, *, timeout=60, plan=False, root=None, base=None, jobs=2, reuse=None, environment_key=None
):
    started = time.monotonic()
    if not isinstance(jobs, int) or isinstance(jobs, bool) or not 1 <= jobs <= 8:
        raise ValueError("jobs must be between 1 and 8")
    if reuse is not None and (not isinstance(environment_key, str) or not environment_key.strip()):
        raise ValueError("--reuse requires a nonempty --environment-key")
    root = ROOT if root is None else Path(root)
    selection = None
    suites = suites_for(root)
    if suite == "changed":
        if not base:
            raise ValueError("verify changed requires --base")
        selection = coverage(root, base)
        selected = selection["suites"]
    else:
        selected = suites if suite == "all" else [suite]
    unique = {}
    for key in selected:
        for check in suites[key]:
            if check[0] in unique and unique[check[0]] != check:
                raise ValueError("conflicting check contracts: " + check[0])
            unique[check[0]] = check
    checks = list(unique.values())
    if plan:
        return {
            "status": "planned",
            "suite": suite,
            "coverage": selection,
            "checks": check_contracts(checks),
            "jobs": jobs,
        }
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True
    )
    before = fingerprint(root)
    identity = runtime_identity(checks, root)
    bindings = {
        "suite": suite,
        "scope": "offline",
        "coverage": selection,
        "base_revision": registry.revision(root, base) if base else None,
        "fingerprint_policy": FINGERPRINT_POLICY,
        "live_kizen": "not_tested",
        "ui": "not_tested",
        "git_revision": revision.stdout.strip() if revision.returncode == 0 else None,
        "source_fingerprint_before": before,
        "runtime_identity": identity,
        "environment_key_sha256": hashlib.sha256(environment_key.encode()).hexdigest()
        if environment_key
        else None,
    }
    reuse_result = {"status": "not_requested"}
    if reuse is not None:
        reuse_path = Path(reuse)
        if not reuse_path.is_absolute():
            reuse_path = root / reuse_path
        reusable = approved_checks(root, "reuse_safe")
        if not bindings["git_revision"] or any(check[0] not in reusable for check in checks):
            cached, reason = None, "checks_not_reuse_safe_or_head_missing"
        else:
            cached, reason = reused_report(
                reuse_path,
                root=root,
                checks=checks,
                expected={
                    **bindings,
                    "status": "passed",
                    "source_fingerprint_after": before,
                    "sources_changed_during_run": False,
                },
            )
        if cached and any(
            check_readiness(*check, root=root)["status"] != "ready" for check in checks
        ):
            cached, reason = None, "prerequisites_not_ready"
        if cached and fingerprint(root) != before:
            cached, reason = None, "sources_changed_during_reuse"
        reuse_result = {
            "status": "hit" if cached else "miss",
            "reason": reason,
            "report": str(reuse),
        }
        if cached:
            return {
                **cached,
                "reuse": {**reuse_result, "elapsed_seconds": time.monotonic() - started},
            }
    run_id = (
        datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        + "-"
        + uuid.uuid4().hex[:8]
    )
    output = root / "artifacts" / "sstack" / run_id
    output.mkdir(parents=True)
    report = {
        **bindings,
        "run_id": run_id,
        "excluded_inputs": excluded_inputs(root),
        "jobs": jobs,
        "reuse": reuse_result,
        "checks": [],
    }
    for result, log in execute_checks(checks, root=root, timeout=timeout, jobs=jobs):
        log_path = output / (result["name"] + ".log")
        log_path.write_text(log)
        result["log"] = str(log_path.relative_to(root))
        result["log_sha256"] = file_digest(log_path)
        report["checks"].append(result)
    if selection:
        report["checks"].extend(
            {"name": "external:" + item["project"], **item} for item in selection["external_checks"]
        )
        if selection["unknown_paths"]:
            report["checks"].append(
                {
                    "name": "project-coverage",
                    "status": "blocked",
                    "reasons": ["unknown_project_paths"],
                    "paths": selection["unknown_paths"],
                }
            )
    report["source_fingerprint_after"] = fingerprint(root)
    report["sources_changed_during_run"] = before != report["source_fingerprint_after"]
    statuses = {item["status"] for item in report["checks"]}
    report["status"] = (
        "failed"
        if statuses & {"failed", "timeout"}
        else "blocked"
        if not statuses or "blocked" in statuses
        else "passed"
    )
    if report["sources_changed_during_run"] and report["status"] == "passed":
        report["status"] = "blocked"
    report["elapsed_seconds"] = time.monotonic() - started
    report["report"] = str((output / "report.json").relative_to(root))
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def positive(value):
    result = int(value)
    if result <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    return result


def bounded_jobs(value):
    result = positive(value)
    if result > 8:
        raise argparse.ArgumentTypeError("must be at most 8")
    return result


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "board":
        import config

        return config.main(sys.argv[2:], root=ROOT)
    if len(sys.argv) > 1 and sys.argv[1] in {"delivery", "eval"}:
        if sys.argv[1] == "delivery":
            import delivery

            return delivery.main(sys.argv[2:])
        import evaluations

        return evaluations.main(sys.argv[2:])
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("board", help="Configure default and per-project PM boards")
    commands.add_parser("delivery", help="Persistent local ownership and delivery gates")
    commands.add_parser("eval", help="PM evaluation plans, scoring, and audited metrics")
    diagnostics = commands.add_parser("doctor")
    available = suites_for(ROOT)
    diagnostics.add_argument("suite", choices=[*available, "all"], nargs="?", default="all")
    commands.add_parser("features")
    runner = commands.add_parser("verify")
    runner.add_argument("suite", choices=[*available, "all", "changed"])
    runner.add_argument("--base")
    coverage_parser = commands.add_parser("coverage")
    coverage_parser.add_argument("--base", required=True)
    runner.add_argument("--timeout", type=positive, default=60)
    runner.add_argument("--plan", action="store_true")
    runner.add_argument("--jobs", type=bounded_jobs, default=2)
    runner.add_argument("--reuse", metavar="REPORT")
    runner.add_argument("--environment-key", metavar="TOKEN")
    args = parser.parse_args()
    if args.command == "features":
        print((ROOT / "tools/sstack/skills/sstack-verify/references/features.md").read_text())
        return 0
    try:
        result = (
            coverage(ROOT, args.base)
            if args.command == "coverage"
            else (
                doctor(ROOT, args.suite)
                if args.command == "doctor"
                else verify(
                    args.suite,
                    timeout=args.timeout,
                    plan=args.plan,
                    base=args.base,
                    jobs=args.jobs,
                    reuse=args.reuse,
                    environment_key=args.environment_key,
                )
            )
        )
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(json.dumps({"status": "blocked", "error": type(error).__name__}))
        return 1
    print(json.dumps(result, indent=2))
    return 0 if result["status"] in {"passed", "planned"} else 1


if __name__ == "__main__":
    sys.exit(main())
