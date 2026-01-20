# consumers.py
from channels.generic.websocket import AsyncWebsocketConsumer
import json

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