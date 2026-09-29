import argparse
import importlib.util
import json
import os
import subprocess
from pathlib import Path

SOURCE = Path(__file__).resolve().parent
CONFIG_SPEC = importlib.util.spec_from_file_location(
    "sstack_config", SOURCE / "tools/sstack/config.py"
)
config = importlib.util.module_from_spec(CONFIG_SPEC)
CONFIG_SPEC.loader.exec_module(config)

SKILLS = ("sstack", "sstack-demo", "sstack-engineer", "sstack-mode", "sstack-verify")
START = "<!-- sstack:begin -->"
END = "<!-- sstack:end -->"
IGNORE_BLOCK = """# sstack generated files
/artifacts/sstack/
/tools/sstack/**/__pycache__/
/__pycache__/
/.ruff_cache/
/.venv/
# end sstack generated files
"""
BLOCK = f"""{START}
Use /sstack for PM goals. Read tools/sstack/skills/sstack/SKILL.md and resolve
project scope and the configured PM board before dispatch. Supporting skills:
sstack-engineer, sstack-mode, sstack-verify. Canonical skills: tools/sstack/skills/.
Configure a board with python tools/sstack/control.py board set URL --project-key KEY.
Run python tools/sstack/control.py board show before starting a new goal.
{END}
"""


def git(root, *args):
    return subprocess.run(
        ["git", "-C", str(root), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def safe_destination(root, relative):
    path = root / relative
    for parent in (path, *path.parents):
        if parent == root:
            break
        if parent.is_symlink():
            raise ValueError(f"Refusing symlink destination: {relative}")
        if parent != path and parent.exists() and not parent.is_dir():
            raise ValueError(f"Destination parent is not a directory: {relative}")
    return path


def instruction_content(path):
    existing = path.read_text() if path.exists() else ""
    if START in existing or END in existing:
        if existing.count(START) != 1 or existing.count(END) != 1 or BLOCK not in existing:
            raise ValueError(f"Managed instructions changed: {path.name}")
        return existing
    return (
        existing
        + ("\n\n" if existing and not existing.endswith("\n") else "\n" if existing else "")
        + BLOCK
    )


def prepare(root, source=SOURCE, board_url=None, project_key=None):
    root = Path(root).resolve()
    source = Path(source).resolve()
    if not root.is_dir() or Path(git(root, "rev-parse", "--show-toplevel")).resolve() != root:
        raise ValueError("--repo must name the root of an existing Git repository")
    if project_key and not board_url:
        raise ValueError("--project-key requires --board-url")
    configuration = config.updated_config(root, board_url, project_key) if board_url else None
    if root == source:
        return root, {}, {}, configuration
    files = {}
    paths = git(source, "ls-files", "-z", "--", "tools/sstack", "install.py").split("\0")
    for relative in paths:
        if not relative:
            continue
        if any(
            part in ("__pycache__", ".ruff_cache", "artifacts") for part in Path(relative).parts
        ) or relative.endswith(".pyc"):
            continue
        original = source / relative
        if original.is_symlink() or not original.is_file():
            raise ValueError(f"Packaged source is not a regular file: {relative}")
        destination = safe_destination(root, relative)
        data = original.read_bytes()
        if destination.exists() and (not destination.is_file() or destination.read_bytes() != data):
            raise ValueError(f"Existing file differs; resolve before install: {relative}")
        if not destination.exists():
            files[destination] = data
    if not files and not (source / "tools/sstack/control.py").is_file():
        raise ValueError("SStack package is missing")
    for name in ("AGENTS.md", "CLAUDE.md"):
        path = safe_destination(root, name)
        data = instruction_content(path).encode()
        if not path.exists() or path.read_bytes() != data:
            files[path] = data
    ignore = safe_destination(root, ".gitignore")
    existing = ignore.read_text() if ignore.exists() else ""
    if IGNORE_BLOCK not in existing:
        separator = "\n" if existing and not existing.endswith("\n") else ""
        files[ignore] = (existing + separator + IGNORE_BLOCK).encode()
    links = {}
    for host in (".agents", ".claude"):
        for skill in SKILLS:
            relative = Path(host) / "skills" / skill
            path = root / relative
            parent = safe_destination(root, relative.parent)
            if parent.exists() and not parent.is_dir():
                raise ValueError(f"Skill registration parent is not a directory: {relative.parent}")
            target = root / "tools" / "sstack" / "skills" / skill
            if not (source / "tools/sstack/skills" / skill / "SKILL.md").is_file():
                raise ValueError(f"Packaged skill missing: {skill}")
            if path.is_symlink():
                if path.resolve() != target:
                    raise ValueError(f"Existing skill link conflicts: {relative}")
            elif path.exists():
                raise ValueError(f"Existing skill registration conflicts: {relative}")
            else:
                links[path] = os.path.relpath(target, path.parent)
    return root, files, links, configuration


def install(root, source=SOURCE, board_url=None, project_key=None, plan=False):
    root, files, links, configuration = prepare(root, source, board_url, project_key)
    result = {
        "status": "planned" if plan else "installed",
        "repo": str(root),
        "files": [str(path.relative_to(root)) for path in files],
        "links": [str(path.relative_to(root)) for path in links],
        "board_updated": configuration is not None,
    }
    if not plan:
        for path, data in files.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        for path, target in links.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.symlink_to(target, target_is_directory=True)
        if configuration is not None:
            config.write_config(root, configuration)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description="Install SStack into an existing repository")
    parser.add_argument("--repo", required=True, type=Path)
    parser.add_argument("--board-url")
    parser.add_argument("--project-key")
    parser.add_argument("--plan", action="store_true")
    args = parser.parse_args(argv)
    try:
        print(
            json.dumps(
                install(
                    args.repo,
                    board_url=args.board_url,
                    project_key=args.project_key,
                    plan=args.plan,
                ),
                indent=2,
            )
        )
        return 0
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        print(json.dumps({"status": "blocked", "reason": str(error)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
