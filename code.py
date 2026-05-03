import aiohttp
from lxml import etree  # type: ignore


async def parse_code(exporter_api_url, url: str)-> dict:
        """解析密令
        Args:
            exporter_api_url: 导出接口的基础URL
            url: 包含密令的URL
        Returns:
            dict: 包含解析结果的字典，格式如下：
            {
                "msg": "解析成功" 或 错误信息,
                "code": "解析到的密令，如果解析失败则为空字符串",
                "share": True 或 False，表示是否需要分享查看额外密令
            }
        """
        ret = {
             "msg": "",
             "code": "",
             "share": False
        }
        #获取url的html
        async with aiohttp.ClientSession() as session:
                params = {"url": url,"format": "html"}
                try:
                    async with session.get(
                        f"{exporter_api_url}/api/public/v1/download",
                        params=params,
                    ) as resp:
                        try:
                            data = await resp.text()
                            tree = etree.HTML(data)
                            spans = tree.xpath("//span/text()")
                            if "*温馨提示：只有上面那行红字是密令~" in spans:
                                index = spans.index("*温馨提示：只有上面那行红字是密令~")
                                code = spans[index-1]
                                ret["msg"] = "解析成功"
                                ret["code"] = code
                                return ret
                            elif "只有上面那行红字是密令~" in spans:
                                index = spans.index("只有上面那行红字是密令~")
                                if spans[index-1] == "*温馨提示：":
                                    code = spans[index-2]
                                    ret["msg"] = "解析成功"
                                    ret["code"] = code
                                    return ret
                            elif "*温馨提示：分享查看额外密令~" in spans:
                                index = spans.index("*温馨提示：分享查看额外密令~")
                                code = spans[index-1]
                                ret["msg"] = "解析成功"
                                ret["code"] = code
                                ret["share"] = True
                                return ret
                            elif "*温馨提示：分享本篇推文，可看到额外密令~" in spans:
                                index = spans.index("*温馨提示：分享本篇推文，可看到额外密令~")
                                code = spans[index-1]
                                ret["msg"] = "解析成功"
                                ret["code"] = code
                                ret["share"] = True
                                return ret
                            elif "*温馨提示：只有上面红字是密令~" in spans:
                                index = spans.index("*温馨提示：只有上面红字是密令~")
                                code1 = spans[index-1]
                                code2 = spans[index-2]
                                ret["msg"] = "解析成功"
                                ret["code"] = f"{code1}\n{code2}"
                                return ret
                            elif "*温馨提示：只有上面是密令~" in spans:
                                index = spans.index("*温馨提示：只有上面是密令~")
                                code = spans[index-1]
                                ret["msg"] = "解析成功"
                                ret["code"] = code
                                return ret
                        except Exception as e:
                             ret["msg"] = f"解析密令失败: {e}"
                             return ret
                except Exception as e:
                    ret["msg"] = f"请求解析密令接口失败: {e}"
                    return ret
        ret["msg"] = "未找到密令"
        return ret

