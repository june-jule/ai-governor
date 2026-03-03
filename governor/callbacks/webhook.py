"""Webhook event callback for Governor transitions.

Sends HTTP POST notifications when transitions occur. Designed to be
used with the ``event_callbacks`` parameter of ``TransitionEngine``.

Usage::

    from governor.callbacks.webhook import WebhookCallback

    webhook = WebhookCallback(
        url="https://example.com/hooks/governor",
        secret="my-signing-secret",  # optional HMAC-SHA256 signing
    )

    engine = TransitionEngine(
        backend=backend,
        event_callbacks=[webhook],
    )

The webhook payload is JSON with the following shape::

    {
        "event_type": "transition",
        "event_config": {...},
        "task_id": "TASK_001",
        "task": {...},
        "transition_params": {...},
        "timestamp": "2026-03-03T12:00:00Z"
    }

When ``secret`` is provided, requests include an ``X-Governor-Signature``
header containing ``sha256=<hex_digest>`` computed over the request body.
"""

import hashlib
import hmac
import json
import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.request import Request, urlopen
from urllib.error import URLError

logger = logging.getLogger("governor.callbacks.webhook")


class WebhookCallback:
    """HTTP webhook event callback.

    Args:
        url: Webhook endpoint URL.
        secret: Optional HMAC-SHA256 signing secret. When provided,
            each request includes an ``X-Governor-Signature`` header.
        timeout_seconds: HTTP request timeout. Default 10.
        retry_count: Number of retries on failure. Default 1.
        retry_delay_seconds: Delay between retries. Default 1.0.
        headers: Additional HTTP headers to include.
        async_dispatch: If True (default), send webhooks in a background
            thread to avoid blocking the transition. If False, send
            synchronously (blocks until complete or timeout).
        event_filter: Optional list of event types to send. If None,
            all events are sent. Example: ``["transition", "notification"]``.
    """

    def __init__(
        self,
        url: str,
        secret: Optional[str] = None,
        timeout_seconds: float = 10.0,
        retry_count: int = 1,
        retry_delay_seconds: float = 1.0,
        headers: Optional[Dict[str, str]] = None,
        async_dispatch: bool = True,
        event_filter: Optional[List[str]] = None,
    ) -> None:
        self._url = url
        self._secret = secret.encode("utf-8") if secret else None
        self._timeout = max(1.0, timeout_seconds)
        self._retry_count = max(0, retry_count)
        self._retry_delay = max(0.0, retry_delay_seconds)
        self._headers = headers or {}
        self._async = async_dispatch
        self._event_filter = set(event_filter) if event_filter else None

    def __call__(
        self,
        event_type: str,
        config: Dict[str, Any],
        task_id: str,
        task: Dict[str, Any],
        transition_params: Dict[str, Any],
    ) -> None:
        """Event callback interface — called by TransitionEngine after transitions."""
        if self._event_filter is not None and event_type not in self._event_filter:
            return

        payload = {
            "event_type": event_type,
            "event_config": config,
            "task_id": task_id,
            "task": _safe_serialize(task),
            "transition_params": _safe_serialize(transition_params),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        if self._async:
            thread = threading.Thread(
                target=self._send_with_retry,
                args=(payload,),
                daemon=True,
                name=f"governor-webhook-{task_id[:20]}",
            )
            thread.start()
        else:
            self._send_with_retry(payload)

    def _send_with_retry(self, payload: Dict[str, Any]) -> None:
        body = json.dumps(payload, default=str).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "Governor-Webhook/1.0",
            **self._headers,
        }

        if self._secret is not None:
            signature = hmac.new(self._secret, body, hashlib.sha256).hexdigest()
            headers["X-Governor-Signature"] = f"sha256={signature}"

        for attempt in range(1 + self._retry_count):
            try:
                req = Request(
                    self._url,
                    data=body,
                    headers=headers,
                    method="POST",
                )
                with urlopen(req, timeout=self._timeout) as resp:
                    status = resp.status
                    if 200 <= status < 300:
                        logger.debug(
                            "Webhook delivered to %s (status=%s, task=%s)",
                            self._url, status, payload.get("task_id"),
                        )
                        return
                    logger.warning(
                        "Webhook %s returned status %s (attempt %s/%s)",
                        self._url, status, attempt + 1, 1 + self._retry_count,
                    )
            except URLError as e:
                logger.warning(
                    "Webhook %s failed (attempt %s/%s): %s",
                    self._url, attempt + 1, 1 + self._retry_count, e,
                )
            except Exception as e:
                logger.error(
                    "Webhook %s unexpected error (attempt %s/%s): %s",
                    self._url, attempt + 1, 1 + self._retry_count, e,
                )

            if attempt < self._retry_count:
                time.sleep(self._retry_delay)

        logger.error(
            "Webhook %s exhausted all retries for task %s",
            self._url, payload.get("task_id"),
        )


def _safe_serialize(obj: Any) -> Any:
    """Convert an object to JSON-safe types."""
    if isinstance(obj, dict):
        return {k: _safe_serialize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_safe_serialize(v) for v in obj]
    if isinstance(obj, (str, int, float, bool, type(None))):
        return obj
    return str(obj)
