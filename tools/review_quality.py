#!/usr/bin/env python3
"""Inventory added C/C++ tokens and enforce the personal fork's comment policy."""

import argparse
from collections import Counter
import hashlib
import bisect
import json
import io
import tokenize
from pathlib import Path
import re
import subprocess

CPP_EXTENSIONS = (".c", ".cc", ".cpp", ".h", ".hpp", ".inl")
MAX_NUMBERS = 1024
MAX_NUMBER_CONTEXT_CHARS = 240
MAX_COMMENT_TEXT_CHARS = 300
MAX_LINT_COMMENT_CHARS = 180
HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")
ADDRESS = re.compile(
    r"^// BW1W120 (?:[0-9a-fA-F]{8}|inlined|purecall|null)"
    r"(?: BW1WCI (?:[0-9a-fA-F]{8}|inlined|purecall|null))?"
    r"(?: BW1M119 (?:[0-9a-fA-F]{8}|inlined|purecall|null)(?: \([^\n]+\))?)?$"
)
TOKEN = re.compile(
    r"(?P<comment>//(?:\\\r?\n|[^\n])*|/\*[\s\S]*?(?:\*/|\Z))"
    r'|(?P<raw_string>(?:u8|[LuU])?R"(?P<delimiter>[^\s()\\]{0,16})\('
    r'[\s\S]*?(?:\)(?P=delimiter)"|\Z))'
    r'|(?P<string>"(?:\\[\s\S]|[^"\\])*(?:"|\Z)|\'(?:\\[\s\S]|[^\'\\])*(?:\'|\Z))'
    r"|(?P<number>(?<![\w.])(?:0[xX][0-9a-fA-F]+[uUlL]*|"
    r"(?:\d+\.\d*|\.\d+|\d+)(?:[eE][+-]?\d+)?[fFuUlL]*)(?!\w))"
    r"|(?P<brace>[{}])"
)


def owned_cpp(path):
    return (
        path.startswith(("src/", "tools/"))
        and path.endswith(CPP_EXTENSIONS)
        and not path.startswith(("src/zlib/", "src/GameSpy/"))
    )


def owned_source(path):
    return (
        owned_cpp(path)
        or (path.endswith(".py") and (path.startswith("tools/") or path == "configure.py"))
        or (path.startswith(".github/") and path.endswith((".yml", ".yaml")))
    )


def scan_python(path, text, changed):
    numbers, comments = [], []
    lines = text.splitlines()
    try:
        for token in tokenize.generate_tokens(io.StringIO(text).readline):
            line, column = token.start
            if line not in changed:
                continue
            location = {"path": path, "line": line, "column": column + 1}
            if token.type == tokenize.NUMBER:
                numbers.append(dict(location, literal=token.string, context=lines[line - 1][:MAX_NUMBER_CONTEXT_CHARS]))
            elif token.type == tokenize.COMMENT:
                directive = (line == 1 and token.string.startswith("#!")) or (
                    line <= 2 and re.search(r"coding[:=]\s*[-\w.]+", token.string)
                )
                comments.append(
                    dict(
                        location,
                        signature=comment_signature(token.string),
                        text=token.string[:MAX_COMMENT_TEXT_CHARS],
                        kind="interpreter/encoding directive" if directive else "remove prose comment",
                    )
                )
    except (tokenize.TokenError, IndentationError):
        return numbers, comments, False
    return numbers, comments, True


def scan_yaml(path, text, changed):
    try:
        import yaml

        tokens = list(yaml.scan(text))
    except ImportError:
        return [], [], False
    except yaml.YAMLError:
        return [], [], False
    masked = list(text)
    lines = text.splitlines()
    numbers = []
    for token in tokens:
        if not isinstance(token, yaml.ScalarToken):
            continue
        line = token.start_mark.line + 1
        if (
            line in changed
            and token.plain
            and re.fullmatch(
                r"[+-]?(?:0[xX][0-9a-fA-F_]+|0[oO][0-7_]+|0[bB][01_]+|"
                r"(?:[0-9][0-9_]*\.?[0-9_]*|\.[0-9_]+)(?:[eE][+-]?[0-9_]+)?)",
                token.value,
            )
        ):
            numbers.append(
                {
                    "path": path,
                    "line": line,
                    "column": token.start_mark.column + 1,
                    "literal": token.value,
                    "context": lines[line - 1][:MAX_NUMBER_CONTEXT_CHARS],
                }
            )
        for offset in range(token.start_mark.index, token.end_mark.index):
            if masked[offset] != "\n":
                masked[offset] = " "
    line_starts = [0] + [m.end() for m in re.finditer("\n", text)]
    comments = []
    for comment in re.finditer(r"#[^\n]*", "".join(masked)):
        line = bisect.bisect_right(line_starts, comment.start())
        if line in changed:
            comments.append(
                {
                    "path": path,
                    "line": line,
                    "column": comment.start() - line_starts[line - 1] + 1,
                    "signature": comment_signature(text[comment.start() : comment.end()]),
                    "text": text[comment.start() : comment.end()][:MAX_COMMENT_TEXT_CHARS],
                    "kind": "remove prose comment",
                }
            )
    return numbers, comments, True


