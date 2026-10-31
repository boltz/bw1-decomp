"""Validate and format the mandatory readability scorecard for fork reviews."""

from urllib.parse import quote, urlparse

DIMENSIONS = ("naming", "intent", "control_flow", "data_types", "consistency")
MAX_DETAILS = 40
MAX_DIMENSION_SCORE = 20
MAX_OBSERVATIONS = 6
MAX_PRECEDENTS = 4
MAX_DECISION_GROUPS = 64
MAX_SUMMARY_CHARS = 1200
MAX_OBSERVATION_CHARS = 800
MAX_NUMERIC_REASON_CHARS = 500
MAX_INLINE_COMMENT_CHARS = 160
MAX_PRECEDENT_QUOTE_CHARS = 200
MAX_JUSTIFICATION_REASONS = 5
MAX_UNCERTAIN_DETAILS = 10
MIN_READABLE_SCORE = 60


def object_schema(properties):
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


TEXT_SCHEMA = {"type": "string"}
OBSERVATION_FIELDS = {
    "path": TEXT_SCHEMA,
    "line": {"type": "integer"},
    "reason": TEXT_SCHEMA,
    "suggestion": TEXT_SCHEMA,
}
QUALITY_SCHEMA = object_schema(
    {
        "dimensions": object_schema({name: {"type": "integer"} for name in DIMENSIONS}),
        "rationale": TEXT_SCHEMA,
        "lionhead_context": TEXT_SCHEMA,
        "precedent_summary": TEXT_SCHEMA,
        "good": {"type": "array", "items": object_schema(OBSERVATION_FIELDS)},
        "bad": {
            "type": "array",
            "items": object_schema(
                dict(OBSERVATION_FIELDS, severity={"type": "string", "enum": ["low", "medium", "high"]})
            ),
        },
        "precedents": {
            "type": "array",
            "items": object_schema(
                {
                    "url": TEXT_SCHEMA,
                    "position": {"type": "string", "enum": ["accepted", "rejected", "discussion"]},
                    "quote": TEXT_SCHEMA,
                    "comparison": TEXT_SCHEMA,
                }
            ),
        },
        "numbers_reviewed": {"type": "boolean"},
        "numeric_decisions": {
            "type": "array",
            "items": object_schema(
                {
                    "ids": {"type": "array", "items": TEXT_SCHEMA},
                    "classification": {"type": "string", "enum": ["magic", "justified", "uncertain"]},
                    "reason": TEXT_SCHEMA,
                    "suggestion": TEXT_SCHEMA,
                }
            ),
        },
    }
)


