# sign_in.py
import asyncio
import random
import time
import urllib.parse

import aiohttp

from astrbot.api import logger

api = "https://api.qingcigame.com"
app_id = "39"
REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=30)
# 服务端不可用时的快速失败超时，避免每个角色都等满 30 秒。
DEGRADED_TIMEOUT = aiohttp.ClientTimeout(total=10, connect=5)
MAX_ATTEMPTS = 3
RETRY_BASE_DELAY = 1.0
RETRY_MAX_DELAY = 8.0
RETRYABLE_STATUS = {429, 500, 502, 503, 504}
# 连续失败这么多次后暂停重试，避免接口整体故障时把一次全量签到拖成数小时。
OUTAGE_THRESHOLD = 3
OUTAGE_COOLDOWN_SECONDS = 120
CHANNEL_BIND_URL = f"{api}/game/binds/channel"
CHANNEL_SIGN_SUPPORTED = True
CHANNEL_SIGN_PENDING_MESSAGE = "等待渠道服签到"
CHANNEL_GAME_ID = "39"
CHANNEL_PLATFORM_NAMES = {
    "bilibili": "B站",
    "huawei": "华为",
    "mi": "小米",
    "oppo": "OPPO",
    "vivo": "vivo",
    "honor": "荣耀",
}

_RETRY_STATE = {"failures": 0, "paused_until": 0.0}


def _reset_retry_state() -> None:
    """重置熔断状态，供测试与手动恢复使用。"""
    _RETRY_STATE["failures"] = 0
    _RETRY_STATE["paused_until"] = 0.0


def _retry_delay(attempt: int, retry_after: float | None = None) -> float:
    """计算第 attempt 次失败后的等待时间。

    Args:
        attempt: 已失败的次数，从 1 开始。
        retry_after: 服务端 Retry-After 提示的秒数。
    Returns:
        float: 等待秒数，带抖动，且不超过上限。
    """
    if retry_after is not None:
        return max(0.5, min(retry_after, RETRY_MAX_DELAY))
    delay = RETRY_BASE_DELAY * (2 ** (attempt - 1))
    return min(RETRY_MAX_DELAY, delay) * random.uniform(0.8, 1.2)


def _parse_retry_after(response) -> float | None:
    """读取响应头中的 Retry-After 秒数。

    Args:
        response: aiohttp 响应对象。
    Returns:
        float | None: 解析成功返回秒数，否则返回 None。
    """
    headers = getattr(response, "headers", None) or {}
    try:
        value = float(str(headers.get("Retry-After", "")).strip())
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _is_retry_paused() -> bool:
    """判断是否处于熔断冷却期。

    Returns:
        bool: 冷却期内返回 True。
    """
    return time.time() < _RETRY_STATE["paused_until"]


def _note_failure() -> None:
    """记录一次最终失败，必要时进入冷却期。"""
    _RETRY_STATE["failures"] += 1
    if _RETRY_STATE["failures"] >= OUTAGE_THRESHOLD:
        _RETRY_STATE["paused_until"] = time.time() + OUTAGE_COOLDOWN_SECONDS
        logger.error(
            f"连续 {_RETRY_STATE['failures']} 次请求失败，"
            f"暂停重试 {OUTAGE_COOLDOWN_SECONDS} 秒并使用快速失败超时"
        )


def _note_success() -> None:
    """记录一次成功，清空连续失败计数。"""
    _RETRY_STATE["failures"] = 0


