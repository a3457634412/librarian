"""统一配置 — 所有模块从这里导入，消除重复的 _load_config()"""
import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

# .env → os.environ
_env_path = Path(__file__).parent / ".env"
if _env_path.exists():
    load_dotenv(_env_path)

# config.yaml
_config_path = Path(__file__).parent / "config.yaml"
with open(_config_path, "r", encoding="utf-8") as f:
    config: dict = yaml.safe_load(f)

DEEPSEEK_API_KEY: str = os.getenv("DEEPSEEK_API_KEY", "")
QWEN_API_KEY: str = os.getenv("QWEN_API_KEY", "")
QWEN_BASE_URL: str = os.getenv("QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")

# HuggingFace 镜像 (国内网络)
_hf_mirror = config.get("index", {}).get("hf_mirror", "")
if _hf_mirror and not os.getenv("HF_ENDPOINT"):
    os.environ["HF_ENDPOINT"] = _hf_mirror
