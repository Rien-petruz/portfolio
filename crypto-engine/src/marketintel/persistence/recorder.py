"""Raw-frame recorder and reader (input for historical replay/backtests).

Frames are written exactly as received, with local receive timestamps, to a
gzip'd TSV: ``recv_wall_ns <TAB> recv_mono_ns <TAB> shard_id <TAB> raw_json``.
Writing happens on a background thread fed by a bounded queue; when the disk
cannot keep up frames are dropped and counted rather than slowing ingestion.
Recording raw frames (not normalized events) means the replay exercises the
same normalizer and state code as live trading.
"""

from __future__ import annotations

import gzip
import os
import queue
import threading
import time
from pathlib import Path
from typing import Iterator, NamedTuple


class RecordedFrame(NamedTuple):
    recv_wall_ns: int
    recv_mono_ns: int
    shard_id: int
    raw: bytes


class FrameRecorder:
    def __init__(self, directory: str, capacity: int = 100_000, prefix: str = "frames") -> None:
        Path(directory).mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        self.path = os.path.join(directory, f"{prefix}-{stamp}.tsv.gz")
        self._q: queue.Queue[bytes | None] = queue.Queue(maxsize=capacity)
        self.written = 0
        self.dropped = 0
        self._thread = threading.Thread(target=self._run, name="frame-recorder", daemon=True)
        self._thread.start()

    def write(self, raw: bytes, recv_wall_ns: int, recv_mono_ns: int, shard_id: int) -> None:
        if b"\n" in raw:  # only possible as inter-token JSON whitespace
            raw = raw.replace(b"\n", b" ")
        line = b"%d\t%d\t%d\t%s\n" % (recv_wall_ns, recv_mono_ns, shard_id, raw)
        try:
            self._q.put_nowait(line)
        except queue.Full:
            self.dropped += 1

    def _run(self) -> None:
        with gzip.open(self.path, "wb", compresslevel=3) as fh:
            while True:
                item = self._q.get()
                if item is None:
                    break
                fh.write(item)
                self.written += 1

    def close(self, timeout: float = 10.0) -> None:
        self._q.put(None)
        self._thread.join(timeout)


def read_frames(path: str) -> Iterator[RecordedFrame]:
    with gzip.open(path, "rb") as fh:
        for line in fh:
            wall, mono, shard, raw = line.rstrip(b"\n").split(b"\t", 3)
            yield RecordedFrame(int(wall), int(mono), int(shard), raw)
