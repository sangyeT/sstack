import argparse
import ipaddress
import json
import os
import re
import tempfile
from pathlib import Path, PurePosixPath
from urllib.parse import parse_qsl, urlsplit

ROOT = Path(__file__).resolve().parents[2]


def project_path(value):
    if not isinstance(value, str) or not value or "\\" in value:
        raise ValueError("Project path must be a repository-relative directory")
    parts = value.rstrip("/").split("/")
    if any(part in ("", ".", "..") for part in parts) or ":" in value:
        raise ValueError("Project path must not escape the repository")
    return str(PurePosixPath(*parts))


def board(value):
    if not isinstance(value, dict) or set(value) - {"url", "project_key"} or "url" not in value:
        raise ValueError("Board requires url and optional project_key only")
    url = value["url"]
    if not isinstance(url, str) or any(char.isspace() or ord(char) < 32 for char in url):
        raise ValueError("Board URL must be an HTTPS URL without whitespace")
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Board URL must use HTTPS without embedded credentials")
    if parsed.fragment or "\\" in url:
        raise ValueError("Board URL must not contain fragments or backslashes")
    _ = parsed.port
    host = parsed.hostname
    try:
        ipaddress.ip_address(host)
    except ValueError:
        if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?", host):
            raise ValueError("Board URL host is invalid") from None
    for key, _ in parse_qsl(parsed.query, keep_blank_values=True):
        if (
            re.search(
                r"token|secret|password|credential|signature|api.?key|access.?key|auth", key, re.I
            )
            or key.lower() == "code"
        ):
            raise ValueError("Board URL must not include credential query parameters")
    key = value.get("project_key")
    if key is not None and (
        not isinstance(key, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", key)
    ):
        raise ValueError("Project key must be an identifier")
    return {"url": url, **({"project_key": key} if key is not None else {})}


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Configuration contains duplicate keys")
        result[key] = value
    return result


def read_config(root):
    path = Path(root) / ".sstack.json"
    if path.is_symlink():
        raise ValueError("Configuration must not be a symlink")
    if not path.exists():
        return {"version": 1, "default": None, "projects": {}}
    try:
        value = json.loads(path.read_text(), object_pairs_hook=unique_object)
    except (json.JSONDecodeError, UnicodeError) as error:
        raise ValueError("Configuration is malformed; repair it before changing boards") from error
    if (
        not isinstance(value, dict)
        or set(value) != {"version", "default", "projects"}
        or type(value["version"]) is not int
        or value["version"] != 1
    ):
        raise ValueError("Configuration must use the version 1 schema")
    if not isinstance(value["projects"], dict):
        raise ValueError("Configuration projects must be a mapping")
    result = {
        "version": 1,
        "default": board(value["default"]) if value["default"] is not None else None,
        "projects": {},
    }
    for scope, entry in value["projects"].items():
        normalized = project_path(scope)
        if normalized != scope:
            raise ValueError("Stored project paths must be normalized")
        result["projects"][scope] = board(entry)
    return result


def updated_config(root, url=None, project_key=None, scope=None, clear=False):
    value = read_config(root)
    scope = project_path(scope) if scope is not None else None
    if scope is not None and not (Path(root) / scope).resolve().is_relative_to(
        Path(root).resolve()
    ):
        raise ValueError("Project scope resolves outside repository")
    entry = (
        None
        if clear
        else board({"url": url, **({"project_key": project_key} if project_key else {})})
    )
    if scope is None:
        value["default"] = entry
    elif clear:
        value["projects"].pop(scope, None)
    else:
        value["projects"][scope] = entry
    return value


def write_config(root, value):
    path = Path(root) / ".sstack.json"
    if path.is_symlink():
        raise ValueError("Configuration must not be a symlink")
    descriptor, temporary = tempfile.mkstemp(prefix=".sstack-", dir=root)
    try:
        with os.fdopen(descriptor, "w") as stream:
            json.dump(value, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def select_board(root, scope=None):
    value = read_config(root)
    if scope is not None:
        scope = project_path(scope)
        candidates = [
            key for key in value["projects"] if scope == key or scope.startswith(key + "/")
        ]
        if candidates:
            selected = max(candidates, key=len)
            return {"scope": selected, **value["projects"][selected]}
    if value["default"] is not None:
        return {"scope": "default", **value["default"]}
    return None


def main(argv=None, root=None):
    parser = argparse.ArgumentParser(description="Configure the PM board for future goals")
    subparsers = parser.add_subparsers(dest="command", required=True)
    setter = subparsers.add_parser("set")
    setter.add_argument("url")
    setter.add_argument("--project-key")
    for child in (setter, subparsers.add_parser("show"), subparsers.add_parser("clear")):
        child.add_argument("--project-path")
    args = parser.parse_args(argv)
    root = Path(root or ROOT)
    try:
        if args.command != "show":
            value = updated_config(
                root,
                getattr(args, "url", None),
                getattr(args, "project_key", None),
                args.project_path,
                args.command == "clear",
            )
            write_config(root, value)
            result = {"status": "configured", "applies_to": "future goals"}
        else:
            selection = select_board(root, args.project_path)
            result = {"status": "configured" if selection else "blocked", "board": selection}
        print(json.dumps(result, indent=2))
        return 0 if result["status"] != "blocked" else 1
    except (ValueError, OSError) as error:
        print(json.dumps({"status": "blocked", "reason": str(error)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
