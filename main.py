import ast
import asyncio
import json
import random
import time
from pathlib import Path
from typing import Any

import aiohttp
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, MessageChain
from astrbot.api.event.filter import EventMessageType, command, event_message_type
from astrbot.api.star import Context, Star
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import (
    AiocqhttpMessageEvent,
)
from astrbot.core.utils.astrbot_path import get_astrbot_data_path
from astrbot.core.utils.session_waiter import SessionController, session_waiter

from .code import parse_code
from .parse import Parse
from .sign_in import binds_account, get_server, sign_request
from .utils import (
    convert_to_query_bytes,
    cron_to_human,
    decrypt_data,
    encrypt_data,
    send_msg,
)

PLUGIN_NAME = "astrbot_plugin_marvelous_snail"


class MarvelousSnailPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self.scheduler = AsyncIOScheduler()
        self.authors = {}
        self.headers = config.get("headers", "{}")
        self.headers = ast.literal_eval(self.headers)

    async def initialize(self):
        """插件初始化"""
        logger.info("最强蜗牛插件已加载")
        self.parse = Parse()
        # await self.get_saved_account()
        await self._start_auto_updata_job()
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
        """搜索公众号作者，默认搜索“最强蜗牛”，返回前5个结果
        Args:
            keyword: 搜索关键词，默认为“最强蜗牛”
            size: 返回结果数量，默认为5
        """
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
        """将搜索结果中指定索引的公众号作者添加到保存列表
        Args:
            index: 搜索结果中的索引
        """
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
        """从保存列表中删除指定名字的公众号作者
        Args:
            name: 作者名称
        """
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
                                author_name = article.get("author_name")
                                if author_name == "广告":  # 如果是广告，就不保存了
                                    continue
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
                                        await self._send_message(
                                            f"作者: {name}\n文章标题: {title}\n文章简介: {digest}\n链接: {link}"
                                        )
                                        if name == "最强蜗牛":
                                            # 如果是最强蜗牛的文章，解析密令并发送
                                            code_info = await self.get_code(link)
                                            code = code_info.get("code")
                                            if code and len(code) > 0:
                                                send_txt = f"密令:{code}"
                                                if code_info.get("share"):
                                                    send_txt += f"\n{digest}"
                                                    self.write_codes(
                                                        digest.split("密令：")[-1]
                                                    )
                                                await self._send_message(send_txt)
                                else:
                                    # 发布了新文章
                                    updata_flag = True
                                    new_articles[name] = article
                                    await self.save_config(name, article)
                                    logger.debug(
                                        f"✅ 作者 {name} aid: {aid} 发布了新文章: {article.get('title')}\n链接: {link}"
                                    )
                                    await self._send_message(
                                        f"作者: {name}\n文章标题: {title}\n文章简介: {digest}\n链接: {link}"
                                    )
                                    if name == "最强蜗牛":
                                        # 如果是最强蜗牛的文章，解析密令并发送
                                        code_info = await self.get_code(link)
                                        code = code_info.get("code")
                                        if code and len(code) > 0:
                                            send_txt = f"密令:{code}"
                                            if code_info.get("share"):
                                                send_txt += f"\n{digest}"
                                                self.write_codes(
                                                    digest.split("密令：")[-1]
                                                )
                                            await self._send_message(send_txt)
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

    async def _start_auto_updata_job(self):
        """根据配置的 Cron 表达式设置监控任务
        Cron 表达式示例：0 0 * * *（每天凌晨0点执行）"""
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
        #如果headers存在，设置每日八点10分执行签到任务，并设置30分钟发送签到命令进行header保持
        if self.headers:
            try:
                sign_trigger = CronTrigger(hour=8, minute=10)
                self.scheduler.add_job(
                    self.auto_sign_in,
                    trigger=sign_trigger,
                    id="auto_sign_in_job",
                )
                logger.info("已注册自动签到任务：每天 08:10")
            except Exception as e:
                logger.error(f"添加自动签到任务失败：{e}")
            try:
                self.scheduler.add_job(
                    sign_request,
                    trigger=CronTrigger(minute="*/1"),
                    id="keep_sign_in_job",
                    args=[self.headers],
                )
                logger.info("已注册签到保持任务：每30分钟执行一次")
                # 立即执行一次签到保持任务，确保在插件加载时就开始保持
                ret = await sign_request(self.headers)
                logger.info(f"初始签到保持结果: {ret}")
            except Exception as e:
                logger.error(f"添加签到保持任务失败：{e}")

    async def _send_message(self, message: str):
        """发送消息
        Args:
            message: 要发送的消息内容
        """
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
        """设置推送列表/开启或关闭推送
        Args:
            enabled: "开启" 或 "关闭"
        """
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

    async def save_config(self, authors: str, write_data: Any) -> None:
        """保存数据到本地 JSON 文件，按作者分类保存
        Args:
            authors: 作者名称
            write_data: 要保存的数据
        """
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
                    # 获取数据数量
                    num = data.get("num", 0)
                    articles = data.get("articles", [])
                    # 根据时间戳排序articles
                    # articles.sort(key=lambda x: x.get("update_time", 0), reverse=True)
                    # 头插
                    articles.insert(0, write_data)
                    num += 1
                    data = {"num": num, "articles": articles}
            except Exception as e:
                logger.error(f"读取 {authors}.json 失败: {e}")
        else:
            data = {"num": 1, "articles": [write_data]}
        # 4.尝试写入文件
        try:
            with authors_file.open("w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
        except Exception as e:
            logger.error(f"写入 {authors}.json 失败: {e}")

    @command("搜索攻略")
    async def get_strategy(self, event: AstrMessageEvent, parse_str: str):
        """获取已保存的文章列表，选择后发送文章详情
        Args:
            parse_str: 搜索关键词
        """
        user_stage = "select_author"
        selected_author = None
        pages_msg, pages_data = [], []
        message_id = None
        page_id = 0
        data_dir_str = get_astrbot_data_path()
        plugin_data_path = Path(data_dir_str) / "plugin_data" / self.name
        # 获取目录下的所有json文件名
        json_files = list(plugin_data_path.glob("*.json"))
        # 去掉扩展名后的文件名作为作者列表
        authors = [file.stem for file in json_files]
        if not authors or len(authors) == 0:
            logger.info("没有已保存的作者和文章数据，请先添加作者并等待更新")
            await event.send(event.plain_result("❌ 暂无数据存储"))
            return
        # asyncio.create_task(
        #     self.parse.send_authors_selection(event=event, authors=authors)
        # )
        formatted_authors = [
            f"{index + 1}. {author}" for index, author in enumerate(authors)
        ]
        formatted_authors.insert(0, "需要获取谁的文章详情？请回复编号选择：")
        msg = "\n".join(formatted_authors)
        message_id = await send_msg(event, msg)
        # 如果是群聊记录用户ID
        group_id = getattr(event.message_obj, "group_id", None)
        user_id = None
        if group_id and group_id != 0:
            user_id = event.get_sender_id()

        @session_waiter(timeout=20)
        async def articles_waiter(
            controller: SessionController, event: AstrMessageEvent
        ):
            nonlocal \
                user_stage, \
                selected_author, \
                pages_msg, \
                pages_data, \
                message_id, \
                page_id
            now_user_id = event.get_sender_id()
            if user_id and now_user_id != user_id:
                return
            # 可能获取的是正在输入情况，不撤回，不进行后续流程
            arg = event.message_str.strip()
            parts = arg.split()
            if len(parts) == 0:
                print("用户正在输入，等待下一次响应...")
                return
            if isinstance(event, AiocqhttpMessageEvent):  # 判断aiocqhttp平台
                if message_id:
                    await event.bot.delete_msg(
                        message_id=message_id
                    )  # 用户响应撤回消息
                    message_id = None

            if user_stage == "select_author":
                arg = event.message_str.strip()
                parts = arg.split()
                index = 0
                # 解析输入格式
                if len(parts) == 1 and parts[0].isdigit():
                    index = int(parts[0])
                if index < 1 or index > len(authors):
                    return
                selected_author = authors[index - 1]
                # 解析作者的文章数据
                result = await self.parse.parse_title_send_link(
                    plugin_data_path, selected_author, parse_str
                )
                if result is None or len(result) == 0:
                    await event.send(
                        event.plain_result(f"❌ 作者 {selected_author} 没有文章数据")
                    )
                    controller.stop()
                    return
                user_stage = "select_article"
                pages_msg, pages_data = await self.parse.Paging_strategies(
                    result["data"], 5
                )
                # 发送第一页攻略列表
                message_id = await send_msg(event, pages_msg[page_id])
                controller.keep(
                    timeout=20, reset_timeout=True
                )  # 重置超时时间，等待用户选择文章
            elif user_stage == "select_article":
                arg = event.message_str.strip()
                parts = arg.split()
                select_article_id = 0
                if len(parts) == 1 and parts[0].isdigit():
                    select_article_id = int(parts[0])
                else:
                    return
                if select_article_id < 1 or select_article_id > len(
                    pages_data[page_id]
                ):
                    return
                if select_article_id in pages_data[page_id]:
                    selected = pages_data[page_id][select_article_id]
                    if selected == "上一页":
                        page_id = max(0, page_id - 1)
                        message_id = await send_msg(event, pages_msg[page_id])
                    elif selected == "下一页":
                        page_id = min(len(pages_msg) - 1, page_id + 1)
                        message_id = await send_msg(event, pages_msg[page_id])
                    else:
                        title, link = selected
                        await event.send(event.plain_result(link))
                        controller.stop()
                        return
                else:
                    return
                controller.keep(
                    timeout=20, reset_timeout=True
                )  # 重置超时时间，等待用户选择文章

        try:
            await articles_waiter(event)
        except TimeoutError as _:
            logger.warning("选择超时！")
            await event.send(event.plain_result("❌ 选择超时，终止运行"))
        except Exception as e:
            logger.error("选择发生错误" + str(e))
        event.stop_event()

    async def get_code(self, link: str):
        """解析密令
        Args:
            link: 文章链接
        """
        ret = {"code": "", "share": False}
        exporter_api_url = self.config.get("exporter_api_url")
        parse_code_result = await parse_code(exporter_api_url, link)
        if parse_code_result.get("msg") == "解析成功":
            code = parse_code_result["code"]
            ret["code"] = code
            self.write_codes(code)
            logger.info(f"解析密令成功: {code}")
            # 判断是否存在share
            if parse_code_result["share"]:
                ret["share"] = True
            return ret
        else:
            self.write_code_error(link)
            logger.info(f"解析密令失败: {parse_code_result.get('msg')},链接: {link}")
        return ret

    def write_codes(self, code: str):
        """将解析得到的密令写入本地 JSON 文件
        Args:
            code: 解析得到的密令
        """
        data = {"num": 0, "code": {}}
        # 1. 获取字符串路径，并显式转换为 Path 对象
        data_dir_str = get_astrbot_data_path()
        plugin_data_path = Path(data_dir_str) / "plugin_data" / self.name
        # 2. 尝试创建目录 (此时 plugin_data_path 是 Path 对象，所以 .mkdir() 可用)，如果目录已存在则不会报错
        codes_dir = plugin_data_path / "codes"
        codes_dir.mkdir(parents=True, exist_ok=True)
        codes_file = codes_dir / "codes.json"
        # 读取原有的密令数据
        codes = {}
        if codes_file.exists():
            try:
                with codes_file.open("r", encoding="utf-8") as f:
                    data = json.load(f)
                    codes = data.get("code", {})
            except Exception as e:
                logger.error(f"读取原有密令数据失败: {e}")
        # 获取当前时间戳,转换为月份格式，作为密令的值
        timestamp = int(time.time())
        month_str = time.strftime("%Y-%m", time.localtime(timestamp))
        codes[code] = month_str
        # 删除过期的密令
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
        """将解析失败的链接写入本地 JSON 文件
        Args:
            link: 解析失败的链接
        """
        data = {"urls": []}
        # 1. 获取字符串路径，并显式转换为 Path 对象
        data_dir_str = get_astrbot_data_path()
        plugin_data_path = Path(data_dir_str) / "plugin_data" / self.name
        # 2. 尝试创建目录 (此时 plugin_data_path 是 Path 对象，所以 .mkdir() 可用)，如果目录已存在则不会报错
        codes_dir = plugin_data_path / "codes"
        codes_dir.mkdir(parents=True, exist_ok=True)
        code_error_file = codes_dir / "code_error.json"
        # 读取原有的解析失败链接数据
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
        """删除过期的密令，假设密令过期时间为2个月
        Args:
            codes: 当前所有密令的字典，格式为 {code: "2024-06"}
        """
        current_timestamp = int(time.time())
        valid_codes = {}
        for code, month_str in codes.items():
            try:
                month_time = time.strptime(month_str, "%Y-%m")
                month_timestamp = int(time.mktime(month_time))
                # 如果当前时间戳与密令月份的时间戳相差不超过2个月（60天），则保留该密令
                if current_timestamp - month_timestamp <= 60 * 24 * 3600:
                    valid_codes[code] = month_str
                else:
                    logger.info(f"密令 {code} 已过期，删除")
            except Exception as e:
                logger.error(f"解析密令 {code} 的月份失败: {e}")
        return valid_codes

    @event_message_type(EventMessageType.ALL)
    async def send_code(self, event: AstrMessageEvent):
        """监听所有消息，如果消息中包含“密令”二字，则发送当前有效的密令列表"""
        if "密令" not in event.message_str:
            return
        # 读取密令文件
        data_dir_str = get_astrbot_data_path()
        plugin_data_path = Path(data_dir_str) / "plugin_data" / self.name
        codes_dir = plugin_data_path / "codes"
        codes_file = codes_dir / "codes.json"
        codes = {}
        if codes_file.exists():
            try:
                with codes_file.open("r", encoding="utf-8") as f:
                    data = json.load(f)
                    codes = data.get("code", {})
            except Exception as e:
                logger.error(f"读取密令数据失败: {e}")
        # 每五十个密令增加一个\n
        codes_list = list(codes.keys())
        codes_str = ""
        for i, code in enumerate(codes_list):
            codes_str += code
            if (i + 1) % 50 == 0:
                codes_str += "\n\n"
            else:
                codes_str += "\n"
        # 发送密令
        yield event.plain_result(codes_str)

    @command("绑定账号")
    async def get_headers(self, event: AstrMessageEvent, account: str):
        """
        获取账号的请求头信息，查询账号绑定的角色，选择角色后绑定账号并保存数据
        Args:
            account: 账号"
        """
        info = "【个人信息处理告知】\
            \n你当前申请绑定账号用于本机器人无偿每日签到服务，我方依据《个人信息保护法》向你完整告知：\
            \n1. 处理数据范围：仅存储你的【手机号、游戏角色ID】，无任何多余信息收集。\
            \n2. 存储期限：**账号绑定存续期间全程存储**，你随时可申请删除，删除后全部数据永久清除无备份。\
            \n3. 数据安全：所有数据服务器端**AES加密存储**，不明文存储、不泄露、不转卖、不共享、不对外传输任何第三方。\
            \n4. 你的全部法定权利：随时查询本人数据、随时一键删除全部数据、撤回本次授权。\
            \n5. 本服务全程无偿、无商业盈利、非经营性个人互助服务。\
            \n请你确认全部内容并自愿授权，后续【选择角色】即视为自愿授权信息并完成完成绑定。"
        await event.send(event.plain_result(info))
        users_data = await get_server(account)
        if users_data is None or len(users_data) == 0:
            await event.send(event.plain_result("❌ 获取数据失败，请检查账号是否正确"))
            return
        # 配置角色菜单信息供用户选择
        select_info = "选择需要绑定的角色:"
        id = 1
        for user_data in users_data:
            select_info += f"\n{id}.区服: {user_data.get('server_name')}, 昵称: {user_data.get('role_name')},战力: {user_data.get('extra').get('score')}"
            id += 1
        message_id = await send_msg(event, select_info)
        # 如果是群聊记录用户ID,需要撤回
        group_id = getattr(event.message_obj, "group_id", None)
        user_id = None
        if group_id and group_id != 0:
            user_id = event.get_sender_id()

        @session_waiter(timeout=60)
        async def bind_waiter(controller: SessionController, event: AstrMessageEvent):
            nonlocal message_id, user_id
            now_user_id = event.get_sender_id()
            if user_id and now_user_id != user_id:
                return
            # 可能获取的是正在输入情况，不撤回，不进行后续流程
            arg = event.message_str.strip()
            parts = arg.split()
            if len(parts) == 0:
                return
            if isinstance(event, AiocqhttpMessageEvent):  # 判断aiocqhttp平台
                if message_id:
                    await event.bot.delete_msg(
                        message_id=message_id
                    )  # 用户响应撤回消息
                    message_id = None

            if len(parts) == 1 and parts[0].isdigit():
                index = int(parts[0])
                if index < 1 or index > len(users_data):
                    return
                selected_user = users_data[index - 1]
                logger.info("编码中")
                payload = convert_to_query_bytes(selected_user, account)
                logger.info("正在绑定账号...")
                result = await binds_account(self.headers, payload)
                if result["code"] == 200:
                    await event.send(
                        event.plain_result(
                            f"✅ 绑定成功:{selected_user['server_name']}-{selected_user['role_name']}:{selected_user['extra']['score']}"
                        )
                    )
                    #首次绑定执行一次签到
                    sign_result = await sign_request(self.headers)
                    await event.send(
                        event.plain_result(f"首次绑定执行签到: {sign_result.get('message')}")
                    )
                    # 加密保存数据
                    encrypted_account = encrypt_data(account)
                    encrypted_role_id = encrypt_data(selected_user["role_id"])
                    # 获取用户ID
                    user_id = event.get_sender_id()
                    # 保存加密后的数据到本地 JSON 文件
                    data_dir_str = get_astrbot_data_path()
                    plugin_data_path = Path(data_dir_str) / "plugin_data" / self.name
                    plugin_data_path.mkdir(parents=True, exist_ok=True)
                    user_dir = plugin_data_path / "users"
                    user_dir.mkdir(parents=True, exist_ok=True)
                    # 根据用户ID创建JSON文件保存数据，方便后续查询和使用
                    user_file = user_dir / f"{user_id}.json"
                    # 先判断是否存在文件，如果存在就读取原有数据，更新后再写入，如果不存在就直接写入
                    user_data = {"num": 0, "users": []}
                    if user_file.exists():
                        try:
                            with user_file.open("r", encoding="utf-8") as f:
                                user_data = json.load(f)
                        except Exception as e:
                            logger.error(f"读取用户数据失败: {e}")
                    if user_data or user_data.get("num", 0) > 0:
                        users = user_data.get("users", [])
                        users.append(
                            {
                                "account": encrypted_account,
                                "role_id": encrypted_role_id,
                                "info": f"{selected_user['server_name']}-{selected_user['role_name']}:{selected_user['extra']['score']}",
                            }
                        )
                        user_data["users"] = users
                        user_data["num"] = len(users)
                    else:
                        user_data = {
                            "num": 1,
                            "users": [
                                {
                                    "account": encrypted_account,
                                    "role_id": encrypted_role_id,
                                    "info": f"{selected_user['server_name']}-{selected_user['role_name']}:{selected_user['extra']['score']}",
                                }
                            ],
                        }
                    with open(user_file, "w", encoding="utf-8") as f:
                        json.dump(user_data, f, ensure_ascii=False, indent=4)
                    logger.info(f"已将绑定数据写入 {user_file}")
                else:
                    await event.send(
                        event.plain_result(f"❌ 绑定失败，{result.get('message')}")
                    )
                controller.stop()
                return
        try:
            await bind_waiter(event)
        except TimeoutError as _:
            logger.warning("选择超时！")
            await event.send(event.plain_result("❌ 选择超时，终止运行"))
        except Exception as e:
            logger.error("选择发生错误" + str(e))
        event.stop_event()

    @command("查询绑定")
    async def query_account(self, event: AstrMessageEvent):
        """查询已绑定的账号，显示已绑定的角色信息
        """
        # 获取用户ID
        user_id = event.get_sender_id()
        # 读取用户数据文件
        data_dir_str = get_astrbot_data_path()
        plugin_data_path = Path(data_dir_str) / "plugin_data" / self.name
        user_dir = plugin_data_path / "users"
        user_file = user_dir / f"{user_id}.json"
        if not user_file.exists():
            await event.send(event.plain_result("❌ 未找到绑定数据"))
            return
        try:
            with user_file.open("r", encoding="utf-8") as f:
                user_data = json.load(f)
                users = user_data.get("users", [])
                if not users or len(users) == 0:
                    await event.send(event.plain_result("❌ 未找到绑定数据"))
                    return
                info_str = "已绑定的角色信息:"
                for user in users:
                    info_str += f"\n{user['info']}"
                await event.send(event.plain_result(info_str))
        except Exception as e:
            logger.error(f"读取用户数据失败: {e}")
            await event.send(event.plain_result("❌ 读取数据失败"))
            return

    @command("注销绑定")
    async def delete_account(self, event: AstrMessageEvent):
        """删除已绑定的账号，查询已绑定的角色，选择后删除账号数据
        """
        # 获取用户ID
        user_id = event.get_sender_id()
        # 读取用户数据文件
        data_dir_str = get_astrbot_data_path()
        plugin_data_path = Path(data_dir_str) / "plugin_data" / self.name
        user_dir = plugin_data_path / "users"
        user_file = user_dir / f"{user_id}.json"
        if not user_file.exists():
            await event.send(event.plain_result("❌ 未找到绑定数据"))
            return
        try:
            with user_file.open("r", encoding="utf-8") as f:
                user_data = json.load(f)
                users = user_data.get("users", [])
                if not users or len(users) == 0:
                    await event.send(event.plain_result("❌ 未找到绑定数据"))
                    return
                # 显示已绑定的账号和角色供用户选择
                select_info = "选择需要删除的账号:"
                id = 1
                for user in users:
                    select_info += f"\n{id}. {user['info']}"
                    id += 1
                message_id = await send_msg(event, select_info)
                @session_waiter(timeout=20)
                async def delete_waiter(controller: SessionController, event: AstrMessageEvent):
                    nonlocal message_id, users, user_file, user_id
                    now_user_id = event.get_sender_id()
                    if now_user_id != user_id:
                        return
                    arg = event.message_str.strip()
                    parts = arg.split()
                    if len(parts) == 0:
                        return
                    if isinstance(event, AiocqhttpMessageEvent):  # 判断aiocqhttp平台
                        if message_id:
                            await event.bot.delete_msg(
                                message_id=message_id
                            )  # 用户响应撤回消息
                            message_id = None
                    if len(parts) == 1 and parts[0].isdigit():
                        index = int(parts[0])
                        if index < 1 or index > len(users):
                            return
                        selected_user = users[index - 1]
                        users.remove(selected_user)
                        with user_file.open("w", encoding="utf-8") as f:
                            json.dump(user_data, f, ensure_ascii=False, indent=4)
                        await event.send(event.plain_result("✅ 账号删除成功"))
                        controller.stop()
                        return
                try:
                    await delete_waiter(event)
                except TimeoutError as _:
                    logger.warning("选择超时！")
                    await event.send(event.plain_result("❌ 选择超时，终止运行"))
        except Exception as e:
            logger.error(f"读取用户数据失败: {e}")
            await event.send(event.plain_result("❌ 读取数据失败"))
            return

    @command("签到")
    async def sign(self, event: AstrMessageEvent):
        """签到功能，查询已绑定的角色，选择后执行签到
        """
        #读取文件
        data_dir_str = get_astrbot_data_path()
        plugin_data_path = Path(data_dir_str) / "plugin_data" / self.name
        user_dir = plugin_data_path / "users"
        user_id = event.get_sender_id()
        user_file = user_dir / f"{user_id}.json"
        if not user_file.exists():
            await event.send(event.plain_result("❌ 未找到绑定数据"))
            return
        try:
            with user_file.open("r", encoding="utf-8") as f:
                user_data = json.load(f)
                users = user_data.get("users", [])
                if not users or len(users) == 0:
                    await event.send(event.plain_result("❌ 未找到绑定数据"))
                    return
                for user in users:
                    #获取角色信息
                    account = decrypt_data(user["account"])
                    role_id = decrypt_data(user["role_id"])
                    users_data = await get_server(account)  # 获取最新的角色信息，更新info显示
                    if users_data is None or len(users_data) == 0:
                        logger.error(f"获取数据失败，账号: {account}")
                        continue
                    for user_data in users_data:
                        if user_data["role_id"] == role_id:
                            #编码数据
                            payload = convert_to_query_bytes(user_data,account)
                            #绑定角色
                            result = await binds_account(self.headers, payload)
                            if result["code"] == 200:
                                sign_result = await sign_request(self.headers)
                                await event.send(
                                    event.plain_result(
                                        f"✅ {user['info']} 签到成功: {sign_result.get('message')}"
                                    )
                                )
                                continue
                            else:
                                logger.error(f"绑定失败，账号: {account}, 角色: {user['info']}, 错误信息: {result.get('message')}")
                    logger.error(f"未找到匹配的角色信息，账号: {account}, 角色ID: {role_id}")
        except Exception as e:
            logger.error(f"读取用户数据失败: {e}")
            await event.send(event.plain_result("❌ 读取数据失败"))
            return

    @command("定时签到推送")
    async def schedule_sign(self, event: AstrMessageEvent,enabled: str):
        """定时签到推送开关
        Args:
            enabled: "开启" 或 "关闭"
        """
        #群聊屏蔽
        group_id = getattr(event.message_obj, "group_id", None)
        if group_id and group_id != 0:
            yield event.plain_result("❌ 群聊暂不支持定时签到信息推送")
            return
        #获取用户ID
        uid = event.get_sender_id()
        users = await self.get_kv_data("users_sign", {})
        if enabled not in ["开启", "关闭"]:
            yield event.plain_result(
                "❌ 参数错误，请使用：定时签到推送 开启 或 定时签到推送 关闭"
            )
            return
        if enabled == "开启":
            user_info = {
                "umo": event.unified_msg_origin,  # 保存统一会话ID
            }
            users[uid] = user_info  # type: ignore
            await self.put_kv_data("users_sign", users)
            yield event.plain_result(f"✅ {uid} 已开启定时签到推送")
        else:
            #关闭直接删除用户的推送信息
            if users.get(uid) is not None:  # type: ignore
                del users[uid] # type: ignore
            await self.put_kv_data("users_sign", users)
            yield event.plain_result(f"✅ {uid} 已关闭定时签到推送")

    async def auto_sign_in(self):
        """定时签到功能，查询已绑定的角色，选择后执行签到
        """
        #获取推送信息列表
        users_sign = await self.get_kv_data("users_sign", {})
        umo = None
        #读取文件
        data_dir_str = get_astrbot_data_path()
        plugin_data_path = Path(data_dir_str) / "plugin_data" / self.name
        user_dir = plugin_data_path / "users"
        #定时任务所以获取目录下所有的文件名，文件名即用户ID，根据文件获取用户数据并执行签到
        for user_file in user_dir.glob("*.json"):
            user_id = user_file.stem
            user_file = user_dir / f"{user_id}.json"
            send_info = "【定时签到推送】"
            if users_sign.get(user_id) is not None:  # type: ignore
                umo = users_sign[user_id].get("umo")  # type: ignore
            if not user_file.exists():
                send_info += "\n未找到绑定数据，无法执行签到"
                if umo:
                    await self.context.send_message(umo, send_info)  # type: ignore
                logger.error(f"未找到用户 {user_id} 的绑定数据文件，无法执行签到")
                continue
            try:
                #读取用户数据
                with user_file.open("r", encoding="utf-8") as f:
                    user_data = json.load(f)
                    users = user_data.get("users", [])
                    #去重role_id相同的角色，只保留最新的一个
                    unique_users = {}
                    for user in users:
                        role_id = decrypt_data(user["role_id"])
                        unique_users[role_id] = user
                    users = list(unique_users.values())
                    writer_data = []
                    for user in users:
                        #获取角色信息
                        account = decrypt_data(user["account"])
                        role_id = decrypt_data(user["role_id"])
                        info = user.get("info", "")
                        users_data = await get_server(account)  # 获取最新的角色信息，更新info显示
                        if users_data is None or len(users_data) == 0:
                            send_info += f"\n{info}:获取数据失败，无法执行签到"
                            logger.error(f"获取数据失败，账号: {account}")
                            continue
                        info = user.get("info", "")
                        for user_data in users_data:
                            if user_data["role_id"] == role_id:
                                user["info"] = user_data.get("info", info)  # 更新角色信息显示
                                #编码数据
                                payload = convert_to_query_bytes(user_data,account)
                                #绑定角色
                                result = await binds_account(self.headers, payload)
                                if result["code"] == 200:
                                    sign_result = await sign_request(self.headers)
                                    send_info += f"\n{user['info']}:签到成功, {sign_result.get('message')}"
                                    #休眠3-5秒，防止请求过快被封IP，间隔随机3-5秒
                                    random_factor = random.uniform(3, 5)
                                    delay = max(3, random_factor)  # 确保间隔至少为3秒
                                    await asyncio.sleep(delay)
                                else:
                                    send_info += f"\n{user['info']}:绑定失败，账号: {account}, 错误信息: {result.get('message')}"
                                writer_data.append(user)
                                break
            except Exception as e:
                logger.error(f"读取用户数据失败: {e}")
                return
            #发送签到结果
            if umo:
                message_chain = MessageChain().message(send_info)  # type: ignore
                try:
                    await self.context.send_message(umo, message_chain)  # type: ignore
                    logger.info(f"已发送消息给用户 {umo}: {send_info}")
                except Exception as e:
                    logger.error(f"发送消息给用户 {umo} 失败: {e}")
                umo = None
            #更新文件数据写入
            user_data["users"] = writer_data
            user_data["num"] = len(writer_data)
            with user_file.open("w", encoding="utf-8") as f:
                json.dump(user_data, f, ensure_ascii=False, indent=4)
            #一个用户签到结束，休眠1-3分钟，防止请求过快被封IP，间隔随机1-3分钟
            random_factor = random.uniform(60, 180)
            delay = max(60, random_factor)  # 确保间隔至少为1分钟
            await asyncio.sleep(delay)
            logger.info(f"用户 {user_id} 的定时签到已完成，休眠{delay}秒后继续下一个用户签到")

    # ==================== LLM 工具 ====================

    # @llm_tool(name="search_strategy")
    # async def search_strategy(
    #     self,
    #     event: AstrMessageEvent,
    #     parse_str: str,
    # ):
    #     """将你分析得到的提示词作为参数调用 get_strategy 方法，后续由get_strategy流程接管运行即可
    #     Args:
    #         parse_str(string): 搜索提示词,例如: "搜索最强蜗牛源兽攻略"中的"源兽"
    #     """
    #     await self.get_strategy(event, parse_str=parse_str)
    #     return "OK. The strategy workflow has been executed. Please do not generate any further text response."
