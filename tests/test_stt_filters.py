import unittest

from src.stt_filters import should_suppress_stt_text


class STTHallucinationFilterTests(unittest.TestCase):
    def test_suppresses_short_silence_boilerplate(self):
        for text in (
            "Thank you.",
            "Thanks!",
            "Thank you for watching. Subtitles by M.K.",
            "İzlediğiniz için teşekkürler. Altyazı M.K.",
        ):
            with self.subTest(text=text):
                self.assertTrue(should_suppress_stt_text(text))

    def test_suppresses_low_diversity_repetition(self):
        self.assertTrue(should_suppress_stt_text("abababababababababab"))
        self.assertTrue(should_suppress_stt_text("mystery mystery mystery mystery"))

    def test_preserves_real_sentences_containing_a_known_phrase(self):
        self.assertFalse(
            should_suppress_stt_text(
                "Thank you for watching the deployment dashboard."
            )
        )
        self.assertFalse(
            should_suppress_stt_text(
                "İzlediğiniz için teşekkürler, şimdi toplantıya geçelim."
            )
        )


if __name__ == "__main__":
    unittest.main()
