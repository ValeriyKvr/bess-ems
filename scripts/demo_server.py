"""Standalone Demo HTTP Server for UI Screenshots & Visual Verification (SPEC §14 Stage 8).

Serves web/dist production bundle and provides populated API endpoints
for Settings, ML, Data, Reports, and Logs without requiring an external database.
"""

# ruff: noqa: E402
import http.server
import json
import socketserver
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

# Ensure ems is discoverable for Pydantic schemas
PROJECT_ROOT = Path(__file__).resolve().parent.parent
EMS_DIR = PROJECT_ROOT / "ems"
if str(EMS_DIR) not in sys.path:
    sys.path.insert(0, str(EMS_DIR))

from ems.api.settings import SECTION_MODELS

PORT = 5173
DIST_DIR = str(PROJECT_ROOT / "web" / "dist")


class DemoServerHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DIST_DIR, **kwargs)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        # 1. API: Settings Schema & Values
        if path.startswith("/api/settings/"):
            parts = path.strip("/").split("/")
            # e.g., ['api', 'settings', 'battery', 'schema'] or ['api', 'settings', 'battery']
            if len(parts) >= 3:
                section = parts[2]
                if section in SECTION_MODELS:
                    model_cls = SECTION_MODELS[section]
                    if len(parts) == 4 and parts[3] == "schema":
                        self._send_json(
                            {
                                "section": section,
                                "schema": model_cls.model_json_schema(),
                            }
                        )
                        return
                    elif len(parts) == 3:
                        self._send_json(model_cls().model_dump())
                        return

        # 2. API: ML Models Registry
        elif path == "/api/ml/models":
            self._send_json(
                [
                    {
                        "name": "Naive Baseline",
                        "model": "naive",
                        "version": "v1.0.0",
                        "target": "price",
                        "mae": 412.50,
                        "mape": 7.8,
                        "rmse": 534.20,
                        "spearman_rank_corr": 0.82,
                        "status": "ready",
                        "active": False,
                    },
                    {
                        "name": "LightGBM 24h Direct",
                        "model": "lightgbm",
                        "version": "v1.2.0",
                        "target": "price",
                        "mae": 238.40,
                        "mape": 4.1,
                        "rmse": 308.15,
                        "spearman_rank_corr": 0.94,
                        "status": "ready",
                        "active": True,
                    },
                    {
                        "name": "Seq2Seq PyTorch LSTM",
                        "model": "lstm",
                        "version": "v1.1.0",
                        "target": "price",
                        "mae": 254.10,
                        "mape": 4.5,
                        "rmse": 322.80,
                        "spearman_rank_corr": 0.92,
                        "status": "ready",
                        "active": False,
                    },
                ]
            )
            return

        # 3. API: ML Backtest
        elif path == "/api/ml/backtest":
            self._send_json(
                [
                    {
                        "model": "Naive (Вчора)",
                        "net_uah": 17611.73,
                        "pct_of_ideal": 26.3,
                        "description": "Baseline персистенція",
                    },
                    {
                        "model": "LightGBM",
                        "net_uah": 43235.81,
                        "pct_of_ideal": 64.5,
                        "description": "24 Direct Models + Quantiles",
                    },
                    {
                        "model": "Perfect Foresight (Ідеал)",
                        "net_uah": 67081.79,
                        "pct_of_ideal": 100.0,
                        "description": "Теоретична верхня межа (істинні ціни)",
                    },
                ]
            )
            return

        # 4. API: Forecasts (p10, value, p90)
        elif path == "/api/forecasts":
            now = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
            items = []
            prices = [
                3100,
                2950,
                2900,
                3050,
                3400,
                4600,
                5500,
                5700,
                5400,
                4900,
                4600,
                4500,
                4600,
                4900,
                5300,
                6100,
                7000,
                7300,
                7000,
                6300,
                5200,
                4300,
                3700,
                3300,
            ]
            for i in range(24):
                t = now + timedelta(hours=i)
                p = prices[i]
                items.append(
                    {
                        "ts": t.isoformat(),
                        "value": p,
                        "p10": p * 0.92,
                        "p90": p * 1.08,
                    }
                )
            self._send_json({"target": "price", "forecasts": items})
            return

        # 5. API: Reports Summary
        elif path == "/api/reports/summary":
            self._send_json(
                {
                    "period_from": "2026-02-01T00:00:00Z",
                    "period_to": "2026-03-01T23:00:00Z",
                    "cost_baseline_uah": 1141373.64,
                    "cost_actual_uah": 996674.57,
                    "revenue_uah": 24520.00,
                    "degradation_uah": 14210.00,
                    "net_savings_uah": 43235.81,
                    "cycles": 20.29,
                    "payback_years": 4.8,
                    "hourly": [],
                }
            )
            return

        # 6. API: Compare Strategies
        elif path == "/api/reports/compare-strategies":
            self._send_json(
                [
                    {
                        "strategy": "TOU_SIMPLE",
                        "cost_baseline_uah": 270729.08,
                        "cost_actual_uah": 282130.63,
                        "revenue_uah": 4210.00,
                        "degradation_uah": 15576.97,
                        "net_uah": 17611.73,
                        "cycles": 12.28,
                    },
                    {
                        "strategy": "ARBITRAGE (MILP)",
                        "cost_baseline_uah": 270729.08,
                        "cost_actual_uah": 244426.95,
                        "revenue_uah": 9850.00,
                        "degradation_uah": 14730.66,
                        "net_uah": 43235.81,
                        "cycles": 20.29,
                    },
                    {
                        "strategy": "PEAK_SHAVING",
                        "cost_baseline_uah": 270729.08,
                        "cost_actual_uah": 251100.20,
                        "revenue_uah": 3100.00,
                        "degradation_uah": 9200.00,
                        "net_uah": 36120.40,
                        "cycles": 14.10,
                    },
                    {
                        "strategy": "SELF_CONSUMPTION",
                        "cost_baseline_uah": 270729.08,
                        "cost_actual_uah": 259800.00,
                        "revenue_uah": 1800.00,
                        "degradation_uah": 8100.00,
                        "net_uah": 28450.00,
                        "cycles": 11.50,
                    },
                ]
            )
            return

        # 7. API: Data Heatmap (24h x 7d)
        elif path == "/api/data/heatmap":
            matrix = []
            for d in range(7):
                for h in range(24):
                    base = 3200 + 3000 * ((1 - ((h - 18) / 8) ** 2) if 10 <= h <= 22 else 0.1)
                    if d in (5, 6):
                        base *= 0.85
                    matrix.append([h, d, round(base, 1)])
            self._send_json({"type": "price", "matrix": matrix})
            return

        # 8. API: Dispatch Logs
        elif path == "/api/dispatch/log":
            items = []
            now = datetime.now(UTC)
            reasons = ["schedule", "schedule", "reactive_derate", "schedule", "safe_mode_clear"]
            for i in range(15):
                t = now - timedelta(minutes=i * 5)
                items.append(
                    {
                        "id": 100 - i,
                        "ts": t.isoformat(),
                        "setpoint_kw": -250.0 if i % 2 == 0 else 300.0,
                        "actual_kw": -248.5 if i % 2 == 0 else 298.0,
                        "reason": reasons[i % len(reasons)],
                        "schedule_id": f"sch-20260301-{10 - i // 2}",
                        "override": i == 2,
                    }
                )
            self._send_json(
                {
                    "items": items,
                    "total": 450,
                    "page": 1,
                    "limit": 15,
                }
            )
            return

        # 9. API: Events Feed
        elif path == "/api/events":
            self._send_json(
                [
                    {
                        "event": "OPTIMIZATION_COMPLETED",
                        "schedule_id": "sch-20260301-01",
                        "strategy": "ARBITRAGE",
                        "ts": datetime.now(UTC).isoformat(),
                    },
                    {
                        "event": "MARKET_PRICES_PUBLISHED",
                        "target_date": "2026-03-02",
                        "count": 24,
                        "ts": datetime.now(UTC).isoformat(),
                    },
                ]
            )
            return

        # Fallback to serving static SPA
        super().do_GET()

    def _send_json(self, data: dict | list) -> None:
        raw = json.dumps(data).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(raw)


def run_demo() -> None:
    socketserver.ThreadingTCPServer.allow_reuse_address = True
    with socketserver.ThreadingTCPServer(("0.0.0.0", PORT), DemoServerHandler) as httpd:
        print(f"Demo HTTP Server running on http://localhost:{PORT}")
        httpd.serve_forever()


if __name__ == "__main__":
    run_demo()
