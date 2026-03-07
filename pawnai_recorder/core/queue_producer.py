"""PawnQueue producer integration for PawnAI Recorder.

Bridges the async :class:`pawn_queue.PawnQueue` API into the synchronous
recording threads via a dedicated daemon thread that runs its own asyncio
event loop for the lifetime of the recording session.

Configuration (in ``.pawnai-recorder.yml``)
--------------------------------------------
The ``queue:`` top-level section enables publishing.  S3 credentials are
reused from the existing ``s3:`` section — no duplication required::

    s3:
      bucket: my-bucket
      endpoint_url: https://s3.example.com
      access_key: AK…
      secret_key: SK…

    queue:
      enabled: true
      topic: pawnai-jobs
      transcribe_diarize:
        threshold: 0.2
        cross_file_threshold: 0.2
        device: cpu
      analyze:
        mode: summary
        model: gpt-4o

Message flow per recording session
-----------------------------------
For every uploaded chunk a ``transcribe-diarize`` command is published::

    {
      "command": "transcribe-diarize",
      "audio_paths": ["s3://bucket/session/session_01.flac"],
      "threshold": 0.2,
      "cross_file_threshold": 0.2,
      "session": "my-session-label",
      "device": "cpu"
    }

When all chunks are uploaded, an ``analyze`` command is published::

    {
      "command": "analyze",
      "session": "my-session-label",
      "mode": "summary",
      "model": "gpt-4o"
    }

Finally a ``sync-siyuan`` command closes the pipeline::

    {
      "command": "sync-siyuan",
      "session": "my-session-label"
    }
"""

import asyncio
import threading
from typing import TYPE_CHECKING, Any, Dict, Optional

from loguru import logger

if TYPE_CHECKING:
    from pawn_queue import PawnQueue, Producer


