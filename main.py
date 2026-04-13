import asyncio
import json
import random
from pathlib import Path
from typing import Any

import aiohttp
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, MessageChain
from astrbot.api.event.filter import command
from astrbot.api.star import Context, Star
from astrbot.core.utils.astrbot_path import get_astrbot_data_path
from astrbot.core.utils.session_waiter import SessionController, session_waiter

from .parse import Parse
from .utils import cron_to_human

PLUGIN_NAME = "astrbot_plugin_marvelous_snail"


class MarvelousSnailPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self.scheduler = AsyncIOScheduler()
        self.authors = {}

    async def initialize(self):
        """插件初始化"""
        logger.info("最强蜗牛插件已加载")
        self.parse = Parse()
        # await self.get_saved_account()
        self._start_auto_updata_job()
        if not self.scheduler.running:
            self.scheduler.start()

    async def terminate(self):
        """插件卸载"""
        logger.info("最强蜗牛插件已卸载")
        if self.scheduler.running:
            self.scheduler.shutdown()
            logger.info("已停止 Cron 监控")

    def _check_config(self) -> bool:
        """检查是否已正确配置 API 地址和认证密钥"""
        api_url = self.config.get("exporter_api_url")
        auth_key = self.config.get("exporter_auth_key")
        return bool(
            api_url
            and isinstance(api_url, str)
            and api_url.strip()
            and auth_key
            and isinstance(auth_key, str)
            and auth_key.strip()
        )

    @command("zqwn")
    async def search_public_account(
        self, event: AstrMessageEvent, keyword: str = "最强蜗牛", size: int = 5
    ):
        """搜索公众号作者，默认搜索“最强蜗牛”，返回前5个结果"""
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
                            # 处理成功响应
                            data_list = data.get("list", [])
                            index = 1
                            result = "搜索结果:"
                            authors = await self.get_kv_data("authors", {})
                            for item in data_list:
                                name = item.get("nickname")
                                if name in authors.keys():  # type: ignore
                                    continue
                                fakeid = item.get("fakeid")
                                result += f"\n{index}: {name}"
                                self.authors[index] = {"name": name, "fakeid": fakeid}
                                index += 1
                            yield event.plain_result(result)
                        else:
                            # 处理失败响应
                            logger.info(
                                f"❌ 搜索失败: {data.get('base_resp').get('err_msg')}"
                            )
                    except (ValueError, KeyError) as e:
                        logger.error(f"API 响应解析失败: {e}")
            except Exception as e:
                logger.error(f"搜索失败: {e}")

    @command("zqwn_add")
    async def add_saved_account(self, event: AstrMessageEvent, index: str):
        """将搜索结果中指定索引的公众号作者添加到保存列表"""
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

    @command("zqwn_del")
    async def del_saved_account(self, event: AstrMessageEvent, name: str):
        """从保存列表中删除指定名字的公众号作者"""
        authors = await self.get_kv_data("authors", {})
        articles = await self.get_kv_data("articles", {})
        if name not in authors.keys():  # type: ignore
            yield event.plain_result(
                "❌ 无效的名字，请先使用 zqwn_list 命令查看已保存的作者列表"
            )
            return

        # 如果删除的作者在文章列表里，也删除文章
        if name in articles.keys():  # type: ignore
            del articles[name]  # type: ignore
            await self.put_kv_data("articles", articles)
        del authors[name]  # type: ignore
        await self.put_kv_data("authors", authors)
        yield event.plain_result(f"✅ 已删除作者: {name}")

    @command("zqwn_list")
    async def list_saved_accounts(self, event: AstrMessageEvent):
        """列出已保存的公众号作者"""
        authors = await self.get_kv_data("authors", {})
        if not authors or len(authors) == 0:
            yield event.plain_result("❌ 请先使用 zqwn 命令搜索公众号作者")
            return

        result = "已保存的作者列表:"
        for name in authors.keys():
            result += f"\n- {name}"

        yield event.plain_result(result)

    async def get_saved_account(self):
        """获取已保存的公众号作者的最新文章"""
        authors = await self.get_kv_data("authors", {})
        if not authors or len(authors) == 0:
            return
        old_articles = await self.get_kv_data("articles", {})
        if not old_articles:
            old_articles = {}
        new_articles = {}
        updata_flag = False
        for name, fakeid in authors.items():
            logger.debug(f"正在获取作者 {name} 的文章列表...")
            async with aiohttp.ClientSession() as session:
                headers = {"X-Auth-Key": self.config.get("exporter_auth_key")}
                params = {"fakeid": fakeid, "size": 1}
                try:
                    async with session.get(
                        f"{self.config.get('exporter_api_url')}/api/public/v1/article",
                        headers=headers,
                        params=params,
                    ) as resp:
                        try:
                            data = await resp.json()
                            base_resp = data.get("base_resp")
                            if base_resp and base_resp.get("err_msg") == "ok":
                                # 处理成功响应
                                articles = data.get("articles")  # 设置了只获取1条文章
                                if articles is None or len(articles) == 0:
                                    logger.debug(f"❌ 作者 {name} 没有文章")
                                    continue
                                article = articles[0]
                                aid = article.get("aid")
                                title = article.get("title")
                                digest = article.get("digest")
                                link = article.get("link")
                                if (
                                    name in old_articles.keys()
                                ):  # 是否添加过这个作者的文章
                                    old_aid = old_articles[name].get("aid")
                                    if old_aid == aid:
                                        logger.debug(f"✅ 作者 {name} 未更新")
                                        new_articles[name] = old_articles[name]  # type: ignore
                                        continue
                                    else:
                                        # 发布了新文章
                                        updata_flag = True
                                        new_articles[name] = article
                                        await self.save_config(name, article)
                                        logger.debug(
                                            f"✅ 作者 {name} old_aid: {old_aid} aid: {aid} 发布了新文章: {article.get('title')}\n链接: {link}"
                                        )
                                        await self._send_message(f"{link}")
                                        await self._send_message(
                                            f"作者: {name}\n文章标题: {title}\n文章简介: {digest}"
                                        )  # 因为链接可能解析不出来，所以把文章信息也发出来
                                else:
                                    # 发布了新文章
                                    updata_flag = True
                                    new_articles[name] = article
                                    await self.save_config(name, article)
                                    logger.debug(
                                        f"✅ 作者 {name} aid: {aid} 发布了新文章: {article.get('title')}\n链接: {link}"
                                    )
                                    await self._send_message(f"{link}")
                                    await self._send_message(
                                        f"作者: {name}\n文章标题: {title}\n文章简介: {digest}"
                                    )  # 因为链接可能解析不出来，所以把文章信息也发出来
                            else:
                                # 处理失败响应
                                logger.debug(
                                    f"❌ 获取{name}的文章失败: {data.get('base_resp').get('err_msg')}"
                                )
                        except (ValueError, KeyError) as e:
                            logger.error(f"API 响应解析失败: {e}")

                except Exception as e:
                    logger.error(f"获取公众号文章失败: {e}")
            base_delay = 6
            random_factor = random.uniform(-5, 5)
            delay = max(5, base_delay + random_factor)  # 确保间隔至少为5秒
            logger.debug(f"等待 {delay:.2f} 秒后继续获取下一个作者的文章...")
            await asyncio.sleep(delay)
        if not updata_flag:
            logger.debug("没有新的文章更新")
        else:
            await self.put_kv_data("articles", new_articles)

    def _start_auto_updata_job(self):
        """根据配置的 Cron 表达式设置监控任务"""
        scheduler = self.scheduler
        if scheduler is None:
            logger.error("Scheduler 未初始化")
            return

        job_id = "updata_cron_job"
        updata_cron = self.config.get("updata_cron")

        if scheduler.get_job(job_id):
            scheduler.remove_job(job_id)

        if not updata_cron:
            logger.debug("未配置 updata_cron，自动更新已禁用")
            return

        try:
            trigger = CronTrigger.from_crontab(updata_cron)
        except Exception as e:
            logger.error(f"Cron 表达式错误：{updata_cron} ({e})")
            return

        try:
            self.scheduler.add_job(
                self.get_saved_account,
                trigger=trigger,
                id=job_id,
            )
            try:
                human_cron = cron_to_human(updata_cron)
                logger.info(f"已注册 Cron 监控：{updata_cron} ({human_cron})")
            except ValueError as e:
                logger.error(f"Cron 表达式错误：{updata_cron} ({e})")
        except Exception as e:
            logger.error(f"添加任务失败：{e}")

    async def _send_message(self, message: str):
        """发送消息"""
        try:
            users = await self.get_kv_data("users", {})
            if not users or len(users) == 0:
                logger.warning("未配置推送用户，无法发送私聊消息")
                return
            for uid, user_info in users.items():
                if not user_info.get("enabled", False):
                    continue
                umo = user_info.get("umo")
                if not umo:
                    logger.warning(f"用户 {uid} 未配置 umo，跳过发送")
                    continue
                message_chain = MessageChain().message(message)
                try:
                    await self.context.send_message(umo, message_chain)  # type: ignore
                    logger.info(f"已发送消息给用户 {uid}: {message}")
                except Exception as e:
                    logger.error(f"发送消息给用户 {uid} 失败: {e}")
        except Exception as e:
            logger.error(f"发送消息失败: {e}")

    @command("获取推送列表")
    async def get_push_list(self, event: AstrMessageEvent):
        """获取推送列表"""
        users = await self.get_kv_data("users", {})
        if not users or len(users) == 0:
            yield event.plain_result("❌ 未配置推送用户")
            return
        push_list = []
        for uid, user_info in users.items():
            if user_info.get("enabled", False):
                push_list.append(uid)
        if push_list:
            yield event.plain_result(f"✅ 当前推送用户: {', '.join(push_list)}")
        else:
            yield event.plain_result("❌ 没有开启自动推送的用户")

    @command("推送zqwn")
    async def push_zqwn(self, event: AstrMessageEvent, enabled: str):
        """设置推送列表/开启或关闭推送"""
        group_id = getattr(event.message_obj, "group_id", None)
        user_name = event.get_sender_name()
        uid = group_id
        if not group_id or group_id == 0:
            uid = user_name
        users = await self.get_kv_data("users", {})
        if enabled not in ["开启", "关闭"]:
            yield event.plain_result(
                "❌ 参数错误，请使用：推送zqwn 开启 或 推送zqwn 关闭"
            )
            return
        if enabled == "开启":
            user_info = {
                "umo": event.unified_msg_origin,  # 保存统一会话ID
                "enabled": True,
            }
            users[uid] = user_info  # type: ignore
            await self.put_kv_data("users", users)
            yield event.plain_result(f"✅ {uid} 已开启自动推送")
        else:
            user_info = {
                "umo": event.unified_msg_origin,  # 保存统一会话ID
                "enabled": False,
            }
            users[uid] = user_info  # type: ignore
            await self.put_kv_data("users", users)
            yield event.plain_result(f"✅ {uid} 已关闭自动推送")

    async def save_config(self,authors: str, write_data: Any)-> None:
        """保存数据到本地 JSON 文件，按作者分类保存"""
        # 1. 获取字符串路径，并显式转换为 Path 对象
        data_dir_str = get_astrbot_data_path()
        plugin_data_path = Path(data_dir_str) / "plugin_data" / self.name

        # 2. 创建目录 (此时 plugin_data_path 是 Path 对象，所以 .mkdir() 可用)
        plugin_data_path.mkdir(parents=True, exist_ok=True)
        # 3.尝试读取文件
        authors_file = plugin_data_path / f"{authors}.json"
        if authors_file.exists():
            try:
                with authors_file.open("r", encoding="utf-8") as f:
                    data = json.load(f)
                    #获取数据数量
                    num = data.get("num", 0)
                    articles = data.get("articles", [])
                    #根据时间戳排序articles
                    # articles.sort(key=lambda x: x.get("update_time", 0), reverse=True)
                    #头插
                    articles.insert(0, write_data)
                    num += 1
                    data = {
                        "num": num,
                        "articles": articles
                    }
            except Exception as e:
                logger.error(f"读取 {authors}.json 失败: {e}")
        else:
            data = {
                "num": 1,
                "articles": [write_data]
            }
        # 4.尝试写入文件
        try:
            with authors_file.open("w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
        except Exception as e:
            logger.error(f"写入 {authors}.json 失败: {e}")

    @command("最新攻略zqwn")
    async def get_articles(self, event: AstrMessageEvent):
        """获取已保存的文章列表，选择后发送文章详情"""
        data_dir_str = get_astrbot_data_path()
        plugin_data_path = Path(data_dir_str) / "plugin_data" / self.name
        #获取目录下的所有json文件名
        json_files = list(plugin_data_path.glob("*.json"))
        #去掉扩展名后的文件名作为作者列表
        authors = [file.stem for file in json_files]
        if not authors:
            logger.debug("没有已保存的作者和文章数据，请先添加作者并等待更新")
            return
        asyncio.create_task(
            self.parse.send_authors_selection(event=event, authors=authors)
        )

        @session_waiter(timeout=10)
        async def empty_mention_waiter(
            controller: SessionController, event: AstrMessageEvent
        ):
            arg = event.message_str.strip()
            parts = arg.split()
            index = 0
            # 解析输入格式
            if len(parts) == 1 and parts[0].isdigit():
                index = int(parts[0])
            if index == 0:
                return
            if index < 1 or index > len(authors):
                controller.stop()
                return
            selected_author = authors[index - 1]+".json"
            # 读取作者对应的文章数据
            try:
                with open(plugin_data_path / selected_author, encoding="utf-8") as f:
                    author_data = json.load(f)
            except Exception as e:
                logger.error(f"读取 {selected_author} 失败: {e}")
                controller.stop()
                return
            # 获取最新的一篇文章
            articles = author_data.get("articles", [])
            if not articles:
                logger.debug(f"作者 {selected_author} 没有文章数据")
                controller.stop()
                return
            new_article: dict = articles[0]
            await self.parse.send_article_details(event, new_article)
            controller.stop()
        try:
            await empty_mention_waiter(event)
        except TimeoutError as _:
            logger.warning("选择超时！")
        except Exception as e:
            logger.error("选择发生错误" + str(e))
