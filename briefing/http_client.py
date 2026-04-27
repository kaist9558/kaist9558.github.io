from __future__ import annotations

import logging

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .config import REQUEST_RETRIES, REQUEST_TIMEOUT, USER_AGENT

log = logging.getLogger(__name__)


def make_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    retry = Retry(
        total=REQUEST_RETRIES,
        backoff_factor=1.0,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET", "HEAD"),
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


def get(session: requests.Session, url: str, *, encoding: str | None = None) -> requests.Response | None:
    try:
        res = session.get(url, timeout=REQUEST_TIMEOUT)
        res.raise_for_status()
    except requests.RequestException as exc:
        log.warning("GET %s failed: %s", url, exc)
        return None
    if encoding:
        res.encoding = encoding
    elif not res.encoding or res.encoding.lower() == "iso-8859-1":
        res.encoding = res.apparent_encoding or "utf-8"
    return res
