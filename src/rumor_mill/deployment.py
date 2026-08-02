"""Deployment verification helpers."""

import json
from collections.abc import Callable
from typing import Any
from urllib.request import urlopen


def smoke(base_url: str, opener: Callable[..., Any] = urlopen) -> None:
    """Require healthy components and the complete public launch surface."""
    base_url = base_url.rstrip("/")
    for path in ("/health/live", "/health/ready"):
        with opener(f"{base_url}{path}", timeout=15) as response:
            if response.status != 200:
                raise RuntimeError(f"{path} returned HTTP {response.status}")
            payload = json.loads(response.read())
            if payload["status"] != "ok":
                raise RuntimeError(f"{path} reported {payload['status']}")
    for path in ("/static/lighthouse.css", "/static/favicon.svg"):
        with opener(f"{base_url}{path}", timeout=15) as response:
            if response.status != 200 or not response.read():
                raise RuntimeError(f"{path} static asset smoke check failed")
    for path, marker in (
        ("/lighthouse", b'property="og:title"'),
        ("/lighthouse/today", b'property="og:title"'),
        ("/lighthouse/town", b'property="og:title"'),
        ("/lighthouse/archive", b'property="og:title"'),
        ("/lighthouse/feedback", b"Share feedback on GitHub"),
    ):
        with opener(f"{base_url}{path}", timeout=15) as response:
            if response.status != 200 or marker not in response.read():
                raise RuntimeError(f"{path} public-page smoke check failed")
