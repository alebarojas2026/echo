"""Tests for pi.radio_node against hand-built HCI packets and fake controller."""

import json
import socket
import struct
import pytest

from contracts.check import errors
from radio import hci
from radio.tests.fakes import FakeController, fixture
from pi.radio_node import (
    ADV_INTERVAL_HCI,
    LE_SET_ADV_PARAMS,
    LE_SET_ADV_DATA,
    LE_SET_ADV_ENABLE,
    build_adv_params_params,
    build_adv_params_cmd,
    build_adv_data_params,
    build_adv_data_cmd,
    build_adv_enable_cmd,
    run,
)


def test_adv_params_parameter_bytes():
    """Verify the 15 parameter bytes: interval 0x0020 twice, type 0x03, channel map 0x07."""
    params = build_adv_params_params()
    assert len(params) == 15
    min_int, max_int = struct.unpack_from("<HH", params, 0)
    assert min_int == 0x0020
    assert max_int == 0x0020
    adv_type = params[4]
    assert adv_type == 0x03  # ADV_NONCONN_IND
    channel_map = params[13]
    assert channel_map == 0x07  # all 3 advert channels (37, 38, 39)
    filter_policy = params[14]
    assert filter_policy == 0x00


def test_adv_params_command_packet():
    cmd = build_adv_params_cmd()
    assert cmd[0] == 0x01  # CMD_PKT
    opcode = struct.unpack_from("<H", cmd, 1)[0]
    assert opcode == LE_SET_ADV_PARAMS
    param_len = cmd[3]
    assert param_len == 15


def test_adv_data_command_packet():
    cmd = build_adv_data_cmd()
    assert cmd[0] == 0x01
    opcode = struct.unpack_from("<H", cmd, 1)[0]
    assert opcode == LE_SET_ADV_DATA
    param_len = cmd[3]
    assert param_len == 32
    # Verify manufacturer payload FFFF 52 53 53 ('S')
    assert bytes.fromhex("FFFF525353") in cmd


def test_adv_enable_command():
    cmd_on = build_adv_enable_cmd(True)
    cmd_off = build_adv_enable_cmd(False)
    assert cmd_on == bytes.fromhex("01 0a 20 01 01")
    assert cmd_off == bytes.fromhex("01 0a 20 01 00")


def test_startup_sequence_and_packet_forwarding():
    """Verify advertising is configured and enabled, scan is started, and packets are forwarded."""
    events = [
        fixture("legacy_report_east"),
        fixture("legacy_reports_three"),        # contains west (-70) and pi5 (-80)
        fixture("legacy_report_near_misses"),    # unknown beacons
    ]
    fake = FakeController(events=events, ext=False)
    dev = hci.Hci(fake)

    # UDP receiver to capture bus messages
    srv = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    srv.bind(("127.0.0.1", 0))
    srv.settimeout(0.5)
    host, port = srv.getsockname()

    seen = run(dev, bus_host=host, bus_port=port, stop=lambda: fake.drained)

    received = []
    while True:
        try:
            data, _ = srv.recvfrom(4096)
            received.append(json.loads(data.decode()))
        except socket.timeout:
            break
    srv.close()

    # 1. Startup sequence opcodes checked against fake:
    # adv off, adv params, adv data, adv on, read supported, scan off, scan params, scan on ...
    assert LE_SET_ADV_ENABLE in fake.opcodes
    assert LE_SET_ADV_PARAMS in fake.opcodes
    assert LE_SET_ADV_DATA in fake.opcodes
    assert hci.LE_SET_SCAN_PARAMS in fake.opcodes
    assert hci.LE_SET_SCAN_ENABLE in fake.opcodes

    # 2. Pi receives east (-61) and west (-70). Pi never emits for itself.
    assert len(received) == 2
    assert [m["link"] for m in received] == ["east>pi5:ble", "west>pi5:ble"]

    # 3. Check every message conforms to contract v2
    for msg in received:
        errs = errors(msg)
        assert errs == [], f"Contract error in {msg}: {errs}"
        assert msg["rx"] == "pi5"
        assert msg["kind"] == "ble"
        assert msg["src"] == "live"

    # 4. Seq starts at 0 and increments
    assert [m["seq"] for m in received] == [0, 1]

    # 5. On exit, scan and advertising are turned off
    assert fake.sent[-1] == hci.command_packet(LE_SET_ADV_ENABLE, bytes([0x00]))
