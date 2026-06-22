import asyncio
import json
import random
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent
from astrbot.core.platform import MessageType as PlatformMessageType
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import (
    AiocqhttpMessageEvent,
)
from astrbot.core.utils.session_waiter import SessionController, session_waiter

from .sign_in import binds_account, get_server, sign_request
from .utils import convert_to_query_bytes, decrypt_data, encrypt_data, send_msg

if TYPE_CHECKING:
    # 避免循环导入导致的类型检查问题，实际运行时 AccountFeatureBase 会被正确替换为 MarvelousSnailPluginBase
    from .plugin_base import MarvelousSnailPluginBase as AccountFeatureBase
else:
    # 在运行时，AccountFeatureBase 将被定义为一个空类，避免导入错误
    class AccountFeatureBase:
        pass


class AccountFeatureMixin(AccountFeatureBase):
    """最强蜗牛账号管理功能，包括账号绑定、查询、删除和定时签到等功能。"""

    def _get_encryption_secret_key(self) -> str:
        secret_key = self.config.get("encryption_secret_key", "")
        if not isinstance(secret_key, str) or not secret_key.strip():
            raise ValueError("未配置 encryption_secret_key，无法执行账号数据加解密")
        return secret_key.strip()

    def _encrypt_data(self, text: str) -> str:
        return encrypt_data(text, self._get_encryption_secret_key())

    def _decrypt_data(self, token: str) -> str:
        return decrypt_data(token, self._get_encryption_secret_key())

    def _prepare_scheduled_user_files(
        self,
        task_name: str,
    ) -> tuple[list[str], list[Path]] | None:
        """准备定时任务需要处理的用户文件列表。
        Args:
            task_name: 任务名称，用于日志记录。
        Returns:
            包含群组目标和用户文件列表的元组，如果无法准备则返回 None。
        """
        if not self.headers:
            logger.info(f"未配置 headers，跳过{task_name}")
            return None

        if not self.read_file("push_datas", "sign.json"):
            logger.info(f"未找到定时签到推送数据文件，跳过{task_name}")
            return None

        group_targets = self._get_group_sign_push_targets()
        user_dir = self._get_user_dir()
        if not user_dir.exists():
            logger.info(f"未找到用户绑定目录，跳过{task_name}")
            return None

        user_files = list(user_dir.glob("*.json"))
        if not user_files:
            logger.info(f"用户绑定目录为空，跳过{task_name}")
            return None

        self.randomizer.shuffle(user_files)
        return group_targets, user_files

    def _load_task_users(
        self,
        user_file: Path,
        user_id: str,
        task_name: str,
    ) -> list[dict[str, Any]] | None:
        """从用户文件中加载绑定的账号数据。
        Args:
            user_file: 用户文件路径。
            user_id: 用户ID，用于日志记录。
            task_name: 任务名称，用于日志记录。
        Returns:
            包含绑定账号数据的列表，如果无法加载则返回 None。
        """
        try:
            with user_file.open("r", encoding="utf-8") as f:
                user_data = json.load(f)
        except Exception as exc:
            logger.error(f"读取用户 {user_id} 的数据失败: {exc}")
            return None

        users = user_data.get("users", []) if isinstance(user_data, dict) else []
        if not isinstance(users, list) or not users:
            logger.warning(f"用户 {user_id} 没有可用的绑定角色，跳过{task_name}")
            return None
        return users

    def _deduplicate_bound_users(
        self,
        user_id: str,
        users: list[dict[str, Any]],
        *,
        on_invalid: Callable[[dict[str, Any]], None] | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        """去重绑定的用户账号数据。
        Args:
            user_id: 用户ID，用于日志记录。
            users: 绑定的用户账号数据列表。
            on_invalid: 可选的回调函数，当遇到无效账号时调用。
        Returns:
            包含去重后的绑定账号数据列表和无效账号数量的元组。
        """
        unique_users: dict[tuple[str, str], dict[str, Any]] = {}
        invalid_account_count = 0
        for user in users:
            try:
                role_id = self._decrypt_data(user["role_id"])
            except Exception as exc:
                logger.error(f"解密用户 {user_id} 的角色数据失败: {exc}")
                invalid_account_count += 1
                if on_invalid is not None:
                    on_invalid(user)
                continue
            bound_game_id = self._get_bound_game_id(user)
            unique_users[(role_id, bound_game_id)] = user
        return list(unique_users.values()), invalid_account_count

    async def get_headers_impl(self, event: AstrMessageEvent, account: str):
        """处理用户绑定账号的请求，获取账号信息并引导用户选择需要绑定的角色。
        Args:
            event: 消息事件对象。
            account: 用户账号信息。
        Returns:
            None
        """
        if isinstance(event, AiocqhttpMessageEvent):
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
        select_info = "选择需要绑定的角色:\n回复 退出 或 取消 可结束当前流程。"
        index = 1
        for user_data in users_data:
            select_info += f"\n{index}. {self._format_role_info(user_data)}"
            index += 1
        message_id = await send_msg(event, select_info)
        group_id = getattr(event.message_obj, "group_id", None)
        user_id = None
        if group_id and group_id != 0:
            user_id = event.get_sender_id().replace("/", "_")

        @session_waiter(timeout=60)
        async def bind_waiter(controller: SessionController, event: AstrMessageEvent):
            """处理用户选择绑定角色的请求，根据用户输入执行绑定操作。
            Args:
                controller: 会话控制器对象。
                event: 消息事件对象。
            Returns:
                None
            """
            nonlocal message_id, user_id
            now_user_id = event.get_sender_id().replace("/", "_")
            if user_id and now_user_id != user_id:
                return
            arg = event.message_str.strip()
            parts = arg.split()
            if len(parts) == 0:
                return
            if self._is_exit_command(arg):
                await event.send(event.plain_result("✅ 已退出绑定流程"))
                controller.stop()
                return
            if isinstance(event, AiocqhttpMessageEvent):
                if message_id:
                    await event.bot.delete_msg(message_id=int(message_id))
                    message_id = None

            if len(parts) == 1 and parts[0].isdigit():
                select_index = int(parts[0])
                if select_index < 1 or select_index > len(users_data):
                    return
                selected_user = users_data[select_index - 1]
                selected_info = self._format_role_info(selected_user)
                selected_game_id = self._get_bound_game_id(selected_user)
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
                    sign_result = await sign_request(self.headers, selected_game_id)
                    sign_ok = self._is_sign_success(sign_result)
                    gift_summary = await self._claim_activity_gifts_for_role(
                        selected_game_id,
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
                    encrypted_account = self._encrypt_data(account)
                    encrypted_role_id = self._encrypt_data(selected_user["role_id"])
                    sender_id = event.get_sender_id().replace("/", "_")
                    user_data = self._load_user_data(sender_id) or {
                        "num": 0,
                        "users": [],
                    }
                    users = (
                        user_data.get("users", [])
                        if isinstance(user_data, dict)
                        else []
                    )
                    if not isinstance(users, list):
                        users = []
                    user_record = {
                        "account": encrypted_account,
                        "role_id": encrypted_role_id,
                        "info": selected_info,
                        "sign_status": self._build_sign_status(
                            "success" if sign_ok else "failed",
                            sign_result.get("message", "首次绑定后签到成功"),
                        ),
                    }
                    self._set_bound_game_id(user_record, selected_game_id)
                    users.append(user_record)
                    self._save_user_data(sender_id, {"num": len(users), "users": users})
                else:
                    await event.send(
                        event.plain_result(f"❌ 绑定失败，{result.get('message')}")
                    )
                controller.stop()
                return

        try:
            await bind_waiter(event)
        except TimeoutError:
            logger.warning("选择超时！")
            await event.send(event.plain_result("❌ 选择超时，终止运行"))
        except Exception as e:
            logger.error("选择发生错误" + str(e))
        event.stop_event()

    async def batch_bind_accounts_impl(self, event: AstrMessageEvent):
        """处理批量绑定账号的请求，解析用户提供的批量绑定数据并执行绑定操作。
        Args:
            event: 消息事件对象。
        Returns:
            None
        """
        if not self.headers:
            await event.send(
                event.plain_result("❌ 未配置签到请求头，暂时无法批量绑定")
            )
            return

        payload, error_msg = await self._load_quoted_json_payload(event)
        if error_msg:
            await event.send(event.plain_result(f"❌ {error_msg}"))
            return
        if payload is None:
            await event.send(event.plain_result("❌ 批量绑定文件为空或格式不正确"))
            return

        server_to_game_id = {
            "官服": "39",
            "光子服": "26",
            "39": "39",
            "26": "26",
        }

        sender_id = event.get_sender_id().replace("/", "_")
        user_data = self._load_user_data(sender_id) or {"num": 0, "users": []}
        users = user_data.get("users", []) if isinstance(user_data, dict) else []
        if not isinstance(users, list):
            users = []

        total_uid_count = 0
        success_count = 0
        failed_count = 0
        success_lines: list[str] = []
        failed_lines: list[str] = []
        await event.send(event.plain_result("⏳ 正在执行批量绑定,请稍候..."))
        for server_name, entries in payload.items():
            if not isinstance(entries, list):
                failed_count += 1
                failed_lines.append(f"- [{server_name}] 数据格式错误，必须是数组")
                continue

            expected_game_id = server_to_game_id.get(str(server_name))
            for entry_index, entry in enumerate(entries, start=1):
                if not isinstance(entry, dict):
                    failed_count += 1
                    failed_lines.append(
                        f"- [{server_name}] 第{entry_index}条 条目格式错误，必须是对象"
                    )
                    continue

                phone = str(entry.get("phone", "")).strip()
                uid_values = entry.get("uid", [])
                if isinstance(uid_values, str):
                    uid_list = [uid_values.strip()] if uid_values.strip() else []
                elif isinstance(uid_values, list):
                    uid_list = [
                        str(uid).strip() for uid in uid_values if str(uid).strip()
                    ]
                else:
                    uid_list = []

                total_uid_count += len(uid_list)
                if not phone or not uid_list:
                    failed_count += 1
                    failed_lines.append(
                        f"- [{server_name}] 第{entry_index}条 手机号或 uid 为空，已跳过"
                    )
                    continue

                roles = await get_server(phone)
                if not roles:
                    failed_count += len(uid_list)
                    failed_lines.extend(
                        [
                            f"- [{server_name}] 第{entry_index}条 第{uid_index}个角色 获取角色失败"
                            for uid_index, _ in enumerate(uid_list, start=1)
                        ]
                    )
                    continue

                role_map: dict[str, dict] = {}
                for role in roles:
                    if not isinstance(role, dict):
                        continue
                    role_id = str(role.get("role_id", "")).strip()
                    if not role_id:
                        continue
                    current_role_game_id = self._get_bound_game_id(role)
                    if expected_game_id and current_role_game_id != expected_game_id:
                        continue
                    role_map[role_id] = role

                for uid_index, uid in enumerate(uid_list, start=1):
                    role_marker = (
                        f"[{server_name}] 第{entry_index}条 第{uid_index}个角色"
                    )
                    selected_user = role_map.get(uid)
                    if not selected_user:
                        failed_count += 1
                        failed_lines.append(f"- {role_marker} 未匹配到对应角色")
                        continue

                    selected_info = self._format_role_info(selected_user)
                    selected_game_id = self._get_bound_game_id(selected_user)
                    if not selected_game_id:
                        selected_game_id = expected_game_id or "39"
                    try:
                        request_payload = convert_to_query_bytes(selected_user, phone)
                    except Exception as exc:
                        failed_count += 1
                        failed_lines.append(f"- {role_marker} 绑定数据编码失败: {exc}")
                        continue

                    result = await binds_account(self.headers, request_payload)
                    if result.get("code") != 200:
                        failed_count += 1
                        failed_lines.append(
                            f"- ❌ 绑定失败: {selected_info} ({result.get('message', '未知错误')})"
                        )
                        continue

                    sign_result = await sign_request(self.headers, selected_game_id)
                    sign_ok = self._is_sign_success(sign_result)
                    gift_summary = await self._claim_activity_gifts_for_role(
                        selected_game_id,
                        str(selected_user.get("role_id", uid)),
                    )

                    user_record = {
                        "account": self._encrypt_data(phone),
                        "role_id": self._encrypt_data(
                            str(selected_user.get("role_id", uid))
                        ),
                        "info": selected_info,
                        "sign_status": self._build_sign_status(
                            "success" if sign_ok else "failed",
                            sign_result.get("message", "首次绑定后签到成功"),
                        ),
                    }
                    self._set_bound_game_id(user_record, selected_game_id)
                    users.append(user_record)

                    success_count += 1
                    gift_prefix = "✅" if gift_summary["success_count"] > 0 else "ℹ️"
                    success_lines.append(
                        "\n".join(
                            [
                                f" {selected_info}\n✅ 绑定成功",
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
                    await asyncio.sleep(max(3, random.uniform(3, 15)))
        if users:
            self._save_user_data(sender_id, {"num": len(users), "users": users})

        summary_lines = [
            "【批量绑定汇总】",
            f"总UID数: {total_uid_count}",
            f"成功: {success_count}",
            f"失败: {failed_count}",
            "",
        ]
        if success_lines:
            summary_lines.append("成功详情:")
            summary_lines.extend(success_lines)
            summary_lines.append("")
        if failed_lines:
            summary_lines.append("失败详情:")
            summary_lines.extend(failed_lines)

        await event.send(event.plain_result("\n".join(summary_lines).strip()))
        event.stop_event()

    async def query_account_impl(self, event: AstrMessageEvent):
        """处理查询绑定账号的请求，加载用户绑定数据并展示给用户。
        Args:
            event: 消息事件对象。
        Returns:
            None
        """
        user_id = event.get_sender_id().replace("/", "_")
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

    async def delete_account_impl(self, event: AstrMessageEvent):
        """处理注销绑定账号的请求，引导用户选择需要删除的绑定账号并执行删除操作。
        Args:
            event: 消息事件对象。
        Returns:
            None
        """
        user_id = event.get_sender_id().replace("/", "_")
        user_file = self._get_user_file(user_id)
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
                select_info = "选择需要删除的账号:\n回复 退出 或 取消 可结束当前流程。"
                index = 1
                for user in users:
                    select_info += f"\n{index}. {user['info']}"
                    index += 1
                message_id = await send_msg(event, select_info)

                @session_waiter(timeout=20)
                async def delete_waiter(
                    controller: SessionController, event: AstrMessageEvent
                ):
                    nonlocal message_id, users, user_file, user_id
                    now_user_id = event.get_sender_id().replace("/", "_")
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
                    if isinstance(event, AiocqhttpMessageEvent):
                        if message_id:
                            await event.bot.delete_msg(message_id=message_id)
                            message_id = None
                    if len(parts) == 1 and parts[0].isdigit():
                        select_index = int(parts[0])
                        if select_index < 1 or select_index > len(users):
                            return
                        selected_user = users[select_index - 1]
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
                except TimeoutError:
                    logger.warning("选择超时！")
                    await event.send(event.plain_result("❌ 选择超时，终止运行"))
        except Exception as e:
            logger.error(f"读取用户数据失败: {e}")
            await event.send(event.plain_result("❌ 读取数据失败"))

    async def schedule_sign_impl(self, event: AstrMessageEvent, enabled: str):
        """处理定时签到推送的请求，根据用户输入开启或关闭定时签到推送功能。
        Args:
            event: 消息事件对象。
            enabled: 用户输入的开启或关闭指令。
        Returns:
            None
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

    async def force_auto_sign_impl(self, event: AstrMessageEvent):
        """强制执行自动签到操作。
        Args:
            event: 消息事件对象。
        Returns:
            None
        """
        # 强制执行自动签到操作，通常用于测试或管理员手动触发签到流程。
        await self.auto_sign_in()

        event.stop_event()

    async def show_help_impl(self, event: AstrMessageEvent):
        """处理显示帮助信息的请求，向用户展示插件的使用说明。
        Args:
            event: 消息事件对象。
        Returns:
            None
        """
        help_text = (
            "【最强蜗牛插件帮助】\n"
            "绑定账号 <手机号> (例:/绑定账号 1234567890)\n"
            "最强蜗牛 批量绑定 (需引用JSON模板文件)\n"
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
        """执行自动签到操作，处理定时签到任务。
        Returns:
            None
        """
        prepared = self._prepare_scheduled_user_files("定时签到任务")
        if prepared is None:
            return
        group_targets, user_files = prepared

        started_at = time.time()
        summary_lines: list[str] = []
        total_account_count = 0
        success_account_count = 0
        failed_account_count = 0
        gift_success_account_count = 0
        gift_failed_account_count = 0
        gift_skipped_account_count = 0
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
            for index, user_file in enumerate(user_files, start=1):
                user_id = user_file.stem
                success_count = 0
                failed_count = 0
                account_count = 0
                invalid_account_count = 0
                role_summary_lines: list[str] = []
                self._set_auto_sign_progress(
                    running=True,
                    completed_users=index - 1,
                    current_user=user_id,
                    current_role=None,
                )
                writer_data: list[dict[str, Any]] = []
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
                    users = self._load_task_users(user_file, user_id, "定时签到")
                    if users is None:
                        failed_user_count += 1
                        summary_lines.append(
                            f"- 用户ID: {user_id}，账号总数: 0，成功: 0，失败: 0"
                        )
                        continue

                    def handle_invalid_role(user: dict[str, Any]) -> None:
                        self._set_user_sign_status(
                            user, "invalid", "角色绑定数据已损坏"
                        )
                        writer_data.append(user)

                    users, invalid_account_count = self._deduplicate_bound_users(
                        user_id,
                        users,
                        on_invalid=handle_invalid_role,
                    )
                    failed_count += invalid_account_count
                    failed_account_count += invalid_account_count
                    account_count = len(users) + invalid_account_count
                    total_account_count += account_count
                    self.randomizer.shuffle(users)
                    for user in users:
                        info = user.get("info", "未知角色")
                        detail_parts = [f"角色: {info}"]
                        bound_game_id = self._get_bound_game_id(user)
                        self._set_auto_sign_progress(
                            running=True,
                            completed_users=index - 1,
                            current_user=user_id,
                            current_role=info,
                        )
                        try:
                            account = self._decrypt_data(user["account"])
                            role_id = self._decrypt_data(user["role_id"])
                        except Exception as exc:
                            logger.error(f"解密用户 {user_id} 的账号数据失败: {exc}")
                            self._set_user_sign_status(
                                user, "invalid", "账号数据解密失败"
                            )
                            writer_data.append(user)
                            failed_count += 1
                            failed_account_count += 1
                            detail_parts.append("结果: 账号数据解密失败")
                            role_summary_lines.append(f"  - {'；'.join(detail_parts)}")
                            continue

                        info = user.get("info", "")
                        detail_parts = [f"角色: {info or '未知角色'}"]
                        users_server_data = await get_server(account)
                        if users_server_data is None or len(users_server_data) == 0:
                            self._set_user_sign_status(
                                user, "failed", "获取角色信息失败"
                            )
                            logger.error(f"获取角色信息失败: {info or user_id}")
                            writer_data.append(user)
                            failed_count += 1
                            failed_account_count += 1
                            detail_parts.append("结果: 获取角色信息失败")
                            role_summary_lines.append(f"  - {'；'.join(detail_parts)}")
                            continue
                        matched = False
                        for user_server_data in users_server_data:
                            current_game_id = self._get_bound_game_id(user_server_data)
                            if (
                                user_server_data.get("role_id") == role_id
                                and current_game_id == bound_game_id
                            ):
                                matched = True
                                self._set_bound_game_id(user, current_game_id)
                                info = self._format_role_info(user_server_data)
                                user["info"] = info
                                detail_parts = [f"角色: {info}"]
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
                                    detail_parts.append("结果: 角色数据异常")
                                    role_summary_lines.append(
                                        f"  - {'；'.join(detail_parts)}"
                                    )
                                    break

                                result = await binds_account(self.headers, payload)
                                if result.get("code") == 200:
                                    sign_result = await sign_request(
                                        self.headers, current_game_id
                                    )
                                    sign_message = str(
                                        sign_result.get("message", "未知结果")
                                    )
                                    if self._is_sign_success(sign_result):
                                        self._set_user_sign_status(
                                            user,
                                            "success",
                                            sign_message or "签到成功",
                                        )
                                        detail_parts.append(
                                            f"结果: 签到成功({sign_message or '签到成功'})"
                                        )
                                        success_count += 1
                                        success_account_count += 1
                                    else:
                                        self._set_user_sign_status(
                                            user,
                                            "failed",
                                            sign_message or "签到失败",
                                        )
                                        failed_count += 1
                                        failed_account_count += 1
                                        detail_parts.append(
                                            f"结果: 签到失败({sign_message or '签到失败'})"
                                        )

                                    # 周五同步领取活动礼包
                                    if datetime.now().weekday() == 4:
                                        try:
                                            gift_summary = await asyncio.wait_for(
                                                self._claim_activity_gifts_for_role(
                                                    current_game_id,
                                                    role_id,
                                                ),
                                                timeout=60,
                                            )
                                        except asyncio.TimeoutError:
                                            logger.error(
                                                f"领取活动礼包超时: {info or user_id}"
                                            )
                                            gift_summary = {
                                                "success_count": 0,
                                                "failed_count": 1,
                                                "claimed_gifts": [],
                                                "failed_gifts": ["领取超时"],
                                                "has_claim_attempt": False,
                                            }
                                        except Exception as exc:
                                            logger.error(
                                                f"领取活动礼包失败: {info or user_id}: {exc}"
                                            )
                                            gift_summary = {
                                                "success_count": 0,
                                                "failed_count": 1,
                                                "claimed_gifts": [],
                                                "failed_gifts": ["领取异常"],
                                                "has_claim_attempt": False,
                                            }
                                        if not isinstance(gift_summary, dict):
                                            logger.error(
                                                f"领取活动礼包返回数据异常: {info or user_id}"
                                            )
                                            gift_summary = {
                                                "success_count": 0,
                                                "failed_count": 1,
                                                "claimed_gifts": [],
                                                "failed_gifts": ["返回数据异常"],
                                                "has_claim_attempt": False,
                                            }

                                        gift_success_count = int(
                                            gift_summary.get("success_count", 0) or 0
                                        )
                                        gift_failed_count = int(
                                            gift_summary.get("failed_count", 0) or 0
                                        )
                                        if gift_success_count > 0:
                                            gift_success_account_count += 1
                                        elif gift_failed_count > 0:
                                            gift_failed_account_count += 1
                                        else:
                                            gift_skipped_account_count += 1

                                        claimed_gifts = gift_summary.get(
                                            "claimed_gifts", []
                                        )
                                        failed_gifts = gift_summary.get(
                                            "failed_gifts", []
                                        )
                                        if claimed_gifts:
                                            detail_parts.append(
                                                f"已领取礼包: {'、'.join(str(name) for name in claimed_gifts)}"
                                            )
                                        if failed_gifts:
                                            detail_parts.append(
                                                f"失败礼包: {'、'.join(str(name) for name in failed_gifts)}"
                                            )
                                        if not claimed_gifts and not failed_gifts:
                                            detail_parts.append(
                                                "已领取礼包: 无可领取礼包"
                                            )
                                        if gift_summary.get("has_claim_attempt", False):
                                            await asyncio.sleep(
                                                max(3, random.uniform(3, 15))
                                            )
                                    elif self._is_sign_success(sign_result):
                                        await asyncio.sleep(
                                            max(3, random.uniform(3, 15))
                                        )
                                else:
                                    error_message = result.get("message", "未知错误")
                                    self._set_user_sign_status(
                                        user, "failed", error_message
                                    )
                                    failed_count += 1
                                    failed_account_count += 1
                                    detail_parts.append(
                                        f"结果: 绑定失败({error_message})"
                                    )
                                role_summary_lines.append(
                                    f"  - {'；'.join(detail_parts)}"
                                )
                                writer_data.append(user)
                                break
                        if not matched:
                            logger.warning(f"定时签到未找到匹配角色: {info or user_id}")
                            self._set_user_sign_status(
                                user, "failed", "未找到最新角色信息"
                            )
                            writer_data.append(user)
                            failed_count += 1
                            failed_account_count += 1
                            detail_parts.append("结果: 未找到最新角色信息")
                            role_summary_lines.append(f"  - {'；'.join(detail_parts)}")
                except Exception as e:
                    logger.error(f"读取用户 {user_id} 的数据失败: {e}")
                    failed_user_count += 1
                    summary_lines.append(
                        f"- 用户ID: {user_id}，账号总数: {account_count}，成功: {success_count}，失败: {failed_count}"
                    )
                    continue
                writer = {"num": 0, "users": writer_data}
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
                summary_lines.extend(role_summary_lines)
                self._set_auto_sign_progress(
                    running=True,
                    completed_users=index,
                    current_user=user_id,
                    current_role=None,
                )

            if group_targets and summary_lines:
                duration_seconds = max(0.0, time.time() - started_at)
                summary_header = [
                    f"- 签到成功用户数: {success_user_count}",
                    f"- 签到失败用户数: {failed_user_count}",
                    f"- 账号总数: {total_account_count}",
                    f"- 签到成功账号数: {success_account_count}",
                    f"- 签到失败账号数: {failed_account_count}",
                ]
                if (
                    gift_success_account_count
                    or gift_failed_account_count
                    or gift_skipped_account_count
                ):
                    summary_header.extend(
                        [
                            f"- 礼包领取成功: {gift_success_account_count}",
                            f"- 礼包领取失败: {gift_failed_account_count}",
                            f"- 无可领礼包: {gift_skipped_account_count}",
                        ]
                    )
                summary_header.extend(
                    [
                        f"- 签到耗时: {duration_seconds:.1f} 秒",
                        "",
                        "## 用户明细",
                    ]
                )
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

    async def keep_sign_in(self):
        """Keep-sign-in 定时任务：遍历用户数据，绑定角色以保持会话活性。
        随机打乱后逐个尝试，直到成功绑定一次为止，避免单次失败导致 headers 过期。
        """
        user_dir = self._get_user_dir()
        if not user_dir.exists():
            logger.info("未找到用户绑定目录，跳过 keep_sign_in")
            return

        user_files = list(user_dir.glob("*.json"))
        if not user_files:
            logger.info("用户绑定目录为空，跳过 keep_sign_in")
            return

        # 随机打乱所有用户文件，逐个尝试直到成功
        self.randomizer.shuffle(user_files)
        for user_file in user_files:
            user_id = user_file.stem

            try:
                with user_file.open("r", encoding="utf-8") as f:
                    user_data = json.load(f)
            except Exception as e:
                logger.warning(f"keep_sign_in 读取用户 {user_id} 数据失败: {e}")
                continue

            users = user_data.get("users", []) if isinstance(user_data, dict) else []
            if not isinstance(users, list) or not users:
                continue

            # 去重后随机打乱
            users, _ = self._deduplicate_bound_users(user_id, users)
            if not users:
                continue
            self.randomizer.shuffle(users)

            for chosen_user in users:
                info = chosen_user.get("info", "未知角色")
                bound_game_id = self._get_bound_game_id(chosen_user)

                try:
                    account = self._decrypt_data(chosen_user["account"])
                    role_id = self._decrypt_data(chosen_user["role_id"])
                except Exception as e:
                    logger.warning(f"keep_sign_in 解密用户 {user_id} 数据失败: {e}")
                    continue

                users_server_data = await get_server(account)
                if not users_server_data:
                    logger.warning(f"keep_sign_in 获取角色信息失败: {info}")
                    continue

                # 匹配角色
                matched = False
                for user_server_data in users_server_data:
                    current_game_id = self._get_bound_game_id(user_server_data)
                    if (
                        user_server_data.get("role_id") == role_id
                        and current_game_id == bound_game_id
                    ):
                        matched = True
                        matched_info = self._format_role_info(user_server_data)
                        try:
                            payload = convert_to_query_bytes(user_server_data, account)
                        except Exception as e:
                            logger.warning(f"keep_sign_in 编码绑定数据失败: {e}")
                            break

                        result = await binds_account(self.headers, payload)
                        if result.get("code") == 200:
                            logger.info(f"keep_sign_in 绑定成功: {matched_info}")
                            return  # 成功即返回
                        else:
                            logger.warning(
                                f"keep_sign_in 绑定失败: {matched_info} -> "
                                f"{result.get('message', '未知错误')}"
                            )
                        break

                if not matched:
                    logger.warning(f"keep_sign_in 未找到匹配角色: {info}")

        logger.warning("keep_sign_in 所有用户均尝试失败，headers 可能已过期")

    async def account_statistics_impl(self, event: AstrMessageEvent):
        """处理账号统计的请求，统计当前绑定数据中的用户数和账号数，并将统计结果返回给用户。
        Args:
            event: 消息事件对象。
        Returns:
            None
        """
        user_dir = self._get_user_dir()
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
