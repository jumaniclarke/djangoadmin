# -*- coding: utf-8 -*-
"""
Celery tasks for asynchronous marking.

This decouples submission processing from the listener, enabling concurrent marking.
"""
from celery import shared_task
from django.db import connection
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
import logging

logger = logging.getLogger(__name__)

@shared_task(bind=True, max_retries=3)
def mark_submission_async(self, submission_id):
    """
    Asynchronous marking task.
    
    This runs in a background Celery worker, so:
    - Multiple submissions can be marked in parallel
    - Listener isn't blocked
    - Failed marking can be retried automatically
    
    Args:
        submission_id: The session ID to mark
    """
    from .management.commands.marking import mark_answers_for_session
    
    try:
        logger.info(f"[Celery Task] Starting marking for submission {submission_id}")
        
        # Call the marking function
        mark_answers_for_session(submission_id)
        
        logger.info(f"[Celery Task] ✓ Completed marking for submission {submission_id}")
        return {"status": "success", "submission_id": submission_id}
        
    except Exception as exc:
        logger.error(f"[Celery Task] Error marking submission {submission_id}: {exc}")
        
        # Retry with exponential backoff (3s, 9s, 27s delays)
        raise self.retry(exc=exc, countdown=3 ** self.request.retries)


@shared_task
def submit_notification_update(submission_id, status="completed"):
    """
    Optional: Update submission status via WebSocket after marking completes.
    """
    try:
        channel_layer = get_channel_layer()
        async_to_sync(channel_layer.group_send)(
            f"session_{submission_id}",
            {
                "type": "submission_status",
                "status": status,
                "submission_id": submission_id
            }
        )
        logger.info(f"[Celery Task] Sent status update for submission {submission_id}")
    except Exception as e:
        logger.error(f"[Celery Task] Failed to send status update: {e}")


@shared_task
def detect_unmarked_submissions():
    """
    HEALTH CHECK: Detects submissions that haven't been marked (dead-letter detection).
    
    Runs every 5 minutes to catch:
    - Lost NOTIFY notifications
    - Crashed listener
    - Failed marking tasks
    
    Automatically re-queues unmarked submissions for marking.
    """
    from django.db import connection
    from datetime import timedelta
    from django.utils import timezone
    
    logger.info("[Celery Task] Running dead-letter detection...")
    
    try:
        with connection.cursor() as cursor:
            # Find submissions submitted >2 minutes ago but still not marked
            cursor.execute("""
                SELECT DISTINCT a.sessionid
                FROM answers a
                WHERE a.markawarded IS NULL 
                  AND a.created_at < NOW() - INTERVAL '2 minutes'
                LIMIT 100
            """)
            
            unmarked_sessions = [row[0] for row in cursor.fetchall()]
            
            if unmarked_sessions:
                logger.warning(f"[Dead-Letter] Found {len(unmarked_sessions)} unmarked submissions: {unmarked_sessions}")
                
                # Re-queue each unmarked submission
                for session_id in unmarked_sessions:
                    logger.info(f"[Dead-Letter] Re-queuing submission {session_id}")
                    mark_submission_async.delay(session_id)
            else:
                logger.info("[Dead-Letter] All submissions are marked ✓")
                
    except Exception as e:
        logger.error(f"[Dead-Letter] Detection failed: {e}")

