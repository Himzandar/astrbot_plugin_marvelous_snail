# utils.py
import base64
import json
import urllib.parse

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import (
    AiocqhttpMessageEvent,
)


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
    try:
        if isinstance(event, AiocqhttpMessageEvent):
            payloads: dict = {"message": [{"type": "text", "data": {"text": msg}}]}
            if event.is_private_chat():
                payloads["user_id"] = event.get_sender_id()
                result = await event.bot.api.call_action("send_private_msg", **payloads)
            else:
                payloads["group_id"] = event.get_group_id()
                result = await event.bot.api.call_action("send_group_msg", **payloads)
            return result.get("message_id")

        await event.send(event.plain_result(msg))
        return None
    except Exception as exc:
        logger.error(f"发送消息失败: {exc}")
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

def convert_to_query_bytes(data, account, page_id=1):
    """
    将输入字典转换为类似示例的 URL 查询字节串
    :param data: 原始数据字典
    :param account: 外部传入的手机号（示例中固定为 "1234567890"）
    :param page_id: 固定页号，默认为 1
    :return: bytes 类型的查询字符串
    """
    if not isinstance(data, dict):
        raise ValueError("角色数据格式无效")

    required_fields = [
        "game_id",
        "role_id",
        "role_name",
        "server_id",
        "server_name",
        "platform",
    ]
    missing_fields = [field for field in required_fields if not data.get(field)]
    if missing_fields:
        raise ValueError(f"角色数据缺少必要字段: {', '.join(missing_fields)}")

    # 构建基础参数
    params = {
        "account": account,
        "page_id": str(page_id),
        "game_id": str(data["game_id"]),
        "role_id": data["role_id"],
        "role_name": data["role_name"],
        "server_id": str(data["server_id"]),
        "server_name": data["server_name"],
        "type": data["platform"],          # 示例中 type 取自 platform
        "platform": data["platform"],
    }
    # 处理 extra 字段：转换为紧凑 JSON 字符串
    extra_raw = data.get("extra")
    extra_data = extra_raw.copy() if isinstance(extra_raw, dict) else {}
    #将 score 统一转为字符串
    if "score" in extra_data:
        extra_data["score"] = str(extra_data["score"])

    # 紧凑 JSON，无空格
    params["extra"] = json.dumps(extra_data, separators=(",", ":"))

    # 进行 URL 编码（使用 quote 而非 quote_plus，保留空格为 %20）
    query_string = urllib.parse.urlencode(params, quote_via=urllib.parse.quote)
    return query_string.encode("utf-8")

# @command("get")
# async def get_(self, event: AstrMessageEvent, author_in: str):
#     """获取指定作者的所有文章并保存到本地 JSON 文件,需要管理员权限
#     Args:
#         event: 消息事件对象
#         author_in: 作者名称
#     """
#     authors = await self.get_kv_data("authors", {})  # 这个是用来获取fakeid
#     write_data = []
#     fakeid = authors.get(author_in, "")  # type: ignore
#     logger.info(f"正在获取作者 {author_in} fakeid 为 {fakeid} 的文章列表...")
#     begin = 0  # 起始索引
#     num = 0  # 记录有效文章数量
#     while True:
#         async with aiohttp.ClientSession() as session:
#             headers = {"X-Auth-Key": self.config.get("exporter_auth_key")}
#             params = {"fakeid": fakeid, "begin": begin, "size": 20}
#             try:
#                 async with session.get(
#                     f"{self.config.get('exporter_api_url')}/api/public/v1/article",
#                     headers=headers,
#                     params=params,
#                 ) as resp:
#                     try:
#                         data = await resp.json()
#                         base_resp = data.get("base_resp")
#                         if base_resp and base_resp.get("err_msg") == "ok":
#                             # 处理成功响应
#                             articles = data.get("articles")
#                             logger.info(
#                                 f"第{begin} 获取到 {len(articles) if articles else 0} 篇文章"
#                             )
#                             if articles is None or len(articles) == 0:
#                                 break
#                             for article in articles:
#                                 is_deleted = article.get("is_deleted", False)
#                                 if is_deleted:  # 如果文章被删除了，就不保存
#                                     continue
#                                 write_data.append(article)  # 保存
#                                 num += 1
#                         else:
#                             # 处理失败响应
#                             logger.error(
#                                 f"❌ 获取{author_in}的文章失败: {data.get('base_resp').get('err_msg')}"
#                             )
#                         begin += 20
#                     except (ValueError, KeyError):
#                         logger.error("API 响应解析失败")
#                         break
#             except Exception:
#                 logger.error("获取公众号文章失败")
#                 break
#         logger.debug(f"第{begin}请求，已获取 {num} 篇有效文章")
#         # 休眠防止请求过快被封IP，间隔随机3-5秒
#         random_factor = random.uniform(3, 5)
#         delay = max(5, random_factor)  # 确保间隔至少为5秒
#         await asyncio.sleep(delay)
#     logger.info(f"共获取到 {num} 篇有效文章")

#     # 保存数据到本地JSON文件
#     # 1. 获取字符串路径，并显式转换为 Path 对象
#     data_dir_str = get_astrbot_data_path()
#     plugin_data_path = Path(data_dir_str) / "plugin_data" / self.name

#     # 2. 创建目录 (此时 plugin_data_path 是 Path 对象，所以 .mkdir() 可用)
#     plugin_data_path.mkdir(parents=True, exist_ok=True)
#     authors_file = plugin_data_path / f"{author_in}.json"
#     data = {"num": num, "articles": write_data}
#     # 3.尝试写入文件
#     try:
#         with authors_file.open("w", encoding="utf-8") as f:
#             json.dump(data, f, ensure_ascii=False, indent=4)
#     except Exception as e:
#         logger.error(f"写入 {author_in}.json 失败: {e}")
