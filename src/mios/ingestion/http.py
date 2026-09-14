"""Minimal HTTP client over the standard library (Constitution Art.8:
no HTTP framework dependency for GET-and-parse workloads).

Supports timeouts, custom headers and conditional GET (ETag /
Last-Modified, MSD §15.3). https/http only.
"""

import urllib.error
import urllib.request
from dataclasses import dataclass, field

from mios.common.errors import MiosError

#: Identifies the collector to the servers it reads. Some agencies — the
#: BLS among them — refuse requests whose agent does not say who is asking,
#: so this is a working requirement rather than politeness.
DEFAULT_USER_AGENT = "MIOS-collector/1.0 (macro research; +https://github.com/samkaz15/invest)"


class TransportError(MiosError):
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

    def get(
        self,
        url: str,
        headers: dict[str, str] | None = None,
        encoding: str | None = None,
    ) -> HttpResponse:
        """Fetch and decode.

        ``encoding`` overrides what the server declares, and exists because
        some servers declare nothing. Japan's MOF serves its JGB CSV in
        Shift-JIS without saying so, and the UTF-8 fallback turned every
        Japanese tenor header into replacement characters — so the parser
        looked for "2年" in a row that had become mojibake and reported the
        column missing. Decoding is a property of the source, and when the
        source does not state it, the configuration has to.
        """
        if not url.startswith(("https://", "http://")):
            raise TransportError(f"unsupported url scheme: {url!r}")
        request = urllib.request.Request(
            url, headers={"User-Agent": self._user_agent, **(headers or {})}
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as resp:
                charset = encoding or resp.headers.get_content_charset() or "utf-8"
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
