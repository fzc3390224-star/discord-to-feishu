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

# 模拟真实浏览器 Header
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
    if not CHANNEL_MAPPINGS_STR: return
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
        url = f'https://discord.com/api/v10/channels/{channel_id}/messages?limit=5'
        r = requests.get(url, headers=BASE_HEADERS, timeout=15)
        if r.status_code == 429:
            retry_after = r.json().get('retry_after', 10)
            print(f"⚠️ [风控触发] Discord 要求冷却 {retry_after}s...")
            time.sleep(retry_after + 1)
            return []
        if r.status_code == 200: return r.json()
    except Exception as e:
        print(f"❌ 网络异常: {e}")
    return []

def upload_image_to_feishu(webhook_url, image_url):
    """下载 Discord 图片并上传到飞书，获取 image_key"""
    try:
        # 1. 下载 Discord 图片 (使用伪装 Header)
        img_res = requests.get(image_url, headers=BASE_HEADERS, timeout=15)
        if img_res.status_code != 200: return None
        img_data = img_res.content

        # 2. 从 Webhook 提取飞书域名，换取上传接口 URL
        # 飞书 Webhook 形式如：https://open.feishu.cn/open-apis/bot/v2/hook/xxx
        # 其对应的图片上传接口为：https://open.feishu.cn/open-apis/bot/v2/hook/upload_image/xxx
        if "upload_image" not in webhook_url:
            upload_url = webhook_url.replace("/v2/hook/", "/v2/hook/upload_image/")
        else:
            upload_url = webhook_url

        # 3. 上传到飞书
        files = {
            'image': ('image.png', img_data, 'image/png')
        }
        # 飞书限制自定义机器人上传图片格式为 form-data，且必须带 image_type
        data = {'image_type': 'message'} 
        
        up_res = requests.post(upload_url, files=files, data=data, timeout=20)
        if up_res.status_code == 200:
            res_json = up_res.json()
            if res_json.get('code') == 0:
                return res_json.get('data', {}).get('image_key')
            else:
                print(f"❌ 飞书图片上传返回错误: {res_json.get('msg')}")
    except Exception as e:
        print(f"❌ 上传图片到飞书失败: {e}")
    return None

def send_to_feishu_rich_text(webhook_url, channel_name, content, image_keys):
    """使用飞书富文本(post)消息格式发送文字和图片"""
    try:
        # 构造富文本内容
        content_element = []
        
        # 添加文字部分
        if content:
            content_element.append({"tag": "text", "text": f"{content}\n"})
        
        # 添加图片部分
        for img_key in image_keys:
            if img_key:
                content_element.append({"tag": "img", "image_key": img_key})

        payload = {
            "msg_type": "post",
            "content": {
                "post": {
                    "zh_cn": {
                        "title": f"[{channel_name}]",
                        "content": [content_element]
                    }
                }
            }
        }
        requests.post(webhook_url, json=payload, timeout=10)
    except Exception as e:
        print(f"❌ 飞书富文本发送失败: {e}")

def poll_discord(user):
    global initialized
    channel_display_names = {}
    
    print("🔍 正在配置频道名称...")
    for cid in CHANNEL_MAPPINGS.keys():
        channel_display_names[cid] = CHANNEL_CUSTOM_NAMES.get(cid) or get_channel_real_name(cid)
    
    print(f"✅ 监控启动！当前用户: {user['username']}")
    print(f"⚙️ 模式: 9-13.8秒随机人类行为模拟 + 支持图片同步")

    while True:
        try:
            for channel_id, webhooks in CHANNEL_MAPPINGS.items():
                messages = get_messages(channel_id)
                time.sleep(random.uniform(0.5, 1.5))

                if not initialized:
                    if messages:
                        last_message_ids[channel_id] = {m['id'] for m in messages}
                    continue
                
                for msg in reversed(messages):
                    mid = msg['id']
                    if mid in last_message_ids.get(channel_id, set()): continue
                    
                    last_message_ids.setdefault(channel_id, set()).add(mid)
                    if len(last_message_ids[channel_id]) > 50:
                        last_message_ids[channel_id] = set(list(last_message_ids[channel_id])[-50:])
                    
                    if msg.get('author', {}).get('id') == user['id']: continue
                    
                    content = msg.get('content', '')
                    
                    # 🔍 提取 Discord 消息中的图片
                    image_keys_map = {} # 格式 {webhook: [image_key1, ...]}
                    attachments = msg.get('attachments', [])
                    embeds = msg.get('embeds', [])
                    
                    # 收集所有的图片 URL
                    img_urls = []
                    for att in attachments:
                        if att.get('content_type', '').startswith('image/') or att.get('url', '').split('?')[0].endswith(('png', 'jpg', 'jpeg', 'gif', 'webp')):
                            img_urls.append(att.get('url'))
                    for emb in embeds:
                        if emb.get('image', {}).get('url'):
                            img_urls.append(emb.get('image', {}).get('url'))

                    # 如果没有任何文字，也没有任何图片，则跳过
                    if not content and not img_urls: continue
                    
                    cname = channel_display_names.get(channel_id)
                    print(f"📩 [{datetime.now().strftime('%H:%M:%S')}] 来自 [{cname}] 的新消息(文字长度:{len(content)}, 图片数:{len(img_urls)})")
                    
                    # 分别处理每个 webhook（因为每个 webhook 上传图片生成的 image_key 是独立的）
                    for webhook in webhooks:
                        feishu_img_keys = []
                        if img_urls:
                            for url in img_urls:
                                img_key = upload_image_to_feishu(webhook, url)
                                if img_key: feishu_img_keys.append(img_key)
                        
                        # 统一使用富文本格式发送，体验更好
                        send_to_feishu_rich_text(webhook, cname, content, feishu_img_keys)
            
            if not initialized:
                initialized = True
                print("--- 🏁 初始化同步完成，开始实时监控 ---")

            # 🎯 你的专属随机时间设定
            sleep_time = random.uniform(8.8, 13.8)
            time.sleep(sleep_time)
            
        except Exception as e:
            print(f"🚨 循环异常: {e}")
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
        print("❌ 错误: 环境变量未配置完全")
        return
    
    server = HTTPServer(('0.0.0.0', PORT), HealthHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    
    r = requests.get('https://discord.com/api/v10/users/@me', headers=BASE_HEADERS)
    if r.status_code != 200:
        print(f"❌ Token 验证失败 ({r.status_code})")
        return
    
    poll_discord(r.json())

if __name__ == '__main__':
    main()
