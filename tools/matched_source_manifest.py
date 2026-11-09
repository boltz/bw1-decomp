"""Verify trusted build bundles before selecting matched-contribution readability.

The bundle is produced/approved outside candidate code and pinned by SHA-256.
It records complete logical ownership (not a regex guess), original extents,
all build inputs and exact object hashes. A PR-authored bundle is never accepted
merely because it calls itself verified. This conservative first collector uses
exact relocation identities; renamed equivalent bindings need a separate proof.
"""

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import subprocess

from decomp_binary import Coff, BinaryError, Unresolved
from readability_scope import SCHEMA, aggregate, digest, render, select_scope


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def safe_path(path):
    if (not isinstance(path, str) or not path or "\\" in path or ":" in path
            or PurePosixPath(path).is_absolute() or any(p in ("", ".", "..") for p in path.split("/"))):
        raise ValueError("Unsafe or ambiguous path")
    return path


def git(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args])


def extent(coff, spec):
    """Compare every byte and every relocation, including multiple per instruction.

    Padding is NOT stripped and BSS is NOT read as file bytes. The trusted extent
    gives section index/start/size: names alone cannot define original identity.
    """
    section, start, size = (spec[key] for key in ("section", "start", "size"))
    if any(type(v) is not int for v in (section, start, size)) or start < 0 or size <= 0:
        raise ValueError("Invalid extent")
    code = bytearray(coff.bytes(section, start, size))
    relocations = []
    for relocation in coff.section(section).relocations:
        if not relocation.width:
            continue
        left, right = relocation.offset, relocation.offset + relocation.width
        if left < start + size and right > start:
            if left < start or right > start + size:
                raise Unresolved("Relocation crosses entity boundary")
            symbol = coff.symbols[relocation.symbol_index]
            # Preserve the full decorated identity AND addend. Section-relative
            # targets require a reviewed binding; do not guess from .text names.
            if symbol.storage == 3 or symbol.section == -2:
                raise Unresolved("Section/static relocation requires original binding proof")
            offset = left - start
            relocations.append(dict(offset=offset, type=relocation.type,
                                    symbol=symbol.name, addend=bytes(code[offset:offset + relocation.width]).hex()))
            code[offset:offset + relocation.width] = bytes(relocation.width)
    return dict(size=size, bytes=code.hex(), relocations=sorted(relocations, key=lambda r: r["offset"]))


