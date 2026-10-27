#!/usr/bin/env python3
"""Search merged BW1 decomp PRs and their discussions with a JSON-first CLI."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import re
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPOSITORY = "openblack/bw1-decomp"
SCHEMA_VERSION = "bw1-pr-rag-v1"
DEFAULT_DB = Path.home() / ".cache" / "bw1-decomp-pr-rag" / "index.sqlite3"
MAX_RESULT_CHARS = 5000


def _json_default(value):
    return value.isoformat() if isinstance(value, datetime) else str(value)


def connect(path: Path) -> sqlite3.Connection:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA journal_mode=WAL")
    db.executescript("""
        CREATE TABLE IF NOT EXISTS metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS pulls (
            repository TEXT NOT NULL,
            number INTEGER NOT NULL,
            title TEXT NOT NULL,
            body TEXT NOT NULL,
            author TEXT,
            author_association TEXT,
            merged_by TEXT,
            merged_at TEXT,
            created_at TEXT,
            updated_at TEXT,
            html_url TEXT NOT NULL,
            base_ref TEXT,
            head_ref TEXT,
            merge_commit_sha TEXT,
            raw_json TEXT NOT NULL,
            PRIMARY KEY (repository, number)
        );
        CREATE TABLE IF NOT EXISTS documents (
            id TEXT PRIMARY KEY,
            repository TEXT NOT NULL,
            pr_number INTEGER NOT NULL,
            kind TEXT NOT NULL,
            title TEXT NOT NULL,
            body TEXT NOT NULL,
            author TEXT,
            author_association TEXT,
            state TEXT,
            path TEXT,
            line INTEGER,
            created_at TEXT,
            updated_at TEXT,
            html_url TEXT NOT NULL,
            raw_json TEXT NOT NULL,
            FOREIGN KEY (repository, pr_number) REFERENCES pulls(repository, number)
                ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS documents_pull ON documents(repository, pr_number);
        CREATE INDEX IF NOT EXISTS pulls_merged ON pulls(repository, merged_at);
        CREATE TABLE IF NOT EXISTS pr_files (
            repository TEXT NOT NULL,
            pr_number INTEGER NOT NULL,
            path TEXT NOT NULL,
            status TEXT,
            additions INTEGER,
            deletions INTEGER,
            raw_json TEXT NOT NULL,
            PRIMARY KEY(repository, pr_number, path),
            FOREIGN KEY (repository, pr_number) REFERENCES pulls(repository, number)
                ON DELETE CASCADE
        );
        CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts USING fts5(
            id UNINDEXED, repository UNINDEXED, pr_number UNINDEXED,
            kind UNINDEXED, title, body, author, path,
            tokenize='unicode61'
        );
    """)
    version = db.execute("SELECT value FROM metadata WHERE key='schema'").fetchone()
    if version and version[0] != SCHEMA_VERSION:
        db.close()
        raise RuntimeError(f"Unsupported index schema: {version[0]}")
    db.execute("INSERT OR REPLACE INTO metadata(key,value) VALUES('schema',?)", (SCHEMA_VERSION,))
    db.commit()
    return db


def _pull_doc(repository: str, pr: dict) -> dict:
    number = int(pr["number"])
    return {
        "id": f"{repository}#{number}:pr",
        "repository": repository,
        "pr_number": number,
        "kind": "pull_request",
        "title": pr.get("title") or "",
        "body": pr.get("body") or "",
        "author": (pr.get("user") or {}).get("login"),
        "author_association": pr.get("author_association"),
        "state": "merged",
        "path": "",
        "line": None,
        "created_at": pr.get("created_at"),
        "updated_at": pr.get("updated_at"),
        "html_url": pr.get("html_url") or f"https://github.com/{repository}/pull/{number}",
        "raw_json": json.dumps(pr, ensure_ascii=False, sort_keys=True),
    }


def _document(repository: str, number: int, kind: str, row: dict) -> dict:
    who = row.get("user") or {}
    identity = row.get("id") or row.get("node_id") or row.get("submitted_at") or "unknown"
    return {
        "id": f"{repository}#{number}:{kind}:{identity}",
        "repository": repository,
        "pr_number": number,
        "kind": kind,
        "title": row.get("name") or row.get("commit_id") or "",
        "body": row.get("body") or "",
        "author": who.get("login"),
        "author_association": row.get("author_association"),
        "state": row.get("state"),
        "path": row.get("path"),
        "line": row.get("line"),
        "created_at": row.get("created_at") or row.get("submitted_at"),
        "updated_at": row.get("updated_at") or row.get("submitted_at"),
        "html_url": row.get("html_url") or "",
        "raw_json": json.dumps(row, ensure_ascii=False, sort_keys=True),
    }


def _pull_number_from_url(url: str | None) -> int | None:
    if not url:
        return None
    match = re.search(r"/(?:issues|pulls)/(\d+)(?:/|$)", url)
    return int(match.group(1)) if match else None


def replace_repository_data(db: sqlite3.Connection, repository: str, pulls: list[dict],
                            docs: list[dict], files: list[tuple[int, dict]], *,
                            fetched_at: str | None = None) -> dict:
    """Atomically replace one repository snapshot after a complete fetch."""
    merged = [row for row in pulls if row.get("merged_at")]
    merged_numbers = {int(row["number"]) for row in merged}
    merged_by_number = {int(row["number"]): row for row in merged}
    document_fields = ("id", "repository", "pr_number", "kind", "title", "body", "author",
                       "author_association", "state", "path", "line", "created_at", "updated_at",
                       "html_url", "raw_json")
    selected_docs = [{key: doc.get(key) for key in document_fields}
                     for doc in docs if doc["pr_number"] in merged_numbers and doc.get("body")]
    for number, file_row in files:
        if number not in merged_numbers:
            continue
        file_path = file_row.get("filename") or ""
        if not file_path:
            continue
        pr = merged_by_number[number]
        selected_docs.append({
            "id": f"{repository}#{number}:file:{file_path}", "repository": repository,
            "pr_number": number, "kind": "changed_file", "title": file_row.get("status") or "",
            "body": file_path, "author": None, "author_association": None, "state": None,
            "path": file_path, "line": None, "created_at": pr.get("merged_at"),
            "updated_at": pr.get("merged_at"),
            "html_url": pr.get("html_url") or f"https://github.com/{repository}/pull/{number}",
            "raw_json": json.dumps(file_row, ensure_ascii=False, sort_keys=True),
        })
    with db:
        db.execute("DELETE FROM documents_fts WHERE repository=?", (repository,))
        db.execute("DELETE FROM pulls WHERE repository=?", (repository,))
        for pr in merged:
            number = int(pr["number"])
            db.execute("""INSERT INTO pulls VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
                repository, number, pr.get("title") or "", pr.get("body") or "",
                (pr.get("user") or {}).get("login"), pr.get("author_association"),
                (pr.get("merged_by") or {}).get("login"), pr.get("merged_at"),
                pr.get("created_at"), pr.get("updated_at"),
                pr.get("html_url") or f"https://github.com/{repository}/pull/{number}",
                (pr.get("base") or {}).get("ref"), (pr.get("head") or {}).get("ref"),
                pr.get("merge_commit_sha"), json.dumps(pr, ensure_ascii=False, sort_keys=True)))
        db.executemany("""INSERT INTO documents VALUES(
            :id,:repository,:pr_number,:kind,:title,:body,:author,:author_association,
            :state,:path,:line,:created_at,:updated_at,:html_url,:raw_json)""", selected_docs)
        db.executemany("INSERT INTO documents_fts VALUES(?,?,?,?,?,?,?,?)", [(
            d["id"], d["repository"], d["pr_number"], d["kind"], d["title"], d["body"],
            d["author"] or "", d["path"] or "") for d in selected_docs])
        db.executemany("INSERT INTO pr_files VALUES(?,?,?,?,?,?,?)", [(
            repository, number, row.get("filename") or "", row.get("status"),
            row.get("additions"), row.get("deletions"),
            json.dumps(row, ensure_ascii=False, sort_keys=True))
            for number, row in files if number in merged_numbers])
        db.execute("INSERT OR REPLACE INTO metadata(key,value) VALUES(?,?)",
                   (f"last_sync:{repository}", fetched_at or datetime.now(timezone.utc).isoformat()))
    return {"merged_pulls": len(merged), "documents": len(selected_docs),
            "files": sum(number in merged_numbers for number, _ in files)}


