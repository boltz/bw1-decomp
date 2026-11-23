"""Assess the pinned PrayerSite source with the fork's whole-TU reviewer."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]
PACKET = Path(__file__).resolve().parent
DIMENSIONS = ("naming", "intent", "control_flow", "data_types", "consistency")
MODEL = "gpt-6-luna"


def sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def object_schema(properties):
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def array_schema(items):
    return {"type": "array", "items": items}


def prepare_packet():
    manifest = json.loads((PACKET / "inputs.json").read_bytes())
    system = (PACKET / "rubric.txt").read_bytes().decode()
    assert sha256(system.encode()) == manifest["rubric_sha256"]

    sources = {}
    for name, digest in manifest["source_hashes"].items():
        raw = (ROOT / name).read_bytes()
        pinned = subprocess.check_output(
            ["git", "show", f"{manifest['target_sha']}:{name}"], cwd=ROOT
        )
        assert raw == pinned and sha256(raw) == digest, name
        sources[name] = raw.decode().splitlines()

    inventory = manifest["function_inventory"]
    ids = {function["id"] for function in inventory}
    unit = manifest["unit"]
    assert len(ids) == len(inventory) == 16
    for function in inventory:
        assert function["path"] == unit
        assert 1 <= function["line"] <= len(sources[unit])

    payload = {
        "scope": f"Whole {unit}, all {len(inventory)} definitions and file-scope data. Companion headers provide declaration context.",
        "function_inventory": inventory,
        "files": [
            {"path": name, "numbered_source": "\n".join(f"{i}: {line}" for i, line in enumerate(lines, 1))}
            for name, lines in sources.items()
        ],
    }
    return manifest, system, payload, sources, ids


def grade(manifest, system, payload, sources, expected_ids):
    assert os.environ["GITHUB_REPOSITORY"] == "boltz/bw1-decomp"
    sys.path.insert(0, str(ROOT / "fork-reviewer/tools"))
    import automatic_pr_review as api

    text = {"type": "string"}
    integer = {"type": "integer"}
    api.REVIEW_SCHEMA = object_schema({
        "findings": array_schema(object_schema({
            "path": text,
            "line": integer,
            "severity": {"type": "string", "enum": ["high", "medium", "low"]},
            "problem": text,
            "suggestion": text,
        })),
        "quality": object_schema({
            "dimensions": object_schema({dimension: integer for dimension in DIMENSIONS}),
            "rationale": text,
            "global_data_review": text,
            "uncertainties": array_schema(text),
            "functions": array_schema(object_schema({"id": text, "assessment": text})),
        }),
    })
    api.MAX_RESPONSE_BYTES = 4_000_000
    result = api.call_model(
        os.environ.get("PR_REVIEW_API_BASE", "https://api.openai.com/v1"),
        os.environ["PR_REVIEW_API_KEY"],
        MODEL,
        system,
        json.dumps(payload),
    )
    quality = result["quality"]
    functions = quality["functions"]
    assert {function["id"] for function in functions} == expected_ids
    assert len(functions) == len(expected_ids)
    assert all(function["assessment"].strip() for function in functions)
    assert quality["rationale"].strip() and quality["global_data_review"].strip()
    score_parts = quality["dimensions"]
    assert set(score_parts) == set(DIMENSIONS)
    assert all(type(value) is int and 0 <= value <= 20 for value in score_parts.values())
    for finding in result["findings"]:
        assert finding["path"] in sources and 1 <= finding["line"] <= len(sources[finding["path"]])
    result.update(
        target_sha=manifest["target_sha"],
        source_hashes=manifest["source_hashes"],
        rubric_sha256=manifest["rubric_sha256"],
        model=MODEL,
        score=sum(score_parts.values()),
        reviewed_function_count=len(functions),
        complete_function_inventory=True,
        advisory=True,
    )
    (ROOT / "prayersite-readability.json").write_text(json.dumps(result, indent=2) + "\n")
    print(f"{result['score']}/100 across {len(functions)} definitions at {result['target_sha']}")


if __name__ == "__main__":
    prepared = prepare_packet()
    if sys.argv[1:] == ["--validate-inputs"]:
        print(f"Validated {len(prepared[4])} definitions at {prepared[0]['target_sha']}")
    else:
        assert len(sys.argv) == 1
        grade(*prepared)
