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


if __name__ == "__main__":
    unittest.main()
