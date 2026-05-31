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

from astrbot.api import AstrBotConfig, llm_tool, logger
from astrbot.api.event import AstrMessageEvent, MessageChain, filter
from astrbot.api.event.filter import (
    command,
    command_group,
)
from astrbot.api.star import Context, Star
from astrbot.core.message.components import Image, Node, Nodes, Plain
from astrbot.core.platform import MessageType as PlatformMessageType
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import (
    AiocqhttpMessageEvent,
)
from astrbot.core.utils.astrbot_path import (
    get_astrbot_data_path,
    get_astrbot_plugin_path,
    get_astrbot_temp_path,
)
from astrbot.core.utils.session_waiter import SessionController, session_waiter

from .code import parse_code
from .parse import Parse
from .sign_in import activity_gift_claim, binds_account, get_server, sign_request
from .utils import (
    convert_to_query_bytes,
    cron_to_human,
    decrypt_data,
    encrypt_data,
    get_week,
    send_msg,
)

PLUGIN_NAME = "astrbot_plugin_marvelous_snail"


class MarvelousSnailPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self.plugin_dir = Path(get_astrbot_plugin_path()) / PLUGIN_NAME
        self.data_dir = Path(get_astrbot_data_path()) / "plugin_data" / PLUGIN_NAME
        self.cache_dir = Path(get_astrbot_temp_path()) / PLUGIN_NAME
        self.randomizer = random.SystemRandom()
        self.scheduler = AsyncIOScheduler()
        self.authors = {}
        self.headers = self._parse_headers_config(config.get("headers", "{}"))
        self.style = None
        self._fugitives_data_cache: dict[str, Any] | None = None
        self._auto_sign_progress = {
            "running": False,
            "total_users": 0,
            "completed_users": 0,
            "current_user": None,
            "current_role": None,
            "started_at": None,
            "last_finished_at": None,
        }

    async def initialize(self):
        """插件初始化"""
        logger.info("最强蜗牛插件已加载")
        self.parse = Parse()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        try:
            import pillowmd

            style_dir = self._get_style_dir()
            if style_dir is not None:
                self.style = pillowmd.LoadMarkdownStyles(style_dir)
        except Exception as e:
            logger.error(f"无法加载 pillowmd 样式：{e}")

        # 设置定时任务
        # 1. 启动前先清理可能存在的旧任务，避免重复添加
        self.scheduler.remove_all_jobs()
        # 2.1 设置攻略更新监控任务,每小时执行一次
        if self.config.get("exporter_auth_key") and self.config.get("exporter_api_url"):
            await self._start_auto_job(
                "get_updata_job", "*/50 * * * *", self.get_saved_account
            )
        else:
            logger.warning("未配置 API 地址或密钥，已跳过攻略更新监控任务")
        # 2.2 设置每日自动签到任务 (如果配置了 headers)，每天八点10分执行一次
        if self.headers:
            await self._start_auto_job(
                "auto_sign_in_job", "10 8 * * *", self.auto_sign_in
            )
            await self._start_auto_job(
                "auto_activity_gift_job",
                "0 9 * * 5",
                self.auto_activity_gift_sign_in,
            )
            # headers心跳保持，每30分钟执行一次签到请求，保持 session 有效
            await self._start_auto_job(
                "keep_sign_in_job", "*/30 * * * *", sign_request, [self.headers]
            )
        else:
            logger.warning("未配置 headers，已跳过自动签到相关定时任务")
        if not self.scheduler.running:
            self.scheduler.start()

    async def terminate(self):
        """插件卸载"""
        logger.info("最强蜗牛插件已卸载")
        if self.scheduler.running:
            self.scheduler.shutdown()
            logger.info("调度器已关闭,已停止所有定时任务")

    async def _start_auto_job(self, job_id: str, cron_expr: str, func, args=None):
        """设置定时任务
        Args:
            job_id: 任务 ID，用于管理和识别任务
            cron_expr: Cron 表达式，定义任务的执行时间
            func: 任务函数，定时执行的异步函数
            args: 任务函数的参数列表，默认为 None
        Cron 表达式示例：0 0 * * *（每天凌晨0点执行）"""
        # 获取调度器实例
        scheduler = self.scheduler
        if scheduler is None:
            logger.error("Scheduler 未初始化")
            return

        # 1. 如果已存在同 ID 的任务，先删除旧任务，避免重复添加
        if scheduler.get_job(job_id):
            scheduler.remove_job(job_id)

        if not cron_expr:
            logger.debug(f"未配置 {job_id} 的 Cron 表达式，自动更新已禁用")
            return

        try:
            trigger = CronTrigger.from_crontab(cron_expr)
        except Exception as e:
            logger.error(f"Cron 表达式错误：{cron_expr} ({e})")
            return

        # 不用传参的情况，args 可能是 None，所以传一个空列表进去
        if args is None:
            args = []
        try:
            scheduler.add_job(
                func,
                trigger=trigger,
                id=job_id,
                args=args,
            )
            try:
                human_cron = cron_to_human(cron_expr)
                logger.info(f"{job_id} 已注册 Cron 监控：{cron_expr} ({human_cron})")
            except ValueError as e:
                logger.error(f"{job_id} 的 Cron 表达式错误：{cron_expr} ({e})")
        except Exception as e:
            logger.error(f"添加任务失败：{e}")

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

    def _parse_headers_config(self, raw_headers: Any) -> dict[str, Any]:
        """解析 headers 配置项，支持直接使用字典或字符串形式的字典"""
        if isinstance(raw_headers, dict):
            return raw_headers

        if not raw_headers:
            return {}

        if not isinstance(raw_headers, str):
            logger.warning(
                "headers 配置类型无效: %s，已回退为空字典", type(raw_headers).__name__
            )
            return {}

        try:
            parsed_headers = ast.literal_eval(raw_headers)
        except (SyntaxError, ValueError) as exc:
            logger.error("headers 配置解析失败，已回退为空字典: %s", exc)
            return {}

        if not isinstance(parsed_headers, dict):
            logger.warning("headers 配置不是字典，已回退为空字典")
            return {}

        return parsed_headers

    def _get_base_resp_error(self, payload: Any) -> str:
        """提取导出器 API 错误信息，用于日志记录和用户反馈"""
        if isinstance(payload, dict):
            base_resp = payload.get("base_resp")
            if isinstance(base_resp, dict):
                err_msg = base_resp.get("err_msg")
                if isinstance(err_msg, str) and err_msg.strip():
                    return err_msg
        return "未知错误"

    @staticmethod
    def _get_server_type_name(app_id: Any) -> str:
        """根据 app_id 返回服务器类型名称。"""
        if str(app_id) == "26":
            return "光子服"
        if str(app_id) == "39":
            return "官服"
        return "未知服"

    @staticmethod
    def _get_bound_app_id(user_data: dict[str, Any]) -> str:
        """读取绑定数据中的 app_id，兼容旧数据默认回退到官服。"""
        return str(user_data.get("app_id", "39"))

    @staticmethod
    def _format_role_info(user_data: dict[str, Any]) -> str:
        """格式化角色信息，用于日志和用户显示"""
        extra = user_data.get("extra")
        score = "未知"
        if isinstance(extra, dict) and extra.get("score") is not None:
            score = str(extra.get("score"))

        server_name = user_data.get("server_name", "未知区服")
        role_name = user_data.get("role_name", "未知角色")
        server_type = MarvelousSnailPlugin._get_server_type_name(
            user_data.get("app_id")
        )
        return f"[{server_type}] {server_name}-{role_name}:{score}"

    def _set_auto_sign_progress(
        self,
        *,
        running: bool,
        total_users: int | None = None,
        completed_users: int | None = None,
        current_user: str | None = None,
        current_role: str | None = None,
        started_at: float | None = None,
        last_finished_at: float | None = None,
    ) -> None:
        """更新定时签到进度状态。"""
        progress = self._auto_sign_progress
        progress["running"] = running
        if total_users is not None:
            progress["total_users"] = total_users
        if completed_users is not None:
            progress["completed_users"] = completed_users
        progress["current_user"] = current_user
        progress["current_role"] = current_role
        if started_at is not None:
            progress["started_at"] = started_at
        if last_finished_at is not None:
            progress["last_finished_at"] = last_finished_at

    def _format_auto_sign_progress(self) -> str:
        """格式化当前定时签到进度。"""
        progress = self._auto_sign_progress
        if progress["running"]:
            current_user = progress.get("current_user") or "暂未开始具体用户"
            current_role = progress.get("current_role") or "暂未定位具体角色"
            return (
                "【定时签到进度】\n"
                f"状态: 进行中\n"
                f"进度: {progress.get('completed_users', 0)}/{progress.get('total_users', 0)}\n"
                f"当前用户: {current_user}\n"
                f"当前角色: {current_role}"
            )

        last_finished_at = progress.get("last_finished_at")
        if last_finished_at:
            finished_time = time.strftime(
                "%Y-%m-%d %H:%M:%S", time.localtime(last_finished_at)
            )
            return (
                "【定时签到进度】\n"
                "状态: 空闲\n"
                f"上次执行: {finished_time}\n"
                f"上次进度: {progress.get('completed_users', 0)}/{progress.get('total_users', 0)}"
            )

        return "【定时签到进度】\n状态: 当前没有进行中的定时签到"

    def _get_style_dir(self) -> Path | None:
        """获取状态图渲染样式目录。

        优先使用插件自身样式，如果不存在则回退为 None，此时调用渲染方法会自动退回文本输出，保证插件核心功能不受影响。同时也允许用户自行放置符合规范的
        pillowmd 样式，保证状态图和汇总图仍然可以正常渲染。
        """
        style_dir = self.plugin_dir / "pillowmd_style"
        if style_dir.exists():
            return style_dir

        logger.warning("未找到可用的 pillowmd 样式目录，状态输出将回退为文本")
        return None

    async def _send_status_card(
        self,
        event: AstrMessageEvent,
        content: str,
        *,
        msg: str | None = None,
    ) -> None:
        """向当前会话发送状态卡。

        这里主要服务于“查询绑定”等会话内命令：优先渲染成图片发送，渲染失败时
        自动退回纯文本，避免因为样式或 pillowmd 异常导致命令不可用。
        """
        await self._send_markdown_card(event, content, msg=msg, stop_event=True)

    def _build_markdown_render_text(self, content: str, msg: str | None = None) -> str:
        """构造用于图片渲染的 Markdown 文本。"""
        return content if not msg else f"# {msg}\n\n{content}"

    @staticmethod
    def _is_exit_command(text: str) -> bool:
        """判断用户是否主动退出当前交互流程。"""
        return text.strip() in {"退出", "取消", "q", "Q"}

    def _split_markdown_chunks(self, content: str, max_lines: int = 50) -> list[str]:
        """按行数切分 Markdown，避免单张图片过长。"""
        lines = content.splitlines()
        if len(lines) <= max_lines:
            return [content]

        chunks = []
        for index in range(0, len(lines), max_lines):
            chunk = "\n".join(lines[index : index + max_lines]).strip()
            if chunk:
                chunks.append(chunk)
        return chunks or [content]

    async def _render_markdown_chunks(self, content: str) -> list[str]:
        """将 Markdown 分片渲染为多张图片，返回图片路径列表。"""
        style = self.style
        if style is None:
            raise RuntimeError("Markdown style is not available")

        image_paths: list[str] = []
        for chunk in self._split_markdown_chunks(content):
            img = await style.AioRender(text=chunk, useImageUrl=True)
            img_path = img.Save(self.cache_dir)
            image_paths.append(str(img_path))
        return image_paths

    def _build_forward_nodes(
        self, image_paths: list[str], name: str, uin: str
    ) -> Nodes:
        """根据图片列表构造聊天记录节点。"""
        nodes = [
            Node(name=name, uin=uin, content=[Image.fromFileSystem(image_path)])
            for image_path in image_paths
        ]
        return Nodes(nodes=nodes)

    def _build_text_forward_nodes(
        self,
        chunks: list[str],
        name: str,
        uin: str,
    ) -> Nodes:
        """根据文本分片构造聊天记录节点。"""
        nodes = [
            Node(name=name, uin=uin, content=[Plain(chunk)])
            for chunk in chunks
            if chunk.strip()
        ]
        return Nodes(nodes=nodes)

    async def _send_forward_images_for_event(
        self,
        event: AstrMessageEvent,
        image_paths: list[str],
    ) -> None:
        """向当前会话发送图片聊天记录。"""
        sender_uin = event.get_self_id() or "0"
        forward = self._build_forward_nodes(image_paths, "最强蜗牛攻略", sender_uin)
        await event.send(event.chain_result([forward]))

    async def _send_forward_text_for_event(
        self,
        event: AstrMessageEvent,
        chunks: list[str],
        *,
        name: str = "最强蜗牛密令",
    ) -> None:
        """向当前会话发送文本聊天记录。"""
        sender_uin = event.get_self_id() or "0"
        forward = self._build_text_forward_nodes(chunks, name, sender_uin)
        await event.send(event.chain_result([forward]))

    async def _send_forward_images_to_target(
        self,
        target: str,
        image_paths: list[str],
    ) -> None:
        """向指定目标发送图片聊天记录。"""
        forward = self._build_forward_nodes(image_paths, "最强蜗牛签到", "0")
        await self.context.send_message(target, MessageChain(chain=[forward]))  # type: ignore

    def _load_valid_codes(self) -> list[str]:
        """读取当前有效密令列表。"""
        data_dir_str = get_astrbot_data_path()
        plugin_data_path = Path(data_dir_str) / "plugin_data" / self.name
        codes_dir = plugin_data_path / "codes"
        codes_file = codes_dir / "codes.json"
        codes: dict[str, Any] = {}
        if codes_file.exists():
            try:
                with codes_file.open("r", encoding="utf-8") as f:
                    data = json.load(f)
                    payload = data.get("code", {}) if isinstance(data, dict) else {}
                    if isinstance(payload, dict):
                        codes = payload
            except Exception as e:
                logger.error(f"读取密令数据失败: {e}")
        return list(codes.keys())

    def _split_codes_chunks(
        self, codes_list: list[str], chunk_size: int = 50
    ) -> list[str]:
        """按指定数量切分密令列表，适配聊天记录发送。"""
        chunks = []
        for index in range(0, len(codes_list), chunk_size):
            chunk_codes = codes_list[index : index + chunk_size]
            if not chunk_codes:
                continue
            chunks.append("\n".join(chunk_codes))
        return chunks

    async def _send_codes_to_event(self, event: AstrMessageEvent) -> None:
        """向当前会话发送有效密令列表。"""
        codes_list = self._load_valid_codes()
        if not codes_list:
            await event.send(event.plain_result("❌ 当前没有可用密令"))
            return

        if len(codes_list) > 50:
            await self._send_forward_text_for_event(
                event,
                self._split_codes_chunks(codes_list, 50),
            )
            return

        await event.send(event.plain_result("\n".join(codes_list)))

    async def _send_markdown_card(
        self,
        event: AstrMessageEvent,
        content: str,
        *,
        msg: str | None = None,
        stop_event: bool = False,
    ) -> None:
        """向当前会话发送 Markdown 卡片，可按需选择是否停止事件。"""
        chain = []

        if msg:
            chain.append(Plain(msg))

        if self.style:
            try:
                render_text = self._build_markdown_render_text(content, msg)
                image_paths = await self._render_markdown_chunks(render_text)
                if len(image_paths) > 1:
                    await self._send_forward_images_for_event(event, image_paths)
                else:
                    single_text = content
                    if msg:
                        single_text = self._build_markdown_render_text(content, None)
                    image_paths = await self._render_markdown_chunks(single_text)
                    img_path = image_paths[0]
                    chain = []
                    if msg:
                        chain.append(Plain(msg))
                    chain.append(Image(str(img_path)))
                    await event.send(event.chain_result(chain))
                if stop_event:
                    event.stop_event()
                return
            except Exception as e:
                logger.error(f"渲染状态卡失败，已回退文本输出：{e}")

        fallback = f"{msg}\n\n{content}" if msg else content
        await event.send(event.plain_result(fallback))
        if stop_event:
            event.stop_event()

    async def _send_rendered_message(
        self,
        target: str,
        content: str,
        *,
        msg: str | None = None,
        extra_image_path: str | None = None,
    ) -> None:
        """向指定目标发送渲染后的图片消息。

        这个方法和 _send_status_card 的区别在于它不依赖 event，适合定时任务。
        当前用于定时签到汇总：先发送汇总图，再按需在同一消息链后追加“今日奖励”图。
        """
        if self.style:
            try:
                render_text = self._build_markdown_render_text(content, msg)
                image_paths = await self._render_markdown_chunks(render_text)
                if extra_image_path:
                    image_paths.append(extra_image_path)
                if len(image_paths) > 1:
                    await self._send_forward_images_to_target(target, image_paths)
                else:
                    message_chain = MessageChain().file_image(image_paths[0])
                    await self.context.send_message(target, message_chain)  # type: ignore
                return
            except Exception as e:
                logger.error(f"渲染推送图片失败，已回退文本输出：{e}")

        fallback = f"{msg}\n\n{content}" if msg else content
        message_chain = MessageChain().message(fallback)
        if extra_image_path:
            message_chain.file_image(extra_image_path)
        await self.context.send_message(target, message_chain)  # type: ignore

    def _get_today_reward_image_path(self) -> str:
        """根据当前星期返回今日奖励配图路径。"""
        weeks = [
            "Monday.png",
            "Tuesday.png",
            "Wednesday.png",
            "Thursday.png",
            "Friday.png",
            "Saturday.png",
            "Sunday.png",
        ]
        return str(self.plugin_dir / "week" / weeks[get_week()])

    def _get_user_dir(self) -> Path:
        return self.data_dir / "users"

    def _get_user_file(self, user_id: str) -> Path:
        return self._get_user_dir() / f"{user_id}.json"

    def _load_user_data(self, user_id: str) -> dict[str, Any] | None:
        user_file = self._get_user_file(user_id)
        if not user_file.exists():
            return None

        try:
            with user_file.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            logger.error(f"读取用户数据失败: {e}")
            return None

        if not isinstance(data, dict):
            logger.error(f"用户 {user_id} 的数据格式错误")
            return None

        return data

    def _save_user_data(self, user_id: str, data: dict[str, Any]) -> bool:
        user_file = self._get_user_file(user_id)
        user_file.parent.mkdir(parents=True, exist_ok=True)

        try:
            with user_file.open("w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
            return True
        except Exception as e:
            logger.error(f"写入用户数据失败: {e}")
            return False

    def _build_sign_status(self, state: str, message: str) -> dict[str, Any]:
        """构造统一的签到状态记录结构，便于后续落盘与展示。"""
        return {
            "state": state,
            "message": message,
            "updated_at": int(time.time()),
        }

    def _is_sign_success(self, sign_result: Any) -> bool:
        """判断签到接口结果是否应视为成功。

        除了标准 code=200 外，游戏接口返回“很抱歉,已经领取过了”时也表示今天的
        奖励已经到账，因此在业务上同样视作成功，避免状态卡和汇总统计出现误判。
        """
        if not isinstance(sign_result, dict):
            return False

        if sign_result.get("code") == 200:
            return True

        message = str(sign_result.get("message", ""))
        return "很抱歉,已经领取过了" in message

    def _set_user_sign_status(
        self, user: dict[str, Any], state: str, message: str
    ) -> None:
        user["sign_status"] = self._build_sign_status(state, message)

    def _summarize_activity_gift_results(
        self, gift_results: Any
    ) -> dict[str, Any]:
        """汇总活动礼包领取结果。"""
        if not isinstance(gift_results, list):
            return {
                "success_count": 0,
                "failed_count": 1,
                "messages": ["活动礼包领取结果无效"],
                "claimed_gifts": [],
                "failed_gifts": [],
            }

        success_count = 0
        failed_count = 0
        messages: list[str] = []
        claimed_gifts: list[str] = []
        failed_gifts: list[str] = []
        for result in gift_results:
            if not isinstance(result, dict):
                failed_count += 1
                messages.append("活动礼包领取结果格式异常")
                continue

            message = str(result.get("message", "未知结果"))
            messages.append(message)
            gift_name = str(result.get("gift_name", "")).strip()
            if result.get("code") == 200:
                success_count += 1
                if gift_name:
                    claimed_gifts.append(gift_name)
            else:
                failed_count += 1
                if gift_name:
                    failed_gifts.append(gift_name)

        return {
            "success_count": success_count,
            "failed_count": failed_count,
            "messages": messages,
            "claimed_gifts": claimed_gifts,
            "failed_gifts": failed_gifts,
        }

    async def _claim_activity_gifts_for_role(
        self, game_id: str, role_id: str
    ) -> dict[str, Any]:
        """执行单个角色的活动礼包领取。"""
        if not self.headers:
            return {
                "success_count": 0,
                "failed_count": 1,
                "messages": ["未配置活动礼包请求头"],
                "claimed_gifts": [],
                "failed_gifts": [],
                "has_claim_attempt": True,
            }

        gift_results = await activity_gift_claim(self.headers, game_id, role_id)
        if not gift_results:
            return {
                "success_count": 0,
                "failed_count": 0,
                "messages": ["没有可领取的活动礼包"],
                "claimed_gifts": [],
                "failed_gifts": [],
                "has_claim_attempt": False,
            }

        summary = self._summarize_activity_gift_results(gift_results)
        return {
            "success_count": summary["success_count"],
            "failed_count": summary["failed_count"],
            "messages": summary["messages"],
            "claimed_gifts": summary["claimed_gifts"],
            "failed_gifts": summary["failed_gifts"],
            "has_claim_attempt": True,
        }

    def _format_sign_status(self, user: dict[str, Any]) -> tuple[str, str, str]:
        sign_status = user.get("sign_status")
        if not isinstance(sign_status, dict):
            return "暂无记录", "尚未产生签到结果", "--"

        state = sign_status.get("state", "unknown")
        message = str(sign_status.get("message", "无详细信息"))
        updated_at = sign_status.get("updated_at")
        updated_text = "--"
        if isinstance(updated_at, int | float):
            updated_text = time.strftime(
                "%Y-%m-%d %H:%M:%S", time.localtime(updated_at)
            )

        state_text = {
            "success": "已签到",
            "failed": "签到失败",
            "invalid": "数据异常",
            "pending": "待签到",
        }.get(state, "暂无记录")
        return state_text, message, updated_text

    def _get_group_sign_push_targets(self) -> list[str]:
        """读取已登记的群聊汇总推送目标。"""
        data = self.read_file("push_datas", "sign.json") or {}
        datas = data.get("datas", []) if isinstance(data, dict) else []
        if not isinstance(datas, list):
            return []
        group_flag = f":{PlatformMessageType.GROUP_MESSAGE.value}:"
        return [
            target
            for target in datas
            if isinstance(target, str) and group_flag in target
        ]

    def _get_author_cache_dir(self) -> Path:
        """返回攻略作者缓存目录。"""
        return self.data_dir / "authors"

    def _get_author_cache_file(self, author: str) -> Path:
        """返回作者缓存文件路径。"""
        return self._get_author_cache_dir() / f"{author}.json"

    def _load_author_cache_payload(self, author: str) -> dict[str, Any] | None:
        """读取作者缓存文件。"""
        author_file = self._get_author_cache_file(author)
        if not author_file.exists():
            return None

        try:
            with author_file.open("r", encoding="utf-8") as f:
                payload = json.load(f)
        except Exception as e:
            logger.error(f"读取作者缓存 {author_file} 失败: {e}")
            return None

        if not isinstance(payload, dict):
            logger.warning(f"作者缓存文件格式无效: {author_file}")
            return None
        return payload

    def _compact_author_article(self, article: dict[str, Any]) -> dict[str, Any] | None:
        """提取攻略搜索真正需要的字段，减少本地冗余存储。"""
        title = str(article.get("title", "")).strip()
        link = str(article.get("link", "")).strip()
        if not title or not link:
            return None

        compacted: dict[str, Any] = {
            "title": title,
            "link": link,
        }

        aid = article.get("aid")
        if aid not in (None, ""):
            compacted["aid"] = aid

        digest = str(article.get("digest", "")).strip()
        if digest:
            compacted["digest"] = digest

        for field in ("update_time", "create_time"):
            value = article.get(field)
            if isinstance(value, int | float):
                compacted[field] = int(value)

        return compacted

    def _get_author_cache_key(self, article: dict[str, Any]) -> tuple[str, str] | None:
        """生成文章缓存主键，优先使用 aid 以便覆盖作者二次编辑后的新链接。"""
        aid = article.get("aid")
        if aid not in (None, ""):
            return ("aid", str(aid))

        title = str(article.get("title", "")).strip()
        if title:
            return ("title", title)

        link = str(article.get("link", "")).strip()
        if link:
            return ("link", link)

        return None

    def _merge_author_articles(
        self,
        existing_articles: list[dict[str, Any]],
        incoming_articles: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """合并作者文章缓存，覆盖旧链接并移除已删除文章。"""
        article_map: dict[tuple[str, str], dict[str, Any]] = {}

        for article in existing_articles:
            if not isinstance(article, dict):
                continue
            cache_key = self._get_author_cache_key(article)
            if cache_key is None:
                continue
            compacted = self._compact_author_article(article)
            if compacted is None:
                continue
            article_map[cache_key] = compacted

        for article in incoming_articles:
            if not isinstance(article, dict):
                continue
            cache_key = self._get_author_cache_key(article)
            if cache_key is None:
                continue
            if article.get("is_deleted") is True:
                article_map.pop(cache_key, None)
                continue
            compacted = self._compact_author_article(article)
            if compacted is None:
                continue
            article_map[cache_key] = compacted

        merged_articles = list(article_map.values())
        merged_articles.sort(
            key=lambda item: (
                item.get("update_time")
                or item.get("create_time")
                or item.get("aid")
                or 0
            ),
            reverse=True,
        )
        return merged_articles

    def _render_author_selection_markdown(self, authors: list[str]) -> str:
        """渲染作者选择卡片。"""
        lines = [
            "# 攻略作者列表",
            "请回复编号选择作者：",
            "回复 退出 或 取消 可结束当前流程。",
            "",
        ]
        for index, author in enumerate(authors, start=1):
            lines.append(f"{index}. {author}")
        return "\n".join(lines)

    def _render_strategy_search_markdown(
        self,
        author: str,
        keyword: str,
        results: list[dict[str, Any]],
    ) -> str:
        """渲染攻略搜索结果卡片。"""
        lines = [
            "# 攻略搜索结果",
            f"- 作者: {author}",
            f"- 关键词: {keyword}",
            f"- 命中数量: {len(results)}",
        ]

        lines.extend(["", "## 结果列表"])
        for index, article in enumerate(results, start=1):
            title = str(article.get("title", "未命名文章")).strip()
            digest = str(article.get("digest", "")).strip()
            lines.append(f"### {index}. {title}")
            if digest:
                lines.append(f"- 简介: {digest}")
            lines.append("")

        lines.append("请回复编号选择文章。")
        lines.append("回复 退出 或 取消 可结束当前流程。")
        return "\n".join(lines).strip()

    def _get_latest_strategy_article(
        self, articles: list[dict[str, Any]]
    ) -> dict[str, Any] | None:
        """从文章列表中选出最新且未删除的文章，用于更新通知。"""
        available_articles = [
            article
            for article in articles
            if isinstance(article, dict)
            and article.get("is_deleted") is not True
            and article.get("author_name") != "广告"
        ]
        if not available_articles:
            return None

        available_articles.sort(
            key=lambda item: (
                item.get("update_time")
                or item.get("create_time")
                or item.get("aid")
                or 0
            ),
            reverse=True,
        )
        return available_articles[0]

    async def _sync_author_articles(
        self, author: str, fakeid: str
    ) -> list[dict[str, Any]] | None:
        """按作者同步文章列表，用于修正旧链接并清理已删除文章。"""
        if not self._check_config() or not fakeid:
            return None

        fetched_articles: list[dict[str, Any]] = []
        begin = 0
        page_size = 20
        headers = {"X-Auth-Key": self.config.get("exporter_auth_key")}
        api_url = self.config.get("exporter_api_url")

        async with aiohttp.ClientSession() as session:
            while True:
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
                    fetched_articles.append(article)

                if len(articles) < page_size:
                    break
                begin += page_size
                await asyncio.sleep(random.uniform(1, 3))

        await self.save_strategy(author, fetched_articles, synced_at=int(time.time()))
        return fetched_articles

    def _render_user_status_markdown(
        self, user_id: str, users: list[dict[str, Any]]
    ) -> str:
        lines = [
            "# 最强蜗牛用户状态",
            f"- 用户ID: {user_id}",
            f"- 已绑定账号: {len(users)}",
            "",
            "## 账号状态",
        ]

        for index, user in enumerate(users, start=1):
            info = str(user.get("info", "未知角色"))
            state_text, message, updated_text = self._format_sign_status(user)
            lines.extend(
                [
                    f"### {index}. {info}",
                    f"- 签到状态: {state_text}",
                    f"- 最近更新: {updated_text}",
                    f"- 详情: {message}",
                    "",
                ]
            )

        return "\n".join(lines).strip()

    def _load_fugitives_data(self) -> dict[str, Any] | None:
        """读取特工逃犯数据文件，返回包含逃犯信息的字典"""
        if self._fugitives_data_cache is not None:
            return self._fugitives_data_cache

        try:
            data = self.read_file("fugitives", "fugitives.json")
        except Exception as e:
            logger.error(f"读取逃犯数据文件失败: {e}")
            return None

        if not isinstance(data, dict):
            logger.error("逃犯数据文件格式错误，根节点必须是字典")
            return None

        self._fugitives_data_cache = data
        return data

    @staticmethod
    def _format_fugitive_result(item: dict[str, Any]) -> str:
        """格式化逃犯信息，用于日志和用户显示"""
        lines = [
            f"逃犯：{item.get('name', '未知')}",
            f"等级：{item.get('level', '未知')}",
        ]

        ba_capture_reward = item.get("ba_capture_reward")
        ba_revenge_reward = item.get("ba_revenge_reward")
        bb_thanks_reward = item.get("bb_thanks_reward")

        if ba_capture_reward:
            lines.append(f"BA 抓住奖励：{ba_capture_reward}")
        if ba_revenge_reward:
            lines.append(f"BA 报复奖励：{ba_revenge_reward}")
        if bb_thanks_reward:
            lines.append(f"BB 感谢奖励：{bb_thanks_reward}")

        return "\n".join(lines)

    @command_group("最强蜗牛")
    def zqwn(self):
        """最强蜗牛攻略相关功能
        搜索，添加，删除，查看攻略作者
        """
        pass

    @filter.permission_type(filter.PermissionType.ADMIN)
    @zqwn.command("作者搜索")
    async def search_public_account(
        self, event: AstrMessageEvent, keyword: str = "最强蜗牛", size: int = 5
    ):
        """搜索作者，默认搜索“最强蜗牛”，返回前5个结果
        Args:
            keyword: 搜索关键词，默认为“最强蜗牛”
            size: 返回结果数量，默认为5
        """
        if event.get_message_type() != PlatformMessageType.FRIEND_MESSAGE:
            yield event.plain_result(
                "⚠️ 该指令仅限私聊使用。\n请私聊发送“最强蜗牛 作者搜索”。"
            )
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
                            # 处理成功响应
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
                                self.authors[index] = {"name": name, "fakeid": fakeid}
                                index += 1
                            if index == 1:
                                yield event.plain_result("❌ 未找到可添加的公众号作者")
                                return
                            yield event.plain_result(result)
                        else:
                            # 处理失败响应
                            err_msg = self._get_base_resp_error(data)
                            logger.warning("搜索公众号作者失败: %s", err_msg)
                            yield event.plain_result(f"❌ 搜索失败: {err_msg}")
                    except (ValueError, KeyError) as e:
                        logger.error(f"API 响应解析失败: {e}")
            except Exception as e:
                logger.error(f"搜索失败: {e}")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @zqwn.command("作者添加")
    async def add_saved_account(self, event: AstrMessageEvent, index: str):
        """将搜索结果中指定索引的公众号作者添加到保存列表
        Args:
            index: 搜索结果中的索引
        """
        if event.get_message_type() != PlatformMessageType.FRIEND_MESSAGE:
            yield event.plain_result(
                "⚠️ 该指令仅限私聊使用。\n请私聊发送“最强蜗牛 作者添加”。"
            )
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

    @filter.permission_type(filter.PermissionType.ADMIN)
    @zqwn.command("作者删除")
    async def del_saved_account(self, event: AstrMessageEvent, name: str):
        """从保存列表中删除指定名字的公众号作者
        Args:
            name: 作者名称
        """
        if event.get_message_type() != PlatformMessageType.FRIEND_MESSAGE:
            yield event.plain_result(
                "⚠️ 该指令仅限私聊使用。\n请私聊发送“最强蜗牛 作者删除”。"
            )
            return
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

    @filter.permission_type(filter.PermissionType.ADMIN)
    @zqwn.command("作者列表")
    async def list_saved_accounts(self, event: AstrMessageEvent):
        """列出已保存的公众号作者"""
        if event.get_message_type() != PlatformMessageType.FRIEND_MESSAGE:
            yield event.plain_result(
                "⚠️ 该指令仅限私聊使用。\n请私聊发送“最强蜗牛 作者列表”。"
            )
            return
        authors = await self.get_kv_data("authors", {})
        if not authors or len(authors) == 0:
            yield event.plain_result("❌ 请先使用 zqwn 命令搜索公众号作者")
            return

        result = "已保存的作者列表:"
        for name in authors.keys():
            result += f"\n- {name}"

        yield event.plain_result(result)

    async def get_saved_account(self):
        """定时全量修正作者文章缓存，并在检测到最新文章变化时推送通知。"""
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
            title = str(article.get("title", ""))
            digest = str(article.get("digest", ""))
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
                    await self._send_message(
                        f"作者: {name}\n文章标题: {title}\n文章简介: {digest}\n链接: {link}"
                    )
                    if name == "最强蜗牛":
                        code_info = await self.get_code(link)
                        code = code_info.get("code")
                        if code and len(code) > 0:
                            send_txt = f"密令:{code}"
                            if code_info.get("share") and digest:
                                send_txt += f"\n{digest}"
                                self.write_codes(digest.split("密令：")[-1])
                            await self._send_message(send_txt)
            else:
                updata_flag = True
                new_articles[name] = article
                logger.debug(
                    f"✅ 作者 {name} aid: {aid} 发布了新文章: {article.get('title')}\n链接: {link}"
                )
                await self._send_message(
                    f"作者: {name}\n文章标题: {title}\n文章简介: {digest}\n链接: {link}"
                )
                if name == "最强蜗牛":
                    code_info = await self.get_code(link)
                    code = code_info.get("code")
                    if code and len(code) > 0:
                        send_txt = f"密令:{code}"
                        if code_info.get("share") and digest:
                            send_txt += f"\n{digest}"
                            self.write_codes(digest.split("密令：")[-1])
                        await self._send_message(send_txt)
            base_delay = 6
            random_factor = random.uniform(-5, 5)
            delay = max(5, base_delay + random_factor)  # 确保间隔至少为5秒
            logger.debug(f"等待 {delay:.2f} 秒后继续获取下一个作者的文章...")
            await asyncio.sleep(delay)
        if not updata_flag:
            logger.debug("没有新的文章更新")
        else:
            await self.put_kv_data("articles", new_articles)

    async def _send_message(self, message: str):
        """发送消息
        Args:
            message: 要发送的消息内容
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

    @filter.permission_type(filter.PermissionType.ADMIN)
    @zqwn.command("攻略推送列表")
    async def get_push_list(self, event: AstrMessageEvent):
        """攻略推送列表"""
        if event.get_message_type() != PlatformMessageType.FRIEND_MESSAGE:
            yield event.plain_result(
                "⚠️ 该指令仅限私聊使用。\n请私聊发送“最强蜗牛 攻略推送列表”。"
            )
            return
        # 读取推送文件夹
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

    @zqwn.command("攻略推送")
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
        # 读取推送文件夹
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
        """保存攻略数据到本地 JSON 文件，按作者分类保存
        Args:
            authors: 作者名称
            write_data: 要保存的数据
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
        # 4.尝试写入文件
        try:
            with authors_file.open("w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
        except Exception as e:
            logger.error(f"写入 {authors}.json 失败: {e}")

    @zqwn.command("搜索攻略")
    async def get_strategy(self, event: AstrMessageEvent, parse_str: str):
        """获取已保存的文章列表，选择后发送文章详情
        Args:
            parse_str: 搜索关键词
        """
        user_stage = "select_author"
        selected_author = None
        strategy_map: dict[int, tuple[str, str]] = {}
        plugin_data_path = self._get_author_cache_dir()
        if not plugin_data_path.exists():
            logger.info("攻略缓存目录不存在，当前没有可查询数据")
            await event.send(event.plain_result("❌ 暂无数据存储"))
            return
        # 获取目录下的所有json文件名
        json_files = list(plugin_data_path.glob("*.json"))
        # 去掉扩展名后的文件名作为作者列表
        authors = [file.stem for file in json_files]
        if not authors or len(authors) == 0:
            logger.info("没有已保存的作者和文章数据，请先添加作者并等待更新")
            await event.send(event.plain_result("❌ 暂无数据存储"))
            return
        await self._send_markdown_card(
            event,
            self._render_author_selection_markdown(authors),
        )
        # 如果是群聊记录用户ID
        group_id = getattr(event.message_obj, "group_id", None)
        user_id = None
        if group_id and group_id != 0:
            user_id = event.get_sender_id()
            user_id = user_id.replace("/", "_")

        @session_waiter(timeout=60)
        async def articles_waiter(
            controller: SessionController, event: AstrMessageEvent
        ):
            # Drive the author-selection and article-selection states in one waiter.
            nonlocal user_stage, selected_author, strategy_map
            now_user_id = event.get_sender_id()
            now_user_id = now_user_id.replace("/", "_")
            if user_id and now_user_id != user_id:
                return
            # 可能获取的是正在输入情况，不撤回，不进行后续流程
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
                if not result or not result.get("data"):
                    message = (
                        result.get("msg", f"❌ 作者 {selected_author} 没有文章数据")
                        if isinstance(result, dict)
                        else f"❌ 作者 {selected_author} 没有文章数据"
                    )
                    await event.send(
                        event.plain_result(f"{message}\n请重新选择作者，或回复 退出 结束流程")
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
                controller.keep(
                    timeout=60, reset_timeout=True
                )  # 重置超时时间，等待用户选择文章
            elif user_stage == "select_article":
                arg = event.message_str.strip()
                parts = arg.split()
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
        except TimeoutError as _:
            logger.warning("选择超时！")
            await event.send(event.plain_result("❌ 选择超时，终止运行"))
        except Exception as e:
            logger.error("选择发生错误" + str(e))
        event.stop_event()

    @zqwn.command("特工逃犯")
    async def get_fugitives(self, event: AstrMessageEvent, name: str):
        """获取特工逃犯信息
        Args:
            name: 逃犯名称"""
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

    @llm_tool("send_code")
    async def send_code(self, event: AstrMessageEvent) -> None:
        """发送当前有效密令列表。仅在用户明确要求查看密令列表时才调用。

        调用前请严格判断：
        1. 用户是否明确要求查看当前有效密令、兑换码列表、全部密令？
        2. 如果用户只是闲聊、询问攻略、绑定账号、签到、特工逃犯等其他功能，请不要调用此工具。
        3. 如果用户只是提到“密令”但意图不明确，请先询问用户是否需要查看当前有效密令列表。
        4. 如果用户是在询问某一条密令的来源、使用方式、失效原因，或让你解释密令内容，请不要调用此工具，应直接回答。

        Args:
            event(object): 当前消息事件。
        """
        await self._send_codes_to_event(event)

    @command("绑定账号")
    async def get_headers(self, event: AstrMessageEvent, account: str):
        """
        获取账号的请求头信息，查询账号绑定的角色，选择角色后绑定账号并保存数据
        Args:
            account: 账号"
        """

        # 撤回用户发送的消息，避免泄露账号信息
        if isinstance(event, AiocqhttpMessageEvent):  # 判断aiocqhttp平台
            user_message_id = event.message_obj.message_id
            if user_message_id:
                try:
                    await event.bot.delete_msg(message_id=int(user_message_id))
                except Exception as e:
                    logger.error(f"撤回用户消息失败: {e}")

        if not self.headers:
            logger.warning("尝试绑定账号，但插件未配置可用的 headers")
            await event.send(
                event.plain_result("❌ 未配置签到请求头，暂时无法绑定账号")
            )
            return

        info = "【个人信息处理告知】\
            \n你当前申请绑定账号用于本机器人无偿每日签到服务，我方依据《个人信息保护法》向你完整告知：\
            \n1. 处理数据范围：仅存储你的【手机号、游戏角色ID】，无任何多余信息收集。\
            \n2. 存储期限：**账号绑定存续期间全程存储**，你随时可申请删除，删除后全部数据永久清除无备份。\
            \n3. 数据安全：所有数据服务器端**AES加密存储**，不明文存储、不泄露、不转卖、不共享、不对外传输任何第三方。\
            \n4. 你的全部法定权利：随时查询本人数据、随时一键删除全部数据、撤回本次授权。\
            \n5. 本服务全程无偿、无商业盈利、非经营性个人互助服务。\
            \n6. 风险提示：可能存在账号被封或奖励追回风险，请谨慎评估后自愿授权绑定,风险自负。\
            \n请你确认全部内容并自愿授权，后续【选择角色】即视为自愿授权信息并完成完成绑定。"
        await event.send(event.plain_result(info))
        users_data = await get_server(account)
        if users_data is None or len(users_data) == 0:
            await event.send(event.plain_result("❌ 获取数据失败，请检查账号是否正确"))
            return
        # 配置角色菜单信息供用户选择
        select_info = "选择需要绑定的角色:\n回复 退出 或 取消 可结束当前流程。"
        id = 1
        for user_data in users_data:
            select_info += f"\n{id}. {self._format_role_info(user_data)}"
            id += 1
        message_id = await send_msg(event, select_info)
        # 如果是群聊记录用户ID,需要撤回
        group_id = getattr(event.message_obj, "group_id", None)
        user_id = None
        if group_id and group_id != 0:
            user_id = event.get_sender_id()
            user_id = user_id.replace("/", "_")

        @session_waiter(timeout=60)
        async def bind_waiter(controller: SessionController, event: AstrMessageEvent):
            nonlocal message_id, user_id
            now_user_id = event.get_sender_id()
            now_user_id = now_user_id.replace("/", "_")
            if user_id and now_user_id != user_id:
                return
            # 可能获取的是正在输入情况，不撤回，不进行后续流程
            arg = event.message_str.strip()
            parts = arg.split()
            if len(parts) == 0:
                return
            if self._is_exit_command(arg):
                await event.send(event.plain_result("✅ 已退出绑定流程"))
                controller.stop()
                return
            if isinstance(event, AiocqhttpMessageEvent):  # 判断aiocqhttp平台
                if message_id:
                    await event.bot.delete_msg(message_id=int(message_id))
                    message_id = None

            if len(parts) == 1 and parts[0].isdigit():
                index = int(parts[0])
                if index < 1 or index > len(users_data):
                    return
                selected_user = users_data[index - 1]
                selected_info = self._format_role_info(selected_user)
                selected_app_id = str(selected_user.get("app_id", "39"))
                logger.info(f"开始绑定角色: {selected_info}")
                try:
                    payload = convert_to_query_bytes(selected_user, account)
                except Exception as exc:
                    logger.error(f"编码绑定数据失败: {exc}")
                    await event.send(
                        event.plain_result("❌ 角色数据异常，无法执行绑定")
                    )
                    controller.stop()
                    return

                result = await binds_account(self.headers, payload)
                if result.get("code") == 200:
                    # 首次绑定执行一次签到
                    sign_result = await sign_request(self.headers, selected_app_id)
                    sign_ok = self._is_sign_success(sign_result)
                    gift_summary = await self._claim_activity_gifts_for_role(
                        selected_app_id,
                        str(selected_user["role_id"]),
                    )
                    gift_prefix = "✅" if gift_summary["success_count"] > 0 else "ℹ️"
                    await event.send(
                        event.plain_result(
                            "\n".join(
                                [
                                    f"✅ 绑定成功: {selected_info}",
                                    (
                                        f"{'✅' if sign_ok else '❌'} 首次绑定执行签到: "
                                        f"{sign_result.get('message', '未知结果')}"
                                    ),
                                    (
                                        f"{gift_prefix} 活动礼包结果: "
                                        + "；".join(gift_summary["messages"])
                                    ),
                                ]
                            )
                        )
                    )
                    # 加密保存数据
                    encrypted_account = encrypt_data(account)
                    encrypted_role_id = encrypt_data(selected_user["role_id"])
                    # 获取用户ID
                    user_id = event.get_sender_id()
                    user_id = user_id.replace("/", "_")
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
                    if isinstance(user_data, dict) and user_data.get("num", 0) > 0:
                        users = user_data.get("users", [])
                        users.append(
                            {
                                "account": encrypted_account,
                                "role_id": encrypted_role_id,
                                "app_id": selected_app_id,
                                "info": selected_info,
                                "sign_status": self._build_sign_status(
                                    "success" if sign_ok else "failed",
                                    sign_result.get("message", "首次绑定后签到成功"),
                                ),
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
                                    "app_id": selected_app_id,
                                    "info": selected_info,
                                    "sign_status": self._build_sign_status(
                                        "success" if sign_ok else "failed",
                                        sign_result.get(
                                            "message", "首次绑定后签到成功"
                                        ),
                                    ),
                                }
                            ],
                        }
                    with user_file.open("w", encoding="utf-8") as f:
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
        """查询已绑定的账号，显示已绑定的角色信息"""
        user_id = event.get_sender_id()
        user_id = user_id.replace("/", "_")
        user_data = self._load_user_data(user_id)
        if not user_data:
            await event.send(event.plain_result("❌ 未找到绑定数据"))
            return

        users = user_data.get("users", [])
        if not isinstance(users, list) or not users:
            await event.send(event.plain_result("❌ 读取数据失败"))
            return

        content = self._render_user_status_markdown(user_id, users)
        await self._send_status_card(event, content)

    @command("注销绑定")
    async def delete_account(self, event: AstrMessageEvent):
        """删除已绑定的账号，查询已绑定的角色，选择后删除账号数据"""
        # 获取用户ID
        user_id = event.get_sender_id()
        user_id = user_id.replace("/", "_")
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
                select_info = "选择需要删除的账号:\n回复 退出 或 取消 可结束当前流程。"
                id = 1
                for user in users:
                    select_info += f"\n{id}. {user['info']}"
                    id += 1
                message_id = await send_msg(event, select_info)

                @session_waiter(timeout=20)
                async def delete_waiter(
                    controller: SessionController, event: AstrMessageEvent
                ):
                    nonlocal message_id, users, user_file, user_id
                    now_user_id = event.get_sender_id()
                    now_user_id = now_user_id.replace("/", "_")
                    if now_user_id != user_id:
                        return
                    arg = event.message_str.strip()
                    parts = arg.split()
                    if len(parts) == 0:
                        return
                    if self._is_exit_command(arg):
                        await event.send(event.plain_result("✅ 已退出注销流程"))
                        controller.stop()
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
                        if users:
                            user_data["users"] = users
                            user_data["num"] = len(users)
                            with user_file.open("w", encoding="utf-8") as f:
                                json.dump(user_data, f, ensure_ascii=False, indent=4)
                        else:
                            user_file.unlink(missing_ok=True)
                        logger.info(
                            f"用户 {user_id} 已删除一个绑定角色，剩余 {len(users)} 个"
                        )
                        await event.send(event.plain_result("✅ 账号删除成功"))
                        controller.stop()
                        return

                try:
                    await delete_waiter(event)
                    event.stop_event()
                except TimeoutError as _:
                    logger.warning("选择超时！")
                    await event.send(event.plain_result("❌ 选择超时，终止运行"))
        except Exception as e:
            logger.error(f"读取用户数据失败: {e}")
            await event.send(event.plain_result("❌ 读取数据失败"))
            return

    @command("定时签到推送")
    async def schedule_sign(self, event: AstrMessageEvent, enabled: str):
        """定时签到推送开关
        Args:
            enabled: "开启" 或 "关闭"
        """
        if event.get_message_type() != PlatformMessageType.GROUP_MESSAGE:
            yield event.plain_result(
                "⚠️ 该指令仅限群聊使用。\n请在目标群发送“定时签到推送 开启”或“定时签到推送 关闭”。"
            )
            return

        group_origin = event.unified_msg_origin
        group_id = event.get_group_id() or event.get_session_id()
        data = self.read_file("push_datas", "sign.json")
        if not data:
            data = {"datas": []}
        groups = data.get("datas", [])
        if not isinstance(groups, list):
            groups = []

        if enabled not in ["开启", "关闭"]:
            yield event.plain_result(
                "❌ 参数错误，请使用：定时签到推送 开启 或 定时签到推送 关闭"
            )
            return
        if enabled == "开启":
            if group_origin in groups:
                yield event.plain_result(
                    f"✅ 群 {group_id} 已经开启定时签到汇总推送，无需重复操作"
                )
                return
            groups.append(group_origin)
            data["datas"] = groups
            yield event.plain_result(f"✅ 群 {group_id} 已开启定时签到汇总推送")
        else:
            if group_origin not in groups:
                yield event.plain_result(
                    f"✅ 群 {group_id} 已经关闭定时签到汇总推送，无需重复操作"
                )
                return
            groups.remove(group_origin)
            data["datas"] = groups
            yield event.plain_result(f"✅ 群 {group_id} 已关闭定时签到汇总推送")
        self.write_file("push_datas", "sign.json", data)

    @command("定时签到进度")
    async def auto_sign_progress(self, event: AstrMessageEvent):
        """查看当前定时签到任务进度。"""
        yield event.plain_result(self._format_auto_sign_progress())

    @filter.permission_type(filter.PermissionType.ADMIN)
    @command("强制执行自动签到")
    async def force_auto_sign(self, event: AstrMessageEvent):
        """强制执行自动签到"""
        # await self.auto_sign_in()
        # await self.auto_activity_gift_sign_in()
        event.stop_event()

    @command("最强蜗牛help")
    async def show_help(self, event: AstrMessageEvent):
        """查看普通用户可用指令。"""
        help_text = (
            "【最强蜗牛插件帮助】\n"
            "绑定账号 <手机号> (例:/绑定账号 1234567890)\n"
            "查询绑定\n"
            "注销绑定\n"
            "定时签到推送 开启|关闭\n"
            "定时签到进度\n"
            "最强蜗牛 搜索攻略 <关键词>\n"
            "最强蜗牛 特工逃犯 <名称>\n"
            "最强蜗牛 攻略推送 开启|关闭\n"
            "账号统计"
        )
        yield event.plain_result(help_text)

    async def auto_sign_in(self):
        """定时签到功能，查询已绑定的角色，选择后执行签到"""
        if not self.headers:
            logger.info("未配置 headers，跳过定时签到任务")
            return

        if not self.read_file("push_datas", "sign.json"):
            logger.info("未找到定时签到推送数据文件，跳过定时签到任务")
            return
        group_targets = self._get_group_sign_push_targets()
        # 读取文件
        data_dir_str = get_astrbot_data_path()
        plugin_data_path = Path(data_dir_str) / "plugin_data" / self.name
        user_dir = plugin_data_path / "users"
        if not user_dir.exists():
            logger.info("未找到用户绑定目录，跳过定时签到任务")
            return
        user_files = list(user_dir.glob("*.json"))
        if not user_files:
            logger.info("用户绑定目录为空，跳过定时签到任务")
            return

        # 使用系统级随机源打乱用户签到顺序，避免每天看起来都是同一批用户先签到。
        self.randomizer.shuffle(user_files)
        started_at = time.time()
        summary_lines: list[str] = []
        total_account_count = 0
        success_account_count = 0
        failed_account_count = 0
        success_user_count = 0
        failed_user_count = 0
        self._set_auto_sign_progress(
            running=True,
            total_users=len(user_files),
            completed_users=0,
            current_user=None,
            current_role=None,
            started_at=started_at,
        )

        try:
            # 逐个用户执行签到，并在结束后生成群聊汇总，不再逐人私聊推送。
            for index, user_file in enumerate(user_files, start=1):
                user_id = user_file.stem
                success_count = 0
                failed_count = 0
                account_count = 0
                invalid_account_count = 0
                self._set_auto_sign_progress(
                    running=True,
                    completed_users=index - 1,
                    current_user=user_id,
                    current_role=None,
                )
                writer_data = []
                try:
                    if not user_file.exists():
                        logger.error(
                            f"未找到用户 {user_id} 的绑定数据文件，无法执行签到"
                        )
                        failed_user_count += 1
                        summary_lines.append(
                            f"- 用户ID: {user_id}，账号总数: 0，成功: 0，失败: 0"
                        )
                        continue
                    # 读取用户数据
                    with user_file.open("r", encoding="utf-8") as f:
                        user_data = json.load(f)
                        users = user_data.get("users", [])
                        if not isinstance(users, list) or not users:
                            logger.warning(
                                f"用户 {user_id} 没有可用的绑定角色，跳过定时签到"
                            )
                            failed_user_count += 1
                            summary_lines.append(
                                f"- 用户ID: {user_id}，账号总数: 0，成功: 0，失败: 0"
                            )
                            continue
                        # 同一角色可能被重复绑定，这里只保留最后一份，避免重复签到与重复统计。
                        unique_users = {}
                        for user in users:
                            try:
                                role_id = decrypt_data(user["role_id"])
                            except Exception as exc:
                                logger.error(
                                    f"解密用户 {user_id} 的角色数据失败: {exc}"
                                )
                                self._set_user_sign_status(
                                    user, "invalid", "角色绑定数据已损坏"
                                )
                                writer_data.append(user)
                                invalid_account_count += 1
                                failed_count += 1
                                failed_account_count += 1
                                continue
                            bound_app_id = self._get_bound_app_id(user)
                            unique_users[(role_id, bound_app_id)] = user
                        users = list(unique_users.values())
                        account_count = len(users) + invalid_account_count
                        total_account_count += account_count
                        # 进一步打乱同一用户下各账号的签到顺序，避免多账号用户每天顺序固定。
                        self.randomizer.shuffle(users)
                        for user in users:
                            info = user.get("info", "未知角色")
                            bound_app_id = self._get_bound_app_id(user)
                            self._set_auto_sign_progress(
                                running=True,
                                completed_users=index - 1,
                                current_user=user_id,
                                current_role=info,
                            )
                            try:
                                account = decrypt_data(user["account"])
                                role_id = decrypt_data(user["role_id"])
                            except Exception as exc:
                                logger.error(
                                    f"解密用户 {user_id} 的账号数据失败: {exc}"
                                )
                                self._set_user_sign_status(
                                    user, "invalid", "账号数据解密失败"
                                )
                                writer_data.append(user)
                                failed_count += 1
                                failed_account_count += 1
                                continue

                            info = user.get("info", "")
                            users_server_data = await get_server(
                                account
                            )  # 获取最新的角色信息，更新info显示
                            if users_server_data is None or len(users_server_data) == 0:
                                self._set_user_sign_status(
                                    user, "failed", "获取角色信息失败"
                                )
                                logger.error(f"获取角色信息失败: {info or user_id}")
                                writer_data.append(user)
                                failed_count += 1
                                failed_account_count += 1
                                continue
                            matched = False
                            for user_server_data in users_server_data:
                                current_app_id = self._get_bound_app_id(
                                    user_server_data
                                )
                                if (
                                    user_server_data.get("role_id") == role_id
                                    and current_app_id == bound_app_id
                                ):
                                    matched = True
                                    user["app_id"] = current_app_id
                                    user["info"] = self._format_role_info(
                                        user_server_data
                                    )
                                    try:
                                        payload = convert_to_query_bytes(
                                            user_server_data, account
                                        )
                                    except Exception as exc:
                                        logger.error(f"编码定时签到数据失败: {exc}")
                                        self._set_user_sign_status(
                                            user, "invalid", "角色数据异常"
                                        )
                                        writer_data.append(user)
                                        failed_count += 1
                                        failed_account_count += 1
                                        break

                                    result = await binds_account(self.headers, payload)
                                    if result.get("code") == 200:
                                        sign_result = await sign_request(
                                            self.headers, current_app_id
                                        )
                                        if self._is_sign_success(sign_result):
                                            self._set_user_sign_status(
                                                user,
                                                "success",
                                                sign_result.get("message", "签到成功"),
                                            )
                                            # “已领取过”也会被判定为成功，因此这里的计数代表
                                            # 当天该用户成功完成或已完成签到的账号数量。
                                            success_count += 1
                                            success_account_count += 1
                                            # 休眠3-15秒，防止请求过快被封IP，间隔随机3-15秒
                                            random_factor = random.uniform(3, 15)
                                            delay = max(
                                                3, random_factor
                                            )  # 确保间隔至少为3秒
                                            await asyncio.sleep(delay)
                                        else:
                                            self._set_user_sign_status(
                                                user,
                                                "failed",
                                                sign_result.get("message", "签到失败"),
                                            )
                                            failed_count += 1
                                            failed_account_count += 1
                                    else:
                                        error_message = result.get(
                                            "message", "未知错误"
                                        )
                                        self._set_user_sign_status(
                                            user, "failed", error_message
                                        )
                                        failed_count += 1
                                        failed_account_count += 1
                                    writer_data.append(user)
                                    break
                            if not matched:
                                logger.warning(
                                    f"定时签到未找到匹配角色: {info or user_id}"
                                )
                                self._set_user_sign_status(
                                    user, "failed", "未找到最新角色信息"
                                )
                                writer_data.append(user)
                                failed_count += 1
                                failed_account_count += 1
                except Exception as e:
                    logger.error(f"读取用户 {user_id} 的数据失败: {e}")
                    failed_user_count += 1
                    summary_lines.append(
                        f"- 用户ID: {user_id}，账号总数: {account_count}，成功: {success_count}，失败: {failed_count}"
                    )
                    continue
                # 更新文件数据写入
                writer = {"num": 0, "users": []}
                writer["users"] = writer_data
                writer["num"] = len(writer_data)
                try:
                    with user_file.open("w", encoding="utf-8") as f:
                        json.dump(writer, f, ensure_ascii=False, indent=4)
                except Exception as e:
                    logger.error(f"写回用户 {user_id} 的签到数据失败: {e}")
                    continue
                if success_count > 0:
                    success_user_count += 1
                else:
                    failed_user_count += 1
                logger.info(f"用户 {user_id} 的定时签到已完成")
                summary_lines.append(
                    f"- 用户ID: {user_id}，账号总数: {account_count}，成功: {success_count}，失败: {failed_count}"
                )
                self._set_auto_sign_progress(
                    running=True,
                    completed_users=index,
                    current_user=user_id,
                    current_role=None,
                )

            if group_targets and summary_lines:
                # 汇总消息统一发往已登记的群聊，并在汇总图后追加当天奖励图。
                duration_seconds = max(0.0, time.time() - started_at)
                summary_header = [
                    f"- 签到成功用户数: {success_user_count}",
                    f"- 签到失败用户数: {failed_user_count}",
                    f"- 账号总数: {total_account_count}",
                    f"- 签到成功账号数: {success_account_count}",
                    f"- 签到失败账号数: {failed_account_count}",
                    f"- 签到耗时: {duration_seconds:.1f} 秒",
                    "",
                    "## 用户明细",
                ]
                summary_text = "\n".join(summary_header + summary_lines)
                reward_image_path = self._get_today_reward_image_path()
                for group_target in group_targets:
                    try:
                        await self._send_rendered_message(
                            group_target,
                            summary_text,
                            msg="定时签到数据",
                            extra_image_path=reward_image_path,
                        )
                        logger.info(f"已发送定时签到汇总到群 {group_target}")
                    except Exception as e:
                        logger.error(f"发送定时签到汇总到群 {group_target} 失败: {e}")
            elif not group_targets:
                logger.info("未配置群聊定时签到汇总推送目标，已跳过汇总消息发送")
        finally:
            self._set_auto_sign_progress(
                running=False,
                completed_users=len(user_files),
                current_user=None,
                current_role=None,
                last_finished_at=time.time(),
            )

    async def auto_activity_gift_sign_in(self):
        """每周活动礼包定时领取，与每日定时签到共用同一批绑定账号。"""
        if not self.headers:
            logger.info("未配置 headers，跳过每周活动礼包任务")
            return

        if not self.read_file("push_datas", "sign.json"):
            logger.info("未找到定时签到推送数据文件，跳过每周活动礼包任务")
            return

        group_targets = self._get_group_sign_push_targets()
        user_dir = self._get_user_dir()
        if not user_dir.exists():
            logger.info("未找到用户绑定目录，跳过每周活动礼包任务")
            return

        user_files = list(user_dir.glob("*.json"))
        if not user_files:
            logger.info("用户绑定目录为空，跳过每周活动礼包任务")
            return

        self.randomizer.shuffle(user_files)
        started_at = time.time()
        summary_lines: list[str] = []
        total_account_count = 0
        success_account_count = 0
        failed_account_count = 0
        skipped_account_count = 0
        success_user_count = 0
        failed_user_count = 0
        skipped_user_count = 0

        for user_file in user_files:
            user_id = user_file.stem
            success_count = 0
            failed_count = 0
            skipped_count = 0
            account_count = 0
            invalid_account_count = 0
            role_summary_lines: list[str] = []

            try:
                with user_file.open("r", encoding="utf-8") as f:
                    user_data = json.load(f)
            except Exception as exc:
                logger.error(f"读取用户 {user_id} 的数据失败: {exc}")
                failed_user_count += 1
                summary_lines.append(
                    f"- 用户ID: {user_id}，账号总数: 0，成功: 0，失败: 0"
                )
                continue

            users = user_data.get("users", [])
            if not isinstance(users, list) or not users:
                logger.warning(f"用户 {user_id} 没有可用的绑定角色，跳过活动礼包任务")
                failed_user_count += 1
                summary_lines.append(
                    f"- 用户ID: {user_id}，账号总数: 0，成功: 0，失败: 0"
                )
                continue

            unique_users = {}
            for user in users:
                try:
                    role_id = decrypt_data(user["role_id"])
                except Exception as exc:
                    logger.error(f"解密用户 {user_id} 的角色数据失败: {exc}")
                    invalid_account_count += 1
                    failed_count += 1
                    failed_account_count += 1
                    continue
                bound_app_id = self._get_bound_app_id(user)
                unique_users[(role_id, bound_app_id)] = user

            role_entries = list(unique_users.items())
            account_count = len(role_entries) + invalid_account_count
            total_account_count += account_count
            self.randomizer.shuffle(role_entries)

            for (role_id, bound_app_id), user in role_entries:
                info = user.get("info", "未知角色")
                gift_summary = await self._claim_activity_gifts_for_role(
                    bound_app_id,
                    role_id,
                )
                if gift_summary["success_count"] > 0:
                    success_count += 1
                    success_account_count += 1
                elif gift_summary["failed_count"] > 0:
                    failed_count += 1
                    failed_account_count += 1
                else:
                    skipped_count += 1
                    skipped_account_count += 1

                message = "；".join(gift_summary["messages"])
                claimed_gifts = gift_summary.get("claimed_gifts", [])
                failed_gifts = gift_summary.get("failed_gifts", [])
                detail_parts = [f"角色: {info}"]
                if claimed_gifts:
                    detail_parts.append(
                        f"已领取礼包: {'、'.join(str(name) for name in claimed_gifts)}"
                    )
                if failed_gifts:
                    detail_parts.append(
                        f"失败礼包: {'、'.join(str(name) for name in failed_gifts)}"
                    )
                if not claimed_gifts and not failed_gifts:
                    detail_parts.append("已领取礼包: 无可领取礼包")
                role_summary_lines.append(f"  - {'；'.join(detail_parts)}")
                logger.info(f"活动礼包处理完成: {user_id} {info} -> {message}")
                if gift_summary["has_claim_attempt"]:
                    await asyncio.sleep(max(3, random.uniform(3, 15)))

            if success_count > 0:
                success_user_count += 1
            elif failed_count > 0:
                failed_user_count += 1
            else:
                skipped_user_count += 1

            summary_lines.append(
                f"- 用户ID: {user_id}，账号总数: {account_count}，成功: {success_count}，失败: {failed_count}，跳过: {skipped_count}"
            )
            summary_lines.extend(role_summary_lines)

        if group_targets and summary_lines:
            duration_seconds = max(0.0, time.time() - started_at)
            summary_header = [
                f"- 领取成功用户数: {success_user_count}",
                f"- 领取失败用户数: {failed_user_count}",
                f"- 无可领礼包用户数: {skipped_user_count}",
                f"- 账号总数: {total_account_count}",
                f"- 领取成功账号数: {success_account_count}",
                f"- 领取失败账号数: {failed_account_count}",
                f"- 无可领礼包账号数: {skipped_account_count}",
                f"- 执行耗时: {duration_seconds:.1f} 秒",
                "",
                "## 用户明细",
            ]
            summary_text = "\n".join(summary_header + summary_lines)
            for group_target in group_targets:
                try:
                    await self._send_rendered_message(
                        group_target,
                        summary_text,
                        msg="每周活动礼包数据",
                    )
                    logger.info(f"已发送每周活动礼包汇总到群 {group_target}")
                except Exception as exc:
                    logger.error(f"发送每周活动礼包汇总到群 {group_target} 失败: {exc}")
        elif not group_targets:
            logger.info("未配置群聊定时签到汇总推送目标，已跳过活动礼包汇总发送")

    @command("账号统计")
    async def account_statistics(self, event: AstrMessageEvent):
        """账号统计功能，统计已绑定账号的数量和信息"""
        # 读取文件
        data_dir_str = get_astrbot_data_path()
        plugin_data_path = Path(data_dir_str) / "plugin_data" / self.name
        user_dir = plugin_data_path / "users"
        total_accounts = 0
        counts = 0
        stats_info = "账号统计信息:"
        if not user_dir.exists():
            yield event.plain_result("❌ 未找到绑定数据")
            return
        try:
            for user_file in user_dir.glob("*.json"):
                with user_file.open("r", encoding="utf-8") as f:
                    user_data = json.load(f)
                    num = user_data.get("num", 0)
                    counts += num
                total_accounts += 1
            stats_info += f"\n总用户数: {total_accounts}"
            stats_info += f"\n总账号数: {counts}"
            yield event.plain_result(stats_info)
        except Exception as e:
            logger.error(f"读取用户数据失败: {e}")
            yield event.plain_result("❌ 读取数据失败")
            return

    def read_file(self, dir_name: str, file_name: str):
        """打开文件，返回文件内容
        Args:
            dir_name: 文件夹名称
            file_name: 文件名称
        """
        data_dir_str = get_astrbot_data_path()
        plugin_data_path = Path(data_dir_str) / "plugin_data" / self.name
        file_path = plugin_data_path / dir_name / file_name
        if not file_path.exists():
            logger.warning(f"文件 {file_path} 不存在")
            return None
        try:
            with file_path.open("r", encoding="utf-8") as f:
                content = json.load(f)
                return content
        except Exception as e:
            logger.error(f"读取文件 {file_path} 失败: {e}")
            return None

    def write_file(self, dir_name: str, file_name: str, data: dict):
        """写入文件，保存数据
        Args:
            dir_name: 文件夹名称
            file_name: 文件名称
            data: 需要写入的数据，字典格式
        """
        data_dir_str = get_astrbot_data_path()
        plugin_data_path = Path(data_dir_str) / "plugin_data" / self.name
        dir_path = plugin_data_path / dir_name
        if not dir_path.exists():
            try:
                dir_path.mkdir(parents=True, exist_ok=True)
                logger.info(f"已创建文件夹 {dir_path}")
            except Exception as e:
                logger.error(f"创建文件夹 {dir_path} 失败: {e}")
                return False
        file_path = dir_path / file_name
        try:
            with file_path.open("w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
            logger.info(f"已将数据写入 {file_path}")
            return True
        except Exception as e:
            logger.error(f"写入文件 {file_path} 失败: {e}")
            return False
