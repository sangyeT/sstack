#!/usr/bin/env python3
"""Read-only checks for the portable SStack documentation contract."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote

import yaml

ROOT = Path(__file__).resolve().parents[2]
SKILLS = ("sstack", "sstack-engineer", "sstack-mode", "sstack-verify")
STACK = Path("tools/sstack")
FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
# Inline destinations, including angle brackets, an optional title and one
# nested pair of parentheses. Reference-style links are outside this contract.
LINK = re.compile(
    r"\[[^\]\n]*\]\(\s*(?:<(?P<angle>[^>\n]*)>|"
    r"(?P<plain>(?:\\.|[^\s()\\]|\((?:\\.|[^()\\])*\))*))"
    r"(?:\s+(?:\"[^\"\n]*\"|'[^'\n]*'|\([^()\n]*\)))?\s*\)"
)


@dataclass(frozen=True)
class Finding:
    """A diagnostic that does not include source contents."""

    path: str
    line: int
    code: str
    message: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}: {self.code} {self.message}"


class UniqueKeyLoader(yaml.SafeLoader):
    """Reject accidental duplicate keys rather than accepting the final value."""


def unique_mapping(loader, node, deep=False):
    seen = set()
    for key_node, _ in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            duplicate = key in seen
            seen.add(key)
        except TypeError as exc:
            raise yaml.constructor.ConstructorError(
                None, None, "mapping key is not scalar", key_node.start_mark
            ) from exc
        if duplicate:
            raise yaml.constructor.ConstructorError(
                None, None, "duplicate mapping key", key_node.start_mark
            )
    return yaml.SafeLoader.construct_mapping(loader, node, deep=deep)


UniqueKeyLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, unique_mapping)


def check_frontmatter(path: str, content: str, expected_name: str) -> list[Finding]:
    lines = content.splitlines()
    if not lines or lines[0] != "---":
        return [Finding(path, 1, "SKILL001", "Add YAML frontmatter starting with ---.")]
    end = next((i for i in range(1, len(lines)) if lines[i] == "---"), None)
    if end is None:
        return [Finding(path, 1, "SKILL001", "Close YAML frontmatter with ---.")]
    try:
        data = yaml.load("\n".join(lines[1:end]), Loader=UniqueKeyLoader)
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        line = mark.line + 2 if mark is not None else 1
        return [Finding(path, line, "SKILL002", "Fix invalid YAML or duplicate keys.")]
    if not isinstance(data, dict):
        return [Finding(path, 1, "SKILL002", "Frontmatter must be a YAML mapping.")]
    findings = []
    if data.get("name") != expected_name:
        findings.append(
            Finding(path, 1, "SKILL003", "Set name to the canonical skill folder name.")
        )
    if not isinstance(data.get("description"), str) or not data["description"].strip():
        findings.append(Finding(path, 1, "SKILL004", "Provide a nonempty string description."))
    return findings


def check_markdown(root: Path, relative: Path, content: str) -> list[Finding]:
    findings = []
    path = relative.as_posix()
    lines = content.splitlines()
    if content and not content.endswith("\n"):
        findings.append(Finding(path, len(lines), "TEXT001", "Add a final newline."))
    fence = None
    for number, line in enumerate(lines, 1):
        if line.rstrip(" \t") != line:
            findings.append(Finding(path, number, "TEXT002", "Remove trailing whitespace."))
        if re.match(r"^(?:<{7}|>{7}|\|{7})(?:\s|$)|^={7}$", line):
            findings.append(Finding(path, number, "TEXT003", "Resolve merge conflict marker."))
        match = FENCE.match(line)
        if match:
            marker = match.group(1)
            if fence is None:
                fence = marker
            elif marker[0] == fence[0] and len(marker) >= len(fence):
                fence = None
            continue
        if fence is not None:
            continue
        # Examples written as inline code are not navigable Markdown links.
        visible = re.sub(r"(`+).*?\1", "", line)
        for match in LINK.finditer(visible):
            target = match.group("angle")
            if target is None:
                target = match.group("plain")
            if not target or target.startswith(("#", "//")):
                continue
            if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", target):
                continue
            target = unquote(re.split(r"[?#]", target, maxsplit=1)[0])
            target = re.sub(r"\\([\\ ()])", r"\1", target)
            # Leading / denotes a repository-root link; others are doc-relative.
            destination = (
                root / target.lstrip("/")
                if target.startswith("/")
                else root / relative.parent / target
            )
            try:
                valid = destination.exists()
            except (OSError, RuntimeError):
                valid = False
            if not valid:
                findings.append(
                    Finding(path, number, "LINK001", "Fix missing local Markdown link target.")
                )
    return findings


def check(root: Path = ROOT) -> list[Finding]:
    """Check only stack docs, entry instructions, and skill registrations."""
    root = Path(root)
    canonical = root / STACK / "skills"
    documents = {Path("AGENTS.md"), Path("CLAUDE.md"), STACK / "README.md"}
    documents.update(STACK / "skills" / name / "SKILL.md" for name in SKILLS)
    documents.update(
        path.relative_to(root)
        for path in canonical.rglob("*.md")
        if not {"backlog", "backlogs", "history"}.intersection(path.relative_to(canonical).parts)
    )
    findings = []
    for relative in sorted(documents):
        try:
            content = (root / relative).read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            findings.append(
                Finding(relative.as_posix(), 1, "FILE001", "Restore readable UTF-8 document.")
            )
            continue
        findings.extend(check_markdown(root, relative, content))
        if relative.name == "SKILL.md" and relative.parent.name in SKILLS:
            findings.extend(check_frontmatter(relative.as_posix(), content, relative.parent.name))
    for host in (".agents", ".claude"):
        for name in SKILLS:
            relative = Path(host) / "skills" / name
            try:
                valid = (root / relative).resolve(strict=True) == (canonical / name).resolve(
                    strict=True
                ) and (root / relative).is_dir()
            except (OSError, RuntimeError):
                valid = False
            if not valid:
                findings.append(
                    Finding(
                        relative.as_posix(),
                        1,
                        "REGISTER001",
                        "Link this registration to its canonical tools/sstack/skills directory.",
                    )
                )
    return findings


def main() -> int:
    findings = check()
    for finding in findings:
        print(finding)
    if not findings:
        print("SStack contracts passed.")
    return int(bool(findings))


if __name__ == "__main__":
    raise SystemExit(main())
