# Matched-contribution readability

Readability acceptance applies to complete matched source contributions, not the
percentage of the TU recovered. Unmatched bodies cannot reduce this score. Binary
regressions, correctness, source authenticity and executable hash checks remain
independent requirements. The existing five 0–20 dimensions are unchanged.

`matched_source_manifest.py` verifies a trusted, independently pinned build receipt
against Git blobs and raw i386 COFF artifacts. It compares full bytes and **all**
relocation fields, identities and addends; it never parses a rounded objdiff score.
It preserves exact extents and rejects unresolved static/section bindings. It does
not claim equivalent renamed relocations without an additional reviewed proof.

`readability_scope.py` selects newly matched entities, edited existing matches and
link promotions per version. It protects base matches separately, folds supporting
declarations/data into parent items, and groups identical source/context variants.
Only complete eligible source ranges reach the model. Each logical entity/variant
gets one vote; hundreds of constants do not inflate the denominator. The report
shows the mean, minimum, reviewed/eligible counts, exclusions and regressions.
An omitted item or uncertain evidence gives **pending, no aggregate score**.
Verified zero eligible contributions gives **N/A**, never 100 or zero.

`matched_readability_review.py` uses the existing quality schema, numeric inventory
and validators one complete item at a time. It does not retry to improve a score.
Oversize items remain pending rather than being truncated. Review observations
outside the item's ranges are rejected. Numeric checks cover complete eligible
bodies; comment-removal checks retain their added/edited ownership rule.

## Dry run

Run trusted tooling against a source repository containing both revisions:

```sh
python tools/matched_readability_review.py --repo /path/to/source \
  --base FULL_BASE_SHA --head FULL_HEAD_SHA --output matched-readability.json
```

Without a trusted receipt the result is pending. This is deliberate: the existing
`binary-evidence-*` artifacts are bounded summaries and cannot supply eligibility.
The frozen PR #24 dry run produces pending/N/A for this reason. Its old whole-TU
60 and changed-line 77 are diagnostics of different populations, not baselines for
this metric. No corrected score can be inferred from them.

## Trusted receipt contract and current rollout boundary

The receipt JSON has `base` and `head` objects. Each contains `revision`, `tree`,
`compiled_tree`, compiler/profile SHA-256 values, `inputs`, and complete `entities`.
Every input has `path`, `kind` and `sha256`. Source inputs are read from the pinned
Git revision; object/reference/compiler/profile/metadata inputs come from the raw
artifact bundle. Paths are relative and traversal is forbidden.

Every entity has version/module/original address identity, a stable `logical_id`,
`linked`, a context hash, complete definition/support `ranges`, and all associated
binary `parts`. Each part specifies reference/candidate path, section index, start
and size, plus a reviewed `bindings` map keyed by COFF symbol index. Each binding
pins the actual symbol record (`name`, `section`, `value`, `storage`, `type`) to
its original version/module/address identity. Equal reconstructed symbol names
alone do not establish equal original bindings. Missing bindings remain unverified.
Compiler-generated helpers belong in their source entity's parts, not as
separate readability items. Standalone matched data gets a logical data entity.
Ranges include signatures, constructor initializers, conditional branches and
required supporting headers. Duplicate filenames must use full repository paths.
Overloads are identified by original address, never substring or basename matching.

The receipt also attests `clean_build`, `dependencies_complete`, `entities_complete`
and `ownership_reviewed`. These are **trusted producer assertions**, not facts that
a JSON flag or SHA-256 establishes. The complete dependency and logical-ownership
catalog must be independently established. Current COFF `.file`/`.bf` coordinates
are useful mapping evidence but are not yet a validated automatic C++ range and
dependency resolver. This release does not pretend that such a resolver exists.
Missing coverage must remain pending; do not set these flags just to obtain a score.

The SHA-256 pin must come from an independent approval of that complete receipt,
not from candidate code, a PR-authored manifest, or the artifact itself. Hashes
detect alteration; they do not authenticate a producer. Automatic acceptance of
candidate-authored `verified: true` JSON is expressly unsupported.

With that receipt, add:

```sh
--bundle /trusted/receipt.json --trusted-bundle-sha256 INDEPENDENT_PIN \
--artifact-root /trusted/artifacts --run-model
```

The manual `Matched contribution readability` workflow runs trusted main tooling,
validates a successful same-repository Build for the specified head, and consumes
only an independently approved `matched-source-bundle` artifact. Candidate scripts
are never run with reviewer credentials. Without a receipt it is a no-model dry
run. The standard Build does not yet produce a complete, independently trusted
ownership catalog, so unattended matched-score publication remains disabled.
The normal post-Build report explicitly reports that missing evidence as pending.
Early changed-line reviews remain advisory and cannot serve as this acceptance
metric. No source TU status or all-five-version requirement is used as a ceiling.

## Validation

```sh
python -m unittest discover -s tools/tests -p 'test_*readability*.py'
python -m unittest discover -s tools/tests -p test_matched_source_manifest.py
```

Fixtures cover mixed matched/unmatched code, partial-TU 100, zero eligible N/A,
metadata-only promotions, regression protection, per-version grouping, support
folding, missing reviews, stale evidence, forged/unpinned bundles and the H136
missing-secondary-relocation case. Full automatic ownership mapping across all
MSVC6 language constructs and build versions remains a prerequisite for removing
the independent receipt-approval step, not something these fixtures claim to prove.
