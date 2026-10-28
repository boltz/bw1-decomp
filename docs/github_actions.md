# GitHub Actions

[`.github/workflows/build.yml`](/.github/workflows/build.yml) runs on every push and pull request. For each version in the matrix it:

1. Pulls the private container `ghcr.io/openblack/bw1-build:main`, which carries the original game binaries under `/orig/<VERSION>/` (for BW1WCI, `CreatureIsle-decrypted.exe` and its four DLLs).
2. Copies `/orig` into the workspace.
3. Runs `configure.py --version <VERSION>`, then `ninja all_source progress build/<VERSION>/report.json`.
4. Uploads `report.json` as a build artifact for [decomp.dev](https://decomp.dev) to consume.

The container is built and pushed by [openblack/bw1-build](https://github.com/openblack/bw1-build) (private — contains game assets). Its package settings grant this repo's Actions runner the **Read** role so the workflow can pull it.

## decomp.dev

Progress is tracked at <https://decomp.dev/openblack/bw1-decomp>. The badge URLs in the root README pull from there.

## Personal fork CI

`boltz/bw1-decomp` uses its own private build image from `boltz/bw1-build`.
Set the fork's `BW1_BUILD_IMAGE` Actions variable to the published image digest,
for example `ghcr.io/boltz/bw1-build@sha256:<digest>`. Without this variable,
the workflow uses upstream's image.

The private package must grant the fork Read under Manage Actions access.
The workflow authenticates with its repository's `GITHUB_TOKEN` and requests
`packages: read`. No personal access token is stored in the fork.

Open experiment PRs with `boltz/bw1-decomp:main` as the base. Each PR runs the
same five-version build commands and uploads the same map/report artifacts as
upstream. The lint workflow also runs clang-format 22 and address-comment checks.
Manual builds are available through the Build workflow's Run workflow button.

Build jobs run only for branches in the same repository, pushes to `main`, and
manual runs. PRs from another fork run lint but skip the private-input build.
To test an external contribution, review it and bring it onto a branch in the
personal fork first. Do not use `pull_request_target` to build PR code.

The image recipe and original-input release remain in the private build repository.
Only maps and progress reports are uploaded by this workflow. Its normal link still
uses extracted objects for `NonMatching` units, even though `all_source` compiles them.
The upstream decomp.dev page and bot are separate from this fork's Actions setup.

## Automatic PR review

`automatic-review.yml` starts a readability review when a same-repository PR is
opened, updated, reopened, or marked ready. It runs alongside Build, without a
build dependency. It uses `pull_request_target` only to run trusted default-branch
reviewer code; PR source is read through the GitHub API and is never checked out
or executed with review credentials. The upstream `AGENTS.md` remains the source
guide. Review text is sent to the configured model provider, so enable it only
if that provider may receive repository diffs.

The readability phase supplies source, matching configure entries, caller
candidates, and RepoScout excerpts. Build checks and binary artifacts are outside
this phase, so their absence does not count as missing readability evidence.
Supported blocking source findings can request changes. Otherwise the bot posts a
comment review; it never issues a formal approval or claims the PR is ready to
merge. The existing numeric, comment, and readability scorecard still applies.

`build-evidence-report.yml` runs separately after Build completes, including failed
builds. It posts a deterministic PR comment with the Build job results and the
exact binary evidence limitations for each version. It uses no model credentials,
does not change the readability score, and cannot approve or merge a PR. Rerunning
the same Build run updates that run's report instead of adding another comment.
Reports for a closed, draft, or superseded PR are skipped.

Each version uploads a `binary-evidence-*` artifact containing strict object
comparison summaries and bounded disassembly. Header changes select all units,
subject to an eight-unit evidence limit. Reports name unit caps, truncated listings,
missing/stale artifacts, and units with no function listing. Artifacts are checked
against both PR revisions and remain untrusted data. Limited binary coverage is
reported separately from failed builds or incomplete source reviews. No game
executables or object files are uploaded. Both reporting workflows must be merged
to the default branch to become active.

RepoScout uses `tools/reposcout.py`, the existing standalone Python/SQLite
retriever also used by the local OpenCode workflow. The RepoScout index workflow
refreshes public upstream merged-PR discussions daily, manually, and when its
code changes on `main`. It uploads an index artifact retained for 30 days.
The review downloads the latest successful default-branch index and runs bounded
lexical searches for up to eight changed source-file stems. It supplies cited
excerpts and the index sync date to the model. The scheduled index omits changed-file
records to reduce API requests; it retains PR descriptions and review discussions.
No results, stale index dates, expired artifacts, and failed retrieval must be
reported honestly. A maintainer discussion is precedent, not a binding rule.

This automation does not run Codex or OpenCode. Installing a skill locally does
not make its tools or data available to the hosted review job. The Python retriever
can also be invoked locally from either agent; it needs no agent-specific rewrite.

Binary evidence collection and map/report uploads run even when a preceding build
step fails, unless the workflow is cancelled. This preserves usable object evidence
when compilation succeeds but the final executable hash check fails. Actual compile
failures can still leave evidence unavailable; the failed build remains a failed
check. Changed source units are selected before the bounded list of potential
header consumers.

Set the Actions variable `AI_PR_REVIEW_ENABLED` to `true` and the secret
`PR_REVIEW_API_KEY` to an OpenAI API key. The workflow defaults to `gpt-6-luna`;
override it with the `PR_REVIEW_MODEL` variable if needed. `PR_REVIEW_API_BASE`
defaults to `https://api.openai.com/v1`; a custom endpoint must support the
OpenAI Responses API.

The readability workflow submits a formal comment or request-changes review as
`github-actions[bot]`. GitHub cannot assign the Actions bot as a requested reviewer.
Build evidence is posted separately as an ordinary PR comment. Neither workflow
merges code or posts an approval; maintainers own the merge decision.


Every personal-fork review begins with a human-readability scorecard: confirmed
magic-number occurrences, unresolved numeric candidates, added/edited comment
counts (including exempt annotations), and a readability score out of 100.
Readability is the first review priority. Naming, intent, control flow, data types,
and consistency each contribute up to 20 points. The score is an advisory model
assessment, supported by concrete changed-code examples; missing evidence yields
an unavailable or provisional score rather than a fabricated clean result.
Documentation-only changes have no assessable code score.

The report separates readable portions, requested changes, magic numbers and
justifications, comment removals, and RepoScout precedents. Source locations link
to the reviewed commit. Matching and binary evidence sit in expandable sections.
The early-2000s Lionhead/MSVC 6.0 explanation is an evidence-based inference, never
a claim to know the original author's intent. Precedents quote actual indexed
discussions with the author's relationship and formal review state when available;
a merged PR alone does not establish acceptance of a particular coding pattern.

Numeric token inventories cover added lines of owned C/C++, Python tooling, and
GitHub YAML scalar values. Strings, Python docstrings, embedded YAML scripts,
documentation and vendored sources are outside this token inventory. Numeric
literals require contextual classification as magic, justified, or uncertain;
zero literals alone is not the only way to pass. The model must classify every
supplied occurrence exactly once. Caps, missing context, and uncertain judgments
are visible and prevent a claim that the audit was complete.

The Boltz-only added-comment lint compares base/head comment inventories so
unchanged or moved comments are not treated as new merely because nearby code
changed. It requests removal of added or edited prose comments while preserving
required address/inliner annotations, initializer formatting, format directives,
and interpreter/encoding directives. Missing base evidence fails the comment
check rather than guessing. New prose comments and confirmed actionable readability
issues request changes even when binary evidence is incomplete. Complete
inventories and the validated scorecard are uploaded as workflow artifacts.
The trusted automatic-review workflow uses these changes after they merge to main.

Every review starts with an Eastern Time timestamp and a `Changes requested`
checklist before the scorecard. Each item identifies the file and line, the exact
edit, and its reason. Optional style preferences and unconfirmed concerns appear
under `Optional suggestions` and `Needs investigation`, respectively. Readability,
magic-number, and comment-removal requests all feed the checklist. An incomplete
review with no validated edits says so explicitly; it does not imply approval.
The model must put each proposed edit in a structured finding and name the exact
identifiers involved, rather than burying a request in its summary.


Review prose follows the TimVoice rules in
`tools/automatic_pr_review_voice.md`. The model receives this file as trusted
writing instructions on every run. A missing guide stops the review. The guide
requires a high-school reading level (grades 9-10), a direct request followed by
its reason, and plain explanations of compiler terms. It applies to every prose
field and requires a separate writing pass before returning the structured
review. Exact code names, quoted reviewer text, scores and evidence stay intact.
The bot still identifies itself as automated. This is a writing requirement;
there is no automatic certification of the generated prose's reading level.

The writing guide is included in the repo so GitHub Actions can use it without
access to Tim's local OpenCode skills. It contains the applicable writing rules,
not his personal correspondence. The report template uses plain labels and keeps
score details, required-comment locations, and long lists of missing files in
expandable sections. The score, counts, review limits, and requested fixes remain
visible. Changing the process does not edit previously posted reviews.


Source collection and diff selection put changed owned C/C++ files first, then
workflow/tooling code, then configure.py, then other files such as symbol records.
A large configuration file cannot consume the review budget before game code is
read. The bounded source allowance is 400,000 characters across 40 files; patches
have a 192,000-character total allowance and a 64,000-character per-file cap.
The numeric inventory holds up to 1,024 occurrences, and model output has a
20,000-token allowance for their classifications and findings. These limits cover
PR #19's 11 source files and 349 numeric occurrences. Larger changes still report
incomplete coverage instead of claiming that an unfinished audit passed.


The owner excludes configure.py and Python files under tools/ and .claude/skills/
from PR review, including Python tests. The automatic reviewer filters these paths
before fetching source, forming diffs, counting tokens or selecting finding
locations. The added-comment PR lint uses the same exclusion. Python-only PRs in
these excluded paths skip the review; they do not receive an empty approval.
Existing configure entries can still supply linkage facts for changed C++ files.
The exclusion does not prevent necessary edits or tests of the Python tooling.
