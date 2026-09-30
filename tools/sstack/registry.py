"""Explicit project coverage for changes in this monorepo."""

import json
import re
import subprocess
import sys
from pathlib import PurePosixPath

REGISTRY_PATH = "tools/sstack/projects.json"


def load_suites(root, builtin):
    path = root / REGISTRY_PATH
    if not path.exists():
        return dict(builtin)
    document = json.loads(path.read_text())
    if not isinstance(document, dict) or document.get("version") != 1:
        raise ValueError("unsupported project registry version")
    configured = document.get("suites", {})
    if not isinstance(configured, dict):
        raise ValueError("suites must be a mapping")
    result = dict(builtin)
    names = {check[0] for checks in builtin.values() for check in checks}
    for suite, checks in configured.items():
        if not re.fullmatch(r"[a-zA-Z0-9_-]+", suite) or suite in {*builtin, "all", "changed"}:
            raise ValueError("invalid or reserved suite name")
        if not isinstance(checks, list) or not checks:
            raise ValueError("suite must contain checks")
        result[suite] = []
        for check in checks:
            required = {"name", "cwd", "command"}
            flags = {"parallel_safe", "reuse_safe"}
            optional = flags | {"min_python", "requires"}
            if (
                not isinstance(check, dict)
                or not required <= set(check)
                or set(check) - required - optional
            ):
                raise ValueError("check requires name, cwd and command")
            for flag in flags:
                if flag in check and not isinstance(check[flag], bool):
                    raise ValueError(f"{flag} must be a boolean")
            name, cwd, command = check["name"], check["cwd"], check["command"]
            if (
                not isinstance(name, str)
                or not re.fullmatch(r"[a-zA-Z0-9_-]+", name)
                or name in names
            ):
                raise ValueError("invalid or duplicate check name")
            names.add(name)
            if (
                not isinstance(cwd, str)
                or not cwd
                or PurePosixPath(cwd).is_absolute()
                or ".." in PurePosixPath(cwd).parts
            ):
                raise ValueError("unsafe check working directory")
            try:
                (root / cwd).resolve().relative_to(root.resolve())
            except ValueError as error:
                raise ValueError("check working directory escapes repository") from error
            if (
                not isinstance(command, list)
                or not command
                or not all(isinstance(arg, str) and arg and "\0" not in arg for arg in command)
            ):
                raise ValueError("command must be a nonempty argument list")
            if "min_python" in check and not (
                isinstance(check["min_python"], str)
                and re.fullmatch(r"[0-9]+\.[0-9]+", check["min_python"])
            ):
                raise ValueError("min_python must be a MAJOR.MINOR string")
            if "requires" in check:
                requires = check["requires"]
                if not isinstance(requires, list) or not requires:
                    raise ValueError("requires must be a nonempty list of paths")
                for entry in requires:
                    if (
                        not isinstance(entry, str)
                        or not entry
                        or "\0" in entry
                        or PurePosixPath(entry).is_absolute()
                        or ".." in PurePosixPath(entry).parts
                    ):
                        raise ValueError("unsafe required path")
                    try:
                        (root / cwd / entry).resolve().relative_to(root.resolve())
                    except ValueError as error:
                        raise ValueError("required path escapes repository") from error
            command = [sys.executable if arg == "$PYTHON" else arg for arg in command]
            if command[1:4] == ["-m", "unittest", "discover"]:
                for flag in ("-s", "-p"):
                    if flag in command and command.index(flag) == len(command) - 1:
                        raise ValueError("missing unittest discovery argument")
            result[suite].append((name, cwd, command))
    return result


def git(root, *args):
    result = subprocess.run(["git", *args], cwd=root, capture_output=True, check=True)
    return result.stdout


def revision(root, ref):
    return (
        git(root, "rev-parse", "--verify", "--end-of-options", ref + "^{commit}").decode().strip()
    )


def changed_files(root, base):
    commands = [
        ("diff", "--name-only", "-z", "--no-renames", base, "HEAD", "--"),
        ("diff", "--name-only", "-z", "--no-renames", "--cached", "--"),
        ("diff", "--name-only", "-z", "--no-renames", "--"),
        ("ls-files", "-z", "--others", "--exclude-standard"),
    ]
    return sorted(
        {
            name
            for args in commands
            for name in git(root, *args).decode("utf-8", "surrogateescape").split("\0")
            if name
        }
    )


def load(root, suites):
    document = json.loads((root / REGISTRY_PATH).read_text())
    if not isinstance(document, dict) or document.get("version") != 1:
        raise ValueError("unsupported project registry version")
    projects = document.get("projects")
    if not isinstance(projects, list) or not projects:
        raise ValueError("project registry must contain projects")
    names = set()
    for project in projects:
        if not isinstance(project, dict) or not isinstance(project.get("id"), str):
            raise ValueError("invalid project entry")
        name = project["id"]
        if not name or name in names:
            raise ValueError("duplicate or empty project id")
        names.add(name)
        for key in ("paths", "suites", "external", "affects"):
            if not isinstance(project.get(key), list) or not all(
                isinstance(item, str) and item for item in project[key]
            ):
                raise ValueError(f"invalid {key} for {name}")
        if not project["paths"] or not (project["suites"] or project["external"]):
            raise ValueError(f"missing coverage contract for {name}")
        if set(project["suites"]) - set(suites):
            raise ValueError(f"unknown suite for {name}")
        excludes = project.get("exclude_paths", [])
        if not isinstance(excludes, list) or not all(
            isinstance(path, str) and path for path in excludes
        ):
            raise ValueError(f"invalid exclude_paths for {name}")
        for path in [*project["paths"], *excludes]:
            if (
                PurePosixPath(path).is_absolute()
                or ".." in PurePosixPath(path).parts
                or path == "."
            ):
                raise ValueError(f"unsafe ownership path for {name}")
        for recipe in project["external"]:
            if PurePosixPath(recipe).is_absolute() or ".." in PurePosixPath(recipe).parts:
                raise ValueError(f"unsafe external recipe for {name}")
            if not (root / recipe).is_file():
                raise ValueError(f"missing external recipe for {name}: {recipe}")
    for project in projects:
        if set(project["affects"]) - names:
            raise ValueError(f"unknown affected project for {project['id']}")
    return projects


def matches(path, patterns):
    return any(
        path.startswith(pattern) if pattern.endswith("/") else path == pattern
        for pattern in patterns
    )


def coverage(root, base, suites):
    base_sha = revision(root, base)
    head = revision(root, "HEAD")
    projects = load(root, suites)
    paths = changed_files(root, base_sha)
    owners = {}
    for path in paths:
        owners[path] = sorted(
            project["id"]
            for project in projects
            if matches(path, project["paths"])
            and not matches(path, project.get("exclude_paths", []))
        )
    selected = {name for names in owners.values() for name in names}
    while True:
        expanded = selected | {
            name for project in projects if project["id"] in selected for name in project["affects"]
        }
        if expanded == selected:
            break
        selected = expanded
    chosen = [project for project in projects if project["id"] in selected]
    unknown = [path for path, names in owners.items() if not names]
    external = [
        {
            "project": project["id"],
            "recipe": recipe,
            "status": "blocked",
            "reason": "external_acceptance_not_run",
        }
        for project in chosen
        for recipe in project["external"]
    ]
    return {
        "status": "blocked" if unknown else "passed",
        "head": head,
        "base": base_sha,
        "files": owners,
        "unknown_paths": unknown,
        "projects": sorted(selected),
        "suites": sorted({suite for project in chosen for suite in project["suites"]}),
        "external_checks": external,
        "scope": "coverage selection only; checks not run",
    }
