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
CHANNEL_CUSTOM_NAMES = {}

def parse_config():
    if not CHANNEL_MAPPINGS_STR: 
        print("⚠️ 警告: CHANNEL_MAPPINGS 环境变量是空的！")
        return
    print(f"原配置文本: {CHANNEL_MAPPINGS_STR}")
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
    print(f"成功解析的映射表: {CHANNEL_MAPPINGS}")
    print(f"成功解析的别名表: {CHANNEL_CUSTOM_NAMES}")

def get_channel_real_name(channel_id):
    try:
        url = f'https://discord.com/api/v10/channels/{channel_id}'
        r = requests.get(url, headers=BASE_HEADERS, timeout=10)
        if r.status_code == 200:
            return r.json().get('name', f'ID-{channel_id[:8]}')
        else:
            print(f"⚠️ 无法获取频道 {channel_id} 的真实名字，状态码: {r.status_code}")
    except Exception as e: 
        print(f"⚠️ 获取频道名称异常: {e}")
    return f'ID-{channel_id[:8]}'

def get_messages(channel_id):
    try:
        url = f'https://discord.com/api/v10/channels/{channel_id}/messages?limit=5'
        r = requests.get(url, headers=BASE_HEADERS, timeout=15)
        print(f"🔄 正在尝试读取频道 [{channel_id}]，Discord 返回状态码: {r.status_code}")
        if r.status_code == 429:
            retry_after = r.json().get('retry_after', 10)
            print(f"⚠️ [风控触发] 触发限流，请求冷却 {retry_after}s...")
            time.sleep(retry_after + 1)
            return []
        if r.status_code == 200: 
            msgs = r.json()
            print(f"📥 成功获取到 {len(msgs)} 条历史消息")
            return msgs
    except Exception as e:
        print(f"❌ 读取消息网络异常: {e}")
    return []

def send_to_feishu(webhook_url, channel_name, content):
    try:
        payload = {
            'msg_type': 'text',
            'content': {'text': f'[{channel_name}]\n{content}'}
        }
        print(f"📤 正在向飞书投递消息...")
        r = requests.post(webhook_url, json=payload, timeout=10)
        print(f"📬 飞书接口返回: {r.text}")
    except Exception as e:
        print(f"❌ 飞书投递异常: {e}")

def poll_discord(user):
    global initialized
    channel_display_names = {}
    
    print("\n--- 🔍 步骤 2: 初始化频道展示名称 ---")
    for cid in CHANNEL_MAPPINGS.keys():
        channel_display_names[cid] = CHANNEL_CUSTOM_NAMES.get(cid) or get_channel_real_name(cid)
    
    print(f"\n✅ 监控正式启动！登录账号: {user['username']} (ID: {user['id']})")
    print(f"⚙️ 运行模式: 9-13.8秒随机纯文本排错版\n")

    while True:
        try:
            for channel_id, webhooks in CHANNEL_MAPPINGS.items():
                cname = channel_display_names.get(channel_id)
                print(f"\n⏱️ [{datetime.now().strftime('%H:%M:%S')}] ---> 开始轮询频道: [{cname}] ({channel_id})")
                
                messages = get_messages(channel_id)
                time.sleep(random.uniform(0.5, 1.5))

                if not initialized:
                    if messages:
                        last_message_ids[channel_id] = {m['id'] for m in messages}
                        print(f"📌 [初始化阶段] 已记录当前最新的 {len(messages)} 条消息 ID，跳过发送。")
                    else:
                        print(f"📌 [初始化阶段] 当前频道没有任何历史消息。")
                    continue
                
                if not messages:
                    print(f"ℹ️ 本轮未抓取到任何消息（可能网络波动或接口为空）")
                    continue

                for msg in reversed(messages):
                    mid = msg['id']
                    author_name = msg.get('author', {}).get('username', '未知用户')
                    msg_content = msg.get('content', '')
                    
                    print(f"🔍 检查消息 ID: {mid} | 发送者: {author_name} | 内容开头: {msg_content[:15]}")

                    # 检查是否重复
                    if mid in last_message_ids.get(channel_id, set()): 
                        print("   -> 略过：属于旧消息")
                        continue
                    
                    last_message_ids.setdefault(channel_id, set()).add(mid)
                    if len(last_message_ids[channel_id]) > 50:
                        last_message_ids[channel_id] = set(list(last_message_ids[channel_id])[-50:])
                    
                    # 检查是不是自己
                    if msg.get('author', {}).get('id') == user['id']: 
                        print("   -> 略过：这是你自己在 Discord 发的消息")
                        continue
                    
                    # 提取文字
                    content = msg_content.strip()
                    
                    # 提取图片/网页链接
                    extra_links = []
                    for att in msg.get('attachments', []):
                        if att.get('url'): extra_links.append(f"[附件/图片链接]: {att.get('url')}")
                    for emb in msg.get('embeds', []):
                        if emb.get('url'): extra_links.append(f"[预览链接]: {emb.get('url')}")
                        elif emb.get('image', {}).get('url'): extra_links.append(f"[嵌入图链接]: {emb.get('image', {}).get('url')}")

                    if not content and not extra_links:
                        print("   -> 略过：该消息不含任何可转发文本或有效链接")
                        continue
                    
                    final_text = content
                    if extra_links:
                        final_text = (final_text + "\n" + "\n".join(extra_links)) if final_text else "\n".join(extra_links)
                    
                    if not final_text.strip(): 
                        print("   -> 略过：最终文本内容为空")
                        continue
                    
                    print(f"🔥 发现全新有效消息！准备发送至飞书...")
                    for webhook in webhooks:
                        send_to_feishu(webhook, cname, final_text)
            
            if not initialized:
                initialized = True
                print("\n" + "="*20 + " 🏁 初始化同步完成，开始实时监控新消息 " + "="*20 + "\n")

            sleep_time = random.uniform(9.0, 13.8)
            print(f"💤 这一轮所有群轮询完毕，随机休眠 {sleep_time:.2f} 秒...")
            time.sleep(sleep_time)
            
        except Exception as e:
            print(f"🚨 循环发生致命异常: {e}")
            time.sleep(13.8)

# ================= 服务入口 =================

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers()
        self.wfile.write(b'OK')
    def log_message(self, *args): pass

def main():
    print("--- 🔍 步骤 1: 开始解析环境变量 ---")
    parse_config()
    if not DISCORD_TOKEN or not CHANNEL_MAPPINGS: 
        print("❌ 错误: 基础环境变量配置不完整，请检查 DISCORD_TOKEN 和 CHANNEL_MAPPINGS")
        return
    
    server = HTTPServer(('0.0.0.0', PORT), HealthHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    
    print("\n--- 🔍 步骤 2: 正在向 Discord 验证 Token 身份 ---")
    r = requests.get('https://discord.com/api/v10/users/@me', headers=BASE_HEADERS)
    if r.status_code != 200: 
        print(f"❌ 身份验证失败！Discord 返回状态码: {r.status_code}。请确认 Token 是否过期或填错。")
        return
    
    poll_discord(r.json())

if __name__ == '__main__':
    main()
