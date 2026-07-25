#!/usr/bin/env python3
"""
sql_syntax_check.py — platform-agnostic SQL syntax checking engine.

Walks a set of SQL files, determines the correct dialect for each
(SQL Server / T-SQL vs Snowflake, extensible to others), runs a
syntax-only parse via sqlfluff, and emits results as JSON to stdout
and a human-readable summary to stderr.

This file has NO Azure DevOps (or any platform) dependency. It is
meant to be called by a thin adapter (AzDO task, GitHub Action,
pre-commit hook, VS Code task, etc). Keeping it standalone means the
same engine can be "mounted" anywhere just by writing a new adapter.

Usage:
    python sql_syntax_check.py --path ./sql --dialect-config dialects.json
    python sql_syntax_check.py --path ./sql --default-dialect tsql
    python sql_syntax_check.py --files a.sql b.sql --default-dialect snowflake

Exit codes:
    0  -> no syntax errors found
    1  -> one or more syntax errors found
    2  -> tool/config error (bad args, sqlfluff not installed, etc.)
"""

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

try:
    from sqlfluff.core import Linter
except ImportError:
    print(
        "ERROR: sqlfluff is not installed. Run: pip install sqlfluff",
        file=sys.stderr,
    )
    sys.exit(2)

# Dialects we currently care about. sqlfluff's own dialect names are
# used directly so this map is mostly documentation + a validation
# gate against typos in dialect-config files.
SUPPORTED_DIALECTS = {
    "tsql": "SQL Server / Azure SQL (T-SQL)",
    "snowflake": "Snowflake",
    "ansi": "Generic ANSI SQL (fallback)",
}


@dataclass
class FileResult:
    path: str
    dialect: str
    ok: bool
    violations: list = field(default_factory=list)


def load_dialect_config(config_path: str) -> list:
    """
    Dialect config is a JSON list of {"pattern": <glob>, "dialect": <name>}
    matched in order, first match wins. Example:

    [
      {"pattern": "sqlserver/**/*.sql", "dialect": "tsql"},
      {"pattern": "snowflake/**/*.sql", "dialect": "snowflake"}
    ]
    """
    with open(config_path, "r", encoding="utf-8-sig") as f:
        rules = json.load(f)
    for rule in rules:
        if rule.get("dialect") not in SUPPORTED_DIALECTS:
            raise ValueError(
                f"Unknown dialect '{rule.get('dialect')}' in config. "
                f"Supported: {list(SUPPORTED_DIALECTS)}"
            )
    return rules


def glob_to_regex(pattern: str) -> re.Pattern:
    """
    Translate a small glob subset to regex, with correct '**' handling
    (matches across directory boundaries, unlike fnmatch's '*').
      **  -> any characters, including '/'
      *   -> any characters except '/'
      ?   -> a single character except '/'
    """
    out = []
    i = 0
    while i < len(pattern):
        c = pattern[i]
        if pattern[i:i + 3] == "**/":
            # '**/' matches zero or more path segments, including none
            out.append("(?:.*/)?")
            i += 3
        elif c == "*" and pattern[i:i + 2] == "**":
            out.append(".*")
            i += 2
        elif c == "*":
            out.append("[^/]*")
            i += 1
        elif c == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(c))
            i += 1
    return re.compile("^" + "".join(out) + "$")


def resolve_dialect(file_path: Path, rules: list, default_dialect: str) -> str:
    posix_path = file_path.as_posix()
    for rule in rules:
        if glob_to_regex(rule["pattern"]).match(posix_path):
            return rule["dialect"]
    return default_dialect


def discover_sql_files(paths: list) -> list:
    """Case-insensitive .sql discovery — mirrors the lesson learned in
    run_snowflake.py where an uppercase .SQL extension was silently
    skipped."""
    found = []
    for p in paths:
        path = Path(p)
        if path.is_file():
            found.append(path)
        elif path.is_dir():
            for f in path.rglob("*"):
                if f.is_file() and f.suffix.lower() == ".sql":
                    found.append(f)
    return sorted(set(found))


