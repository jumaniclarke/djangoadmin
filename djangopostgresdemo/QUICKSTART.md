# Quick Start Guide: Cross-Platform Deployment

## TL;DR - Get Running in 2 Minutes

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Start services (choose one method)

# Option A: Python Service Manager (Recommended - works on Windows/Mac/Linux)
python run_services.py start

# Option B: Supervisor (Linux/macOS only)
chmod +x deploy.sh
./deploy.sh $(pwd)  # Choose option 1 when prompted


# 3. Open Web UI
# Visit: http://localhost:5555 (Celery Flower - task monitoring)
```

---

## Platform-Specific Instructions

### Windows

```powershell
# PowerShell
cd C:\path\to\djangopostgresdemo
pip install -r requirements.txt
python run_services.py start

# View logs
Get-Content logs\listener.log -Wait
```

### macOS

```bash
cd /path/to/djangopostgresdemo
pip install -r requirements.txt
python run_services.py start

# View logs
tail -f logs/listener.log
```

### Linux

```bash
cd /path/to/djangopostgresdemo
pip install -r requirements.txt

# Option 1: Python Service Manager (Recommended)
python run_services.py start

# Option 2: Supervisor (requires sudo for production setup)
./deploy.sh $(pwd)
# Choose: 1 (Supervisor)
```

---

## Monitoring

### Check Service Status

```bash
python run_services.py status
```

### View Logs

```bash
# Real-time (all platforms)
tail -f logs/listener.log       # Listener logs
tail -f logs/celery_worker1.log # Worker logs

# Or use Flower Web UI
# http://localhost:5555
```

### Stop Services

```bash
python run_services.py stop
```

---

## What Gets Started?

1. **Django Listener** - Watches PostgreSQL for new submissions
2. **Celery Worker 1 & 2** - Process marking tasks in parallel
3. **Celery Beat** - Scheduler for periodic health checks
4. **Celery Flower** - Web dashboard at `http://localhost:5555`

---

## Troubleshooting

**Services won't start?**
```bash
# Make sure Redis and PostgreSQL are running
redis-cli ping          # Should output: PONG
psql -U numeracy -d mam107h -c "SELECT 1;"  # Should output: 1
```

**Port 5555 already in use?**
```bash
# Stop the old instance
python run_services.py stop

# Or kill the process manually
# Windows: taskkill /PID <pid> /F
# Linux/Mac: kill -9 <pid>
```

**See detailed logs:**
```bash
cat logs/listener.log
cat logs/celery_beat.log
cat logs/celery_flower.log
```

---

## For Full Documentation

See [DEPLOYMENT.md](DEPLOYMENT.md) for complete setup instructions and production recommendations.
