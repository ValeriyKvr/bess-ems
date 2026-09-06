# BESS Modbus TCP Register Map

The BESS simulator embeds a Modbus TCP server (per SPEC §4.3) listening by default on port `5020`. It enables direct industrial PLC/SCADA integration alongside or in place of MQTT telemetry.

## Protocol Specification
- **Transport:** Modbus TCP (Ethernet / IP)
- **Default Port:** `5020` (Configurable via `BESS_MODBUS_PORT` in `.env`)
- **Unit ID / Slave ID:** `1`
- **Register Architecture:** 16-bit unsigned / signed Holding Registers (Function Codes `0x03` Read, `0x06` Write Single, `0x10` Write Multiple).
- **Byte Order:** Big-Endian (Network standard).

---

## Holding Register Memory Map

| Register (1-based) | Modbus Address (0-based) | Register Name | Data Type | Units / Scaling | Access | Description / Valid Range |
|:---:|:---:|:---|:---:|:---:|:---:|:---|
| **40001** | `0x0000` | `SoC` | `uint16` | `0.01 %` | RO | State of Charge. Range: `0` to `10000` (`0.00%` to `100.00%`). |
| **40002** | `0x0001` | `Active Power` | `int16` | `1 kW` | RO | Current active power. **Sign convention:** `< 0` Discharge, `> 0` Charge. Range: `-32768` to `+32767`. |
| **40003** | `0x0002` | `DC Voltage` | `uint16` | `0.1 V` | RO | DC Bus Voltage. Scale: `1 = 0.1 V` (e.g. `8000` = `800.0 V`). |
| **40004** | `0x0003` | `Cell Temperature` | `int16` | `0.1 °C` | RO | Maximum cell temperature. Scale: `1 = 0.1 °C` (e.g. `250` = `25.0 °C`). |
| **40005** | `0x0004` | `BESS State` | `uint16` | Enum | RO | Battery FSM State: <br>`0` = OFF<br>`1` = STANDBY<br>`2` = CHARGING<br>`3` = DISCHARGING<br>`4` = FAULT |
| **40006** | `0x0005` | `Power Setpoint` | `int16` | `1 kW` | RW | Active power command dispatched to battery inverter. **Sign convention:** `< 0` Discharge, `> 0` Charge. Range: `[-P_max, +P_max]`. |

---

## Python Example (Reading Registers with standard sockets or pymodbus)

### Raw Socket Modbus TCP Query
```python
import socket
import struct

# Connect to BESS Modbus TCP Server
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.connect(("127.0.0.1", 5020))

# Modbus TCP Request: Transaction ID 1, Protocol 0, Length 6, Unit 1, Func 3 (Read), Addr 0, Count 6
request = struct.pack(">HHHBBHH", 1, 0, 6, 1, 3, 0, 6)
s.sendall(request)

response = s.recv(1024)
header = response[:9]
payload = response[9:]
soc_raw, power_kw, voltage_raw, temp_raw, state, setpoint_kw = struct.unpack(
    ">HhHhHh", payload
)

print(f"SoC: {soc_raw / 100.0:.2f}%")
print(f"Power: {power_kw} kW")
print(f"DC Voltage: {voltage_raw / 10.0:.1f} V")
print(f"Temperature: {temp_raw / 10.0:.1f} °C")
print(f"State: {state}")
print(f"Active Setpoint: {setpoint_kw} kW")
s.close()
```

### PyModbus Client
```python
from pymodbus.client import ModbusTcpClient

client = ModbusTcpClient("localhost", port=5020)
client.connect()

# Read 6 holding registers starting from address 0
rr = client.read_holding_registers(address=0, count=6, slave=1)
if not rr.isError():
    soc = rr.registers[0] / 100.0
    power = (
        rr.registers[1]
        if rr.registers[1] < 32768
        else rr.registers[1] - 65536
    )
    print(f"BESS SoC: {soc}%, Power: {power} kW")

# Write power setpoint -250 kW (discharge)
client.write_register(address=5, value=-250 & 0xFFFF, slave=1)
client.close()
```
