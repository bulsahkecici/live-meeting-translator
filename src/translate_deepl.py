"""Translation using DeepL API."""
import logging
import requests
import time
from typing import Optional, Sequence
from cachetools import LRUCache

from .backend_interfaces import TranslatorBackend

logger = logging.getLogger(__name__)


class DeepLTranslator(TranslatorBackend):
    """DeepL API translator with retry logic and caching."""
    
    def __init__(
        self,
        api_key: str,
        source_lang: str = "TR",
        target_lang: str = "EN",
        cache_size: int = 128,
        timeout_seconds: int = 10,
        retry_max_attempts: int = 3,
        retry_backoff: list = None,
        context: Optional[str] = None,
        custom_instructions: Optional[Sequence[str]] = None,
    ):
        """
        Initialize DeepL translator.
        
        Args:
            api_key: DeepL API key
            source_lang: Source language code
            target_lang: Target language code
            cache_size: LRU cache size
            timeout_seconds: Request timeout
            retry_max_attempts: Maximum retry attempts
            retry_backoff: Backoff delays in seconds [0.5, 1.0, 2.0, 4.0]
            context: Optional short disambiguation context; not translated
            custom_instructions: Optional DeepL translation instructions
        """
        if not api_key:
            raise ValueError("DeepL API key is required")
        
        self.api_key = api_key
        self.source_lang = source_lang
        self.target_lang = target_lang
        self.timeout = timeout_seconds
        self.retry_max_attempts = retry_max_attempts
        self.retry_backoff = retry_backoff or [0.5, 1.0, 2.0, 4.0]
        self.context = context.strip() if isinstance(context, str) else None
        if custom_instructions is None:
            custom_instructions = ()
        elif isinstance(custom_instructions, str):
            custom_instructions = (custom_instructions,)
        self.custom_instructions = tuple(
            instruction.strip()
            for instruction in custom_instructions
            if isinstance(instruction, str) and instruction.strip()
        )
        if len(self.custom_instructions) > 10:
            raise ValueError("DeepL accepts at most 10 custom instructions")
        if any(len(instruction) > 300 for instruction in self.custom_instructions):
            raise ValueError(
                "DeepL custom instructions must be at most 300 characters"
            )
        
        # LRU cache
        self.cache = LRUCache(maxsize=cache_size)
        
        # API endpoint
        self.api_url = "https://api-free.deepl.com/v2/translate"
        
        logger.info(
            f"DeepL translator initialized: {source_lang} -> {target_lang}, "
            f"cache_size={cache_size}"
        )
    
    def translate(self, text: str) -> Optional[str]:
        """
        Translate text from source to target language.
        
        Args:
            text: Text to translate
        
        Returns:
            Translated text or None on error
        """
        if not text or not text.strip():
            return None
        
        text = text.strip()
        
        # Check cache
        cache_key = (
            self.source_lang,
            self.target_lang,
            self.context,
            self.custom_instructions,
            text,
        )
        if cache_key in self.cache:
            logger.debug(f"Translation cache hit: '{text[:50]}...'")
            return self.cache[cache_key]
        
        # Translate with retry
        for attempt in range(self.retry_max_attempts):
            try:
                request_data = {
                    "text": text,
                    "source_lang": self.source_lang,
                    "target_lang": self.target_lang,
                }
                if self.context:
                    request_data["context"] = self.context
                if self.custom_instructions:
                    request_data["custom_instructions"] = list(
                        self.custom_instructions
                    )
                response = requests.post(
                    self.api_url,
                    headers={
                        "Authorization": f"DeepL-Auth-Key {self.api_key}",
                    },
                    data=request_data,
                    timeout=self.timeout
                )
                
                # Check status code
                if response.status_code == 200:
                    result = response.json()
                    translated_text = result["translations"][0]["text"]
                    
                    # Cache result
                    self.cache[cache_key] = translated_text
                    
                    logger.info(
                        f"Translation: '{text[:50]}...' -> "
                        f"'{translated_text[:50]}...'"
                    )
                    
                    return translated_text
                
                elif response.status_code == 429:
                    # Rate limited
                    backoff = self.retry_backoff[min(attempt, len(self.retry_backoff) - 1)]
                    logger.warning(
                        f"DeepL rate limited (429). Retrying in {backoff}s "
                        f"(attempt {attempt + 1}/{self.retry_max_attempts})"
                    )
                    if attempt < self.retry_max_attempts - 1:
                        time.sleep(backoff)
                        continue
                    else:
                        logger.error("DeepL rate limit exceeded after retries")
                        return None
                
                elif response.status_code >= 500:
                    # Server error
                    backoff = self.retry_backoff[min(attempt, len(self.retry_backoff) - 1)]
                    logger.warning(
                        f"DeepL server error ({response.status_code}). "
                        f"Retrying in {backoff}s "
                        f"(attempt {attempt + 1}/{self.retry_max_attempts})"
                    )
                    if attempt < self.retry_max_attempts - 1:
                        time.sleep(backoff)
                        continue
                    else:
                        logger.error(
                            f"DeepL server error after retries: "
                            f"{response.status_code}"
                        )
                        return None
                
                else:
                    # Other error
                    logger.error(
                        f"DeepL API error: {response.status_code} - "
                        f"{response.text}"
                    )
                    return None
                    
            except requests.exceptions.Timeout:
                logger.warning(
                    f"DeepL request timeout. Retrying "
                    f"(attempt {attempt + 1}/{self.retry_max_attempts})"
                )
                if attempt < self.retry_max_attempts - 1:
                    backoff = self.retry_backoff[min(attempt, len(self.retry_backoff) - 1)]
                    time.sleep(backoff)
                    continue
                else:
                    logger.error("DeepL request timeout after retries")
                    return None
            
            except Exception as e:
                logger.error(f"DeepL translation error: {e}", exc_info=True)
                return None
        
        return None
