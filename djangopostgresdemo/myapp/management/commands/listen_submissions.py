
from django.core.management.base import BaseCommand
from django.conf import settings
import json
import select
import time
import psycopg2
import psycopg2.extensions
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from myapp.tasks import mark_submission_async  # Import Celery task
import logging

logger = logging.getLogger(__name__)
channel_layer = get_channel_layer()

class Command(BaseCommand):
    help = "Listen for new submissions via PostgreSQL LISTEN/NOTIFY"

    def handle(self, *args, **options):
        # Use a dedicated connection (LISTEN must be on a persistent session)
        while True:
            try:
                conn = psycopg2.connect(
                    dsn=settings.DATABASES['default']['OPTIONS'].get('dsn')
                    if 'OPTIONS' in settings.DATABASES['default'] and 'dsn' in settings.DATABASES['default']['OPTIONS']
                    else None,
                    dbname=settings.DATABASES['default']['NAME'],
                    user=settings.DATABASES['default']['USER'],
                    password=settings.DATABASES['default']['PASSWORD'],
                    host=settings.DATABASES['default']['HOST'],
                    port=settings.DATABASES['default']['PORT'],
                )
                conn.set_isolation_level(psycopg2.extensions.ISOLATION_LEVEL_AUTOCOMMIT)
                cur = conn.cursor()
                cur.execute("LISTEN submission_new;")
                self.stdout.write(self.style.SUCCESS("Listening on channel 'submission_new'..."))

                while True:
                    # Wait until the connection has notifications
                    
                    if select.select([conn], [], [], 30) == ([], [], []):
                        # heartbeat or metrics; keep the loop alive
                        continue

                    conn.poll()
                    while conn.notifies:
                        notify = conn.notifies.pop(0)
                        # payload is a JSON string like {"id": 123}
                        
                        try:
                            data = json.loads(notify.payload)
                            submission_id = data.get("sessionid")
                        except json.JSONDecodeError:
                            submission_id = None

                        if submission_id is None:
                            self.stderr.write("Received malformed payload; skipping")
                            continue

                        # Enqueue marking task to Celery instead of blocking
                        self.stdout.write(f"Step 1: Enqueuing marking task for submission ID: {submission_id}")
                        
                        # Queue the async task (returns immediately)
                        mark_submission_async.delay(submission_id)
                        
                        self.stdout.write(self.style.SUCCESS(f"✓ Task queued for submission {submission_id}; worker will process"))
            except Exception as e:
                self.stderr.write(self.style.ERROR(f"Listener error: {e}; retrying in 5s"))
                time.sleep(5)

    def process_submission_id(self, submission_id: int):
        # For testing: don't import models — just log and (optionally) send via channel layer
        self.stdout.write(self.style.NOTICE("Sending to channel layer"))
        self.stdout.write(self.style.NOTICE(f"New submission ID: {submission_id}"))
        try:
            from asgiref.sync import async_to_sync
            from channels.layers import get_channel_layer
            channel_layer = get_channel_layer()
            print("Sending to channel layer:", channel_layer)
            async_to_sync(channel_layer.group_send)(
                "answers_updates", #group name
                {"type": "answers_update", #will call answers_update in consumers.py 
                 "submission_id": submission_id},
            )
        except Exception as e:
            # it's fine if Channels not configured — we still got the notify
            self.stderr.write(f"Channels send failed (ok for test): {e}")
