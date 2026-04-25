#sign_in.py
import base64

import aiohttp

api = "https://api.qingcigame.com"
app_id = "39"
page_id = "1"


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
    async with aiohttp.ClientSession() as session:
        async with session.get(url, params=params) as response:
            datas = await response.json()
            if datas.get("code") == 200:
                getID = ["data","39","android"]
                for key in getID:
                    datas = datas.get(key, {})
                    if not datas:
                        return None
                return datas
            else:
                return None


async def binds_account(headers,payload):
    """执行绑定请求
    Args:
        headers: 请求头
        payload: 请求体
    Returns:
        绑定结果的 JSON 数据
    """
    url = f"{api}/game/binds"
    async with aiohttp.ClientSession() as session:
        async with session.post(url,headers=headers, data=payload) as resp:
            data = await resp.json()
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
    # print(headers)
    async with aiohttp.ClientSession() as session:
        async with session.post(url,headers=headers, data=payload) as resp:
            data = await resp.json()
            return data
