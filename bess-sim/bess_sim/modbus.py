"""Modbus TCP Gateway for BESS Simulator (SPEC §4.2, Stage 8).

Implements Modbus TCP industrial protocol server on configurable port (default 5020).
Holding Register Map (SPEC §4.2):
- 40001 (Offset 0): SoC in 0.01% resolution (0..10000)
- 40002 (Offset 1): Active Power kW (signed 16-bit, -32768..32767)
- 40003 (Offset 2): Voltage V (16-bit uint, e.g. 780 V)
- 40004 (Offset 3): Temperature °C (signed 16-bit, e.g. 25 °C)
- 40005 (Offset 4): State (1=INIT, 2=STANDBY, 3=CHARGING, 4=DISCHARGING, 5=FAULT, 6=DEGRADED)
- 40006 (Offset 5): Active Power Setpoint kW (Read/Write, signed 16-bit)
"""

import logging
import socketserver
import struct
import threading
from collections.abc import Callable

logger = logging.getLogger("bess-modbus")

# State string to Modbus register enum value (SPEC §4.2)
STATE_ENUM_MAP: dict[str, int] = {
    "INIT": 1,
    "STANDBY": 2,
    "CHARGING": 3,
    "DISCHARGING": 4,
    "FAULT": 5,
    "DEGRADED": 6,
}


