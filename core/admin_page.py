from __future__ import annotations

import asyncio
import json
import re
import threading
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, cast

from astrbot.api import logger

from .sign_in import CHANNEL_PLATFORM_NAMES
from .signin_preferences import (
    GIFT_CLAIM_MODE_LABELS,
    GIFT_CLAIM_MODES,
    load_sign_push_payload,
    load_signin_settings,
    normalize_bool,
    normalize_gift_claim_mode,
    normalize_summary_detail_mode,
    write_sign_push_payload,
    write_signin_settings,
)
from .signin_summary import SUMMARY_DETAIL_MODE_LABELS, SUMMARY_DETAIL_MODES
from .strategy_settings import set_strategy_service_enabled
from .utils import atomic_write_json

try:
    from quart import jsonify as quart_jsonify
    from quart import request as quart_request
except ImportError:
    quart_jsonify = None
    quart_request = None


PLUGIN_NAME = "astrbot_plugin_marvelous_snail"
QQ_RE = re.compile(r"^\d{5,12}$")
ACCOUNT_RE = re.compile(r"^\d{6,20}$")
ROLE_ID_RE = re.compile(r"^\S{1,128}$")
GAME_IDS = {"39": "官服", "26": "光子服"}
MAX_ROLE_INFO_LENGTH = 200
MAX_AUTHOR_NAME_LENGTH = 40
MAX_FAKEID_LENGTH = 128
MAX_PUSH_PLATFORM_LENGTH = 64
MAX_PUSH_TARGET_LENGTH = 128
MAX_ARTICLE_TITLE_LENGTH = 200
MAX_ARTICLE_DIGEST_LENGTH = 400
MAX_ARTICLE_LINK_LENGTH = 1000
MAX_ARTICLE_AID_LENGTH = 128
MAX_ARTICLE_PAGE_SIZE = 200
SIGN_STATES = {
    "success",
    "already_claimed",
    "failed",
    "pending",
    "invalid",
    "unknown",
}
STRATEGY_AFFECTED_COMMANDS = [
    "最强蜗牛 作者搜索",
    "最强蜗牛 作者添加",
    "最强蜗牛 作者删除",
    "最强蜗牛 作者列表",
    "最强蜗牛 攻略推送",
    "最强蜗牛 攻略推送列表",
    "最强蜗牛 搜索攻略",
]
AUTHOR_NAME_FORBIDDEN_RE = re.compile(r'[\x00-\x1f\x7f/\\:*?"<>|]')
PUSH_PLATFORM_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
PUSH_TARGET_RE = re.compile(r"^[^\s:]{1,128}$")
PUSH_MESSAGE_TYPES = {
    "group": "GroupMessage",
    "private": "FriendMessage",
}
JOB_LABELS = {
    "get_updata_job": "攻略更新监控",
    "auto_sign_in_job": "每日全量签到",
    "keep_sign_in_job": "签到会话保活",
    "web_binding_sync_job": "网页绑定同步",
    "web_auto_sign_job": "网页自动签到",
}
JOB_SERVICES = {
    "get_updata_job": "strategy",
    "auto_sign_in_job": "signin",
    "keep_sign_in_job": "signin",
    "web_binding_sync_job": "signin",
    "web_auto_sign_job": "signin",
}


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    if isinstance(value, int | float):
        return bool(value)
    return default


def _mask_account(value: str) -> str:
    value = str(value or "")
    if len(value) >= 7:
        return f"{value[:3]}****{value[-4:]}"
    return "••••"


def _mask_role_id(value: str) -> str:
    value = str(value or "")
    if len(value) >= 10:
        return f"{value[:2]}••••{value[-2:]}"
    return "••••"


def _redact_sensitive_text(value: Any, secrets: tuple[str, ...] = ()) -> str:
    text = str(value or "")
    for secret in secrets:
        if secret and len(secret) >= 4:
            text = text.replace(secret, "••••")
    return text


def _normalize_text(
    value: Any,
    field: str,
    *,
    required: bool = False,
    fallback: str = "",
    max_length: int = MAX_ROLE_INFO_LENGTH,
) -> str:
    text = re.sub(r"[\r\n\t]+", " ", str(value or "")).strip()
    if not text:
        if required:
            raise ValueError(f"{field}不能为空")
        return fallback
    if len(text) > max_length:
        raise ValueError(f"{field}不能超过 {max_length} 个字符")
    return text


def _normalize_qq(value: Any) -> str:
    qq = str(value or "").strip()
    if not QQ_RE.fullmatch(qq):
        raise ValueError("QQ 格式无效")
    return qq


def _normalize_account(value: Any) -> str:
    account = str(value or "").strip()
    if not ACCOUNT_RE.fullmatch(account):
        raise ValueError("手机号应为 6-20 位数字")
    return account


def _normalize_role_id(value: Any) -> str:
    role_id = str(value or "").strip()
    if not ROLE_ID_RE.fullmatch(role_id):
        raise ValueError("角色 ID 不能为空且不能包含空白字符")
    return role_id


def _normalize_game_id(value: Any) -> str:
    game_id = str(value or "").strip()
    if game_id not in GAME_IDS:
        raise ValueError("游戏服无效")
    return game_id


def _normalize_author_name(value: Any) -> str:
    name = _normalize_text(
        value,
        "作者名称",
        required=True,
        max_length=MAX_AUTHOR_NAME_LENGTH,
    )
    if name in {".", ".."} or AUTHOR_NAME_FORBIDDEN_RE.search(name):
        raise ValueError('作者名称不能包含 / \\ : * ? " < > | 等字符')
    return name


def _normalize_fakeid(value: Any, *, required: bool) -> str:
    fakeid = str(value or "").strip()
    if not fakeid:
        if required:
            raise ValueError("作者 fakeid 不能为空")
        return ""
    if len(fakeid) > MAX_FAKEID_LENGTH:
        raise ValueError(f"作者 fakeid 不能超过 {MAX_FAKEID_LENGTH} 个字符")
    if re.search(r"\s", fakeid):
        raise ValueError("作者 fakeid 不能包含空白字符")
    return fakeid


def _normalize_push_definition(payload: dict[str, Any]) -> dict[str, str]:
    platform = str(payload.get("platform", "") or "").strip()
    if len(platform) > MAX_PUSH_PLATFORM_LENGTH or not PUSH_PLATFORM_RE.fullmatch(
        platform
    ):
        raise ValueError("推送平台格式无效")
    kind = str(payload.get("kind", "") or "").strip().lower()
    if kind not in PUSH_MESSAGE_TYPES:
        raise ValueError("推送类型必须为群聊或私聊")
    identifier = str(payload.get("target", "") or "").strip()
    if len(identifier) > MAX_PUSH_TARGET_LENGTH or not PUSH_TARGET_RE.fullmatch(
        identifier
    ):
        raise ValueError("推送目标不能为空、不能包含空白或冒号，且不能超过 128 个字符")
    return {
        "platform": platform,
        "kind": kind,
        "identifier": identifier,
        "target": f"{platform}:{PUSH_MESSAGE_TYPES[kind]}:{identifier}",
    }


def _article_timestamp(article: dict[str, Any]) -> int:
    value = article.get("update_time") or article.get("create_time")
    try:
        timestamp = int(value)
    except (TypeError, ValueError):
        return 0
    if timestamp > 10_000_000_000:
        timestamp //= 1000
    return max(0, timestamp)


def _article_text(value: Any, max_length: int) -> str:
    text = re.sub(r"[\r\n\t]+", " ", str(value or "")).strip()
    return text[:max_length]


def _describe_push_target(value: Any) -> dict[str, str]:
    target = str(value or "").strip()
    parts = target.split(":")
    if len(parts) >= 3:
        platform = parts[0].strip() or "未知平台"
        message_type = parts[1].strip()
        identifier = parts[2].strip()
        kind = {
            "GroupMessage": "group",
            "FriendMessage": "private",
        }.get(message_type, "unknown")
        label = {
            "GroupMessage": "群聊",
            "FriendMessage": "私聊",
        }.get(message_type, message_type or "消息目标")
        return {
            "target": target,
            "platform": platform,
            "kind": kind,
            "label": label,
            "identifier": identifier,
        }
    return {
        "target": target,
        "platform": "",
        "kind": "unknown",
        "label": "自定义目标",
        "identifier": target,
    }


