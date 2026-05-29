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

# 模拟真实浏览器 Header，降低封号风险
BASE_HEADERS = {
    'Authorization': DISCORD_TOKEN,
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': '*/*',
    'Accept-Language': 'zh-CN,zh;q=0.9',
    'Referer': 'https://discord.com/channels/@me',
    'X-Discord-Locale': 'zh-CN',
}

# 全局变量
last_message_ids = {}
initialized = False
CHANNEL_MAPPINGS = {}
CHANNEL_CUSTOM_NAMES = {}

# ================= 核心逻辑 =================

def parse_config():
    """解析环境变量中的频道映射"""
    if not CHANNEL_MAPPINGS_STR:
        return
    for config in CHANNEL_MAPPINGS_STR.split(';'):
        if not config.strip(): continue
        parts = config.strip().split(':')
        # 格式 A: 频道ID:群名:Webhook
        if len(parts) >= 3:
            cid = parts[0].strip()
            cname = parts[1].strip()
            # 重新组合 Webhook 地址，防止 URL 中包含冒号导致分割错误
            webhook = ':'.join(parts[2:]).strip()
            CHANNEL_MAPPINGS[cid] = [w.strip() for w in webhook.split(',') if w.strip()]
            CHANNEL_CUSTOM_NAMES[cid] = cname
        # 格式 B: 频道ID:Webhook (自动获取名字)
        elif len(parts) == 2:
            cid = parts[0].strip()
            webhook = parts[1].strip()
            CHANNEL_MAPPINGS[cid] = [w.strip() for w in webhook.split(',') if w.strip()]

def get_channel_real_name(channel_id):
    """从 Discord API 获取真实的频道名称"""
    try:
        url = f'https://discord.com/api/v10/channels/{channel_id}'
        r = requests.get(url, headers=BASE_HEADERS, timeout=10)
        if r.status_code == 200:
            return r.json().get('name', f'ID-{channel_id[:8]}')
    except:
        pass
    return f'ID-{channel_id[:8]}'

def get_messages(channel_id):
    """拉取 Discord 消息，包含 429 频率限制处理"""
    try:
        url = f'https://discord.com/api/v10/channels/{channel_id}/messages?limit=5'
        r = requests.get(url, headers=BASE_HEADERS, timeout=15)
        
        if r.status_code == 429:
            retry_after = r.json().get('retry_after', 10)
            print(f"⚠️ [风控触发] Discord 要求等待 {retry_after}s，执行冷却...")
            time.sleep(retry_after + 1)
            return []
            
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        print(f"❌ 网络异常: {e}")
    return []

def send_to_feishu(webhook_url, channel_name, content):
    """发送消息到飞书"""
    try:
        payload = {
            'msg_type': 'text',
            'content': {'text': f'[{channel_name}]\n{content}'}
        }
        requests.post(webhook_url, json=payload, timeout=10)
    except Exception as e:
        print(f"❌ 飞书发送失败: {e}")

def poll_discord(user):
    global initialized
    channel_display_names = {}
    
    # 初始化频道名称展示
    print("🔍 正在配置频道名称...")
    for cid in CHANNEL_MAPPINGS.keys():
        if cid in CHANNEL_CUSTOM_NAMES:
            channel_display_names[cid] = CHANNEL_CUSTOM_NAMES[cid]
        else:
            channel_display_names[cid] = get_channel_real_name(cid)
    
    print(f"✅ 监控启动！当前用户: {user['username']}")
    print(f"⚙️ 模式: 9-15秒随机人类行为模拟")

    while True:
        try:
            for channel_id, webhooks in CHANNEL_MAPPINGS.items():
                messages = get_messages(channel_id)
                
                # 模拟人类在群组间切换的停顿
                time.sleep(random.uniform(0.5, 1.5))

                if not initialized:
                    if messages:
                        last_message_ids[channel_id] = {m['id'] for m in messages}
                    continue
                
                # 处理新消息
                for msg in reversed(messages):
                    mid = msg['id']
                    # 如果消息已处理过，跳过
                    if mid in last_message_ids.get(channel_id, set()):
                        continue
                    
                    # 存入已处理列表
                    last_message_ids.setdefault(channel_id, set()).add(mid)
                    # 限制内存缓存大小
                    if len(last_message_ids[channel_id]) > 50:
                        last_message_ids[channel_id] = set(list(last_message_ids[channel_id])[-50:])
                    
                    # 排除自己发的消息
                    if msg.get('author', {}).get('id') == user['id']:
                        continue
                    
                    content = msg.get('content', '')
                    if not content: continue # 略过空消息（纯图片等）
                    
                    cname = channel_display_names.get(channel_id)
                    print(f"📩 [{datetime.now().strftime('%H:%M:%S')}] 来自 [{cname}] 的新消息")
                    
                    for webhook in webhooks:
                        send_to_feishu(webhook, cname, content)
            
            if not initialized:
                initialized = True
                print("--- 🏁 初始化同步完成，开始实时监控 ---")

            # 🎯 核心需求：9-15秒随机访问一次
            sleep_time = random.uniform(8.8, 13.8)
            time.sleep(sleep_time)
            
        except Exception as e:
            print(f"🚨 循环异常: {e}")
            time.sleep(15)

# ================= 服务入口 =================

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
        self.wfile.write(b'OK')
    def log_message(self, *args): pass

def main():
    parse_config()
    if not DISCORD_TOKEN or not CHANNEL_MAPPINGS:
        print("❌ 错误: DISCORD_TOKEN 或 CHANNEL_MAPPINGS 未配置")
        return
    
    # 启动 Render 健康检查端口
    server = HTTPServer(('0.0.0.0', PORT), HealthHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    
    # 验证 Token
    r = requests.get('https://discord.com/api/v10/users/@me', headers=BASE_HEADERS)
    if r.status_code != 200:
        print(f"❌ Token 验证失败 (Code: {r.status_code})，请检查环境变量。")
        return
    
    poll_discord(r.json())

if __name__ == '__main__':
    main()
