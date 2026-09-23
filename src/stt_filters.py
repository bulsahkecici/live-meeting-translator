"""Narrow filters for recurring Whisper silence hallucinations."""
from typing import Optional
import unicodedata


def normalize_stt_text(text: str) -> str:
    """Normalize case, punctuation, accents, and spacing for matching."""
    folded = unicodedata.normalize("NFKD", text.casefold())
    characters = []
    for character in folded:
        if unicodedata.combining(character):
            continue
        characters.append(character if character.isalnum() else " ")
    return " ".join("".join(characters).split())


_KNOWN_SILENCE_PHRASES = tuple(
    sorted(
        {
            normalize_stt_text(phrase)
            for phrase in (
                "thank you for watching",
                "thanks for watching",
                "thank you",
                "thanks",
                "subtitles by m k",
                "subtitles m k",
                "subtitle by m k",
                "subtitle m k",
                "videoyu izlediğiniz için teşekkürler",
                "videoyu izlediğiniz için",
                "izlediğiniz için teşekkürler",
                "izlediğiniz için teşekkür ederim",
                "bir sonraki videoda görüşürüz",
                "altyazı m k",
                "altyazılar m k",
            )
        },
        key=len,
        reverse=True,
    )
)


def _is_low_diversity_repetition(normalized: str) -> bool:
    tokens = normalized.split()
    if len(tokens) >= 4 and len(set(tokens)) <= 2:
        return True

    compact = "".join(tokens)
    return len(compact) >= 12 and len(set(compact)) <= 2


def should_suppress_stt_text(text: Optional[str]) -> bool:
    """Suppress only whole boilerplate or clearly repetitive transcripts."""
    if not text:
        return False

    normalized = normalize_stt_text(text)
    if _is_low_diversity_repetition(normalized):
        return True

    remainder = f" {normalized} "
    for phrase in _KNOWN_SILENCE_PHRASES:
        remainder = remainder.replace(f" {phrase} ", " ")
    return not remainder.strip()