class SnailAdminPageService:
    """Build privacy-preserving snapshots and manage plugin data."""

    def __init__(self, plugin: Any):
        self.plugin = plugin
        self.version = self._read_version()
        self._strategy_lock = asyncio.Lock()
        self._push_lock = threading.Lock()
        self._signin_lock = threading.Lock()

    def _read_version(self) -> str:
        metadata_path = Path(getattr(self.plugin, "plugin_dir", "")) / "metadata.yaml"
        try:
            for line in metadata_path.read_text(encoding="utf-8").splitlines():
                if line.startswith("version:"):
                    return line.split(":", 1)[1].strip() or "unknown"
        except OSError:
            pass
        return "unknown"

    async def get_bootstrap(self) -> dict[str, Any]:
        snapshot = await asyncio.to_thread(self._build_data_snapshot)
        runtime = self._build_runtime_snapshot()
        snapshot["runtime"] = runtime
        snapshot["strategy"] = await self.get_strategy_snapshot(runtime=runtime)
        snapshot["version"] = self.version
        return snapshot

    async def get_signin_bootstrap(self) -> dict[str, Any]:
        snapshot = await asyncio.to_thread(self._build_data_snapshot)
        runtime = self._build_runtime_snapshot()
        runtime["jobs"] = [
            job
            for job in runtime.get("jobs", [])
            if not isinstance(job, dict) or job.get("service") != "strategy"
        ]
        snapshot["runtime"] = runtime
        snapshot["version"] = self.version
        snapshot["service"] = "signin"
        snapshot["signin"] = await asyncio.to_thread(
            self._build_signin_preferences_snapshot
        )
        return snapshot

    async def get_strategy_bootstrap(self) -> dict[str, Any]:
        runtime = self._build_runtime_snapshot()
        strategy = await self.get_strategy_snapshot(runtime=runtime)
        strategy_jobs = [
            job
            for job in runtime.get("jobs", [])
            if isinstance(job, dict) and job.get("service") == "strategy"
        ]
        return {
            "generated_at": strategy.get("server_time", int(time.time())),
            "runtime": {
                "scheduler_running": bool(runtime.get("scheduler_running")),
                "jobs": strategy_jobs,
                "exporter_configured": bool(runtime.get("exporter_configured")),
                "server_time": runtime.get("server_time", int(time.time())),
            },
            "strategy": strategy,
            "version": self.version,
            "service": "strategy",
        }

    async def get_strategy_snapshot(
        self, runtime: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        saved_authors = await self._load_saved_authors()
        snapshot = await asyncio.to_thread(self._build_strategy_snapshot, saved_authors)
        runtime = runtime or self._build_runtime_snapshot()
        jobs = runtime.get("jobs", [])
        snapshot["job"] = next(
            (
                job
                for job in jobs
                if isinstance(job, dict) and job.get("id") == "get_updata_job"
            ),
            None,
        )
        snapshot["scheduler_running"] = bool(runtime.get("scheduler_running"))
        snapshot["service_enabled"] = self.plugin._is_strategy_service_enabled()
        return snapshot

    async def _load_saved_authors(self) -> dict[str, Any]:
        getter = getattr(self.plugin, "get_kv_data", None)
        if not callable(getter):
            return {}
        try:
            authors = await getter("authors", {})
        except Exception as exc:
            logger.warning(f"读取攻略作者列表失败: {exc}")
            return {}
        return authors if isinstance(authors, dict) else {}

    async def _load_saved_authors_for_update(self) -> dict[str, Any]:
        getter = getattr(self.plugin, "get_kv_data", None)
        if not callable(getter):
            raise RuntimeError("当前运行环境不支持KV数据，无法修改攻略作者")
        try:
            authors = await getter("authors", {})
        except Exception as exc:
            raise RuntimeError("读取攻略作者列表失败") from exc
        if authors is None:
            return {}
        if not isinstance(authors, dict):
            raise ValueError("攻略作者数据格式异常，请先检查插件KV数据")
        return dict(authors)

    async def _load_kv_dict_for_update(self, key: str, label: str) -> dict[str, Any]:
        getter = getattr(self.plugin, "get_kv_data", None)
        if not callable(getter):
            raise RuntimeError("当前运行环境不支持KV数据，无法修改攻略配置")
        try:
            payload = await getter(key, {})
        except Exception as exc:
            raise RuntimeError(f"读取{label}失败") from exc
        if payload is None:
            return {}
        if not isinstance(payload, dict):
            raise ValueError(f"{label}格式异常，请先检查插件KV数据")
        return dict(payload)

    async def _put_kv_data(self, key: str, payload: dict[str, Any]) -> None:
        putter = getattr(self.plugin, "put_kv_data", None)
        if not callable(putter):
            raise RuntimeError("当前运行环境不支持KV数据，无法保存攻略配置")
        try:
            result = await putter(key, payload)
        except Exception as exc:
            raise RuntimeError("写入插件KV数据失败") from exc
        if result is False:
            raise RuntimeError("写入插件KV数据失败")

    def _author_cache_path(self, name: str) -> Path:
        cache_root = Path(self.plugin._get_author_cache_dir()).resolve()
        cache_path = (cache_root / f"{name}.json").resolve()
        if cache_path.parent != cache_root:
            raise ValueError("作者名称不能指向缓存目录之外")
        return cache_path

    def _rename_author_cache(self, old_name: str, new_name: str) -> bool:
        old_path = self._author_cache_path(old_name)
        new_path = self._author_cache_path(new_name)
        if not old_path.exists():
            return False
        if new_path.exists():
            raise ValueError("目标名称已存在本地文章缓存，请换一个名称")
        old_path.replace(new_path)
        return True

    def _push_file_path(self, *, create_parent: bool = False) -> Path:
        data_dir = getattr(self.plugin, "data_dir", None)
        if not isinstance(data_dir, str | Path):
            raise RuntimeError("插件数据目录不可用，无法修改推送目标")
        push_root = (Path(data_dir) / "push_datas").resolve()
        push_file = (push_root / "strategy.json").resolve()
        if push_file.parent != push_root:
            raise RuntimeError("推送目标文件路径异常")
        if create_parent:
            push_root.mkdir(parents=True, exist_ok=True)
        return push_file

    def _load_push_payload_for_update(self) -> dict[str, Any]:
        push_file = self._push_file_path()
        if not push_file.is_file():
            return {"datas": []}
        try:
            payload = json.loads(push_file.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ValueError("攻略推送目标文件格式异常，请先修复文件") from exc
        if not isinstance(payload, dict):
            raise ValueError("攻略推送目标文件格式异常，请先修复文件")
        targets = payload.get("datas", [])
        if not isinstance(targets, list) or any(
            not isinstance(target, str) for target in targets
        ):
            raise ValueError("攻略推送目标 datas 字段格式异常，请先修复文件")
        return payload

    @staticmethod
    def _write_push_payload(push_file: Path, payload: dict[str, Any]) -> None:
        atomic_write_json(push_file, payload)

    def _plugin_data_dir(self) -> Path:
        data_dir = getattr(self.plugin, "data_dir", None)
        if not isinstance(data_dir, str | Path):
            raise RuntimeError("插件数据目录不可用")
        return Path(data_dir).resolve()

    def _build_signin_preferences_snapshot(self) -> dict[str, Any]:
        data_dir = self._plugin_data_dir()
        settings = load_signin_settings(data_dir)
        gift = settings.get("gift", {})
        notification = settings.get("notification", {})
        payload = load_sign_push_payload(data_dir)
        targets = [
            _describe_push_target(target)
            for target in payload.get("datas", [])
            if str(target or "").strip()
        ]
        push_file_present = (data_dir / "push_datas" / "sign.json").is_file()
        return {
            "gift": {
                "claim_mode": str(gift.get("claim_mode", "all")),
                "options": [
                    {"value": mode, "label": GIFT_CLAIM_MODE_LABELS[mode]}
                    for mode in GIFT_CLAIM_MODES
                ],
            },
            "notification": {
                "enabled": bool(notification.get("enabled", True)),
                "include_reward_image": bool(
                    notification.get("include_reward_image", True)
                ),
                "detail_mode": str(notification.get("detail_mode", "issues_overview")),
                "detail_mode_options": [
                    {"value": mode, "label": SUMMARY_DETAIL_MODE_LABELS[mode]}
                    for mode in SUMMARY_DETAIL_MODES
                ],
                "targets": targets,
                "target_count": len(targets),
                "push_file_present": push_file_present,
            },
        }

    def update_signin_gift_settings(self, payload: dict[str, Any]) -> dict[str, Any]:
        claim_mode = normalize_gift_claim_mode(payload.get("claim_mode"))
        data_dir = self._plugin_data_dir()
        with self._signin_lock:
            settings = load_signin_settings(data_dir)
            gift = settings.get("gift")
            gift = dict(gift) if isinstance(gift, dict) else {}
            gift["claim_mode"] = claim_mode
            settings["gift"] = gift
            write_signin_settings(data_dir, settings)
        return {"action": "update-gift", "claim_mode": claim_mode}

    def update_signin_notification_settings(
        self, payload: dict[str, Any]
    ) -> dict[str, Any]:
        data_dir = self._plugin_data_dir()
        with self._signin_lock:
            settings = load_signin_settings(data_dir)
            notification = settings.get("notification")
            notification = dict(notification) if isinstance(notification, dict) else {}
            if "enabled" in payload:
                notification["enabled"] = normalize_bool(
                    payload.get("enabled"), "通知开关"
                )
            if "include_reward_image" in payload:
                notification["include_reward_image"] = normalize_bool(
                    payload.get("include_reward_image"), "奖励图片开关"
                )
            if "detail_mode" in payload:
                notification["detail_mode"] = normalize_summary_detail_mode(
                    payload.get("detail_mode")
                )
            notification.setdefault("enabled", True)
            notification.setdefault("include_reward_image", True)
            notification.setdefault("detail_mode", "issues_overview")
            settings["notification"] = notification
            write_signin_settings(data_dir, settings)
        return {
            "action": "update-notification",
            "enabled": bool(notification.get("enabled", True)),
            "include_reward_image": bool(
                notification.get("include_reward_image", True)
            ),
            "detail_mode": str(notification.get("detail_mode", "issues_overview")),
        }

    def create_signin_push_target(self, payload: dict[str, Any]) -> dict[str, Any]:
        definition = _normalize_push_definition(payload)
        data_dir = self._plugin_data_dir()
        with self._push_lock:
            raw = load_sign_push_payload(data_dir, strict=True)
            targets = list(raw.get("datas", []))
            if definition["target"] in targets:
                raise ValueError("该签到通知目标已存在")
            targets.append(definition["target"])
            raw["datas"] = targets
            write_sign_push_payload(data_dir, raw)
        return {**definition, "action": "create-notification"}

    def update_signin_push_target(self, payload: dict[str, Any]) -> dict[str, Any]:
        original = str(payload.get("original", "") or "").strip()
        if not original:
            raise ValueError("原签到通知目标不能为空")
        definition = _normalize_push_definition(payload)
        data_dir = self._plugin_data_dir()
        with self._push_lock:
            raw = load_sign_push_payload(data_dir, strict=True)
            targets = list(raw.get("datas", []))
            if original not in targets:
                raise ValueError("未找到该签到通知目标，请刷新后重试")
            if definition["target"] != original and definition["target"] in targets:
                raise ValueError("该签到通知目标已存在")
            raw["datas"] = [
                definition["target"] if target == original else target
                for target in targets
            ]
            write_sign_push_payload(data_dir, raw)
        return {**definition, "action": "update-notification", "original": original}

    def delete_signin_push_target(self, payload: dict[str, Any]) -> dict[str, Any]:
        target = str(payload.get("target", "") or "").strip()
        if not target:
            raise ValueError("签到通知目标不能为空")
        data_dir = self._plugin_data_dir()
        with self._push_lock:
            raw = load_sign_push_payload(data_dir, strict=True)
            targets = list(raw.get("datas", []))
            if target not in targets:
                raise ValueError("未找到该签到通知目标，请刷新后重试")
            targets.remove(target)
            raw["datas"] = targets
            write_sign_push_payload(data_dir, raw)
        return {
            "action": "delete-notification",
            "target": target,
            "remaining": len(targets),
        }

    def set_strategy_service_enabled(self, payload: dict[str, Any]) -> dict[str, Any]:
        """开启或关闭攻略服务。

        Args:
            payload: 请求体，`enabled` 为目标开关状态。
        Returns:
            操作结果，包含保存后的开关状态与受影响的指令数量。
        Raises:
            ValueError: `enabled` 不是布尔值时抛出。
        """
        enabled = payload.get("enabled")
        if not isinstance(enabled, bool):
            raise ValueError("enabled 必须为布尔值")
        settings = set_strategy_service_enabled(self._plugin_data_dir(), enabled)
        enabled_now = bool(settings["service"]["enabled"])
        logger.info(
            "最强蜗牛攻略服务已%s：攻略作者、搜索攻略、攻略推送与更新任务同步生效",
            "开启" if enabled_now else "关闭",
        )
        return {
            "action": "set-strategy-service",
            "enabled": enabled_now,
            "affected_commands": STRATEGY_AFFECTED_COMMANDS,
        }

    async def create_strategy_author(self, payload: dict[str, Any]) -> dict[str, Any]:
        name = _normalize_author_name(payload.get("name"))
        fakeid = _normalize_fakeid(payload.get("fakeid"), required=True)
        async with self._strategy_lock:
            authors = await self._load_saved_authors_for_update()
            if name in authors:
                raise ValueError("该作者已在保存列表中，请直接编辑")
            authors[name] = fakeid
            await self._put_kv_data("authors", authors)
        logger.info("最强蜗牛管理页新增攻略作者：%s", name)
        return {"action": "create-author", "name": name}

    async def update_strategy_author(self, payload: dict[str, Any]) -> dict[str, Any]:
        name = _normalize_author_name(payload.get("name"))
        new_name = _normalize_author_name(payload.get("new_name", name))
        fakeid_input = _normalize_fakeid(payload.get("fakeid"), required=False)

        async with self._strategy_lock:
            authors = await self._load_saved_authors_for_update()
            if name not in authors:
                raise ValueError("未找到该已保存作者，请刷新后重试")
            current_fakeid = str(authors.get(name, "") or "")
            fakeid = fakeid_input or current_fakeid
            if new_name != name and new_name in authors:
                raise ValueError("该作者名称已存在")

            articles = await self._load_kv_dict_for_update("articles", "攻略文章状态")
            if new_name != name and new_name in articles:
                raise ValueError("目标名称已有文章状态，请换一个名称")

            fakeid_changed = fakeid != current_fakeid
            renamed = new_name != name
            if not renamed and not fakeid_changed:
                return {
                    "action": "update-author",
                    "name": name,
                    "renamed": False,
                    "fakeid_changed": False,
                    "changed": False,
                }

            new_articles = dict(articles)
            articles_changed = False
            if name in new_articles:
                article = new_articles.pop(name)
                if not fakeid_changed:
                    new_articles[new_name] = article
                articles_changed = True

            new_authors = dict(authors)
            if renamed:
                new_authors.pop(name, None)
            new_authors[new_name] = fakeid

            cache_renamed = False
            try:
                if renamed:
                    cache_renamed = await asyncio.to_thread(
                        self._rename_author_cache, name, new_name
                    )
                if articles_changed:
                    await self._put_kv_data("articles", new_articles)
                await self._put_kv_data("authors", new_authors)
            except Exception:
                if articles_changed:
                    try:
                        await self._put_kv_data("articles", articles)
                    except Exception as rollback_exc:
                        logger.warning("回滚攻略文章状态失败: %s", rollback_exc)
                if cache_renamed:
                    try:
                        await asyncio.to_thread(
                            self._rename_author_cache, new_name, name
                        )
                    except Exception as rollback_exc:
                        logger.warning("回滚作者缓存文件名失败: %s", rollback_exc)
                raise

        logger.info(
            "最强蜗牛管理页更新攻略作者：%s，重命名 %s，fakeid 变更 %s",
            name,
            renamed,
            fakeid_changed,
        )
        return {
            "action": "update-author",
            "name": new_name,
            "previous_name": name,
            "renamed": renamed,
            "fakeid_changed": fakeid_changed,
            "changed": True,
        }

    async def delete_strategy_author(self, payload: dict[str, Any]) -> dict[str, Any]:
        name = _normalize_author_name(payload.get("name"))
        remove_registration = _as_bool(payload.get("remove_registration"), default=True)
        delete_cache = _as_bool(payload.get("delete_cache"), default=False)
        if not remove_registration and not delete_cache:
            raise ValueError("请选择移除作者或清理缓存")

        async with self._strategy_lock:
            authors = await self._load_saved_authors_for_update()
            articles = await self._load_kv_dict_for_update("articles", "攻略文章状态")
            cache_path = self._author_cache_path(name)
            cache_exists = cache_path.is_file()
            registration_exists = name in authors
            if remove_registration and not registration_exists:
                raise ValueError("未找到该已保存作者，请刷新后重试")
            if not remove_registration and not cache_exists:
                raise ValueError("未找到该作者的本地文章缓存")

            new_authors = dict(authors)
            new_articles = dict(articles)
            if remove_registration:
                new_authors.pop(name, None)
                new_articles.pop(name, None)

            try:
                if remove_registration and new_articles != articles:
                    await self._put_kv_data("articles", new_articles)
                if remove_registration:
                    await self._put_kv_data("authors", new_authors)
            except Exception:
                if remove_registration and new_articles != articles:
                    try:
                        await self._put_kv_data("articles", articles)
                    except Exception as rollback_exc:
                        logger.warning("回滚攻略文章状态失败: %s", rollback_exc)
                raise

            cache_removed = False
            if delete_cache and cache_exists:
                try:
                    cache_path.unlink()
                    cache_removed = True
                except OSError as exc:
                    raise RuntimeError("作者记录已更新，但本地缓存删除失败") from exc

        logger.info(
            "最强蜗牛管理页删除攻略作者：%s，移除登记 %s，清理缓存 %s",
            name,
            remove_registration,
            cache_removed,
        )
        return {
            "action": "delete-author",
            "name": name,
            "registration_removed": remove_registration,
            "cache_removed": cache_removed,
        }

    def create_push_target(self, payload: dict[str, Any]) -> dict[str, Any]:
        definition = _normalize_push_definition(payload)
        with self._push_lock:
            push_payload = self._load_push_payload_for_update()
            targets = push_payload["datas"]
            if definition["target"] in targets:
                raise ValueError("该推送目标已存在")
            targets.append(definition["target"])
            self._write_push_payload(
                self._push_file_path(create_parent=True), push_payload
            )
        logger.info(
            "最强蜗牛管理页新增攻略推送目标：%s/%s",
            definition["platform"],
            definition["kind"],
        )
        return {
            "action": "create-push",
            "platform": definition["platform"],
            "kind": definition["kind"],
            "target": definition["target"],
        }

    def update_push_target(self, payload: dict[str, Any]) -> dict[str, Any]:
        original = str(payload.get("original", "") or "").strip()
        if not original:
            raise ValueError("原推送目标不能为空")
        definition = _normalize_push_definition(payload)
        with self._push_lock:
            push_payload = self._load_push_payload_for_update()
            targets = push_payload["datas"]
            if original not in targets:
                raise ValueError("未找到该推送目标，请刷新后重试")
            if definition["target"] != original and definition["target"] in targets:
                raise ValueError("该推送目标已存在")
            targets[targets.index(original)] = definition["target"]
            self._write_push_payload(
                self._push_file_path(create_parent=True), push_payload
            )
        logger.info(
            "最强蜗牛管理页更新攻略推送目标：%s/%s",
            definition["platform"],
            definition["kind"],
        )
        return {
            "action": "update-push",
            "platform": definition["platform"],
            "kind": definition["kind"],
            "target": definition["target"],
        }

    def delete_push_target(self, payload: dict[str, Any]) -> dict[str, Any]:
        target = str(payload.get("target", "") or "").strip()
        if not target:
            raise ValueError("推送目标不能为空")
        with self._push_lock:
            push_payload = self._load_push_payload_for_update()
            targets = push_payload["datas"]
            if target not in targets:
                raise ValueError("未找到该推送目标，请刷新后重试")
            targets.remove(target)
            self._write_push_payload(
                self._push_file_path(create_parent=True), push_payload
            )
        logger.info("最强蜗牛管理页删除攻略推送目标，剩余 %s 项", len(targets))
        return {"action": "delete-push", "deleted": True, "remaining": len(targets)}

    async def get_user_detail(self, qq: str) -> dict[str, Any]:
        normalized = str(qq or "").strip()
        if not QQ_RE.fullmatch(normalized):
            raise ValueError("QQ 格式无效")
        detail = await asyncio.to_thread(self._build_user_detail, normalized)
        if detail is None:
            raise ValueError("未找到该 QQ 的绑定数据")
        detail["version"] = self.version
        return detail

    async def get_strategy_author_articles(
        self, name: Any, limit: Any = 100
    ) -> dict[str, Any]:
        normalized_name = _normalize_author_name(name)
        try:
            page_size = int(limit)
        except (TypeError, ValueError):
            raise ValueError("文章数量参数无效") from None
        page_size = max(1, min(page_size, MAX_ARTICLE_PAGE_SIZE))
        return await asyncio.to_thread(
            self._build_author_articles, normalized_name, page_size
        )

    def _build_author_articles(self, name: str, limit: int) -> dict[str, Any]:
        cache_path = self._author_cache_path(name)
        if not cache_path.is_file():
            raise ValueError("未找到该作者的本地文章缓存")
        try:
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ValueError("作者文章缓存无法读取，请重新同步") from exc
        if not isinstance(payload, dict):
            raise ValueError("作者文章缓存格式异常，请重新同步")
        articles = payload.get("articles", [])
        if not isinstance(articles, list):
            raise ValueError("作者文章缓存格式异常，请重新同步")

        items: list[dict[str, Any]] = []
        for article in articles:
            if not isinstance(article, dict):
                continue
            items.append(
                {
                    "aid": _article_text(article.get("aid"), MAX_ARTICLE_AID_LENGTH),
                    "title": _article_text(
                        article.get("title"), MAX_ARTICLE_TITLE_LENGTH
                    ),
                    "digest": _article_text(
                        article.get("digest"), MAX_ARTICLE_DIGEST_LENGTH
                    ),
                    "link": _article_text(article.get("link"), MAX_ARTICLE_LINK_LENGTH),
                    "published_at": _article_timestamp(article),
                }
            )
        items.sort(key=lambda item: (item["published_at"], item["title"]), reverse=True)
        total = len(items)
        synced_at = _as_int(payload.get("synced_at"))
        if synced_at <= 0:
            try:
                synced_at = int(cache_path.stat().st_mtime)
            except OSError:
                synced_at = 0
        return {
            "name": name,
            "synced_at": synced_at,
            "total": total,
            "returned": min(total, limit),
            "has_more": total > limit,
            "items": items[:limit],
        }

    async def sync_web_bindings(self) -> dict[str, Any]:
        if not getattr(self.plugin, "headers", None):
            raise ValueError("未配置签到请求头，无法同步网页申请")
        if self.plugin._get_portal_settings() is None:
            raise ValueError("未配置网页绑定服务，无法同步网页申请")
        imported = await self.plugin.sync_web_bindings()
        return {"imported": int(imported or 0)}

    def create_binding(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._ensure_mutation_allowed()
        qq = _normalize_qq(payload.get("qq"))
        account = _normalize_account(payload.get("account"))
        role_id = _normalize_role_id(payload.get("role_id"))
        game_id = _normalize_game_id(payload.get("game_id"))
        info = _normalize_text(
            payload.get("info"),
            "角色备注",
            fallback=self._default_role_info(game_id),
        )
        conflict = self._find_role_conflict(qq, account, game_id, role_id)
        if conflict is not None:
            self._raise_role_conflict(conflict, qq)

        data, users, revision = self._load_users_for_update(qq, allow_missing=True)
        record = {
            "account": self.plugin._encrypt_data(account),
            "role_id": self.plugin._encrypt_data(role_id),
            "game_id": game_id,
            "app_id": "39",
            "info": info,
            "sign_status": self.plugin._build_sign_status("pending", "等待首次签到"),
        }
        users.append(record)
        self._save_users(qq, data, users, revision)
        logger.info("最强蜗牛管理页新增绑定：QQ %s，角色序号 %s", qq, len(users))
        return {"action": "create", "qq": qq, "roles": len(users), "index": len(users)}

    def update_binding(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._ensure_mutation_allowed()
        qq = _normalize_qq(payload.get("qq"))
        index = _as_int(payload.get("index"), -1)
        data, users, revision = self._load_users_for_update(qq)
        if index < 1 or index > len(users):
            raise ValueError("角色记录不存在，请刷新后重试")
        record = users[index - 1]
        if not isinstance(record, dict):
            raise ValueError("该角色记录已损坏，无法编辑")
        if self.plugin._is_channel_record(record):
            raise ValueError("渠道服角色仅支持网页绑定，请删除后重新在网页提交")

        current_game_id = str(self.plugin._get_bound_game_id(record))
        try:
            current_account = str(self.plugin._decrypt_data(str(record["account"])))
            current_role_id = str(self.plugin._decrypt_data(str(record["role_id"])))
        except Exception as exc:
            raise ValueError("当前角色数据无法解密，请删除后重新添加") from exc

        account_input = str(payload.get("account", "") or "").strip()
        role_input = str(payload.get("role_id", "") or "").strip()
        if bool(account_input) != bool(role_input):
            raise ValueError("修改账号或角色 ID 时，请同时填写两项")
        if account_input:
            account = _normalize_account(account_input)
            role_id = _normalize_role_id(role_input)
        else:
            account = current_account
            role_id = current_role_id

        game_input = str(payload.get("game_id", current_game_id) or "").strip()
        game_id = _normalize_game_id(game_input or current_game_id)
        current_info = str(record.get("info", "") or "").strip()
        if "info" in payload:
            info = _normalize_text(
                payload.get("info"),
                "角色备注",
                fallback=current_info or self._default_role_info(game_id),
            )
        else:
            info = current_info or self._default_role_info(game_id)

        identity_changed = (account, game_id, role_id) != (
            current_account,
            current_game_id,
            current_role_id,
        )
        if identity_changed:
            conflict = self._find_role_conflict(
                qq, account, game_id, role_id, exclude_index=index
            )
            if conflict is not None:
                self._raise_role_conflict(conflict, qq)
            record["account"] = self.plugin._encrypt_data(account)
            record["role_id"] = self.plugin._encrypt_data(role_id)
            record["game_id"] = game_id
            record["sign_status"] = self.plugin._build_sign_status(
                "pending", "绑定信息已更新，等待重新签到"
            )

        record["info"] = info
        self._save_users(qq, data, users, revision)
        logger.info(
            "最强蜗牛管理页更新绑定：QQ %s，角色序号 %s，身份变更 %s",
            qq,
            index,
            identity_changed,
        )
        return {
            "action": "update",
            "qq": qq,
            "roles": len(users),
            "index": index,
            "identity_changed": identity_changed,
        }

    def delete_binding(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._ensure_mutation_allowed()
        qq = _normalize_qq(payload.get("qq"))
        index = _as_int(payload.get("index"), -1)
        data, users, revision = self._load_users_for_update(qq)
        if index < 1 or index > len(users):
            raise ValueError("角色记录不存在，请刷新后重试")
        users.pop(index - 1)
        if users:
            self._save_users(qq, data, users, revision)
        else:
            self._remove_user_file(qq)
        logger.info("最强蜗牛管理页删除绑定：QQ %s，角色序号 %s", qq, index)
        return {
            "action": "delete",
            "qq": qq,
            "roles": len(users),
            "deleted_index": index,
            "user_removed": not users,
        }

    def delete_user(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._ensure_mutation_allowed()
        qq = _normalize_qq(payload.get("qq"))
        data = self.plugin._load_user_data(qq)
        if not isinstance(data, dict):
            raise ValueError("未找到该 QQ 的绑定数据")
        users = data.get("users", [])
        deleted_roles = len(users) if isinstance(users, list) else 0
        self._remove_user_file(qq)
        logger.info("最强蜗牛管理页删除用户：QQ %s，角色数 %s", qq, deleted_roles)
        return {"action": "delete-user", "qq": qq, "deleted_roles": deleted_roles}

    def _ensure_mutation_allowed(self) -> None:
        reason = self._mutation_lock_reason()
        if reason:
            raise ValueError(f"{reason}，请稍后再修改绑定")

    def _mutation_lock_reason(self) -> str:
        progress = getattr(self.plugin, "_auto_sign_progress", {}) or {}
        if progress.get("running"):
            return "全量签到任务正在执行"
        if getattr(self.plugin, "_keep_sign_running", False):
            return "签到会话保活正在执行"
        locks = getattr(self.plugin, "_manual_sign_locks", {}) or {}
        if isinstance(locks, dict):
            for lock in locks.values():
                try:
                    if lock.locked():
                        return "用户签到任务正在执行"
                except Exception:
                    continue
        return ""

    def _load_users_for_update(
        self, qq: str, *, allow_missing: bool = False
    ) -> tuple[dict[str, Any], list[Any], tuple[int, int] | None]:
        revision = self.plugin._user_file_revision(qq)
        data = self.plugin._load_user_data(qq)
        if data is None:
            if not allow_missing:
                raise ValueError("未找到该 QQ 的绑定数据")
            return {"num": 0, "users": []}, [], revision
        if not isinstance(data, dict):
            raise ValueError("用户数据格式异常")
        users = data.get("users", [])
        if not isinstance(users, list):
            raise ValueError("用户角色列表格式异常")
        return data, list(users), revision

    def _save_users(
        self,
        qq: str,
        data: dict[str, Any],
        users: list[Any],
        expected_revision: tuple[int, int] | None = None,
    ) -> None:
        """写回绑定数据，并在读改写期间文件被改动时拒绝覆盖。

        Args:
            qq: 用户 QQ。
            data: 用户数据字典。
            users: 角色列表。
            expected_revision: 读取时记录的版本标记；不一致说明期间有其它写入。
        Raises:
            ValueError: 数据已被其他操作修改。
            RuntimeError: 写入失败。
        """
        if self.plugin._user_file_revision(qq) != expected_revision:
            raise ValueError("绑定数据已被其他操作修改，请刷新后重试")
        data["users"] = users
        data["num"] = len(users)
        if not self.plugin._save_user_data(qq, data):
            raise RuntimeError("写入绑定数据失败")

    def _remove_user_file(self, qq: str) -> None:
        user_dir = self.plugin._get_user_dir().resolve()
        user_file = Path(self.plugin._get_user_file(qq)).resolve()
        if user_file.parent != user_dir:
            raise RuntimeError("拒绝删除用户目录之外的文件")
        user_file.unlink(missing_ok=True)

    def _find_role_conflict(
        self,
        qq: str,
        account: str,
        game_id: str,
        role_id: str,
        *,
        exclude_index: int | None = None,
    ) -> str | None:
        target = (str(account), str(game_id), str(role_id))
        user_dir = self.plugin._get_user_dir()
        if not user_dir.exists():
            return None
        for user_file in sorted(user_dir.glob("*.json")):
            other_qq = user_file.stem
            if not QQ_RE.fullmatch(other_qq):
                continue
            data = self.plugin._load_user_data(other_qq)
            records = data.get("users", []) if isinstance(data, dict) else []
            if not isinstance(records, list):
                continue
            for record_index, record in enumerate(records, start=1):
                if other_qq == qq and record_index == exclude_index:
                    continue
                if not isinstance(record, dict):
                    continue
                try:
                    other_account = str(
                        self.plugin._decrypt_data(str(record.get("account", "")))
                    )
                    other_role_id = str(
                        self.plugin._decrypt_data(str(record.get("role_id", "")))
                    )
                except Exception:
                    continue
                identity = (
                    other_account,
                    str(self.plugin._get_bound_game_id(record)),
                    other_role_id,
                )
                if identity == target:
                    return other_qq
        return None

    def _default_role_info(self, game_id: str) -> str:
        server_type = self.plugin._get_server_type_name(game_id)
        return f"[{server_type}] 手动维护角色"

    @staticmethod
    def _raise_role_conflict(conflict_qq: str, qq: str) -> None:
        if conflict_qq == qq:
            raise ValueError("该 QQ 已绑定此角色")
        raise ValueError(f"该角色已被 QQ {conflict_qq} 绑定")

    def _build_data_snapshot(self) -> dict[str, Any]:
        user_dir = self.plugin._get_user_dir()
        user_files = sorted(user_dir.glob("*.json")) if user_dir.exists() else []
        users: list[dict[str, Any]] = []
        all_accounts: set[str] = set()
        status_totals = dict.fromkeys(SIGN_STATES, 0)
        roles_total = 0
        invalid_roles = 0

        for user_file in user_files:
            qq = user_file.stem
            if not QQ_RE.fullmatch(qq):
                continue
            user_data = self.plugin._load_user_data(qq)
            if not isinstance(user_data, dict):
                continue
            records = user_data.get("users", [])
            if not isinstance(records, list) or not records:
                continue

            account_set: set[str] = set()
            state_counts = dict.fromkeys(SIGN_STATES, 0)
            last_updated = 0
            for record in records:
                if not isinstance(record, dict):
                    invalid_roles += 1
                    status_totals["invalid"] += 1
                    state_counts["invalid"] += 1
                    continue
                is_channel = self.plugin._is_channel_record(record)
                try:
                    self.plugin._decrypt_data(str(record.get("role_id", "")))
                    account = ""
                    if not is_channel:
                        account = str(
                            self.plugin._decrypt_data(str(record.get("account", "")))
                        )
                except Exception:
                    invalid_roles += 1
                    state_counts["invalid"] += 1
                    status_totals["invalid"] += 1
                    continue
                state, _message, updated_at = self._sign_state(record)
                state_counts[state] += 1
                status_totals[state] += 1
                last_updated = max(last_updated, updated_at)
                if account:
                    account_set.add(account)

            if last_updated <= 0:
                try:
                    last_updated = int(user_file.stat().st_mtime)
                except OSError:
                    last_updated = 0

            role_count = len(records)
            roles_total += role_count
            all_accounts.update(account_set)
            users.append(
                {
                    "qq": qq,
                    "accounts": len(account_set),
                    "roles": role_count,
                    "success": state_counts["success"],
                    "already_claimed": state_counts["already_claimed"],
                    "failed": state_counts["failed"],
                    "pending": state_counts["pending"],
                    "invalid": state_counts["invalid"],
                    "unknown": state_counts["unknown"],
                    "last_updated": last_updated,
                    "status": self._user_status(state_counts, role_count),
                }
            )

        users.sort(key=lambda item: (item["last_updated"], item["qq"]), reverse=True)
        pending = self._build_pending_snapshot()
        success = status_totals["success"]
        attention = status_totals["failed"] + status_totals["invalid"]
        sign_total = success + attention
        success_rate = round(success / sign_total * 100, 1) if sign_total else None

        return {
            "generated_at": int(time.time()),
            "stats": {
                "users": len(users),
                "accounts": len(all_accounts),
                "roles": roles_total,
                "success": success,
                "already_claimed": status_totals["already_claimed"],
                "failed": status_totals["failed"],
                "pending": status_totals["pending"],
                "invalid": status_totals["invalid"],
                "unknown": status_totals["unknown"],
                "attention": attention,
                "invalid_roles": invalid_roles,
                "success_rate": success_rate,
                "pending_web_requests": pending["qq_count"],
                "pending_web_roles": pending["roles"],
            },
            "users": users,
            "pending": pending,
        }

    def _build_user_detail(self, qq: str) -> dict[str, Any] | None:
        user_data = self.plugin._load_user_data(qq)
        if not isinstance(user_data, dict):
            return None
        records = user_data.get("users", [])
        if not isinstance(records, list):
            records = []

        roles: list[dict[str, Any]] = []
        accounts: set[str] = set()
        state_counts = dict.fromkeys(SIGN_STATES, 0)
        last_updated = 0
        for index, record in enumerate(records, start=1):
            if not isinstance(record, dict):
                state_counts["invalid"] += 1
                roles.append(
                    {
                        "index": index,
                        "info": "数据格式损坏",
                        "game_id": "",
                        "server": "未知服",
                        "account": "••••",
                        "role_id": "••••",
                        "state": "invalid",
                        "message": "角色记录格式异常",
                        "updated_at": 0,
                    }
                )
                continue

            state, message, updated_at = self._sign_state(record)
            last_updated = max(last_updated, updated_at)
            if self.plugin._is_channel_record(record):
                platform = self.plugin._get_channel_platform(record)
                channel_name = CHANNEL_PLATFORM_NAMES.get(
                    platform, platform or "未知渠道"
                )
                role_mask = "••••"
                role_id = ""
                try:
                    role_id = str(
                        self.plugin._decrypt_data(str(record.get("role_id", "")))
                    )
                    role_mask = _mask_role_id(role_id)
                except Exception:
                    state = "invalid"
                    message = "渠道服角色数据解密失败"
                state_counts[state] += 1
                roles.append(
                    {
                        "index": index,
                        "binding_type": "channel",
                        "channel": True,
                        "platform": platform,
                        "platform_name": channel_name,
                        "info": _redact_sensitive_text(
                            record.get("info", "未知渠道服角色"), (role_id,)
                        ),
                        "game_id": "",
                        "server": f"渠道服 · {channel_name}",
                        "account": "",
                        "role_id": role_mask,
                        "state": state,
                        "message": _redact_sensitive_text(message, (role_id,)),
                        "updated_at": updated_at,
                    }
                )
                continue
            account_mask = "••••"
            role_mask = "••••"
            account = ""
            role_id = ""
            try:
                account = str(self.plugin._decrypt_data(str(record.get("account", ""))))
                role_id = str(self.plugin._decrypt_data(str(record.get("role_id", ""))))
                account_mask = _mask_account(account)
                role_mask = _mask_role_id(role_id)
                if account:
                    accounts.add(account)
            except Exception:
                state = "invalid"
                message = "账号数据解密失败"
                state_counts["invalid"] += 1
                roles.append(
                    {
                        "index": index,
                        "info": _redact_sensitive_text(
                            record.get("info", "未知角色"),
                            (account, role_id),
                        ),
                        "game_id": str(self.plugin._get_bound_game_id(record)),
                        "server": self.plugin._get_server_type_name(
                            self.plugin._get_bound_game_id(record)
                        ),
                        "account": account_mask,
                        "role_id": role_mask,
                        "state": state,
                        "message": _redact_sensitive_text(message, (account, role_id)),
                        "updated_at": updated_at,
                    }
                )
                continue

            state_counts[state] += 1
            game_id = str(self.plugin._get_bound_game_id(record))
            roles.append(
                {
                    "index": index,
                    "info": _redact_sensitive_text(
                        record.get("info", "未知角色"),
                        (account, role_id),
                    ),
                    "game_id": game_id,
                    "server": self.plugin._get_server_type_name(game_id),
                    "account": account_mask,
                    "role_id": role_mask,
                    "state": state,
                    "message": _redact_sensitive_text(message, (account, role_id)),
                    "updated_at": updated_at,
                }
            )

        return {
            "qq": qq,
            "accounts": len(accounts),
            "roles": len(roles),
            "last_updated": last_updated,
            "status": self._user_status(state_counts, len(roles)),
            "state_counts": state_counts,
            "items": roles,
            "masked": True,
        }

    def _build_pending_snapshot(self) -> dict[str, Any]:
        folder = self.plugin._get_web_pending_dir()
        now = int(time.time())
        items: list[dict[str, Any]] = []
        roles_total = 0
        expired_roles = 0

        pending_files = sorted(folder.glob("*.json")) if folder.exists() else []
        for path in pending_files:
            qq = path.stem
            if not QQ_RE.fullmatch(qq):
                continue
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            records = payload.get("records", []) if isinstance(payload, dict) else []
            if not isinstance(records, list):
                continue

            auto_roles = 0
            manual_roles = 0
            due_roles = 0
            earliest_expiry = 0
            earliest_auto_sign = 0
            for record in records:
                if not isinstance(record, dict):
                    continue
                expires_at = _as_int(record.get("expires_at"))
                if expires_at <= now:
                    expired_roles += 1
                    continue
                sign_mode = str(record.get("sign_mode", "manual")).strip().lower()
                if sign_mode == "auto":
                    auto_roles += 1
                    auto_sign_at = _as_int(record.get("auto_sign_at"))
                    attempted_at = _as_int(record.get("auto_attempted_at"))
                    if auto_sign_at and auto_sign_at <= now and attempted_at <= 0:
                        due_roles += 1
                    if auto_sign_at > 0:
                        earliest_auto_sign = (
                            min(earliest_auto_sign, auto_sign_at)
                            if earliest_auto_sign
                            else auto_sign_at
                        )
                else:
                    manual_roles += 1
                earliest_expiry = (
                    min(earliest_expiry, expires_at) if earliest_expiry else expires_at
                )

            active_roles = auto_roles + manual_roles
            if active_roles <= 0:
                continue
            roles_total += active_roles
            items.append(
                {
                    "qq": qq,
                    "roles": active_roles,
                    "auto": auto_roles,
                    "manual": manual_roles,
                    "due": due_roles,
                    "earliest_expiry": earliest_expiry,
                    "earliest_auto_sign": earliest_auto_sign,
                    "updated_at": _as_int(payload.get("updated_at")),
                }
            )

        items.sort(key=lambda item: (item["due"] > 0, item["updated_at"]), reverse=True)
        return {
            "items": items,
            "qq_count": len(items),
            "roles": roles_total,
            "expired_roles": expired_roles,
            "due_roles": sum(item["due"] for item in items),
            "server_time": now,
        }

    def _build_strategy_snapshot(self, saved_authors: dict[str, Any]) -> dict[str, Any]:
        now = int(time.time())
        cache_dir: Path | None = None
        cache_getter = getattr(self.plugin, "_get_author_cache_dir", None)
        if callable(cache_getter):
            try:
                cache_dir = Path(cache_getter())
            except Exception as exc:
                logger.warning(f"读取攻略缓存目录失败: {exc}")

        cache_files: dict[str, Path] = {}
        if cache_dir is not None and cache_dir.exists():
            try:
                cache_files = {
                    path.stem: path
                    for path in cache_dir.glob("*.json")
                    if path.is_file()
                }
            except OSError as exc:
                logger.warning(f"读取攻略缓存文件失败: {exc}")

        saved_names = {str(name).strip() for name in saved_authors if str(name).strip()}
        authors: list[dict[str, Any]] = []
        for name in sorted(saved_names | set(cache_files)):
            cache_path = cache_files.get(name)
            cached = cache_path is not None
            cache_readable = False
            article_count = 0
            latest_article_at = 0
            cache_updated_at = 0
            if cache_path is not None:
                try:
                    payload = json.loads(cache_path.read_text(encoding="utf-8"))
                except (OSError, ValueError) as exc:
                    logger.warning(f"读取攻略作者缓存 {name} 失败: {exc}")
                    payload = None
                if isinstance(payload, dict):
                    cache_readable = True
                    articles = payload.get("articles", [])
                    if isinstance(articles, list):
                        article_count = len(articles)
                        latest_article_at = max(
                            (
                                _article_timestamp(article)
                                for article in articles
                                if isinstance(article, dict)
                            ),
                            default=0,
                        )
                    else:
                        article_count = _as_int(payload.get("num"))
                    cache_updated_at = _as_int(payload.get("synced_at"))
                if cache_updated_at <= 0:
                    try:
                        cache_updated_at = int(cache_path.stat().st_mtime)
                    except OSError:
                        cache_updated_at = 0
            authors.append(
                {
                    "name": name,
                    "saved": name in saved_names,
                    "cached": cached,
                    "cache_readable": cache_readable,
                    "article_count": article_count,
                    "latest_article_at": latest_article_at,
                    "cache_updated_at": cache_updated_at,
                }
            )
        authors.sort(
            key=lambda item: (
                bool(item["cache_readable"]),
                _as_int(item["latest_article_at"]),
                str(item["name"]),
            ),
            reverse=True,
        )

        push_targets: list[dict[str, str]] = []
        push_file_present = False
        data_dir = getattr(self.plugin, "data_dir", None)
        if isinstance(data_dir, str | Path):
            push_file = Path(data_dir) / "push_datas" / "strategy.json"
            push_file_present = push_file.is_file()
            if push_file_present:
                try:
                    push_payload = json.loads(push_file.read_text(encoding="utf-8"))
                except (OSError, ValueError) as exc:
                    logger.warning(f"读取攻略推送目标失败: {exc}")
                    push_payload = None
                targets = (
                    push_payload.get("datas", [])
                    if isinstance(push_payload, dict)
                    else []
                )
                if isinstance(targets, list):
                    push_targets = [
                        _describe_push_target(target)
                        for target in targets
                        if str(target or "").strip()
                    ]

        config = getattr(self.plugin, "config", {}) or {}
        exporter_url_configured = bool(
            str(config.get("exporter_api_url", "") or "").strip()
        )
        exporter_key_configured = bool(
            str(config.get("exporter_auth_key", "") or "").strip()
        )
        latest_cache_sync_at = max(
            (_as_int(item["cache_updated_at"]) for item in authors), default=0
        )
        return {
            "generated_at": now,
            "authors": authors,
            "author_count": len(authors),
            "saved_author_count": len(saved_names),
            "cached_author_count": sum(bool(item["cached"]) for item in authors),
            "readable_author_count": sum(
                bool(item["cache_readable"]) for item in authors
            ),
            "article_count": sum(_as_int(item["article_count"]) for item in authors),
            "latest_cache_sync_at": latest_cache_sync_at,
            "push_targets": push_targets,
            "push_target_count": len(push_targets),
            "push_file_present": push_file_present,
            "exporter_configured": exporter_url_configured and exporter_key_configured,
            "exporter_url_configured": exporter_url_configured,
            "exporter_key_configured": exporter_key_configured,
            "sync_window_days": 7,
            "server_time": now,
        }

    def _build_runtime_snapshot(self) -> dict[str, Any]:
        scheduler = getattr(self.plugin, "scheduler", None)
        jobs: list[dict[str, Any]] = []
        if scheduler is not None:
            try:
                for job in scheduler.get_jobs():
                    next_run = getattr(job, "next_run_time", None)
                    jobs.append(
                        {
                            "id": job.id,
                            "label": JOB_LABELS.get(job.id, job.id),
                            "service": JOB_SERVICES.get(job.id, "other"),
                            "next_run_time": next_run.isoformat() if next_run else None,
                        }
                    )
            except Exception as exc:
                logger.warning(f"读取插件定时任务状态失败: {exc}")

        config = getattr(self.plugin, "config", {}) or {}
        progress = dict(getattr(self.plugin, "_auto_sign_progress", {}) or {})
        secret = config.get("encryption_secret_key", "")
        keep_sign_running = bool(getattr(self.plugin, "_keep_sign_running", False))
        mutation_lock_reason = self._mutation_lock_reason()
        return {
            "scheduler_running": bool(getattr(scheduler, "running", False)),
            "jobs": jobs,
            "auto_sign_progress": progress,
            "keep_sign_running": keep_sign_running,
            "mutations_locked": bool(mutation_lock_reason),
            "mutation_lock_reason": mutation_lock_reason,
            "headers_configured": bool(getattr(self.plugin, "headers", None)),
            "portal_configured": self.plugin._get_portal_settings() is not None,
            "encryption_configured": bool(isinstance(secret, str) and secret.strip()),
            "exporter_configured": bool(
                str(config.get("exporter_api_url", "") or "").strip()
                and str(config.get("exporter_auth_key", "") or "").strip()
            ),
            "auto_sign_delay_seconds": self.plugin._get_auto_sign_delay_seconds(),
            "server_time": int(time.time()),
        }

    @staticmethod
    def _sign_state(record: dict[str, Any]) -> tuple[str, str, int]:
        status = record.get("sign_status")
        if not isinstance(status, dict):
            return "unknown", "", 0
        state = str(status.get("state", "unknown")).strip().lower()
        if state not in SIGN_STATES:
            state = "unknown"
        return (
            state,
            str(status.get("message", "") or ""),
            _as_int(status.get("updated_at")),
        )

    @staticmethod
    def _user_status(counts: dict[str, int], role_count: int) -> str:
        if role_count <= 0:
            return "empty"
        if counts.get("failed", 0) or counts.get("invalid", 0):
            return "attention"
        if counts.get("pending", 0):
            return "pending"
        if counts.get("success", 0) or counts.get("already_claimed", 0):
            return "healthy"
        return "unknown"


class SnailAdminPageController:
    def __init__(self, context: Any, plugin: Any):
        self.context = context
        self.service = SnailAdminPageService(plugin)

    def register_routes(self) -> None:
        routes: list[tuple[str, Callable[[], Awaitable[Any]], list[str], str]] = [
            ("/admin/ping", self.page_ping, ["GET"], "Snail admin page ping"),
            (
                "/admin/bootstrap",
                self.page_bootstrap,
                ["GET"],
                "Load snail admin overview and user bindings",
            ),
            (
                "/admin/signin/bootstrap",
                self.page_signin_bootstrap,
                ["GET"],
                "Load sign-in service overview and user bindings",
            ),
            (
                "/admin/strategy/bootstrap",
                self.page_strategy_bootstrap,
                ["GET"],
                "Load strategy service authors, caches and push targets",
            ),
            (
                "/admin/user",
                self.page_user,
                ["GET"],
                "Load masked role details for one QQ",
            ),
            (
                "/admin/sync",
                self.page_sync,
                ["POST"],
                "Import pending website binding requests",
            ),
            (
                "/admin/strategy/service",
                self.page_strategy_service,
                ["POST"],
                "Enable or disable the whole strategy service",
            ),
            (
                "/admin/signin/sync",
                self.page_signin_sync,
                ["POST"],
                "Import pending website binding requests for sign-in service",
            ),
            (
                "/admin/signin/gift/update",
                self.page_signin_gift_update,
                ["POST"],
                "Update sign-in gift claim mode",
            ),
            (
                "/admin/signin/notification/settings",
                self.page_signin_notification_settings,
                ["POST"],
                "Update sign-in summary notification settings",
            ),
            (
                "/admin/signin/notification/add",
                self.page_signin_notification_add,
                ["POST"],
                "Create one sign-in summary notification target",
            ),
            (
                "/admin/signin/notification/update",
                self.page_signin_notification_update,
                ["POST"],
                "Update one sign-in summary notification target",
            ),
            (
                "/admin/signin/notification/delete",
                self.page_signin_notification_delete,
                ["POST"],
                "Delete one sign-in summary notification target",
            ),
            (
                "/admin/binding/add",
                self.page_binding_add,
                ["POST"],
                "Create one QQ role binding",
            ),
            (
                "/admin/binding/update",
                self.page_binding_update,
                ["POST"],
                "Update one QQ role binding",
            ),
            (
                "/admin/binding/delete",
                self.page_binding_delete,
                ["POST"],
                "Delete one QQ role binding",
            ),
            (
                "/admin/user/delete",
                self.page_user_delete,
                ["POST"],
                "Delete all role bindings for one QQ",
            ),
            (
                "/admin/strategy/author/add",
                self.page_strategy_author_add,
                ["POST"],
                "Create one saved strategy author",
            ),
            (
                "/admin/strategy/author/update",
                self.page_strategy_author_update,
                ["POST"],
                "Update or rename one saved strategy author",
            ),
            (
                "/admin/strategy/author/delete",
                self.page_strategy_author_delete,
                ["POST"],
                "Remove author registration or delete cached articles",
            ),
            (
                "/admin/strategy/author/articles",
                self.page_strategy_author_articles,
                ["GET"],
                "Load cached articles for one strategy author",
            ),
            (
                "/admin/strategy/push/add",
                self.page_strategy_push_add,
                ["POST"],
                "Create one strategy push target",
            ),
            (
                "/admin/strategy/push/update",
                self.page_strategy_push_update,
                ["POST"],
                "Update one strategy push target",
            ),
            (
                "/admin/strategy/push/delete",
                self.page_strategy_push_delete,
                ["POST"],
                "Delete one strategy push target",
            ),
        ]
        for path, handler, methods, description in routes:
            self.context.register_web_api(
                f"/{PLUGIN_NAME}{path}",
                self._wrap_handler(handler),
                methods,
                description,
            )

    @staticmethod
    def _check_quart_available() -> None:
        if quart_jsonify is None or quart_request is None:
            raise RuntimeError("AstrBot Web 框架不可用，无法加载管理页 API")

    @classmethod
    async def _json_body(cls) -> dict[str, Any]:
        cls._check_quart_available()
        payload = await quart_request.get_json(force=True, silent=True)
        return payload if isinstance(payload, dict) else {}

    @staticmethod
    def _jsonify(payload: dict[str, Any]):
        SnailAdminPageController._check_quart_available()
        return cast(Callable[[dict[str, Any]], Any], quart_jsonify)(payload)

    @staticmethod
    def _request():
        SnailAdminPageController._check_quart_available()
        return cast(Any, quart_request)

    def _wrap_handler(
        self,
        handler: Callable[[], Awaitable[Any]],
    ) -> Callable[[], Awaitable[Any]]:
        async def wrapped():
            self._check_quart_available()
            try:
                return await handler()
            except ValueError as exc:
                return self._jsonify({"ok": False, "message": str(exc)}), 400
            except Exception as exc:
                logger.exception("最强蜗牛管理页请求失败")
                return (
                    self._jsonify({"ok": False, "message": f"管理页请求失败: {exc}"}),
                    500,
                )

        wrapped.__name__ = handler.__name__
        return wrapped

    async def page_ping(self):
        return self._jsonify({"ok": True, "data": {"message": "pong"}})

    async def page_bootstrap(self):
        return self._jsonify({"ok": True, "data": await self.service.get_bootstrap()})

    async def page_signin_bootstrap(self):
        return self._jsonify(
            {"ok": True, "data": await self.service.get_signin_bootstrap()}
        )

    async def page_strategy_bootstrap(self):
        return self._jsonify(
            {"ok": True, "data": await self.service.get_strategy_bootstrap()}
        )

    async def page_user(self):
        qq = str(self._request().args.get("qq", "")).strip()
        return self._jsonify(
            {"ok": True, "data": await self.service.get_user_detail(qq)}
        )

    async def page_sync(self):
        await self._json_body()
        return self._jsonify(
            {"ok": True, "data": await self.service.sync_web_bindings()}
        )

    async def page_signin_sync(self):
        return await self.page_sync()

    async def page_strategy_service(self):
        payload = await self._json_body()
        data = await asyncio.to_thread(
            self.service.set_strategy_service_enabled, payload
        )
        return self._jsonify({"ok": True, "data": data})

    async def page_signin_gift_update(self):
        payload = await self._json_body()
        data = await asyncio.to_thread(
            self.service.update_signin_gift_settings, payload
        )
        return self._jsonify({"ok": True, "data": data})

    async def page_signin_notification_settings(self):
        payload = await self._json_body()
        data = await asyncio.to_thread(
            self.service.update_signin_notification_settings, payload
        )
        return self._jsonify({"ok": True, "data": data})

    async def page_signin_notification_add(self):
        payload = await self._json_body()
        data = await asyncio.to_thread(self.service.create_signin_push_target, payload)
        return self._jsonify({"ok": True, "data": data})

    async def page_signin_notification_update(self):
        payload = await self._json_body()
        data = await asyncio.to_thread(self.service.update_signin_push_target, payload)
        return self._jsonify({"ok": True, "data": data})

    async def page_signin_notification_delete(self):
        payload = await self._json_body()
        data = await asyncio.to_thread(self.service.delete_signin_push_target, payload)
        return self._jsonify({"ok": True, "data": data})

    async def page_binding_add(self):
        payload = await self._json_body()
        data = await asyncio.to_thread(self.service.create_binding, payload)
        return self._jsonify({"ok": True, "data": data})

    async def page_binding_update(self):
        payload = await self._json_body()
        data = await asyncio.to_thread(self.service.update_binding, payload)
        return self._jsonify({"ok": True, "data": data})

    async def page_binding_delete(self):
        payload = await self._json_body()
        data = await asyncio.to_thread(self.service.delete_binding, payload)
        return self._jsonify({"ok": True, "data": data})

    async def page_user_delete(self):
        payload = await self._json_body()
        data = await asyncio.to_thread(self.service.delete_user, payload)
        return self._jsonify({"ok": True, "data": data})

    async def page_strategy_author_add(self):
        payload = await self._json_body()
        data = await self.service.create_strategy_author(payload)
        return self._jsonify({"ok": True, "data": data})

    async def page_strategy_author_update(self):
        payload = await self._json_body()
        data = await self.service.update_strategy_author(payload)
        return self._jsonify({"ok": True, "data": data})

    async def page_strategy_author_delete(self):
        payload = await self._json_body()
        data = await self.service.delete_strategy_author(payload)
        return self._jsonify({"ok": True, "data": data})

    async def page_strategy_author_articles(self):
        request = self._request()
        name = request.args.get("name", "")
        limit = request.args.get("limit", 100)
        data = await self.service.get_strategy_author_articles(name, limit)
        return self._jsonify({"ok": True, "data": data})

    async def page_strategy_push_add(self):
        payload = await self._json_body()
        data = await asyncio.to_thread(self.service.create_push_target, payload)
        return self._jsonify({"ok": True, "data": data})

    async def page_strategy_push_update(self):
        payload = await self._json_body()
        data = await asyncio.to_thread(self.service.update_push_target, payload)
        return self._jsonify({"ok": True, "data": data})

    async def page_strategy_push_delete(self):
        payload = await self._json_body()
        data = await asyncio.to_thread(self.service.delete_push_target, payload)
        return self._jsonify({"ok": True, "data": data})
