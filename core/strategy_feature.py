import asyncio
import json
import random
import time
from typing import TYPE_CHECKING, Any

import aiohttp

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, MessageChain
from astrbot.core.platform import MessageType as PlatformMessageType
from astrbot.core.utils.session_waiter import SessionController, session_waiter

from .code import parse_code

if TYPE_CHECKING:
    # 避免循环导入导致的类型检查问题，实际运行时 StrategyFeatureBase 会被正确替换为 MarvelousSnailPluginBase
    from .plugin_base import MarvelousSnailPluginBase as StrategyFeatureBase
else:
    # 在运行时，StrategyFeatureBase 将被定义为一个空类，避免导入错误
    class StrategyFeatureBase:
        pass


class StrategyFeatureMixin(StrategyFeatureBase):
    """最强蜗牛攻略功能类，提供了与攻略相关的核心功能实现，包括获取最新文章、发送更新通知、搜索和选择攻略等。"""

    STRATEGY_SYNC_WINDOW_SECONDS = 7 * 24 * 60 * 60

    @staticmethod
    def _get_strategy_article_time(article: dict[str, Any]) -> int | None:
        """获取攻略文章的时间戳，优先使用 update_time 字段，如果没有则使用 create_time 字段。
        Args:
            article: 文章信息字典，包含 update_time 和 create_time 字段。
        Returns:
            int | None: 返回文章的时间戳，如果无法获取则返回 None。
        """
        article_time = article.get("update_time","") or article.get("create_time","")
        try:
            timestamp = int(article_time)
        except (TypeError, ValueError):
            return None
        if timestamp > 10_000_000_000:
            timestamp //= 1000
        return timestamp

    @staticmethod
    def _friend_message_only_error(
        event: AstrMessageEvent,
        command_text: str,
    ) -> str | None:
        """检查消息是否来自私聊，如果不是则返回错误提示文本。
        Args:
            event: 消息事件对象。
            command_text: 命令文本。
        Returns:
            str | None: 如果消息不是来自私聊，返回错误提示文本，否则返回 None。
        """
        if event.get_message_type() == PlatformMessageType.FRIEND_MESSAGE:
            return None
        return f"⚠️ 该指令仅限私聊使用。\n请私聊发送“{command_text}”。"

    async def _notify_strategy_article_update(
        self,
        name: str,
        article: dict[str, Any],
    ) -> None:
        """当作者发布新文章时，发送更新通知给用户。
        Args:
            name: 作者名称。
            article: 文章信息字典，包含标题、简介和链接等。
        Returns:
            None
        """
        title = str(article.get("title", ""))
        digest = str(article.get("digest", ""))
        link = str(article.get("link", ""))
        await self._send_message(
            f"作者: {name}\n文章标题: {title}\n文章简介: {digest}\n链接: {link}"
        )
        if name != "最强蜗牛":
            return

        code_info = await self.get_code(link)
        code = code_info.get("code")
        if not code:
            return

        send_txt = f"密令:{code}"
        if code_info.get("share") and digest:
            send_txt += f"\n{digest}"
            self.write_codes(digest.split("密令：")[-1])
        await self._send_message(send_txt)

    async def search_public_account_impl(
        self, event: AstrMessageEvent, keyword: str = "最强蜗牛", size: int = 5
    ):
        """搜索公众号作者实现函数，支持搜索“最强蜗牛”公众号作者并返回结果列表。
        Args:
            event: 消息事件对象。
            keyword: 搜索关键词，默认为“最强蜗牛”。
            size: 返回结果数量，默认为 5。
        Returns:
            异步生成器，返回搜索结果。
        """
        if error_text := self._friend_message_only_error(event, "最强蜗牛 作者搜索"):
            yield event.plain_result(error_text)
            return
        if not self._check_config():
            yield event.plain_result("❌ 插件未配置 API 地址或密钥，请联系管理员")
            return

        if keyword != "最强蜗牛":
            yield event.plain_result("❌ 目前仅支持搜索“最强蜗牛”公众号作者")
            return

        async with aiohttp.ClientSession() as session:
            headers = {"X-Auth-Key": self.config.get("exporter_auth_key")}
            params = {"keyword": keyword, "size": size}
            try:
                async with session.get(
                    f"{self.config.get('exporter_api_url')}/api/public/v1/account",
                    headers=headers,
                    params=params,
                ) as resp:
                    try:
                        data = await resp.json()
                        base_resp = data.get("base_resp")
                        if base_resp and base_resp.get("err_msg") == "ok":
                            data_list = data.get("list", [])
                            index = 1
                            result = "搜索结果:"
                            authors = await self.get_kv_data("authors", {})
                            if not isinstance(authors, dict):
                                logger.warning(
                                    "authors 存储数据格式异常，已回退为空字典"
                                )
                                authors = {}
                            for item in data_list:
                                name = item.get("nickname")
                                if name in authors.keys():  # type: ignore
                                    continue
                                fakeid = item.get("fakeid")
                                result += f"\n{index}: {name}"
                                self.authors[index] = {
                                    "name": name,
                                    "fakeid": fakeid,
                                }
                                index += 1
                            if index == 1:
                                yield event.plain_result("❌ 未找到可添加的公众号作者")
                                return
                            yield event.plain_result(result)
                        else:
                            err_msg = self._get_base_resp_error(data)
                            logger.warning("搜索公众号作者失败: %s", err_msg)
                            yield event.plain_result(f"❌ 搜索失败: {err_msg}")
                    except (ValueError, KeyError) as e:
                        logger.error(f"API 响应解析失败: {e}")
            except Exception as e:
                logger.error(f"搜索失败: {e}")

    async def add_saved_account_impl(self, event: AstrMessageEvent, index: str):
        """添加已保存的公众号作者。
        Args:
            event: 消息事件对象。
            index: 作者索引。
        Returns:
            异步生成器，返回操作结果。
        """
        if error_text := self._friend_message_only_error(event, "最强蜗牛 作者添加"):
            yield event.plain_result(error_text)
            return
        authors = await self.get_kv_data("authors", {})
        try:
            data = self.authors.get(int(index))
        except ValueError:
            yield event.plain_result("❌ 无效的索引，请输入数字")
            return
        if not data:
            yield event.plain_result("❌ 无效的索引，请先使用 zqwn 命令搜索公众号作者")
            return
        name = data.get("name")
        fakeid = data.get("fakeid")
        authors[name] = fakeid  # type: ignore
        await self.put_kv_data("authors", authors)
        yield event.plain_result(f"✅ 已添加作者: {name}")

    async def del_saved_account_impl(self, event: AstrMessageEvent, name: str):
        """删除已保存的公众号作者。
        Args:
            event: 消息事件对象。
            name: 作者名称。
        Returns:
            异步生成器，返回操作结果。
        """
        if error_text := self._friend_message_only_error(event, "最强蜗牛 作者删除"):
            yield event.plain_result(error_text)
            return
        authors = await self.get_kv_data("authors", {})
        articles = await self.get_kv_data("articles", {})
        if name not in authors.keys():  # type: ignore
            yield event.plain_result(
                "❌ 无效的名字，请先使用 zqwn_list 命令查看已保存的作者列表"
            )
            return

        if name in articles.keys():  # type: ignore
            del articles[name]  # type: ignore
            await self.put_kv_data("articles", articles)
        del authors[name]  # type: ignore
        await self.put_kv_data("authors", authors)
        yield event.plain_result(f"✅ 已删除作者: {name}")

    async def list_saved_accounts_impl(self, event: AstrMessageEvent):
        """列出已保存的公众号作者。
        Args:
            event: 消息事件对象。
        Returns:
            异步生成器，返回已保存的作者列表。
        """
        if error_text := self._friend_message_only_error(event, "最强蜗牛 作者列表"):
            yield event.plain_result(error_text)
            return
        authors = await self.get_kv_data("authors", {})
        if not authors or len(authors) == 0:
            yield event.plain_result("❌ 请先使用 zqwn 命令搜索公众号作者")
            return

        result = "已保存的作者列表:"
        for name in authors.keys():
            result += f"\n- {name}"

        yield event.plain_result(result)

    async def _sync_author_articles(
        self, author: str, fakeid: str
    ) -> list[dict[str, Any]] | None:
        """同步作者文章实现函数，获取指定作者的文章列表。
        Args:
            author: 作者名称。
            fakeid: 作者的唯一标识。
        Returns:
            list[dict[str, Any]] | None: 返回文章列表，如果同步失败返回 None。
        """
        if not self._check_config() or not fakeid:
            return None

        fetched_articles: list[dict[str, Any]] = []
        begin = 0
        page_size = 20
        cutoff_time = int(time.time()) - self.STRATEGY_SYNC_WINDOW_SECONDS
        headers = {"X-Auth-Key": self.config.get("exporter_auth_key")}
        api_url = self.config.get("exporter_api_url")

        async with aiohttp.ClientSession() as session:
            while True:
                reached_cutoff = False
                params = {"fakeid": fakeid, "begin": begin, "size": page_size}
                try:
                    async with session.get(
                        f"{api_url}/api/public/v1/article",
                        headers=headers,
                        params=params,
                    ) as resp:
                        if resp.status != 200:
                            logger.warning(
                                f"同步作者 {author} 文章失败，HTTP 状态码: {resp.status}"
                            )
                            return None

                        data = await resp.json(content_type=None)
                except Exception as e:
                    logger.error(f"同步作者 {author} 文章失败: {e}")
                    return None

                base_resp = data.get("base_resp") if isinstance(data, dict) else None
                if not base_resp or base_resp.get("err_msg") != "ok":
                    err_msg = self._get_base_resp_error(data)
                    logger.warning("同步 %s 的文章失败: %s", author, err_msg)
                    return None

                articles = data.get("articles", [])
                if not isinstance(articles, list) or len(articles) == 0:
                    break

                for article in articles:
                    if not isinstance(article, dict):
                        continue
                    if article.get("author_name") == "广告":
                        continue
                    article_time = self._get_strategy_article_time(article)
                    if article_time is not None and article_time < cutoff_time:
                        reached_cutoff = True
                        continue
                    fetched_articles.append(article)

                if reached_cutoff:
                    logger.debug("作者 %s 已同步到一周前文章，停止继续翻页", author)
                    break
                if len(articles) < page_size:
                    break
                begin += page_size
                await asyncio.sleep(random.uniform(1, 3))

        await self.save_strategy(author, fetched_articles, synced_at=int(time.time()))
        return fetched_articles

    async def get_saved_account(self):
        """获取已保存的公众号作者列表。
        Returns:
            dict: 已保存的作者字典，键为作者名称，值为作者的唯一标识。
        """
        authors = await self.get_kv_data("authors", {}) or {}
        if not isinstance(authors, dict) or len(authors) == 0:
            return
        old_articles = await self.get_kv_data("articles", {})
        if not isinstance(old_articles, dict) or not old_articles:
            old_articles = {}
        new_articles = {}
        updata_flag = False
        for name, fakeid in authors.items():
            logger.debug(f"正在获取作者 {name} 的文章列表...")
            fetched_articles = await self._sync_author_articles(name, fakeid)
            if fetched_articles is None:
                continue

            article = self._get_latest_strategy_article(fetched_articles)
            if article is None:
                logger.debug(f"❌ 作者 {name} 没有可用文章")
                continue

            aid = article.get("aid")
            link = str(article.get("link", ""))
            if not link:
                logger.warning(f"作者 {name} 的最新文章缺少链接，已跳过推送")
                continue
            if name in old_articles.keys():
                old_aid = old_articles[name].get("aid")
                if old_aid == aid:
                    logger.debug(f"✅ 作者 {name} 未更新")
                    new_articles[name] = old_articles[name]  # type: ignore
                else:
                    updata_flag = True
                    new_articles[name] = article
                    logger.debug(
                        f"✅ 作者 {name} old_aid: {old_aid} aid: {aid} 发布了新文章: {article.get('title')}\n链接: {link}"
                    )
                    await self._notify_strategy_article_update(name, article)
            else:
                updata_flag = True
                new_articles[name] = article
                logger.debug(
                    f"✅ 作者 {name} aid: {aid} 发布了新文章: {article.get('title')}\n链接: {link}"
                )
                await self._notify_strategy_article_update(name, article)
            base_delay = 6
            random_factor = random.uniform(-5, 5)
            delay = max(5, base_delay + random_factor)
            logger.debug(f"等待 {delay:.2f} 秒后继续获取下一个作者的文章...")
            await asyncio.sleep(delay)
        if not updata_flag:
            logger.debug("没有新的文章更新")
        else:
            await self.put_kv_data("articles", new_articles)

    async def _send_message(self, message: str):
        """发送消息给已配置的推送用户。
        Args:
            message: 要发送的消息内容。
        Returns:
            None
        """
        try:
            data = self.read_file("push_datas", "strategy.json")
            users = data.get("datas", []) if data else []
            if not users or len(users) == 0:
                logger.warning("未配置推送用户，无法发送私聊消息")
                return
            for user in users:
                message_chain = MessageChain().message(message)
                try:
                    await self.context.send_message(user, message_chain)  # type: ignore
                    logger.info(f"已发送消息给用户 {user}: {message}")
                except Exception as e:
                    logger.error(f"发送消息给用户 {user} 失败: {e}")
        except Exception as e:
            logger.error(f"发送消息失败: {e}")

    async def get_push_list_impl(self, event: AstrMessageEvent):
        """获取当前推送用户列表。
        Args:
            event: 消息事件对象。
        Returns:
            异步生成器，返回推送用户列表。
        """
        if error_text := self._friend_message_only_error(
            event, "最强蜗牛 攻略推送列表"
        ):
            yield event.plain_result(error_text)
            return
        data = self.read_file("push_datas", "strategy.json")
        if not data:
            yield event.plain_result("❌ 未配置推送用户")
            return
        push_list = data.get("datas", [])
        if push_list:
            msg = "\n".join(push_list)
            yield event.plain_result(f"✅ 当前推送用户: {msg}")
        else:
            yield event.plain_result("❌ 没有开启自动推送的用户")

    async def push_zqwn_impl(self, event: AstrMessageEvent, enabled: str):
        """开启或关闭攻略推送功能。
        Args:
            event: 消息事件对象。
            enabled: "开启" 或 "关闭"。
        Returns:
            None
        """
        group_id = getattr(event.message_obj, "group_id", None)
        user_name = event.get_sender_name()
        uid = group_id
        if not group_id or group_id == 0:
            uid = user_name
        data = self.read_file("push_datas", "strategy.json")
        if not data:
            data = {"datas": []}
        if enabled not in ["开启", "关闭"]:
            yield event.plain_result(
                "❌ 参数错误，请使用：最强蜗牛 攻略推送 开启 或 最强蜗牛 攻略推送 关闭"
            )
            return
        if enabled == "开启":
            if event.unified_msg_origin in data["datas"]:
                yield event.plain_result(f"✅ {uid} 已经开启自动推送，无需重复设置")
                return
            data["datas"].append(event.unified_msg_origin)
            yield event.plain_result(f"✅ {uid} 已开启自动推送")
        else:
            if event.unified_msg_origin not in data["datas"]:
                yield event.plain_result(f"✅ {uid} 已经关闭自动推送，无需重复设置")
                return
            data["datas"].remove(event.unified_msg_origin)
            yield event.plain_result(f"✅ {uid} 已关闭自动推送")
        self.write_file("push_datas", "strategy.json", data)

    async def save_strategy(
        self,
        authors: str,
        write_data: Any,
        *,
        synced_at: int | None = None,
    ) -> None:
        """保存攻略数据。
        Args:
            authors: 作者名称。
            write_data: 要保存的攻略数据。
            synced_at: 同步时间戳，可选。
        Returns:
            None
        """
        plugin_data_path = self._get_author_cache_dir()
        plugin_data_path.mkdir(parents=True, exist_ok=True)
        authors_file = plugin_data_path / f"{authors}.json"

        incoming_articles = []
        if isinstance(write_data, dict):
            incoming_articles = [write_data]
        elif isinstance(write_data, list):
            incoming_articles = [item for item in write_data if isinstance(item, dict)]

        if not incoming_articles and not authors_file.exists() and synced_at is None:
            logger.warning("作者 %s 没有可写入的文章数据", authors)
            return

        existing_articles: list[dict[str, Any]] = []
        if authors_file.exists():
            try:
                with authors_file.open("r", encoding="utf-8") as f:
                    data = json.load(f)
                    if not isinstance(data, dict):
                        logger.warning("%s 数据格式异常，已重建文件", authors_file)
                        data = {}
                    articles = data.get("articles", [])
                    if not isinstance(articles, list):
                        logger.warning(
                            "%s articles 字段格式异常，已重建列表", authors_file
                        )
                        articles = []
                    existing_articles = articles
            except Exception as e:
                logger.error(f"读取 {authors}.json 失败，使用回退数据继续写入: {e}")
        merged_articles = self._merge_author_articles(
            existing_articles, incoming_articles
        )
        data = {
            "synced_at": synced_at if synced_at is not None else int(time.time()),
            "num": len(merged_articles),
            "articles": merged_articles,
        }
        try:
            with authors_file.open("w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
        except Exception as e:
            logger.error(f"写入 {authors}.json 失败: {e}")

    async def get_strategy_impl(self, event: AstrMessageEvent, parse_str: str):
        """获取攻略实现函数，支持用户选择作者和文章进行查询。
        Args:
            event: 消息事件对象。
            parse_str: 要解析的字符串。
        Returns:
            None
        """
        user_stage = "select_author"
        selected_author = None
        strategy_map: dict[int, tuple[str, str]] = {}
        plugin_data_path = self._get_author_cache_dir()
        if not plugin_data_path.exists():
            logger.info("攻略缓存目录不存在，当前没有可查询数据")
            await event.send(event.plain_result("❌ 暂无数据存储"))
            return
        json_files = list(plugin_data_path.glob("*.json"))
        authors = [file.stem for file in json_files]
        if not authors or len(authors) == 0:
            logger.info("没有已保存的作者和文章数据，请先添加作者并等待更新")
            await event.send(event.plain_result("❌ 暂无数据存储"))
            return
        await self._send_markdown_card(
            event,
            self._render_author_selection_markdown(authors),
        )
        group_id = getattr(event.message_obj, "group_id", None)
        user_id = None
        if group_id and group_id != 0:
            user_id = event.get_sender_id().replace("/", "_")

        @session_waiter(timeout=60)
        async def articles_waiter(
            controller: SessionController, event: AstrMessageEvent
        ):
            """等待用户选择文章的回调函数，处理用户输入并返回对应的攻略链接。
            Args:
                controller: 会话控制器对象。
                event: 消息事件对象。
            Returns:
                None
            """
            nonlocal user_stage, selected_author, strategy_map
            now_user_id = event.get_sender_id().replace("/", "_")
            if user_id and now_user_id != user_id:
                return
            arg = event.message_str.strip()
            parts = arg.split()
            if len(parts) == 0:
                logger.debug("攻略选择流程收到空输入，继续等待用户响应")
                return
            if self._is_exit_command(arg):
                await event.send(event.plain_result("✅ 已退出攻略查询流程"))
                controller.stop()
                return

            if user_stage == "select_author":
                index = 0
                if len(parts) == 1 and parts[0].isdigit():
                    index = int(parts[0])
                if index < 1 or index > len(authors):
                    return
                selected_author = authors[index - 1]
                result = await self.parse.parse_title_send_link(
                    plugin_data_path, selected_author, parse_str
                )
                if not result or not result.get("data"):
                    message = (
                        result.get("msg", f"❌ 作者 {selected_author} 没有文章数据")
                        if isinstance(result, dict)
                        else f"❌ 作者 {selected_author} 没有文章数据"
                    )
                    await event.send(
                        event.plain_result(
                            f"{message}\n请重新选择作者，或回复 退出 结束流程"
                        )
                    )
                    await self._send_markdown_card(
                        event,
                        self._render_author_selection_markdown(authors),
                    )
                    controller.keep(timeout=60, reset_timeout=True)
                    return
                user_stage = "select_article"
                results = result["data"]
                strategy_map = {
                    idx: (item.get("title", ""), item.get("link", ""))
                    for idx, item in enumerate(results, start=1)
                    if isinstance(item, dict)
                }
                await self._send_markdown_card(
                    event,
                    self._render_strategy_search_markdown(
                        selected_author,
                        parse_str,
                        results,
                    ),
                )
                controller.keep(timeout=60, reset_timeout=True)
            elif user_stage == "select_article":
                select_article_id = 0
                if len(parts) == 1 and parts[0].isdigit():
                    select_article_id = int(parts[0])
                else:
                    return
                if select_article_id < 1 or select_article_id > len(strategy_map):
                    return
                selected = strategy_map.get(select_article_id)
                if not selected:
                    return
                _title, link = selected
                await event.send(event.plain_result(link))
                controller.stop()
                return

        try:
            await articles_waiter(event)
        except TimeoutError:
            logger.warning("选择超时！")
            await event.send(event.plain_result("❌ 选择超时，终止运行"))
        except Exception as e:
            logger.error("选择发生错误" + str(e))
        event.stop_event()

    async def get_fugitives_impl(self, event: AstrMessageEvent, name: str):
        """获取特工逃犯信息实现函数，支持用户查询特工逃犯的奖励信息。
        Args:
            event: 消息事件对象。
            name: 逃犯名称。
        Returns:
            异步生成器，返回特工逃犯信息。
        """
        keyword = name.strip()
        if not keyword:
            yield event.plain_result(
                "❌ 请输入逃犯名称，例如：最强蜗牛 特工逃犯 白雪公主"
            )
            return

        data = self._load_fugitives_data()
        if not data:
            yield event.plain_result("❌ 逃犯数据不存在")
            return
        fugitives = data.get("fugitives", [])
        if not isinstance(fugitives, list):
            yield event.plain_result("❌ 逃犯数据格式错误")
            return

        exact_matches = [item for item in fugitives if item.get("name") == keyword]
        fuzzy_matches = [
            item
            for item in fugitives
            if isinstance(item, dict) and keyword in str(item.get("name", ""))
        ]
        matches = exact_matches or fuzzy_matches

        if not matches:
            fallback = data.get(
                "not_found_message",
                "未收录该逃犯，代表没有特殊奖励，可以直接打特工。",
            )
            yield event.plain_result(f"未收录逃犯“{keyword}”。{fallback}")
            return

        if not exact_matches and len(matches) > 1:
            names = "、".join(str(item.get("name", "未知")) for item in matches)
            yield event.plain_result(
                f"找到多个匹配项：{names}\n请提供更完整的逃犯名称。"
            )
            return

        yield event.plain_result(self._format_fugitive_result(matches[0]))

    async def get_code(self, link: str):
        """获取密令实现函数，支持用户解析密令链接。
        Args:
            link: 密令链接。
        Returns:
            异步生成器，返回解析结果。
        """
        ret = {"code": "", "share": False}
        exporter_api_url = self.config.get("exporter_api_url")
        parse_code_result = await parse_code(exporter_api_url, link)
        if parse_code_result.get("msg") == "解析成功":
            code = parse_code_result["code"]
            ret["code"] = code
            self.write_codes(code)
            logger.info(f"解析密令成功: {code}")
            if parse_code_result["share"]:
                ret["share"] = True
            return ret

        self.write_code_error(link)
        logger.info(f"解析密令失败: {parse_code_result.get('msg')},链接: {link}")
        return ret

    def write_codes(self, code: str):
        """将解析到的密令写入本地文件，保存最近两个月内的密令数据。
        Args:
            code: 解析到的密令。
        Returns:
            None
        """
        data = {"num": 0, "code": {}}
        codes_dir = self.data_dir / "codes"
        codes_dir.mkdir(parents=True, exist_ok=True)
        codes_file = codes_dir / "codes.json"
        codes = {}
        if codes_file.exists():
            try:
                with codes_file.open("r", encoding="utf-8") as f:
                    data = json.load(f)
                    codes = data.get("code", {})
            except Exception as e:
                logger.error(f"读取原有密令数据失败: {e}")
        timestamp = int(time.time())
        month_str = time.strftime("%Y-%m", time.localtime(timestamp))
        codes[code] = month_str
        codes = self.delete_past_code(codes)
        data["code"] = codes
        data["num"] = len(codes)
        try:
            with codes_file.open("w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
            logger.info(f"已将密令写入 {codes_file}")
        except Exception as e:
            logger.error(f"写入密令失败: {e}")

    def write_code_error(self, link: str):
        """将解析失败的密令链接写入本地文件。
        Args:
            link: 解析失败的密令链接。
        Returns:
            None
        """
        data = {"urls": []}
        codes_dir = self.data_dir / "codes"
        codes_dir.mkdir(parents=True, exist_ok=True)
        code_error_file = codes_dir / "code_error.json"
        urls = []
        if code_error_file.exists():
            try:
                with code_error_file.open("r", encoding="utf-8") as f:
                    data = json.load(f)
                    urls = data.get("urls", [])
            except Exception as e:
                logger.error(f"读取原有解析失败链接数据失败: {e}")
        urls.append(link)
        data["urls"] = urls
        try:
            with code_error_file.open("w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
            logger.info(f"已将解析失败的链接写入 {code_error_file}")
        except Exception as e:
            logger.error(f"写入解析失败链接失败: {e}")

    def delete_past_code(self, codes: dict):
        """删除过期的密令，只保留最近两个月内的密令。
        Args:
            codes: 当前的密令字典，格式为 {密令: 月份字符串}。
        Returns:
            dict: 过滤后的密令字典，只包含最近两个月内的密令。
        """
        current_timestamp = int(time.time())
        valid_codes = {}
        for code, month_str in codes.items():
            try:
                month_time = time.strptime(month_str, "%Y-%m")
                month_timestamp = int(time.mktime(month_time))
                if current_timestamp - month_timestamp <= 60 * 24 * 3600:
                    valid_codes[code] = month_str
                else:
                    logger.info(f"密令 {code} 已过期，删除")
            except Exception as e:
                logger.error(f"解析密令 {code} 的月份失败: {e}")
        return valid_codes

    async def send_code_impl(self, event: AstrMessageEvent) -> None:
        """发送密令实现函数，支持用户查询最新的密令信息并发送给用户。
        Args:
            event: 消息事件对象。
        Returns:
            None
        """
        await self._send_codes_to_event(event)
