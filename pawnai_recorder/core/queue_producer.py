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
      topic: audio-chunks

Message payload (per uploaded chunk)
--------------------------------------
::

    {
      "session_id":     "260303143022",
      "chunk_index":    1,
      "s3_bucket":      "my-bucket",
      "s3_key":         "recordings/260303143022/260303143022_01.flac",
      "conversation_id": "optional-id"   # omitted when None
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

    def publish(
        self,
        session_id: str,
        chunk_index: int,
        s3_key: str,
        conversation_id: Optional[str] = None,
    ) -> None:
        """Fire-and-forget publish of a chunk-uploaded message.

        Submits the coroutine to the background event loop and returns
        immediately.  Publish errors are logged as warnings but never raised,
        so a queue failure never interrupts the audio recording.

        Args:
            session_id: Recording session identifier.
            chunk_index: Sequential chunk number within the session.
            s3_key: S3 object key of the uploaded audio file.
            conversation_id: Optional conversation grouping ID.
        """
        if self._producer is None:
            logger.warning("PawnQueue producer not initialised; dropping message for chunk %d", chunk_index)
            return

        payload: Dict[str, Any] = {
            "session_id":  session_id,
            "chunk_index": chunk_index,
            "s3_bucket":   self._bucket,
            "s3_key":      s3_key,
        }
        if conversation_id is not None:
            payload["conversation_id"] = conversation_id

        producer = self._producer  # capture for closure — avoids Optional-None issue

        async def _do_publish() -> None:
            try:
                await producer.publish(self._topic, payload)
                logger.debug(
                    "PawnQueue message published: topic=%r session=%s chunk=%d",
                    self._topic, session_id, chunk_index,
                )
            except Exception as exc:
                logger.warning(
                    "PawnQueue publish failed (session=%s chunk=%d): %s",
                    session_id, chunk_index, exc,
                )

        asyncio.run_coroutine_threadsafe(_do_publish(), self._loop)

    def close(self) -> None:
        """Gracefully tear down the PawnQueue client and stop the event loop.

        Blocks until teardown completes (up to 10 s) so that any in-flight
        messages are sent before the process exits.
        """
        async def _teardown() -> None:
            if self._pq is not None:
                try:
                    await self._pq.teardown()
                    logger.info("PawnQueue client closed")
                except Exception as exc:
                    logger.warning(f"PawnQueue teardown error: {exc}")

        if self._loop.is_running():
            future = asyncio.run_coroutine_threadsafe(_teardown(), self._loop)
            try:
                future.result(timeout=10)
            except Exception as exc:
                logger.warning(f"PawnQueue teardown timed out: {exc}")

        self._stop_loop()
