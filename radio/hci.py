"""Raw HCI for LE scanning, with the Python standard library only.

Byte layouts follow the Bluetooth Core spec, Vol 4 Part E: packets 5.4, supported commands 6.27,
LE commands 7.8 and LE Meta events 7.7.65. Everything here except Hci.open() is plain bytes in and
out, so it runs (and is tested) anywhere. Hci.open() needs Linux and root.

Parsing never hands back a device address: an advertising report comes out as (data, rssi).
"""
import socket
import struct
import time

CMD_PKT, EVENT_PKT = 0x01, 0x04
EV_CMD_COMPLETE, EV_CMD_STATUS, EV_LE_META = 0x0E, 0x0F, 0x3E
LE_ADV_REPORT, LE_EXT_ADV_REPORT = 0x02, 0x0D
AD_MANUFACTURER = 0xFF
RSSI_UNAVAILABLE = 127

# Opcodes = OGF << 10 | OCF
HCI_RESET = 0x0C03
READ_LOCAL_SUPPORTED_COMMANDS = 0x1002
LE_SET_SCAN_PARAMS, LE_SET_SCAN_ENABLE = 0x200B, 0x200C              # legacy
LE_SET_EXT_SCAN_PARAMS, LE_SET_EXT_SCAN_ENABLE = 0x2041, 0x2042      # extended

# Supported commands bit for LE Set Extended Scan Enable: octet 37, bit 6
EXT_SCAN_ENABLE_BIT = (37, 6)

SCAN_INTERVAL = SCAN_WINDOW = 0x0010  # x 0.625 ms = 10 ms each, so the radio listens all the time

STATUS = {0x01: "Unknown HCI Command", 0x0C: "Command Disallowed", 0x12: "Invalid HCI Command Parameters"}

# Linux socket constants, spelled out for Pythons that don't define them
AF_BLUETOOTH = getattr(socket, "AF_BLUETOOTH", 31)
BTPROTO_HCI = getattr(socket, "BTPROTO_HCI", 1)
SOL_HCI = getattr(socket, "SOL_HCI", 0)
HCI_FILTER = getattr(socket, "HCI_FILTER", 2)


class HciError(Exception):
    def __init__(self, opcode, status=None, text=None):
        self.opcode, self.status = opcode, status
        if text is None:
            text = f"status 0x{status:02X} {STATUS.get(status, '')}".rstrip()
        super().__init__(f"HCI command 0x{opcode:04X}: {text}")


def command_packet(opcode: int, params: bytes = b"") -> bytes:
    return struct.pack("<BHB", CMD_PKT, opcode, len(params)) + params


def event_filter(*events: int) -> bytes:
    """struct hci_ufilter: type mask, 64-bit event mask, opcode, padded to 16 bytes like the kernel's."""
    mask = 0
    for ev in events:
        mask |= 1 << (ev & 63)
    return struct.pack("<IIIH2x", 1 << EVENT_PKT, mask & 0xFFFFFFFF, mask >> 32, 0)


def command_result(packet: bytes, opcode: int):
    """Status and return parameters if packet completes `opcode` (Command Complete or Status), else None."""
    if len(packet) < 7 or packet[0] != EVENT_PKT:
        return None
    body = packet[3:3 + packet[2]]
    if packet[1] == EV_CMD_COMPLETE and len(body) >= 4 and struct.unpack_from("<H", body, 1)[0] == opcode:
        return bytes(body[3:])
    if packet[1] == EV_CMD_STATUS and len(body) >= 4 and struct.unpack_from("<H", body, 2)[0] == opcode:
        return bytes(body[:1])
    return None


def completed_opcode(packet: bytes):
    """The opcode a Command Complete event answers, or None for any other packet."""
    if len(packet) >= 6 and packet[0] == EVENT_PKT and packet[1] == EV_CMD_COMPLETE:
        return struct.unpack_from("<H", packet, 4)[0]
    return None


def supports(commands: bytes, octet_bit) -> bool:
    """True if the Supported_Commands bit mask (64 octets) has (octet, bit) set."""
    octet, bit = octet_bit
    return len(commands) > octet and bool(commands[octet] >> bit & 1)