def safe_relative(path: Path, root: Path) -> str:
    """Best-effort relative path for display; falls back to the absolute
    path instead of crashing if the file isn't actually under root."""
    if not root:
        return str(path)
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def check_file(path: Path, dialect: str, root: Path) -> FileResult:
    linter = Linter(dialect=dialect)
    try:
        parsed = linter.lint_string(path.read_text(encoding="utf-8-sig", errors="replace"))
    except Exception as e:  # sqlfluff can raise on truly malformed input
        return FileResult(
            path=safe_relative(path, root),
            dialect=dialect,
            ok=False,
            violations=[{
                "line": 0, "col": 0, "code": "ENGINE_ERROR",
                "description": f"Parser failure: {e}",
            }],
        )

    violations = []
    for v in parsed.violations:
        d = v.to_dict()
        # Restrict to parse/syntax-level issues (rule code "PRS") —
        # this tool is a syntax checker, not a style linter. Style
        # rules (LT*, layout/formatting, etc.) can be layered on
        # later as an opt-in mode, but are excluded here so results
        # stay focused on "will this actually fail to run."
        if d.get("code") == "PRS":
            violations.append({
                "line": d.get("start_line_no", 0),
                "col": d.get("start_line_pos", 0),
                "code": d.get("code", "PRS"),
                "description": d.get("description", ""),
            })

    rel = safe_relative(path, root)
    return FileResult(path=rel, dialect=dialect, ok=len(violations) == 0, violations=violations)


def main():
    parser = argparse.ArgumentParser(description="Dialect-aware SQL syntax checker")
    parser.add_argument("filenames", nargs="*", default=[],
                         help="Positional files to check (used by the pre-commit framework, "
                              "which passes staged files this way)")
    parser.add_argument("--path", action="append", default=[],
                         help="Directory (or file) to scan; repeatable")
    parser.add_argument("--files", nargs="*", default=[],
                         help="Explicit list of files (e.g. changed files in a PR)")
    parser.add_argument("--dialect-config", default=None,
                         help="JSON file mapping glob patterns to dialects")
    parser.add_argument("--default-dialect", default="ansi",
                         choices=list(SUPPORTED_DIALECTS),
                         help="Dialect used when no config rule matches")
    parser.add_argument("--root", default=".",
                         help="Root used to compute relative paths in output")
    parser.add_argument("--json-out", default=None,
                         help="Optional path to write full JSON results")
    parser.add_argument("--quiet", action="store_true",
                         help="Suppress the JSON dump to stdout; keep only the human-readable "
                              "summary on stderr (used by the pre-commit hook)")
    args = parser.parse_args()

    if not args.path and not args.files and not args.filenames:
        print("ERROR: provide --path, --files, and/or positional filenames", file=sys.stderr)
        sys.exit(2)

    rules = load_dialect_config(args.dialect_config) if args.dialect_config else []
    root = Path(args.root).resolve()

    targets = discover_sql_files(args.path) + [Path(f) for f in args.files] + [Path(f) for f in args.filenames]
    targets = sorted(set(t.resolve() for t in targets))

    if not targets:
        print("No .sql files found to check.", file=sys.stderr)
        results = []
    else:
        results = []
        for t in targets:
            try:
                rel_for_match = t.resolve().relative_to(root)
            except ValueError:
                rel_for_match = t
            dialect = resolve_dialect(rel_for_match, rules, args.default_dialect)
            results.append(check_file(t, dialect, root))

    total = len(results)
    failed = [r for r in results if not r.ok]

    for r in results:
        status = "OK   " if r.ok else "ERROR"
        print(f"[{status}] {r.path}  (dialect: {r.dialect})", file=sys.stderr)
        for v in r.violations:
            print(f"         line {v['line']}, col {v['col']}: {v['description']}", file=sys.stderr)

    print(f"\n{total - len(failed)}/{total} files passed syntax check.", file=sys.stderr)

    payload = {
        "summary": {"total": total, "passed": total - len(failed), "failed": len(failed)},
        "results": [
            {"path": r.path, "dialect": r.dialect, "ok": r.ok, "violations": r.violations}
            for r in results
        ],
    }
    output_json = json.dumps(payload, indent=2)
    if not args.quiet:
        print(output_json)

    if args.json_out:
        Path(args.json_out).write_text(output_json, encoding="utf-8")

    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
