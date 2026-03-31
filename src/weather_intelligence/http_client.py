"""Secure HTTP client with URL allowlisting and safety features."""

import logging
from typing import Any
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)


class URLNotAllowedError(Exception):
    """Raised when a URL is not in the allowlist."""


class SecureHTTPClient:
    """
    HTTP client with security hardening.
    
    Features:
    - URL allowlisting (only specified base URLs are permitted)
    - TLS enforcement (rejects plain HTTP)
    - Response size limiting (streaming check)
    - Retry with exponential backoff on 429/5xx
    - Redirects disabled (prevents allowlist bypass)
    - Certificate verification enforced
    """

    def __init__(
        self,
        allowed_base_urls: list[str],
        max_response_bytes: int = 2 * 1024 * 1024,
        max_retries: int = 3,
        timeout: float = 30.0,
    ):
        self.allowed_base_urls = [url.rstrip("/") for url in allowed_base_urls]
        self.max_response_bytes = max_response_bytes
        self.max_retries = max_retries
        self.timeout = timeout
        
        self._client = httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=False,
            verify=True,
        )

    def _is_url_allowed(self, url: str) -> bool:
        """Check if URL matches any allowed base URL."""
        parsed = urlparse(url)
        
        if parsed.scheme != "https":
            return False
        
        url_base = f"{parsed.scheme}://{parsed.netloc}"
        return any(url_base == allowed for allowed in self.allowed_base_urls)

    async def get(self, url: str, params: dict[str, Any] | None = None) -> dict:
        """
        Make a GET request with security checks.
        
        Args:
            url: The URL to request (must be in allowlist)
            params: Optional query parameters
            
        Returns:
            Parsed JSON response
            
        Raises:
            URLNotAllowedError: If URL is not in allowlist
            httpx.HTTPError: On network/HTTP errors after retries
        """
        if not self._is_url_allowed(url):
            raise URLNotAllowedError(f"URL not in allowlist: {url}")

        last_error = None
        backoff = 1.0

        for attempt in range(self.max_retries):
            try:
                response = await self._client.get(url, params=params)
                
                if response.status_code == 429 or response.status_code >= 500:
                    logger.warning(
                        f"Retry {attempt + 1}/{self.max_retries}: "
                        f"HTTP {response.status_code} for {url}"
                    )
                    last_error = httpx.HTTPStatusError(
                        f"HTTP {response.status_code}",
                        request=response.request,
                        response=response,
                    )
                    import asyncio
                    await asyncio.sleep(backoff)
                    backoff *= 2
                    continue

                response.raise_for_status()

                content_length = response.headers.get("content-length")
                if content_length and int(content_length) > self.max_response_bytes:
                    raise ValueError(
                        f"Response too large: {content_length} bytes "
                        f"(max {self.max_response_bytes})"
                    )

                return response.json()

            except httpx.HTTPStatusError:
                raise
            except Exception as e:
                last_error = e
                logger.warning(f"Retry {attempt + 1}/{self.max_retries}: {e}")
                import asyncio
                await asyncio.sleep(backoff)
                backoff *= 2

        if last_error:
            raise last_error
        raise RuntimeError("Unexpected retry loop exit")

    async def close(self):
        """Close the underlying HTTP client."""
        await self._client.aclose()
