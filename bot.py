import requests
import json
import os
import time
import threading
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler

DISCORD_TOKEN = os.environ.get('DISCORD_TOKEN', '')
CHANNEL_MAPPINGS_STR = os.environ.get('CHANNEL_MAPPINGS', '')
POLL_INTERVAL = int(os.environ.get('POLL_INTERVAL', '10'))
PORT = int(os.environ.get('PORT', '10000'))

HEADERS = {'Authorization': DISCORD_TOKEN}
last_message_ids = {}

# 解析频道映射配置
# 格式: "频道ID1:webhook1,webhook2;频道ID2:webhook3"
CHANNEL_MAPPINGS = {}
if CHANNEL_MAPPINGS_STR:
    for channel_config in CHANNEL_MAPPINGS_STR.split(';'):
        if ':' in channel_config:
            parts = channel_config.strip().split(':', 1)
            channel_id = parts[0].strip()
            webhooks_str = parts[1].strip()
            webhooks = [w.strip() for w in webhooks_str.split(',') if w.strip()]
            if channel_id and webhooks:
                CHANNEL_MAPPINGS[channel_id] = webhooks

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
        self.wfile.write(b'OK')
    def log_message(self, format, *args):
        pass

def get_messages(channel_id):
    try:
        url = f'https://discord.com/api/v10/channels/{channel_id}/messages?limit=10'
        r = requests.get(url, headers=HEADERS, timeout=10)
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        pass
    return []

def send_to_feishu(webhook_url, channel_id, author_name, content):
    try:
        payload = {
            'msg_type': 'text',
            'content': {
                'text': f'Discord Message\n\nChannel: {channel_id}\nAuthor: {author_name}\nContent: {content}'
            }
        }
        r = requests.post(webhook_url, headers={'Content-Type': 'application/json'},
                         data=json.dumps(payload, ensure_ascii=False), timeout=10)
    except Exception as e:
        pass

def poll_discord(user):
    while True:
        try:
            for channel_id, webhooks in CHANNEL_MAPPINGS.items():
                messages = get_messages(channel_id)
                for msg in reversed(messages):
                    msg_id = msg['id']
                    if msg_id in last_message_ids.get(channel_id, set()):
                        continue
                    last_message_ids.setdefault(channel_id, set()).add(msg_id)
                    if len(last_message_ids[channel_id]) > 100:
                        last_message_ids[channel_id] = set(list(last_message_ids[channel_id])[-100:])
                    author = msg.get('author', {})
                    if author.get('id') == user['id']:
                        continue
                    content = msg.get('content', '')
                    if not content:
                        continue
                    print(f'[{datetime.now()}] [{channel_id}] {author["username"]}: {content[:50]}')
                    for webhook in webhooks:
                        send_to_feishu(webhook, channel_id, author['username'], content)
            time.sleep(POLL_INTERVAL)
        except Exception as e:
            time.sleep(POLL_INTERVAL)

def main():
    if not DISCORD_TOKEN:
        return
    if not CHANNEL_MAPPINGS:
        return
    
    server = HTTPServer(('0.0.0.0', PORT), HealthHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    
    r = requests.get('https://discord.com/api/v10/users/@me', headers=HEADERS, timeout=10)
    if r.status_code != 200:
        return
    user = r.json()
    print(f'Logged in as: {user["username"]}')
    print(f'Polling every {POLL_INTERVAL}s')
    for ch, hooks in CHANNEL_MAPPINGS.items():
        print(f'Channel {ch} -> {len(hooks)} webhook(s)')
    print('=' * 50)
    
    poll_discord(user)

if __name__ == '__main__':
    main()
