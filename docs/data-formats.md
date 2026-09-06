# Data Formats Specification

**Version:** 1.0  
**Compliance:** SPEC §3.4, §6.1, §7  

## 1. CSV Import Formats

### 1.1. Day-Ahead Market Prices (`dam_prices`)
File format for hourly Ukrainian DAM prices (Source: Market Operator / SE "Market Operator"):
```csv
date,hour,price_uah_mwh,zone
2026-03-01,1,3450.00,OES
2026-03-01,2,3100.50,OES
...
2026-03-01,24,5200.00,OES
```
- `date`: `YYYY-MM-DD`
- `hour`: integer `1..24`
- `price_uah_mwh`: float, price in UAH/MWh
- `zone`: string, default `OES`

### 1.2. Site Load Consumption (`site_load`)
Industrial consumption load profile and onsite PV:
```csv
ts,load_kw,pv_kw
2026-03-01T00:00:00Z,240.50,0.00
2026-03-01T00:15:00Z,238.20,0.00
```
- `ts`: ISO 8601 UTC timestamp (`YYYY-MM-DDTHH:MM:SSZ`)
- `load_kw`: facility active power consumption in kW
- `pv_kw`: optional onsite solar generation in kW (default 0.0)

### 1.3. Weather Data (`weather`)
Meteorological factors influencing prices and PV generation:
```csv
ts,temp_c,cloud_cover,wind_speed_ms
2026-03-01T00:00:00Z,4.2,0.8,3.5
2026-03-01T01:00:00Z,3.8,0.7,3.2
```
- `ts`: ISO 8601 UTC timestamp
- `temp_c`: ambient temperature in °C
- `cloud_cover`: cloudiness factor from 0.0 (clear sky) to 1.0 (overcast)
- `wind_speed_ms`: wind velocity in m/s

---

## 2. API Series Retrieval Format (`GET /api/data/series`)
Response schema:
```json
{
  "type": "price",
  "step": "1h",
  "count": 24,
  "data": [
    {
      "ts": "2026-03-01T00:00:00Z",
      "value": 3450.0
    }
  ]
}
```
