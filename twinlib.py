"""Tiny shared helper: emit a URI event to the eventbus (stdlib only)."""
from __future__ import annotations

import json
import os
import urllib.request

EVENTBUS = os.environ.get("EVENTBUS_URL", "http://eventbus:9800")


def emit(uri: str, actor: str = "system", **payload) -> None:
    body = json.dumps({"uri": uri, "actor": actor, "payload": payload}).encode()
    req = urllib.request.Request(f"{EVENTBUS}/emit", data=body,
                                 headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=3).read()
    except Exception:
        pass  # the twin keeps working even if the recorder is down
