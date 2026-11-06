#!/usr/bin/env python3

import argparse
import asyncio
import os
import socket
import sys
from array import array

import pyatv
import pyatv.protocols.raop as raop
from pyatv.const import Protocol
from pyatv.protocols.raop.audio_source import AudioSource
from pyatv.protocols.raop.protocols import StreamContext, airplayv2
from pyatv.support.metadata import EMPTY_METADATA
from pyatv.support.rtsp import RtspSession

RATE = 44100
FRAME_BYTES = 4
PREFILL = int(RATE * 0.06) * FRAME_BYTES
MAX_BUFFER = int(RATE * 0.25) * FRAME_BYTES
LIVE = "live-stereo-split"
LEAD_SECONDS = 0.5
RETRY_SECONDS = 15
PROBE_SECONDS = 20

PACKET_FRAMES = 352
PACKET_BYTES = PACKET_FRAMES * FRAME_BYTES
PACKET_BITS = PACKET_BYTES * 8
ALAC_FORMAT = 0x40000
ALAC_CT = 2
ALAC_HEADER = (0b001 << 20) | 0b0001

def log(msg):
    print(f"[airplay] {msg}", file=sys.stderr, flush=True)

class Pipe:

    def __init__(self, path):
        self.fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
        self.keep_open = os.open(path, os.O_WRONLY | os.O_NONBLOCK)
        self.buf = bytearray()

    def start(self, loop):
        loop.add_reader(self.fd, self._readable)

    def _readable(self):
        while True:
            try:
                data = os.read(self.fd, 65536)
            except BlockingIOError:
                break
            if not data:
                break
            self.buf += data
        if len(self.buf) > MAX_BUFFER:
            cut = len(self.buf) - PREFILL
            del self.buf[: cut - cut % FRAME_BYTES]

class LiveSource(AudioSource):

    def __init__(self, pipe, sample_rate, channels, sample_size):
        self._pipe = pipe
        self._rate = sample_rate
        self._channels = channels
        self._sample_size = sample_size
        self._buffering = True
        pipe.buf.clear()

    async def readframes(self, nframes):
        need = nframes * FRAME_BYTES
        buf = self._pipe.buf
        if self._buffering and len(buf) >= PREFILL:
            self._buffering = False
        if not self._buffering:
            if len(buf) >= need:
                samples = array("h")
                samples.frombytes(bytes(buf[:need]))
                del buf[:need]
                if sys.byteorder == "little":
                    samples.byteswap()
                return samples.tobytes()
            self._buffering = True
        return bytes(need)

    async def get_metadata(self):
        return EMPTY_METADATA

    @property
    def sample_rate(self):
        return self._rate

    @property
    def channels(self):
        return self._channels

    @property
    def sample_size(self):
        return self._sample_size

    @property
    def duration(self):
        return 0

def alac_frame(pcm):
    bits = (ALAC_HEADER << (PACKET_BITS + 3)) | (int.from_bytes(pcm, "big") << 3) | 0b111
    total = 23 + PACKET_BITS + 3
    pad = -total % 8
    return (bits << pad).to_bytes((total + pad) // 8, "big")

def use_alac():
    original_setup = RtspSession.setup

    async def setup(self, headers=None, body=None):
        if isinstance(body, dict) and body.get("streams"):
            for stream in body["streams"]:
                stream["audioFormat"] = ALAC_FORMAT
                stream["ct"] = ALAC_CT
                stream["spf"] = PACKET_FRAMES
        return await original_setup(self, headers=headers, body=body)

    RtspSession.setup = setup

    original_send = airplayv2.AirPlayV2.send_audio_packet

    async def send_audio_packet(self, transport, rtp_header, audio):
        if len(audio) == PACKET_BYTES:
            audio = alac_frame(audio)
        return await original_send(self, transport, rtp_header, audio)

    airplayv2.AirPlayV2.send_audio_packet = send_audio_packet

def use_lead(seconds):
    frames = max(11025, round(seconds * RATE))
    original_reset = StreamContext.reset

    def reset(self):
        original_reset(self)
        self.latency = frames

    StreamContext.reset = reset

def use_live_source(pipe):
    original = raop.open_source

    async def open_source(source, sample_rate, channels, sample_size):
        if source == LIVE:
            return LiveSource(pipe, sample_rate, channels, sample_size)
        return await original(source, sample_rate, channels, sample_size)

    raop.open_source = open_source

async def probe(host, port):
    try:
        _, writer = await asyncio.wait_for(asyncio.open_connection(host, port), 5)
    except (OSError, asyncio.TimeoutError):
        return False
    writer.close()
    return True

async def watchdog(host, port):
    failures = 0
    while True:
        await asyncio.sleep(PROBE_SECONDS)
        failures = 0 if await probe(host, port) else failures + 1
        if failures >= 3:
            raise ConnectionError(f"{host}:{port} stopped answering")

async def stream_once(host):
    loop = asyncio.get_running_loop()
    confs = await pyatv.scan(loop, hosts=[host], timeout=5, protocol=Protocol.RAOP)
    if not confs:
        raise ConnectionError(f"no AirPlay receiver answered at {host}")
    conf = confs[0]
    service = conf.get_service(Protocol.RAOP)
    log(f"connecting to '{conf.name}' at {host}")
    atv = await pyatv.connect(conf, loop)
    try:
        await atv.audio.set_volume(100.0)
        stream = asyncio.ensure_future(atv.stream.stream_file(LIVE))
        guard = asyncio.ensure_future(watchdog(host, service.port))
        log("streaming (silence until a room plays)")
        done, pending = await asyncio.wait({stream, guard}, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        for task in done:
            task.result()
        raise ConnectionError("stream ended")
    finally:
        atv.close()

async def main_async(args):
    pipe = Pipe(args.fifo)
    pipe.start(asyncio.get_running_loop())
    use_live_source(pipe)
    use_alac()
    use_lead(LEAD_SECONDS)
    while True:
        try:
            await stream_once(args.host)
        except asyncio.CancelledError:
            raise
        except Exception as err:
            log(f"{type(err).__name__}: {err}; retrying in {RETRY_SECONDS}s")
        await asyncio.sleep(RETRY_SECONDS)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True, help="Denon IP or hostname")
    parser.add_argument("--fifo", required=True, help="PCM pipe written by the mixer")
    args = parser.parse_args()
    try:
        args.host = socket.gethostbyname(args.host)
    except OSError:
        pass
    try:
        asyncio.run(main_async(args))
    except KeyboardInterrupt:
        pass

if __name__ == "__main__":
    sys.exit(main())