class GitHub:
    """Uses the caller's authenticated GitHub CLI; no token is copied into the index."""

    def __init__(self, runner=subprocess.run):
        self.runner = runner
        token = runner(["gh", "auth", "token"], capture_output=True, text=True)
        if token.returncode:
            raise RuntimeError("GitHub CLI is not authenticated; run `gh auth login`")
        self.token = token.stdout.strip()
        if not self.token:
            raise RuntimeError("GitHub CLI returned an empty authentication token")

    def pages(self, endpoint: str) -> list[dict]:
        url = "https://api.github.com/" + endpoint.lstrip("/")
        rows = []
        while url:
            for attempt in range(7):
                request = urllib.request.Request(url, headers={
                    "Accept": "application/vnd.github+json",
                    "Authorization": f"Bearer {self.token}",
                    "X-GitHub-Api-Version": "2022-11-28",
                    "User-Agent": "bw1-decomp-pr-rag/1",
                })
                try:
                    with urllib.request.urlopen(request, timeout=45) as response:
                        payload = json.loads(response.read().decode("utf-8"))
                        link = response.headers.get("Link", "")
                    if not isinstance(payload, list):
                        raise ValueError(f"Expected a JSON array from {url}")
                    rows.extend(payload)
                    next_link = re.search(r'<([^>]+)>;\s*rel="next"', link)
                    url = next_link.group(1) if next_link else ""
                    break
                except urllib.error.HTTPError as exc:
                    retry_after = exc.headers.get("Retry-After")
                    remaining = exc.headers.get("X-RateLimit-Remaining")
                    reset = exc.headers.get("X-RateLimit-Reset")
                    if exc.code in (403, 429) and remaining == "0" and reset:
                        delay = max(1, int(reset) - int(time.time()) + 1)
                    elif exc.code in (403, 429, 500, 502, 503, 504) and attempt < 6:
                        delay = int(retry_after) if retry_after and retry_after.isdigit() else min(60, 2 ** attempt)
                    else:
                        detail = exc.read().decode("utf-8", "replace")[:500]
                        raise RuntimeError(f"GitHub HTTP {exc.code} for {url}: {detail}") from exc
                    time.sleep(delay)
                except (urllib.error.URLError, TimeoutError) as exc:
                    if attempt >= 6:
                        raise RuntimeError(f"GitHub connection failed for {url}: {exc}") from exc
                    time.sleep(min(60, 2 ** attempt))
        return rows

    def fetch_repository(self, repository: str, *, include_files: bool = True) -> tuple[list, list, list]:
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
            raise ValueError("Repository must be owner/name")
        pulls = self.pages(f"repos/{repository}/pulls?state=all&per_page=100&sort=updated&direction=desc")
        merged = [pr for pr in pulls if pr.get("merged_at")]
        merged_numbers = {int(pr["number"]) for pr in merged}
        documents: list[dict] = []

        # Global comment endpoints avoid two HTTP calls for every individual PR.
        for kind, endpoint in (("conversation_comment", f"repos/{repository}/issues/comments?per_page=100"),
                               ("inline_review_comment", f"repos/{repository}/pulls/comments?per_page=100")):
            for row in self.pages(endpoint):
                number = _pull_number_from_url(row.get("issue_url") or row.get("pull_request_url"))
                if number in merged_numbers:
                    documents.append(_document(repository, number, kind, row))

        files: list[tuple[int, dict]] = []
        def fetch_pr_details(pr):
            number = int(pr["number"])
            reviews = self.pages(f"repos/{repository}/pulls/{number}/reviews?per_page=100")
            changed_files = self.pages(f"repos/{repository}/pulls/{number}/files?per_page=100") if include_files else []
            return number, reviews, changed_files

        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            futures = [pool.submit(fetch_pr_details, pr) for pr in merged]
            for index, future in enumerate(concurrent.futures.as_completed(futures), 1):
                number, reviews, changed_files = future.result()
                documents.extend(_document(repository, number, "review", review) for review in reviews)
                files.extend((number, row) for row in changed_files)
                if index % 50 == 0:
                    print(f"Fetched discussion details for {index}/{len(merged)} merged PRs", file=sys.stderr)
        documents.extend(_pull_doc(repository, pr) for pr in merged)
        return pulls, documents, files


