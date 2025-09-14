#!/bin/bash
# Enhanced hardware detection and temperature monitoring dependencies installer
# Run this script to install optional dependencies for better hardware detection and temperature monitoring

echo "Installing enhanced hardware detection and temperature monitoring dependencies..."

# Install psutil for cross-platform system information
echo "Installing psutil..."
pip install psutil

# Install GPUtil for GPU detection (primarily NVIDIA)
echo "Installing GPUtil..."
pip install GPUtil

# Install nvidia-ml-py3 for NVIDIA GPU temperature monitoring
echo "Installing nvidia-ml-py3 for GPU temperature monitoring..."
pip install nvidia-ml-py3

# Install WMI for Windows temperature monitoring (Windows only)
if [[ "$OSTYPE" == "msys" || "$OSTYPE" == "win32" ]]; then
    echo "Installing WMI for Windows temperature monitoring..."
    pip install WMI
else
    echo "Skipping WMI installation (not on Windows)"
fi

echo "✅ Enhanced dependencies installed successfully!"
echo ""
echo "The sentry client will now have improved hardware detection and temperature monitoring for:"
echo "  - CPU information across all platforms"
echo "  - GPU detection (NVIDIA, AMD, Intel, ARM)"
echo "  - CPU temperature monitoring (Linux, macOS, Windows)"
echo "  - GPU temperature monitoring (NVIDIA, AMD, Intel)"
echo "  - Raspberry Pi specific hardware"
echo "  - Better fallback mechanisms"
echo ""
echo "You can now run the sentry client with enhanced hardware detection and temperature monitoring."
