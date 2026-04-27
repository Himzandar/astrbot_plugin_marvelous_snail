#sign_in.py
import base64

import aiohttp

from astrbot.api import logger

api = "https://api.qingcigame.com"
app_id = "39"
page_id = "1"
REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=30)


async def _request_json(method: str, url: str, **kwargs):
    """发送请求并统一处理网络异常、超时和非 200 响应。"""
    try:
        async with aiohttp.ClientSession(timeout=REQUEST_TIMEOUT) as session:
            request = getattr(session, method)
            async with request(url, **kwargs) as response:
                if response.status != 200:
                    body = await response.text()
                    logger.error(
                        f"请求 {url} 失败，HTTP 状态码: {response.status}，响应: {body[:200]}"
                    )
                    return None
                return await response.json(content_type=None)
    except aiohttp.ClientError as exc:
        logger.error(f"请求 {url} 失败: {exc}")
    except Exception as exc:
        logger.error(f"请求 {url} 时出现未处理异常: {exc}")
    return None


async def get_server(account: str):
    """查询账号绑定的角色信息
    Args:
        account: 账号
    Returns:
        绑定的角色信息，如果查询失败返回 None
    """
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
        get_keys = ["data", "39", "android"]
        for key in get_keys:
            datas = datas.get(key, {})
            if not datas:
                logger.warning(f"查询账号角色时缺少字段: {key}")
                return None
        return datas

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

async def sign_request(headers):
    """执行签到请求
    Args:
        headers: 请求头
    Returns:
        签到结果的 JSON 数据
    """
    url = f"{api}/game/sign/record"
    payload = base64.b64decode("YXBwX2lkPTM5JnBhZ2VfaWQ9MSZnYW1lX2lkPTM5")
    data = await _request_json("post", url, headers=headers, data=payload)
    if not isinstance(data, dict):
        return {"code": -1, "message": "签到请求失败"}
    return data
