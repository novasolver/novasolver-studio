"""Offline regression checks; no credentials or network required."""
import io
import json
import unittest
from unittest.mock import patch

import ds_review


class ReviewResponseTests(unittest.TestCase):
    def call(self, content, model="deepseek-flash", finish="stop"):
        response = {"choices": [{"message": {"content": content},
                                  "finish_reason": finish}], "usage": {}}
        with patch.object(ds_review, "api_key", return_value="synthetic"), patch.object(
                ds_review.urllib.request, "urlopen",
                return_value=io.BytesIO(json.dumps(response).encode())) as send:
            result, _ = ds_review.ask("Return JSON", "synthetic code", model)
            payload = json.loads(send.call_args.args[0].data)
        return result, payload

    def test_flash_disables_default_thinking(self):
        result, body = self.call('{"findings": []}')
        self.assertEqual(result, {"findings": []})
        self.assertEqual(body["thinking"], {"type": "disabled"})

    def test_reasoning_override_is_preserved(self):
        _, body = self.call('{"findings": []}', "deepseek-reasoner")
        self.assertNotIn("thinking", body)

    def test_empty_and_wrong_shapes_are_not_clean_reviews(self):
        for content in (None, "", "{}", "[]", "null", '{"findings": {}}'):
            with self.subTest(content=content):
                result, _ = self.call(content)
                self.assertIn("error", result)

    def test_truncated_empty_answer_is_reported(self):
        result, _ = self.call(None, finish="length")
        self.assertTrue(result["truncated"])
        self.assertIn("error", result)


if __name__ == "__main__":
    unittest.main()
