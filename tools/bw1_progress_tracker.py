#!/usr/bin/env python3
"""Read-only BW1 CI progress archive and static report generator."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

VERSIONS = ("BW1W100", "BW1W110", "BW1W120", "BW1W130", "BW1WCI")
SCHEMA = "bw1-progress-snapshot-v1"
ROOT = Path(__file__).resolve().parent
DEFAULT_DATA = ROOT / "data"
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
MEASURE_KEYS = (
    "total_code", "matched_code", "matched_code_percent",
    "total_data", "matched_data", "matched_data_percent",
    "total_functions", "matched_functions", "total_units", "complete_units",
    "complete_code", "complete_code_percent", "complete_data", "complete_data_percent",
)


class TrackerError(Exception):
    pass


def command(*args: str) -> str:
    try:
        result = subprocess.run(args, check=True, capture_output=True, text=True)
    except FileNotFoundError as exc:
        raise TrackerError(f"Required command is unavailable: {args[0]}") from exc
    except subprocess.CalledProcessError as exc:
        raise TrackerError(f"Command failed: {' '.join(args)}\n{exc.stderr.strip()}") from exc
    return result.stdout


def read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise TrackerError(f"Cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise TrackerError(f"Expected a JSON object in {path}")
    return value


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")


def validate_repository(repository: str) -> str:
    if not REPO_RE.fullmatch(repository):
        raise TrackerError("Repository must have the form owner/name")
    return repository


def inspect_metadata(meta: dict, repository: str, run_id: int) -> dict:
    sha = meta.get("headSha")
    jobs = meta.get("jobs")
    if not isinstance(sha, str) or not SHA_RE.fullmatch(sha):
        raise TrackerError("Run metadata lacks a full head SHA")
    if not isinstance(jobs, list):
        raise TrackerError("Run metadata lacks jobs")
    job_states = {}
    for version in VERSIONS:
        name = f"build ({version})"
        matching = [job for job in jobs if isinstance(job, dict) and job.get("name") == name]
        job_states[version] = matching[0].get("conclusion") if len(matching) == 1 else "missing-or-duplicate"
    other_jobs = {str(job.get("name")): job.get("conclusion")
                  for job in jobs if isinstance(job, dict) and job.get("name") not in
                  {f"build ({version})" for version in VERSIONS}}
    return {
        "repository": repository,
        "run_id": run_id,
        "run_url": f"https://github.com/{repository}/actions/runs/{run_id}",
        "head_sha": sha,
        "head_branch": meta.get("headBranch") or "",
        "event": meta.get("event") or "",
        "created_at": meta.get("createdAt") or "",
        "conclusion": meta.get("conclusion") or "",
        "build_jobs": job_states,
        "other_jobs": other_jobs,
        "eligible": meta.get("conclusion") == "success" and all(v == "success" for v in job_states.values()),
    }


def fetch_metadata(repository: str, run_id: int) -> dict:
    payload = command(
        "gh", "run", "view", str(run_id), "-R", repository,
        "--json", "headSha,headBranch,conclusion,event,createdAt,jobs",
    )
    try:
        return json.loads(payload)
    except json.JSONDecodeError as exc:
        raise TrackerError("GitHub CLI returned invalid run JSON") from exc


def latest_main_runs(repository: str, count: int) -> list[int]:
    if count < 1 or count > 20:
        raise TrackerError("Count must be between 1 and 20")
    payload = command("gh", "run", "list", "-R", repository, "-w", "Build", "-b", "main",
                      "-L", str(max(20, count * 4)), "--json", "databaseId,conclusion,createdAt")
    try:
        rows = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise TrackerError("GitHub CLI returned invalid run list JSON") from exc
    if not isinstance(rows, list):
        raise TrackerError("GitHub CLI returned an invalid run list")
    passed = sorted((row for row in rows if row.get("conclusion") == "success"),
                    key=lambda row: row.get("createdAt") or "", reverse=True)
    if len(passed) < count:
        raise TrackerError(f"Found only {len(passed)} successful main Build runs in recent history")
    return [int(row["databaseId"]) for row in reversed(passed[:count])]


def validate_report(path: Path) -> dict:
    report = read_json(path)
    if report.get("version") != 2:
        raise TrackerError(f"Unsupported objdiff report version in {path}: {report.get('version')!r}")
    measures = report.get("measures")
    if not isinstance(measures, dict) or not isinstance(report.get("units"), list):
        raise TrackerError(f"Missing objdiff measures or units in {path}")
    clean = {}
    for key in MEASURE_KEYS:
        value = measures.get(key)
        if isinstance(value, str) and value.isdecimal():
            value = int(value)
        if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
            raise TrackerError(f"Invalid {key} in {path}")
        clean[key] = value
    for whole, part in (("total_code", "matched_code"), ("total_data", "matched_data"),
                        ("total_functions", "matched_functions"), ("total_units", "complete_units")):
        if clean[part] > clean[whole]:
            raise TrackerError(f"{part} exceeds {whole} in {path}")
    for key in ("matched_code_percent", "matched_data_percent", "complete_code_percent", "complete_data_percent"):
        if clean[key] > 100:
            raise TrackerError(f"Invalid percentage {key} in {path}")
    categories = []
    for category in report.get("categories", []):
        if isinstance(category, dict) and isinstance(category.get("measures"), dict):
            categories.append({
                "id": str(category.get("id", "")),
                "name": str(category.get("name", "")),
                "matched_code_percent": category["measures"].get("matched_code_percent"),
                "matched_data_percent": category["measures"].get("matched_data_percent"),
            })
    return {"measures": clean, "categories": categories, "units_count": len(report["units"])}


def locate_reports(directory: Path) -> dict[str, Path]:
    found = {}
    for version in VERSIONS:
        candidates = [directory / f"{version}_report" / "report.json"]
        candidates.extend(directory.glob(f"**/{version}_report/report.json"))
        unique = sorted({p.resolve() for p in candidates if p.is_file()})
        if len(unique) != 1:
            raise TrackerError(f"Expected exactly one {version}_report/report.json under {directory}; found {len(unique)}")
        found[version] = unique[0]
    return found


def archive_run(data_dir: Path, metadata: dict, reports_dir: Path, *, summary_only: bool = False) -> dict:
    repository = validate_repository(metadata["repository"])
    run_id = int(metadata["run_id"])
    if not metadata["eligible"]:
        bad = {k: v for k, v in metadata["build_jobs"].items() if v != "success"}
        raise TrackerError(f"Run {run_id} is not a complete successful build: conclusion={metadata['conclusion']}, jobs={bad}")
    report_paths = locate_reports(reports_dir)
    target = data_dir / "runs" / repository.replace("/", "__") / str(run_id)
    if target.exists():
        existing = read_json(target / "manifest.json")
        if existing.get("head_sha") != metadata["head_sha"]:
            raise TrackerError(f"Run ID {run_id} already archived with a different SHA")
        for version, source in report_paths.items():
            actual = hashlib.sha256(source.read_bytes()).hexdigest()
            if actual != existing["versions"][version]["sha256"]:
                raise TrackerError(f"Run ID {run_id} has changed {version} report bytes")
        return {"status": "already_archived", "manifest": existing, "path": str(target)}
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".staging-", dir=target.parent) as temporary:
        staging = Path(temporary)
        summaries = {}
        for version, source in report_paths.items():
            summaries[version] = validate_report(source)
            summaries[version]["sha256"] = hashlib.sha256(source.read_bytes()).hexdigest()
            if not summary_only:
                shutil.copyfile(source, staging / f"{version}.json")
            summaries[version]["artifact_name"] = f"{version}_report"
        manifest = {
            "schema": SCHEMA, **metadata,
            "ingested_at": datetime.now(timezone.utc).isoformat(),
            "report_storage": "summary_only" if summary_only else "full",
            "versions": summaries,
            "version_identity": "GitHub Actions artifact name and matrix job; objdiff report v2 has no embedded game version",
        }
        write_json(staging / "manifest.json", manifest)
        staging.rename(target)
    return {"status": "archived", "manifest": manifest, "path": str(target)}


def all_manifests(data_dir: Path) -> list[dict]:
    result = []
    for path in (data_dir / "runs").glob("*/*/manifest.json"):
        row = read_json(path)
        if row.get("schema") == SCHEMA:
            result.append(row)
    return sorted(result, key=lambda row: (row.get("created_at", ""), row["repository"], row["run_id"]))


def find_manifest(data_dir: Path, repository: str, run_id: int) -> dict:
    path = data_dir / "runs" / repository.replace("/", "__") / str(run_id) / "manifest.json"
    if not path.exists():
        raise TrackerError(f"Run {repository}#{run_id} is not archived")
    return read_json(path)


def verify_archive(data_dir: Path) -> dict:
    runs = all_manifests(data_dir)
    checked = 0
    compact = 0
    for run in runs:
        root = data_dir / "runs" / run["repository"].replace("/", "__") / str(run["run_id"])
        if not run.get("eligible") or set(run.get("versions", {})) != set(VERSIONS):
            raise TrackerError(f"Incomplete archived run {run['run_id']}")
        if run.get("report_storage") == "summary_only":
            for version in VERSIONS:
                entry = run["versions"][version]
                if not re.fullmatch(r"[0-9a-f]{64}", entry.get("sha256", "")):
                    raise TrackerError(f"Invalid archived report digest for {version} in run {run['run_id']}")
                measures = entry.get("measures")
                if not isinstance(measures, dict) or set(measures) != set(MEASURE_KEYS):
                    raise TrackerError(f"Invalid archived measures for {version} in run {run['run_id']}")
                compact += 1
            continue
        for version in VERSIONS:
            path = root / f"{version}.json"
            if not path.is_file():
                raise TrackerError(f"Missing archived report {path}")
            if hashlib.sha256(path.read_bytes()).hexdigest() != run["versions"][version]["sha256"]:
                raise TrackerError(f"Archived report hash differs: {path}")
            if validate_report(path)["measures"] != run["versions"][version]["measures"]:
                raise TrackerError(f"Archived report measures differ: {path}")
            checked += 1
    return {"runs": len(runs), "reports_verified": checked, "summary_only_records": compact}


def compare_runs(old: dict, new: dict) -> dict:
    if old["repository"] != new["repository"]:
        raise TrackerError("Cannot compare runs from different repositories")
    rows = {}
    for version in VERSIONS:
        before = old["versions"][version]["measures"]
        after = new["versions"][version]["measures"]
        rows[version] = {
            "matched_code_bytes": after["matched_code"] - before["matched_code"],
            "matched_data_bytes": after["matched_data"] - before["matched_data"],
            "complete_units": after["complete_units"] - before["complete_units"],
            "total_code_bytes": after["total_code"] - before["total_code"],
            "code_percent_points": round(after["matched_code_percent"] - before["matched_code_percent"], 4),
            "data_percent_points": round(after["matched_data_percent"] - before["matched_data_percent"], 4),
        }
    return {"repository": new["repository"], "from_run": old["run_id"], "to_run": new["run_id"],
            "from_sha": old["head_sha"], "to_sha": new["head_sha"], "versions": rows}


def badge(label: str, percent: float) -> str:
    label = html.escape(label)
    value = html.escape(f"{percent:.2f}%")
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="178" height="22" role="img" '
            f'aria-label="{label}: {value}"><rect width="178" height="22" rx="4" fill="#30343b"/>'
            f'<path d="M88 0h86a4 4 0 0 1 4 4v14a4 4 0 0 1-4 4H88z" fill="#247e62"/>'
            f'<text x="44" y="15" text-anchor="middle" fill="white" font-family="Arial" font-size="12">{label}</text>'
            f'<text x="133" y="15" text-anchor="middle" fill="white" font-family="Arial" font-size="12">{value}</text></svg>')


def render(data_dir: Path, output: Path, repository: str, branch: str = "main") -> dict:
    runs = [row for row in all_manifests(data_dir)
            if row["repository"] == repository and (branch == "*" or row["head_branch"] == branch)]
    if not runs:
        raise TrackerError(f"No archived runs for {repository} on branch {branch}")
    output.mkdir(parents=True, exist_ok=True)
    latest = runs[-1]
    rows = []
    for version in VERSIONS:
        m = latest["versions"][version]["measures"]
        rows.append(f"<tr><th>{version}</th><td>{m['matched_code_percent']:.2f}%</td>"
                    f"<td>{m['matched_data_percent']:.2f}%</td><td>{m['complete_units']:,}/{m['total_units']:,}</td></tr>")
        (output / f"{version}-code.svg").write_text(badge(f"{version} code", m["matched_code_percent"]), encoding="utf-8")
        (output / f"{version}-data.svg").write_text(badge(f"{version} data", m["matched_data_percent"]), encoding="utf-8")
    history = []
    for version in VERSIONS:
        previous = None
        for run in runs:
            m = run["versions"][version]["measures"]
            code_delta = "—" if previous is None else f"{m['matched_code'] - previous['matched_code']:+,} B"
            data_delta = "—" if previous is None else f"{m['matched_data'] - previous['matched_data']:+,} B"
            history.append(f'<tr><th>{version}</th><td><a href="{html.escape(run["run_url"], quote=True)}">{run["run_id"]}</a></td>'
                           f'<td>{html.escape(run["created_at"])}</td><td>{m["matched_code_percent"]:.2f}%</td>'
                           f'<td>{code_delta}</td><td>{m["matched_data_percent"]:.2f}%</td><td>{data_delta}</td>'
                           f'<td>{m["complete_units"]:,}/{m["total_units"]:,}</td></tr>')
            previous = m
    content = f"""<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>BW1 progress · {html.escape(repository)}</title><style>