def scan_params(ext: bool):
    """Passive scan, 1M PHY, interval = window = 10 ms, public address, accept all adverts."""
    if ext:
        return LE_SET_EXT_SCAN_PARAMS, struct.pack("<BBBBHH", 0x00, 0x00, 0x01, 0x00, SCAN_INTERVAL, SCAN_WINDOW)
    return LE_SET_SCAN_PARAMS, struct.pack("<BHHBB", 0x00, SCAN_INTERVAL, SCAN_WINDOW, 0x00, 0x00)


def scan_enable(ext: bool, on: bool):
    """Filter_Duplicates is always 0: we want every advert, not one per device."""
    if ext:  # Enable, Filter_Duplicates, Duration 0 (until disabled), Period 0
        return LE_SET_EXT_SCAN_ENABLE, struct.pack("<BBHH", int(on), 0x00, 0, 0)
    return LE_SET_SCAN_ENABLE, struct.pack("<BB", int(on), 0x00)


def signed(byte: int) -> int:
    return byte - 256 if byte > 127 else byte


def adv_reports(packet: bytes):
    """Yield (advertising data, rssi) for every report in an LE (Extended) Advertising Report event.

    Anything else, or a report cut short, yields nothing more.
    """
    if len(packet) < 5 or packet[0] != EVENT_PKT or packet[1] != EV_LE_META:
        return
    body = packet[3:3 + packet[2]]
    sub, count, i = body[0], body[1], 2
    for _ in range(count):
        if sub == LE_ADV_REPORT:
            # Event_Type 1, Address_Type 1, Address 6, Data_Length 1, Data, RSSI 1
            if i + 9 > len(body):
                return
            start = i + 9
            end = start + body[i + 8]
            if end + 1 > len(body):
                return
            yield bytes(body[start:end]), signed(body[end])
            i = end + 1
        elif sub == LE_EXT_ADV_REPORT:
            # Event_Type 2, Address_Type 1, Address 6, Primary_PHY 1, Secondary_PHY 1, SID 1, TX_Power 1,
            # RSSI 1, Periodic_Adv_Interval 2, Direct_Address_Type 1, Direct_Address 6, Data_Length 1, Data
            if i + 24 > len(body):
                return
            start = i + 24
            end = start + body[i + 23]
            if end > len(body):
                return
            yield bytes(body[start:end]), signed(body[i + 13])
            i = end
        else:
            return


def manufacturer_data(data: bytes):
    """Yield the payload (company id first) of each Manufacturer Specific Data AD structure."""
    i = 0
    while i < len(data):
        n = data[i]
        if n == 0 or i + 1 + n > len(data):
            return
        if data[i + 1] == AD_MANUFACTURER:
            yield bytes(data[i + 2:i + 1 + n])
        i += 1 + n


class Hci:
    """Commands and events over one HCI socket (or anything with send, recv and settimeout)."""

    def __init__(self, sock):
        self.sock = sock

    @classmethod
    def open(cls, dev: int = 0) -> "Hci":
        """Raw HCI socket on hciN that sees Command Complete, Command Status and LE Meta events. Root only."""
        sock = socket.socket(AF_BLUETOOTH, socket.SOCK_RAW, BTPROTO_HCI)
        sock.setsockopt(SOL_HCI, HCI_FILTER, event_filter(EV_CMD_COMPLETE, EV_CMD_STATUS, EV_LE_META))
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1 << 20)
        sock.bind((dev,))
        return cls(sock)

    def recv(self, timeout: float):
        """One packet, or None after `timeout` seconds."""
        self.sock.settimeout(max(timeout, 0.001))
        try:
            return self.sock.recv(1024)
        except socket.timeout:
            return None

    def command(self, opcode: int, params: bytes = b"", check: bool = True, timeout: float = 2.0) -> bytes:
        """Send one command and wait for its result. Raises HciError on a bad status if check."""
        self.sock.send(command_packet(opcode, params))
        deadline = time.monotonic() + timeout
        while (left := deadline - time.monotonic()) > 0:
            packet = self.recv(left)
            result = None if packet is None else command_result(packet, opcode)
            if result is not None:
                if check and result[0] != 0:
                    raise HciError(opcode, result[0])
                return result
        raise HciError(opcode, text=f"no reply in {timeout} s")

    def supports_ext_scan(self) -> bool:
        result = self.command(READ_LOCAL_SUPPORTED_COMMANDS)
        return supports(result[1:65], EXT_SCAN_ENABLE_BIT)

    def close(self) -> None:
        self.sock.close()
