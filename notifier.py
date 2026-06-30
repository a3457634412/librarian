"""
统一推送 — 微信 (cc-connect send) + 飞书 (API 直连)

用法:
  from notifier import push
  push(msg)                          # 同时推微信 + 飞书
  push(msg, channels=["weixin"])     # 只推微信
"""

import json
import os
import subprocess
import time
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import URLError

# 加载 .env
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")

# ── 路径 ──────────────────────────────────────
CC_CONNECT = os.getenv("CC_CONNECT_PATH", "D:/Claude code/下载/npm-global/cc-connect.cmd")

# ── 飞书凭证 (从环境变量读取) ─────────────────

FEISHU_APP_ID = os.getenv("FEISHU_APP_ID", "")
FEISHU_APP_SECRET = os.getenv("FEISHU_APP_SECRET", "")

FEISHU_CHATS = {
    "personal": os.getenv("FEISHU_PERSONAL_CHAT_ID", "oc_c2e85cd1179b4752921d1ebc925f31cd"),
}

WECHAT_TARGET = "weixin:dm:o9cq8012PnnFcCfvq22M39_o_KOw@im.wechat"
WECHAT_DATA_DIR = "D:/Claude code/微信"

_token_cache = {"token": "", "expires_at": 0}


def _get_tenant_token() -> str:
    now = time.time()
    if _token_cache["token"] and now < _token_cache["expires_at"] - 60:
        return _token_cache["token"]

    body = json.dumps({
        "app_id": FEISHU_APP_ID,
        "app_secret": FEISHU_APP_SECRET,
    }).encode()

    req = Request(
        "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
        data=body,
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    with urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode())

    token = data.get("tenant_access_token", "")
    expires = data.get("expire", 1800)
    _token_cache["token"] = token
    _token_cache["expires_at"] = now + expires
    return token


def send_feishu(chat_id: str, text: str) -> bool:
    token = _get_tenant_token()
    if not token:
        print("  ⚠️ 飞书 token 获取失败")
        return False

    content = json.dumps({"text": text})
    body = json.dumps({
        "receive_id": chat_id,
        "msg_type": "text",
        "content": content,
    }).encode()

    req = Request(
        "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id",
        data=body,
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "Authorization": f"Bearer {token}",
        },
    )
    try:
        with urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
            if data.get("code") != 0:
                print(f"  ⚠️ 飞书发送失败 [{chat_id[:12]}…]: {data.get('msg', '')}")
                return False
            return True
    except URLError as e:
        print(f"  ⚠️ 飞书发送异常 [{chat_id[:12]}…]: {e}")
        return False


def send_wechat(text: str) -> bool:
    """通过 stdin 发微信，避免特殊字符被 bash 吃掉"""
    try:
        env = {**os.environ, "MSYS_NO_PATHCONV": "1"}
        result = subprocess.run(
            [CC_CONNECT, "send", "--stdin",
             "--data-dir", WECHAT_DATA_DIR,
             "-p", "weixin", "-s", WECHAT_TARGET],
            input=text, capture_output=True, text=True, timeout=30, env=env,
        )
        if result.returncode != 0:
            err = result.stderr.strip()
            print(f"  ⚠️ 微信发送失败: {err[:200]}")
            return False
        return True
    except Exception as e:
        print(f"  ⚠️ 微信发送异常: {e}")
        return False


def push(text: str, channels: list[str] | None = None) -> dict[str, bool]:
    """主入口 — 推送到指定通道，默认全部"""
    if channels is None:
        channels = ["weixin", "feishu"]

    results = {}

    if "weixin" in channels:
        print("  推送微信...")
        results["weixin"] = send_wechat(text)

    if "feishu" in channels:
        for name, chat_id in FEISHU_CHATS.items():
            print(f"  推送飞书 ({name})...")
            results[f"feishu_{name}"] = send_feishu(chat_id, text)

    return results


if __name__ == "__main__":
    push("📡 Librarian 推送测试 — 如果你看到这条消息，说明推送通道正常。")
