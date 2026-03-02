# Cross-Platform Deployment Guide (Option 1: Supervisor)

This guide covers deploying the Django + Celery system on **Windows**, **Linux**, and **macOS**.

## Quick Start

### For Linux/macOS with Supervisor

```bash
# Install supervisor
pip install supervisor

# Make deploy script executable
chmod +x deploy.sh

# Run deployment (will prompt for method choice)
./deploy.sh /path/to/djangopostgresdemo

# When prompted, choose: 1 (Supervisor)
```

### For All Platforms (Python Service Manager - Recommended)

```bash
# From Django project root directory
cd /path/to/djangopostgresdemo

# Start all services
python run_services.py start

# In another terminal, check status
python run_services.py status

# Stop services
python run_services.py stop
```

### For Windows (PowerShell)

```powershell
# Navigate to Django project
cd C:\path\to\djangopostgresdemo

# Start services
python run_services.py start

# Check status (in another PowerShell window)
python run_services.py status

# Stop services
python run_services.py stop
```

---

## Detailed Setup Instructions

### Prerequisites (All Platforms)

```bash
# Ensure you're in the Django project directory
cd /path/to/djangopostgresdemo

# Activate virtual environment
# Linux/macOS:
source venv/bin/activate

# Windows (PowerShell):
.\venv\Scripts\Activate.ps1

# Windows (Command Prompt):
venv\Scripts\activate.bat

# Install required packages (if not already done)
pip install celery redis psutil supervisor
```

---

## Method 1: Python Service Manager (Cross-Platform)

**Best for:** All platforms (Windows, Linux, macOS)  
**Requires:** Python (built-in), psutil

### Start Services

```bash
cd /path/to/djangopostgresdemo
python run_services.py start
```

**Output:**
```
2026-02-14 10:30:45,123 - INFO - Django project: /home/user/djangopostgresdemo
2026-02-14 10:30:45,125 - INFO - Virtual env: /home/user/djangopostgresdemo/venv/bin/python
2026-02-14 10:30:45,130 - INFO - Starting Django Listener...
2026-02-14 10:30:45,140 - INFO - ✓ Django Listener started (PID: 12345)
...
2026-02-14 10:30:50,250 - INFO - All services started successfully!
2026-02-14 10:30:50,251 - INFO - 
2026-02-14 10:30:50,251 - INFO - Web UI: http://localhost:5555 (Celery Flower)
```

### Monitor Services

```bash
python run_services.py status
```

**Output:**
```
============================================================
Service Status
============================================================

Django Listener
  PID: 12345
  Status: ✓ RUNNING
  Uptime: 0h 2m
  Log: /path/to/djangopostgresdemo/logs/listener.log

Celery Worker 1
  PID: 12346
  Status: ✓ RUNNING
  Uptime: 0h 1m
  Log: /path/to/djangopostgresdemo/logs/celery_worker1.log

...
```

### View Logs

```bash
# Linux/macOS
tail -f logs/listener.log
tail -f logs/celery_worker1.log

# Windows PowerShell
Get-Content logs/listener.log -Wait
Get-Content logs/celery_worker1.log -Wait
```

### Stop Services

```bash
python run_services.py stop
```

**Features:**
- ✅ Auto-restart failed services
- ✅ Graceful shutdown on Ctrl+C
- ✅ Cross-platform (Windows, Linux, macOS)
- ✅ Persistent PID tracking
- ✅ Real-time uptime monitoring

---

## Method 2: Supervisor (Linux/macOS Only)

**Best for:** Production Linux servers  
**Requires:** `supervisor` package

### Setup

```bash
# Install supervisor
pip install supervisor

# Make deploy script executable
chmod +x deploy.sh

# Run deployment
./deploy.sh /path/to/djangopostgresdemo

# When prompted, choose: 1 (Supervisor)
```

### Manual Setup (If deploy.sh doesn't work)

```bash
# Set environment variables
export DJANGO_PROJECT="/path/to/djangopostgresdemo"
export VENV="/path/to/djangopostgresdemo/venv"
export HOME="/home/username"

# Create supervisor directories
mkdir -p ~/supervisor
chmod 755 ~/supervisor

# Start supervisord
supervisord -c $DJANGO_PROJECT/supervisor.conf
```

### Monitor Services

```bash
# View all services
supervisorctl -c /path/to/supervisor.conf status

# Restart a specific service
supervisorctl -c /path/to/supervisor.conf restart django-listener

# Stop all services
supervisorctl -c /path/to/supervisor.conf stop all

# Start all services
supervisorctl -c /path/to/supervisor.conf start all
```

**supervisor.conf Configuration:**
- Uses environment variables: `%(ENV_DJANGO_PROJECT)s`, `%(ENV_VENV)s`, `%(ENV_HOME)s`
- Auto-restarts failed services
- Logs to `~/supervisor/*.log`
- Groups celery services for easy management

---

## Accessing the Web UI

### Celery Flower (Task Monitoring Dashboard)

Open your browser:
```
http://localhost:5555
```

**Features:**
- View running tasks
- Monitor worker status
- View task history
- See real-time task statistics

---

## Troubleshooting

### Issue: Services won't start

```bash
# Check if Redis is running
redis-cli ping
# Output: PONG

# Check if PostgreSQL is running
psql -U numeracy -d mam107h -c "SELECT 1;"
```

### Issue: "python: command not found"

```bash
# Activate virtual environment
source venv/bin/activate  # Linux/macOS
# OR
.\venv\Scripts\activate.ps1  # Windows PowerShell
```

### Issue: "Address already in use" (port 5555)

```bash
# Flower is already running on another instance
# Stop the old instance first
python run_services.py stop

# Or use a different port (edit run_services.py or use supervisor)
```

### Issue: Services crash immediately

```bash
# Check logs
tail -f logs/listener.log
tail -f logs/celery_worker1.log

# Common issues:
# - Redis not running: start Redis
# - PostgreSQL not running: start PostgreSQL
# - DJANGO_SETTINGS_MODULE not set: it's auto-set by scripts
```

### View Detailed Logs

```bash
# Python service manager
cat logs/listener.log
cat logs/celery_worker1.log
cat logs/celery_beat.log

# Supervisor
cat ~/supervisor/listener.log
cat ~/supervisor/celery_worker1.log
```

---

## Scaling Workers

### Using Python Service Manager

Edit `run_services.py` and modify the `get_services()` method to add more workers:

```python
'celery-worker-3': {
    'name': 'Celery Worker 3',
    'command': [...],
    ...
}
```

### Using Supervisor

Add more `[program:celery-worker-N]` sections to `supervisor.conf`:

```ini
[program:celery-worker-3]
command=%(ENV_VENV)s/bin/celery -A dbapp worker --loglevel=info --hostname=worker3@%%h
...
```

Then reload supervisor:
```bash
supervisorctl -c /path/to/supervisor.conf reread
supervisorctl -c /path/to/supervisor.conf update
```

---

## Production Recommendations

1. **Use Python Service Manager** for cross-platform simplicity
2. **Or use Supervisor** on Linux for proven stability
3. **Monitor with Flower** at `localhost:5555`
4. **Set up log rotation** (optional but recommended):
   ```bash
   # Linux: Use logrotate
   # Edit /etc/logrotate.d/django-services
   /path/to/djangopostgresdemo/logs/*.log {
       daily
       rotate 7
       compress
       delaycompress
   }
   ```

5. **Enable dead-letter detection** (auto-retries lost submissions every 5 minutes)

---

## Next Steps

- Set up database backups
- Configure email for error notifications
- Set up monitoring/alerting
- Configure firewall to allow only `localhost:5555` or restrict to VPN
