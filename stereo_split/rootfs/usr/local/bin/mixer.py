#!/usr/bin/env python3

import argparse
import os
import signal
import sys
import time
from array import array

RATE = 44100
TICK = 0.01
TICK_FRAMES = int(RATE * TICK)
FRAME_BYTES = 4
CHUNK = TICK_FRAMES * FRAME_BYTES
MAX_BUFFER = RATE * FRAME_BYTES // 10
IDLE_FLUSH = 0.5

assert array("h").itemsize == 2

def log(msg):
    print(f"[mixer] {msg}", file=sys.stderr, flush=True)

class Room:
    def __init__(self, name, path):
        self.name = name
        self.fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
        self.buf = bytearray()
        self.last_data = 0.0
        self.last_audio = 0.0
        self.active = False

    def drain(self, now):
        while True:
            try:
                data = os.read(self.fd, 65536)
            except BlockingIOError:
                break
            if not data:
                break
            self.buf += data
            self.last_data = now
        excess = len(self.buf) - MAX_BUFFER
        if excess > 0:
            del self.buf[: excess - excess % FRAME_BYTES]
        if 0 < len(self.buf) < CHUNK and now - self.last_data > IDLE_FLUSH:
            self.buf.clear()

    def next_chunk(self, now):
        if len(self.buf) >= CHUNK:
            chunk = bytes(self.buf[:CHUNK])
            del self.buf[:CHUNK]
            self.last_audio = now
            return chunk
        return None

    def update_state(self, now):
        active = now - self.last_audio < IDLE_FLUSH
        if active != self.active:
            self.active = active
            log(f"{self.name}: {'audio started' if active else 'audio stopped'}")

def to_mono(chunk):
    pcm = array("h")
    pcm.frombytes(chunk)
    if sys.byteorder == "big":
        pcm.byteswap()
    return array("h", [(left + right) >> 1 for left, right in zip(pcm[0::2], pcm[1::2])])

def mix(mono_a, mono_b):
    out = array("h", bytes(CHUNK))
    if mono_a is not None:
        out[0::2] = mono_a
    if mono_b is not None:
        out[1::2] = mono_b
    if sys.byteorder == "big":
        out.byteswap()
    return out.tobytes()

class FifoSink:

    def __init__(self, path):
        self.path = path
        self.fd = None
        self.next_try = 0.0

    def write(self, data):
        if self.fd is None:
            now = time.monotonic()
            if now < self.next_try:
                return
            try:
                self.fd = os.open(self.path, os.O_WRONLY | os.O_NONBLOCK)
            except OSError:
                self.next_try = now + 1.0
                return
        try:
            os.write(self.fd, data)
        except BlockingIOError:
            pass
        except BrokenPipeError:
            os.close(self.fd)
            self.fd = None

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fifo-a", required=True, help="PCM pipe for room A (left)")
    parser.add_argument("--fifo-b", required=True, help="PCM pipe for room B (right)")
    parser.add_argument("--out-fifo", required=True, help="named pipe the mixed PCM is written to")
    args = parser.parse_args()

    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))

    room_a = Room("Room A (left)", args.fifo_a)
    room_b = Room("Room B (right)", args.fifo_b)
    sink = FifoSink(args.out_fifo)
    log("running")

    next_tick = time.monotonic()
    try:
        while True:
            now = time.monotonic()
            room_a.drain(now)
            room_b.drain(now)
            chunk_a = room_a.next_chunk(now)
            chunk_b = room_b.next_chunk(now)
            room_a.update_state(now)
            room_b.update_state(now)

            data = mix(
                to_mono(chunk_a) if chunk_a else None,
                to_mono(chunk_b) if chunk_b else None,
            )
            sink.write(data)

            next_tick += TICK
            delay = next_tick - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            elif delay < -1.0:
                next_tick = time.monotonic()
    finally:
        sink.close()

if __name__ == "__main__":
    sys.exit(main())
