# consumers.py
from channels.generic.websocket import AsyncWebsocketConsumer
from django.db import connection
import json
from channels.db import database_sync_to_async

class AnswersConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        await self.channel_layer.group_add("answers_updates", self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard("answers_updates", self.channel_name)

    async def answers_update(self, event):
        # Debug print to server log
        print(f"[Channels] answers_update called with event: {event}")
        # Send message to WebSocket
        print("About to send to WebSocket:", event)
        await self.send(text_data=json.dumps({
            "submission_id": event["submission_id"]
        }))


class SessionMarksConsumer(AsyncWebsocketConsumer):
    @database_sync_to_async
    def fetch_data(self):
        with connection.cursor() as cur:
            cur.execute(
                "SELECT questionid, markawarded, feedback FROM answers_stream WHERE sessionid = %s",
                [self.sessionid],
            )
            return cur.fetchall()
            
    async def connect(self):
        try:
            # Extract sessionid from URL route
            self.sessionid = self.scope['url_route']['kwargs']['sessionid']
            self.group_name = f"session_{self.sessionid}"
            
            # Join session-specific group
            await self.channel_layer.group_add(self.group_name, self.channel_name)
            await self.accept()
            print(f"[SessionMarksConsumer] Client connected to session {self.sessionid}")

            # On connect, send current marks snapshot for this session (async-safe)
            rows = await self.fetch_data()
            for questionid, mark, feedback in rows:
                await self.send(text_data=json.dumps({
                    "type": "mark_update",
                    "questionid": str(questionid),
                    "mark": mark,
                    "feedback": feedback,
                    "initial": True,
                }))
        except Exception as e:
            print(f"[SessionMarksConsumer] Connection error: {e}")
            import traceback
            traceback.print_exc()
            await self.close()

    async def disconnect(self, close_code):
        try:
            # Leave group
            await self.channel_layer.group_discard(self.group_name, self.channel_name)
            print(f"[SessionMarksConsumer] Client disconnected from session {self.sessionid}")
        except Exception as e:
            print(f"[SessionMarksConsumer] Disconnect error: {e}")

    async def mark_update(self, event):
        try:
            # Send mark update to WebSocket
            print(f"[SessionMarksConsumer] Sending mark update: {event}")
            await self.send(text_data=json.dumps({
                "type": "mark_update",
                "questionid": str(event["questionid"]),
                "mark": event["mark"],
                "feedback": event.get("feedback", "")
            }))
        except Exception as e:
            print(f"[SessionMarksConsumer] Send error: {e}")