def validate_quality(raw, inventory, changed_lines, precedents):
    result = {
        "inventory": inventory,
        "score": None,
        "dimensions": {},
        "good": [],
        "bad": [],
        "precedents": [],
        "magic": [],
        "justified": [],
        "uncertain": [],
        "invalid": 0,
        "validation_errors": [],
        "rationale": "",
        "lionhead_context": "",
        "precedent_summary": "",
        "numbers_complete": False,
        "blocking": False,
        "unresolved_numbers": inventory["number_count"],
    }
    if not isinstance(raw, dict):
        result["invalid"] += 1
        result["validation_errors"].append("Quality must be an object")
        return result
    applicable = any(
        lines
        for path, lines in changed_lines.items()
        if path.endswith((".c", ".cc", ".cpp", ".h", ".hpp", ".inl", ".py", ".sh", ".yml", ".yaml"))
    )
    dimensions = raw.get("dimensions")
    valid_dimensions = (
        isinstance(dimensions, dict)
        and set(dimensions) == set(DIMENSIONS)
        and all(type(v) is int and 0 <= v <= MAX_DIMENSION_SCORE for v in dimensions.values())
    )
    for field in ("rationale", "lionhead_context", "precedent_summary"):
        value = raw.get(field)
        if not isinstance(value, str) or not value.strip():
            result["invalid"] += 1
            result["validation_errors"].append("Required rationale/context field is empty: " + field)
        else:
            result[field] = value.strip()[:MAX_SUMMARY_CHARS]
    if applicable and valid_dimensions:
        result["dimensions"] = dimensions
        result["score"] = sum(dimensions.values())
    elif applicable:
        result["invalid"] += 1
        result["validation_errors"].append("Dimension scores are invalid")
    if applicable and result["score"] is not None and result["score"] < MIN_READABLE_SCORE and not raw.get("bad"):
        result["invalid"] += 1
        result["validation_errors"].append("A low score has no concrete negative observation")
    for kind in ("good", "bad"):
        entries = raw.get(kind)
        if not isinstance(entries, list):
            result["invalid"] += 1
            result["validation_errors"].append("Observation list must be an array: " + kind)
            continue
        if len(entries) > MAX_OBSERVATIONS:
            result["invalid"] += 1
            result["validation_errors"].append("Too many observations: " + kind)
        for entry in entries[:MAX_OBSERVATIONS]:
            if (
                not isinstance(entry, dict)
                or type(entry.get("line")) is not int
                or not isinstance(entry.get("path"), str)
                or entry["line"] not in changed_lines.get(entry["path"], set())
                or not isinstance(entry.get("reason"), str)
                or not entry["reason"].strip()
                or not isinstance(entry.get("suggestion"), str)
            ):
                result["invalid"] += 1
                result["validation_errors"].append("Observation is malformed or not on an added line: " + kind)
                continue
            if kind == "bad" and (
                entry.get("severity") not in ("low", "medium", "high") or not entry["suggestion"].strip()
            ):
                result["invalid"] += 1
                result["validation_errors"].append("Negative observation needs a severity and specific suggestion")
                continue
            result[kind].append(
                {
                    key: value[:MAX_OBSERVATION_CHARS] if isinstance(value, str) else value
                    for key, value in entry.items()
                }
            )
    if applicable and not result["good"] and not result["bad"]:
        result["score"] = None
        result["invalid"] += 1
        result["validation_errors"].append("No valid readability observations support the score")
    numbers = {number["id"]: number for number in inventory["numbers"]}
    seen = set()
    decisions = raw.get("numeric_decisions")
    if not isinstance(decisions, list):
        decisions = []
        result["invalid"] += 1
        result["validation_errors"].append("Numeric decisions must be an array")
    if len(decisions) > MAX_DECISION_GROUPS:
        result["invalid"] += 1
        result["validation_errors"].append("Too many numeric decision groups")
    for decision in decisions[:MAX_DECISION_GROUPS]:
        if (
            not isinstance(decision, dict)
            or decision.get("classification") not in ("magic", "justified", "uncertain")
            or not isinstance(decision.get("ids"), list)
            or not decision["ids"]
            or not isinstance(decision.get("reason"), str)
            or not decision["reason"].strip()
            or not isinstance(decision.get("suggestion"), str)
            or (decision["classification"] == "magic" and not decision["suggestion"].strip())
        ):
            result["invalid"] += 1
            result["validation_errors"].append("Numeric decision is malformed")
            continue
        for identifier in decision["ids"]:
            if not isinstance(identifier, str) or identifier not in numbers or identifier in seen:
                result["invalid"] += 1
                result["validation_errors"].append("Numeric ID is unknown, duplicated, or not a string: " + str(identifier))
                continue
            seen.add(identifier)
            result[decision["classification"]].append(
                dict(
                    numbers[identifier],
                    reason=decision["reason"][:MAX_NUMERIC_REASON_CHARS],
                    suggestion=decision["suggestion"][:MAX_NUMERIC_REASON_CHARS],
                )
            )
    result["unresolved_numbers"] = inventory["number_count"] - len(result["magic"]) - len(result["justified"])
    missing = set(numbers) - seen
    if missing:
        result["invalid"] += 1
        result["validation_errors"].append("Numeric IDs were not classified: " + ", ".join(sorted(missing)))
    result["numbers_complete"] = (
        not inventory["limitations"]
        and not result["unresolved_numbers"]
        and (raw.get("numbers_reviewed") is True or not inventory["eligible_files"])
    )
    cited = raw.get("precedents", [])
    if not isinstance(cited, list):
        cited = []
        result["invalid"] += 1
        result["validation_errors"].append("Precedents must be an array")
    if len(cited) > MAX_PRECEDENTS:
        result["invalid"] += 1
        result["validation_errors"].append("Too many precedents")
    for citation in cited[:MAX_PRECEDENTS]:
        if (
            not isinstance(citation, dict)
            or not isinstance(citation.get("url"), str)
            or citation["url"] not in precedents
            or urlparse(citation["url"]).netloc != "github.com"
            or urlparse(citation["url"]).scheme != "https"
            or not isinstance(citation.get("comparison"), str)
            or not citation["comparison"].strip()
            or citation.get("position") not in ("accepted", "rejected", "discussion")
            or not isinstance(citation.get("quote"), str)
            or not citation["quote"].strip()
            or len(citation["quote"]) > MAX_PRECEDENT_QUOTE_CHARS
            or citation["quote"] not in precedents[citation["url"]].get("excerpt", "")
        ):
            result["invalid"] += 1
            result["validation_errors"].append("Precedent quote or source is unsupported")
            continue
        result["precedents"].append(
            dict(
                precedents[citation["url"]],
                comparison=citation["comparison"][:MAX_OBSERVATION_CHARS],
                position=citation["position"],
                quote=citation["quote"],
            )
        )
    result["blocking"] = bool(
        result["magic"]
        or inventory["remove_comment_count"]
        or any(item["severity"] in ("medium", "high") for item in result["bad"])
    )
    if result["invalid"]:
        result["numbers_complete"] = False
    return result


