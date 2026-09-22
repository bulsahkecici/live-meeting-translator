"""Deterministic transcript normalization and error metrics for STT benchmarks."""
import unicodedata
from typing import Sequence, Tuple

_TURKISH_CASE_TRANSLATION = str.maketrans({"I": "ı", "İ": "i"})


def normalize_transcript(text: str) -> str:
    """Normalize case, punctuation, and whitespace without folding diacritics."""
    normalized = unicodedata.normalize("NFC", text)
    normalized = normalized.translate(_TURKISH_CASE_TRANSLATION).lower()
    normalized = "".join(
        " " if unicodedata.category(character).startswith("P") else character
        for character in normalized
    )
    return " ".join(normalized.split())


def edit_distance(reference: Sequence[str], hypothesis: Sequence[str]) -> int:
    """Return Levenshtein distance using linear memory."""
    previous = list(range(len(hypothesis) + 1))
    for row, reference_item in enumerate(reference, start=1):
        current = [row]
        for column, hypothesis_item in enumerate(hypothesis, start=1):
            substitution = previous[column - 1] + (
                reference_item != hypothesis_item
            )
            current.append(
                min(
                    previous[column] + 1,
                    current[column - 1] + 1,
                    substitution,
                )
            )
        previous = current
    return previous[-1]


def word_error_counts(reference: str, hypothesis: str) -> Tuple[int, int]:
    """Return word edit errors and normalized reference word count."""
    reference_words = normalize_transcript(reference).split()
    hypothesis_words = normalize_transcript(hypothesis).split()
    return edit_distance(reference_words, hypothesis_words), len(reference_words)


def character_error_counts(reference: str, hypothesis: str) -> Tuple[int, int]:
    """Return character edit errors and reference length, including single spaces."""
    reference_text = normalize_transcript(reference)
    hypothesis_text = normalize_transcript(hypothesis)
    return edit_distance(reference_text, hypothesis_text), len(reference_text)


def word_error_rate(reference: str, hypothesis: str) -> float:
    """Return WER; an empty reference uses a denominator of one."""
    errors, reference_count = word_error_counts(reference, hypothesis)
    return errors / max(1, reference_count)


def character_error_rate(reference: str, hypothesis: str) -> float:
    """Return CER; an empty reference uses a denominator of one."""
    errors, reference_count = character_error_counts(reference, hypothesis)
    return errors / max(1, reference_count)
