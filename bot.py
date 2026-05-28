import discord
import requests
import json
import os
from datetime import datetime

DISCORD_TOKEN = os.environ.get('DISCORD_TOKEN', '')
FEISHU_WEBHOOK = os.environ.get('FEISHU_WEBHOOK', '')
CHANNEL_IDS_STR = os.environ.get('CHANNEL_IDS', '')
CHANNEL_IDS = [cid.strip() for cid in CHANNEL_IDS_STR.split(',') if cid.strip()] if CHANNEL_IDS_STR else []

processed_messages = set()

class DiscordToFeishu(discord.Client):
    async def on_ready(self):
        print(f'Logged in as {self.user}')
        print(f'Monitoring: {CHANNEL_IDS if CHANNEL_IDS else "All channels"}')
    
    async def on_message(self, message):
        if message.author == self.user:
            return
        if CHANNEL_IDS and str(message.channel.id) not in CHANNEL_IDS:
            return
        if message.id in processed_messages:
            return
        processed_messages.add(message.id)
        if len(processed_messages) > 1000:
            processed_messages.clear()
        print(f'New message from {message.author.name} in {message.channel.name}')
        await self.send_to_feishu(message)
    
    async def send_to_feishu(self, message):
        try:
            payload = {
                'msg_type': 'text',
                'content': {
                    'text': f'Discord Message\n\nChannel: {message.channel.name}\nAuthor: {message.author.name}\nContent: {message.content}'
                }
            }
            response = requests.post(FEISHU_WEBHOOK, headers={'Content-Type': 'application/json'}, 
                                   data=json.dumps(payload, ensure_ascii=False), timeout=10)
            if response.status_code == 200:
                print('Sent to Feishu')
            else:
                print(f'Failed: {response.text}')
        except Exception as e:
            print(f'Error: {e}')

def main():
    if not DISCORD_TOKEN:
        print('Error: DISCORD_TOKEN not set')
        return
    if not FEISHU_WEBHOOK:
        print('Error: FEISHU_WEBHOOK not set')
        return
    client = DiscordToFeishu()
    try:
        client.run(DISCORD_TOKEN)
    except Exception as e:
        print(f'Error: {e}')

if __name__ == '__main__':
    main()
