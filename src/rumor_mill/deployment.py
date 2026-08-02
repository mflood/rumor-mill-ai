"""Deployment verification helpers."""

import json
import re
from collections.abc import Callable
from http.cookiejar import CookieJar
from typing import Any
from urllib.request import HTTPCookieProcessor, Request, build_opener


def smoke(base_url: str, opener: Callable[..., Any] | None = None) -> None:
    """Require healthy components and the complete public launch surface."""
    base_url = base_url.rstrip("/")
    if opener is None:
        opener = build_opener(HTTPCookieProcessor(CookieJar())).open  # pragma: no cover
    for path in ("/health/live", "/health/ready", "/health/product"):
        with opener(f"{base_url}{path}", timeout=15) as response:
            if response.status != 200:
                raise RuntimeError(f"{path} returned HTTP {response.status}")
            payload = json.loads(response.read())
            if payload["status"] != "ok":
                raise RuntimeError(f"{path} reported {payload['status']}")
            if (
                path == "/health/ready"
                and payload.get("components", {}).get("story_pipeline") != "ok"
            ):
                raise RuntimeError("/health/ready did not verify autonomous story progression")
    for path in ("/static/lighthouse.css", "/static/favicon.svg"):
        with opener(f"{base_url}{path}", timeout=15) as response:
            if response.status != 200 or not response.read():
                raise RuntimeError(f"{path} static asset smoke check failed")
    for path, marker in (
        ("/lighthouse", b'property="og:title"'),
        ("/lighthouse/feedback", b"Share feedback on GitHub"),
    ):
        with opener(f"{base_url}{path}", timeout=15) as response:
            if response.status != 200 or marker not in response.read():
                raise RuntimeError(f"{path} public-page smoke check failed")

    request = Request(f"{base_url}/lighthouse/session", data=b"", method="POST")
    with opener(request, timeout=15) as response:
        body = response.read()
        final_url = response.geturl()
        if response.status != 200 or not final_url.endswith("/lighthouse/today"):
            raise RuntimeError("visitor entry did not redirect to /lighthouse/today")
        if b'property="og:title"' not in body:
            raise RuntimeError("/lighthouse/today playable-page smoke check failed")

    destination = re.search(
        rb'href="(/lighthouse/runs/[^"?#]+/(?:town/[^"?#]+|people/[^"?#]+))"', body
    )
    if destination is None:
        raise RuntimeError("/lighthouse/today exposed no location or character destination")
    path = destination.group(1).decode("ascii")
    with opener(f"{base_url}{path}", timeout=15) as response:
        if response.status != 200 or not response.read():
            raise RuntimeError(f"{path} playable destination smoke check failed")
