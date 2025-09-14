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

# Optional imports for enhanced hardware detection
try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False

try:
    import GPUtil
    GPUTIL_AVAILABLE = True
except ImportError:
    GPUTIL_AVAILABLE = False

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
    Enhanced CPU detection with support for multiple platforms.
    Tries platform-specific methods first, then falls back to generic methods.
    """
    system = platform.system()
    
    # macOS - use sysctl
    if system == "Darwin":
        try:
            return (
                subprocess.check_output(["sysctl", "-n", "machdep.cpu.brand_string"],
                                        text=True)
                .strip()
            )
        except Exception:
            pass
    
    # Linux - try multiple methods
    elif system == "Linux":
        # Try /proc/cpuinfo first (most reliable on Linux)
        try:
            with open("/proc/cpuinfo", "r") as f:
                for line in f:
                    if line.startswith("model name"):
                        return line.split(":")[1].strip()
        except Exception:
            pass
        
        # Try lscpu command
        try:
            result = subprocess.check_output(["lscpu"], text=True)
            for line in result.split("\n"):
                if "Model name:" in line:
                    return line.split(":")[1].strip()
        except Exception:
            pass
        
        # Try dmidecode (if available)
        try:
            result = subprocess.check_output(["dmidecode", "-t", "processor"], text=True)
            for line in result.split("\n"):
                if "Version:" in line and "Not Specified" not in line:
                    return line.split(":")[1].strip()
        except Exception:
            pass
    
    # Windows - try wmic
    elif system == "Windows":
        try:
            result = subprocess.check_output(
                ["wmic", "cpu", "get", "name", "/value"], 
                text=True, 
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            for line in result.split("\n"):
                if line.startswith("Name="):
                    return line.split("=", 1)[1].strip()
        except Exception:
            pass
    
    # Raspberry Pi specific - try vcgencmd
    try:
        result = subprocess.check_output(["vcgencmd", "get_cpu"], text=True)
        if "arm" in result.lower():
            # Try to get more specific info from /proc/cpuinfo
            try:
                with open("/proc/cpuinfo", "r") as f:
                    for line in f:
                        if line.startswith("Hardware"):
                            hardware = line.split(":")[1].strip()
                            if hardware != "BCM2835":  # Skip generic Pi hardware
                                return f"Raspberry Pi {hardware}"
                            break
            except Exception:
                pass
            return "Raspberry Pi ARM"
    except Exception:
        pass
    
    # Fallback to platform.processor() or psutil
    if PSUTIL_AVAILABLE:
        try:
            # psutil provides more detailed CPU info
            cpu_info = psutil.cpu_freq()
            if cpu_info and cpu_info.max:
                return f"CPU @ {cpu_info.max:.0f}MHz"
        except Exception:
            pass
    
    # Final fallback
    processor = platform.processor()
    if processor and processor != "":
        return processor
    
    return "unknown-cpu"


def get_gpu_name() -> str:
    """
    Enhanced GPU detection with support for multiple platforms.
    Tries platform-specific methods first, then falls back to generic methods.
    """
    system = platform.system()
    
    # Try GPUtil first (works for NVIDIA GPUs on all platforms)
    if GPUTIL_AVAILABLE:
        try:
            gpus = GPUtil.getGPUs()
            if gpus:
                return gpus[0].name
        except Exception:
            pass
    
    # macOS - use system_profiler
    if system == "Darwin":
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
    
    # Linux - try multiple methods
    elif system == "Linux":
        # Try lspci for PCI devices
        try:
            result = subprocess.check_output(["lspci"], text=True)
            for line in result.split("\n"):
                if "vga" in line.lower() or "display" in line.lower() or "3d" in line.lower():
                    # Extract GPU name from lspci output
                    gpu_name = line.split(":")[-1].strip()
                    if gpu_name and gpu_name != "":
                        return gpu_name
        except Exception:
            pass
        
        # Try nvidia-smi for NVIDIA GPUs
        try:
            result = subprocess.check_output(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"], text=True)
            if result.strip():
                return result.strip()
        except Exception:
            pass
        
        # Try /proc/driver/nvidia/gpus/ for NVIDIA GPUs
        try:
            nvidia_dir = "/proc/driver/nvidia/gpus/"
            if os.path.exists(nvidia_dir):
                for gpu_dir in os.listdir(nvidia_dir):
                    info_file = os.path.join(nvidia_dir, gpu_dir, "information")
                    if os.path.exists(info_file):
                        with open(info_file, "r") as f:
                            for line in f:
                                if line.startswith("Model:"):
                                    return line.split(":")[1].strip()
        except Exception:
            pass
        
        # Try glxinfo for OpenGL info
        try:
            result = subprocess.check_output(["glxinfo"], text=True)
            for line in result.split("\n"):
                if "OpenGL renderer string:" in line:
                    renderer = line.split(":")[1].strip()
                    if renderer and renderer != "":
                        return renderer
        except Exception:
            pass
    
    # Windows - try wmic
    elif system == "Windows":
        try:
            result = subprocess.check_output(
                ["wmic", "path", "win32_VideoController", "get", "name", "/value"], 
                text=True, 
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            for line in result.split("\n"):
                if line.startswith("Name=") and "=" in line:
                    gpu_name = line.split("=", 1)[1].strip()
                    if gpu_name and gpu_name != "":
                        return gpu_name
        except Exception:
            pass
    
    # Raspberry Pi specific - try vcgencmd
    try:
        result = subprocess.check_output(["vcgencmd", "get_cpu"], text=True)
        if "arm" in result.lower():
            # Check if it's a Pi with GPU
            try:
                gpu_mem = subprocess.check_output(["vcgencmd", "get_mem", "gpu"], text=True)
                if "gpu=" in gpu_mem:
                    return "Raspberry Pi GPU"
            except Exception:
                pass
            return "Raspberry Pi VideoCore"
    except Exception:
        pass
    
    # Try to detect integrated graphics from CPU info
    try:
        cpu_name = get_cpu_name().lower()
        if "intel" in cpu_name:
            return "Intel Integrated Graphics"
        elif "amd" in cpu_name:
            return "AMD Integrated Graphics"
        elif "arm" in cpu_name or "raspberry" in cpu_name:
            return "ARM Mali GPU"
    except Exception:
        pass
    
    return "unknown-gpu"


def get_hardware_summary() -> str:
    """
    Get a brief hardware summary for debugging purposes.
    """
    try:
        cpu = get_cpu_name()
        gpu = get_gpu_name()
        return f"CPU: {cpu}, GPU: {gpu}"
    except Exception:
        return "Hardware detection failed"

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
    print(f"🖥️  Hardware: {get_hardware_summary()}")
    
    # Show optional dependency status
    if not PSUTIL_AVAILABLE:
        print("⚠️  psutil not available - install with 'pip install psutil' for enhanced CPU detection")
    if not GPUTIL_AVAILABLE:
        print("⚠️  GPUtil not available - install with 'pip install gputil' for enhanced GPU detection")
    
    while True:
        data = build_payload()
        post_payload(data)
        time.sleep(POST_INTERVAL)