body{{font:16px/1.5 system-ui,sans-serif;max-width:960px;margin:2rem auto;padding:0 1rem;color:#e9edf0;background:#171b20}}
a{{color:#7ed9ba}}table{{width:100%;border-collapse:collapse;margin:1rem 0 2rem}}th,td{{padding:.55rem;border-bottom:1px solid #454b52;text-align:left}}
.note{{color:#b8c1c9}}code{{font-size:.9em}}
</style><h1>Black &amp; White 1 progress</h1><p>{html.escape(repository)} · {html.escape(branch)}</p>
<p class="note">Latest archived successful five-version Build run: <a href="{html.escape(latest['run_url'], quote=True)}">{latest['run_id']}</a>,
commit <code>{html.escape(latest['head_sha'][:12])}</code>. Each version build passed its binary checksum.</p>
<h2>Latest run by version</h2><table><thead><tr><th>Version</th><th>Matched code</th><th>Matched data</th><th>Linked units</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table><h2>Progress history</h2><table><thead><tr><th>Version</th><th>CI run</th><th>Created UTC</th><th>Code</th><th>Code change</th><th>Data</th><th>Data change</th><th>Linked units</th></tr></thead>
<tbody>{''.join(history)}</tbody></table><p class="note">Percentages come from objdiff report.json. Byte changes compare consecutive archived runs of this branch, which may not be consecutive upstream commits. Version identity comes from CI artifact names and matrix jobs;
objdiff report v2 has no embedded BW1 version. A passing build confirms its checksum gate, not source quality.</p></html>"""
    (output / "index.html").write_text(content, encoding="utf-8")
    return {"repository": repository, "branch": branch, "runs": len(runs), "latest_run": latest["run_id"], "output": str(output)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    sub = parser.add_subparsers(dest="action", required=True)
    for name in ("inspect-run", "ingest-run"):
        cmd = sub.add_parser(name)
        cmd.add_argument("--repo", default="openblack/bw1-decomp")
        cmd.add_argument("--run", type=int, required=True)
        if name == "ingest-run":
            cmd.add_argument("--summary-only", action="store_true", help="store report measures and hashes without raw reports")
            cmd.add_argument("--require-branch", help="reject a run whose source branch differs")
    sync = sub.add_parser("sync-main", help="archive the latest successful main Build run(s)")
    sync.add_argument("--repo", default="openblack/bw1-decomp")
    sync.add_argument("--count", type=int, default=1)
    local = sub.add_parser("ingest-local", help="ingest downloaded CI artifacts with gh run metadata JSON")
    local.add_argument("--repo", required=True)
    local.add_argument("--run", type=int, required=True)
    local.add_argument("--metadata", type=Path, required=True)
    local.add_argument("--reports", type=Path, required=True)
    sub.add_parser("status")
    sub.add_parser("verify", help="validate archived report hashes and measures")
    diff = sub.add_parser("compare")
    diff.add_argument("--repo", default="openblack/bw1-decomp")
    diff.add_argument("--from-run", type=int, required=True)
    diff.add_argument("--to-run", type=int, required=True)
    site = sub.add_parser("render")
    site.add_argument("--repo", default="openblack/bw1-decomp")
    site.add_argument("--branch", default="main", help="branch to show; * includes all archived branches")
    site.add_argument("--output", type=Path, default=ROOT / "site")
    args = parser.parse_args(argv)
    try:
        if args.action == "sync-main":
            repo = validate_repository(args.repo)
            ingested = []
            for run_id in latest_main_runs(repo, args.count):
                meta = inspect_metadata(fetch_metadata(repo, run_id), repo, run_id)
                if not meta["eligible"] or meta["head_branch"] != "main":
                    raise TrackerError(f"Run {run_id} is not a successful main five-version build")
                target = args.data / "runs" / repo.replace("/", "__") / str(run_id)
                if target.exists():
                    if read_json(target / "manifest.json")["head_sha"] != meta["head_sha"]:
                        raise TrackerError(f"Archived run {run_id} has a different SHA")
                    status = "already_archived"
                else:
                    with tempfile.TemporaryDirectory(prefix="bw1-progress-") as temporary:
                        command("gh", "run", "download", str(run_id), "-R", repo,
                                "--pattern", "*_report", "--dir", temporary)
                        status = archive_run(args.data, meta, Path(temporary))["status"]
                ingested.append({"run_id": run_id, "head_sha": meta["head_sha"], "status": status})
            result = {"repository": repo, "branch": "main", "runs": ingested}
        elif args.action in ("inspect-run", "ingest-run", "ingest-local"):
            repo = validate_repository(args.repo)
            if args.run <= 0:
                raise TrackerError("Run ID must be positive")
            raw = read_json(args.metadata) if args.action == "ingest-local" else fetch_metadata(repo, args.run)
            meta = inspect_metadata(raw, repo, args.run)
            if args.action == "inspect-run":
                result = meta
            elif args.action == "ingest-local":
                result = archive_run(args.data, meta, args.reports)
            else:
                if args.require_branch and meta["head_branch"] != args.require_branch:
                    raise TrackerError(f"Run branch {meta['head_branch']!r} is not {args.require_branch!r}")
                with tempfile.TemporaryDirectory(prefix="bw1-progress-") as temporary:
                    command("gh", "run", "download", str(args.run), "-R", repo, "--pattern", "*_report", "--dir", temporary)
                    result = archive_run(args.data, meta, Path(temporary), summary_only=args.summary_only)
            if args.action != "inspect-run":
                result = {"status": result["status"], "repository": repo, "run_id": args.run,
                          "head_sha": meta["head_sha"], "path": result["path"]}
        elif args.action == "status":
            rows = all_manifests(args.data)
            result = {"runs": len(rows), "latest": rows[-1] if rows else None}
            if result["latest"]:
                result["latest"] = {key: result["latest"][key] for key in ("repository", "run_id", "created_at", "head_sha")}
        elif args.action == "verify":
            result = verify_archive(args.data)
        elif args.action == "compare":
            repo = validate_repository(args.repo)
            result = compare_runs(find_manifest(args.data, repo, args.from_run), find_manifest(args.data, repo, args.to_run))
        else:
            result = render(args.data, args.output, validate_repository(args.repo), args.branch)
        print(json.dumps(result, sort_keys=True))
        return 0
    except TrackerError as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
