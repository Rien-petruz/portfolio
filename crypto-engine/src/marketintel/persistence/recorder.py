"""Raw-frame recorder and reader (input for replay and backtests).

File format (gzip'd text):

* line 1: ``#meta<TAB>{json}`` - data source, connection plans (conn id ->
  venue, symbols) and the full instrument metadata, so a replay can rebuild
  the engine without any network access;
* then one line per frame:
  ``recv_wall_ns<TAB>recv_mono_ns<TAB>conn_id<TAB>sock_uid<TAB>raw``.

Frames are written exactly as received, from a background thread fed by a
bounded queue; when the disk cannot keep up frames are dropped and counted
(never blocking ingestion). Recording raw frames means a replay exercises
the same decoders, state and strategy code as live processing.
"""

from __future__ import annotations

import gzip
import os
import queue
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any, NamedTuple

import orjson


class RecordedFrame(NamedTuple):
    recv_wall_ns: int
    recv_mono_ns: int
    conn_id: int
    sock_uid: int
    raw: bytes


class FrameRecorder:
    def __init__(self, directory: str, meta: dict[str, Any], capacity: int = 200_000, prefix: str = "frames") -> None:
        Path(directory).mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        self.path = os.path.join(directory, f"{prefix}-{stamp}-{os.getpid()}.tsv.gz")
        self._q: queue.Queue[bytes | None] = queue.Queue(maxsize=capacity)
        self.written = 0
        self.dropped = 0
        self._meta = b"#meta\t" + orjson.dumps(meta, default=str) + b"\n"
        self._thread = threading.Thread(target=self._run, name="frame-recorder", daemon=True)
        self._thread.start()

    def write(self, raw: bytes, recv_wall_ns: int, recv_mono_ns: int, conn_id: int, sock_uid: int) -> None:
        if b"\n" in raw:  # only possible as inter-token JSON whitespace
            raw = raw.replace(b"\n", b" ")
        try:
            self._q.put_nowait(b"%d\t%d\t%d\t%d\t%s\n" % (recv_wall_ns, recv_mono_ns, conn_id, sock_uid, raw))
        except queue.Full:
            self.dropped += 1

    def _run(self) -> None:
        with gzip.open(self.path, "wb", compresslevel=3) as fh:
            fh.write(self._meta)
            while True:
                item = self._q.get()
                if item is None:
                    break
                fh.write(item)
                self.written += 1

    def close(self, timeout: float = 30.0) -> None:
        self._q.put(None)
        self._thread.join(timeout)


def read_meta(path: str) -> dict[str, Any]:
    with gzip.open(path, "rb") as fh:
        first = fh.readline()
    if not first.startswith(b"#meta\t"):
        raise ValueError(f"{path}: missing #meta header")
    return orjson.loads(first[6:])


def read_frames(path: str) -> Iterator[RecordedFrame]:
    with gzip.open(path, "rb") as fh:
        for line in fh:
            if line.startswith(b"#"):
                continue
            wall, mono, conn, sock, raw = line.rstrip(b"\n").split(b"\t", 4)
            yield RecordedFrame(int(wall), int(mono), int(conn), int(sock), raw)
