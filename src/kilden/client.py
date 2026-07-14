"""The Kilden client: bounded in-memory queue, one background worker,
retry with backoff, fork safety. Semantics are the Kilden Server SDK
Specification's — see SPEC.md in kilden-sdk-spec; the numbered contracts
referenced in comments are §3 of that document."""

import gzip as gzipmod
import json
import logging
import os
import random
import threading
import time
from collections import OrderedDict, deque
from datetime import datetime
from typing import Any, Callable, Deque, Dict, List, Mapping, Optional, Tuple, Union

from ._timefmt import coerce_timestamp, now_wire
from ._uuid7 import uuid7
from .transport import Transport, TransportResponse
from .version import VERSION

logger = logging.getLogger("kilden")

DEFAULT_HOST = "https://ingest.kilden.io"
MAX_EVENTS_PER_REQUEST = 1000
MAX_EVENT_BYTES = 200
MAX_DISTINCT_ID_BYTES = 512
GZIP_THRESHOLD = 1024
MAX_RETRIES = 3
CLOSE_DEADLINE = 10.0
FLAG_CACHE_TTL = 30.0
FLAG_CACHE_SIZE = 1000

FlagValue = Union[bool, str]
Event = Dict[str, Any]


class Client:
    """A Kilden client for trusted backend code. Requires the project's
    **secret** write key — never the public one."""

    def __init__(
        self,
        write_key: str,
        *,
        host: str = DEFAULT_HOST,
        flush_at: int = 20,
        flush_interval: float = 10.0,
        max_queue_size: int = 10000,
        timeout: float = 3.0,
        transport: Optional[Transport] = None,
        debug: bool = False,
        enabled: bool = True,
    ) -> None:
        # Contract 2: this is the one place that fails fast.
        if not isinstance(write_key, str) or write_key == "":
            raise ValueError("write_key is required: pass your project's secret write key")
        if write_key.startswith("wk_"):
            raise ValueError(
                "this looks like a public write key (wk_…). Server-side events must use "
                "the secret key: the secret key is what makes them verified facts. Keep "
                "it out of browsers and use the public key only in kilden-sdk-js."
            )

        self._write_key = write_key
        self._host = host.rstrip("/")
        self._flush_at = max(1, flush_at)
        self._flush_interval = flush_interval
        self._max_queue_size = max_queue_size
        self._timeout = timeout
        self._transport = transport or Transport(timeout)
        self._debug = debug
        self._enabled = enabled

        self._lock = threading.Lock()
        self._wake = threading.Condition(self._lock)
        self._queue: Deque[Event] = deque()
        self._dropped = 0
        self._closed = False
        self._sending = False
        self._pid = os.getpid()

        # Injectable for tests; production never touches these.
        self._sleep: Callable[[float], None] = time.sleep
        self._jitter: Callable[[], float] = lambda: random.uniform(0.5, 1.5)

        self._flag_cache: "OrderedDict[str, Tuple[float, Dict[str, FlagValue]]]" = OrderedDict()

        self._worker: Optional[threading.Thread] = None
        if self._enabled:
            self._start_worker()
            import atexit

            atexit.register(self.close)

    # -- public surface ---------------------------------------------------

    def track(
        self,
        distinct_id: str,
        event: str,
        properties: Optional[Mapping[str, Any]] = None,
        *,
        timestamp: Union[str, datetime, None] = None,
        uuid: Optional[str] = None,
    ) -> None:
        if not self._valid_string("distinct_id", distinct_id, MAX_DISTINCT_ID_BYTES):
            return
        if not self._valid_string("event", event, MAX_EVENT_BYTES):
            return
        if self._debug and event.startswith("$"):
            logger.warning("event %r uses the $ prefix reserved for Kilden; sending anyway", event)
        if self._debug and isinstance(properties, Mapping):
            for key in properties:
                if isinstance(key, str) and key.startswith("$"):
                    logger.warning(
                        "property %r uses the $ prefix reserved for Kilden; sending anyway", key
                    )
        self._enqueue(distinct_id, event, properties, timestamp, uuid)

    def identify(
        self,
        distinct_id: str,
        traits: Optional[Mapping[str, Any]] = None,
        *,
        timestamp: Union[str, datetime, None] = None,
        uuid: Optional[str] = None,
    ) -> None:
        if not self._valid_string("distinct_id", distinct_id, MAX_DISTINCT_ID_BYTES):
            return
        if traits is not None and not isinstance(traits, Mapping):
            logger.warning("identify: traits must be a mapping; dropping event")
            return
        if self._debug and traits:
            for key in traits:
                if isinstance(key, str) and key.startswith("$"):
                    logger.warning(
                        "trait %r uses the $ prefix reserved for Kilden; sending anyway", key
                    )
        self._enqueue(distinct_id, "$identify", {"$set": dict(traits or {})}, timestamp, uuid)

    def alias(self, previous_id: str, distinct_id: str) -> None:
        if not self._valid_string("previous_id", previous_id, MAX_DISTINCT_ID_BYTES):
            return
        if not self._valid_string("distinct_id", distinct_id, MAX_DISTINCT_ID_BYTES):
            return
        # The envelope's distinct_id is the EXISTING identity; $alias is the
        # id being attached to its person (SPEC §4.6).
        self._enqueue(previous_id, "$alias", {"$alias": distinct_id}, None, None)

    def flush(self) -> None:
        """Drain everything queued right now; blocks through retries."""
        if not self._enabled:
            return
        try:
            self._fork_check()
            with self._wake:
                self._wake.notify_all()
                while self._queue and not self._closed:
                    self._wake.wait(timeout=0.05)
                    self._wake.notify_all()
                # Wait out an in-flight send so "flush returned" means
                # "delivery finished", not "queue looked empty".
                while self._sending:
                    self._wake.wait(timeout=0.05)
        except Exception:
            logger.exception("flush failed")  # contract 1: never raise

    def close(self) -> None:
        """Flush with a deadline, then stop the worker. Idempotent."""
        if not self._enabled:
            return
        try:
            deadline = time.monotonic() + CLOSE_DEADLINE
            with self._wake:
                if self._closed:
                    return
                self._wake.notify_all()
                while (self._queue or self._sending) and time.monotonic() < deadline:
                    self._wake.wait(timeout=0.05)
                    self._wake.notify_all()
                remaining = len(self._queue)
                if remaining:
                    self._dropped += remaining
                    self._queue.clear()
                    logger.warning(
                        "close: %d events dropped after the %.0fs deadline", remaining, CLOSE_DEADLINE
                    )
                self._closed = True
                self._wake.notify_all()
            worker = self._worker
            if worker is not None and worker is not threading.current_thread():
                worker.join(timeout=1.0)
        except Exception:
            logger.exception("close failed")  # contract 1: never raise

    @property
    def dropped_count(self) -> int:
        """Events dropped so far: queue overflow, close deadline, exhausted
        retries (contract 7)."""
        with self._lock:
            return self._dropped

    # -- feature flags (SPEC §8) ------------------------------------------

    def get_feature_flag(
        self,
        flag_key: str,
        distinct_id: str,
        *,
        person_properties: Optional[Mapping[str, Any]] = None,
        default: FlagValue = False,
    ) -> FlagValue:
        try:
            if not self._enabled:
                return default
            if not isinstance(flag_key, str) or flag_key == "":
                logger.warning("get_feature_flag: flag_key must be a non-empty string")
                return default
            if not isinstance(distinct_id, str) or distinct_id == "":
                logger.warning("get_feature_flag: distinct_id must be a non-empty string")
                return default

            flags = self._decide(distinct_id, person_properties)
            if flags is None or flag_key not in flags:
                return default
            return flags[flag_key]
        except Exception:
            logger.exception("get_feature_flag failed; returning default")
            return default

    def is_enabled(
        self,
        flag_key: str,
        distinct_id: str,
        *,
        person_properties: Optional[Mapping[str, Any]] = None,
        default: bool = False,
    ) -> bool:
        value = self.get_feature_flag(
            flag_key, distinct_id, person_properties=person_properties, default=default
        )
        return value is True or isinstance(value, str)

    # -- internals ---------------------------------------------------------

    def _valid_string(self, what: str, value: Any, max_bytes: int) -> bool:
        if not isinstance(value, str) or value == "":
            logger.warning("%s must be a non-empty string; dropping event", what)
            return False
        if len(value.encode("utf-8")) > max_bytes:
            logger.warning("%s exceeds %d bytes; dropping event", what, max_bytes)
            return False
        return True

    def _enqueue(
        self,
        distinct_id: str,
        event: str,
        properties: Optional[Mapping[str, Any]],
        timestamp: Union[str, datetime, None],
        uuid: Optional[str],
    ) -> None:
        try:
            if not self._enabled:
                return
            self._fork_check()

            wire_ts = coerce_timestamp(timestamp)
            if wire_ts is None:
                logger.warning("timestamp %r is not interpretable; dropping event", timestamp)
                return
            try:
                # Freeze properties now (events are immutable) and prove they
                # are JSON-serializable while we can still just drop + warn.
                frozen = json.loads(json.dumps(dict(properties or {}), ensure_ascii=False))
            except (TypeError, ValueError):
                logger.warning("properties are not JSON-serializable; dropping event")
                return
            if not isinstance(frozen, dict):
                logger.warning("properties must be a mapping; dropping event")
                return

            item: Event = {
                "uuid": uuid if uuid is not None else uuid7(),
                "event": event,
                "distinct_id": distinct_id,
                "properties": frozen,
                "timestamp": wire_ts,
            }
            with self._wake:
                if self._closed:
                    self._dropped += 1
                    logger.warning("client is closed; dropping event")
                    return
                if len(self._queue) >= self._max_queue_size:
                    self._dropped += 1  # contract 7: drop the NEW event
                    logger.warning("queue full (%d); dropping event", self._max_queue_size)
                    return
                self._queue.append(item)
                if len(self._queue) >= self._flush_at:
                    self._wake.notify_all()
        except Exception:
            logger.exception("enqueue failed")  # contract 1: never raise

    def _fork_check(self) -> None:
        """Contract 9: after a fork, the inherited queue belongs to the
        parent and the inherited worker thread is dead. Discard and restart."""
        pid = os.getpid()
        if pid == self._pid:
            return
        with self._lock:
            if pid == self._pid:
                return
            inherited = len(self._queue)
            self._queue.clear()
            self._flag_cache.clear()
            self._closed = False
            self._sending = False
            self._pid = pid
            if inherited:
                logger.debug("fork detected; discarded %d inherited events", inherited)
        self._start_worker()

    def _start_worker(self) -> None:
        self._worker = threading.Thread(target=self._run, name="kilden-worker", daemon=True)
        self._worker.start()

    def _run(self) -> None:
        while True:
            with self._wake:
                if self._closed:
                    return
                if len(self._queue) < self._flush_at:
                    self._wake.wait(timeout=self._flush_interval)
                if self._closed and not self._queue:
                    return
                if os.getpid() != self._pid:
                    return  # a fork orphaned this thread's state; child restarts
                batch: List[Event] = []
                while self._queue and len(batch) < MAX_EVENTS_PER_REQUEST:
                    batch.append(self._queue.popleft())
                if batch:
                    self._sending = True
            if batch:
                try:
                    self._send_with_retry(batch)
                finally:
                    with self._wake:
                        self._sending = False
                        self._wake.notify_all()

    # -- delivery ----------------------------------------------------------

    def _send_with_retry(self, batch: List[Event]) -> None:
        body = json.dumps(
            {"write_key": self._write_key, "sent_at": now_wire(), "batch": batch},
            ensure_ascii=False,
        ).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "User-Agent": f"kilden-python/{VERSION}",
        }
        if len(body) > GZIP_THRESHOLD:
            body = gzipmod.compress(body)
            headers["Content-Encoding"] = "gzip"

        for attempt in range(MAX_RETRIES + 1):
            resp = self._transport.send(f"{self._host}/capture", body, headers)
            outcome = _classify(resp)
            if outcome == "ok":
                if self._debug:
                    logger.debug("delivered %d events", len(batch))
                return
            if outcome == "fatal":
                logger.warning(
                    "capture rejected with %d (%s); dropping %d events",
                    resp.status,
                    resp.body[:200].decode("utf-8", "replace").strip(),
                    len(batch),
                )
                with self._lock:
                    self._dropped += len(batch)
                return
            if attempt == MAX_RETRIES:
                break
            retry_after = resp.headers.get("retry-after") if resp.status == 429 else None
            if retry_after is not None:
                try:
                    delay = float(retry_after)
                except ValueError:
                    delay = min(0.5 * 2**attempt, 30.0) * self._jitter()
            else:
                delay = min(0.5 * 2**attempt, 30.0) * self._jitter()
            self._sleep(delay)

        logger.warning("retries exhausted; dropping %d events", len(batch))
        with self._lock:
            self._dropped += len(batch)

    def _decide(
        self, distinct_id: str, person_properties: Optional[Mapping[str, Any]]
    ) -> Optional[Dict[str, FlagValue]]:
        bypass_cache = bool(person_properties)
        if not bypass_cache:
            cached = self._flag_cache_get(distinct_id)
            if cached is not None:
                return cached

        payload: Dict[str, Any] = {"write_key": self._write_key, "distinct_id": distinct_id}
        if person_properties:
            payload["person_properties"] = dict(person_properties)
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        resp = self._transport.send(
            f"{self._host}/decide",
            body,
            {"Content-Type": "application/json", "User-Agent": f"kilden-python/{VERSION}"},
        )
        if resp.status != 200:
            logger.warning("decide failed (%s); returning default", resp.error or resp.status)
            return None
        try:
            parsed = json.loads(resp.body)
            flags = parsed["flags"]
            if not isinstance(flags, dict):
                raise TypeError("flags is not an object")
        except Exception:
            logger.warning("decide returned a malformed body; returning default")
            return None

        result: Dict[str, FlagValue] = {
            k: v for k, v in flags.items() if isinstance(v, (bool, str))
        }
        if not bypass_cache:
            self._flag_cache_put(distinct_id, result)
        return result

    def _flag_cache_get(self, distinct_id: str) -> Optional[Dict[str, FlagValue]]:
        with self._lock:
            entry = self._flag_cache.get(distinct_id)
            if entry is None:
                return None
            expires, flags = entry
            if time.monotonic() >= expires:
                del self._flag_cache[distinct_id]
                return None
            self._flag_cache.move_to_end(distinct_id)
            return flags

    def _flag_cache_put(self, distinct_id: str, flags: Dict[str, FlagValue]) -> None:
        with self._lock:
            self._flag_cache[distinct_id] = (time.monotonic() + FLAG_CACHE_TTL, flags)
            self._flag_cache.move_to_end(distinct_id)
            while len(self._flag_cache) > FLAG_CACHE_SIZE:
                self._flag_cache.popitem(last=False)


def _classify(resp: TransportResponse) -> str:
    """SPEC §4.3: ok | fatal (drop) | retry."""
    if resp.status == 200:
        try:
            json.loads(resp.body)
            return "ok"
        except ValueError:
            return "retry"  # corrupt response
    if resp.status == 429 or resp.status >= 500 or resp.status == 0:
        return "retry"
    return "fatal"  # remaining 4xx: retrying cannot fix it
