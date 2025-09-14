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
import os
import platform
import socket
import subprocess
import time
from http import client as http_client
from typing import Dict, Optional

# ────────────────────────────────────────────────────────────
# 0.  Configuration ─ loading sentry_secret file
# ────────────────────────────────────────────────────────────
def load_sentry_config() -> Dict[str, str]:
    """
    Load configuration from sentry_secret file.
    Returns a dictionary with SERVER_HOST, SERVER_PORT, and SENTRY_SECRET.
    """
    config = {
        "SERVER_HOST": "localhost",
        "SERVER_PORT": "3000", 
        "SENTRY_SECRET": None
    }
    
    # Look for sentry_secret file in the same directory as this script
    script_dir = os.path.dirname(os.path.abspath(__file__))
    secret_file = os.path.join(script_dir, "sentry_secret")
    
    if not os.path.exists(secret_file):
        print(f"❌ Error: sentry_secret file not found at {secret_file}")
        print("Please create a sentry_secret file with the following format:")
        print("SERVER_HOST=your-server-host")
        print("SERVER_PORT=your-server-port")
        print("SENTRY_SECRET=your-magic-string")
        exit(1)
    
    try:
        with open(secret_file, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    if '=' in line:
                        key, value = line.split('=', 1)
                        key = key.strip()
                        value = value.strip()
                        if key in config:
                            config[key] = value
    except Exception as e:
        print(f"❌ Error reading sentry_secret file: {e}")
        exit(1)
    
    if not config["SENTRY_SECRET"]:
        print("❌ Error: SENTRY_SECRET not found in sentry_secret file")
        exit(1)
    
    return config

# Load configuration at startup
SENTRY_CONFIG = load_sentry_config()

# ────────────────────────────────────────────────────────────
# 1.  Helpers ─ gathering node information
# ────────────────────────────────────────────────────────────
def iso_timestamp() -> str:
    """UTC timestamp in ISO-8601 with trailing Z (no microseconds)."""
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


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
        "sentry_secret": SENTRY_CONFIG["SENTRY_SECRET"],
    }


# ────────────────────────────────────────────────────────────
# 2.  Transport ─ HTTP POST to Bun server
# ────────────────────────────────────────────────────────────
SERVER_HOST = SENTRY_CONFIG["SERVER_HOST"]
SERVER_PORT = int(SENTRY_CONFIG["SERVER_PORT"])
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
    print(f"📡 Connecting to server: {SERVER_HOST}:{SERVER_PORT}")
    print(f"🔐 Using authentication: {'*' * len(SENTRY_CONFIG['SENTRY_SECRET'])}")
    while True:
        data = build_payload()
        post_payload(data)
        time.sleep(POST_INTERVAL)

