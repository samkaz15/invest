"""Minimal HTTP client over the standard library (Constitution Art.8:
no HTTP framework dependency for GET-and-parse workloads).

Supports timeouts, custom headers and conditional GET (ETag /
Last-Modified, MSD §15.3). https/http only.
"""

import urllib.error
import urllib.request
from dataclasses import dataclass, field

from bios.common.errors import BiosError

DEFAULT_USER_AGENT = "BIOS-collector/0.1 (personal research; contact: repo owner)"


class TransportError(BiosError):
    """Network / HTTP-level failure (retryable)."""


@dataclass(frozen=True)
class HttpResponse:
    status: int
    text: str
    headers: dict[str, str] = field(default_factory=dict)  # keys lowercased

    @property
    def not_modified(self) -> bool:
        return self.status == 304


class HttpClient:
    def __init__(self, timeout_seconds: float = 30.0, user_agent: str = DEFAULT_USER_AGENT):
        self._timeout = timeout_seconds
        self._user_agent = user_agent

    def get(self, url: str, headers: dict[str, str] | None = None) -> HttpResponse:
        if not url.startswith(("https://", "http://")):
            raise TransportError(f"unsupported url scheme: {url!r}")
        request = urllib.request.Request(
            url, headers={"User-Agent": self._user_agent, **(headers or {})}
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as resp:
                charset = resp.headers.get_content_charset() or "utf-8"
                return HttpResponse(
                    status=resp.status,
                    text=resp.read().decode(charset, errors="replace"),
                    headers={k.lower(): v for k, v in resp.headers.items()},
                )
        except urllib.error.HTTPError as exc:
            if exc.code == 304:
                return HttpResponse(status=304, text="")
            raise TransportError(f"HTTP {exc.code} from {url}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise TransportError(f"transport failure for {url}: {exc}") from exc
