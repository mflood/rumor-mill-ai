"""Deployment verification helpers."""

import json
from collections.abc import Callable
from typing import Any
from urllib.request import urlopen


def smoke(base_url: str, opener: Callable[..., Any] = urlopen) -> None:
    """Require healthy web/worker components and a packaged static asset."""
    base_url = base_url.rstrip("/")
    for path in ("/health/live", "/health/ready"):
        with opener(f"{base_url}{path}", timeout=15) as response:
            if response.status != 200:
                raise RuntimeError(f"{path} returned HTTP {response.status}")
            payload = json.loads(response.read())
            if payload["status"] != "ok":
                raise RuntimeError(f"{path} reported {payload['status']}")
    with opener(f"{base_url}/static/lighthouse.css", timeout=15) as response:
        if response.status != 200 or not response.read():
            raise RuntimeError("static asset smoke check failed")
