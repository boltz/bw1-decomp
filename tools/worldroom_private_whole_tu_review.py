"""Run the pinned fork grader with private input and an encrypted result artifact."""

import ast
import base64
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import zlib

import automatic_pr_review as api


RUBRIC = "12ec1e2e6fbcbf3d0495009a6f6e4fe5258119e53940940c49d3a06d05121197"
MODEL = "gpt-6-luna"


def assess(envelope):
    assert os.environ["GITHUB_REPOSITORY"] == "boltz/bw1-decomp"
    packet = envelope["packet"]
    original = Path("tools/worldroom_whole_tu_review.py").read_text()
    # Reuse the original schema and transport without running its public-source loader.
    scope = {}
    exec(original.split("\nrepository = ")[0], scope)
    original_rubric = next(
        ast.literal_eval(node.value)
        for node in ast.parse(original).body
        if isinstance(node, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "system" for t in node.targets)
    )
    assert packet["system"] == original_rubric
    assert hashlib.sha256(packet["system"].encode()).hexdigest() == RUBRIC
    assert packet["rubric_sha256"] == RUBRIC
    assert packet["model"] == os.environ["PR_REVIEW_MODEL"] == MODEL
    payload = packet["user_payload"]
    inventory = payload["function_inventory"]
    expected = [f["id"] for f in inventory]
    assert len(expected) == len(set(expected)) == envelope["inputs"]["definitions"] >= 50
    assert os.environ["PR_REVIEW_API_KEY"]
    result = api.call_model(
        os.environ.get("PR_REVIEW_API_BASE", "https://api.openai.com/v1"),
        os.environ["PR_REVIEW_API_KEY"], MODEL,
        packet["system"], json.dumps(payload),
    )
    q = result["quality"]
    actual = [f["id"] for f in q["functions"]]
    assert len(actual) == len(set(actual)) and set(actual) == set(expected)
    dimensions = ("naming", "intent", "control_flow", "data_types", "consistency")
    assert set(q["dimensions"]) == set(dimensions)
    assert all(type(q["dimensions"][d]) is int and 0 <= q["dimensions"][d] <= 20 for d in dimensions)
    lengths = {f["path"]: max(int(line.split(":", 1)[0]) for line in f["numbered_source"].splitlines()) for f in payload["files"]}
    for finding in result["findings"]:
        assert finding["path"] in lengths and 1 <= finding["line"] <= lengths[finding["path"]]
    result.update(
        model=MODEL, rubric_sha256=RUBRIC,
        score=sum(q["dimensions"].values()),
        reviewed_function_count=len(actual), complete_function_inventory=True,
        source_hashes=envelope["inputs"]["source_hashes"],
        source_snapshot_sha256=envelope["inputs"]["source_snapshot_sha256"],
        private_delivery=True,
        grader_reference="410ee18dd6db63488ad243f5c5da19246ae42c29",
        original_grader_sha256=hashlib.sha256(original.encode()).hexdigest(),
        request_id=envelope["request_id"],
    )
    return {"success": True, "review": result, "inputs": envelope["inputs"]}


def main():
    result = None
    try:
        # Captured diagnostics and exception details are encrypted with the result.
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            encoded = os.environ["WORLDROOM_PACKET_A"] + os.environ["WORLDROOM_PACKET_B"] + os.environ.get("WORLDROOM_PACKET_C", "")
            raw = zlib.decompress(base64.b64decode(encoded, validate=True))
            assert hashlib.sha256(raw).hexdigest() == os.environ["WORLDROOM_ENVELOPE_SHA256"]
            result = assess(json.loads(raw))
    except Exception as error:
        result = {"success": False, "error_type": type(error).__name__, "error": str(error)}
    with tempfile.TemporaryDirectory() as directory:
        plaintext = Path(directory) / "result.json"
        plaintext.write_text(json.dumps(result, indent=2) + "\n")
        output = Path("private-review-result.p7m")
        completed = subprocess.run([
            "openssl", "cms", "-encrypt", "-binary", "-aes-256-gcm", "-outform", "DER",
            "-in", str(plaintext), "-out", str(output), "tools/worldroom_review_recipient.pem",
        ], capture_output=True)
        assert completed.returncode == 0, "Result encryption failed; no plaintext artifact is uploaded"
    print("Private review attempt finished; encrypted result prepared.")
    return 0 if result["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