def added_lines(patch):
    result, current = set(), None
    for row in patch.splitlines():
        match = HUNK.match(row)
        if match:
            current = int(match.group(1))
        elif current is not None and row.startswith("+"):
            result.add(current)
            current += 1
        elif current is not None and row.startswith(" "):
            current += 1
    return result


def comment_kind(path, text, start, end, comment, depth):
    stripped = comment.strip()
    if stripped in ("// clang-format off", "// clang-format on"):
        return "format directive"
    following = text[end:].lstrip()
    if ADDRESS.fullmatch(stripped):
        if path.endswith((".h", ".hpp", ".inl")):
            return "address annotation"
        declaration = following.split(";", 1)[0]
        if ";" in following and "{" not in declaration and "(" in declaration:
            return "forward-declaration address annotation"
    if re.fullmatch(r"// Inliner IL size: \d+", stripped) and following.startswith("// BW1W120 "):
        return "inliner annotation"
    prefix = text[text.rfind("\n", 0, start) + 1 : start].rstrip()
    if stripped == "//" and prefix.endswith(",") and depth > 0:
        return "initializer formatting"
    return "remove prose comment"


def scan_file(path, text, changed):
    line_starts = [0] + [m.end() for m in re.finditer("\n", text)]
    numbers, comments, depth = [], [], 0
    complete = True
    lines = text.splitlines()
    for token in TOKEN.finditer(text):
        kind = token.lastgroup
        value = token.group()
        if kind == "raw_string":
            complete = complete and value.endswith(")" + token.group("delimiter") + '"')
            continue
        if kind == "string":
            trailing_slashes = len(value[:-1]) - len(value[:-1].rstrip("\\"))
            complete = complete and value[-1:] == value[:1] and trailing_slashes % 2 == 0
            continue
        if kind == "comment" and value.startswith("/*") and not value.endswith("*/"):
            complete = False
        if kind == "brace":
            depth += 1 if value == "{" else -1
            continue
        first = bisect.bisect_right(line_starts, token.start())
        last = bisect.bisect_right(line_starts, max(token.start(), token.end() - 1))
        touched = changed.intersection(range(first, last + 1))
        if not touched:
            continue
        line = min(touched)
        location = {"path": path, "line": line, "column": token.start() - line_starts[first - 1] + 1}
        if kind == "number":
            numbers.append(dict(location, literal=value, context=lines[line - 1][:MAX_NUMBER_CONTEXT_CHARS]))
        elif kind == "comment":
            comments.append(
                dict(
                    location,
                    signature=comment_signature(value),
                    text=value[:MAX_COMMENT_TEXT_CHARS],
                    started_in_added_line=first in changed,
                    added_lines=sorted(touched),
                    kind=comment_kind(path, text, token.start(), token.end(), value, depth),
                )
            )
    return numbers, comments, complete


def comment_signature(text):
    return hashlib.sha256(" ".join(text.split()).encode("utf-8")).hexdigest()


def comment_signatures(path, text):
    scanner = scan_python if path.endswith(".py") else scan_yaml if path.endswith((".yml", ".yaml")) else scan_file
    _, comments, complete = scanner(path, text, set(range(1, len(text.splitlines()) + 1)))
    return [comment["signature"] for comment in comments], complete


