"""Deterministic matched-contribution selection and per-entity score aggregation.

This module consumes evidence produced by a TRUSTED collector. JSON supplied by a
pull request is not a trust root. Missing coverage never falls back to whole-file
or changed-line scoring. The caller must authenticate the producing workflow and
verify the input bundle before calling select_scope.
"""

from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json

from readability_review import DIMENSIONS, MIN_READABLE_SCORE

SCHEMA = 1


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def select_scope(base, head, expected):
    """Join complete, verified snapshots, preserving losses independently of scores.

    Each entity is a logical source definition (including its supporting ranges),
    identified independently of its symbol spelling. Per-version evidence records
    are grouped only when their complete source/context variant hashes agree.
    """
    result = dict(schema=SCHEMA, metric="matched-contribution-readability", base=expected["base"],
                  head=expected["head"], eligible=[], excluded=[], unverified=[], regressions=[], provenance={})
    for name, snapshot in (("base", base), ("head", head)):
        if snapshot is None:
            result["unverified"].append(name + ": verified snapshot unavailable")
            continue
        result["provenance"][name] = {key: snapshot.get(key) for key in
            ("revision", "tree", "receipt_sha256", "compiler_sha256", "profile_sha256", "input_hashes")}
        if (snapshot.get("schema") != SCHEMA or snapshot.get("revision") != expected[name]
                or snapshot.get("verified") is not True or snapshot.get("coverage_complete") is not True
                or snapshot.get("tree") != expected[name + "_tree"]):
            result["unverified"].append(dict(side=name, reason="Stale, incomplete, or unverified snapshot",
                                             limitations=snapshot.get("limitations", [])))
    if result["unverified"]:
        result["status"] = "pending"
        result["scope_sha256"] = digest(result)
        return result
    def index(snapshot):
        entries = {}
        for entity in snapshot["entities"]:
            key = (entity["identity"], entity["version"])
            if key in entries:
                raise ValueError("Duplicate original identity/version")
            entries[key] = entity
        return entries
    before, after = index(base), index(head)
    grouped = {}
    for key in sorted(set(before) | set(after)):
        old, new = before.get(key), after.get(key)
        label = {"identity": key[0], "version": key[1]}
        if old and old["match"] == "matched":
            if not new or new["match"] == "unverified":
                result["unverified"].append(dict(label, reason="Prior match has no verified head evidence"))
            elif new["match"] != "matched":
                result["regressions"].append(dict(label, reason="Prior exact match lost"))
        if not new:
            if not old or old["match"] != "matched":
                result["unverified"].append(dict(label, reason="Original entity absent from head inventory"))
            continue
        if old and old["reference_sha256"] != new["reference_sha256"]:
            result["unverified"].append(dict(label, reason="Original reference changed; reconciliation required"))
            continue
        if new["match"] == "unverified":
            result["unverified"].append(dict(label, reason=new.get("reason", "Evidence incomplete")))
            continue
        if new["match"] != "matched":
            result["excluded"].append(dict(label, reason="Unmatched implementation"))
            continue
        contributed = (not old or old["match"] != "matched" or old["variant_sha256"] != new["variant_sha256"]
                       or (new.get("linked") and not old.get("linked")))
        if not contributed:
            result["excluded"].append(dict(label, reason="Unchanged existing match"))
            continue
        if not new.get("ranges") or not new.get("ownership_complete"):
            result["unverified"].append(dict(label, reason="Complete source/support ownership unavailable"))
            continue
        group = (new["logical_id"], new["variant_sha256"])
        if group not in grouped:
            grouped[group] = dict(id=digest(group), logical_id=new["logical_id"],
                                  variant_sha256=new["variant_sha256"], ranges=new["ranges"], versions=[])
        elif grouped[group]["ranges"] != new["ranges"]:
            result["unverified"].append(dict(label, reason="Variant has conflicting ownership"))
            continue
        grouped[group]["versions"].append(dict(label, proof_sha256=new["proof_sha256"]))
    result["eligible"] = [grouped[key] for key in sorted(grouped)]
    result["status"] = "pending" if result["unverified"] else "ready" if grouped else "not_applicable"
    result["scope_sha256"] = digest(result)
    return result