async def _request_json(method: str, url: str, **kwargs):
    """发送请求并统一处理网络异常、超时、限流与 5xx 重试。

    单次抖动（5xx、超时）不再直接判定当日签到失败：可重试状态最多尝试
    MAX_ATTEMPTS 次，指数退避并尊重 Retry-After。连续失败达到阈值后进入
    冷却期，改用快速失败超时且不再重试，避免接口整体故障时把全量签到拖长。

    Args:
        method: HTTP 方法，如 "get" 或 "post"。
        url: 请求的 URL。
        **kwargs: 其他请求参数，如 headers、data 等。
    Returns:
        dict: 如果请求成功返回 JSON 数据，否则返回 None。
    """
    paused = _is_retry_paused()
    attempts = 1 if paused else MAX_ATTEMPTS
    timeout = DEGRADED_TIMEOUT if paused else REQUEST_TIMEOUT
    last_error = ""

    for attempt in range(1, attempts + 1):
        retry_after: float | None = None
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                request = getattr(session, method)
                async with request(url, **kwargs) as response:
                    status = response.status
                    if status == 200:
                        try:
                            payload = await response.json(content_type=None)
                        except ValueError as exc:
                            last_error = f"响应不是合法 JSON: {exc}"
                        else:
                            _note_success()
                            return payload
                    elif status in RETRYABLE_STATUS:
                        retry_after = _parse_retry_after(response)
                        body = await response.text()
                        last_error = f"HTTP {status}"
                        logger.warning(
                            f"请求 {url} 返回 HTTP {status}"
                            f"（第 {attempt}/{attempts} 次），响应: {body[:200]}"
                        )
                    else:
                        body = await response.text()
                        logger.error(
                            f"请求 {url} 失败，HTTP 状态码: {status}，响应: {body[:200]}"
                        )
                        return None
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            logger.warning(f"请求 {url} 失败（第 {attempt}/{attempts} 次）: {exc}")
        except Exception as exc:
            logger.error(f"请求 {url} 时出现未处理异常: {exc}")
            return None

        if attempt >= attempts:
            break
        await asyncio.sleep(_retry_delay(attempt, retry_after))

    _note_failure()
    if paused:
        logger.warning(f"请求 {url} 失败（熔断冷却中，未重试）: {last_error}")
    else:
        logger.error(f"请求 {url} 重试 {attempts} 次后仍失败: {last_error}")
    return None


async def get_server(account: str):
    """查询账号绑定的角色信息
    Args:
        account: 账号
    Returns:
        绑定的角色信息，如果查询失败返回 None
    """
    page_id = "1"
    url = f"{api}/game/server"
    params = {
        "account": account,
        "app_id": app_id,
        "page_id": page_id,
    }
    datas = await _request_json("get", url, params=params)
    if not isinstance(datas, dict):
        return None

    if datas.get("code") == 200:
        data_dict = datas.get("data", {})
        server_keys = [
            server_key for server_key in ("39", "26") if server_key in data_dict
        ]
        if not server_keys:
            logger.warning("查询账号角色时缺少字段: 39 或 26")
            return None

        merged_android_data = []
        for server_key in server_keys:
            server_data = data_dict.get(server_key, {})
            android_data = server_data.get("android")
            if not android_data:
                logger.warning(f"查询账号角色时缺少字段: android ({server_key})")
                continue

            for character in android_data:
                if isinstance(character, dict):
                    character["game_id"] = server_key
                    merged_android_data.append(character)

        if not merged_android_data:
            return None
        return merged_android_data

    logger.warning(f"查询账号角色失败: {datas.get('message', '未知错误')}")
    return None


async def binds_account(headers, payload):
    """执行绑定请求
    Args:
        headers: 请求头
        payload: 请求体
    Returns:
        绑定结果的 JSON 数据
    """
    url = f"{api}/game/binds"
    data = await _request_json("post", url, headers=headers, data=payload)
    if not isinstance(data, dict):
        return {"code": -1, "message": "绑定请求失败"}
    return data


async def binds_channel_account(
    headers,
    role_id: str,
    role_name: str,
    platform: str,
):
    """执行渠道服角色绑定请求。

    Args:
        headers: 与普通签到共用的请求头。
        role_id: 渠道服角色 ID。
        role_name: 渠道服角色昵称。
        platform: 渠道编码。
    Returns:
        绑定结果的 JSON 数据。
    """
    page_id = "1"
    params = {
        "app_id": app_id,
        "page_id": page_id,
        "role_id": role_id,
        "role_name": role_name,
        "platform": platform,
    }
    payload = urllib.parse.urlencode(params, quote_via=urllib.parse.quote).encode()
    data = await _request_json("post", CHANNEL_BIND_URL, headers=headers, data=payload)
    if not isinstance(data, dict):
        return {"code": -1, "message": "渠道服绑定请求失败"}
    return data


async def sign_request(headers, game_id: str = "39"):
    """执行每日签到请求
    Args:
        headers: 请求头
        game_id: 签到所属服务器的 game_id
    Returns:
        签到结果的 JSON 数据
    """
    url = f"{api}/game/sign/record"
    page_id = "1"
    payload = f"app_id={app_id}&page_id={page_id}&game_id={game_id}".encode()
    data = await _request_json("post", url, headers=headers, data=payload)
    if not isinstance(data, dict):
        return {"code": -1, "message": "签到请求失败"}
    return data


