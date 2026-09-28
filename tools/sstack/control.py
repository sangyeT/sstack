#!/usr/bin/env python3
"""Offline verification, deliberately separate from live Kizen operations."""

import argparse
import datetime
import hashlib
import importlib.util
import json
import os
import shutil
import signal
import stat
import subprocess
import sys
import uuid
from pathlib import Path

import registry

ROOT = Path(__file__).resolve().parents[2]
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
        )
    ],
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


def check_readiness(name, cwd, command, *, root):
    """Inspect known suite contracts without importing or executing project code."""
    reasons = []
    directory = root / cwd
    if not directory.is_dir():
        reasons.append("working_directory_missing")
    if not shutil.which(command[0]):
        reasons.append("executable_missing")
    if name == "stack":
        for module in ("ruff", "yaml"):
            if importlib.util.find_spec(module) is None:
                reasons.append(f"dev_dependency_missing:{module}")
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
    }, stdout + "\n--- stderr ---\n" + stderr


def verify(suite, *, timeout=60, plan=False, root=None, base=None):
    root = ROOT if root is None else root
    selection = None
    suites = suites_for(root)
    if suite == "changed":
        if not base:
            raise ValueError("verify changed requires --base")
        selection = coverage(root, base)
        selected = selection["suites"]
    else:
        selected = suites if suite == "all" else [suite]
    checks = [check for key in selected for check in suites[key]]
    if plan:
        return {
            "status": "planned",
            "suite": suite,
            "coverage": selection,
            "checks": [
                {"name": name, "cwd": cwd, "command": command} for name, cwd, command in checks
            ],
        }
    run_id = (
        datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        + "-"
        + uuid.uuid4().hex[:8]
    )
    output = root / "artifacts" / "sstack" / run_id
    output.mkdir(parents=True)
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True
    )
    before = fingerprint(root)
    report = {
        "run_id": run_id,
        "suite": suite,
        "scope": "offline",
        "coverage": selection,
        "base_revision": registry.revision(root, base) if base else None,
        "fingerprint_policy": FINGERPRINT_POLICY,
        "excluded_inputs": excluded_inputs(root),
        "live_kizen": "not_tested",
        "ui": "not_tested",
        "git_revision": revision.stdout.strip() if revision.returncode == 0 else None,
        "source_fingerprint_before": before,
        "checks": [],
    }
    for name, cwd, command in checks:
        prerequisite = check_readiness(name, cwd, command, root=root)
        if prerequisite["status"] == "blocked":
            result = {**prerequisite, "exit_code": None}
            log = "Blocked prerequisites: " + ", ".join(prerequisite["reasons"]) + "\n"
        else:
            result, log = run_check(name, cwd, command, root=root, timeout=timeout)
        log_path = output / (name + ".log")
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
    report["report"] = str((output / "report.json").relative_to(root))
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def positive(value):
    result = int(value)
    if result <= 0:
        raise argparse.ArgumentTypeError("must be positive")
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
                else verify(args.suite, timeout=args.timeout, plan=args.plan, base=args.base)
            )
        )
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(json.dumps({"status": "blocked", "error": type(error).__name__}))
        return 1
    print(json.dumps(result, indent=2))
    return 0 if result["status"] in {"passed", "planned"} else 1


if __name__ == "__main__":
    sys.exit(main())
