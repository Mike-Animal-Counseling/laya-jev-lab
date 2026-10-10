"""Fail-closed source release check. Prints filenames/rule names, never matched values."""
import argparse
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
IGNORED_DIRS = {".git", ".venv", "venv", "node_modules", ".next", "var", "models", "__pycache__", "build", "dist"}
IGNORED_FILES = {".env.local", "next-env.d.ts", "tsconfig.tsbuildinfo"}
RULES = {
    "private-key": re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "github-token": re.compile(rb"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})\b"),
    "cloud-key": re.compile(rb"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    "api-token": re.compile(rb"\b(?:sk|hf)-?[A-Za-z0-9_\-]{35,}\b"),
    "jwt": re.compile(rb"\beyJ[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{15,}\b"),
    "workstation-path": re.compile(rb"(?i)(?:(?<![a-z])[a-z]:[\\/](?![\\/])|/(?:home|Users)/[A-Za-z0-9_.-]+/)"),
    "credential-url": re.compile(rb"https?://[^\s/\"']+:[^\s/\"']+@"),
    "private-network-address": re.compile(rb"\b(?:192\.168\.\d{1,3}\.\d{1,3}|10\.\d{1,3}\.\d{1,3}\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})\b"),
}
EMAIL = re.compile(rb"\b[A-Za-z0-9_.+-]+@([A-Za-z0-9.-]+\.[A-Za-z]{2,})\b")
EXAMPLE_EMAIL_DOMAINS = {b"example.com", b"example.org", b"example.net", b"example.invalid", b"users.noreply.github.com"}


def linked(path):
    return path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction())


def allowlist():
    names = json.loads((ROOT / "release-files.json").read_text(encoding="utf-8"))
    if not isinstance(names, list) or len(names) != len(set(names)):
        raise ValueError("Invalid release allowlist")
    for name in names:
        p = PurePosixPath(name)
        if not isinstance(name, str) or p.is_absolute() or ".." in p.parts or "\\" in name or ":" in name:
            raise ValueError("Unsafe release path")
        if set(p.parts) & IGNORED_DIRS or (p.name.startswith(".env") and p.name != ".env.example"):
            raise ValueError("Private runtime path in release allowlist")
        if p.suffix in {".sqlite3", ".db", ".safetensors", ".zip", ".csv", ".jsonl", ".pem", ".key"}:
            raise ValueError("Private or binary artifact in source allowlist")
    return set(names)


def inspect(name, data, allowed):
    problems = []
    if name not in allowed:
        problems.append((name, "not-allowlisted"))
    if len(data) > 2 * 1024 * 1024:
        problems.append((name, "oversized-source-file"))
    for label, pattern in RULES.items():
        if pattern.search(data):
            problems.append((name, label))
    if any(match[1].lower() not in EXAMPLE_EMAIL_DOMAINS for match in EMAIL.finditer(data)):
        problems.append((name, "unreviewed-email-address"))
    if name == ".env.example":
        for line in data.decode("utf-8").splitlines():
            key, sep, value = line.partition("=")
            if sep and (key.strip().endswith(("_KEY", "_TOKEN", "_PASSWORD")) or key.strip() in {"ZENDESK_EMAIL", "MAIL_IMAP_USER"}) and value.strip():
                problems.append((name, "example-must-have-empty-key"))
    return problems


def git(*args):
    result = subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, check=True)
    return result.stdout


def check_identity():
    problems = []
    for label in ("GIT_AUTHOR_IDENT", "GIT_COMMITTER_IDENT"):
        try:
            identity = git("var", label).decode("utf-8").strip()
        except subprocess.CalledProcessError:
            problems.append(("Git identity", "configure-public-name-and-github-privacy-email"))
            continue
        match = re.match(r"(.+) <([^<>]+)> \d+ [+-]\d{4}$", identity)
        if not match or not re.fullmatch(r"(?:\d+\+)?[A-Za-z0-9-]+@users\.noreply\.github\.com", match[2]):
            problems.append(("Git identity", "use-github-provided-privacy-email"))
        elif any(value and value.casefold() == match[1].strip().casefold()
                 for value in (os.environ.get("USERNAME"), os.environ.get("COMPUTERNAME"))):
            problems.append(("Git identity", "choose-public-alias-not-workstation-name"))
    return problems


def check(staged=False):
    allowed = allowlist()
    problems = []
    for name in sorted(allowed):
        path = ROOT / name
        if not path.is_file():
            problems.append((name, "missing-source"))
            continue
        if any(linked(p) for p in [path, *path.parents]):
            problems.append((name, "linked-source"))
            continue
        problems.extend(inspect(name, path.read_bytes(), allowed))
    # Unexpected files cannot quietly join an export, even if .gitignore changes.
    def walk(directory):
        for p in directory.iterdir():
            name = p.relative_to(ROOT).as_posix()
            if p.name in IGNORED_DIRS or (p.is_dir() and p.name.endswith(".egg-info")) or (p.parent == ROOT and p.name in IGNORED_FILES):
                continue
            if linked(p):
                problems.append((name, "linked-source"))
            elif p.is_dir():
                walk(p)
            elif name not in allowed:
                problems.append((name, "unexpected-source"))
    walk(ROOT)
    if staged:
        # Scan actual index bytes, including ignored files added with git add -f.
        if Path(git("rev-parse", "--show-toplevel").decode().strip()).resolve() != ROOT:
            raise ValueError("The release must be its own repository, not part of a parent workspace")
        entries = git("ls-files", "--stage", "-z").split(b"\0")
        for entry in filter(None, entries):
            meta, raw_name = entry.split(b"\t", 1)
            mode, object_id, stage = meta.split()
            name = raw_name.decode("utf-8")
            if stage != b"0" or mode not in (b"100644", b"100755"):
                problems.append((name, "unsafe-git-entry"))
            else:
                problems.extend(inspect(name, git("cat-file", "blob", object_id.decode()), allowed))
    return sorted(set(problems))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--staged", action="store_true", help="Also inspect the exact Git index before committing")
    parser.add_argument("--identity", action="store_true", help="Require a public alias and GitHub privacy email")
    args = parser.parse_args()
    try:
        problems = check(args.staged)
        if args.identity:
            problems.extend(check_identity())
    except (OSError, ValueError, subprocess.CalledProcessError):
        print("Public check could not complete; do not publish.")
        return 1
    for name, rule in problems:
        print(f"BLOCKED {name}: {rule}")
    if problems:
        return 1
    print(f"PASS: {len(allowlist())} allowlisted source files; no detected publication blockers.")
    print("Pattern scanning cannot prove the absence of every kind of personal information.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
