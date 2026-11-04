import asyncio
import json
import random
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, MessageChain
from astrbot.core.platform import MessageType as PlatformMessageType
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import (
    AiocqhttpMessageEvent,
)
from astrbot.core.utils.session_waiter import SessionController, session_waiter

from .sign_in import binds_account, get_server, sign_request
from .signin_preferences import (
    load_sign_push_payload,
    update_signin_notification_enabled,
    write_sign_push_payload,
)
from .signin_summary import (
    build_role_summary_record,
    build_signin_summary,
    build_user_summary_record,
)
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

        push_targets = self._get_sign_push_targets()
        user_dir = self._get_user_dir()
        if not user_dir.exists():
            logger.info(f"未找到用户绑定目录，跳过{task_name}")
            return None

        user_files = list(user_dir.glob("*.json"))
        if not user_files:
            logger.info(f"用户绑定目录为空，跳过{task_name}")
            return None

        self.randomizer.shuffle(user_files)
        return push_targets, user_files

    def _binding_pause_message(self) -> str:
        progress = getattr(self, "_auto_sign_progress", {}) or {}
        if progress.get("running"):
            return (
                "⏳ 每日定时签到正在执行，暂不能进行账号绑定。\n"
                "请稍后重试；发送「定时签到进度」可查看当前进度。"
            )
        if getattr(self, "_keep_sign_running", False):
            return "⏳ 签到保活任务正在执行，暂不能进行账号绑定。请稍后重试。"
        return ""

    async def _send_binding_pause_notice(self, targets: list[str]) -> None:
        if not targets:
            return
        notice = (
            "【每日定时签到开始】\n"
            "本次签到执行期间，插件指令与网页都会暂停新增账号绑定，"
            "任务结束后自动恢复。\n"
            "发送「定时签到进度」可查看当前进度。"
        )
        for target in targets:
            try:
                sent = await self._send_summary_chain_with_retry(
                    target,
                    MessageChain().message(notice),
                    label="签到开始提示 ",
                )
                if sent:
                    logger.info(f"已发送定时签到开始提示到 {target}")
                else:
                    logger.error(f"发送定时签到开始提示到 {target} 失败")
            except Exception as exc:
                logger.error(f"发送定时签到开始提示到 {target} 时发生异常: {exc}")

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
        unique_users: dict[tuple[str, str, str], dict[str, Any]] = {}
        invalid_account_count = 0
        for user in users:
            identity = self._role_identity_from_user(user)
            if identity is None:
                logger.error(f"解密用户 {user_id} 的角色数据失败")
                invalid_account_count += 1
                if on_invalid is not None:
                    on_invalid(user)
                continue
            unique_users[identity] = user
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

        pause_message = self._binding_pause_message()
        if pause_message:
            await event.send(event.plain_result(pause_message))
            event.stop_event()
            return

        if not self.headers:
            logger.warning("尝试绑定账号，但插件未配置可用的 headers")
            await event.send(
                event.plain_result("❌ 未配置签到请求头，暂时无法绑定账号")
            )
            return
        try:
            # Validate the local persistence requirement before creating a
            # remote binding that cannot be represented in local storage.
            self._get_encryption_secret_key()
        except ValueError as exc:
            await event.send(event.plain_result(f"❌ {exc}"))
            event.stop_event()
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
        sender_id = event.get_sender_id().replace("/", "_")
        user_id = None
        if group_id and group_id != 0:
            user_id = sender_id

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
                selected_role_id = str(selected_user["role_id"])
                pause_message = self._binding_pause_message()
                if pause_message:
                    await event.send(event.plain_result(pause_message))
                    controller.stop()
                    return
                owner_qq = self._find_role_owner(
                    account, selected_game_id, selected_role_id, sender_id
                )
                if owner_qq is not None:
                    if owner_qq == sender_id:
                        message = f"ℹ️ 你已经绑定过该角色：{selected_info}"
                    else:
                        message = (
                            f"⚠️ 该角色已被 QQ {owner_qq} 绑定，无法重复绑定："
                            f"{selected_info}"
                        )
                    await event.send(event.plain_result(message))
                    controller.stop()
                    return
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
                    sign_state, sign_message = self._format_sign_result_message(
                        sign_result
                    )
                    sign_mark = {
                        "success": "✅",
                        "already_claimed": "ℹ️",
                        "failed": "❌",
                    }[sign_state]
                    gift_summary = await self._claim_activity_gifts_for_role(
                        selected_game_id,
                        str(selected_user["role_id"]),
                    )
                    gift_prefix = "✅" if gift_summary["success_count"] > 0 else "ℹ️"
                    encrypted_account = self._encrypt_data(account)
                    encrypted_role_id = self._encrypt_data(selected_role_id)
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
                            sign_state,
                            sign_message,
                        ),
                    }
                    self._set_bound_game_id(user_record, selected_game_id)
                    users.append(user_record)
                    if not self._save_user_data(
                        sender_id, {"num": len(users), "users": users}
                    ):
                        await event.send(
                            event.plain_result(
                                "❌ 游戏侧已完成绑定，但本地保存失败。"
                                "请发送“签到”重试，或联系管理员检查数据目录权限。"
                            )
                        )
                        controller.stop()
                        return
                    await event.send(
                        event.plain_result(
                            "\n".join(
                                [
                                    f"✅ 绑定成功: {selected_info}",
                                    (f"{sign_mark} 首次绑定执行签到: {sign_message}"),
                                    (
                                        f"{gift_prefix} 活动礼包结果: "
                                        + "；".join(gift_summary["messages"])
                                    ),
                                ]
                            )
                        )
                    )
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
        pause_message = self._binding_pause_message()
        if pause_message:
            await event.send(event.plain_result(pause_message))
            return

        if not self.headers:
            await event.send(
                event.plain_result("❌ 未配置签到请求头，暂时无法批量绑定")
            )
            return
        try:
            self._get_encryption_secret_key()
        except ValueError as exc:
            await event.send(event.plain_result(f"❌ {exc}"))
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
        storage_error = False
        success_lines: list[str] = []
        failed_lines: list[str] = []
        await event.send(event.plain_result("⏳ 正在执行批量绑定,请稍候..."))
        binding_paused = ""
        for server_name, entries in payload.items():
            if binding_paused:
                break
            if not isinstance(entries, list):
                failed_count += 1
                failed_lines.append(f"- [{server_name}] 数据格式错误，必须是数组")
                continue

            expected_game_id = server_to_game_id.get(str(server_name))
            for entry_index, entry in enumerate(entries, start=1):
                if binding_paused:
                    break
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
                    binding_paused = self._binding_pause_message()
                    if binding_paused:
                        break
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
                    selected_role_id = str(selected_user.get("role_id", uid))
                    owner_qq = self._find_role_owner(
                        phone, selected_game_id, selected_role_id, sender_id
                    )
                    if owner_qq is not None:
                        failed_count += 1
                        if owner_qq == sender_id:
                            failed_lines.append(
                                f"- {role_marker} 你已经绑定过该角色: {selected_info}"
                            )
                        else:
                            failed_lines.append(
                                f"- {role_marker} 已被 QQ {owner_qq} 绑定: {selected_info}"
                            )
                        continue
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
                    sign_state, sign_message = self._format_sign_result_message(
                        sign_result
                    )
                    sign_mark = {
                        "success": "✅",
                        "already_claimed": "ℹ️",
                        "failed": "❌",
                    }[sign_state]
                    gift_summary = await self._claim_activity_gifts_for_role(
                        selected_game_id,
                        selected_role_id,
                    )

                    user_record = {
                        "account": self._encrypt_data(phone),
                        "role_id": self._encrypt_data(selected_role_id),
                        "info": selected_info,
                        "sign_status": self._build_sign_status(
                            sign_state,
                            sign_message,
                        ),
                    }
                    self._set_bound_game_id(user_record, selected_game_id)
                    users.append(user_record)

                    # 每条成功即落盘：整批结束才写一次的话，中途异常或插件重载
                    # 会让已经提示“绑定成功”的角色在本地零记录。
                    if not self._append_user_record(sender_id, user_record):
                        storage_error = True
                        logger.error(f"批量绑定写回本地失败: {selected_info}")

                    success_count += 1
                    gift_prefix = "✅" if gift_summary["success_count"] > 0 else "ℹ️"
                    success_lines.append(
                        "\n".join(
                            [
                                f" {selected_info}\n✅ 绑定成功",
                                (f"{sign_mark} 首次绑定执行签到: {sign_message}"),
                                (
                                    f"{gift_prefix} 活动礼包结果: "
                                    + "；".join(gift_summary["messages"])
                                ),
                            ]
                        )
                    )
                    await asyncio.sleep(max(3, random.uniform(3, 15)))

        if binding_paused:
            failed_lines.append(f"- {binding_paused.replace(chr(10), ' ')}")
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
        if storage_error:
            summary_lines.extend(
                [
                    "",
                    "⚠️ 游戏侧绑定已完成，但本地数据保存失败。",
                    "请检查插件数据目录权限后重新执行绑定。",
                ]
            )

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
            with user_file.open("r", encoding="utf-8") as handle:
                user_data = json.load(handle)
        except Exception as e:
            logger.error(f"读取用户 {user_id} 的绑定数据失败: {e}")
            await event.send(event.plain_result("❌ 读取数据失败，请稍后重试"))
            return

        users = user_data.get("users", []) if isinstance(user_data, dict) else []
        if not isinstance(users, list) or not users:
            await event.send(event.plain_result("❌ 未找到绑定数据"))
            return

        select_info = "选择需要删除的账号:\n回复 退出 或 取消 可结束当前流程。"
        for index, user in enumerate(users, start=1):
            info = (
                user.get("info", "未知角色") if isinstance(user, dict) else "未知角色"
            )
            select_info += f"\n{index}. {info}"
        message_id = await send_msg(event, select_info)

        @session_waiter(timeout=20)
        async def delete_waiter(controller: SessionController, event: AstrMessageEvent):
            nonlocal message_id, users, user_id
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
                del users[select_index - 1]
                if users:
                    if not self._save_user_data(
                        user_id, {"num": len(users), "users": users}
                    ):
                        logger.error(f"用户 {user_id} 保存删除结果失败")
                        await event.send(
                            event.plain_result("❌ 保存删除结果失败，请联系管理员")
                        )
                        controller.stop()
                        return
                else:
                    user_file.unlink(missing_ok=True)
                logger.info(f"用户 {user_id} 已删除一个绑定角色，剩余 {len(users)} 个")
                await event.send(event.plain_result("✅ 账号删除成功"))
                controller.stop()
                return

        try:
            await delete_waiter(event)
            event.stop_event()
        except TimeoutError:
            logger.warning("选择超时！")
            await event.send(event.plain_result("❌ 选择超时，终止运行"))
        except (OSError, RuntimeError, TypeError, ValueError) as e:
            logger.error(f"用户 {user_id} 注销流程异常: {e}")
            await event.send(event.plain_result("❌ 操作失败，请稍后重试"))

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
        data = load_sign_push_payload(self.data_dir)
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
            try:
                write_sign_push_payload(self.data_dir, data)
                update_signin_notification_enabled(self.data_dir, True)
            except Exception as exc:
                logger.error(f"保存定时签到推送目标失败: {exc}")
                yield event.plain_result("❌ 保存定时签到推送目标失败，请查看日志")
                return
            yield event.plain_result(f"✅ 群 {group_id} 已开启定时签到汇总推送")
        else:
            if group_origin not in groups:
                yield event.plain_result(
                    f"✅ 群 {group_id} 已经关闭定时签到汇总推送，无需重复操作"
                )
                return
            groups.remove(group_origin)
            data["datas"] = groups
            try:
                write_sign_push_payload(self.data_dir, data)
            except Exception as exc:
                logger.error(f"保存定时签到推送目标失败: {exc}")
                yield event.plain_result("❌ 保存定时签到推送目标失败，请查看日志")
                return
            yield event.plain_result(f"✅ 群 {group_id} 已关闭定时签到汇总推送")

    async def force_auto_sign_impl(self, event: AstrMessageEvent):
        """强制执行自动签到操作。
        Args:
            event: 消息事件对象。
        Returns:
            None
        """
        lock = getattr(self, "_auto_sign_lock", None)
        if lock is not None and lock.locked():
            await event.send(
                event.plain_result("⏳ 定时签到任务已在执行，请勿重复触发")
            )
            event.stop_event()
            return
        if getattr(self, "_keep_sign_running", False):
            await event.send(event.plain_result("⏳ 签到保活任务正在执行，请稍后再试"))
            event.stop_event()
            return
        # This entry point shares the same lock as the scheduled job.
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
            "签到 (处理当前 QQ 的绑定与首次签到)\n"
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
        """Run the full sign-in job while preventing overlapping executions.

        APScheduler already limits its own job, but administrators can also invoke
        the same workflow manually. A shared lock keeps both entry points from
        mutating user files and the remote game session at the same time.

        Returns:
            None
        """
        lock = getattr(self, "_auto_sign_lock", None)
        if lock is None:
            lock = asyncio.Lock()
            self._auto_sign_lock = lock
        if lock.locked():
            logger.info("定时签到任务已在执行，忽略重复触发")
            return
        if getattr(self, "_keep_sign_running", False):
            logger.info("签到保活任务正在执行，跳过本轮定时签到")
            return

        async with lock:
            try:
                await self._auto_sign_in_once()
            except BaseException:
                # Cancellation may happen before the inner try/finally is entered.
                # Restore visible state and the paused keep-alive job in that case.
                self._set_auto_sign_progress(
                    running=False,
                    current_user=None,
                    current_role=None,
                    last_finished_at=time.time(),
                )
                try:
                    if self.scheduler.get_job("keep_sign_in_job"):
                        self.scheduler.resume_job("keep_sign_in_job")
                except Exception as exc:
                    logger.error(f"恢复 keep_sign_in_job 失败: {exc}")
                raise

    async def _auto_sign_in_once(self):
        """Execute one complete sign-in pass.

        Returns:
            None
        """
        prepared = self._prepare_scheduled_user_files("定时签到任务")
        if prepared is None:
            return
        push_targets, user_files = prepared
        notification_settings = self._get_signin_notification_settings()

        started_at = time.time()
        run_records: list[dict[str, Any]] = []
        user_records: list[dict[str, Any]] = []
        total_account_count = 0
        success_account_count = 0
        already_claimed_account_count = 0
        failed_account_count = 0
        success_user_count = 0
        already_claimed_user_count = 0
        failed_user_count = 0
        self._set_auto_sign_progress(
            running=True,
            total_users=len(user_files),
            completed_users=0,
            current_user=None,
            current_role=None,
            started_at=started_at,
        )
        if notification_settings.get("enabled", True):
            await self._send_binding_pause_notice(push_targets)
        logger.info("每日定时签到已开始，新增账号绑定已临时暂停")

        if self.scheduler.get_job("keep_sign_in_job"):
            try:
                self.scheduler.pause_job("keep_sign_in_job")
                logger.info("自动签到开始，已暂停 keep_sign_in_job 保活任务")
            except Exception as exc:
                logger.error(f"暂停 keep_sign_in_job 失败: {exc}")

        try:
            for index, user_file in enumerate(user_files, start=1):
                user_id = user_file.stem
                success_count = 0
                already_claimed_count = 0
                failed_count = 0
                account_count = 0
                invalid_account_count = 0
                user_role_records: list[dict[str, Any]] = []
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
                        record = build_role_summary_record(
                            user_id,
                            "用户绑定数据",
                            "failed",
                            "未找到绑定数据文件",
                        )
                        run_records.append(record)
                        user_role_records.append(record)
                        user_records.append(
                            build_user_summary_record(
                                user_id, 0, 0, 0, user_role_records
                            )
                        )
                        continue
                    user_revision = self._user_file_revision(user_id)
                    users = self._load_task_users(user_file, user_id, "定时签到")
                    if users is None:
                        failed_user_count += 1
                        record = build_role_summary_record(
                            user_id,
                            "用户绑定数据",
                            "failed",
                            "读取绑定数据失败",
                        )
                        run_records.append(record)
                        user_role_records.append(record)
                        user_records.append(
                            build_user_summary_record(
                                user_id, 0, 0, 0, user_role_records
                            )
                        )
                        continue

                    def handle_invalid_role(user: dict[str, Any]) -> None:
                        self._set_user_sign_status(
                            user, "invalid", "角色绑定数据已损坏"
                        )
                        writer_data.append(user)
                        record = build_role_summary_record(
                            user_id,
                            user.get("info", "未知角色"),
                            "invalid",
                            "角色绑定数据已损坏",
                        )
                        run_records.append(record)
                        user_role_records.append(record)

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
                        if self._is_channel_record(user):
                            result = await self._sign_channel_record(
                                user,
                                claim_gifts=datetime.now().weekday() == 4,
                            )
                            sign_state = str(result.get("state", "failed"))
                            if sign_state == "success":
                                success_count += 1
                                success_account_count += 1
                            elif sign_state == "already_claimed":
                                already_claimed_count += 1
                                already_claimed_account_count += 1
                            else:
                                failed_count += 1
                                failed_account_count += 1
                            record = build_role_summary_record(
                                user_id,
                                info,
                                sign_state,
                                str(result.get("message", "")),
                                result.get("gift_summary") or None,
                            )
                            run_records.append(record)
                            user_role_records.append(record)
                            writer_data.append(user)
                            continue
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
                            record = build_role_summary_record(
                                user_id,
                                info,
                                "invalid",
                                "账号数据解密失败",
                            )
                            run_records.append(record)
                            user_role_records.append(record)
                            continue

                        info = user.get("info", "")
                        users_server_data = await get_server(account)
                        if users_server_data is None or len(users_server_data) == 0:
                            self._set_user_sign_status(
                                user, "failed", "获取角色信息失败"
                            )
                            logger.error(f"获取角色信息失败: {info or user_id}")
                            writer_data.append(user)
                            failed_count += 1
                            failed_account_count += 1
                            record = build_role_summary_record(
                                user_id,
                                info or "未知角色",
                                "failed",
                                "获取角色信息失败",
                            )
                            run_records.append(record)
                            user_role_records.append(record)
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
                                    record = build_role_summary_record(
                                        user_id,
                                        info,
                                        "invalid",
                                        "角色数据异常",
                                    )
                                    run_records.append(record)
                                    user_role_records.append(record)
                                    break

                                result = await binds_account(self.headers, payload)
                                if result.get("code") == 200:
                                    sign_result = await sign_request(
                                        self.headers, current_game_id
                                    )
                                    (
                                        sign_state,
                                        sign_status_message,
                                    ) = self._format_sign_result_message(sign_result)
                                    if sign_state == "success":
                                        self._set_user_sign_status(
                                            user,
                                            "success",
                                            sign_status_message,
                                        )
                                        success_count += 1
                                        success_account_count += 1
                                    elif sign_state == "already_claimed":
                                        self._set_user_sign_status(
                                            user,
                                            "already_claimed",
                                            sign_status_message,
                                        )
                                        already_claimed_count += 1
                                        already_claimed_account_count += 1
                                    else:
                                        self._set_user_sign_status(
                                            user,
                                            "failed",
                                            sign_status_message,
                                        )
                                        failed_count += 1
                                        failed_account_count += 1

                                    # 周五同步领取活动礼包
                                    gift_summary = None
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
                                                "failed_reasons": ["领取超时"],
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
                                                "failed_reasons": ["领取异常"],
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
                                                "failed_reasons": ["返回数据异常"],
                                                "has_claim_attempt": False,
                                            }

                                        if gift_summary.get("has_claim_attempt", False):
                                            await asyncio.sleep(
                                                max(3, random.uniform(3, 15))
                                            )
                                    elif sign_state == "success":
                                        await asyncio.sleep(
                                            max(3, random.uniform(3, 15))
                                        )
                                    record = build_role_summary_record(
                                        user_id,
                                        info,
                                        sign_state,
                                        sign_status_message,
                                        gift_summary,
                                    )
                                    run_records.append(record)
                                    user_role_records.append(record)
                                else:
                                    error_message = result.get("message", "未知错误")
                                    self._set_user_sign_status(
                                        user, "failed", error_message
                                    )
                                    failed_count += 1
                                    failed_account_count += 1
                                    record = build_role_summary_record(
                                        user_id,
                                        info,
                                        "failed",
                                        f"绑定失败（{error_message}）",
                                    )
                                    run_records.append(record)
                                    user_role_records.append(record)
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
                            record = build_role_summary_record(
                                user_id,
                                info or "未知角色",
                                "failed",
                                "未找到最新角色信息",
                            )
                            run_records.append(record)
                            user_role_records.append(record)
                except Exception as e:
                    logger.error(f"读取用户 {user_id} 的数据失败: {e}")
                    failed_user_count += 1
                    record = build_role_summary_record(
                        user_id,
                        "用户数据处理",
                        "failed",
                        f"读取用户数据失败：{e}",
                    )
                    run_records.append(record)
                    user_role_records.append(record)
                    user_records.append(
                        build_user_summary_record(
                            user_id,
                            account_count,
                            success_count,
                            failed_count,
                            user_role_records,
                        )
                    )
                    continue
                writer = {"num": 0, "users": writer_data}
                writer["num"] = len(writer_data)
                try:
                    if not self._save_user_data_snapshot(
                        user_id, user_revision, writer_data
                    ):
                        raise RuntimeError("写入用户数据失败")
                except Exception as e:
                    logger.error(f"写回用户 {user_id} 的签到数据失败: {e}")
                    record = build_role_summary_record(
                        user_id,
                        "用户数据处理",
                        "failed",
                        f"写回签到数据失败：{e}",
                    )
                    run_records.append(record)
                    user_role_records.append(record)
                    failed_user_count += 1
                    user_records.append(
                        build_user_summary_record(
                            user_id,
                            account_count,
                            success_count,
                            failed_count,
                            user_role_records,
                        )
                    )
                    continue
                role_count = account_count - invalid_account_count
                if success_count > 0:
                    success_user_count += 1
                elif already_claimed_count > 0:
                    already_claimed_user_count += 1
                elif role_count > 0:
                    failed_user_count += 1
                logger.info(f"用户 {user_id} 的定时签到已完成")
                user_records.append(
                    build_user_summary_record(
                        user_id,
                        account_count,
                        success_count,
                        failed_count,
                        user_role_records,
                        already_claimed_count,
                    )
                )
                self._set_auto_sign_progress(
                    running=True,
                    completed_users=index,
                    current_user=user_id,
                    current_role=None,
                )

            if (
                notification_settings.get("enabled", True)
                and push_targets
                and user_records
            ):
                duration_seconds = max(0.0, time.time() - started_at)
                gift_counts = dict.fromkeys(
                    ("success", "partial", "failed", "none", "off", "not_attempted"), 0
                )
                for record in run_records:
                    state = str(record.get("gift_state", "not_attempted"))
                    if state in gift_counts:
                        gift_counts[state] += 1
                summary_text = build_signin_summary(
                    records=run_records,
                    users=user_records,
                    stats={
                        "total_users": len(user_files),
                        "success_users": success_user_count,
                        "already_claimed_users": already_claimed_user_count,
                        "failed_users": failed_user_count,
                        "total_accounts": total_account_count,
                        "success_accounts": success_account_count,
                        "already_claimed_accounts": already_claimed_account_count,
                        "failed_accounts": failed_account_count,
                        "gift_counts": gift_counts,
                        "duration_seconds": duration_seconds,
                    },
                    detail_mode=str(
                        notification_settings.get("detail_mode", "issues_overview")
                    ),
                )
                summary_text += (
                    "\n\n账号绑定已恢复。"
                    "每日定时签到执行期间，插件与网页会临时暂停新增账号绑定。"
                )
                reward_image_path = (
                    self._get_today_reward_image_path()
                    if notification_settings.get("include_reward_image", True)
                    else None
                )
                results = await self._send_signin_summary_to_targets(
                    push_targets,
                    summary_text,
                    reward_image_path=reward_image_path,
                )
                for push_target, sent in results.items():
                    if sent:
                        logger.info(f"已发送定时签到汇总到 {push_target}")
                    else:
                        logger.error(f"发送定时签到汇总到 {push_target} 失败")
            elif not notification_settings.get("enabled", True):
                logger.info("签到汇总通知已关闭，已跳过汇总消息发送")
            elif not push_targets:
                logger.info("未配置签到汇总通知目标，已跳过汇总消息发送")
        finally:
            if self.scheduler.get_job("keep_sign_in_job"):
                try:
                    self.scheduler.resume_job("keep_sign_in_job")
                    logger.info("自动签到结束，已恢复 keep_sign_in_job 保活任务")
                except Exception as exc:
                    logger.error(f"恢复 keep_sign_in_job 失败: {exc}")
            self._set_auto_sign_progress(
                running=False,
                completed_users=len(user_files),
                current_user=None,
                current_role=None,
                last_finished_at=time.time(),
            )

    async def _run_keep_sign_in(self):
        if getattr(self, "_auto_sign_progress", {}).get("running"):
            logger.info("全量签到正在执行，跳过本轮签到保活")
            return
        self._keep_sign_running = True
        try:
            await self.keep_sign_in()
        finally:
            self._keep_sign_running = False

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
        attempted_roles = 0
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
            for user in users:
                if not self._is_channel_record(user):
                    continue
                attempted_roles += 1
                if await self._keep_alive_channel_record(user):
                    return
            users = [user for user in users if not self._is_channel_record(user)]
            if not users:
                continue
            self.randomizer.shuffle(users)

            for chosen_user in users:
                info = chosen_user.get("info", "未知角色")
                bound_game_id = self._get_bound_game_id(chosen_user)
                attempted_roles += 1

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

        if attempted_roles:
            logger.warning("keep_sign_in 所有用户均尝试失败，headers 可能已过期")
        else:
            logger.info("keep_sign_in 没有官服角色可保活，已跳过渠道服记录")

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
