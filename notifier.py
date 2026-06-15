"""
统一推送模块 — 飞书 + 微信
替代 notify.sh + process_new.sh 中的重复推送逻辑
"""
import json
import os
import subprocess
from datetime import datetime
from pathlib import Path
from urllib.request import Request, urlopen

from config import config


class Notifier:
    def __init__(self):
        self.config = config

    def _get_feishu_token(self, app_id: str, app_secret: str) -> str:
        url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
        body = json.dumps({"app_id": app_id, "app_secret": app_secret}).encode()
        req = Request(url, data=body, headers={"Content-Type": "application/json"})
        with urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            return data.get("tenant_access_token", "")

    def send_feishu(self, chat_id: str, text: str, app_id: str, app_secret: str) -> bool:
        try:
            token = self._get_feishu_token(app_id, app_secret)
        except Exception as e:
            print(f"  [飞书] 获取 token 失败: {e}")
            return False

        content_str = json.dumps({"text": text})
        body = json.dumps({
            "receive_id": chat_id,
            "msg_type": "text",
            "content": content_str,
        }).encode()

        url = "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=open_id"
        req = Request(url, data=body, headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        })

        try:
            with urlopen(req, timeout=10) as resp:
                result = json.loads(resp.read().decode())
                code = result.get("code", -1)
                if code != 0:
                    print(f"  [飞书] 发送失败: {result.get('msg', result)}")
                    return False
                return True
        except Exception as e:
            print(f"  [飞书] 发送失败: {e}")
            return False

    def _cc_connect_path(self) -> str:
        return self.config.get("paths", {}).get("cc_connect", "cc-connect")

    def send_wechat(self, text: str) -> bool:
        cfg = self.config["notify"]["wechat"]
        try:
            result = subprocess.run(
                [
                    self._cc_connect_path(), "send",
                    "--data-dir", cfg["data_dir"],
                    "-s", cfg["session"],
                    "-m", text,
                ],
                capture_output=True, text=True, timeout=15,
                env={**os.environ, "MSYS_NO_PATHCONV": "1"},
            )
            if "successfully" in result.stdout.lower():
                return True
            print(f"  [微信] 发送失败: {result.stdout.strip() or result.stderr.strip()}")
            return False
        except Exception as e:
            print(f"  [微信] 发送失败: {e}")
            return False

    def push_daily_summary(self, tagged_file: str, date_str: str = None):
        if date_str is None:
            date_str = datetime.now().strftime("%Y-%m-%d")

        with open(tagged_file, "r", encoding="utf-8") as f:
            articles = json.load(f)

        total = len(articles)
        relevant = [a for a in articles if a.get("relevance_to_me") and a["relevance_to_me"] != "不直接相关"]
        sources = list(set(a.get("source", "") for a in articles if a.get("source")))

        # 按领域分组
        from collections import defaultdict
        by_domain = defaultdict(list)
        for a in articles:
            by_domain[a.get("domain", "其他")].append(a)

        domain_lines = ""
        for domain, domain_articles in by_domain.items():
            domain_lines += f"  {domain}: {len(domain_articles)} 篇\n"

        if relevant:
            titles = "\n".join(f"  • {a['title'][:60]} ({a.get('domain', '')})" for a in relevant[:5])
            more = f"\n  ...等" if len(relevant) > 5 else ""
            msg = (
                f"📰 今日成功获取 {total} 篇文章 ({date_str})\n"
                f"{domain_lines}\n"
                f"与你相关 ({len(relevant)} 篇)：\n"
                f"{titles}{more}\n\n"
                f"🔗 raw/"
            )
        else:
            msg = (
                f"📰 今日成功获取 {total} 篇文章 ({date_str})\n"
                f"{domain_lines}"
                f"暂无与你直接相关的内容\n"
            )

        feishu = self.config["notify"]["feishu"]
        print(f"[通知] 正在发送...")

        self.send_feishu(feishu["company"]["chat_id"], msg, feishu["company"]["app_id"], feishu["company"]["app_secret"])
        self.send_feishu(feishu["personal"]["chat_id"], msg, feishu["personal"]["app_id"], feishu["personal"]["app_secret"])
        self.send_wechat(msg)

        print(f"  已推送: 飞书 ×2 + 微信")


if __name__ == "__main__":
    import sys
    date_str = sys.argv[1] if len(sys.argv) > 1 else None
    if date_str is None:
        date_str = datetime.now().strftime("%Y-%m-%d")

    n = Notifier()
    tagged_file = f"D:/Claude code/获取信息/data/{date_str}_tagged.json"
    if Path(tagged_file).exists():
        n.push_daily_summary(tagged_file, date_str)
    else:
        print(f"文件不存在: {tagged_file}")
