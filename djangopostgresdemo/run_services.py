"""
Cross-platform service manager for Django + Celery
Works on Windows, Linux, and macOS without supervisor.

Usage:
    python run_services.py start      # Start all services
    python run_services.py stop       # Stop all services
    python run_services.py status     # Show service status
"""

import os
import sys
import subprocess
import time
import signal
import psutil
from pathlib import Path
from typing import Dict, List
import json
import logging

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class ServiceManager:
    """Manage Django listener and Celery workers cross-platform"""
    
    def __init__(self, django_project: Path):
        self.django_project = Path(django_project).resolve()
        self.state_file = self.django_project / '.services.json'
        self.log_dir = self.django_project / 'logs'
        self.log_dir.mkdir(exist_ok=True)
        
        # Detect virtual environment
        self.venv = self._find_venv()
        if not self.venv:
            raise RuntimeError("Virtual environment not found. Activate it or set VIRTUAL_ENV")
        
        logger.info(f"Django project: {self.django_project}")
        logger.info(f"Virtual env: {self.venv}")
        
    def _find_venv(self) -> Path:
        """Locate Python executable in virtual environment"""
        # Try VIRTUAL_ENV env var first
        if os.getenv('VIRTUAL_ENV'):
            venv_path = Path(os.getenv('VIRTUAL_ENV'))
        else:
            # Look for common venv locations
            for candidate in ['venv', '.venv', 'env']:
                candidate_path = self.django_project / candidate
                if candidate_path.exists():
                    venv_path = candidate_path
                    break
            else:
                return None
        
        # Get python executable path
        if sys.platform == 'win32':
            python_exe = venv_path / 'Scripts' / 'python.exe'
        else:
            python_exe = venv_path / 'bin' / 'python'
        
        return python_exe if python_exe.exists() else None
    
    def get_services(self) -> Dict[str, dict]:
        """Define services to manage"""
        return {
            'listener': {
                'name': 'Django Listener',
                'command': [str(self.venv), 'manage.py', 'listen_submissions'],
                'log': self.log_dir / 'listener.log',
                'critical': True,
            },
            'celery-worker-1': {
                'name': 'Celery Worker 1',
                'command': [
                    str(self.venv.parent.parent / ('Scripts' if sys.platform == 'win32' else 'bin') / 
                        ('celery.exe' if sys.platform == 'win32' else 'celery')),
                    '-A', 'dbapp', 'worker',
                    '--loglevel=info', '--hostname=worker1@%h', '--concurrency=2'
                ],
                'log': self.log_dir / 'celery_worker1.log',
                'critical': False,
            },
            'celery-worker-2': {
                'name': 'Celery Worker 2',
                'command': [
                    str(self.venv.parent.parent / ('Scripts' if sys.platform == 'win32' else 'bin') / 
                        ('celery.exe' if sys.platform == 'win32' else 'celery')),
                    '-A', 'dbapp', 'worker',
                    '--loglevel=info', '--hostname=worker2@%h', '--concurrency=2'
                ],
                'log': self.log_dir / 'celery_worker2.log',
                'critical': False,
            },
            'celery-beat': {
                'name': 'Celery Beat',
                'command': [
                    str(self.venv.parent.parent / ('Scripts' if sys.platform == 'win32' else 'bin') / 
                        ('celery.exe' if sys.platform == 'win32' else 'celery')),
                    '-A', 'dbapp', 'beat',
                    '--loglevel=info'
                ],
                'log': self.log_dir / 'celery_beat.log',
                'critical': True,
            },
            'celery-flower': {
                'name': 'Celery Flower (Web UI)',
                'command': [
                    str(self.venv.parent.parent / ('Scripts' if sys.platform == 'win32' else 'bin') / 
                        ('celery.exe' if sys.platform == 'win32' else 'celery')),
                    '-A', 'dbapp', 'flower',
                    '--port=5555', '--loglevel=info'
                ],
                'log': self.log_dir / 'celery_flower.log',
                'critical': False,
            },
        }
    
    def _get_state(self) -> Dict:
        """Load service state from file"""
        if self.state_file.exists():
            with open(self.state_file, 'r') as f:
                return json.load(f)
        return {}
    
    def _save_state(self, state: Dict):
        """Save service state to file"""
        with open(self.state_file, 'w') as f:
            json.dump(state, f, indent=2)
    
    def start(self):
        """Start all services"""
        logger.info("=" * 60)
        logger.info("Starting all services...")
        logger.info("=" * 60)
        
        os.chdir(self.django_project)
        services = self.get_services()
        state = {}
        
        for service_id, config in services.items():
            logger.info(f"\nStarting {config['name']}...")
            
            try:
                # Open log file
                log_file = open(config['log'], 'a')
                
                # Start process
                process = subprocess.Popen(
                    config['command'],
                    cwd=str(self.django_project),
                    stdout=log_file,
                    stderr=subprocess.STDOUT,
                    env={**os.environ, 'DJANGO_SETTINGS_MODULE': 'dbapp.settings'}
                )
                
                state[service_id] = {
                    'pid': process.pid,
                    'name': config['name'],
                    'started_at': time.time(),
                    'critical': config['critical'],
                    'log': str(config['log'])
                }
                
                logger.info(f"✓ {config['name']} started (PID: {process.pid})")
                logger.info(f"  Log: {config['log']}")
                
            except Exception as e:
                logger.error(f"✗ Failed to start {config['name']}: {e}")
                if config['critical']:
                    logger.error("Critical service failed. Stopping...")
                    self.stop()
                    sys.exit(1)
        
        self._save_state(state)
        logger.info("\n" + "=" * 60)
        logger.info("All services started successfully!")
        logger.info("=" * 60)
        logger.info("\nWeb UI: http://localhost:5555 (Celery Flower)")
        logger.info("\nPress Ctrl+C to stop services\n")
        
        # Keep running
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("\nShutdown signal received...")
            self.stop()
    
    def stop(self):
        """Stop all services gracefully"""
        logger.info("\n" + "=" * 60)
        logger.info("Stopping all services...")
        logger.info("=" * 60)
        
        state = self._get_state()
        
        for service_id, info in state.items():
            logger.info(f"\nStopping {info['name']} (PID: {info['pid']})...")
            
            try:
                process = psutil.Process(info['pid'])
                
                # Try graceful termination first
                process.terminate()
                
                try:
                    process.wait(timeout=5)
                    logger.info(f"✓ {info['name']} stopped")
                except psutil.TimeoutExpired:
                    # Force kill if not stopped
                    logger.warning(f"  Force killing {info['name']}...")
                    process.kill()
                    process.wait()
                    logger.info(f"✓ {info['name']} force-killed")
                    
            except (psutil.NoSuchProcess, ProcessLookupError):
                logger.warning(f"  {info['name']} already stopped")
            except Exception as e:
                logger.error(f"✗ Error stopping {info['name']}: {e}")
        
        # Clear state
        self._save_state({})
        
        logger.info("\n" + "=" * 60)
        logger.info("All services stopped")
        logger.info("=" * 60 + "\n")
    
    def status(self):
        """Show service status"""
        state = self._get_state()
        
        if not state:
            logger.info("No services running")
            return
        
        logger.info("\n" + "=" * 60)
        logger.info("Service Status")
        logger.info("=" * 60)
        
        for service_id, info in state.items():
            try:
                process = psutil.Process(info['pid'])
                status = "✓ RUNNING"
                uptime = time.time() - info['started_at']
                uptime_str = f"{int(uptime // 3600)}h {int((uptime % 3600) // 60)}m"
                
                logger.info(f"\n{info['name']}")
                logger.info(f"  PID: {info['pid']}")
                logger.info(f"  Status: {status}")
                logger.info(f"  Uptime: {uptime_str}")
                logger.info(f"  Log: {info['log']}")
                
            except psutil.NoSuchProcess:
                logger.info(f"\n{info['name']}")
                logger.info(f"  Status: ✗ STOPPED (PID {info['pid']} not found)")
                logger.info(f"  Log: {info['log']}")
        
        logger.info("\n" + "=" * 60 + "\n")


def main():
    if len(sys.argv) < 2:
        print("Usage: python run_services.py <command>")
        print("\nCommands:")
        print("  start    - Start all services")
        print("  stop     - Stop all services")
        print("  status   - Show service status")
        sys.exit(1)
    
    # Detect Django project directory
    django_project = Path.cwd()
    if not (django_project / 'manage.py').exists():
        print("Error: manage.py not found. Run from Django project root directory.")
        sys.exit(1)
    
    try:
        manager = ServiceManager(django_project)
        command = sys.argv[1].lower()
        
        if command == 'start':
            manager.start()
        elif command == 'stop':
            manager.stop()
        elif command == 'status':
            manager.status()
        else:
            print(f"Unknown command: {command}")
            sys.exit(1)
            
    except Exception as e:
        logger.error(f"Error: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
