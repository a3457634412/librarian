"""
归档模块
替代 archiver.sh — >7 天的文件移到 archive/，向量移到存档索引
"""
import json
import shutil
from datetime import datetime, timedelta
from pathlib import Path

from config import config


def archive(date_str: str = None):
    raw_dir = Path(config["paths"]["obsidian_raw"])
    archive_dir = Path(config["paths"]["obsidian_archive"])
    archive_dir.mkdir(parents=True, exist_ok=True)

    cfg = config["archive"]
    threshold = datetime.now() - timedelta(days=cfg["days_threshold"])

    moved = 0
    for md in raw_dir.glob("*.md"):
        try:
            file_date = datetime.strptime(md.stem, "%Y-%m-%d")
        except ValueError:
            continue

        if file_date < threshold:
            dest = archive_dir / md.name
            shutil.move(str(md), str(dest))
            moved += 1
            print(f"  归档: {md.name} → archive/")

    print(f"归档完成: {moved} 个文件")


if __name__ == "__main__":
    archive()
