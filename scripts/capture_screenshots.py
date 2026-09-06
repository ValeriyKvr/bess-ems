"""Capture high-resolution screenshots of all web application pages for documentation (SPEC §14 Stage 8)."""

import os
import subprocess
import time

PAGES = [
    ("01_dashboard.png", "http://localhost:5173/#dashboard"),
    ("02_settings.png", "http://localhost:5173/#settings"),
    ("03_data.png", "http://localhost:5173/#data"),
    ("04_forecasting.png", "http://localhost:5173/#ml"),
    ("05_reports.png", "http://localhost:5173/#reports"),
    ("06_logs.png", "http://localhost:5173/#logs"),
]


def capture_all() -> None:
    edge_path = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
    screenshots_dir = os.path.abspath(r"docs\screenshots")
    os.makedirs(screenshots_dir, exist_ok=True)

    print(f"Capturing {len(PAGES)} screenshots to {screenshots_dir}...")

    for filename, url in PAGES:
        out_file = os.path.join(screenshots_dir, filename)
        cmd = [
            edge_path,
            "--headless=new",
            "--disable-gpu",
            "--window-size=1920,1080",
            f"--screenshot={out_file}",
            url,
        ]
        print(f"Capturing {filename} from {url}...")
        subprocess.run(cmd, capture_output=True)
        time.sleep(0.5)

        if os.path.exists(out_file):
            size_kb = os.path.getsize(out_file) / 1024.0
            print(f"  [OK] Saved {filename} ({size_kb:.1f} KB)")
        else:
            print(f"  [ERROR] Failed to save {filename}")

    print("\nAll screenshots captured successfully.")


if __name__ == "__main__":
    capture_all()
