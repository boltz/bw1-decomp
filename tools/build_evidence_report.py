#!/usr/bin/env python3
"""Post a deterministic build report independently of the source review."""

from datetime import datetime
import os
import sys
from zoneinfo import ZoneInfo

try:
    from .automatic_pr_review import GitHub, ReviewError, load_binary_evidence, safe_markdown
except ImportError:
    from automatic_pr_review import GitHub, ReviewError, load_binary_evidence, safe_markdown


MARKER = "<!-- bw1-build-evidence -->"
VERSIONS = ("BW1W100", "BW1W110", "BW1W120", "BW1W130", "BW1WCI")


def render_report(repository, head_sha, run, jobs, evidence, limited):
    stamp = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d %I:%M:%S %p %Z")
    run_id = int(run["id"])
    lines = [
        MARKER, "Reported: {} (Eastern Time)".format(stamp), "",
        "## Build and binary evidence", "",
        "Commit `{}`. [Build run](https://github.com/{}/actions/runs/{}): {}.".format(
            head_sha[:12], repository, run_id, safe_markdown(run.get("conclusion") or "unfinished")
        ), "", "### Build results", "", "| Check | Result |", "| --- | --- |",
    ]
    for job in jobs:
        lines.append("| {} | {} |".format(
            safe_markdown(str(job.get("name", "unknown"))),
            safe_markdown(str(job.get("conclusion") or job.get("status", "unknown"))),
        ))
    if not jobs:
        lines.append("| Job results | unavailable |")
    if run.get("conclusion") != "success":
        lines += ["", "The build did not succeed. Open the build run for the failed or cancelled checks."]
    lines += ["", "### Binary evidence coverage", ""]
    by_version = {item["version"]: item for item in evidence}
    for version in VERSIONS:
        item = by_version.get(version)
        if item is None:
            lines += ["- {}: no usable artifact for this PR head and base.".format(version)]
            continue
        units = item.get("units", [])
        lines += ["- {}: {} unit summaries supplied.".format(version, len(units))]
        for reason in item.get("limitations", [])[:20]:
            reason = str(reason)
            if "Function not found" in reason:
                reason = reason.split(" disassembly failed:")[0] + ": no function listing; this may be a data-only unit."
            lines += ["  - " + safe_markdown(reason)]
        if len(item.get("limitations", [])) > 20:
            lines += ["  - More limitations are listed in the build artifacts."]
    if limited:
        lines += ["", "Coverage is limited. This is a limit of the supplied binary evidence, not a missing readability result."]
    lines += [
        "", "### What this proves", "",
        "Build success means the configured checks passed. Consult the build log for executable hash results. "
        "It does not prove that a NonMatching source was linked, that every object matches, or that runtime behavior is correct.",
        "", "The source readability review is separate. This report does not approve or merge the PR.",
    ]
    body = "\n".join(lines)
    if len(body) > 58_000:
        body = body[:57_500] + "\n\nReport truncated. Consult the Build artifacts for the remaining evidence limits."
    return body


def main():
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    number = os.environ.get("PR_NUMBER", "")
    run_id = os.environ.get("BUILD_RUN_ID", "")
    expected_sha = os.environ.get("PR_REVIEW_EXPECTED_SHA", "")
    token = os.environ.get("GITHUB_TOKEN", "")
    if repository != "boltz/bw1-decomp" or not number.isdigit() or not run_id.isdigit() or not expected_sha or not token:
        raise ReviewError("Missing or invalid build-report repository, PR, run, head, or token")
    github = GitHub(repository, token)
    pr_path = "/repos/{}/pulls/{}".format(repository, number)
    pr = github.request("GET", pr_path)
    if pr.get("state") != "open" or pr.get("draft") or pr["head"]["sha"] != expected_sha:
        print("Skipping closed, draft, or superseded build report")
        return
    run = github.request("GET", "/repos/{}/actions/runs/{}".format(repository, run_id))
    if (run.get("event") != "pull_request" or run.get("status") != "completed"
            or run.get("head_sha") != expected_sha
            or run.get("head_repository", {}).get("full_name") != repository):
        raise ReviewError("Build run does not match the expected completed same-repository PR build")
    jobs, page = [], 1
    while True:
        result = github.request("GET", "/repos/{}/actions/runs/{}/jobs?per_page=100&page={}".format(repository, run_id, page))
        rows = result.get("jobs", [])
        jobs.extend(rows)
        if len(rows) < 100:
            break
        page += 1
    evidence, limited = load_binary_evidence(pr)
    body = render_report(repository, expected_sha, run, jobs, evidence, limited)
    comments, page = [], 1
    while True:
        rows = github.request("GET", "/repos/{}/issues/{}/comments?per_page=100&page={}".format(repository, number, page))
        comments.extend(rows)
        if len(rows) < 100:
            break
        page += 1
    current = github.request("GET", pr_path)
    if current.get("state") != "open" or current["head"]["sha"] != expected_sha or current["base"]["sha"] != pr["base"]["sha"]:
        print("Skipping superseded build report")
        return
    run_link = "https://github.com/{}/actions/runs/{}".format(repository, run_id)
    previous = next((c for c in comments if c.get("user", {}).get("login") == "github-actions[bot]"
                     and MARKER in c.get("body", "") and run_link in c.get("body", "")), None)
    if previous:
        github.request("PATCH", "/repos/{}/issues/comments/{}".format(repository, previous["id"]), {"body": body})
    else:
        github.request("POST", "/repos/{}/issues/{}/comments".format(repository, number), {"body": body})


if __name__ == "__main__":
    try:
        main()
    except ReviewError as error:
        print("build evidence report failed: {}".format(error), file=sys.stderr)
        sys.exit(1)