def inventory(files, source_context, file_list_truncated=False, base_context_required=False):
    sources = {source["path"]: source for source in source_context}
    result = {
        "scope": "Added/edited owned C/C++, Python tooling, and GitHub YAML values/comments; excludes vendored code, documentation, strings/docstrings, and embedded scripts",
        "numbers": [],
        "comments": [],
        "number_count": 0,
        "comment_count": 0,
        "remove_comment_count": 0,
        "allowed_comment_count": 0,
        "limitations": [],
        "eligible_files": 0,
        "comments_complete": True,
    }
    if file_list_truncated:
        result["limitations"].append("Changed-file list was truncated")
        result["comments_complete"] = False
    for item in files:
        path = item.get("filename", "")
        if not owned_source(path) or item.get("status") == "removed":
            continue
        result["eligible_files"] += 1
        if item.get("additions") == 0:
            continue
        source = sources.get(path)
        patch = item.get("patch")
        if not source or not isinstance(patch, str):
            result["limitations"].append(path + ": source or patch unavailable")
            result["comments_complete"] = False
            continue
        changed = added_lines(patch)
        if len(changed) != item.get("additions", len(changed)):
            result["limitations"].append(path + ": patch additions are incomplete")
            result["comments_complete"] = False
        if source.get("status") != "complete":
            result["limitations"].append(path + ": source context is incomplete")
            result["comments_complete"] = False
        if path.endswith(".py"):
            numbers, comments, complete = scan_python(path, source.get("text", ""), changed)
            if not complete:
                result["limitations"].append(path + ": Python tokenization was incomplete")
                result["comments_complete"] = False
        elif path.endswith((".yml", ".yaml")):
            numbers, comments, complete = scan_yaml(path, source.get("text", ""), changed)
            if not complete:
                result["limitations"].append(path + ": YAML tokenizer unavailable or syntax incomplete")
                result["comments_complete"] = False
        else:
            numbers, comments, complete = scan_file(path, source.get("text", ""), changed)
            if not complete:
                result["limitations"].append(path + ": C/C++ tokenization was incomplete")
                result["comments_complete"] = False
        if "base_comment_signatures" in source and source.get("base_comments_complete"):
            head_signatures, head_complete = comment_signatures(path, source.get("text", ""))
            remaining = Counter(head_signatures) - Counter(source["base_comment_signatures"])
            added_comments = []
            for comment in comments:
                signature = comment["signature"]
                if remaining[signature] > 0:
                    added_comments.append(comment)
                    remaining[signature] -= 1
            comments = added_comments
            if not head_complete:
                result["comments_complete"] = False
        elif base_context_required:
            comments = []
            result["comments_complete"] = False
            result["limitations"].append(path + ": base comment comparison unavailable")
        for number in numbers:
            result["number_count"] += 1
            if len(result["numbers"]) < MAX_NUMBERS:
                result["numbers"].append(dict(number, id="N" + str(result["number_count"])))
        result["comment_count"] += len(comments)
        result["remove_comment_count"] += sum(c["kind"] == "remove prose comment" for c in comments)
        result["allowed_comment_count"] += sum(c["kind"] != "remove prose comment" for c in comments)
        result["comments"].extend(comments)
    if result["number_count"] > len(result["numbers"]):
        result["limitations"].append("Numeric classification inventory is capped at {}".format(MAX_NUMBERS))
    return result


def git_inventory(base, head):
    def resolve(ref):
        return subprocess.check_output(
            ["git", "rev-parse", "--verify", "--end-of-options", ref + "^{commit}"], text=True
        ).strip()

    base, head = resolve(base), resolve(head)
    paths = (
        subprocess.check_output(
            ["git", "diff", "--name-only", "--diff-filter=ACMR", "--no-renames", "-z", base, head, "--"]
        )
        .decode()
        .split("\0")
    )
    added_paths = set(
        subprocess.check_output(
            ["git", "diff", "--name-only", "--diff-filter=A", "--no-renames", "-z", base, head, "--"]
        )
        .decode()
        .split("\0")
    )
    files, sources = [], []
    for path in paths:
        if not owned_source(path):
            continue
        patch = subprocess.check_output(
            [
                "git",
                "diff",
                "--no-ext-diff",
                "--no-textconv",
                "--no-color",
                "--no-renames",
                "--unified=3",
                base,
                head,
                "--",
                path,
            ],
            text=True,
        )
        text = subprocess.check_output(["git", "show", head + ":" + path], text=True)
        files.append({"filename": path, "patch": patch})
        previous = subprocess.run(["git", "show", base + ":" + path], text=True, capture_output=True)
        signatures, complete = (
            comment_signatures(path, previous.stdout) if previous.returncode == 0 else ([], path in added_paths)
        )
        sources.append(
            {
                "path": path,
                "text": text,
                "status": "complete",
                "base_comment_signatures": signatures,
                "base_comments_complete": complete,
            }
        )
    return inventory(files, sources, base_context_required=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", default="HEAD")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--check-comments", action="store_true")
    args = parser.parse_args()
    result = git_inventory(args.base, args.head)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(
        "Added/edited comments: {}; remove: {}; allowed annotations: {}; numeric literals: {}".format(
            result["comment_count"],
            result["remove_comment_count"],
            result["allowed_comment_count"],
            result["number_count"],
        )
    )
    for comment in result["comments"]:
        if comment["kind"] == "remove prose comment":
            print(
                "{}:{}: remove added prose comment: {}".format(
                    comment["path"], comment["line"], " ".join(comment["text"].split())[:MAX_LINT_COMMENT_CHARS]
                )
            )
    return int(args.check_comments and (result["remove_comment_count"] or not result["comments_complete"]))


if __name__ == "__main__":
    raise SystemExit(main())