def collect(plan, repo, artifact_root, revision, tree):
    """Consume a caller-authenticated plan, recheck hashes and Git source ownership.

    The trusted build receipt attests dependency enumeration, clean compilation,
    and candidate completeness. Hash verification cannot establish those facts
    from a bounded objdiff report; absent attestations yield pending evidence.
    """
    result = dict(schema=SCHEMA, revision=revision, tree=tree, verified=False,
                  coverage_complete=False, entities=[], limitations=[])
    required = ("clean_build", "dependencies_complete", "entities_complete", "ownership_reviewed")
    if (plan.get("revision") != revision or plan.get("tree") != tree
            or plan.get("compiled_tree") != tree or not all(plan.get(k) is True for k in required)
            or not plan.get("compiler_sha256") or not plan.get("profile_sha256")
            or not plan.get("inputs") or not isinstance(plan.get("entities"), list)):
        result["limitations"].append("Missing or inconsistent trusted build/coverage receipt")
        return result
    objects, inputs = {}, {}
    for record in plan["inputs"]:
        name = safe_path(record["path"])
        if name in inputs:
            raise ValueError("Duplicate input path")
        if record["kind"] == "source":
            data = git(repo, "show", revision + ":" + name)
        elif record["kind"] in ("object", "reference", "compiler", "profile", "metadata"):
            path = (artifact_root / name).resolve()
            if not path.is_relative_to(artifact_root.resolve()):
                raise ValueError("Artifact path escapes bundle")
            data = path.read_bytes()
        else:
            raise ValueError("Unknown input kind")
        if sha256(data) != record["sha256"]:
            result["limitations"].append(name + ": input hash mismatch")
            return result
        inputs[name] = (record, data)
    if not any(record["kind"] == "metadata" for record, _ in inputs.values()):
        result["limitations"].append("Missing original reference metadata fingerprint")
        return result
    for kind, field in (("compiler", "compiler_sha256"), ("profile", "profile_sha256")):
        if not any(r["kind"] == kind and r["sha256"] == plan[field] for r, _ in inputs.values()):
            result["limitations"].append("Missing " + kind + " fingerprint")
            return result
    seen = set()
    for entity in plan["entities"]:
        key = (entity["identity"], entity["version"])
        if key in seen:
            raise ValueError("Duplicate original identity/version")
        seen.add(key)
        # Identity includes original version/module/address; aliases never supply it.
        if (entity["version"] not in ("BW1W100", "BW1W110", "BW1W120", "BW1W130", "BW1WCI")
                or entity["identity"] != "{}:{}:{:08x}".format(entity["version"], entity["module"], entity["address"])):
            raise ValueError("Original identity is not version/module/address")
        item = dict(identity=entity["identity"], version=entity["version"], logical_id=entity["logical_id"],
                    linked=entity.get("linked", False), match="unverified", ranges=[], ownership_complete=False,
                    reference_sha256="", variant_sha256="", proof_sha256="")
        try:
            variants = []
            for span in entity["ranges"]:
                path = safe_path(span["path"])
                record, data = inputs[path]
                lines = data.decode("utf-8").splitlines(keepends=True)
                if (record["kind"] != "source" or type(span["start"]) is not int or type(span["end"]) is not int
                        or not 1 <= span["start"] <= span["end"] <= len(lines)):
                    raise ValueError("Invalid source ownership range")
                text = "".join(lines[span["start"] - 1:span["end"]])
                if span["role"] not in ("definition", "support"):
                    raise ValueError("Unknown scored ownership role")
                item["ranges"].append(dict(path=path, start=span["start"], end=span["end"],
                                           role=span["role"], text=text))
                # No line numbers or unrelated source bodies in the variant hash.
                variants.append(dict(path=path, role=span["role"], text=text))
            if not any(r["role"] == "definition" for r in item["ranges"]):
                raise ValueError("Missing complete logical definition")
            item["variant_sha256"] = digest(dict(ranges=variants, context=entity["context_sha256"]))
            proofs = []
            for part in entity["parts"]:
                pair = []
                for side, kind in (("reference", "reference"), ("candidate", "object")):
                    spec = part[side]
                    record, data = inputs[spec["path"]]
                    if record["kind"] != kind:
                        raise ValueError("Wrong binary input kind")
                    if spec["path"] not in objects:
                        objects[spec["path"]] = Coff(data)
                    pair.append(extent(objects[spec["path"]], spec))
                proofs.append(dict(reference=pair[0], candidate=pair[1]))
            if not proofs:
                raise ValueError("No binary parts for logical entity")
            item["reference_sha256"] = digest([
                dict(extent=part["reference"], input_sha256=inputs[part["reference"]["path"]][0]["sha256"])
                for part in entity["parts"]])
            item["proof_sha256"] = digest(proofs)
            item["match"] = "matched" if all(p["reference"] == p["candidate"] for p in proofs) else "unmatched"
            item["ownership_complete"] = entity.get("ownership_complete") is True
        except (ValueError, KeyError, BinaryError, Unresolved, UnicodeError) as error:
            item["reason"] = str(error)
        result["entities"].append(item)
    result["verified"] = True
    result["coverage_complete"] = True
    result["receipt_sha256"] = digest(plan)
    result["compiler_sha256"] = plan["compiler_sha256"]
    result["profile_sha256"] = plan["profile_sha256"]
    result["input_hashes"] = [{k: record[k] for k in ("path", "kind", "sha256")} for record, _ in inputs.values()]
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", required=True)
    parser.add_argument("--bundle", type=Path, help="Trusted build receipt JSON, not a PR artifact")
    parser.add_argument("--trusted-bundle-sha256", help="Independent trust-root pin; never read from candidate code")
    parser.add_argument("--artifact-root", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    expected = {}
    for name in ("base", "head"):
        value = git(args.repo, "rev-parse", "--verify", "--end-of-options", getattr(args, name) + "^{commit}").decode().strip()
        expected[name] = value
        expected[name + "_tree"] = git(args.repo, "rev-parse", value + "^{tree}").decode().strip()
    base = head = None
    if args.bundle:
        raw = args.bundle.read_bytes()
        if not args.trusted_bundle_sha256 or sha256(raw) != args.trusted_bundle_sha256 or not args.artifact_root:
            parser.error("Bundle requires independently trusted SHA-256 and artifact root")
        bundle = json.loads(raw)
        base = collect(bundle["base"], args.repo, args.artifact_root, expected["base"], expected["base_tree"])
        head = collect(bundle["head"], args.repo, args.artifact_root, expected["head"], expected["head_tree"])
    scope = select_scope(base, head, expected)
    output = dict(scope=scope, review=aggregate(scope, []))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    print(render(output["review"]), end="")


if __name__ == "__main__":
    main()
