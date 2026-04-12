
import asyncio
import aiohttp
import random

from astrbot.api import logger,AstrBotConfig
from astrbot.api.star import Context, Star
from astrbot.api.event import AstrMessageEvent,MessageChain
from astrbot.api.event.filter import command

from apscheduler.triggers.cron import CronTrigger
from apscheduler.schedulers.asyncio import AsyncIOScheduler
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
        # await self.get_saved_account()
        self._start_auto_updata_job()
        if not self.scheduler.running:
            self.scheduler.start()

    async def terminate(self):
        """插件卸载"""
        logger.info("最强蜗牛插件已卸载")
        if self.scheduler.running:
            self.scheduler.shutdown()
            logger.info(f"已停止 Cron 监控")

    def _check_config(self) -> bool:
        """检查是否已正确配置 API 地址和认证密钥"""
        return bool(self.config.get("exporter_api_url") and self.config.get("exporter_auth_key"))

    @command("zqwn")
    async def search_public_account(self, event: AstrMessageEvent,keyword: str = "最强蜗牛", size: int = 5):
        """搜索公众号作者，默认搜索“最强蜗牛”，返回前5个结果"""
        if not self._check_config():
            yield event.plain_result("❌ 插件未配置 API 地址或密钥，请联系管理员")
            return
        
        if keyword != "最强蜗牛":
            yield event.plain_result("❌ 目前仅支持搜索“最强蜗牛”公众号作者")
            return
         
        async with aiohttp.ClientSession() as session:
            headers = {"X-Auth-Key": self.config.get("exporter_auth_key")}
            params = {"keyword": keyword,"size": size}
            try:
                async with session.get(
                    f"{self.config.get('exporter_api_url')}/api/public/v1/account",
                    headers=headers,
                    params=params
                ) as resp:
                    data = await resp.json()
                    if data.get("base_resp").get("err_msg") == "ok":
                        datdList = data.get("list")
                        index = 1
                        result = f"搜索结果:"
                        authors = await self.get_kv_data("authors",{})
                        for item in datdList:
                            name = item.get("nickname")
                            if name in authors.keys():  # type: ignore
                                continue
                            fakeid = item.get("fakeid")
                            result += f"\n{index}: {name}"
                            self.authors[index] = {"name": name, "fakeid": fakeid}
                            index += 1
                        yield event.plain_result(result)
                    else:
                        logger.info(f"❌ 搜索失败: {data.get('base_resp').get('err_msg')}")
            except Exception as e:
                logger.error(f"搜索失败: {e}")

    @command("zqwn_add")
    async def add_saved_account(self, event: AstrMessageEvent, index: str):
        """将搜索结果中指定索引的公众号作者添加到保存列表"""
        authors = await self.get_kv_data("authors",{})
        data = self.authors.get(int(index))
        if not data:
            yield event.plain_result("❌ 无效的索引，请先使用 zqwn 命令搜索公众号作者")
            return
        name = data.get("name")
        fakeid = data.get("fakeid")
        authors[name] = fakeid  # type: ignore
        await self.put_kv_data("authors", authors)
        yield event.plain_result(f"✅ 已添加作者: {name}")

    @command("zqwn_list")
    async def list_saved_accounts(self, event: AstrMessageEvent):
        """列出已保存的公众号作者"""
        authors = await self.get_kv_data("authors",{})
        if not authors or len(authors) == 0:
            yield event.plain_result("❌ 请先使用 zqwn 命令搜索公众号作者")
            return
        
        result = "已保存的作者列表:"
        for name in authors.keys():
            result += f"\n- {name}"
        
        yield event.plain_result(result)

    async def get_saved_account(self):
        """获取已保存的公众号作者的最新文章"""
        authors = await self.get_kv_data("authors",{})
        if not authors or len(authors) == 0:
            return
        old_articles = await self.get_kv_data("articles",{})
        if not old_articles:
            old_articles = {}
        new_articles = {}
        updata_flag = False
        for name, fakeid in authors.items():
            logger.info(f"正在获取作者 {name} 的文章列表...")
            async with aiohttp.ClientSession() as session:
                headers = {"X-Auth-Key": self.config.get("exporter_auth_key")}
                params = {"fakeid": fakeid,"size": 1}
                try:
                    async with session.get(
                        f"{self.config.get('exporter_api_url')}/api/public/v1/article",
                        headers=headers,
                        params=params
                    ) as resp:
                        data = await resp.json()
                        if data.get("base_resp").get("err_msg") == "ok":
                            articles = data.get("articles")#设置了只获取1条文章
                            if articles is None or len(articles) == 0:
                                logger.info(f"❌ 作者 {name} 没有文章")
                                continue
                            article = articles[0]
                            aid = article.get("aid")
                            title = article.get("title")
                            digest = article.get("digest")
                            link = article.get("link")
                            if name in old_articles.keys():#是否添加过这个作者的文章
                                old_aid = old_articles[name].get("aid")
                                if old_aid == aid:
                                    logger.info(f"✅ 作者 {name} 未更新")
                                    continue
                                else:
                                    #发布了新文章
                                    updata_flag = True
                                    new_articles[name] = article
                                    logger.info(f"✅ 作者 {name} old_aid: {old_aid} aid: {aid} 发布了新文章: {article.get('title')}\n链接: {link}")
                                    await self._send_message(f"{link}")
                                    await self._send_message(f"作者: {name}\n文章标题: {title}\n文章简介: {digest}")#因为链接可能解析不出来，所以把文章信息也发出来
                            else:   
                                #发布了新文章
                                updata_flag = True
                                new_articles[name] = article
                                logger.info(f"✅ 作者 {name} aid: {aid} 发布了新文章: {article.get('title')}\n链接: {link}")
                                await self._send_message(f"{link}")
                                await self._send_message(f"作者: {name}\n文章标题: {title}\n文章简介: {digest}")#因为链接可能解析不出来，所以把文章信息也发出来
                        else:
                            logger.info(f"❌ 获取{name}的文章失败: {data.get('base_resp').get('err_msg')}")
                except Exception as e:
                    logger.error(f"获取公众号文章失败: {e}")
            base_delay = 6
            random_factor = random.uniform(-5, 5)
            delay = max(5, base_delay + random_factor) # 确保间隔至少为5秒
            logger.info(f"等待 {delay:.2f} 秒后继续获取下一个作者的文章...")
            await asyncio.sleep(delay)
        if not updata_flag:
            logger.info(f"没有新的文章更新")
        else:
            await self.put_kv_data("articles", new_articles)

    def _start_auto_updata_job(self):
        """根据配置的 Cron 表达式设置监控任务"""
        scheduler = self.scheduler
        if scheduler is None:
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
        
        self.scheduler.add_job(
            self.get_saved_account,
            trigger=trigger,
            id=job_id,
        )

        logger.info(f"已注册 Cron 监控：{updata_cron}")
    

    

    async def _send_message(self,message: str):
        """发送消息"""
        try:
            users = await self.get_kv_data("users",{})
            if not users or len(users) == 0:
                logger.warning("未配置推送用户，无法发送私聊消息")
                return
            for uid, user_info in users.items():
                if not user_info.get("enabled", False):
                    continue
                umo = user_info.get("umo")
                message_chain = MessageChain().message(message)
                await self.context.send_message(umo, message_chain)  # type: ignore
                logger.info(f"已发送消息给用户 {uid}: {message}")
        except Exception as e:
            logger.error(f"发送消息失败: {e}")
    
    @command("获取推送列表")
    async def get_push_list(self, event: AstrMessageEvent):
        """获取推送列表"""
        users = await self.get_kv_data("users",{})
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
    async def push_zqwn(self, event: AstrMessageEvent,enabled: str):
        """设置推送列表/开启或关闭推送"""
        group_id = getattr(event.message_obj, "group_id", None)
        user_name = event.get_sender_name()
        uid = group_id
        if not group_id or group_id == 0:
            uid = user_name
        users = await self.get_kv_data("users",{})
        if enabled not in ["开启", "关闭"]:
            yield event.plain_result("❌ 参数错误，请使用：推送zqwn 开启 或 推送zqwn 关闭")
            return
        if enabled == "开启":
            user_info = {
                "umo": event.unified_msg_origin,  # 保存统一会话ID
                "enabled": True
                }
            users[uid] = user_info  # type: ignore
            await self.put_kv_data("users", users)
            yield event.plain_result(f"✅ {uid} 已开启自动推送")
        else:
            user_info = {
                "umo": event.unified_msg_origin,  # 保存统一会话ID
                "enabled": False
                }
            users[uid] = user_info  # type: ignore
            await self.put_kv_data("users", users)
            yield event.plain_result(f"✅ {uid} 已关闭自动推送")
