import ast
import json
import random
import time
from pathlib import Path
from typing import Any

import aiohttp
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

import astrbot.core.message.components as Comp
from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, MessageChain
from astrbot.api.star import Context, Star
from astrbot.core.message.components import Image, Node, Nodes, Plain
from astrbot.core.platform import MessageType as PlatformMessageType
from astrbot.core.utils.astrbot_path import (
    get_astrbot_data_path,
    get_astrbot_plugin_path,
    get_astrbot_temp_path,
)

from .parse import Parse
from .sign_in import activity_gift_claim
from .utils import cron_to_human, get_week

PLUGIN_NAME = "astrbot_plugin_marvelous_snail"


class MarvelousSnailPluginBase(Star):
    """最强蜗牛插件基础类，提供通用的工具方法和定时任务管理功能。"""

    def __init__(self, context: Context, config: AstrBotConfig):
        """初始化最强蜗牛插件基础类，设置数据路径、调度器和其他基础设施。
        Args:
            context: 插件上下文对象。
            config: 插件配置对象。
        """
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

    async def get_saved_account(self):
        """由strategy_feature提供实现。
        Returns:
            None
        """
        raise NotImplementedError()

    async def auto_sign_in(self):
        """由account_feature提供实现。
        Returns:
            None
        """
        raise NotImplementedError()

    async def keep_sign_in(self):
        """由account_feature提供实现。
        Returns:
            None
        """
        raise NotImplementedError()

    async def initialize(self):
        """插件初始化
        Returns:
            None
        """
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

        self.scheduler.remove_all_jobs()
        if self.config.get("exporter_auth_key") and self.config.get("exporter_api_url"):
            await self._start_auto_job(
                "get_updata_job", "*/50 * * * *", self.get_saved_account
            )
        else:
            logger.warning("未配置 API 地址或密钥，已跳过攻略更新监控任务")

        if self.headers:
            await self._start_auto_job(
                "auto_sign_in_job", "10 8 * * *", self.auto_sign_in
            )
            await self._start_auto_job(
                "keep_sign_in_job", "*/30 * * * *", self.keep_sign_in
            )
        else:
            logger.warning("未配置 headers，已跳过自动签到相关定时任务")

        if not self.scheduler.running:
            self.scheduler.start()

    async def terminate(self):
        """插件卸载
        Returns:
            None
        """
        logger.info("最强蜗牛插件已卸载")
        if self.scheduler.running:
            self.scheduler.shutdown()
            logger.info("调度器已关闭,已停止所有定时任务")

    async def _start_auto_job(self, job_id: str, cron_expr: str, func, args=None):
        """设置定时任务。
        Args:
            job_id: 任务 ID。
            cron_expr: Cron 表达式。
            func: 任务函数。
            args: 任务函数参数列表。
        Returns:
            None
        """
        scheduler = self.scheduler
        if scheduler is None:
            logger.error("Scheduler 未初始化")
            return

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
        """检查是否已正确配置 API 地址和认证密钥
        Returns:
            bool: 如果配置正确返回 True，否则返回 False。
        """
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
        """解析 headers 配置项，支持直接使用字典或字符串形式的字典
        Args:
            raw_headers: 原始 headers 配置，可以是字典或字符串形式的字典。
        Returns:
            dict[str, Any]: 解析后的 headers 字典。
        """
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
        """提取导出器 API 错误信息，用于日志记录和用户反馈
        Args:
            payload: API 响应的原始数据，预期为包含 base_resp 的字典
        Returns:
            str: 提取到的错误信息，如果无法提取则返回 "未知错误"。
        """
        if isinstance(payload, dict):
            base_resp = payload.get("base_resp")
            if isinstance(base_resp, dict):
                err_msg = base_resp.get("err_msg")
                if isinstance(err_msg, str) and err_msg.strip():
                    return err_msg
        return "未知错误"

    @staticmethod
    def _get_server_type_name(game_id: Any) -> str:
        """根据 game_id 返回服务器类型名称。
            - "26" 对应 "光子服"
            - "39" 对应 "官服"
            - 其他值返回 "未知服"
        Args:
            game_id: 服务器 ID，预期为字符串或可转换为字符串的值。
        Returns:
            str: 服务器类型名称。
        """
        if str(game_id) == "26":
            return "光子服"
        if str(game_id) == "39":
            return "官服"
        return "未知服"

    @staticmethod
    def _get_bound_game_id(user_data: dict[str, Any]) -> str:
        """读取绑定数据中的 game_id。
        Args:
            user_data: 用户绑定数据字典。
        Returns:
            str: 绑定的 game_id，如果不存在则返回默认值 "39"。
        """
        return str(user_data.get("game_id", "39"))

    @staticmethod
    def _set_bound_game_id(user_data: dict[str, Any], game_id: Any) -> None:
        """写入绑定数据的 game_id。
        Args:
            user_data: 用户绑定数据字典。
            game_id: 要绑定的 game_id。
        Returns:
            None
        """
        game_id_text = str(game_id)
        user_data["game_id"] = game_id_text

    @staticmethod
    def _format_role_info(user_data: dict[str, Any]) -> str:
        """格式化角色信息，用于日志和用户显示。
        Args:
            user_data: 用户绑定数据字典。
        Returns:
            str: 格式化后的角色信息字符串。
        """
        extra = user_data.get("extra")
        score = "未知"
        if isinstance(extra, dict) and extra.get("score") is not None:
            score = str(extra.get("score"))

        server_name = user_data.get("server_name", "未知区服")
        role_name = user_data.get("role_name", "未知角色")
        server_type = MarvelousSnailPluginBase._get_server_type_name(
            MarvelousSnailPluginBase._get_bound_game_id(user_data)
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
        """更新定时签到进度状态。
        Args:
            running: 是否正在运行。
            total_users: 总用户数。
            completed_users: 已完成用户数。
            current_user: 当前用户。
            current_role: 当前角色。
            started_at: 开始时间戳。
            last_finished_at: 上次完成时间戳。
        Returns:
            None
        """
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
        """格式化当前定时签到进度。
        Returns:
            str: 格式化后的定时签到进度字符串。
        """
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
        Returns:
            Path | None: 状态图渲染样式目录路径，如果不存在则返回 None。
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
        Args:
            event: 消息事件对象。
            content: 状态卡内容。
            msg: 可选的消息标题。
        Returns:
            None
        """
        await self._send_markdown_card(event, content, msg=msg, stop_event=True)

    def _build_markdown_render_text(self, content: str, msg: str | None = None) -> str:
        """构造用于图片渲染的 Markdown 文本。
        Args:
            content: Markdown 内容。
            msg: 可选的消息标题。
        Returns:
            str: 构造后的 Markdown 文本。
        """
        return content if not msg else f"# {msg}\n\n{content}"

    @staticmethod
    def _is_exit_command(text: str) -> bool:
        """判断用户是否主动退出当前交互流程。
        Args:
            text: 用户输入的文本。
        Returns:
            bool: 如果用户输入的是退出命令，则返回 True，否则返回 False。
        """
        return text.strip() in {"退出", "取消", "q", "Q"}

    async def _download_bytes_from_url(self, url: str) -> bytes | None:
        """下载文件字节流，兼容回调文件服务。
        Args:
            url: 文件的 URL 地址。
        Returns:
            bytes | None: 下载的文件字节流，如果下载失败则返回 None。
        """
        normalized_url = url.replace("https://", "http://")
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(normalized_url) as response:
                    if response.status != 200:
                        logger.error(
                            "下载文件失败，状态码: %s, url: %s",
                            response.status,
                            normalized_url,
                        )
                        return None
                    return await response.read()
        except Exception as exc:
            logger.error(f"下载文件失败: {exc}")
            return None

    async def _load_quoted_json_payload(
        self, event: AstrMessageEvent
    ) -> tuple[dict[str, Any] | None, str | None]:
        """读取当前消息引用中的 JSON 文件并解析。
        Args:
            event: 消息事件对象。
        Returns:
            tuple[dict[str, Any] | None, str | None]: 如果解析成功，返回解析后的 JSON 对象和 None；否则返回 None 和错误信息。
        """
        chain = getattr(event.message_obj, "message", None)
        reply_chain = (
            chain[0].chain if chain and isinstance(chain[0], Comp.Reply) else None
        )
        file_comp = None
        if isinstance(reply_chain, list):
            file_comp = next(
                (
                    item
                    for item in reply_chain
                    if isinstance(item, Comp.File) and (item.url or item.file_)
                ),
                None,
            )

        if file_comp is None:
            return None, "请引用一个批量绑定 JSON 文件"

        file_name = str(file_comp.name or "")
        if file_name and not file_name.lower().endswith(".json"):
            return None, "仅支持 .json 文件"

        try:
            file_source = await file_comp.get_file(allow_return_url=True)
        except Exception as exc:
            logger.error(f"读取引用文件失败: {exc}")
            return None, "读取引用文件失败"

        if not file_source:
            return None, "无法获取引用文件地址"

        raw_bytes: bytes | None = None
        if file_source.startswith(("http://", "https://")):
            raw_bytes = await self._download_bytes_from_url(file_source)
        else:
            try:
                raw_bytes = Path(file_source).read_bytes()
            except Exception as exc:
                logger.error(f"读取本地引用文件失败: {exc}")

        if not raw_bytes:
            return None, "下载或读取引用文件失败"

        try:
            payload = json.loads(raw_bytes.decode("utf-8-sig"))
        except Exception as exc:
            logger.error(f"解析批量绑定 JSON 失败: {exc}")
            return None, "JSON 解析失败，请检查文件格式"

        if not isinstance(payload, dict):
            return None, "JSON 根节点必须是对象"

        return payload, None

    def _split_markdown_chunks(self, content: str, max_lines: int = 50) -> list[str]:
        """按行数切分 Markdown，避免单张图片过长。
        Args:
            content: Markdown 内容。
            max_lines: 每个分片的最大行数。
        Returns:
            list[str]: 分片后的 Markdown 列表。
        """
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
        """将 Markdown 分片渲染为多张图片，返回图片路径列表。
        Args:
            content: Markdown 内容。
        Returns:
            list[str]: 渲染后的图片路径列表。
        """
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
        """根据图片列表构造聊天记录节点。
        Args:
            image_paths: 图片路径列表。
            name: 节点名称。
            uin: 节点 UIN。
        Returns:
            Nodes: 构造的聊天记录节点。
        """
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
        """根据文本分片构造聊天记录节点。
        Args:
            chunks: 文本分片列表。
            name: 节点名称。
            uin: 节点 UIN。
        Returns:
            Nodes: 构造的聊天记录节点。
        """
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
        """向当前会话发送图片聊天记录。
        Args:
            event: 消息事件对象。
            image_paths: 图片路径列表。
        Returns:
            None
        """
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
        """向当前会话发送文本聊天记录。
        Args:
            event: 消息事件对象。
            chunks: 文本分片列表。
            name: 节点名称。
        Returns:
            None
        """
        sender_uin = event.get_self_id() or "0"
        forward = self._build_text_forward_nodes(chunks, name, sender_uin)
        await event.send(event.chain_result([forward]))

    async def _send_forward_images_to_target(
        self,
        target: str,
        image_paths: list[str],
    ) -> None:
        """向指定目标发送图片聊天记录。
        Args:
            target: 目标 ID。
            image_paths: 图片路径列表。
        Returns:
            None
        """
        forward = self._build_forward_nodes(image_paths, "最强蜗牛签到", "0")
        await self.context.send_message(target, MessageChain(chain=[forward]))  # type: ignore

    def _load_valid_codes(self) -> list[str]:
        """读取当前有效密令列表。
        Returns:
            list[str]: 当前有效密令列表。
        """
        codes_dir = self.data_dir / "codes"
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
        """按指定数量切分密令列表，适配聊天记录发送。
        Args:
            codes_list: 密令列表。
            chunk_size: 每个分片的最大数量。
        Returns:
            list[str]: 分片后的密令列表。
        """
        chunks = []
        for index in range(0, len(codes_list), chunk_size):
            chunk_codes = codes_list[index : index + chunk_size]
            if not chunk_codes:
                continue
            chunks.append("\n".join(chunk_codes))
        return chunks

    async def _send_codes_to_event(self, event: AstrMessageEvent) -> None:
        """向当前会话发送有效密令列表。
        Args:
            event: 消息事件对象。
        Returns:
            None
        """
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
        """向当前会话发送 Markdown 卡片，可按需选择是否停止事件。
        Args:
            event: 消息事件对象。
            content: Markdown 内容。
            msg: 可选的消息标题。
            stop_event: 是否在发送后停止事件，默认为 False。
        Returns:
            None
        """
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
        Args:
            target: 目标 ID。
            content: 消息内容。
            msg: 可选的消息标题。
            extra_image_path: 可选的额外图片路径。
        Returns:
            None
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
        """根据当前星期返回今日奖励配图路径。
        Returns:
            str: 今日奖励配图路径。
        """
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
        """获取用户数据目录路径。
        Returns:
            Path: 用户数据目录路径。
        """
        return self.data_dir / "users"

    def _get_user_file(self, user_id: str) -> Path:
        """获取指定用户的文件路径。
        Args:
            user_id: 用户 ID。
        Returns:
            Path: 用户文件路径。
        """
        return self._get_user_dir() / f"{user_id}.json"

    def _load_user_data(self, user_id: str) -> dict[str, Any] | None:
        """加载指定用户的数据。
        Args:
            user_id: 用户 ID。
        Returns:
            dict[str, Any] | None: 用户数据，如果不存在或读取失败则返回 None。
        """
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
        """保存指定用户的数据。
        Args:
            user_id: 用户 ID。
            data: 用户数据。
        Returns:
            bool: 保存是否成功。
        """
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
        """构造统一的签到状态记录结构，便于后续落盘与展示。
        Args:
            state: 签到状态。
            message: 签到消息。
        Returns:
            dict[str, Any]: 签到状态记录。
        """
        return {
            "state": state,
            "message": message,
            "updated_at": int(time.time()),
        }

    def _is_sign_success(self, sign_result: Any) -> bool:
        """判断签到接口结果是否应视为成功。
        Args:
            sign_result: 签到接口返回结果。
        Returns:
            bool: 是否签到成功。
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
        """更新用户数据中的签到状态记录。
        Args:
            user: 用户数据字典。
            state: 签到状态。
            message: 签到消息。
        Returns:
            None
        """
        user["sign_status"] = self._build_sign_status(state, message)

    def _summarize_activity_gift_results(self, gift_results: Any) -> dict[str, Any]:
        """汇总活动礼包领取结果。
        Args:
            gift_results: 活动礼包领取结果。
        Returns:
            dict[str, Any]: 汇总结果。
        """
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
        """执行单个角色的活动礼包领取。
        Args:
            game_id: 游戏 ID。
            role_id: 角色 ID。
        Returns:
            dict[str, Any]: 活动礼包领取结果汇总。
        """
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
        """格式化用户签到状态为可读文本。
        Args:
            user: 用户数据字典。
        Returns:
            tuple[str, str, str]: 签到状态文本、消息和更新时间。
        """
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
        """读取已登记的群聊汇总推送目标。
        Returns:
            list[str]: 群聊汇总推送目标列表。
        """
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
        """返回攻略作者缓存目录。
        Returns:
            Path: 攻略作者缓存目录路径。
        """
        return self.data_dir / "authors"

    def _get_author_cache_file(self, author: str) -> Path:
        """返回作者缓存文件路径。
        Args:
            author: 作者名称。
        Returns:
            Path: 作者缓存文件路径。
        """
        return self._get_author_cache_dir() / f"{author}.json"

    def _load_author_cache_payload(self, author: str) -> dict[str, Any] | None:
        """读取作者缓存文件。
        Args:
            author: 作者名称。
        Returns:
            dict[str, Any] | None: 作者缓存数据字典，如果文件不存在或格式无效则返回 None。
        """
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
        """提取攻略搜索真正需要的字段，减少本地冗余存储。
        Args:
            article: 文章数据字典。
        Returns:
            dict[str, Any] | None: 精简后的文章数据字典，如果标题或链接缺失则返回 None。
        """
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
        """生成文章缓存主键，优先使用 aid 以便覆盖作者二次编辑后的新链接。
        Args:
            article: 文章数据字典。
        Returns:
            tuple[str, str] | None: 文章缓存主键，如果无法生成则返回 None。
        """
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
        """合并作者文章缓存，覆盖旧链接并移除已删除文章。
        Args:
            existing_articles: 已有的文章列表。
            incoming_articles: 新的文章列表。
        Returns:
            list[dict[str, Any]]: 合并后的文章列表。
        """
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
        """渲染作者选择卡片。
        Args:
            authors: 作者列表。
        Returns:
            str: 渲染后的作者选择卡片内容。
        """
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
        """渲染攻略搜索结果卡片。
        Args:
            author: 作者名称。
            keyword: 搜索关键词。
            results: 搜索结果列表。
        Returns:
            str: 渲染后的攻略搜索结果卡片内容。
        """
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
        """从文章列表中选出最新且未删除的文章，用于更新通知。
        Args:
            articles: 文章列表。
        Returns:
            dict[str, Any] | None: 最新且未删除的文章，如果没有可用文章则返回 None。
        """
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

    def _render_user_status_markdown(
        self, user_id: str, users: list[dict[str, Any]]
    ) -> str:
        """渲染用户状态卡片，展示用户绑定的账号和签到状态。
        Args:
            user_id: 用户ID。
            users: 用户绑定的账号列表。
        Returns:
            str: 渲染后的用户状态卡片内容。
        """
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
        """读取特工逃犯数据文件，返回包含逃犯信息的字典。
        Returns:
            dict[str, Any] | None: 包含逃犯信息的字典，如果读取失败则返回 None。
        """
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
        """格式化逃犯信息，用于日志和用户显示。
        Args:
            item: 逃犯信息字典。
        Returns:
            str: 格式化后的逃犯信息字符串。
        """
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

    def read_file(self, dir_name: str, file_name: str):
        """打开文件，返回文件内容。
        Args:
            dir_name: 文件所在的目录名称。
            file_name: 文件名称。
        Returns:
            dict[str, Any] | None: 文件内容的字典，如果读取失败则返回 None。
        """
        file_path = self.data_dir / dir_name / file_name
        if not file_path.exists():
            logger.warning(f"文件 {file_path} 不存在")
            return None
        try:
            with file_path.open("r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"读取文件 {file_path} 失败: {e}")
            return None

    def write_file(self, dir_name: str, file_name: str, data: dict):
        """写入文件，保存数据。
        Args:
            dir_name: 文件所在的目录名称。
            file_name: 文件名称。
            data: 要写入的字典数据。
        Returns:
            bool: 写入成功返回 True，失败返回 False。
        """
        dir_path = self.data_dir / dir_name
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
