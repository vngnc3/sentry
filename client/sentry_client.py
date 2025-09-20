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
  "cpu_temperature": "45.2°C",  // Optional, if available
  "gpu_temperature": "62.1°C",  // Optional, if available
  "timestamp": "2025-09-08T02:21:00Z"
}

Temperature monitoring supports:
- CPU: Linux (psutil), macOS (powermetrics), Windows (WMI)
- GPU: NVIDIA (pynvml/nvidia-smi), AMD/Intel (sysfs), various fallbacks
"""

import datetime
import json
import os
import platform
import re
import socket
import subprocess
import sys
import time
from http import client as http_client
from pathlib import Path
from typing import Dict, List, Optional, Tuple

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

# Optional imports for temperature detection
try:
    import pynvml
    PYNVML_AVAILABLE = True
except ImportError:
    PYNVML_AVAILABLE = False

try:
    import wmi
    WMI_AVAILABLE = True
except ImportError:
    WMI_AVAILABLE = False

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
# 0.6. User Input and Render Monitoring Configuration
# ────────────────────────────────────────────────────────────
def get_user_input() -> Tuple[str, int, int]:
    """
    Get render directory and frame range from user input.
    Returns (render_directory, start_frame, end_frame).
    """
    print("🎬 Mata Sentry Render Monitor")
    print("=" * 50)
    
    # Get render directory
    while True:
        render_dir = input("📁 Enter render output directory path: ").strip()
        if not render_dir:
            print("❌ Please enter a valid directory path.")
            continue
        
        # Resolve the path (handles relative paths and normalizes separators)
        render_path = Path(render_dir).resolve()
        
        if not render_path.exists():
            print(f"❌ Error: Directory does not exist: {render_path}")
            print("Please ensure the render output directory exists before starting the monitor.")
            exit(1)
        elif not render_path.is_dir():
            print(f"❌ Error: Path exists but is not a directory: {render_path}")
            exit(1)
        else:
            print(f"✅ Using directory: {render_path}")
            break
    
    # Get frame range
    while True:
        try:
            start_frame = int(input("🎬 Enter start frame number: ").strip())
            break
        except ValueError:
            print("❌ Please enter a valid integer for start frame.")
    
    while True:
        try:
            end_frame = int(input("🎬 Enter end frame number: ").strip())
            if end_frame < start_frame:
                print(f"❌ End frame ({end_frame}) must be >= start frame ({start_frame})")
                continue
            break
        except ValueError:
            print("❌ Please enter a valid integer for end frame.")
    
    print(f"✅ Monitoring: {render_dir} for frames {start_frame}-{end_frame}")
    print("=" * 50)
    
    return str(render_path), start_frame, end_frame

def extract_frame_number(filename: str) -> Optional[int]:
    """
    Extract frame number from filename.
    Handles various padding formats (2-10 digits) and file extensions.
    Returns None if no frame number found.
    """
    # Remove file extension
    name_without_ext = os.path.splitext(filename)[0]
    
    # Pattern to match frame numbers at the end of filename
    # Supports 2-10 digit padding with optional separators
    patterns = [
        r'(\d{2,10})$',  # 2-10 digits at the end
        r'[._-](\d{2,10})$',  # 2-10 digits after separator
        r'(\d{2,10})[._-]',  # 2-10 digits before separator at end
    ]
    
    for pattern in patterns:
        match = re.search(pattern, name_without_ext)
        if match:
            try:
                return int(match.group(1))
            except ValueError:
                continue
    
    return None

def get_render_files(render_dir: str, start_frame: int, end_frame: int) -> List[Tuple[str, int, float]]:
    """
    Get all render files in the directory with their frame numbers and modification times.
    Returns list of (filename, frame_number, mtime) tuples.
    """
    render_path = Path(render_dir)
    if not render_path.exists():
        return []
    
    files = []
    for file_path in render_path.iterdir():
        if file_path.is_file():
            frame_num = extract_frame_number(file_path.name)
            if frame_num is not None and start_frame <= frame_num <= end_frame:
                files.append((file_path.name, frame_num, file_path.stat().st_mtime))
    
    # Sort by frame number
    files.sort(key=lambda x: x[1])
    return files

def determine_node_status(render_progress: Dict[str, any], last_frame_count: int, current_time: float, last_post_time: float) -> str:
    """
    Determine the current status of the render node.
    Returns: 'idling', 'rendering', or 'needs attention'
    """
    total_frames = render_progress['total_frames']
    rendered_frames = render_progress['rendered_frames']
    frame_delta_time = render_progress['frame_delta_time']
    
    # If no frames have been rendered yet, it's idling
    if rendered_frames == 0:
        return 'idling'
    
    # If all frames are rendered, it's idling
    if rendered_frames >= total_frames:
        return 'idling'
    
    # If we have a frame delta time, check if we're overdue for a new frame
    if frame_delta_time:
        try:
            # Parse the delta time string (format: "H:MM:SS" or "MM:SS")
            delta_parts = frame_delta_time.split(':')
            if len(delta_parts) == 3:  # H:MM:SS
                hours, minutes, seconds = map(int, delta_parts)
                delta_seconds = hours * 3600 + minutes * 60 + seconds
            elif len(delta_parts) == 2:  # MM:SS
                minutes, seconds = map(int, delta_parts)
                delta_seconds = minutes * 60 + seconds
            else:
                # Fallback: assume it's just seconds
                delta_seconds = int(delta_parts[0])
            
            # Check if we're overdue (4x the known delta time)
            time_since_last_post = current_time - last_post_time
            expected_next_frame_time = delta_seconds * 4
            
            if time_since_last_post > expected_next_frame_time:
                return 'needs attention'
        except (ValueError, IndexError):
            # If we can't parse the delta time, fall back to a simple check
            time_since_last_post = current_time - last_post_time
            if time_since_last_post > 300:  # 5 minutes without activity
                return 'needs attention'
    
    # If we have new frames since last check, we're actively rendering
    if rendered_frames > last_frame_count:
        return 'rendering'
    
    # If we're in the middle of rendering but no new frames, check timing
    time_since_last_post = current_time - last_post_time
    if time_since_last_post > 300:  # 5 minutes without activity
        return 'needs attention'
    
    # Default to rendering if we're in progress
    return 'rendering'

def get_render_progress(render_dir: str, start_frame: int, end_frame: int) -> Dict[str, any]:
    """
    Get current render progress information.
    Returns dictionary with progress stats including delta time between last two frames.
    """
    files = get_render_files(render_dir, start_frame, end_frame)
    
    if not files:
        return {
            "total_frames": end_frame - start_frame + 1,
            "rendered_frames": 0,
            "progress_percentage": 0.0,
            "latest_frame": None,
            "frame_delta_time": None,
            "missing_frames": list(range(start_frame, end_frame + 1))
        }
    
    # Get latest frame info
    latest_file, latest_frame, latest_mtime = files[-1]
    
    # Calculate delta time between last two frames
    frame_delta_time = None
    if len(files) >= 2:
        # Get the second-to-last frame
        second_last_file, second_last_frame, second_last_mtime = files[-2]
        delta_seconds = latest_mtime - second_last_mtime
        frame_delta_time = str(datetime.timedelta(seconds=int(delta_seconds)))
    
    # Find missing frames
    rendered_frames = {frame for _, frame, _ in files}
    missing_frames = [frame for frame in range(start_frame, end_frame + 1) if frame not in rendered_frames]
    
    # Calculate progress
    total_frames = end_frame - start_frame + 1
    rendered_count = len(files)
    progress_percentage = (rendered_count / total_frames) * 100
    
    return {
        "total_frames": total_frames,
        "rendered_frames": rendered_count,
        "progress_percentage": round(progress_percentage, 1),
        "latest_frame": latest_frame,
        "frame_delta_time": frame_delta_time,
        "missing_frames": missing_frames[:10] if len(missing_frames) > 10 else missing_frames  # Limit to first 10
    }

# ────────────────────────────────────────────────────────────
# 0.5. Rolling Display Functions
# ────────────────────────────────────────────────────────────
def clear_and_redraw_status(server_host, server_port, hardware_summary, last_status, last_timestamp, render_progress=None, render_dir=None, start_frame=None, end_frame=None, node_status="idling"):
    """
    Clear the console and redraw the client status display.
    """
    # Clear the console (works on most terminals)
    os.system('clear' if os.name == 'posix' else 'cls')
    
    # Redraw the status
    print("🎬 Mata Sentry Render Monitor - Press Ctrl-C to quit")
    print("=" * 60)
    print(f"📡 Server: {server_host}:{server_port}")
    print(f"🔐 Auth: {'*' * len(SENTRY_CONFIG['SENTRY_SECRET'])}")
    print(f"🖥️  Hardware: {hardware_summary}")
    
    # Show node status
    status_icons = {
        "idling": "😴",
        "rendering": "🎬", 
        "needs attention": "⚠️"
    }
    status_icon = status_icons.get(node_status, "❓")
    print(f"📊 Node Status: {status_icon} {node_status.upper()}")
    
    # Show render monitoring info
    if render_dir and start_frame is not None and end_frame is not None:
        print(f"📁 Monitoring: {render_dir}")
        print(f"🎬 Frame Range: {start_frame}-{end_frame}")
        
        if render_progress:
            progress = render_progress
            print(f"📊 Progress: {progress['rendered_frames']}/{progress['total_frames']} frames ({progress['progress_percentage']}%)")
            
            if progress['latest_frame'] is not None:
                frame_info = f"Latest Frame: {progress['latest_frame']}"
                if progress['frame_delta_time']:
                    frame_info += f" (Δ: {progress['frame_delta_time']})"
                print(f"🎯 {frame_info}")
            else:
                print("🎯 Latest Frame: None (no frames rendered yet)")
            
            if progress['missing_frames']:
                missing_str = str(progress['missing_frames'])[:50]
                if len(progress['missing_frames']) > 10:
                    missing_str += "..."
                print(f"⏳ Missing: {missing_str}")
    
    # Show optional dependency status
    if not PSUTIL_AVAILABLE:
        print("⚠️  psutil not available - install with 'pip install psutil' for enhanced CPU detection")
    if not GPUTIL_AVAILABLE:
        print("⚠️  GPUtil not available - install with 'pip install gputil' for enhanced GPU detection")
    if not PYNVML_AVAILABLE:
        print("⚠️  pynvml not available - install with 'pip install nvidia-ml-py3' for GPU temperature monitoring")
    if not WMI_AVAILABLE:
        print("⚠️  wmi not available - install with 'pip install WMI' for Windows temperature monitoring")
    print('')  # Empty line
    
    # Display current status
    if last_status and last_timestamp:
        status_icon = "✅" if "200" in last_status else "❌"
        print(f"📡 Server Status: {status_icon} {last_status} at {last_timestamp}")
    else:
        print("📡 Server Status: Waiting for first update...")

# ────────────────────────────────────────────────────────────
# 1.  Helpers ─ gathering node information
# ────────────────────────────────────────────────────────────
def iso_timestamp() -> str:
    """UTC timestamp in ISO-8601 with trailing Z (no microseconds)."""
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def get_hostname() -> str:
    return socket.gethostname()


def is_vcgencmd_available() -> bool:
    """
    Check if vcgencmd is available (Raspberry Pi OS only).
    """
    try:
        subprocess.check_output(["vcgencmd", "commands"], text=True, stderr=subprocess.DEVNULL)
        return True
    except Exception:
        return False

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
    
    # ARM-specific detection (including Raspberry Pi)
    if system == "Linux":
        try:
            with open("/proc/cpuinfo", "r") as f:
                cpuinfo = f.read()
                if "arm" in cpuinfo.lower() or "aarch64" in cpuinfo.lower():
                    # Try to get specific ARM processor info
                    for line in cpuinfo.split("\n"):
                        if line.startswith("model name") or line.startswith("Processor"):
                            processor = line.split(":")[1].strip()
                            if processor and processor != "":
                                return processor
                        elif line.startswith("Hardware"):
                            hardware = line.split(":")[1].strip()
                            if hardware and hardware != "":
                                return f"ARM {hardware}"
                        elif line.startswith("CPU architecture"):
                            arch = line.split(":")[1].strip()
                            if arch and arch != "":
                                return f"ARM {arch}"
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
    
    # ARM-specific GPU detection (including Raspberry Pi)
    if system == "Linux":
        try:
            with open("/proc/cpuinfo", "r") as f:
                cpuinfo = f.read()
                if "arm" in cpuinfo.lower() or "aarch64" in cpuinfo.lower():
                    # Check for Mali GPU (common on ARM systems)
                    try:
                        result = subprocess.check_output(["lspci"], text=True)
                        for line in result.split("\n"):
                            if "mali" in line.lower() or "gpu" in line.lower():
                                gpu_name = line.split(":")[-1].strip()
                                if gpu_name and gpu_name != "":
                                    return gpu_name
                    except Exception:
                        pass
                    
                    # Check for VideoCore (Raspberry Pi specific) - only if vcgencmd is available
                    if is_vcgencmd_available():
                        try:
                            result = subprocess.check_output(["vcgencmd", "get_cpu"], text=True)
                            if "arm" in result.lower():
                                return "Raspberry Pi VideoCore"
                        except Exception:
                            pass
                    
                    # Check for ARM GPU in device tree
                    try:
                        if os.path.exists("/proc/device-tree/soc/gpu"):
                            return "ARM Mali GPU"
                    except Exception:
                        pass
                    
                    # Check for GPU in /sys/class/graphics
                    try:
                        if os.path.exists("/sys/class/graphics"):
                            for item in os.listdir("/sys/class/graphics"):
                                if item.startswith("fb"):
                                    # Check for Mali GPU in framebuffer
                                    try:
                                        with open(f"/sys/class/graphics/{item}/name", "r") as f:
                                            name = f.read().strip()
                                            if "mali" in name.lower():
                                                return f"ARM {name}"
                                    except Exception:
                                        pass
                    except Exception:
                        pass
                    
                    # Check for GPU in /dev/dri
                    try:
                        if os.path.exists("/dev/dri"):
                            for item in os.listdir("/dev/dri"):
                                if item.startswith("card"):
                                    # Try to get GPU info from DRI
                                    try:
                                        result = subprocess.check_output(["cat", f"/sys/class/drm/{item}/device/uevent"], text=True)
                                        for line in result.split("\n"):
                                            if "DRIVER=" in line:
                                                driver = line.split("=")[1].strip()
                                                if "mali" in driver.lower():
                                                    return f"ARM Mali GPU ({driver})"
                                    except Exception:
                                        pass
                    except Exception:
                        pass
        except Exception:
            pass
    
    # Try to detect integrated graphics from CPU info
    try:
        cpu_name = get_cpu_name().lower()
        if "intel" in cpu_name:
            return "Intel Integrated Graphics"
        elif "amd" in cpu_name:
            return "AMD Integrated Graphics"
        elif "arm" in cpu_name or "cortex" in cpu_name:
            # For ARM systems, try to detect specific GPU
            if system == "Linux":
                # Check for common ARM GPU drivers
                try:
                    if os.path.exists("/sys/class/drm"):
                        for item in os.listdir("/sys/class/drm"):
                            if "card" in item:
                                # Check if it's a Mali GPU
                                try:
                                    with open(f"/sys/class/drm/{item}/device/uevent", "r") as f:
                                        uevent = f.read()
                                        if "mali" in uevent.lower():
                                            return "ARM Mali GPU"
                                except Exception:
                                    pass
                except Exception:
                    pass
            return "ARM Integrated Graphics"
    except Exception:
        pass
    
    return "unknown-gpu"


def get_cpu_temperature() -> Optional[float]:
    """
    Get CPU temperature in Celsius.
    Uses platform-specific methods with fallbacks.
    """
    system = platform.system()
    
    # Linux - use psutil sensors
    if system == "Linux" and PSUTIL_AVAILABLE:
        try:
            temps = psutil.sensors_temperatures()
            # Try common CPU temperature sensor names
            for sensor_name in ['coretemp', 'cpu_thermal', 'k10temp', 'zenpower']:
                if sensor_name in temps:
                    sensors = temps[sensor_name]
                    if sensors:
                        # Return the first available temperature
                        return round(sensors[0].current, 1)
        except Exception:
            pass
    
    # macOS - try system_profiler and powermetrics
    elif system == "Darwin":
        try:
            # Try powermetrics for CPU temperature (requires sudo)
            result = subprocess.check_output(
                ["powermetrics", "--samplers", "smc", "-n", "1", "-i", "1000"], 
                text=True, 
                stderr=subprocess.DEVNULL
            )
            for line in result.split('\n'):
                if 'CPU die temperature' in line:
                    # Extract temperature value
                    temp_match = line.split(':')[-1].strip().replace('C', '')
                    return round(float(temp_match), 1)
        except Exception:
            pass
        
        # Fallback: try system_profiler (less reliable)
        try:
            result = subprocess.check_output(
                ["system_profiler", "SPHardwareDataType", "-json"], 
                text=True
            )
            data = json.loads(result)
            # This is a fallback - system_profiler doesn't always have temp data
            # but we can try to extract any thermal info if available
        except Exception:
            pass
    
    # Windows - use WMI
    elif system == "Windows" and WMI_AVAILABLE:
        try:
            w = wmi.WMI(namespace="root\\wmi")
            temperature_info = w.MSAcpi_ThermalZoneTemperature()[0]
            # Convert from tenths of Kelvin to Celsius
            temp_celsius = (temperature_info.CurrentTemperature / 10.0) - 273.15
            return round(temp_celsius, 1)
        except Exception:
            pass
    
    # Generic fallback using psutil if available
    if PSUTIL_AVAILABLE:
        try:
            temps = psutil.sensors_temperatures()
            # Look for any temperature sensor
            for sensor_name, sensors in temps.items():
                if sensors and 'cpu' in sensor_name.lower():
                    return round(sensors[0].current, 1)
        except Exception:
            pass
    
    return None


def get_gpu_temperature() -> Optional[float]:
    """
    Get GPU temperature in Celsius.
    Supports NVIDIA, AMD, and integrated graphics with fallbacks.
    """
    system = platform.system()
    
    # Try NVIDIA GPUs first (works on all platforms)
    if PYNVML_AVAILABLE:
        try:
            pynvml.nvmlInit()
            device_count = pynvml.nvmlDeviceGetCount()
            if device_count > 0:
                handle = pynvml.nvmlDeviceGetHandleByIndex(0)
                temp = pynvml.nvmlDeviceGetTemperature(handle, pynvml.NVML_TEMPERATURE_GPU)
                pynvml.nvmlShutdown()
                return round(float(temp), 1)
        except Exception:
            pass
    
    # Try nvidia-smi command (works on Linux and Windows)
    try:
        result = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=temperature.gpu", "--format=csv,noheader,nounits"], 
            text=True, 
            stderr=subprocess.DEVNULL
        )
        if result.strip():
            return round(float(result.strip()), 1)
    except Exception:
        pass
    
    # Linux - try various GPU temperature sources
    if system == "Linux":
        # Try AMD GPU temperature via sysfs
        try:
            for card in os.listdir("/sys/class/drm"):
                if card.startswith("card"):
                    temp_file = f"/sys/class/drm/{card}/device/hwmon/hwmon*/temp1_input"
                    import glob
                    temp_files = glob.glob(temp_file)
                    if temp_files:
                        with open(temp_files[0], 'r') as f:
                            temp_millicelsius = int(f.read().strip())
                            return round(temp_millicelsius / 1000.0, 1)
        except Exception:
            pass
        
        # Try Intel GPU temperature
        try:
            for card in os.listdir("/sys/class/drm"):
                if card.startswith("card"):
                    temp_file = f"/sys/class/drm/{card}/device/hwmon/hwmon*/temp1_input"
                    import glob
                    temp_files = glob.glob(temp_file)
                    if temp_files:
                        with open(temp_files[0], 'r') as f:
                            temp_millicelsius = int(f.read().strip())
                            return round(temp_millicelsius / 1000.0, 1)
        except Exception:
            pass
    
    # macOS - try system_profiler for GPU temperature
    elif system == "Darwin":
        try:
            result = subprocess.check_output(
                ["system_profiler", "SPDisplaysDataType", "-json"], 
                text=True
            )
            data = json.loads(result)
            displays = data.get("SPDisplaysDataType", [])
            for display in displays:
                # Look for temperature info in display data
                if "temperature" in str(display).lower():
                    # This is a fallback - actual temperature extraction would need
                    # more specific parsing based on the actual data structure
                    pass
        except Exception:
            pass
    
    # Windows - try WMI for GPU temperature
    elif system == "Windows" and WMI_AVAILABLE:
        try:
            w = wmi.WMI(namespace="root\\wmi")
            # Try to get GPU temperature from WMI
            # This is a fallback method and may not work on all systems
            pass
        except Exception:
            pass
    
    return None


def get_hardware_summary() -> str:
    """
    Get a brief hardware summary for debugging purposes.
    """
    try:
        cpu = get_cpu_name()
        gpu = get_gpu_name()
        cpu_temp = get_cpu_temperature()
        gpu_temp = get_gpu_temperature()
        
        summary = f"CPU: {cpu}"
        if cpu_temp is not None:
            summary += f" ({cpu_temp}°C)"
        
        summary += f", GPU: {gpu}"
        if gpu_temp is not None:
            summary += f" ({gpu_temp}°C)"
        
        return summary
    except Exception:
        return "Hardware detection failed"

def build_payload(render_progress: Optional[Dict] = None, status: str = "idling") -> Dict[str, any]:
    payload = {
        "hostname": get_hostname(),
        "os": get_os_string(),
        "cpu": get_cpu_name(),
        "gpu": get_gpu_name(),
        "timestamp": iso_timestamp(),
        "sentry_secret": SENTRY_CONFIG["SENTRY_SECRET"],
        "status": status,
    }
    
    # Add CPU temperature if available
    cpu_temp = get_cpu_temperature()
    if cpu_temp is not None:
        payload["cpu_temperature"] = f"{cpu_temp}°C"
    
    # Add GPU temperature if available
    gpu_temp = get_gpu_temperature()
    if gpu_temp is not None:
        payload["gpu_temperature"] = f"{gpu_temp}°C"
    
    # Add render progress information if available
    if render_progress:
        payload["render_progress"] = render_progress
    
    return payload


# ────────────────────────────────────────────────────────────
# 2.  Transport ─ HTTP POST to Bun server
# ────────────────────────────────────────────────────────────
SERVER_HOST = SENTRY_CONFIG["SERVER_HOST"]
SERVER_PORT = int(SENTRY_CONFIG["SERVER_PORT"])
SERVER_PATH = "/submit"  # agreed endpoint
HEADERS = {"Content-Type": "application/json"}

def post_payload(payload: Dict[str, str]) -> tuple[str, str]:
    """
    Post payload to server and return status information.
    Returns (status_message, timestamp) tuple.
    """
    body = json.dumps(payload)
    conn = http_client.HTTPConnection(SERVER_HOST, SERVER_PORT, timeout=10)
    try:
        conn.request("POST", SERVER_PATH, body=body, headers=HEADERS)
        response = conn.getresponse()
        status = f"{response.status} {response.reason}"
        conn.close()
        return status, payload['timestamp']
    except Exception as exc:
        return f"✗ POST failed: {exc}", payload['timestamp']


# ────────────────────────────────────────────────────────────
# 3.  Main loop with dynamic render monitoring
# ────────────────────────────────────────────────────────────
POST_INTERVAL = 30  # Maximum seconds between posts
CHECK_INTERVAL = 2  # Seconds between directory checks

def monitor_render_directory(render_dir: str, start_frame: int, end_frame: int):
    """
    Monitor render directory for new files and post updates dynamically.
    Posts immediately when new frames are detected, or at least every 30 seconds.
    """
    hardware_summary = get_hardware_summary()
    last_status = None
    last_timestamp = None
    last_post_time = 0
    last_frame_count = 0
    
    # Initial display
    render_progress = get_render_progress(render_dir, start_frame, end_frame)
    initial_status = determine_node_status(render_progress, 0, time.time(), 0)
    clear_and_redraw_status(SERVER_HOST, SERVER_PORT, hardware_summary, last_status, last_timestamp, 
                           render_progress, render_dir, start_frame, end_frame, initial_status)
    
    print("🎬 Starting render monitoring...")
    
    while True:
        try:
            current_time = time.time()
            current_progress = get_render_progress(render_dir, start_frame, end_frame)
            current_frame_count = current_progress['rendered_frames']
            
            # Determine current node status
            node_status = determine_node_status(current_progress, last_frame_count, current_time, last_post_time)
            
            # Check if new frames have been added or if it's time for a regular update
            new_frames_detected = current_frame_count > last_frame_count
            time_for_regular_update = (current_time - last_post_time) >= POST_INTERVAL
            
            if new_frames_detected or time_for_regular_update:
                # Build and send payload with current status
                data = build_payload(current_progress, node_status)
                last_status, last_timestamp = post_payload(data)
                last_post_time = current_time
                last_frame_count = current_frame_count
                
                # Update display
                clear_and_redraw_status(SERVER_HOST, SERVER_PORT, hardware_summary, last_status, last_timestamp,
                                       current_progress, render_dir, start_frame, end_frame, node_status)
                
                # Show what triggered the update
                if new_frames_detected:
                    print(f"🆕 New frame detected! Frame count: {last_frame_count}")
                elif time_for_regular_update:
                    print("⏰ Regular status update (30s interval)")
            
            # Check if render is complete
            if current_progress['progress_percentage'] >= 100.0:
                print("🎉 Render complete! All frames have been rendered.")
                # Send final update with idling status
                final_status = "idling"
                data = build_payload(current_progress, final_status)
                last_status, last_timestamp = post_payload(data)
                clear_and_redraw_status(SERVER_HOST, SERVER_PORT, hardware_summary, last_status, last_timestamp,
                                       current_progress, render_dir, start_frame, end_frame, final_status)
                print("✅ Final status sent to server. Monitoring will continue...")
            
            time.sleep(CHECK_INTERVAL)
            
        except KeyboardInterrupt:
            print("\n\n👋 Mata Sentry render monitor stopped.")
            break
        except Exception as e:
            print(f"\n❌ Error in monitoring loop: {e}")
            print("🔄 Continuing monitoring...")
            time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    # Get user input for render monitoring
    render_dir, start_frame, end_frame = get_user_input()
    
    # Start monitoring
    monitor_render_directory(render_dir, start_frame, end_frame)

