#!/bin/bash
# OpenHands Integration Setup Script

set -e

echo "=== OpenHands Integration Setup ==="

# Check prerequisites
echo "Checking prerequisites..."

# Python
python3 --version || { echo "Python3 required"; exit 1; }

# Docker
docker --version || { echo "Docker required"; exit 1; }

# OpenHands CLI
openhands --version || { echo "OpenHands CLI required. Run: pip install openhands"; exit 1; }

# Create directories
echo "Creating directories..."
mkdir -p openhands_workspace
mkdir -p logging_traces
mkdir -p logs

# Install Python dependencies
echo "Installing Python dependencies..."
pip3 install pyyaml -q

# Verify environment
echo "Verifying environment..."
python3 -c "from openhands_integration.src import OpenHandsAgent; print('✓ Integration module loads correctly')"

echo ""
echo "=== Setup Complete ==="
echo ""
echo "To start using OpenHands integration:"
echo ""
echo "1. Set LLM credentials:"
echo "   export LLM_API_KEY='your-key'"
echo "   export LLM_MODEL='anthropic/claude-sonnet-4-20250514'"
echo ""
echo "2. Test a generation:"
echo "   python3 -c \\"
echo "     'from openhands_integration.src import FullstackOpenHandsGenerator;"
echo "      g = FullstackOpenHandsGenerator();"
echo "      r = g.generate_project(\"test\", \"Create a hello world app\", inject_logging=True);"
echo "      print(r)'"
echo ""
echo "3. For Docker-based sandbox (recommended):"
echo "   openhands serve"
