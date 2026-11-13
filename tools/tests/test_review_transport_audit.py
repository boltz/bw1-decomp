import hashlib
import io
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

import tools.automatic_pr_review as api
from tools.review_transport_audit import ModelResponseAudit


class ModelResponseAuditTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.audit = ModelResponseAudit(self.root / "request.json", self.root / "transport.json")
        self.review = {"findings": [], "quality": {"dimensions": {"naming": 12}}}
        self.envelope = {
            "id": "resp_test", "model": "reported-model", "status": "completed",
            "error": None, "incomplete_details": None,
            "usage": {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120,
                      "input_tokens_details": {"cached_tokens": 10},
                      "output_tokens_details": {"reasoning_tokens": 5}},
            "output": [{"id": "msg_test", "type": "message", "role": "assistant",
                        "status": "completed",
                        "content": [{"type": "output_text", "text": json.dumps(self.review)}]}],
        }

    def response(self, body):
        result = mock.MagicMock()
        result.read.return_value = body
        result.status = 200
        result.headers = {"x-request-id": "request_test", "authorization": "untrusted-header"}
        result.__enter__.return_value = result
        return result

    def call(self, responses, audit=True):
        opener = mock.MagicMock()
        opener.open.side_effect = responses
        self.opener = opener
        with (mock.patch.object(api.urllib.request, "build_opener", return_value=opener),
              mock.patch.object(api.time, "sleep")):
            return api.call_model("https://example.test/v1", "dummy-private-token", "configured-model",
                                  "system unicode: é", "entire user source", audit=self.audit if audit else None)

    def receipt(self):
        return json.loads(self.audit.receipt_path.read_text())

    def test_success_preserves_exact_request_and_allowlisted_metadata(self):
        self.envelope.update(authorization="dummy-private-token", metadata={"secret": "dummy-private-token"})
        self.envelope["usage"]["secret"] = "dummy-private-token"
        raw = json.dumps(self.envelope).encode()
        self.assertEqual(self.call([self.response(raw)]), self.review)
        request = self.opener.open.call_args.args[0]
        self.assertEqual(self.audit.request_path.read_bytes(), request.data)
        saved = self.receipt()
        self.assertEqual(saved["request"]["body_sha256"], hashlib.sha256(request.data).hexdigest())
        self.assertEqual(saved["request"]["body_bytes"], len(request.data))
        envelope = saved["attempts"][0]["envelope"]
        self.assertEqual(envelope["id"], "resp_test")
        self.assertEqual(envelope["model"], "reported-model")
        self.assertEqual(envelope["usage"]["input_tokens"], 100)
        self.assertEqual(envelope["usage"]["output_tokens_details"], {"reasoning_tokens": 5})
        self.assertEqual(saved["attempts"][0]["outcome"], "completed_review_json")
        self.assertEqual(saved["attempts"][0]["request_id"], "request_test")
        self.assertEqual(saved["attempts"][0]["response_body_sha256"], hashlib.sha256(raw).hexdigest())
        for path in self.root.iterdir():
            self.assertNotIn("dummy-private-token", path.read_text())
            self.assertNotIn("untrusted-header", path.read_text())

    def test_noncompleted_status_is_terminal_even_with_valid_review_json(self):
        for status in ("incomplete", "failed", "cancelled", "queued", "in_progress", None):
            with self.subTest(status=status):
                envelope = dict(self.envelope, status=status,
                                incomplete_details={"reason": "max_output_tokens"})
                with self.assertRaisesRegex(api.ReviewError, "did not complete"):
                    self.call([self.response(json.dumps(envelope).encode())])
                self.assertEqual(self.opener.open.call_count, 1)
                self.assertEqual(self.receipt()["attempts"][-1]["envelope"]["status"], status)
                self.assertEqual(self.receipt()["attempts"][-1]["outcome"], "rejected_response")

    def test_completed_error_is_rejected_and_freeform_message_is_hashed(self):
        self.envelope["error"] = {"code": "invalid_api_key", "message": "dummy-private-token",
                                  "unknown": "dummy-private-token"}
        with self.assertRaisesRegex(api.ReviewError, "reported an error"):
            self.call([self.response(json.dumps(self.envelope).encode())])
        saved = self.receipt()["attempts"][-1]["envelope"]["error"]
        self.assertEqual(saved["code"], "invalid_api_key")
        self.assertEqual(saved["message_sha256"], hashlib.sha256(b"dummy-private-token").hexdigest())
        self.assertNotIn("dummy-private-token", self.audit.receipt_path.read_text())
        self.assertEqual(self.opener.open.call_count, 1)

    def test_completed_status_with_incomplete_details_is_rejected(self):
        self.envelope["incomplete_details"] = {"reason": "max_output_tokens"}
        with self.assertRaisesRegex(api.ReviewError, "incomplete output"):
            self.call([self.response(json.dumps(self.envelope).encode())])
        self.assertEqual(self.opener.open.call_count, 1)

    def test_incomplete_message_and_refusal_are_rejected(self):
        self.envelope["output"][0]["status"] = "incomplete"
        with self.assertRaisesRegex(api.ReviewError, "message did not complete"):
            self.call([self.response(json.dumps(self.envelope).encode())])
        self.envelope["output"][0]["status"] = "completed"
        self.envelope["output"][0]["content"] = [{"type": "refusal", "refusal": "unavailable"}]
        with self.assertRaisesRegex(api.ReviewError, "refused"):
            self.call([self.response(json.dumps(self.envelope).encode())])

    def test_truncated_envelope_retries_preserve_each_failed_attempt(self):
        truncated = self.response(b'{"status":"completed","output":')
        with self.assertRaisesRegex(api.ReviewError, "invalid JSON"):
            self.call([truncated] * api.MAX_RETRIES)
        attempts = self.receipt()["attempts"]
        self.assertEqual(len(attempts), api.MAX_RETRIES)
        self.assertTrue(all(r["envelope_json_valid"] is False and r["outcome"] == "invalid_json" for r in attempts))

    def test_truncated_inner_review_is_not_a_completed_grade(self):
        self.envelope["output"][0]["content"][0]["text"] = '{"findings": [], "quality":'
        response = self.response(json.dumps(self.envelope).encode())
        with self.assertRaisesRegex(api.ReviewError, "invalid JSON"):
            self.call([response] * api.MAX_RETRIES)
        self.assertTrue(all(r["outcome"] == "invalid_json" for r in self.receipt()["attempts"]))

    def test_malformed_output_or_message_fields_fail_cleanly(self):
        variants = [None, {}, [{"type": "message", "status": {}, "content": []}],
                    [{"type": "message", "status": "completed", "content": None}]]
        for output in variants:
            with self.subTest(output=output):
                envelope = dict(self.envelope, output=output)
                response = self.response(json.dumps(envelope).encode())
                with self.assertRaises(api.ReviewError):
                    self.call([response] * api.MAX_RETRIES)
                self.assertNotEqual(self.receipt()["attempts"][-1]["outcome"], "completed_review_json")

    def test_response_size_cap_records_prefix_as_incomplete(self):
        with (mock.patch.object(api, "MAX_RESPONSE_BYTES", 10),
              self.assertRaisesRegex(api.ReviewError, "size limit")):
            self.call([self.response(b"x" * 11)])
        attempt = self.receipt()["attempts"][-1]
        self.assertEqual(attempt["response_bytes_read"], 11)
        self.assertFalse(attempt["response_body_complete"])
        self.assertEqual(self.opener.open.call_count, 1)

    def test_invalid_utf8_is_recorded_and_rejected(self):
        with self.assertRaisesRegex(api.ReviewError, "invalid UTF-8"):
            self.call([self.response(b'\xff')])
        self.assertEqual(self.receipt()["attempts"][-1]["outcome"], "invalid_utf8")

    def test_http_error_metadata_is_saved_without_credential_message(self):
        raw = json.dumps({"error": {"code": "invalid_api_key", "message": "dummy-private-token"}}).encode()
        error = urllib.error.HTTPError("https://example.test/v1/responses", 401, "Unauthorized",
                                       {"x-request-id": "failed_request"}, io.BytesIO(raw))
        with self.assertRaisesRegex(api.ReviewError, "HTTP 401") as raised:
            self.call([error])
        self.assertNotIn("dummy-private-token", str(raised.exception))
        self.assertTrue(raised.exception.__suppress_context__)
        self.assertNotIn("dummy-private-token", self.audit.receipt_path.read_text())
        self.assertEqual(self.receipt()["attempts"][-1]["http_status"], 401)
        self.assertEqual(self.receipt()["attempts"][-1]["outcome"], "http_error")

    def test_transport_error_is_recorded_without_exception_text(self):
        with self.assertRaises(api.ReviewError) as raised:
            self.call([TimeoutError("dummy-private-token")] * api.MAX_RETRIES)
        self.assertNotIn("dummy-private-token", str(raised.exception))
        self.assertTrue(raised.exception.__suppress_context__)
        self.assertNotIn("dummy-private-token", self.audit.receipt_path.read_text())
        self.assertTrue(all(r["outcome"] == "transport_error" for r in self.receipt()["attempts"]))

    def test_generic_call_remains_compatible_and_request_bytes_are_identical(self):
        envelope = {"output_text": json.dumps(self.review)}
        self.assertEqual(self.call([self.response(json.dumps(envelope).encode())], audit=False), self.review)
        generic_body = self.opener.open.call_args.args[0].data
        self.assertFalse(self.audit.request_path.exists())
        self.assertEqual(self.call([self.response(json.dumps(self.envelope).encode())]), self.review)
        self.assertEqual(self.opener.open.call_args.args[0].data, generic_body)


if __name__ == "__main__":
    unittest.main()
