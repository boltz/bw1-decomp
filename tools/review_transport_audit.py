import hashlib
import json
from pathlib import Path


def digest(data):
    return hashlib.sha256(data).hexdigest()


def scalar_fields(value, names):
    if not isinstance(value, dict):
        return None
    return {name: value[name] for name in names
            if name in value and (value[name] is None or type(value[name]) in (str, int, float, bool))}


def envelope_metadata(envelope):
    result = scalar_fields(envelope, ("id", "object", "model", "status", "created_at", "completed_at"))
    if result is None:
        return None
    result["incomplete_details"] = scalar_fields(envelope.get("incomplete_details"), ("reason",))
    error = envelope.get("error")
    result["error"] = scalar_fields(error, ("code", "type", "param"))
    if isinstance(error, dict) and isinstance(error.get("message"), str):
        message = error["message"].encode("utf-8")
        result["error"].update(message_sha256=digest(message), message_bytes=len(message))
    usage = envelope.get("usage")
    result["usage"] = scalar_fields(usage, ("input_tokens", "output_tokens", "total_tokens"))
    if isinstance(usage, dict):
        for name, fields in (
            ("input_tokens_details", ("cached_tokens", "cache_write_tokens")),
            ("output_tokens_details", ("reasoning_tokens",)),
        ):
            result["usage"][name] = scalar_fields(usage.get(name), fields)
    result["messages"] = [
        {**scalar_fields(item, ("id", "role", "status")),
         "content_types": [content.get("type") for content in item.get("content", [])
                           if isinstance(content, dict) and isinstance(content.get("type"), str)]}
        for item in envelope.get("output", [])
        if isinstance(item, dict) and item.get("type") == "message"
        and isinstance(item.get("content", []), list)
    ] if isinstance(envelope.get("output", []), list) else []
    return result


class ModelResponseAudit:
    def __init__(self, request_path, receipt_path):
        self.request_path = Path(request_path)
        self.receipt_path = Path(receipt_path)
        self.receipt = {"schema": 1, "attempts": []}

    def save(self):
        self.receipt_path.write_text(json.dumps(self.receipt, indent=2) + "\n")

    def record_request(self, body):
        payload = json.loads(body)
        self.request_path.write_bytes(body)
        self.receipt["request"] = {
            "body_path": str(self.request_path),
            "body_sha256": digest(body),
            "body_bytes": len(body),
            "messages": [
                {"role": item["role"], "content_utf8_bytes": len(item["content"].encode("utf-8")),
                 "content_sha256": digest(item["content"].encode("utf-8"))}
                for item in payload["input"]
            ],
        }
        self.save()

    def start_attempt(self, number):
        self.receipt["attempts"].append({"attempt": number, "outcome": "pending"})
        self.save()

    def record_response(self, raw, status, headers, body_complete=True):
        attempt = self.receipt["attempts"][-1]
        attempt.update(response_body_sha256=digest(raw), response_bytes_read=len(raw),
                       response_body_complete=body_complete, http_status=status)
        request_id = headers.get("x-request-id") if headers is not None else None
        if isinstance(request_id, str):
            attempt["request_id"] = request_id
        try:
            envelope = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            attempt["envelope_json_valid"] = False
        else:
            attempt["envelope_json_valid"] = True
            attempt["envelope"] = envelope_metadata(envelope)
        self.save()

    def record_failure(self, kind):
        self.receipt["attempts"][-1]["outcome"] = kind
        self.save()

    def record_result(self):
        self.receipt["attempts"][-1]["outcome"] = "completed_review_json"
        self.save()
