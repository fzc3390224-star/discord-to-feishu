import requests
import json
import os
import time
import random
import threading
from datetime import datetime, timezone

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

# 全局状态
last_message_ids = {}
START_TIME = datetime.now(timezone.utc)  # 🛠️ 核心：记录脚本启动的精准时间戳（UTC时间）
CHANNEL_MAPPINGS = {}
CHANNEL_CUSTOM_NAMES = {}

def parse_config():
    if not CHANNEL_MAPPINGS_STR: 
        print("⚠️ CHANNEL_MAPPINGS 环境变量为空")
        return
    for config in CHANNEL_MAPPINGS_STR.split(';'):
        if not config.strip(): continue
        parts = config.strip().split(':')
        if len(parts) >= 3:
            cid, cname = parts[0].strip(), parts[1].strip()
            webhook = ':'.join(parts[2:]).strip()
            CHANNEL_MAPPINGS[cid] = [w.strip() for w in webhook.split(',') if w.strip()]
            CHANNEL_CUSTOM_NAMES[cid] = cname
        elif len(parts) == 2:
            cid, webhook = parts[0].strip(), parts[1].strip()
            CHANNEL_MAPPINGS[cid] = [w.strip() for w in webhook.split(',') if w.strip()]

def get_channel_real_name(channel_id):
    try:
        url = f'https://discord.com/api/v10/channels/{channel_id}'
        r = requests.get(url, headers=BASE_HEADERS, timeout=10)
        if r.status_code == 200:
            return r.json().get('name', f'ID-{channel_id[:8]}')
    except: pass
    return f'ID-{channel_id[:8]}'

def get_messages(channel_id):
    try:
        # 🛠️ 提升抓取上限到 20 条，防止高频刷屏时漏消息
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

def send_to_feishu(webhook_url, channel_name, content):
    try:
        payload = {
            'msg_type': 'text',
            'content': {'text': f'[{channel_name}]\n{content}'}
        }
        r = requests.post(webhook_url, json=payload, timeout=10)
        if r.status_code != 200 or r.json().get('code') != 0:
            print(f"❌ 飞书端拦截或出错: {r.text}")
    except Exception as e:
        print(f"❌ 飞书网络发送失败: {e}")

def poll_discord(user):
    channel_display_names = {}
    
    print("🔍 正在初始化频道名称...")
    for cid in CHANNEL_MAPPINGS.keys():
        channel_display_names[cid] = CHANNEL_CUSTOM_NAMES.get(cid) or get_channel_real_name(cid)
    
    print(f"\n🚀 终极无漏监控启动！当前用户: {user['username']}")
    print(f"⏰ 启动基准时间 (UTC): {START_TIME.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"⚙️ 模式: 9-13.8秒随机步调 + 文字+URL防漏版\n")

    while True:
        try:
            for channel_id, webhooks in CHANNEL_MAPPINGS.items():
                messages = get_messages(channel_id)
                # 频道间人类行为切换停顿
                time.sleep(random.uniform(0.5, 1.5))

                if not messages: continue
                
                for msg in reversed(messages):
                    mid = msg['id']
                    
                    # 1. 查重过滤器：去过发过的直接跳过
                    if mid in last_message_ids.get(channel_id, set()):
                        continue
                    
                    # 2. 核心改进：时间戳过滤器 🛠️
                    # 解析 Discord 消息自带的 ISO 时间戳字符串 (转换为 UTC datetime)
                    # 格式样例: "2024-03-29T12:00:00.123000+00:00"
                    msg_timestamp_str = msg.get('timestamp')
                    if msg_timestamp_str:
                        # 兼容处理 Discord 返回的时间字符串格式
                        msg_timestamp_str = msg_timestamp_str.replace('Z', '+00:00')
                        msg_time = datetime.fromisoformat(msg_timestamp_str)
                        
                        # 核心防漏铁律：只要消息时间晚于脚本启动时间，它就是新消息！哪怕它是在初始化时被抓到的！
                        if msg_time < START_TIME:
                            # 属于脚本开启前的陈年老账，记录 ID 并无情跳过
                            last_message_ids.setdefault(channel_id, set()).add(mid)
                            continue

                    # 3. 记录当前处理的消息 ID，限制去重集合大小
                    last_message_ids.setdefault(channel_id, set()).add(mid)
                    if len(last_message_ids[channel_id]) > 100: # 扩大去重池到 100
                        last_message_ids[channel_id] = set(list(last_message_ids[channel_id])[-100:])
                    
                    # 4. 身份过滤器：排除自己发的
                    if msg.get('author', {}).get('id') == user['id']: 
                        continue
                    
                    # 5. 提取内容与链接
                    content = msg.get('content', '').strip()
                    
                    extra_links = []
                    for att in msg.get('attachments', []):
                        if att.get('url'): extra_links.append(f"[图片/附件]: {att.get('url')}")
                    for emb in msg.get('embeds', []):
                        if emb.get('url'): extra_links.append(f"[链接预览]: {emb.get('url')}")
                        elif emb.get('image', {}).get('url'): extra_links.append(f"[嵌入图片]: {emb.get('image', {}).get('url')}")

                    if not content and not extra_links: 
                        continue
                    
                    final_text = content
                    if extra_links:
                        final_text = (final_text + "\n" + "\n".join(extra_links)) if final_text else "\n".join(extra_links)
                    
                    if not final_text.strip(): 
                        continue

                    cname = channel_display_names.get(channel_id)
                    print(f"📩 [{datetime.now().strftime('%H:%M:%S')}] 抓取到 [{cname}] 真正新动态并投递")
                    
                    for webhook in webhooks:
                        send_to_feishu(webhook, cname, final_text)
            
            # 精准执行 9 ~ 13.8 秒人类随机休眠
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
    if not DISCORD_TOKEN or not CHANNEL_MAPPINGS: 
        print("❌ 错误: 环境变量不完整")
        return
    
    server = HTTPServer(('0.0.0.0', PORT), HealthHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    
    r = requests.get('https://discord.com/api/v10/users/@me', headers=BASE_HEADERS)
    if r.status_code != 200: 
        print(f"❌ 身份校验失败: {r.status_code}")
        return
    
    poll_discord(r.json())

if __name__ == '__main__':
    main()
