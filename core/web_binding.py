from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
from pathlib import Path
from typing import Any

import aiohttp

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent

from .sign_in import (
    CHANNEL_PLATFORM_NAMES,
    CHANNEL_SIGN_PENDING_MESSAGE,
    binds_account,
    binds_channel_account,
    get_server,
    sign_request,
)
from .utils import atomic_write_json, convert_to_query_bytes

QQ_RE = re.compile(r"^\d{5,12}$")
PHONE_RE = re.compile(r"^1[3-9]\d{9}$")
SIGN_MODES = {"auto", "manual", "instant"}


class WebBindingMixin:
    """网页绑定同步与用户级首次签到。"""

    def _get_web_pending_dir(self) -> Path:
        return self.data_dir / "web_pending"

    def _get_web_sync_lock(self) -> asyncio.Lock:
        lock = getattr(self, "_web_sync_lock", None)
        if lock is None:
            lock = asyncio.Lock()
            self._web_sync_lock = lock
        return lock

    def _get_manual_sign_lock(self, sender_key: str) -> asyncio.Lock:
        locks = getattr(self, "_manual_sign_locks", None)
        if locks is None:
            locks = {}
            self._manual_sign_locks = locks
        lock = locks.get(sender_key)
        if lock is None:
            lock = asyncio.Lock()
            locks[sender_key] = lock
        return lock

    def _get_portal_settings(self) -> tuple[str, str] | None:
        base_url = str(self.config.get("web_portal_url", "") or "").strip().rstrip("/")
        token = str(self.config.get("web_portal_sync_token", "") or "").strip()
        if not base_url or not token:
            return None
        return base_url, token

    async def _portal_request(
        self,
        method: str,
        endpoint: str,
        *,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        portal = self._get_portal_settings()
        if portal is None:
            return None
        base_url, token = portal
        url = f"{base_url}/api/plugin/{endpoint}"
        progress = getattr(self, "_auto_sign_progress", {}) or {}
        signin_running = "1" if progress.get("running") else "0"
        headers = {
            "Authorization": f"Bearer {token}",
            "X-Snail-Signin-Running": signin_running,
        }
        timeout = aiohttp.ClientTimeout(total=20)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                request = session.get if method.upper() == "GET" else session.post
                async with request(url, headers=headers, json=json_body) as response:
                    body = await response.text()
                    if response.status >= 400:
                        logger.warning(
                            f"网页绑定接口 {endpoint} 返回 HTTP {response.status}: {body[:200]}"
                        )
                        return None
                    return json.loads(body) if body else {}
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as exc:
            logger.warning(f"网页绑定接口 {endpoint} 请求失败: {exc}")
            return None

    def _get_auto_sign_delay_seconds(self) -> int:
        raw = self.config.get("web_auto_sign_delay_seconds", 300)
        try:
            value = int(raw)
        except (TypeError, ValueError):
            value = 300
        return max(60, min(1500, value))

    def _web_role_key(self, account: Any, game_id: Any, role_id: Any) -> str:
        raw = f"{str(account)}:{str(game_id)}:{str(role_id)}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _write_web_pending(self, qq: str, records: list[dict[str, Any]]) -> None:
        folder = self._get_web_pending_dir()
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{qq}.json"
        payload = {
            "version": 3,
            "qq": qq,
            "updated_at": int(time.time()),
            "records": records,
        }
        # Pending records contain encrypted account identifiers, so keep the
        # file private while replacing it atomically for concurrent readers.
        atomic_write_json(path, payload, indent=2, mode=0o600)

    def _load_web_pending(self, qq: str) -> list[dict[str, Any]]:
        qq = re.sub(r"\D", "", str(qq))
        if not QQ_RE.fullmatch(qq):
            return []
        folder = self._get_web_pending_dir()
        path = folder / f"{qq}.json"
        if not path.exists():
            return []
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning(f"读取网页绑定暂存失败: {exc}")
            return []
        records = payload.get("records", []) if isinstance(payload, dict) else []
        if not isinstance(records, list):
            return []
        now = int(time.time())
        valid: list[dict[str, Any]] = []
        for item in records:
            if not isinstance(item, dict):
                continue
            try:
                expires_at = int(item.get("expires_at", 0))
            except (TypeError, ValueError):
                continue
            if expires_at <= now:
                continue
            sign_mode = str(item.get("sign_mode", "manual")).strip().lower()
            if sign_mode not in SIGN_MODES:
                sign_mode = "manual"
            item["sign_mode"] = sign_mode
            try:
                auto_sign_at = int(item.get("auto_sign_at", 0) or 0)
            except (TypeError, ValueError):
                auto_sign_at = 0
            if sign_mode == "auto" and auto_sign_at <= 0:
                try:
                    created_at = int(item.get("created_at", now) or now)
                except (TypeError, ValueError):
                    created_at = now
                auto_sign_at = created_at + self._get_auto_sign_delay_seconds()
            item["auto_sign_at"] = auto_sign_at if sign_mode == "auto" else 0
            try:
                item["auto_attempted_at"] = int(item.get("auto_attempted_at", 0) or 0)
            except (TypeError, ValueError):
                item["auto_attempted_at"] = 0
            valid.append(item)
        if not valid and path.exists():
            path.unlink()
        return valid

    def _remove_web_pending(self, qq: str, role_keys: set[str]) -> None:
        qq = re.sub(r"\D", "", str(qq))
        remaining = [
            item
            for item in self._load_web_pending(qq)
            if str(item.get("role_key", "")) not in role_keys
        ]
        folder = self._get_web_pending_dir()
        path = folder / f"{qq}.json"
        if remaining:
            self._write_web_pending(qq, remaining)
        elif path.exists():
            path.unlink()

    def _stage_web_item(self, item: dict[str, Any]) -> int:
        qq = re.sub(r"\D", "", str(item.get("qq", "")))
        request_id = str(item.get("request_id", "")).strip()
        expires_at = int(item.get("expires_at", 0) or 0)
        sign_mode = str(item.get("sign_mode", "manual")).strip().lower()
        if sign_mode not in SIGN_MODES:
            raise ValueError("签到模式无效")
        if not QQ_RE.fullmatch(qq):
            raise ValueError("QQ 格式无效")
        if not request_id:
            raise ValueError("缺少 request_id")
        if expires_at <= int(time.time()):
            raise ValueError("网页数据已过期")
        created_at = int(item.get("created_at", time.time()) or time.time())
        if sign_mode == "auto":
            auto_sign_at = created_at + self._get_auto_sign_delay_seconds()
        elif sign_mode == "instant":
            auto_sign_at = created_at
        else:
            auto_sign_at = 0

        existing = self._load_web_pending(qq)
        by_key = {str(record.get("role_key", "")): record for record in existing}
        staged = 0

        channel_roles = item.get("channel_roles")
        is_channel = str(item.get("binding_type", "")).strip().lower() == "channel" or (
            isinstance(channel_roles, list) and bool(channel_roles)
        )
        if is_channel:
            if not isinstance(channel_roles, list) or not channel_roles:
                raise ValueError("没有可用的渠道服角色数据")
            for role in channel_roles:
                if not isinstance(role, dict):
                    continue
                platform = str(role.get("platform", "")).strip().lower()
                role_id = str(role.get("role_id", "")).strip()
                role_name = str(role.get("role_name", "")).strip()
                if (
                    platform not in CHANNEL_PLATFORM_NAMES
                    or not role_id
                    or not role_name
                ):
                    continue
                role_key = self._web_role_key(f"channel:{platform}", "", role_id)
                by_key[role_key] = {
                    "request_id": request_id,
                    "binding_type": "channel",
                    "platform": platform,
                    "role_id": self._encrypt_data(role_id),
                    "role_name": self._encrypt_data(role_name),
                    "role_key": role_key,
                    "sign_mode": sign_mode,
                    "auto_sign_at": auto_sign_at,
                    "auto_attempted_at": 0,
                    "created_at": created_at,
                    "expires_at": expires_at,
                }
                staged += 1
        else:
            accounts = item.get("accounts")
            if not isinstance(accounts, list) or not accounts:
                accounts = [
                    {
                        "account": item.get("phone", ""),
                        "roles": item.get("roles", []),
                    }
                ]
            for account_item in accounts:
                if not isinstance(account_item, dict):
                    continue
                account = str(account_item.get("account", "")).strip()
                roles = account_item.get("roles", [])
                if not PHONE_RE.fullmatch(account):
                    raise ValueError("最强蜗牛账号格式无效")
                if not isinstance(roles, list) or not roles:
                    continue
                for role in roles:
                    if not isinstance(role, dict):
                        continue
                    game_id = str(role.get("game_id", "")).strip()
                    role_id = str(role.get("role_id", "")).strip()
                    if not game_id or not role_id:
                        continue
                    role_key = self._web_role_key(account, game_id, role_id)
                    by_key[role_key] = {
                        "request_id": request_id,
                        "account": self._encrypt_data(account),
                        "game_id": game_id,
                        "role_id": self._encrypt_data(role_id),
                        "role_key": role_key,
                        "sign_mode": sign_mode,
                        "auto_sign_at": auto_sign_at,
                        "auto_attempted_at": 0,
                        "created_at": created_at,
                        "expires_at": expires_at,
                    }
                    staged += 1
        if staged == 0:
            raise ValueError("没有可用的角色数据")
        self._write_web_pending(qq, list(by_key.values()))
        return staged

    def _mark_auto_attempted(self, qq: str, role_keys: set[str]) -> None:
        if not role_keys:
            return
        records = self._load_web_pending(qq)
        changed = False
        now = int(time.time())
        for record in records:
            if (
                str(record.get("role_key", "")) in role_keys
                and int(record.get("auto_attempted_at", 0) or 0) <= 0
            ):
                record["auto_attempted_at"] = now
                changed = True
        if changed:
            self._write_web_pending(qq, records)

    async def _ack_portal(
        self,
        request_id: str,
        lease_token: str,
        status: str,
        error: str | None = None,
    ) -> None:
        await self._portal_request(
            "POST",
            "ack",
            json_body={
                "request_id": request_id,
                "lease_token": lease_token,
                "status": status,
                "error": error,
            },
        )

    async def _report_web_result(
        self,
        request_id: str,
        status: str,
        result: dict[str, Any],
        created_at: int | None = None,
    ) -> None:
        if status not in {"success", "partial", "failed"}:
            status = "failed"
        if self._get_portal_settings() is None:
            return
        await self._portal_request(
            "POST",
            "result",
            json_body={
                "request_id": request_id,
                "created_at": int(created_at or 0) or None,
                "status": status,
                "result": result,
            },
        )

    def _staged_identity(self, record: dict[str, Any]) -> tuple[str, str, str] | None:
        """计算网页暂存记录对应的角色身份。"""
        try:
            if self._is_channel_record(record):
                platform = self._get_channel_platform(record)
                role_id = self._decrypt_data(str(record["role_id"]))
                if not platform or not role_id:
                    return None
                return (f"channel:{platform}", "", str(role_id))
            account = self._decrypt_data(
                str(record.get("account") or record.get("phone") or "")
            )
            role_id = self._decrypt_data(str(record["role_id"]))
            if not account or not role_id:
                return None
            return (str(account), str(record.get("game_id", "39")), str(role_id))
        except Exception:
            return None

    def _web_record_info(self, record: dict[str, Any]) -> str:
        label = str(record.get("label", "")).strip()
        if label:
            return label
        try:
            if self._is_channel_record(record):
                platform = self._get_channel_platform(record)
                role_name = self._decrypt_data(str(record.get("role_name", "")))
                if platform and role_name:
                    return self._format_channel_role_info(platform, role_name)
            return "官服角色"
        except Exception:
            return "角色信息"

    def _web_failure_result(
        self, records: list[dict[str, Any]], message: str
    ) -> tuple[str, dict[str, Any]]:
        roles: list[dict[str, str]] = []
        for record in records:
            binding_type = "channel" if self._is_channel_record(record) else "official"
            roles.append(
                {
                    "info": self._web_record_info(record),
                    "state": "failed",
                    "message": str(message or "绑定失败")[:300],
                    "binding_type": binding_type,
                    "platform": self._get_channel_platform(record)
                    if binding_type == "channel"
                    else "",
                }
            )
        binding_type = (
            "channel"
            if records and all(self._is_channel_record(record) for record in records)
            else "official"
        )
        return "failed", {
            "binding_type": binding_type,
            "roles": roles,
            "errors": [str(message or "绑定失败")[:300]],
        }

    def _build_web_request_result(
        self,
        records: list[dict[str, Any]],
        outcomes: dict[str, dict[str, Any]],
        users: list[dict[str, Any]],
        fallback_error: str = "",
    ) -> tuple[str, dict[str, Any]]:
        users_by_identity: dict[tuple[str, str, str], dict[str, Any]] = {}
        for user in users:
            identity = self._role_identity_from_user(user)
            if identity is not None and identity not in users_by_identity:
                users_by_identity[identity] = user

        roles: list[dict[str, Any]] = []
        errors: list[str] = []
        for record in records:
            role_key = str(record.get("role_key", ""))
            identity = self._staged_identity(record)
            user = users_by_identity.get(identity) if identity is not None else None
            outcome = outcomes.get(role_key, {})
            duplicate = outcome.get("state") == "duplicate"
            info = str(user.get("info", "")) if user else self._web_record_info(record)
            binding_type = "channel" if self._is_channel_record(record) else "official"
            platform = (
                self._get_channel_platform(record) if binding_type == "channel" else ""
            )
            if user:
                sign_status = user.get("sign_status", {})
                if not isinstance(sign_status, dict):
                    sign_status = {}
                state = str(sign_status.get("state", "failed") or "failed")
                message = str(sign_status.get("message", "") or "")
                if state == "pending":
                    state = "failed"
                    message = fallback_error or "绑定成功，但签到尚未完成，请稍后重试"
                if duplicate:
                    duplicate_message = str(outcome.get("message", "") or "").strip()
                    if duplicate_message:
                        message = (
                            f"{duplicate_message}；{message}"
                            if message
                            else duplicate_message
                        )
            elif duplicate:
                state = "failed"
                message = str(
                    outcome.get("message", "") or fallback_error or "重复绑定"
                )
            elif outcome.get("state") == "failed":
                state = "failed"
                message = str(
                    outcome.get("message", "") or fallback_error or "绑定失败"
                )
            else:
                state = "failed"
                message = fallback_error or str(
                    outcome.get("message", "") or "绑定或签到失败"
                )
            if state not in {
                "success",
                "already_claimed",
                "failed",
                "invalid",
                "pending",
            }:
                state = "failed"
            if state not in {"success", "already_claimed"} and message:
                errors.append(message[:300])
            roles.append(
                {
                    "info": info[:120],
                    "state": state,
                    "message": message[:300],
                    "binding_type": binding_type,
                    "platform": platform,
                    "duplicate": duplicate,
                }
            )
        success_count = sum(
            role["state"] in {"success", "already_claimed"} for role in roles
        )
        if roles and success_count == len(roles):
            overall = "success"
        elif success_count:
            overall = "partial"
        else:
            overall = "failed"
        binding_type = (
            "channel"
            if records and all(self._is_channel_record(record) for record in records)
            else "official"
        )
        return overall, {
            "binding_type": binding_type,
            "roles": roles,
            "errors": list(dict.fromkeys(errors))[:10],
        }

    async def sync_web_bindings(self) -> int:
        if not self.headers:
            return 0
        if self._get_portal_settings() is None:
            return 0
        async with self._get_web_sync_lock():
            payload = await self._portal_request("GET", "pending")
            if not payload:
                return 0
            items = payload.get("items", [])
            if not isinstance(items, list):
                return 0
            staged_requests = 0
            for item in items:
                if not isinstance(item, dict):
                    continue
                request_id = str(item.get("request_id", ""))
                lease_token = str(item.get("lease_token", ""))
                try:
                    staged = self._stage_web_item(item)
                    await self._ack_portal(request_id, lease_token, "imported")
                    staged_requests += 1
                    logger.info(f"已接收网页绑定申请 {request_id}，共 {staged} 个角色")
                except Exception as exc:
                    logger.warning(f"网页绑定申请 {request_id} 暂存失败: {exc}")
                    records = []
                    if isinstance(item.get("channel_roles"), list):
                        for role in item["channel_roles"]:
                            if not isinstance(role, dict):
                                continue
                            records.append(
                                {
                                    "binding_type": "channel",
                                    "platform": str(role.get("platform", "")),
                                    "label": self._format_channel_role_info(
                                        str(role.get("platform", "")).strip().lower(),
                                        str(role.get("role_name", "")).strip(),
                                    ),
                                }
                            )
                    elif isinstance(item.get("accounts"), list):
                        index = 0
                        for account_item in item["accounts"]:
                            if not isinstance(account_item, dict):
                                continue
                            for role in account_item.get("roles", []):
                                if not isinstance(role, dict):
                                    continue
                                index += 1
                                records.append(
                                    {
                                        "binding_type": "official",
                                        "label": f"官服角色 {index}",
                                    }
                                )
                    status_value, result = self._web_failure_result(records, str(exc))
                    await self._report_web_result(
                        request_id,
                        status_value,
                        result,
                        int(item.get("created_at", 0) or 0),
                    )
                    await self._ack_portal(request_id, lease_token, "failed", str(exc))
            return staged_requests

    async def auto_sign_web_bindings(self) -> int:
        if not self.headers or self._get_portal_settings() is None:
            return 0
        if getattr(self, "_keep_sign_running", False):
            return 0
        if getattr(self, "_auto_sign_progress", {}).get("running"):
            return 0
        await self.sync_web_bindings()
        folder = self._get_web_pending_dir()
        if not folder.exists():
            return 0

        processed = 0
        for path in sorted(folder.glob("*.json")):
            qq = path.stem
            if not QQ_RE.fullmatch(qq):
                continue
            now = int(time.time())
            due = [
                record
                for record in self._load_web_pending(qq)
                if record.get("sign_mode") in {"auto", "instant"}
                and int(record.get("auto_sign_at", 0) or 0) <= now
                and int(record.get("auto_attempted_at", 0) or 0) <= 0
            ]
            if not due:
                continue

            lock = self._get_manual_sign_lock(qq)
            if lock.locked():
                continue
            async with lock:
                now = int(time.time())
                due = [
                    record
                    for record in self._load_web_pending(qq)
                    if record.get("sign_mode") in {"auto", "instant"}
                    and int(record.get("auto_sign_at", 0) or 0) <= now
                    and int(record.get("auto_attempted_at", 0) or 0) <= 0
                ]
                if not due:
                    continue
                due_keys = {str(record.get("role_key", "")) for record in due}
                outcomes: dict[str, dict[str, str]] = {}
                try:
                    (
                        users,
                        _imported_users,
                        errors,
                        outcomes,
                    ) = await self._import_staged_bindings_detailed(qq, qq, due)
                except Exception as exc:
                    self._mark_auto_attempted(qq, due_keys)
                    logger.exception(f"用户 {qq} 网页自动绑定导入失败: {exc}")
                    request_groups: dict[str, list[dict[str, Any]]] = {}
                    for record in due:
                        request_groups.setdefault(
                            str(record.get("request_id", "")), []
                        ).append(record)
                    for request_id, records in request_groups.items():
                        if not request_id:
                            continue
                        status_value, result = self._build_web_request_result(
                            records,
                            {},
                            [],
                            fallback_error="绑定任务执行异常，请稍后重试",
                        )
                        await self._report_web_result(
                            request_id,
                            status_value,
                            result,
                            int(records[0].get("created_at", 0) or 0),
                        )
                    continue

                identities = {
                    identity
                    for record in due
                    if (identity := self._staged_identity(record)) is not None
                }
                target_users: list[dict[str, Any]] = []
                seen_targets: set[int] = set()
                for user in users:
                    identity = self._role_identity_from_user(user)
                    if identity in identities and id(user) not in seen_targets:
                        seen_targets.add(id(user))
                        target_users.append(user)

                success = 0
                already_claimed = 0
                failed = 0
                sign_error = ""
                if target_users:
                    try:
                        (
                            success,
                            already_claimed,
                            failed,
                            _details,
                        ) = await self._sign_current_user_records(
                            qq, users, target_users=target_users
                        )
                    except Exception as exc:
                        logger.exception(f"用户 {qq} 网页自动任务失败: {exc}")
                        sign_error = "签到任务执行异常，请稍后重试"
                request_groups = {}
                for record in due:
                    request_groups.setdefault(
                        str(record.get("request_id", "")), []
                    ).append(record)
                for request_id, records in request_groups.items():
                    if not request_id:
                        continue
                    status_value, result = self._build_web_request_result(
                        records,
                        outcomes,
                        users,
                        fallback_error=sign_error,
                    )
                    await self._report_web_result(
                        request_id,
                        status_value,
                        result,
                        int(records[0].get("created_at", 0) or 0),
                    )
                processed += len(target_users)
                logger.info(
                    f"用户 {qq} 网页自动任务完成：处理 {len(target_users)} 个角色，"
                    f"签到成功 {success}，已领取 {already_claimed}，失败 {failed}"
                )
                remaining_keys = {
                    str(record.get("role_key", ""))
                    for record in self._load_web_pending(qq)
                    if str(record.get("role_key", "")) in due_keys
                }
                self._mark_auto_attempted(qq, remaining_keys)
                if errors:
                    logger.warning(
                        f"用户 {qq} 网页自动签到存在未导入角色: "
                        + "；".join(errors[:3])
                    )
        return processed

    def _bound_role_keys(
        self, users: list[dict[str, Any]]
    ) -> set[tuple[str, str, str]]:
        keys: set[tuple[str, str, str]] = set()
        for user in users:
            try:
                if self._is_channel_record(user):
                    platform = self._get_channel_platform(user)
                    role_id = self._decrypt_data(user["role_id"])
                    if platform:
                        keys.add((f"channel:{platform}", "", str(role_id)))
                    continue
                account = self._decrypt_data(user["account"])
                role_id = self._decrypt_data(user["role_id"])
                keys.add((str(account), str(user.get("game_id", "39")), str(role_id)))
            except Exception:
                continue
        return keys

    @staticmethod
    def _match_server_role(
        roles: list[dict[str, Any]], game_id: str, role_id: str
    ) -> dict[str, Any] | None:
        for role in roles:
            if not isinstance(role, dict):
                continue
            current_game_id = str(role.get("game_id", "39"))
            if current_game_id == str(game_id) and str(role.get("role_id", "")) == str(
                role_id
            ):
                return role
        return None

    async def _import_staged_bindings(
        self,
        qq: str,
        sender_key: str,
        staged: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
        (
            users,
            imported_users,
            errors,
            _outcomes,
        ) = await self._import_staged_bindings_detailed(qq, sender_key, staged)
        return users, imported_users, errors

    async def _import_staged_bindings_detailed(
        self,
        qq: str,
        sender_key: str,
        staged: list[dict[str, Any]],
    ) -> tuple[
        list[dict[str, Any]],
        list[dict[str, Any]],
        list[str],
        dict[str, dict[str, Any]],
    ]:
        user_data = self._load_user_data(sender_key) or {"num": 0, "users": []}
        users = user_data.get("users", []) if isinstance(user_data, dict) else []
        if not isinstance(users, list):
            users = []
        bound_keys = self._bound_role_keys(users)
        bound_info_by_key: dict[tuple[str, str, str], str] = {}
        for user in users:
            identity = self._role_identity_from_user(user)
            if identity is None:
                continue
            info = str(user.get("info", "")).strip()
            if info and identity not in bound_info_by_key:
                bound_info_by_key[identity] = info
        consumed: set[str] = set()
        imported_users: list[dict[str, Any]] = []
        errors: list[str] = []
        outcomes: dict[str, dict[str, Any]] = {}
        role_cache: dict[str, list[dict[str, Any]]] = {}

        async def roles_for(account: str) -> list[dict[str, Any]]:
            if account not in role_cache:
                result = await get_server(account)
                role_cache[account] = result or []
            return role_cache[account]

        for record in staged:
            role_key = str(record.get("role_key", ""))
            if self._is_channel_record(record):
                try:
                    platform = str(record.get("platform", "")).strip().lower()
                    role_id = self._decrypt_data(str(record["role_id"]))
                    role_name = self._decrypt_data(str(record["role_name"]))
                except Exception as exc:
                    message = f"渠道服暂存数据损坏：{exc}"
                    errors.append(message)
                    outcomes[role_key] = {"state": "failed", "message": message}
                    continue
                if (
                    platform not in CHANNEL_PLATFORM_NAMES
                    or not role_id
                    or not role_name
                ):
                    message = "渠道服暂存数据无效"
                    errors.append(message)
                    outcomes[role_key] = {"state": "failed", "message": message}
                    continue
                key = (f"channel:{platform}", "", role_id)
                info = self._format_channel_role_info(platform, role_name)
                if key in bound_keys:
                    consumed.add(role_key)
                    label = bound_info_by_key.get(key, info)
                    message = f"重复绑定：{label} 已在当前 QQ 绑定"
                    outcomes[role_key] = {"state": "duplicate", "message": message}
                    continue
                owner_qq = self._find_role_owner(*key, sender_key)
                if owner_qq is not None:
                    if owner_qq == sender_key:
                        consumed.add(role_key)
                        message = f"重复绑定：{info} 已在当前 QQ 绑定"
                        outcomes[role_key] = {"state": "duplicate", "message": message}
                    else:
                        message = f"重复绑定：{info} 已被 QQ {owner_qq} 绑定"
                        errors.append(message)
                        outcomes[role_key] = {"state": "duplicate", "message": message}
                    continue
                try:
                    result = await binds_channel_account(
                        self.headers, role_id, role_name, platform
                    )
                except Exception as exc:
                    logger.warning(f"网页渠道服角色绑定异常: {exc}")
                    message = "渠道服绑定请求异常"
                    errors.append(message)
                    outcomes[role_key] = {"state": "failed", "message": message}
                    continue
                if result.get("code") != 200:
                    message = str(result.get("message", "渠道服绑定失败"))
                    errors.append(message)
                    outcomes[role_key] = {"state": "failed", "message": message}
                    continue
                user_record = {
                    "binding_type": "channel",
                    "platform": platform,
                    "role_id": self._encrypt_data(role_id),
                    "role_name": self._encrypt_data(role_name),
                    "info": info,
                    "sign_status": self._build_sign_status(
                        "pending", CHANNEL_SIGN_PENDING_MESSAGE
                    ),
                }
                users.append(user_record)
                imported_users.append(user_record)
                outcomes[role_key] = {"state": "bound", "message": "渠道绑定成功"}
                bound_keys.add(key)
                consumed.add(role_key)
                continue
            try:
                encrypted_account = record.get("account") or record["phone"]
                account = self._decrypt_data(str(encrypted_account))
                role_id = self._decrypt_data(str(record["role_id"]))
                game_id = str(record.get("game_id", "39"))
            except Exception as exc:
                message = f"暂存数据损坏：{exc}"
                errors.append(message)
                outcomes[role_key] = {"state": "failed", "message": message}
                continue
            key = (account, game_id, role_id)
            if key in bound_keys:
                label = bound_info_by_key.get(key, "").strip()
                if not label:
                    roles = await roles_for(account)
                    matched = self._match_server_role(roles, game_id, role_id)
                    if matched is not None:
                        label = self._format_role_info(matched)
                consumed.add(role_key)
                message = f"重复绑定：{label or '该账号'} 已在当前 QQ 绑定"
                outcomes[role_key] = {"state": "duplicate", "message": message}
                continue
            roles = await roles_for(account)
            matched = self._match_server_role(roles, game_id, role_id)
            if matched is None:
                message = "获取角色信息失败"
                errors.append(message)
                outcomes[role_key] = {"state": "failed", "message": message}
                continue
            info = self._format_role_info(matched)
            owner_qq = self._find_role_owner(account, game_id, role_id, sender_key)
            if owner_qq is not None:
                if owner_qq == sender_key:
                    consumed.add(role_key)
                    message = f"重复绑定：{info} 已在当前 QQ 绑定"
                    outcomes[role_key] = {"state": "duplicate", "message": message}
                else:
                    message = f"重复绑定：{info} 已被 QQ {owner_qq} 绑定"
                    errors.append(message)
                    outcomes[role_key] = {"state": "duplicate", "message": message}
                continue
            try:
                payload = convert_to_query_bytes(matched, account)
                result = await binds_account(self.headers, payload)
            except Exception as exc:
                logger.warning(f"网页角色绑定异常: {exc}")
                message = "绑定请求异常"
                errors.append(message)
                outcomes[role_key] = {"state": "failed", "message": message}
                continue
            if result.get("code") != 200:
                message = str(result.get("message", "绑定失败"))
                errors.append(message)
                outcomes[role_key] = {"state": "failed", "message": message}
                continue
            user_record = {
                "account": self._encrypt_data(account),
                "role_id": self._encrypt_data(role_id),
                "info": info,
                "sign_status": self._build_sign_status("pending", "等待首次签到"),
            }
            self._set_bound_game_id(user_record, game_id)
            users.append(user_record)
            imported_users.append(user_record)
            outcomes[role_key] = {"state": "bound", "message": "绑定成功"}
            bound_keys.add(key)
            consumed.add(role_key)

        if imported_users and not self._save_user_data(
            sender_key, {"num": len(users), "users": users}
        ):
            raise RuntimeError("写入本地绑定数据失败")
        if consumed:
            self._remove_web_pending(qq, consumed)
        return users, imported_users, errors, outcomes

    async def _sign_current_user_records(
        self,
        sender_key: str,
        users: list[dict[str, Any]],
        target_users: list[dict[str, Any]] | None = None,
    ) -> tuple[int, int, int, list[str]]:
        success_count = 0
        already_claimed_count = 0
        failed_count = 0
        details: list[str] = []
        role_cache: dict[str, list[dict[str, Any]]] = {}

        async def roles_for(phone: str) -> list[dict[str, Any]]:
            if phone not in role_cache:
                result = await get_server(phone)
                role_cache[phone] = result or []
            return role_cache[phone]

        signing_users = users if target_users is None else target_users
        for user in signing_users:
            info = str(user.get("info", "未知角色"))
            if self._is_channel_record(user):
                result = await self._sign_channel_record(user)
                state = str(result.get("state", "failed"))
                if state == "success":
                    success_count += 1
                    details.append(f"{info}：{result.get('message', '签到成功')}")
                elif state == "already_claimed":
                    already_claimed_count += 1
                    details.append(f"{info}：{result.get('message', '已领取')}")
                else:
                    failed_count += 1
                    details.append(f"{info}：{result.get('message', '签到失败')}")
                continue
            try:
                phone = self._decrypt_data(user["account"])
                role_id = self._decrypt_data(user["role_id"])
                game_id = str(user.get("game_id", "39"))
            except Exception:
                self._set_user_sign_status(user, "invalid", "账号数据解密失败")
                failed_count += 1
                details.append(f"{info}：账号数据损坏")
                continue

            roles = await roles_for(phone)
            matched = self._match_server_role(roles, game_id, role_id)
            if matched is None:
                self._set_user_sign_status(user, "failed", "获取角色信息失败")
                failed_count += 1
                details.append(f"{info}：获取角色信息失败")
                continue

            current_game_id = str(matched.get("game_id", game_id))
            self._set_bound_game_id(user, current_game_id)
            user["info"] = self._format_role_info(matched)
            try:
                payload = convert_to_query_bytes(matched, phone)
                bind_result = await binds_account(self.headers, payload)
            except Exception as exc:
                logger.warning(f"用户签到绑定异常: {exc}")
                bind_result = {"code": -1, "message": "绑定请求异常"}

            if bind_result.get("code") != 200:
                message = str(bind_result.get("message", "绑定失败"))
                self._set_user_sign_status(user, "failed", message)
                failed_count += 1
                details.append(f"{user['info']}：{message}")
                continue

            sign_result = await sign_request(self.headers, current_game_id)
            sign_state, sign_message = self._format_sign_result_message(sign_result)
            if sign_state == "success":
                self._set_user_sign_status(user, "success", sign_message or "签到成功")
                success_count += 1
                details.append(f"{user['info']}：{sign_message or '签到成功'}")
            elif sign_state == "already_claimed":
                self._set_user_sign_status(
                    user, "already_claimed", sign_message or "今日奖励已领取"
                )
                already_claimed_count += 1
                details.append(f"{user['info']}：{sign_message or '今日奖励已领取'}")
            else:
                self._set_user_sign_status(user, "failed", sign_message or "签到失败")
                failed_count += 1
                details.append(f"{user['info']}：{sign_message or '签到失败'}")

            try:
                gift_summary = await self._claim_activity_gifts_for_role(
                    current_game_id, role_id
                )
                if gift_summary.get("success_count", 0):
                    details.append(f"{user['info']}：领取活动礼包成功")
            except Exception as exc:
                logger.warning(f"领取活动礼包失败: {exc}")

        if not self._save_user_data(sender_key, {"num": len(users), "users": users}):
            raise RuntimeError("写入签到结果失败")
        return success_count, already_claimed_count, failed_count, details

    async def sign_current_user_impl(self, event: AstrMessageEvent) -> None:
        if not self.headers:
            await event.send(event.plain_result("❌ 未配置签到请求头，暂时无法签到"))
            event.stop_event()
            return

        if getattr(self, "_keep_sign_running", False):
            await event.send(event.plain_result("⏳ 签到保活任务正在执行，请稍后再试"))
            event.stop_event()
            return
        if getattr(self, "_auto_sign_progress", {}).get("running"):
            await event.send(event.plain_result("⏳ 全量签到任务正在执行，请稍后再试"))
            event.stop_event()
            return

        sender_raw = str(event.get_sender_id())
        sender_key = sender_raw.replace("/", "_")
        qq = re.sub(r"\D", "", sender_raw)
        if not QQ_RE.fullmatch(qq):
            await event.send(event.plain_result("❌ 无法识别当前 QQ，请稍后重试"))
            event.stop_event()
            return

        cooldowns = getattr(self, "_manual_sign_last_at", None)
        if cooldowns is None:
            cooldowns = {}
            self._manual_sign_last_at = cooldowns
        now = time.time()
        last_at = float(cooldowns.get(sender_key, 0))
        if now - last_at < 60:
            wait = max(1, int(60 - (now - last_at)))
            await event.send(
                event.plain_result(f"⏳ 操作过快，请 {wait} 秒后再发送“签到”")
            )
            event.stop_event()
            return

        lock = self._get_manual_sign_lock(sender_key)
        if lock.locked():
            await event.send(event.plain_result("⏳ 当前 QQ 的签到正在执行，请稍候"))
            event.stop_event()
            return

        async with lock:
            cooldowns[sender_key] = now
            await self.sync_web_bindings()
            staged = self._load_web_pending(qq)
            try:
                (
                    users,
                    imported_users,
                    import_errors,
                ) = await self._import_staged_bindings(qq, sender_key, staged)
                imported = len(imported_users)
                if not users:
                    lines = [
                        "❌ 当前 QQ 暂无可签到角色。",
                        "请先在网页提交绑定，再发送“签到”。",
                    ]
                    if import_errors:
                        lines.append("原因：" + "；".join(import_errors[:3]))
                    await event.send(event.plain_result("\n".join(lines)))
                    event.stop_event()
                    return
                (
                    success,
                    already_claimed,
                    failed,
                    details,
                ) = await self._sign_current_user_records(sender_key, users)
                lines = [
                    "【签到结果】",
                    f"网页新增：{imported} 个角色",
                    (
                        f"处理角色：{len(users)} 个，签到成功 {success}，"
                        f"已领取 {already_claimed}，失败 {failed}"
                    ),
                ]
                if details:
                    lines.append("")
                    lines.extend(details[:8])
                    if len(details) > 8:
                        lines.append(
                            f"其余 {len(details) - 8} 个角色请在“查询绑定”中查看"
                        )
                if import_errors:
                    lines.append("")
                    lines.append("未导入：" + "；".join(import_errors[:3]))
                await event.send(event.plain_result("\n".join(lines)))
            except Exception as exc:
                logger.exception(f"用户 {qq} 执行网页签到失败: {exc}")
                await event.send(event.plain_result(f"❌ 签到失败：{exc}"))
            finally:
                event.stop_event()
