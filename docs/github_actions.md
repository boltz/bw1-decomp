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

`automatic-review.yml` runs after the Build workflow completes and reviews ready PRs with the upstream `AGENTS.md` as its
source guide. It reads patches through the GitHub API and checks out only the
trusted revision that supplied the workflow; it never checks out or runs PR
code. Review text is sent to the configured OpenAI-compatible API, so enable it
only if that provider may receive repository diffs.

The reviewer instructions are in `tools/automatic_pr_review_instructions.md`.
The job supplies changed source files, matching configure entries, base-source
method-name matches as caller candidates, and the check-run states available
when review starts. Each version build also uploads a `binary-evidence-*`
artifact with strict object comparison summaries and bounded disassembly for
changed source units. Header changes select all units, with an explicit eight-unit
limit. Output truncation and failed comparisons are recorded. Artifacts identify
the PR base, head, and actual compiled checkout (normally the PR merge commit).
The review reads these artifacts as untrusted data and validates their PR revision
identities. Missing versions, stale artifacts, or truncated evidence prevent an
automatic approval. No game executables or object files are uploaded.

The review workflow uses trusted default-branch code and never executes artifact
contents or PR code with the review credentials. Closed, draft, and superseded
PRs are skipped. These workflow changes must be present on the fork's default
branch before they can handle Build completion events.

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

The workflow submits a formal review as `github-actions[bot]`. It requests
changes for high- or medium-severity correctness defects, approves only a
complete review with no findings, and leaves limited reviews or non-blocking
findings as comments. GitHub cannot assign the Actions bot as a requested
reviewer. Approvals require **Allow GitHub Actions to create and approve pull
requests** under Settings > Actions > General. This setting applies to all
workflows in the repository. Review text goes to the configured model provider,
and maintainers still own the merge decision.


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
