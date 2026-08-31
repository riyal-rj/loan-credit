"""`KafkaEventProducer`: thin `aiokafka` wrapper used by the outbox relay.

Mirrors `S3ObjectStore`'s `ensure_ready`/`check_connectivity` convention for `/health/ready`
wiring, except a producer *is* held open for the process lifetime (unlike the per-call S3 client)
because `aiokafka` batches/pipelines writes internally and reconnecting per publish would defeat
that.
"""

from __future__ import annotations

from aiokafka import AIOKafkaProducer


class KafkaEventProducer:
    def __init__(
        self,
        *,
        bootstrap_servers: str,
        security_protocol: str,
        topic: str,
        request_timeout_ms: int = 5000,
    ) -> None:
        self._topic = topic
        self._producer = AIOKafkaProducer(
            bootstrap_servers=bootstrap_servers,
            security_protocol=security_protocol,
            request_timeout_ms=request_timeout_ms,
        )
        self._started = False

    async def ensure_ready(self) -> None:
        if not self._started:
            await self._producer.start()
            self._started = True

    async def check_connectivity(self) -> None:
        # `partitions_for` fetches (and caches) topic metadata over the real connection -- a
        # side-effect-free real round trip, not a pool-state guess.
        await self._producer.partitions_for(self._topic)

    async def publish(self, *, key: str, value: bytes) -> None:
        await self._producer.send_and_wait(self._topic, value=value, key=key.encode("utf-8"))

    async def close(self) -> None:
        if self._started:
            await self._producer.stop()
            self._started = False
