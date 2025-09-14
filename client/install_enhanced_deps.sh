#!/bin/bash
# Enhanced hardware detection dependencies installer
# Run this script to install optional dependencies for better hardware detection

echo "Installing enhanced hardware detection dependencies..."

# Install psutil for cross-platform system information
echo "Installing psutil..."
pip install psutil

# Install GPUtil for GPU detection (primarily NVIDIA)
echo "Installing GPUtil..."
pip install GPUtil

echo "✅ Enhanced dependencies installed successfully!"
echo ""
echo "The sentry client will now have improved hardware detection for:"
echo "  - CPU information across all platforms"
echo "  - GPU detection (NVIDIA, AMD, Intel, ARM)"
echo "  - Raspberry Pi specific hardware"
echo "  - Better fallback mechanisms"
echo ""
echo "You can now run the sentry client with enhanced hardware detection."