def scored_lines(item):
    lines = {}
    for span in item["ranges"]:
        lines.setdefault(span["path"], set()).update(range(span["start"], span["end"] + 1))
    return lines


def aggregate(scope, reviews):
    """One equally weighted vote per logical source variant, never per define/helper.

    No score is published for incomplete/invalid coverage. Findings must cite a
    scored range of their own item; context-only observations cannot deduct points.
    """
    expected = {item["id"]: item for item in scope["eligible"]}
    valid, errors, blocking = {}, [], []
    for review in reviews:
        if not isinstance(review, dict):
            errors.append("Reviewed item must be an object")
            continue
        identifier = review.get("id")
        if not isinstance(identifier, str) or identifier not in expected or identifier in valid:
            errors.append("Unknown or duplicate reviewed item: " + str(identifier))
            continue
        item = expected[identifier]
        if review.get("variant_sha256") != item["variant_sha256"]:
            errors.append(identifier + ": stale source variant")
            continue
        dimensions = review.get("dimensions")
        if (not isinstance(dimensions, dict) or set(dimensions) != set(DIMENSIONS)
                or any(type(value) is not int or not 0 <= value <= 20 for value in dimensions.values())
                or not isinstance(review.get("rationale"), str) or not review["rationale"].strip()):
            errors.append(identifier + ": invalid dimensions/rationale")
            continue
        allowed = scored_lines(item)
        observations = review.get("observations")
        if not isinstance(observations, list) or not observations:
            errors.append(identifier + ": concrete source observations required")
            continue
        malformed = False
        for observation in observations:
            if (not isinstance(observation, dict) or type(observation.get("line")) is not int
                    or not isinstance(observation.get("path"), str)
                    or observation["line"] not in allowed.get(observation.get("path"), set())
                    or not isinstance(observation.get("reason"), str) or not observation["reason"].strip()
                    or observation.get("severity") not in ("good", "low", "medium", "high")):
                malformed = True
            elif observation["severity"] in ("medium", "high"):
                blocking.append(dict(observation, id=identifier))
        if malformed or (sum(dimensions.values()) < 60 and all(o.get("severity") == "good" for o in observations)):
            errors.append(identifier + ": unsupported or out-of-scope observations")
            continue
        valid[identifier] = sum(dimensions.values())
    missing = sorted(set(expected) - set(valid))
    complete = not errors and not missing and scope["status"] in ("ready", "not_applicable")
    score = None
    if complete and valid:
        score = float((Decimal(sum(valid.values())) / Decimal(len(valid))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    return dict(metric=scope["metric"], scope_sha256=scope["scope_sha256"], score=score,
                minimum=min(valid.values()) if valid else None, eligible=len(expected), reviewed=len(valid),
                missing=missing, errors=errors, complete=complete, unmatched_excluded=sum(
                    item["reason"] == "Unmatched implementation" for item in scope["excluded"]),
                unverified=scope["unverified"], regressions=scope["regressions"], blocking=blocking,
                status="pending" if not complete else "not_applicable" if not valid else "complete",
                acceptance_ready=bool(complete and valid and min(valid.values()) >= MIN_READABLE_SCORE
                                      and not scope["regressions"] and not blocking))


def render(result):
    score = "N/A" if result["score"] is None else str(result["score"]) + " / 100"
    return ("Matched-contribution readability: " + score + "; minimum item: " + str(result["minimum"]) + "\n"
            + "Reviewed {reviewed}/{eligible}; unmatched excluded: {unmatched_excluded}; "
              "unverified: {unknown}; binary regressions: {lost}. Status: {status}.\n".format(
                  **result, unknown=len(result["unverified"]), lost=len(result["regressions"])))