async def activity_gift_inquiry(headers, game_id, role_id):
    """活动礼包查询请求
    Args:
        headers: 请求头
        game_id: 查询所属服务器的 game_id
        role_id: 角色 ID
    Returns:
        活动礼包信息的 JSON 数据
    """
    week_page_id = "7"
    url = (
        f"{api}/game/package/list?area=QC-GAME&game_id={game_id}"
        f"&role_id={role_id}&page_id={week_page_id}&app_id={app_id}"
    )
    data = await _request_json("get", url, headers=headers)
    if not isinstance(data, dict):
        return {"code": -1, "message": "查询活动礼包信息请求失败"}
    return data


async def activity_gift_data_parse(activity_data):
    """解析活动礼包数据，提取礼包名称和领取状态
    Args:
        activity_data: 活动礼包的 JSON 数据
    Returns:
        包含礼包名称和领取状态的列表
    """
    if activity_data.get("code") != 200:
        logger.warning(f"活动礼包数据异常: {activity_data.get('message', '未知错误')}")
        return []

    data_payload = activity_data.get("data", {})
    if not isinstance(data_payload, dict):
        logger.warning(f"活动礼包 data 字段格式异常: {data_payload}")
        return []

    data_list = data_payload.get("list", [])
    if not isinstance(data_list, list):
        logger.warning(f"活动礼包 list 字段格式异常: {data_list}")
        return []

    parsed_activities = []
    for item in data_list:
        if isinstance(item, dict):
            name = item.get("name", "")
            gift_id = item.get("id", "")
            is_get = item.get("is_get", True)
            parsed_activities.append({"name": name, "id": gift_id, "is_get": is_get})
        else:
            logger.warning(f"活动礼包数据项格式异常: {item}")
    return parsed_activities


async def activity_gift_request(headers, activity_gift_datas, game_id: str = "39"):
    """活动礼包请求
    Args:
        headers: 请求头
        activity_gift_datas: 活动礼包数据列表，包含礼包 ID 和领取状态
        game_id: 查询所属服务器的 game_id
    Returns:
        活动礼包信息的 JSON 数据
    """
    activity_gift_page_id = "7"
    response_data = []
    if not activity_gift_datas:
        return {"code": -1, "message": "没有可领取的活动礼包"}
    for gift_data in activity_gift_datas:
        if gift_data.get("is_get") is False:
            package_id = gift_data.get("id")
            url = f"{api}/game/package"
            payload = (
                f"game_id={game_id}&package_id={package_id}"
                f"&page_id={activity_gift_page_id}&app_id={app_id}"
            ).encode()
            data = await _request_json("post", url, headers=headers, data=payload)
            if not isinstance(data, dict):
                response_data.append(
                    {
                        "code": -1,
                        "gift_name": gift_data.get("name", ""),
                        "message": f"领取礼包 {gift_data.get('name', '')} 请求失败",
                    }
                )
            else:
                response_data.append(
                    {
                        "code": data.get("code", -1),
                        "gift_name": gift_data.get("name", ""),
                        "message": (
                            f"<{gift_data.get('name', '')}>: "
                            f"{data.get('message', '未知错误')}"
                        ),
                    }
                )
    return response_data


async def activity_gift_claim(headers, game_id: str, role_id: str):
    """查询并领取当前角色的活动礼包。
    Args:
        headers: 请求头
        game_id: 查询所属服务器的 game_id
        role_id: 角色 ID
    Returns:
        包含领取结果的列表
    """
    inquiry_data = await activity_gift_inquiry(headers, game_id, role_id)
    if not isinstance(inquiry_data, dict):
        return [{"code": -1, "message": "查询活动礼包信息请求失败"}]

    if inquiry_data.get("code") != 200:
        return [
            {
                "code": inquiry_data.get("code", -1),
                "message": inquiry_data.get("message", "查询活动礼包信息请求失败"),
            }
        ]

    activity_gift_datas = await activity_gift_data_parse(inquiry_data)
    claimable_gifts = [
        gift_data
        for gift_data in activity_gift_datas
        if isinstance(gift_data, dict) and gift_data.get("is_get") is False
    ]
    if not claimable_gifts:
        return []

    response_data = await activity_gift_request(headers, claimable_gifts, game_id)
    if isinstance(response_data, list):
        return response_data
    if isinstance(response_data, dict):
        return [response_data]
    return [{"code": -1, "message": "领取活动礼包请求失败"}]
