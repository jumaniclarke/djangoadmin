#!/bin/bash
# Cross-platform deployment script
# Works on Linux, macOS, and WSL2 (Windows Subsystem for Linux)
# Usage: ./deploy.sh /path/to/django/project

set -e  # Exit on error

# Detect OS
OS_TYPE=$(uname -s)
echo "Detected OS: $OS_TYPE"

# Check argument
if [ -z "$1" ]; then
    echo "Usage: $0 /path/to/django/project"
    echo "Example: $0 /home/ubuntu/djangopostgresdemo"
    exit 1
fi

DJANGO_PROJECT="$1"
VENV="${2:-.venv}"
HOME_DIR="${HOME}"

# Validate Django project exists
if [ ! -f "$DJANGO_PROJECT/manage.py" ]; then
    echo "Error: manage.py not found in $DJANGO_PROJECT"
    exit 1
fi

# Resolve to absolute paths
DJANGO_PROJECT="$(cd "$DJANGO_PROJECT" && pwd)"
if [ -d "$DJANGO_PROJECT/$VENV" ]; then
    VENV="$(cd "$DJANGO_PROJECT/$VENV" && pwd)"
else
    VENV="$VENV"  # Use as-is if not found (might be system Python)
fi

echo "=========================================="
echo "Deploying Django app (Cross-Platform)"
echo "=========================================="
echo "Django project: $DJANGO_PROJECT"
echo "Virtual env: $VENV"
echo "Home directory: $HOME_DIR"
echo ""

# Create supervisor directories
mkdir -p "$HOME_DIR/supervisor"
chmod 755 "$HOME_DIR/supervisor"

# Option 1: Use Supervisor (Linux/macOS)
# Option 2: Use Python service manager (all platforms)

echo "Choose deployment method:"
echo "1) Supervisor (Linux/macOS only, requires 'pip install supervisor')"
echo "2) Python service manager (all platforms, no extra dependencies)"
read -p "Enter choice (1 or 2): " choice

if [ "$choice" = "1" ]; then
    # Check if supervisor is installed
    if ! command -v supervisord &> /dev/null; then
        echo "Supervisor not found. Install with: pip install supervisor"
        exit 1
    fi
    
    SUPERVISOR_CONFIG="$DJANGO_PROJECT/supervisor.conf"
    
    # Export environment variables for supervisor config
    export DJANGO_PROJECT="$DJANGO_PROJECT"
    export VENV="$VENV"
    export HOME="$HOME_DIR"
    
    echo ""
    echo "Starting supervisord with config: $SUPERVISOR_CONFIG"
    supervisord -c "$SUPERVISOR_CONFIG"
    
    echo "✓ Supervisord started successfully"
    echo ""
    echo "Monitor with: supervisorctl -c $SUPERVISOR_CONFIG status"
    echo "Web UI: http://localhost:5555 (Celery Flower)"
    
elif [ "$choice" = "2" ]; then
    # Use Python service manager (works on all platforms)
    cd "$DJANGO_PROJECT"
    
    echo ""
    echo "Starting services with Python manager..."
    echo "This will run: python run_services.py start"
    echo ""
    
    # Activate venv if it exists
    if [ -f "$VENV/bin/activate" ]; then
        source "$VENV/bin/activate"
    fi
    
    python run_services.py start
    
else
    echo "Invalid choice. Exiting."
    exit 1
fi

