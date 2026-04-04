"""Redis Streams event bus implementation for AgentBench.

This module provides the EventBus class for publishing and consuming events
via Redis Streams, with support for consumer groups, correlation ID logging,
and payload validation.
"""

from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any, AsyncIterator

if TYPE_CHECKING:
    import redis.asyncio as redis

from agentbench.events.types import (
    STREAM_KEYS,
    EventEnvelope,
    get_stream_for_event,
    validate_event_envelope,
    validate_payload,
)
from agentbench.models.events import VALID_EVENT_TYPES

logger = logging.getLogger(__name__)


class EventBus:
    """Redis Streams event bus for AgentBench.

    The EventBus provides:
    - Publishing events to appropriate streams
    - Consuming events with consumer groups
    - Automatic acknowledgment of processed messages
    - Correlation ID preservation and logging
    - Payload validation

    Usage:
        bus = EventBus(redis_client)

        # Publishing
        await bus.publish("stream:eval-runs", event_envelope)

        # Consuming
        async for event in bus.consume("stream:eval-runs", "my-group", "consumer-1"):
            # Process event
            await bus.ack("stream:eval-runs", "my-group", event.message_id)
    """

    def __init__(self, redis_client: "redis.Redis") -> None:
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
        """Publish an event to a Redis Stream.

        Args:
            stream: The stream key (e.g., "stream:eval-runs").
            event: The EventEnvelope to publish.
            max_len: Maximum stream length for trimming (approximate).
                    Set to None to disable trimming.

        Returns:
            The message ID assigned by Redis.

        Raises:
            ValueError: If stream is invalid or event fails validation.
            redis.RedisError: If Redis operation fails.
        """
        # Validate stream
        if stream not in STREAM_KEYS:
            raise ValueError(f"Invalid stream '{stream}'. Must be one of: {', '.join(STREAM_KEYS)}")

        # Validate event type matches stream
        expected_stream = get_stream_for_event(event.event_type)
        if stream != expected_stream:
            raise ValueError(
                f"Event type '{event.event_type}' should be published to "
                f"'{expected_stream}', not '{stream}'"
            )

        # Validate envelope (including payload)
        validate_event_envelope(event)

        # Correlation ID preservation: all events must carry correlation_id = run_id
        if "run_id" in event.payload:
            if event.correlation_id != event.payload["run_id"]:
                raise ValueError(
                    f"correlation_id ({event.correlation_id}) must equal "
                    f"run_id ({event.payload['run_id']})"
                )

        # Serialize event to JSON
        event_data = {
            "event_id": event.event_id,
            "event_type": event.event_type,
            "schema_version": event.schema_version,
            "timestamp": event.timestamp,
            "correlation_id": event.correlation_id,
            "payload": json.dumps(event.payload),  # Payload as JSON string
        }

        # Publish to Redis Stream
        try:
            if max_len:
                # XADD with MAXLEN ~ for approximate trimming
                message_id = await self._redis.xadd(
                    stream, event_data, maxlen=max_len, approximate=True
                )
            else:
                message_id = await self._redis.xadd(stream, event_data)

            self._logger.debug(
                "Published event",
                extra={
                    "event_type": event.event_type,
                    "stream": stream,
                    "message_id": message_id,
                    "correlation_id": event.correlation_id,
                },
            )

            return str(message_id)

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

    @asynccontextmanager
    async def consume(
        self,
        stream: str,
        consumer_group: str,
        consumer_name: str,
        auto_create_group: bool = True,
        block_ms: int = 5000,
        count: int = 1,
    ) -> AsyncIterator[EventEnvelope]:
        """Consume events from a Redis Stream as part of a consumer group.

        This is an async context manager that yields EventEnvelope objects.
        Messages must be acknowledged using ack() after processing.

        Args:
            stream: The stream key to consume from.
            consumer_group: Name of the consumer group.
            consumer_name: Unique name for this consumer instance.
            auto_create_group: Whether to create the group if it doesn't exist.
            block_ms: Milliseconds to block waiting for messages.
            count: Maximum number of messages to fetch per call.

        Yields:
            EventEnvelope objects with an added 'message_id' attribute.

        Raises:
            ValueError: If stream is invalid.
            redis.RedisError: If Redis operation fails.
        """
        if stream not in STREAM_KEYS:
            raise ValueError(f"Invalid stream '{stream}'. Must be one of: {', '.join(STREAM_KEYS)}")

        # Create consumer group if needed
        if auto_create_group:
            try:
                await self._redis.xgroup_create(stream, consumer_group, id="0", mkstream=True)
            except redis.ResponseError as e:
                if "already exists" not in str(e):
                    raise

        while True:
            try:
                # Read from consumer group
                messages = await self._redis.xreadgroup(
                    groupname=consumer_group,
                    consumername=consumer_name,
                    streams={stream: ">"},  # ">" means undelivered messages
                    count=count,
                    block=block_ms,
                )

                if not messages:
                    continue

                for stream_name, entries in messages:
                    for message_id, fields in entries:
                        try:
                            event = self._deserialize_event(fields)
                            # Attach message_id for acknowledgment
                            event.__dict__["_message_id"] = message_id
                            event.__dict__["_stream"] = stream
                            event.__dict__["_consumer_group"] = consumer_group

                            # All consumers must log correlation_id
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
                            # Acknowledge invalid messages to avoid reprocessing
                            try:
                                await self.ack(stream, consumer_group, message_id)
                            except Exception:
                                pass

            except redis.RedisError:
                self._logger.exception("Redis error during consume")
                raise

    async def ack(
        self,
        stream: str,
        group: str,
        message_id: str | bytes,
    ) -> None:
        """Acknowledge a message has been processed.

        Args:
            stream: The stream key.
            group: The consumer group name.
            message_id: The message ID to acknowledge.

        Raises:
            redis.RedisError: If Redis operation fails.
        """
        await self._redis.xack(stream, group, message_id)
        self._logger.debug(
            "Acknowledged message",
            extra={
                "stream": stream,
                "group": group,
                "message_id": message_id,
            },
        )

    def _deserialize_event(self, fields: dict[bytes, bytes]) -> EventEnvelope:
        """Deserialize event data from Redis stream fields.

        Args:
            fields: Raw field data from Redis (bytes keys and values).

        Returns:
            Deserialized EventEnvelope.

        Raises:
            ValueError: If deserialization fails.
        """
        # Decode bytes to strings
        data: dict[str, Any] = {}
        for key, value in fields.items():
            key_str = key.decode("utf-8") if isinstance(key, bytes) else key
            value_str = value.decode("utf-8") if isinstance(value, bytes) else value
            data[key_str] = value_str

        # Parse payload JSON
        payload_json = data.get("payload", "{}")
        try:
            payload = json.loads(payload_json)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid payload JSON: {e}") from e

        return EventEnvelope(
            event_id=data["event_id"],
            event_type=data["event_type"],
            schema_version=data.get("schema_version", "1.0"),
            timestamp=data["timestamp"],
            correlation_id=data["correlation_id"],
            payload=payload,
        )

    async def create_consumer_group(
        self,
        stream: str,
        group: str,
        start_from: str = "0",
        mkstream: bool = True,
    ) -> bool:
        """Create a consumer group for a stream.

        Args:
            stream: The stream key.
            group: The consumer group name.
            start_from: Starting message ID (default "0" means beginning).
            mkstream: Whether to create the stream if it doesn't exist.

        Returns:
            True if group was created, False if it already exists.

        Raises:
            ValueError: If stream is invalid.
            redis.RedisError: If Redis operation fails.
        """
        if stream not in STREAM_KEYS:
            raise ValueError(f"Invalid stream '{stream}'. Must be one of: {', '.join(STREAM_KEYS)}")

        try:
            await self._redis.xgroup_create(stream, group, id=start_from, mkstream=mkstream)
            self._logger.info(
                "Created consumer group",
                extra={
                    "stream": stream,
                    "group": group,
                    "start_from": start_from,
                },
            )
            return True
        except redis.ResponseError as e:
            if "already exists" in str(e):
                return False
            raise

    async def get_pending_messages(
        self,
        stream: str,
        group: str,
        consumer: str | None = None,
        count: int = 100,
    ) -> list[dict[str, Any]]:
        """Get pending messages for a consumer group.

        Args:
            stream: The stream key.
            group: The consumer group name.
            consumer: Optional specific consumer name.
            count: Maximum number of messages to return.

        Returns:
            List of pending message info dictionaries.

        Raises:
            ValueError: If stream is invalid.
            redis.RedisError: If Redis operation fails.
        """
        if stream not in STREAM_KEYS:
            raise ValueError(f"Invalid stream '{stream}'. Must be one of: {', '.join(STREAM_KEYS)}")

        if consumer:
            pending = await self._redis.xpending_range(
                stream, group, min="-", max="+", count=count, consumername=consumer
            )
        else:
            pending = await self._redis.xpending_range(stream, group, min="-", max="+", count=count)

        return [
            {
                "message_id": p["message_id"],
                "consumer": p["consumer"],
                "time_since_delivered": p["time_since_delivered"],
                "delivery_count": p["delivery_count"],
            }
            for p in (pending or [])
        ]


__all__ = [
    "EventBus",
]