def _fts_query(query: str) -> str:
    terms = re.findall(r"[^\W_]+(?:[_./:#-][^\W_]+)*", query, flags=re.UNICODE)
    if not terms:
        raise ValueError("Query must contain searchable letters or numbers")
    # Phrase quoting prevents user text from injecting FTS operators.
    return " AND ".join('"' + term.replace('"', '""') + '"' for term in terms)


def retrieve(db: sqlite3.Connection, query: str, *, repository: str = REPOSITORY,
             limit: int = 8, max_chars: int = MAX_RESULT_CHARS) -> dict:
    if not 1 <= limit <= 50 or max_chars < 256:
        raise ValueError("limit must be 1..50 and max_chars must be at least 256")
    fts = _fts_query(query)
    rows = db.execute("""SELECT d.*, p.title AS pr_title, p.merged_by, p.merged_at,
            p.html_url AS pr_url, p.author AS pr_author, p.base_ref, p.head_ref,
            bm25(documents_fts,0,0,0,0,5.0,1.0,0.25,0.8) AS rank
        FROM documents_fts JOIN documents d ON d.id=documents_fts.id
        JOIN pulls p ON p.repository=d.repository AND p.number=d.pr_number
        WHERE documents_fts MATCH ? AND d.repository=?
        ORDER BY rank LIMIT ?""", (fts, repository, limit)).fetchall()
    results = []
    used = 0
    for row in rows:
        content = row["body"]
        remaining = max_chars - used
        if remaining <= 0:
            break
        excerpt = content[:remaining]
        if len(content) > len(excerpt):
            excerpt = excerpt.rstrip() + " …[excerpt truncated]"
        used += len(excerpt)
        results.append({
            "document_id": row["id"], "kind": row["kind"], "pr_number": row["pr_number"],
            "pr_title": row["pr_title"], "title": row["title"], "author": row["author"],
            "author_association": row["author_association"], "review_state": row["state"],
            "path": row["path"], "line": row["line"], "created_at": row["created_at"],
            "url": row["html_url"] or row["pr_url"], "pr_url": row["pr_url"],
            "merged_at": row["merged_at"], "merged_by": row["merged_by"],
            "pr_author": row["pr_author"], "base_ref": row["base_ref"],
            "head_ref": row["head_ref"], "relevance": -float(row["rank"]),
            "excerpt": excerpt,
        })
    return {"schema": "bw1-pr-rag-results-v1", "repository": repository,
            "query": query, "results": results, "result_count": len(results),
            "source_policy": "Merged PR records and associated GitHub discussions; retrieval is precedent, not proof or an automatic project rule."}


