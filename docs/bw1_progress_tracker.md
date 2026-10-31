# BW1 progress history on the fork

`.github/workflows/bw1-progress.yml` archives successful five-version `main` Build runs on `boltz/bw1-decomp` and publishes a static progress page with badges through GitHub Pages. It runs after Build completes or by manual dispatch with a Build run ID. The workflow is guarded to this fork and does not send anything to upstream.

The tracker source is `tools/bw1_progress_tracker.py`. It reads the five `*_report` artifacts produced by the Build workflow. It accepts a run only when GitHub reports overall success, each version's build job succeeded, and the run belongs to `main`. Build's `progress` target depends on the executable checksum gate. Objdiff reports provide code, data, and linked-unit measures; the tracker does not recompute matching.

The `progress-data` branch holds one immutable compact manifest per run and the generated `site/`. Each manifest contains the run URL, commit SHA, report SHA-256 hashes, and objdiff measures. Raw reports remain in the Build artifacts and in any separate local full archive. The compact manifests keep Git history small; after CI artifacts expire, the branch can still show the progress figures but cannot rehash the original report bytes. `verify` checks compact manifest structure, while a local full archive checks the actual files.

The page is deployed at `https://boltz.github.io/bw1-decomp/` once GitHub Pages is configured for **GitHub Actions**. The workflow needs `actions: read` to fetch Build artifacts, `contents: write` to update `progress-data`, and `pages: write` plus `id-token: write` to deploy. The data-branch push does not trigger Build, which runs only on `main` pushes and pull requests.

The workflow never downloads or publishes original game binaries. A match percentage is not a claim about readability or game quality. Failed or partial Build runs are excluded from the successful progress history.
