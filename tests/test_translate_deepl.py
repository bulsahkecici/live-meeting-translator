import unittest
from unittest.mock import Mock, patch

from src.translate_deepl import DeepLTranslator


class DeepLTranslatorTests(unittest.TestCase):
    def test_api_key_is_sent_in_authorization_header_only(self):
        response = Mock(status_code=200)
        response.json.return_value = {
            "translations": [{"text": "Hello"}],
        }

        with patch("src.translate_deepl.requests.post", return_value=response) as post:
            translator = DeepLTranslator(api_key="test-secret")
            result = translator.translate("Merhaba")

        self.assertEqual(result, "Hello")
        post.assert_called_once()
        request = post.call_args.kwargs
        self.assertEqual(
            request["headers"],
            {"Authorization": "DeepL-Auth-Key test-secret"},
        )
        self.assertNotIn("auth_key", request["data"])
        self.assertEqual(request["data"]["text"], "Merhaba")
        self.assertNotIn("context", request["data"])
        self.assertNotIn("custom_instructions", request["data"])

    def test_context_and_name_instruction_are_sent_without_transcript_history(self):
        response = Mock(status_code=200)
        response.json.return_value = {
            "translations": [{"text": "The person's name is ExampleName."}],
        }
        translator = DeepLTranslator(
            api_key="test-secret",
            context="ExampleName is a personal name.",
            custom_instructions=["Keep the personal name ExampleName unchanged."],
        )

        with patch("src.translate_deepl.requests.post", return_value=response) as post:
            result = translator.translate("Kişinin adı ExampleName.")

        self.assertEqual(result, "The person's name is ExampleName.")
        request_data = post.call_args.kwargs["data"]
        self.assertEqual(
            request_data["context"],
            "ExampleName is a personal name.",
        )
        self.assertEqual(
            request_data["custom_instructions"],
            ["Keep the personal name ExampleName unchanged."],
        )
        self.assertNotIn("history", request_data)

    def test_invalid_custom_instruction_limits_fail_before_api_use(self):
        with self.assertRaisesRegex(ValueError, "at most 10"):
            DeepLTranslator(
                api_key="test-secret",
                custom_instructions=["instruction"] * 11,
            )
        with self.assertRaisesRegex(ValueError, "at most 300"):
            DeepLTranslator(
                api_key="test-secret",
                custom_instructions=["x" * 301],
            )


if __name__ == "__main__":
    unittest.main()
