import requests
import json
import os
import time
import threading
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler

DISCORD_TOKEN = os.environ.get('DISCORD_TOKEN', '')
FEISHU_WEBHOOK = os.environ.get('FEISHU_WEBHOOK', '')
CHANNEL_IDS_STR = os.environ.get('CHANNEL_IDS', '')
CHANNEL_IDS = [cid.strip() for cid in CHANNEL_IDS_STR.split(',') if cid.strip()] if CHANNEL_IDS_STR else []
POLL_INTERVAL = int(os.environ.get('POLL_INTERVAL', '10'))
PORT = int(os.environ.get('PORT', '10000'))

HEADERS = {'Authorization': DISCORD_TOKEN}
last_message_ids = {}

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
        self.wfile.write(b'OK')
    def log_message(self, format, *args):
        pass

def get_guilds():
    try:
        r = requests.get('https://discord.com/api/v10/users/@me/guilds', headers=HEADERS, timeout=10)
        if r.status_code == 200:
            return [g['id'] for g in r.json()]
    except Exception as e:
        print(f'Error getting guilds: {e}')
    return []

def get_channels(guild_id):
    try:
        r = requests.get(f'https://discord.com/api/v10/guilds/{guild_id}/channels', headers=HEADERS, timeout=10)
        if r.status_code == 200:
            return [c for c in r.json() if c['type'] == 0]
    except Exception as e:
        print(f'Error getting channels: {e}')
    return []

def get_messages(channel_id):
    try:
        url = f'https://discord.com/api/v10/channels/{channel_id}/messages?limit=5'
        r = requests.get(url, headers=HEADERS, timeout=10)
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        print(f'Error getting messages: {e}')
    return []

def send_to_feishu(channel_name, author_name, content):
    try:
        payload = {
            'msg_type': 'text',
            'content': {
                'text': f'Discord Message\n\nChannel: {channel_name}\nAuthor: {author_name}\nContent: {content}'
            }
        }
        r = requests.post(FEISHU_WEBHOOK, headers={'Content-Type': 'application/json'},
                         data=json.dumps(payload, ensure_ascii=False), timeout=10)
        if r.status_code == 200:
            print(f'  -> Sent to Feishu')
        else:
            print(f'  -> Failed: {r.text}')
    except Exception as e:
        print(f'  -> Error: {e}')

def poll_discord(user):
    while True:
        try:
            guilds = get_guilds()
            for guild_id in guilds:
                channels = get_channels(guild_id)
                for ch in channels:
                    if CHANNEL_IDS and ch['id'] not in CHANNEL_IDS:
                        continue
                    messages = get_messages(ch['id'])
                    for msg in reversed(messages):
                        msg_id = msg['id']
                        if msg_id in last_message_ids.get(ch['id'], set()):
                            continue
                        last_message_ids.setdefault(ch['id'], set()).add(msg_id)
                        if len(last_message_ids[ch['id']]) > 100:
                            last_message_ids[ch['id']] = set(list(last_message_ids[ch['id']])[-100:])
                        author = msg.get('author', {})
                        if author.get('id') == user['id']:
                            continue
                        content = msg.get('content', '')
                        if not content:
                            continue
                        print(f'[{datetime.now()}] New: [{ch["name"]}] {author["username"]}: {content[:50]}')
                        send_to_feishu(ch['name'], author['username'], content)
            time.sleep(POLL_INTERVAL)
        except Exception as e:
            print(f'Poll error: {e}')
            time.sleep(POLL_INTERVAL)

def main():
    if not DISCORD_TOKEN:
        print('Error: DISCORD_TOKEN not set')
        return
    if not FEISHU_WEBHOOK:
        print('Error: FEISHU_WEBHOOK not set')
        return
    
    # Start health check server FIRST
    server = HTTPServer(('0.0.0.0', PORT), HealthHandler)
    print(f'Health check server started on port {PORT}')
    threading.Thread(target=server.serve_forever, daemon=True).start()
    
    # Test token
    r = requests.get('https://discord.com/api/v10/users/@me', headers=HEADERS, timeout=10)
    if r.status_code != 200:
        print(f'Error: Invalid Discord Token (status {r.status_code})')
        return
    user = r.json()
    print(f'Logged in as: {user["username"]}')
    print(f'Polling every {POLL_INTERVAL}s')
    print(f'Channel filter: {CHANNEL_IDS if CHANNEL_IDS else "All channels"}')
    print('=' * 50)
    
    poll_discord(user)

if __name__ == '__main__':
    main()
