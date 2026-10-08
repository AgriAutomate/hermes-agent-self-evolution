"""Bounded model requests with exclusive, UTF-8 request/response receipts.

The cap counts dispatch attempts, including failures: retrying a timed-out
client cannot recover the budget of a request the provider may have processed.
Currency costs are not invented; provider-reported model/usage are retained.
"""

from __future__ import annotations

import hashlib
import json
import threading
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


class BudgetExhausted(RuntimeError):
    pass


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, ensure_ascii=False, allow_nan=False, indent=2)
        handle.write("\n")


class RequestLedger:
    def __init__(self, directory: Path, max_calls: int = 0, budget_note: str = ""):
        if (
            isinstance(max_calls, bool)
            or not isinstance(max_calls, int)
            or max_calls < 0
        ):
            raise ValueError("max_calls must be a nonnegative integer")
        if max_calls and not budget_note.strip():
            raise ValueError("live requests require an explicit budget note")
        self.directory = Path(directory)
        self.max_calls = max_calls
        self.budget_note = budget_note
        self.calls = 0
        self._lock = threading.Lock()

    def post_json(
        self, endpoint: str, payload: dict, api_key: str, timeout: int = 30
    ) -> dict:
        body = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
        if len(body) > 120_000:
            raise ValueError("request exceeds the local 120000-byte limit")
        if not api_key:
            raise ValueError("API key is unavailable")
        with self._lock:
            if self.calls >= self.max_calls:
                raise BudgetExhausted("model dispatch cap reached")
            receipt_id = str(uuid4())
            write_json(
                self.directory / f"{receipt_id}-request.json",
                {
                    "receipt_id": receipt_id,
                    "started_at": datetime.now(timezone.utc).isoformat(),
                    "requested_model": payload.get("model"),
                    "request_hash": hashlib.sha256(body).hexdigest(),
                    "request_bytes": len(body),
                    "budget_note": self.budget_note,
                    "request": payload,
                },
            )
            self.calls += 1
        req = urllib.request.Request(
            endpoint,
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
        )
        status = None
        response = None
        error = None
        try:
            with urllib.request.urlopen(req, timeout=timeout) as result:
                status = result.status
                response = json.loads(result.read().decode("utf-8"))
            if not isinstance(response, dict):
                raise ValueError("model response is not an object")
            return response
        except Exception as cause:
            status = getattr(cause, "code", status)
            error = type(cause).__name__
            raise
        finally:
            # Headers are never persisted. Redact any exact credential echo.
            safe_response = json.loads(
                json.dumps(response).replace(api_key, "[REDACTED]")
            )
            write_json(
                self.directory / f"{receipt_id}-response.json",
                {
                    "receipt_id": receipt_id,
                    "finished_at": datetime.now(timezone.utc).isoformat(),
                    "http_status": status,
                    "returned_model": response.get("model")
                    if isinstance(response, dict)
                    else None,
                    "usage": response.get("usage")
                    if isinstance(response, dict)
                    else None,
                    "response": safe_response,
                    "error": error,
                },
            )
