#!/bin/bash
# One-click install and launch (Mac/Linux)

cd "$(dirname "$0")"

echo "Checking Python..."
if command -v python3 &>/dev/null; then
    PY=python3
elif command -v python &>/dev/null; then
    PY=python
else
    echo "ERROR: Python not found. Please install Python 3.10+"
    echo "Mac: brew install python@3.12"
    exit 1
fi

VER=$($PY -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo "Python version: $VER"

# Check version >= 3.10
MAJOR=$($PY -c "import sys; print(sys.version_info.major)")
MINOR=$($PY -c "import sys; print(sys.version_info.minor)")
if [ "$MAJOR" -lt 3 ] || ([ "$MAJOR" -eq 3 ] && [ "$MINOR" -lt 10 ]); then
    echo "ERROR: Python 3.10+ required, current: $VER"
    echo "Mac: brew install python@3.12"
    exit 1
fi

echo "Installing dependencies..."
$PY -m pip install -r requirements.txt --quiet --disable-pip-version-check

echo "Starting..."
$PY gui.py
