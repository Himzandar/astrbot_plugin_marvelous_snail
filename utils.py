# utils.py

from astrbot.api.event import AstrMessageEvent
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import (
    AiocqhttpMessageEvent,
)

import base64
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import os

def cron_to_human(cron: str) -> str:
    """将 5 段 cron（分 时 日 月 周）转换为中文易读描述
    Args:
        cron: 5 段 cron 表达式
    Returns:
        中文易读描述字符串
    """
    parts = cron.strip().split()
    if len(parts) != 5:
        raise ValueError("Cron 表达式必须是 5 段（分 时 日 月 周）")

    minute, hour, day, month, week = parts

    def parse_field(val, unit, names=None):
        if val == "*":
            return f"每{unit}"
        if val.startswith("*/"):
            return f"每{val[2:]}{unit}"
        if "," in val:
            items = val.split(",")
            return "、".join(
                names.get(i, f"{i}{unit}") if names else f"{i}{unit}" for i in items
            )
        if "-" in val:
            start, end = val.split("-")
            if names:
                return f"{names[start]}至{names[end]}"
            return f"{start}到{end}{unit}"
        return names.get(val, f"{val}{unit}") if names else f"{val}{unit}"

    week_names = {
        "0": "周日",
        "1": "周一",
        "2": "周二",
        "3": "周三",
        "4": "周四",
        "5": "周五",
        "6": "周六",
    }

    desc = []

    # 周
    if week != "*":
        desc.append(parse_field(week, "", week_names))

    # 月
    if month != "*":
        desc.append(parse_field(month, "月"))

    # 日
    if day != "*":
        desc.append(parse_field(day, "日"))
    elif week == "*":
        desc.append("每天")

    # 时间
    if hour == "*" and minute == "*":
        desc.append("每分钟")
    else:
        time_desc = []
        if hour != "*":
            time_desc.append(parse_field(hour, "点"))
        if minute != "*":
            time_desc.append(parse_field(minute, "分"))
        desc.append(" ".join(time_desc))

    return " ".join(desc)

async def send_msg(event: AstrMessageEvent, msg: str) -> int | None:
    """发送消息并返回消息ID
    Args:
        event: 消息事件对象
        msg: 要发送的消息内容
    Returns:
        发送平台如果不是 Aiocqhttp 则返回 None，如果是 Aiocqhttp 且发送失败则返回 None ，否则返回消息ID
    """
    if isinstance(event, AiocqhttpMessageEvent):
        payloads: dict = {"message": [{"type": "text", "data": {"text": msg}}]}
        if event.is_private_chat():
            payloads["user_id"] = event.get_sender_id()
            result = await event.bot.api.call_action("send_private_msg", **payloads)
        else:
            payloads["group_id"] = event.get_group_id()
            result = await event.bot.api.call_action("send_group_msg", **payloads)
        return result.get("message_id")
    else:
        await event.send(event.plain_result(msg))
        return None

# ====================== AES 加密工具（个保法合规必备） ======================
SECRET_KEY = b"a7s9d2k4f6g5h3j1q8w2e4r6t7y0u5i"  # 自己改一个

def get_fernet():
    """生成 Fernet 对象用于加密和解密"""
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b"Himzandar",
        iterations=100000,
    )
    key = base64.urlsafe_b64encode(kdf.derive(SECRET_KEY))
    return Fernet(key)

def encrypt_data(text: str) -> str:
    """加密数据，返回加密后的字符串"""
    return get_fernet().encrypt(text.encode()).decode()

def decrypt_data(token: str) -> str:
    """解密数据，返回解密后的字符串"""
    return get_fernet().decrypt(token.encode()).decode()
