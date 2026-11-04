import re

import aiohttp
from lxml import etree  # type: ignore

REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=30, connect=10)

# 密令只允许短的中文/字母/数字，避免把相邻的说明文字当成密令推送出去。
# 这里宁可从紧：取不到合法密令时按“未找到密令”处理，比把噪声文本群发出去安全。
CODE_MAX_LENGTH = 10
CODE_PATTERN = re.compile(r"^[\u4e00-\u9fffA-Za-z0-9]+$")
CODE_FORBIDDEN_WORDS = ("温馨提示", "密令", "分享", "点击", "关注", "领取")

# (警示语, 取值规则, 是否需要分享)。规则与原文案顺序一致，先匹配到的先生效。
#   prev     —— 取警示语前一个 span
#   prev_two —— 取警示语前两个 span（两行密令）
#   prefix   —— 要求警示语前一 span 是 "*温馨提示："，取再前一个 span
_MARKER_RULES: tuple[tuple[str, str, bool], ...] = (
    ("*温馨提示：只有上面那行红字是密令~", "prev", False),
    ("只有上面那行红字是密令~", "prefix", False),
    ("*温馨提示：分享查看额外密令~", "prev", True),
    ("*温馨提示：分享本篇推文，可看到额外密令~", "prev", True),
    ("*温馨提示：只有上面红字是密令~", "prev_two", False),
    ("*温馨提示：只有上面是密令~", "prev", False),
)


def _is_valid_code(text: str) -> bool:
    """判断候选文本是否像一个密令。

    Args:
        text: 候选文本。
    Returns:
        bool: 长度、字符集与关键词都合规时返回 True。
    """
    if not text or len(text) > CODE_MAX_LENGTH:
        return False
    if any(word in text for word in CODE_FORBIDDEN_WORDS):
        return False
    return bool(CODE_PATTERN.fullmatch(text))


def _pick_codes(candidates: list[str], *, join: bool = False) -> str:
    """从候选文本中挑出合法密令。

    Args:
        candidates: 候选文本列表，按页面顺序给出。
        join: 为 True 时把多条合法密令用换行拼接。
    Returns:
        str: 合法密令；没有合法候选时返回空字符串。
    """
    valid = [
        text for text in (item.strip() for item in candidates) if _is_valid_code(text)
    ]
    if join:
        return "\n".join(valid)
    return valid[0] if valid else ""


def extract_code(spans: list[str]) -> tuple[str, bool]:
    """从页面 span 文本中提取密令。

    解析完全依赖页面结构，必须容忍“警示语存在但相邻文本不是密令”的情况：
    取不到合法候选时返回空字符串，由调用方按“未找到密令”处理，绝不把噪声文本
    当成密令写库并群发。

    Args:
        spans: 按文档顺序排列的 span 文本。
    Returns:
        tuple[str, bool]: (密令文本, 是否需要分享才能看到额外密令)。
    """
    text_spans = [str(item).strip() for item in spans]
    if not text_spans:
        return "", False

    for marker, rule, share in _MARKER_RULES:
        try:
            index = text_spans.index(marker)
        except ValueError:
            continue

        if rule == "prev":
            if index < 1:
                continue
            code = _pick_codes([text_spans[index - 1]])
        elif rule == "prev_two":
            if index < 2:
                continue
            code = _pick_codes(
                [text_spans[index - 1], text_spans[index - 2]], join=True
            )
        else:  # prefix
            if index < 2 or text_spans[index - 1] != "*温馨提示：":
                continue
            code = _pick_codes([text_spans[index - 2]])

        if code:
            return code, share

    return "", False


async def parse_code(exporter_api_url, url: str) -> dict:
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
    ret = {"msg": "", "code": "", "share": False}
    # 获取url的html
    async with aiohttp.ClientSession(timeout=REQUEST_TIMEOUT) as session:
        params = {"url": url, "format": "html"}
        try:
            async with session.get(
                f"{exporter_api_url}/api/public/v1/download",
                params=params,
            ) as resp:
                if resp.status != 200:
                    ret["msg"] = f"解析密令接口返回 HTTP {resp.status}"
                    return ret
                try:
                    data = await resp.text()
                    tree = etree.HTML(data)
                    spans = tree.xpath("//span/text()")
                    code, share = extract_code(spans)
                    if code:
                        ret["msg"] = "解析成功"
                        ret["code"] = code
                        ret["share"] = share
                        return ret
                except Exception as e:
                    ret["msg"] = f"解析密令失败: {e}"
                    return ret
        except Exception as e:
            ret["msg"] = f"请求解析密令接口失败: {e}"
            return ret
    ret["msg"] = "未找到密令"
    return ret
