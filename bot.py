import requests
import json
import os
import time
import random
import threading
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler

# ================= 配置参数 =================
DISCORD_TOKEN = os.environ.get('DISCORD_TOKEN', '')
CHANNEL_MAPPINGS_STR = os.environ.get('CHANNEL_MAPPINGS', '')
PORT = int(os.environ.get('PORT', '10000'))

BASE_HEADERS = {
    'Authorization': DISCORD_TOKEN,
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': '*/*',
    'Accept-Language': 'zh-CN,zh;q=0.9',
    'Referer': 'https://discord.com/channels/@me',
    'X-Discord-Locale': 'zh-CN',
}

last_message_ids = {}
initialized = False
CHANNEL_MAPPINGS = {}

def parse_config():
    if not CHANNEL_MAPPINGS_STR: return
    # 针对分号分割的多个频道进行处理
    for config in CHANNEL_MAPPINGS_STR.split(';'):
        if not config.strip(): continue
        
        # 🛠️ 核心修复：使用 split(':', 1) 限制只切第一刀！
        # 这样 '6540385343:https://open.feishu.cn/...' 会被精准切成：
        # ['6540385343', 'https://open.feishu.cn/...'] 后面 https 的冒号再也不会被切断！
        parts = config.strip().split(':', 1)
        
        if len(parts) == 2:
            cid = parts[0].strip()
            webhooks_part = parts[1].strip()
            # 支持用逗号配置多个飞书群
            CHANNEL_MAPPINGS[cid] = [w.strip() for w in webhooks_part.split(',') if w.strip()]

def get_messages(channel_id):
    try:
        url = f'https://discord.com/api/v10/channels/{channel_id}/messages?limit=20'
        r = requests.get(url, headers=BASE_HEADERS, timeout=15)
        if r.status_code == 429:
            retry_after = r.json().get('retry_after', 10)
            print(f"⚠️ [限流触发] 熔断冷却 {retry_after}s...")
            time.sleep(retry_after + 1)
            return []
        if r.status_code == 200: return r.json()
    except Exception as e:
        print(f"❌ 读取通道 [{channel_id}] 异常: {e}")
    return []

def send_to_feishu(webhook_url, content):
    try:
        payload = {
            'msg_type': 'text',
            'content': {'text': content}
        }
        r = requests.post(webhook_url, json=payload, timeout=10)
        if r.status_code != 200 or r.json().get('code') != 0:
            print(f"❌ 飞书内部拒绝发送: {r.text} | Webhook: {webhook_url}")
    except Exception as e:
        print(f"❌ 飞书网络发送失败: {e} | Webhook: {webhook_url}")

def poll_discord(user):
    global initialized
    
    print(f"\n🚀 智能冒号解析版监控启动！当前用户: {user['username']}")
    print(f"⚙️ 模式: 9-13.8秒随机步调 + 纯净内容\n")

    while True:
        try:
            for channel_id, webhooks in CHANNEL_MAPPINGS.items():
                messages = get_messages(channel_id)
                time.sleep(random.uniform(0.5, 1.5))

                if not messages: continue
                
                if not initialized:
                    last_message_ids[channel_id] = {m['id'] for m in messages}
                    continue
                
                for msg in reversed(messages):
                    mid = msg['id']
                    
                    if mid in last_message_ids.get(channel_id, set()):
                        continue
                    
                    last_message_ids.setdefault(channel_id, set()).add(mid)
                    if len(last_message_ids[channel_id]) > 150: 
                        last_message_ids[channel_id] = set(list(last_message_ids[channel_id])[-150:])
                    
                    if msg.get('author', {}).get('id') == user['id']: 
                        continue
                    
                    text_pieces = []
                    base_content = msg.get('content', '').strip()
                    if base_content:
                        text_pieces.append(base_content)
                    
                    embeds = msg.get('embeds', [])
                    extra_links = []
                    
                    for emb in embeds:
                        if emb.get('title'):
                            text_pieces.append(f"【标题】{emb.get('title').strip()}")
                        if emb.get('description'):
                            text_pieces.append(emb.get('description').strip())
                        
                        if emb.get('url'): 
                            extra_links.append(f"[链接预览]: {emb.get('url')}")
                        elif emb.get('image', {}).get('url'): 
                            extra_links.append(f"[嵌入图片]: {emb.get('image', {}).get('url')}")

                    for att in msg.get('attachments', []):
                        if att.get('url'): 
                            extra_links.append(f"[图片/附件]: {att.get('url')}")
                        if att.get('description'):
                            text_pieces.append(f"（图片说明：{att.get('description').strip()}）")

                    final_content = "\n".join(text_pieces).strip()

                    if not final_content and not extra_links: 
                        continue
                    
                    final_text = final_content
                    if extra_links:
                        final_text = (final_text + "\n" + "\n".join(extra_links)) if final_text else "\n".join(extra_links)
                    
                    if not final_text.strip(): 
                        continue

                    print(f"📩 [{datetime.now().strftime('%H:%M:%S')}] 成功抓取新动态，正在投递...")
                    
                    for webhook in webhooks:
                        send_to_feishu(webhook, final_text)
            
            if not initialized:
                initialized = True
                print("\n--- 🏁 初始化同步完成，开始实时监控新消息 ---\n")

            sleep_time = random.uniform(9.0, 13.8)
            time.sleep(sleep_time)
            
        except Exception as e:
            print(f"🚨 运行异常: {e}")
            time.sleep(13.8)

# ================= 服务入口 =================

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers()
        self.wfile.write(b'OK')
    def log_message(self, *args): pass

def main():
    parse_config()
    if not DISCORD_TOKEN or not CHANNEL_MAPPINGS: return
    server = HTTPServer(('0.0.0.0', PORT), HealthHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    r = requests.get('https://discord.com/api/v10/users/@me', headers=BASE_HEADERS)
    if r.status_code != 200: return
    poll_discord(r.json())

if __name__ == '__main__':
    main()
