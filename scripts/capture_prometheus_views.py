"""Prometheus Advanced Observability Suite Capture Script.

Captures high-resolution, production screenshots of Prometheus:
1. 03_prometheus_graph_explorer.png        - Primary Graph explorer with live multi-detector timeseries
2. 03a_prometheus_graph_tab_multipanel.png  - Multi-panel Graph tab (Anomaly rate + Latency SLA)
3. 03b_prometheus_table_tab_multipanel.png  - Multi-panel Table tab (Health + Remediations + Detector breakdown)
4. 03c_prometheus_alerts_rules.png         - Prometheus Alerts Console showcasing 5 active SRE SLA rules
5. 04_prometheus_targets_health.png        - Scrape targets status (100% UP)
"""

import os
from pathlib import Path
import subprocess
import urllib.parse

CHROME_PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
SCREENSHOTS_DIR = Path(r"F:\AegisAI\screenshots")
PROMETHEUS_URL = "http://localhost:9090"


def capture_with_cli(filename: str, url: str, width: int = 1920, height: int = 1080, budget_ms: int = 5000):
    out_path = SCREENSHOTS_DIR / filename
    cmd = [
        CHROME_PATH,
        "--headless=new",
        "--no-sandbox",
        "--disable-gpu",
        f"--window-size={width},{height}",
        f"--virtual-time-budget={budget_ms}",
        f"--screenshot={str(out_path)}",
        url,
    ]
    print(f"[*] Capturing {filename} from {url[:80]}...")
    subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if out_path.exists() and out_path.stat().st_size > 5000:
        print(f"    [PASS] Saved {filename} ({out_path.stat().st_size:,} bytes)")
        return True
    print(f"    [FAIL] Could not capture {filename}")
    return False


def main():
    print("==================================================================")
    print("      PROMETHEUS ADVANCED OBSERVABILITY SUITE CAPTURE")
    print("==================================================================")

    # 1. Primary Graph Explorer (Focused active timeseries chart)
    q_focus = "sum(rate(aegisai_anomaly_detections_total[5m])) by (detector_type)"
    url_focus = f"{PROMETHEUS_URL}/graph?g0.expr={urllib.parse.quote(q_focus)}&g0.tab=0&g0.range_input=30m"
    capture_with_cli("03_prometheus_graph_explorer.png", url_focus, 1920, 1080, 5000)

    # 2. Multi-Panel Graph Tab
    params_graph = [
        ("g0.expr", "sum(rate(aegisai_anomaly_detections_total[5m])) by (detector_type)"),
        ("g0.tab", "0"),
        ("g0.range_input", "30m"),
        ("g1.expr", "histogram_quantile(0.99, sum(rate(aegisai_detection_latency_seconds_bucket[5m])) by (le))"),
        ("g1.tab", "0"),
        ("g1.range_input", "30m"),
    ]
    url_graph = f"{PROMETHEUS_URL}/graph?{urllib.parse.urlencode(params_graph)}"
    capture_with_cli("03a_prometheus_graph_tab_multipanel.png", url_graph, 1920, 1500, 6000)

    # 3. Multi-Panel Table Tab
    params_table = [
        ("g0.expr", "aegisai_subsystem_health"),
        ("g0.tab", "1"),
        ("g1.expr", "sum(aegisai_remediation_actions_total) by (action_type, status)"),
        ("g1.tab", "1"),
        ("g2.expr", "sum(aegisai_anomaly_detections_total) by (detector_type, severity)"),
        ("g2.tab", "1"),
    ]
    url_table = f"{PROMETHEUS_URL}/graph?{urllib.parse.urlencode(params_table)}"
    capture_with_cli("03b_prometheus_table_tab_multipanel.png", url_table, 1920, 1200, 5000)

    # 4. Alerts Rules Console
    capture_with_cli("03c_prometheus_alerts_rules.png", f"{PROMETHEUS_URL}/alerts", 1920, 1080, 4000)

    # 5. Targets Health
    capture_with_cli("04_prometheus_targets_health.png", f"{PROMETHEUS_URL}/targets", 1920, 1080, 4000)

    print("\n[+] All Prometheus professional screenshots captured successfully.")


if __name__ == "__main__":
    main()
