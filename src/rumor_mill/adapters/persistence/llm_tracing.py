"""Independent durable storage for opt-in LLM request and response tracing."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session, sessionmaker

from rumor_mill.adapters.persistence.models import LlmTraceMessageModel

logger = logging.getLogger(__name__)


class SqlAlchemyLlmTraceStore:
    """Commit trace rows independently from application transactions."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def record_outbound(
        self,
        *,
        call_id: UUID,
        provider: str,
        model: str,
        purpose: str,
        messages: Sequence[dict[str, Any]],
    ) -> None:
        rows = [
            LlmTraceMessageModel(
                call_id=call_id,
                direction="outbound",
                sequence=sequence,
                provider=provider,
                model=model,
                purpose=purpose,
                item_type="message",
                role=str(message.get("role")) if message.get("role") is not None else None,
                payload=message,
            )
            for sequence, message in enumerate(messages)
        ]
        self._commit(rows)

    def record_inbound(
        self,
        *,
        call_id: UUID,
        sequence: int,
        provider: str,
        model: str,
        purpose: str,
        item_type: str,
        payload: dict[str, Any],
        duration_ms: int | None = None,
    ) -> None:
        self._commit(
            [
                LlmTraceMessageModel(
                    call_id=call_id,
                    direction="inbound",
                    sequence=sequence,
                    provider=provider,
                    model=model,
                    purpose=purpose,
                    item_type=item_type,
                    payload=payload,
                    duration_ms=duration_ms,
                )
            ]
        )

    def _commit(self, rows: Sequence[LlmTraceMessageModel]) -> None:
        try:
            with self._session_factory() as database:
                database.add_all(rows)
                database.commit()
        except Exception:
            # Tracing is diagnostic and must never make a model call fail.
            logger.exception("llm_trace_write_failed")
