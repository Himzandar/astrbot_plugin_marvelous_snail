import json
from pathlib import Path

import jieba

from astrbot.api import logger


class Parse:
    def __init__(self):
        pass

    async def get_author_all_title_and_link(self, plugin_data_path: Path, author: str):
        """获取作者的所有文章标题+简介和链接
        Args:
            plugin_data_path: 插件数据路径
            author: 作者名称
        Returns:
            包含标题+简介和链接的字典，键为标题+简介，值为链接
        """
        #读取作者.json文件
        selected_author = f"{author}.json"
        author_file = plugin_data_path / selected_author
        if not author_file.exists():
            logger.warning(f"作者缓存文件不存在: {selected_author}")
            return {}

        # 读取作者对应的文章数据
        try:
            with author_file.open(encoding="utf-8") as f:
                author_data = json.load(f)
        except Exception as e:
            logger.error(f"读取 {selected_author} 失败: {e}")
            return {}

        if not isinstance(author_data, dict):
            logger.error(f"作者缓存文件格式无效: {selected_author}")
            return {}

        num = author_data.get("num", 0)
        articles = author_data.get("articles", [])
        if num == 0 or not articles:
            logger.warning(f"作者 {author} 没有文章数据")
            return {}
        #这里要把标题和简介拼接在一起，并且要与链接关联起来，方便后续发送消息时使用
        result = {}
        for article in articles:
            if not isinstance(article, dict):
                continue
            title = article.get("title", "")
            digest = article.get("digest", "")
            link = article.get("link", "")
            if not title or not link:
                continue
            result[f"{title}digest:{digest}"] = link
        return result

    def chinese_relevance_score(self, title, query):
        """计算两个中文字符串的相关度分数，使用 Jaccard 相似度
        Args:
            title: 标题字符串
            query: 查询字符串
        Returns:
            相关度分数，范围为0到1
        """
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
        """根据中文相关度对数据字典进行搜索和排序
        Args:
            data_dict: 数据字典，键为标题，值为链接
            query: 查询字符串
        Returns:            按相关度排序的结果列表，元素为 (标题, 链接, 相关度分数) 的元组
        """
        if not isinstance(data_dict, dict):
            logger.warning("搜索攻略时未获得有效的文章索引")
            return []

        results = []
        for title, value in data_dict.items():
            score = self.chinese_relevance_score(title, query)
            if score > 0:
                results.append((title, value, score))
        results.sort(key=lambda x: x[2], reverse=True)
        return results

    async def parse_title_send_link(
        self, plugin_data_path: Path, author: str, parse_str: str
    ):
        """解析文章标题并发送链接
        Args:
            plugin_data_path: 插件数据路径
            author: 作者名称
            parse_str: 要解析的字符串
        """
        ret = {"msg": "", "data": {}}
        articles = await self.get_author_all_title_and_link(plugin_data_path, author)
        if not articles:
            msg = f"{author} 暂无可搜索的攻略数据"
            logger.info(msg)
            return {"msg": msg, "data": {}}

        data = self.search_chinese_relevance(articles, parse_str)
        if data is None or len(data) == 0:
            msg = f"{author} 没有{parse_str}相关的攻略"
            logger.info(msg)
            return {"msg": msg, "data": {}}
        ret["msg"] = f"{author}:{parse_str}相关攻略，共{len(data)}条，请回复编号选择："

        for title, link, _score in data:
            ret["data"][title] = link
        return ret

    async def Paging_strategies(self, strategies: dict, page_size: int = 5):
        """分页攻略列表
        Args:
            strategies (dict): 攻略字典，键为标题，值为链接
            page_size (int): 每页显示的攻略数量
        """
        #计算总页数
        total_pages = (len(strategies) + page_size - 1) // page_size
        #生成每页的攻略列表
        pages_data = []
        pages_msg = []
        for page in range(total_pages):
            start_index = page * page_size
            end_index = start_index + page_size
            page_strategies = list(strategies.items())[start_index:end_index]
            formatted_strategies = [
                f"{tid + 1}. {title}"
                for tid, (title, _) in enumerate(page_strategies)
            ]
            #记录编号与文章对应关系 并 增加上下页选项
            line_data = {}
            for tid, (title, link) in enumerate(page_strategies):
                line_data[tid + 1] = (title, link)
            if page > 0:
                formatted_strategies.append(f"{len(line_data)+1}. 上一页")
                line_data[len(line_data) + 1] = "上一页"
            if page < total_pages - 1:
                formatted_strategies.append(f"{len(line_data)+1}. 下一页")
                line_data[len(line_data) + 1] = "下一页"

            formatted_strategies.insert(0, f"--- 第 {page + 1} 页 / 共 {total_pages} 页 ---")
            msg = "\n".join(formatted_strategies).replace("digest:", "")
            pages_data.append(line_data)
            pages_msg.append(msg)
        return pages_msg, pages_data