def _map_s3_config(s3_cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Map recorder S3 config keys to PawnQueueConfig S3 field names.

    The recorder uses the field names ``bucket``, ``access_key``, ``secret_key``
    and ``region``; PawnQueue expects ``bucket_name``, ``aws_access_key_id``,
    ``aws_secret_access_key`` and ``region_name``.

    Args:
        s3_cfg: Recorder-style S3 configuration dict.

    Returns:
        PawnQueue-compatible S3 dict suitable for ``PawnQueueConfig``.
    """
    key_map = {
        "bucket":     "bucket_name",
        "access_key": "aws_access_key_id",
        "secret_key": "aws_secret_access_key",
        "region":     "region_name",
    }
    result: Dict[str, Any] = {}
    for recorder_key, pq_key in key_map.items():
        if recorder_key in s3_cfg:
            result[pq_key] = s3_cfg[recorder_key]

    # Pass-through fields that already have the right name
    for key in ("endpoint_url", "bucket_name", "aws_access_key_id",
                "aws_secret_access_key", "region_name"):
        if key in s3_cfg and key not in result:
            result[key] = s3_cfg[key]

    # Map verify_ssl → use_ssl
    if "verify_ssl" in s3_cfg and "use_ssl" not in result:
        result["use_ssl"] = bool(s3_cfg["verify_ssl"])

    return result


class SessionQueueProducer:
    """Synchronous façade over the async PawnQueue producer.

    Opens and holds a single :class:`pawn_queue.PawnQueue` client for the
    duration of the recording session.  All async calls are dispatched to a
    private daemon thread that owns a persistent :class:`asyncio.AbstractEventLoop`,
    so the calling code (recording save-threads) never needs to be async-aware.

    Args:
        s3_config: Recorder-style S3 config dict.  Keys recognised:
            ``bucket``, ``access_key``, ``secret_key``, ``endpoint_url``,
            ``region``, ``verify_ssl``.
        topic: PawnQueue topic name to publish messages to.
        producer_name: Logical producer name registered in the queue registry.
            Defaults to ``"pawnai-recorder"``.

    Raises:
        Exception: If the PawnQueue client cannot be initialised within the
            setup timeout (30 s).  Recording is aborted when this happens.
    """

    def __init__(
        self,
        s3_config: Dict[str, Any],
        topic: str,
        producer_name: str = "pawnai-recorder",
    ) -> None:
        self._topic = topic
        self._producer_name = producer_name
        self._pq_s3_config = _map_s3_config(s3_config)
        self._bucket = self._pq_s3_config.get("bucket_name", "")

        self._pq: Optional["PawnQueue"] = None
        self._producer: Optional["Producer"] = None

        # Private event loop on a daemon thread
        self._loop: asyncio.AbstractEventLoop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._run_loop,
            daemon=True,
            name="pawn-queue-loop",
        )
        self._thread.start()

        # Block until the PawnQueue client is ready (or raise on failure)
        future = asyncio.run_coroutine_threadsafe(self._setup(), self._loop)
        try:
            future.result(timeout=30)
        except Exception as exc:
            logger.error(f"PawnQueue setup failed: {exc}")
            self._stop_loop()
            raise

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _run_loop(self) -> None:
        """Entry point for the background event-loop thread."""
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    async def _setup(self) -> None:
        """Async initialisation: connect, create topic, register producer."""
        from pawn_queue import PawnQueue  # local import — optional dependency

        config_dict = {"s3": self._pq_s3_config}
        self._pq = await PawnQueue.from_config(config_dict)
        await self._pq.setup()
        await self._pq.create_topic(self._topic)
        self._producer = await self._pq.register_producer(self._producer_name)
        logger.info(
            f"PawnQueue producer ready: topic={self._topic!r}, "
            f"producer_id={self._producer.id}"
        )

    def _stop_loop(self) -> None:
        """Stop the background event loop and join its thread."""
        if self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=5)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def publish(self, payload: Dict[str, Any]) -> None:
        """Fire-and-forget publish of an arbitrary payload dict.

        Submits the coroutine to the background event loop and returns
        immediately.  Publish errors are logged as warnings but never raised,
        so a queue failure never interrupts the audio recording.

        Args:
            payload: Arbitrary JSON-serialisable dict to send as the message
                payload.  Must include a ``"command"`` key so the consumer
                knows how to route it (e.g. ``"transcribe-diarize"``,
                ``"analyze"``, ``"sync-siyuan"``).
        """
        if self._producer is None:
            logger.warning(
                "PawnQueue producer not initialised; dropping message (command=%s)",
                payload.get("command"),
            )
            return

        producer = self._producer  # capture for closure — avoids Optional-None issue

        async def _do_publish() -> None:
            try:
                await producer.publish(self._topic, payload)
                logger.debug(
                    "PawnQueue message published: topic=%r command=%s",
                    self._topic, payload.get("command"),
                )
            except Exception as exc:
                logger.warning(
                    "PawnQueue publish failed (command=%s): %s",
                    payload.get("command"), exc,
                )

        asyncio.run_coroutine_threadsafe(_do_publish(), self._loop)

    def close(self) -> None:
        """Gracefully tear down the PawnQueue client and stop the event loop.

        First drains all pending publish tasks so that in-flight messages are
        delivered before the aiohttp connection pool is closed.  Blocks until
        teardown completes (up to 30 s).
        """
        async def _teardown() -> None:
            # Drain every pending task on the loop (e.g. in-flight _do_publish
            # coroutines) before closing the underlying aiohttp session.
            # Without this, tasks that are still connecting/writing get
            # ClientConnectionResetError when pq.teardown() closes the pool.
            current = asyncio.current_task()
            pending = [t for t in asyncio.all_tasks() if t is not current]
            if pending:
                logger.debug(
                    "PawnQueue close: waiting for %d pending task(s)", len(pending)
                )
                await asyncio.gather(*pending, return_exceptions=True)

            if self._pq is not None:
                try:
                    await self._pq.teardown()
                    logger.info("PawnQueue client closed")
                except Exception as exc:
                    logger.warning(f"PawnQueue teardown error: {exc}")

        if self._loop.is_running():
            future = asyncio.run_coroutine_threadsafe(_teardown(), self._loop)
            try:
                future.result(timeout=30)
            except Exception as exc:
                logger.warning(f"PawnQueue teardown timed out: {exc}")

        self._stop_loop()
