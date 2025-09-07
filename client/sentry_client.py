#!/usr/bin/env python3
"""
mata_sentry_client.py
Small heartbeat agent for Mata Sentry render-node monitoring.
Sends JSON payloads via HTTP POST once every 30 s.

Current payload spec
{
  "hostname": "render-node-01",
  "os": "macOS 15.6.1 arm64",
  "cpu": "cpu-name",
  "gpu": "gpu-name",
  "timestamp": "2025-09-08T02:21:00Z"
}
"""

import datetime
import json
import platform
import socket
import subprocess
import time
from http import client as http_client
from typing import Dict

# ────────────────────────────────────────────────────────────
# 1.  Helpers ─ gathering node information
# ────────────────────────────────────────────────────────────
def iso_timestamp() -> str:
    """UTC timestamp in ISO-8601 with trailing Z (no microseconds)."""
    return datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def get_hostname() -> str:
    return socket.gethostname()


def get_os_string() -> str:
    """
    Return OS string like 'macOS 15.6.1 arm64'.
    Falls back to platform.system/release/architecture if sw_vers is missing.
    """
    if platform.system() == "Darwin":
        try:
            product = (
                subprocess.check_output(["sw_vers", "-productVersion"], text=True)
                .strip()
            )
            arch = platform.machine()
            return f"macOS {product} {arch}"
        except Exception:
            pass  # fall back below
    # Generic fallback
    return f"{platform.system()} {platform.release()} {platform.machine()}"


def get_cpu_name() -> str:
    """
    Tries sysctl (macOS) first, otherwise falls back to platform.processor().
    """
    if platform.system() == "Darwin":
        try:
            return (
                subprocess.check_output(["sysctl", "-n", "machdep.cpu.brand_string"],
                                        text=True)
                .strip()
            )
        except Exception:
            pass
    return platform.processor() or "unknown-cpu"


def get_gpu_name() -> str:
    """
    Uses system_profiler (macOS). For Windows/Linux you’ll replace this block.
    """
    if platform.system() == "Darwin":
        try:
            sp = subprocess.check_output(
                ["system_profiler", "SPDisplaysDataType", "-json"], text=True
            )
            data = json.loads(sp)
            gpus = data["SPDisplaysDataType"]
            # Take first GPU name
            if gpus:
                return gpus[0].get("_name", "unknown-gpu")
        except Exception:
            pass
    return "unknown-gpu"


def build_payload() -> Dict[str, str]:
    return {
        "hostname": get_hostname(),
        "os": get_os_string(),
        "cpu": get_cpu_name(),
        "gpu": get_gpu_name(),
        "timestamp": iso_timestamp(),
    }


# ────────────────────────────────────────────────────────────
# 2.  Transport ─ HTTP POST to Bun server
# ────────────────────────────────────────────────────────────
SERVER_HOST = "localhost"      # change to IP/hostname of Bun server
SERVER_PORT = 3000             # Bun default
SERVER_PATH = "/submit"  # agreed endpoint
HEADERS = {"Content-Type": "application/json"}

def post_payload(payload: Dict[str, str]) -> None:
    body = json.dumps(payload)
    conn = http_client.HTTPConnection(SERVER_HOST, SERVER_PORT, timeout=10)
    try:
        conn.request("POST", SERVER_PATH, body=body, headers=HEADERS)
        response = conn.getresponse()
        print(f"{payload['timestamp']} → {response.status} {response.reason}")
        # Optional: read response body if needed
        conn.close()
    except Exception as exc:
        print(f"{payload['timestamp']} ✗ POST failed: {exc}")


# ────────────────────────────────────────────────────────────
# 3.  Main loop
# ────────────────────────────────────────────────────────────
POST_INTERVAL = 30  # seconds

if __name__ == "__main__":
    print("Mata Sentry client started. Press Ctrl-C to quit.")
    while True:
        data = build_payload()
        post_payload(data)
        time.sleep(POST_INTERVAL)

