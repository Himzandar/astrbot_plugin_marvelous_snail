import asyncio
import json
from pathlib import Path

import jieba

from astrbot.api import logger
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


    async def get_author_all_title_and_link(self, plugin_data_path: Path,author: str):
        """
        获取作者的所有文章标题+简介和链接
        """
        #读取作者.json文件
        selected_author = author+".json"
        # 读取作者对应的文章数据
        try:
            with open(plugin_data_path / selected_author, encoding="utf-8") as f:
                author_data = json.load(f)
        except Exception as e:
            logger.error(f"读取 {selected_author} 失败: {e}")
            return None
        num = author_data.get("num", 0)
        articles = author_data.get("articles", [])
        if num == 0 or not articles:
            logger.warning(f"作者 {author} 没有文章数据")
            return None
        #这里要把标题和简介拼接在一起，并且要与链接关联起来，方便后续发送消息时使用
        result = []
        for article in articles:
            title = article.get("title", "")
            digest = article.get("digest", "")
            link = article.get("link", "")
            result.append({
                title+"digest:"+digest: link
            })
        return result

    def chinese_relevance_score(self, title, query):
        # 分词
        title_words = set(jieba.lcut(title))
        query_words = set(jieba.lcut(query))
        # 计算 Jaccard 相似度（交集大小 / 并集大小）
        intersection = title_words & query_words
        union = title_words | query_words
        if not union:
            return 0.0
        return len(intersection) / len(union)

    def search_chinese_relevance(self, data_dict, query):
        results = []
        for title, value in data_dict.items():
            score = self.chinese_relevance_score(title, query)
            if score > 0:
                results.append((title, value, score))
        results.sort(key=lambda x: x[2], reverse=True)
        return results

    async def parse_title_send_link(self,plugin_data_path: Path, author: str,parse_str:str):
        """解析文章标题并发送链接"""
        ret = {
            "msg": "",
            "data": {}
        }
        articles = await self.get_author_all_title_and_link(plugin_data_path, author)
        if articles is None or len(articles) == 0:
            msg = f"{author} 没有{parse_str}相关的文章"
            return {"msg": msg, "data": {}}
        data = self.search_chinese_relevance(articles, parse_str)

        article = articles[0]
        title_digest = list(article.keys())[0]
        link = article[title_digest]
        return {"title_digest": title_digest, "link": link}
    


