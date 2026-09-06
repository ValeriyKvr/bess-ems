"""Tests for Modbus TCP Gateway (SPEC §4.2, Stage 8)."""

import socket
import struct
import time

from bess_sim.modbus import ModbusServer


def test_modbus_tcp_read_and_write() -> None:
    """Test reading holding registers (FC 03) and writing setpoint (FC 06)."""
    received_setpoints = []

    def on_setpoint(val: float) -> None:
        received_setpoints.append(val)

    # Use port 5029 for testing
    port = 5029
    server = ModbusServer(host="127.0.0.1", port=port, on_setpoint_write=on_setpoint)
    server.start()
    time.sleep(0.1)

    try:
        # Update telemetry
        server.update_telemetry(
            soc_pct=75.5,
            power_kw=-250.0,
            voltage_v=785.0,
            temp_c=28.0,
            state_str="DISCHARGING",
        )

        # Connect via TCP
        client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client.connect(("127.0.0.1", port))
        client.settimeout(2.0)

        # 1. Read Holding Registers (FC 03): 5 registers from address 0
        # MBAP: TransID=1 (2B), Proto=0 (2B), Len=6 (2B), UnitID=1 (1B)
        # PDU: FC=3 (1B), Start=0 (2B), Qty=5 (2B)
        req = struct.pack(">HHHBBHH", 1, 0, 6, 1, 3, 0, 5)
        client.sendall(req)

        resp = client.recv(1024)
        assert len(resp) >= 9 + 10  # 7 MBAP + 1 FC + 1 ByteCount + 10 data
        trans_id, proto, length, unit, fc, byte_count = struct.unpack(">HHHBBB", resp[:9])
        assert fc == 3
        assert byte_count == 10

        soc, power, volt, temp, state = struct.unpack(">HhHHH", resp[9:19])
        assert soc == 7550  # 75.5% * 100
        assert power == -250
        assert volt == 785
        assert temp == 28
        assert state == 4  # DISCHARGING is 4

        # 2. Write Single Register (FC 06): write setpoint 350 kW to register 5 (40006)
        # MBAP: TransID=2 (2B), Proto=0 (2B), Len=6 (2B), UnitID=1 (1B)
        # PDU: FC=6 (1B), Addr=5 (2B), Val=350 (2B)
        req_write = struct.pack(">HHHBBHh", 2, 0, 6, 1, 6, 5, 350)
        client.sendall(req_write)

        resp_write = client.recv(1024)
        assert len(resp_write) >= 12
        trans_id2, proto2, len2, unit2, fc2, addr2, val2 = struct.unpack(
            ">HHHBBHh", resp_write[:12]
        )
        assert fc2 == 6
        assert addr2 == 5
        assert val2 == 350

        # Check callback received setpoint
        assert len(received_setpoints) == 1
        assert received_setpoints[0] == 350.0

        client.close()
    finally:
        server.stop()
