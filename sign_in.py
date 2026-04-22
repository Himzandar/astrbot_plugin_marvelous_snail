#sign_in.py
import aiohttp

api = "https://api.qingcigame.com"
app_id = "39"
page_id = "1"

async def get_server(account: str):
    url = f"{api}/game/server"
    params = {
            "account": account,
            "app_id": app_id,
            "page_id": page_id,
        }
    async with aiohttp.ClientSession() as session:
        ret = []
        async with session.get(url, params=params) as response:
            datas = await response.json()
            if datas.get("code") == 200:
                getID = ["data","39","android"]
                for key in getID:
                    datas = datas.get(key, {})
                    if not datas:
                        return None
                #解析数据按指定格式存储
                for data in datas:
                    bindParams={
                        "game_id": 39,
                        "role_id": data["role_id"],
                        "role_name": data["role_name"],
                        "server_id": data["server_id"],
                        "server_name": data["server_name"],
                        "type": "android",
                        "platform": data["platform"],
                        "extra":
                        {
                            "zone": data["extra"]["zone"],
                            "account": data["extra"]["account"],
                            "token": data["extra"]["token"],
                            "score": data["extra"]["score"]
                        }
                    }
                    ret.append(bindParams)
                return ret
            else:
                return None


async def binds_account(account,headers,bindParams):
    url = f"{api}/game/binds"
    data = {"account": account, "page_id": page_id, **bindParams}
    print(type(headers))
    async with aiohttp.ClientSession() as session:
        async with session.post(url,cookies=headers, data=data) as resp:
            # 必须 await 读取响应内容，否则 resp.text() 只是一个协程对象
            data = await resp.json()
            return data