def status(db: sqlite3.Connection, repository: str = REPOSITORY) -> dict:
    counts = db.execute("SELECT kind,COUNT(*) AS n FROM documents WHERE repository=? GROUP BY kind",
                        (repository,)).fetchall()
    return {"schema": SCHEMA_VERSION, "repository": repository,
            "merged_pulls": db.execute("SELECT COUNT(*) FROM pulls WHERE repository=?", (repository,)).fetchone()[0],
            "documents_by_kind": {row["kind"]: row["n"] for row in counts},
            "last_sync": (lambda r: r[0] if r else None)(db.execute(
                "SELECT value FROM metadata WHERE key=?", (f"last_sync:{repository}",)).fetchone())}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help="SQLite index path (default: user cache)")
    sub = parser.add_subparsers(dest="command", required=True)
    sync = sub.add_parser("sync", help="download merged PRs and discussion from GitHub")
    sync.add_argument("--repository", default=REPOSITORY)
    sync.add_argument("--no-files", action="store_true", help="skip per-PR changed-file metadata")
    search = sub.add_parser("search", help="retrieve cited excerpts as JSON")
    search.add_argument("query", nargs="?")
    search.add_argument("--stdin", action="store_true", help="read a JSON object containing query from stdin")
    search.add_argument("--repository", default=REPOSITORY)
    search.add_argument("--limit", type=int, default=8)
    search.add_argument("--max-chars", type=int, default=MAX_RESULT_CHARS)
    sub.add_parser("status", help="show index counts and last sync time")
    args = parser.parse_args(argv)
    db = connect(args.db)
    try:
        if args.command == "sync":
            gh = GitHub()
            pulls, docs, files = gh.fetch_repository(args.repository, include_files=not args.no_files)
            result = replace_repository_data(db, args.repository, pulls, docs, files)
            result.update(repository=args.repository, last_sync=datetime.now(timezone.utc).isoformat())
        elif args.command == "search":
            if args.stdin:
                request = json.load(sys.stdin)
                if not isinstance(request, dict) or not isinstance(request.get("query"), str):
                    raise ValueError("stdin JSON must be an object with a string query")
                result = retrieve(db, request["query"], repository=request.get("repository", args.repository),
                                  limit=int(request.get("limit", args.limit)),
                                  max_chars=int(request.get("max_chars", args.max_chars)))
            else:
                if not args.query:
                    raise ValueError("Provide query text or use --stdin")
                result = retrieve(db, args.query, repository=args.repository, limit=args.limit,
                                  max_chars=args.max_chars)
        else:
            result = status(db)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, RuntimeError, sqlite3.Error, OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        raise SystemExit(2)
