"""A stand-in Bluetooth controller for tests, fed with the hand-built packets in fixtures/hci."""
import socket
import struct
from collections import deque
from pathlib import Path

from radio import hci

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "hci"


def fixture(name: str) -> bytes:
    """One packet from fixtures/hci/<name>.hex (hex bytes, '#' starts a comment)."""
    text = (FIXTURES / f"{name}.hex").read_text(encoding="utf-8")
    return bytes.fromhex(" ".join(line.split("#")[0] for line in text.splitlines()))


class FakeController:
    """Looks like a raw HCI socket. Answers every command, then hands out `events` one per recv().

    ext: whether Read Local Supported Commands reports extended scanning.
    status: {opcode: status} for commands that should fail.
    noise: packets that arrive before each command's reply (other traffic on the socket).
    When the events run out, recv() times out, or raises `at_end` if given.
    """

    def __init__(self, ext=False, events=(), status=None, noise=(), at_end=None):
        self.supported = fixture("read_supported_commands_" + ("ext" if ext else "legacy"))
        self.events, self.replies, self.sent = deque(events), deque(), []
        self.status, self.noise, self.at_end = status or {}, list(noise), at_end

    @property
    def opcodes(self):
        return [struct.unpack_from("<H", p, 1)[0] for p in self.sent]

    @property
    def drained(self) -> bool:
        return not self.events and not self.replies

    def settimeout(self, timeout):
        pass

    def send(self, packet: bytes):
        self.sent.append(bytes(packet))
        opcode = struct.unpack_from("<H", packet, 1)[0]
        self.replies.extend(self.noise)
        if opcode == hci.READ_LOCAL_SUPPORTED_COMMANDS:
            self.replies.append(self.supported)
        else:  # Command Complete: 1 packet allowed, opcode, status
            self.replies.append(bytes([4, 0x0E, 4, 1]) + struct.pack("<HB", opcode, self.status.get(opcode, 0)))

    def recv(self, size):
        if self.replies or self.events:
            return (self.replies or self.events).popleft()
        raise self.at_end or socket.timeout()

    def close(self):
        pass