def apply_quality_event(event, quality):
    if quality["inventory"]["remove_comment_count"]:
        return "REQUEST_CHANGES"
    if quality["blocking"] and not quality["invalid"]:
        return "REQUEST_CHANGES"
    return event


def precedent_sources(evidence):
    return {
        row["url"]: row
        for query in (evidence or {}).get("queries", [])
        for row in query.get("results", [])
        if isinstance(row.get("url"), str)
        and row.get("kind") in ("review", "inline_review_comment", "conversation_comment")
    }


def location_label(path, line, escape, repository="", commit=""):
    label = "`{}:{}`".format(escape(path), line)
    if repository and commit:
        url = "https://github.com/{}/blob/{}/{}#L{}".format(
            quote(repository, safe="/"), quote(commit, safe=""), quote(path, safe="/"), line
        )
        return "[{}]({})".format(label, url)
    return label


def render_quality(result, escape, repository="", commit=""):
    if result is None:
        return [
            "## Review scorecard",
            "",
            "| Check | Result |",
            "| --- | --- |",
            "| Human readability | Not scored / 100 |",
            "| Magic numbers | Unavailable |",
            "| Added comments | Unavailable |",
            "",
            "The review data is missing. These checks are unfinished.",
            "",
        ]
    inventory = result["inventory"]
    score = (
        "{} / 100".format(result["score"]) if result["score"] is not None else "N/A / 100 - not enough code to score"
    )
    incomplete = bool(
        result["invalid"] or inventory["limitations"] or not result["numbers_complete"] or result.get("scope_limited")
    )
    if incomplete and result["score"] is not None:
        score += " (partial review)"
    lines = [
        "## Review scorecard",
        "",
        "| Check | Result |",
        "| --- | --- |",
        "| Human readability | {} |".format(score),
        "| Magic numbers | {} found; {} still unclear; checked: {} |".format(
            len(result["magic"]), result.get("unresolved_numbers", inventory["number_count"]), inventory["number_count"]
        ),
        "| Added/edited comments | {} total; {} to remove; {} required comments kept |".format(
            (
                str(inventory["comment_count"])
                if inventory["comments_complete"]
                else "at least " + str(inventory["comment_count"])
            ),
            inventory["remove_comment_count"],
            inventory["allowed_comment_count"],
        ),
        "| Review coverage | {} |".format(
            "Partial. Counts may be too low" if incomplete else "Complete for the code checked"
        ),
        "",
        "Counts cover the added code this check could read. Strings, vendor code, and docs are excluded.",
        "",
        "## Human readability",
        "",
        escape(result["rationale"]) or "There was not enough code to assess readability.",
        "",
    ]
    if result["dimensions"]:
        lines += [
            "<details>",
            "<summary>Score breakdown</summary>",
            "",
            "Score breakdown: "
            + "; ".join("{} {}/20".format(name.replace("_", " "), result["dimensions"][name]) for name in DIMENSIONS)
            + ".",
            "",
            "This score rates how easy the code is to read. It does not prove the code is correct or matches the game.",
            "",
            "</details>",
            "",
        ]
    for kind, title in [("good", "Readable code"), ("bad", "Changes needed")]:
        lines += ["### " + title, ""]
        if not result[kind]:
            if kind == "bad" and (result["magic"] or inventory["remove_comment_count"]):
                lines += [
                    "See the numbers and comments listed below.",
                    "",
                ]
            else:
                lines += [
                    "No specific {} found in the code reviewed.".format(
                        "strengths" if kind == "good" else "readability problems"
                    ),
                    "",
                ]
        for entry in result[kind]:
            lines += [
                "- {} - {}".format(
                    location_label(entry["path"], entry["line"], escape, repository, commit), escape(entry["reason"])
                )
            ]
            if entry["suggestion"]:
                lines += ["  Change: " + escape(entry["suggestion"])]
        lines.append("")
    lines += [
        "### Lionhead C++ style",
        "",
        escape(result["lionhead_context"]) or "There was not enough code to assess this.",
        "",
        "## Magic numbers",
        "",
        "These are numbers whose purpose needs a clear name or an existing constant.",
        "",
    ]
    if not result["magic"]:
        if result["numbers_complete"] and inventory["eligible_files"]:
            lines += ["Good: no magic numbers found in the inspected additions."]
        elif not inventory["eligible_files"]:
            lines += ["No added code was covered by this check."]
        else:
            lines += ["No magic numbers were confirmed. Some code or numbers still need checking."]
    for item in result["magic"][:MAX_DETAILS]:
        lines += [
            "- {} literal `{}` - {} Change: {}".format(
                location_label(item["path"], item["line"], escape, repository, commit),
                escape(item["literal"]),
                escape(item["reason"]),
                escape(item["suggestion"]),
            )
        ]
    if len(result["magic"]) > MAX_DETAILS:
        lines += ["Only the first {} are shown. The review-quality download has the full list.".format(MAX_DETAILS)]
    if result["uncertain"]:
        lines += ["", "Numbers that still need checking:"]
        lines += [
            "- {} `{}` - {}".format(
                location_label(n["path"], n["line"], escape, repository, commit),
                escape(n["literal"]),
                escape(n["reason"]),
            )
            for n in result["uncertain"][:MAX_UNCERTAIN_DETAILS]
        ]
    justified_reasons = list(dict.fromkeys(item["reason"] for item in result["justified"]))
    if justified_reasons:
        lines += ["", "Numbers that are clear in context:"]
        lines += ["- " + escape(reason) for reason in justified_reasons[:MAX_JUSTIFICATION_REASONS]]
    lines += ["", "## Added comments", ""]
    if inventory["remove_comment_count"]:
        count = inventory["remove_comment_count"]
        lines += [
            "Remove {} added or edited comment{}. Keep required address and format comments, and leave unchanged text alone.".format(
                count, "" if count == 1 else "s"
            ),
            "",
        ]
    elif not inventory["eligible_files"]:
        lines += ["No added code was covered by this comment check.", ""]
    elif inventory["comments_complete"]:
        lines += ["Good: no added prose comments require removal.", ""]
    else:
        lines += ["No added comments were found in the code supplied. The rest still needs checking.", ""]
    comments = [item for item in inventory["comments"] if item["kind"] == "remove prose comment"]
    for comment in comments[:MAX_DETAILS]:
        lines += [
            "- {} - {}: `{}`".format(
                location_label(comment["path"], comment["line"], escape, repository, commit),
                escape(
                    "remove only the added text; keep the existing comment"
                    if comment.get("started_in_added_line") is False
                    else "remove this added comment"
                ),
                escape(comment["text"][:MAX_INLINE_COMMENT_CHARS]),
            )
        ]
    if len(comments) > MAX_DETAILS:
        lines += [
            "Only the first {} comments are shown. The review-quality download has the full list.".format(MAX_DETAILS)
        ]
    allowed = [item for item in inventory["comments"] if item["kind"] != "remove prose comment"]
    if allowed:
        lines += ["", "<details>", "<summary>Required comments kept ({})</summary>".format(len(allowed)), ""]
        for comment in allowed[:MAX_DETAILS]:
            lines += [
                "- {}: {}".format(
                    location_label(comment["path"], comment["line"], escape, repository, commit),
                    escape(comment["kind"]),
                )
            ]
        if len(allowed) > MAX_DETAILS:
            lines += ["The review-quality download has the full list."]
        lines += ["", "</details>", ""]
    lines += ["", "## Past reviews from RepoScout", ""]
    if result["precedent_summary"]:
        lines += [escape(result["precedent_summary"]), ""]
    accepted = sum(item["position"] == "accepted" for item in result["precedents"])
    rejected = sum(item["position"] == "rejected" for item in result["precedents"])
    lines += [
        "Similar code in the quoted reviews: {} accepted; {} rejected. A merged PR alone does not count as acceptance.".format(
            accepted, rejected
        ),
        "",
    ]
    if not result["precedents"] and not result["precedent_summary"]:
        lines += ["The supplied RepoScout results did not show a clear decision on similar code."]
    for item in result["precedents"]:
        url = quote(item["url"], safe=":/#?=&%")
        actor = "{} ({})".format(
            item.get("author") or "author unknown", item.get("author_association") or "role unknown"
        )
        state = item.get("review_state") or "comment only; no formal review result"
        lines += [
            "### {} pattern - [PR #{} source]({})".format(item["position"].capitalize(), item["pr_number"], url),
            "",
            "{}; {}.".format(escape(actor), escape(state)),
            "",
            "> " + escape(item["quote"]),
            "",
            "This applies here because: " + escape(item["comparison"]),
            "",
        ]
    if inventory["limitations"] or result["invalid"]:
        lines += [
            "",
            "Some files or results were missing. This review cannot approve the PR.",
            "",
            "<details>",
            "<summary>Missing files and checks</summary>",
            "",
        ]
        lines += ["- " + escape(note) for note in inventory["limitations"]]
        if result["invalid"]:
            lines += [
                "- {} part(s) of the model response could not be checked. This review cannot approve the PR.".format(
                    result["invalid"]
                )
            ]
        lines += ["", "</details>"]
    return lines + [""]
