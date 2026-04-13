"""Redis Streams event bus implementation for AgentBench."""

from __future__ import annotations

import contextlib
import json
import logging
from collections.abc import AsyncIterator
from typing import Any

# CRITICAL: Must import redis at module level for exception handling
import redis.asyncio as redis_module

from agentbench.events.types import (
    STREAM_KEYS,
    EventEnvelope,
    get_stream_for_event,
    validate_event_envelope,
    validate_payload,
)

logger = logging.getLogger(__name__)


class EventBus:
    """Redis Streams event bus for AgentBench."""

    def __init__(self, redis_client) -> None:
        """Initialize the event bus.

        Args:
            redis_client: Configured Redis async client.
        """
        self._redis = redis_client
        self._logger = logging.getLogger(self.__class__.__name__)

    async def publish(
        self,
        stream: str,
        event: EventEnvelope,
        max_len: int | None = 10000,
    ) -> str:
        """Publish an event to a Redis Stream."""
        if stream not in STREAM_KEYS:
            raise ValueError(f"Invalid stream '{stream}'")

        expected_stream = get_stream_for_event(event.event_type)
        if stream != expected_stream:
            raise ValueError(
                f"Event type '{event.event_type}' should be published to '{expected_stream}'"
            )

        validate_event_envelope(event)

        if "run_id" in event.payload and event.correlation_id != event.payload["run_id"]:
            raise ValueError("correlation_id must equal run_id")

        validate_payload(event.payload)

        try:
            fields = {"data": json.dumps(event.model_dump())}
            message_id = await self._redis.xadd(stream, fields, maxlen=max_len, approximate=True)

            self._logger.info(
                "Published event",
                extra={
                    "event_type": event.event_type,
                    "stream": stream,
                    "correlation_id": event.correlation_id,
                    "message_id": message_id,
                },
            )
            return message_id
        except Exception as e:
            self._logger.error(
                "Failed to publish event",
                extra={
                    "event_type": event.event_type,
                    "stream": stream,
                    "correlation_id": event.correlation_id,
                    "error": str(e),
                },
            )
            raise

    async def consume(
        self,
        stream: str,
        consumer_group: str,
        consumer_name: str,
        auto_create_group: bool = True,
        block_ms: int = 5000,
        count: int = 1,
    ) -> AsyncIterator[EventEnvelope]:
        """Consume events from a Redis Stream."""
        if stream not in STREAM_KEYS:
            raise ValueError(f"Invalid stream '{stream}'")

        # Create consumer group if needed
        if auto_create_group:
            try:
                await self._redis.xgroup_create(stream, consumer_group, id="0", mkstream=True)
            except redis_module.ResponseError as e:
                if "already exists" not in str(e):
                    raise

        while True:
            try:
                messages = await self._redis.xreadgroup(
                    groupname=consumer_group,
                    consumername=consumer_name,
                    streams={stream: ">"},
                    count=count,
                    block=block_ms,
                )

                if not messages:
                    continue

                for _stream_name, entries in messages:
                    for message_id, fields in entries:
                        try:
                            event = self._deserialize_event(fields)
                            event.__dict__["_message_id"] = message_id
                            event.__dict__["_stream"] = stream
                            event.__dict__["_consumer_group"] = consumer_group

                            self._logger.info(
                                "Consuming event",
                                extra={
                                    "event_type": event.event_type,
                                    "stream": stream,
                                    "consumer_group": consumer_group,
                                    "consumer_name": consumer_name,
                                    "correlation_id": event.correlation_id,
                                    "message_id": message_id,
                                },
                            )

                            yield event

                        except Exception as e:
                            self._logger.error(
                                "Failed to deserialize event",
                                extra={
                                    "stream": stream,
                                    "message_id": message_id,
                                    "error": str(e),
                                    "fields": fields,
                                },
                            )
                            with contextlib.suppress(Exception):
                                await self._redis.xack(stream, consumer_group, message_id)

            except redis_module.RedisError as e:
                self._logger.error(
                    "Redis error in consume loop",
                    extra={
                        "stream": stream,
                        "consumer_group": consumer_group,
                        "error": str(e),
                    },
                )
                import asyncio

                await asyncio.sleep(1)
            except Exception as e:
                self._logger.error(
                    "Unexpected error in consume loop",
                    extra={
                        "stream": stream,
                        "consumer_group": consumer_group,
                        "error": str(e),
                    },
                )
                import asyncio

                await asyncio.sleep(1)

    def _deserialize_event(self, fields: dict[str, Any]) -> EventEnvelope:
        """Deserialize event from Redis stream fields."""
        if b"data" in fields:
            data = json.loads(fields[b"data"])
        elif "data" in fields:
            data = json.loads(fields["data"])
        else:
            raise ValueError(f"No 'data' field in message: {fields}")

        return EventEnvelope(**data)

    async def ack(
        self,
        stream: str,
        group: str,
        message_id: bytes | str,
    ) -> int:
        """Acknowledge a message."""
        try:
            result = await self._redis.xack(stream, group, message_id)
            self._logger.debug(
                "Acknowledged message",
                extra={
                    "stream": stream,
                    "group": group,
                    "message_id": message_id,
                },
            )
            return result
        except Exception as e:
            self._logger.error(
                "Failed to acknowledge message",
                extra={
                    "stream": stream,
                    "group": group,
                    "message_id": message_id,
                    "error": str(e),
                },
            )
            raise


__all__ = ["EventBus"]