class ModbusRegisters:
    """Thread-safe container for Modbus holding registers."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.soc_raw: int = 5000  # 50.00%
        self.power_kw: int = 0
        self.voltage_v: int = 780
        self.temp_c: int = 25
        self.state_enum: int = 2  # STANDBY
        self.setpoint_kw: int = 0
        self.on_setpoint_write: Callable[[float], None] | None = None

    def update_telemetry(
        self,
        soc_pct: float,
        power_kw: float,
        voltage_v: float,
        temp_c: float,
        state_str: str,
    ) -> None:
        with self._lock:
            self.soc_raw = max(0, min(10000, int(round(soc_pct * 100))))
            self.power_kw = max(-32768, min(32767, int(round(power_kw))))
            self.voltage_v = max(0, min(65535, int(round(voltage_v))))
            self.temp_c = max(-32768, min(32767, int(round(temp_c))))
            self.state_enum = STATE_ENUM_MAP.get(state_str, 2)

    def read_holding_registers(self, start_addr: int, quantity: int) -> list[int]:
        with self._lock:
            registers = [
                self.soc_raw & 0xFFFF,
                self.power_kw & 0xFFFF,
                self.voltage_v & 0xFFFF,
                self.temp_c & 0xFFFF,
                self.state_enum & 0xFFFF,
                self.setpoint_kw & 0xFFFF,
            ]
        if start_addr < 0 or start_addr + quantity > len(registers):
            raise IndexError("Register address out of range")
        return registers[start_addr : start_addr + quantity]

    def write_single_register(self, addr: int, value: int) -> None:
        with self._lock:
            if addr == 5:  # Register 40006: Setpoint kW
                signed_val = struct.unpack(">h", struct.pack(">H", value & 0xFFFF))[0]
                self.setpoint_kw = signed_val
                cb = self.on_setpoint_write
            else:
                cb = None
        if cb is not None:
            cb(float(signed_val))


class ModbusTCPHandler(socketserver.BaseRequestHandler):
    """Handles Modbus TCP client connections."""

    registers: ModbusRegisters

    def handle(self) -> None:
        while True:
            # MBAP Header is 7 bytes: Transaction ID (2), Protocol ID (2), Length (2), Unit ID (1)
            header = self._recv_exact(7)
            if not header:
                break
            trans_id, proto_id, length, unit_id = struct.unpack(">HHHB", header)
            if proto_id != 0 or length < 2:
                break

            pdu_len = length - 1  # Subtract Unit ID
            pdu = self._recv_exact(pdu_len)
            if not pdu or len(pdu) < 1:
                break

            func_code = pdu[0]
            response_pdu = self._process_pdu(func_code, pdu[1:])

            # Build MBAP Response
            resp_len = len(response_pdu) + 1  # +1 for unit_id
            resp_header = struct.pack(">HHHB", trans_id, 0, resp_len, unit_id)
            try:
                self.request.sendall(resp_header + response_pdu)
            except Exception:
                break

    def _recv_exact(self, num_bytes: int) -> bytes | None:
        data = bytearray()
        while len(data) < num_bytes:
            chunk = self.request.recv(num_bytes - len(data))
            if not chunk:
                return None
            data.extend(chunk)
        return bytes(data)

    def _process_pdu(self, func_code: int, data: bytes) -> bytes:
        if func_code == 0x03:  # Read Holding Registers
            if len(data) < 4:
                return struct.pack(">BB", func_code | 0x80, 0x03)  # Illegal data value
            start_addr, quantity = struct.unpack(">HH", data[:4])
            try:
                values = self.registers.read_holding_registers(start_addr, quantity)
                byte_count = quantity * 2
                res = bytearray([func_code, byte_count])
                for v in values:
                    res.extend(struct.pack(">H", v))
                return bytes(res)
            except IndexError:
                return struct.pack(">BB", func_code | 0x80, 0x02)  # Illegal data address

        elif func_code == 0x06:  # Write Single Register
            if len(data) < 4:
                return struct.pack(">BB", func_code | 0x80, 0x03)
            addr, val = struct.unpack(">HH", data[:4])
            try:
                self.registers.write_single_register(addr, val)
                return struct.pack(">BHH", func_code, addr, val)
            except IndexError:
                return struct.pack(">BB", func_code | 0x80, 0x02)

        elif func_code == 0x10:  # Write Multiple Registers
            if len(data) < 5:
                return struct.pack(">BB", func_code | 0x80, 0x03)
            start_addr, quantity, byte_count = struct.unpack(">HHB", data[:5])
            if len(data) < 5 + byte_count:
                return struct.pack(">BB", func_code | 0x80, 0x03)
            try:
                offset = 5
                for i in range(quantity):
                    val = struct.unpack(">H", data[offset : offset + 2])[0]
                    self.registers.write_single_register(start_addr + i, val)
                    offset += 2
                return struct.pack(">BHH", func_code, start_addr, quantity)
            except IndexError:
                return struct.pack(">BB", func_code | 0x80, 0x02)

        else:
            return struct.pack(">BB", func_code | 0x80, 0x01)  # Illegal function


class ModbusServer:
    """Embedded Modbus TCP Server running in background thread."""

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 5020,
        on_setpoint_write: Callable[[float], None] | None = None,
    ) -> None:
        self.host = host
        self.port = port
        self.registers = ModbusRegisters()
        self.registers.on_setpoint_write = on_setpoint_write
        self._server: socketserver.ThreadingTCPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        class BoundHandler(ModbusTCPHandler):
            registers = self.registers

        # Allow address reuse
        socketserver.ThreadingTCPServer.allow_reuse_address = True
        try:
            self._server = socketserver.ThreadingTCPServer((self.host, self.port), BoundHandler)
            self._thread = threading.Thread(
                target=self._server.serve_forever, name="ModbusTCPServer", daemon=True
            )
            self._thread.start()
            logger.info("Modbus TCP Server started on %s:%d", self.host, self.port)
        except Exception as e:
            logger.warning("Could not bind Modbus TCP server on port %d: %s", self.port, e)

    def stop(self) -> None:
        if self._server:
            logger.info("Stopping Modbus TCP Server...")
            self._server.shutdown()
            self._server.server_close()
            self._server = None

    def update_telemetry(
        self,
        soc_pct: float,
        power_kw: float,
        voltage_v: float,
        temp_c: float,
        state_str: str,
    ) -> None:
        self.registers.update_telemetry(
            soc_pct=soc_pct,
            power_kw=power_kw,
            voltage_v=voltage_v,
            temp_c=temp_c,
            state_str=state_str,
        )
