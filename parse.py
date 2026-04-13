import asyncio

from astrbot.api.event import AstrMessageEvent
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import (
    AiocqhttpMessageEvent,
)


class Parse:
    def __init__(self):
        pass

    @staticmethod
    async def send_msg(event: AiocqhttpMessageEvent, payloads: dict) -> int | None:
        if event.is_private_chat():
            payloads["user_id"] = event.get_sender_id()
            result = await event.bot.api.call_action("send_private_msg", **payloads)
        else:
            payloads["group_id"] = event.get_group_id()
            result = await event.bot.api.call_action("send_group_msg", **payloads)
        return result.get("message_id")

    async def send_authors_selection(self, event: AstrMessageEvent, authors: list[str]) -> None:
        """
        发送作者选择消息
        """
        formatted_authors = [
            f"{index + 1}. {author}"
            for index, author in enumerate(authors)
        ]
        formatted_authors.insert(0, "需要获取谁的文章详情？请回复编号选择：")
        msg = "\n".join(formatted_authors)
        if isinstance(event, AiocqhttpMessageEvent):
            payloads = {"message": [{"type": "text", "data": {"text": msg}}]}
            message_id = await self.send_msg(event, payloads)
            if message_id and 10:
                await asyncio.sleep(10)
                await event.bot.delete_msg(message_id=message_id)
        else:
            await event.send(event.plain_result(msg))

    async def send_article_details(self, event: AstrMessageEvent, article: dict) -> None:
        """
        发送文章详情
        """
        author = article.get("author_name", "")
        title = article.get("title", "")
        digest = article.get("digest", "")
        link = article.get("link", "")
        await event.send(event.plain_result(link))
        await event.send(event.plain_result(f"作者: {author}\n标题: {title}\n简介: {digest}"))
