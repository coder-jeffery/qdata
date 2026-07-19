"""告警通知：钉钉/企微 webhook（失败也尽量投递）。"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request

from qdata.config import settings

logger = logging.getLogger(__name__)


def notify(title: str, content: str, *, ok: bool = True) -> bool:
    """向 QDATA_ALERT_WEBHOOK 发送文本。无配置时返回 False 且不报错。"""
    url = (settings().alert_webhook or "").strip()
    if not url:
        return False
    text = f"{'[OK]' if ok else '[FAIL]'} {title}\n{content}".strip()
    # 钉钉/企微 text 兼容
    body = json.dumps(
        {"msgtype": "text", "text": {"content": text}},
        ensure_ascii=False,
    ).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            _ = resp.read()
        return True
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        logger.warning("webhook 通知失败: %s", e)
        return False
