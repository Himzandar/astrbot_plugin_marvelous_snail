from __future__ import annotations

import copy
import json
import threading
from pathlib import Path
from typing import Any

from astrbot.api import logger

from .signin_summary import (
    DEFAULT_SUMMARY_DETAIL_MODE,
    SUMMARY_DETAIL_MODES,
)
from .utils import atomic_write_json

SIGNIN_SETTINGS_DIR = "settings"
SIGNIN_SETTINGS_FILE = "signin.json"
SIGN_PUSH_DIR = "push_datas"
SIGN_PUSH_FILE = "sign.json"
GIFT_CLAIM_MODES = ("all", "none")
GIFT_CLAIM_MODE_LABELS = {
    "all": "全部可领取礼包",
    "none": "不自动领取",
}
_STORE_LOCK = threading.RLock()


def default_signin_settings() -> dict[str, Any]:
    return {
        "version": 1,
        "gift": {"claim_mode": "all"},
        "notification": {
            "enabled": True,
            "include_reward_image": True,
            "detail_mode": DEFAULT_SUMMARY_DETAIL_MODE,
        },
    }


def _data_root(data_dir: str | Path) -> Path:
    return Path(data_dir).resolve()


def _settings_path(data_dir: str | Path) -> Path:
    return _data_root(data_dir) / SIGNIN_SETTINGS_DIR / SIGNIN_SETTINGS_FILE


def _push_path(data_dir: str | Path) -> Path:
    return _data_root(data_dir) / SIGN_PUSH_DIR / SIGN_PUSH_FILE


def _coerce_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return default


def normalize_gift_claim_mode(value: Any) -> str:
    mode = str(value or "").strip().lower()
    if mode not in GIFT_CLAIM_MODES:
        raise ValueError("礼包领取类型必须为全部领取或不领取")
    return mode


def normalize_bool(value: Any, field: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    raise ValueError(f"{field}必须为布尔值")


def normalize_summary_detail_mode(value: Any) -> str:
    mode = str(value or "").strip().lower()
    if mode not in SUMMARY_DETAIL_MODES:
        raise ValueError("汇总明细必须为异常加用户概览、仅异常或完整角色明细")
    return mode


def normalize_signin_settings(payload: Any) -> dict[str, Any]:
    normalized = copy.deepcopy(payload) if isinstance(payload, dict) else {}
    gift_source = normalized.get("gift")
    gift = copy.deepcopy(gift_source) if isinstance(gift_source, dict) else {}
    notification_source = normalized.get("notification")
    notification = (
        copy.deepcopy(notification_source)
        if isinstance(notification_source, dict)
        else {}
    )

    claim_mode = str(gift.get("claim_mode", "all") or "all").strip().lower()
    if claim_mode not in GIFT_CLAIM_MODES:
        claim_mode = "all"
    gift["claim_mode"] = claim_mode
    notification["enabled"] = _coerce_bool(notification.get("enabled"), True)
    notification["include_reward_image"] = _coerce_bool(
        notification.get("include_reward_image"), True
    )
    detail_mode = (
        str(
            notification.get("detail_mode", DEFAULT_SUMMARY_DETAIL_MODE)
            or DEFAULT_SUMMARY_DETAIL_MODE
        )
        .strip()
        .lower()
    )
    if detail_mode not in SUMMARY_DETAIL_MODES:
        detail_mode = DEFAULT_SUMMARY_DETAIL_MODE
    notification["detail_mode"] = detail_mode

    normalized["version"] = 1
    normalized["gift"] = gift
    normalized["notification"] = notification
    return normalized


def load_signin_settings(data_dir: str | Path) -> dict[str, Any]:
    path = _settings_path(data_dir)
    if not path.is_file():
        return default_signin_settings()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.warning(f"读取签到偏好设置失败，将使用默认值: {exc}")
        return default_signin_settings()
    if not isinstance(payload, dict):
        logger.warning("签到偏好设置格式异常，将使用默认值")
        return default_signin_settings()
    return normalize_signin_settings(payload)


def write_signin_settings(
    data_dir: str | Path, payload: dict[str, Any]
) -> dict[str, Any]:
    path = _settings_path(data_dir)
    normalized = normalize_signin_settings(payload)
    with _STORE_LOCK:
        atomic_write_json(path, normalized)
    return normalized


def update_signin_notification_enabled(
    data_dir: str | Path, enabled: bool
) -> dict[str, Any]:
    with _STORE_LOCK:
        settings = load_signin_settings(data_dir)
        settings["notification"]["enabled"] = bool(enabled)
        return write_signin_settings(data_dir, settings)


def load_sign_push_payload(
    data_dir: str | Path, *, strict: bool = False
) -> dict[str, Any]:
    path = _push_path(data_dir)
    if not path.is_file():
        return {"datas": []}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        if strict:
            raise ValueError("签到通知目标文件格式异常，请先修复文件") from exc
        logger.warning(f"读取签到通知目标失败: {exc}")
        return {"datas": []}
    if not isinstance(payload, dict):
        if strict:
            raise ValueError("签到通知目标文件格式异常，请先修复文件")
        logger.warning("签到通知目标文件格式异常")
        return {"datas": []}
    targets = payload.get("datas", [])
    if not isinstance(targets, list) or any(
        not isinstance(target, str) for target in targets
    ):
        if strict:
            raise ValueError("签到通知目标 datas 字段格式异常，请先修复文件")
        logger.warning("签到通知目标 datas 字段格式异常")
        return {"datas": []}
    return payload


def write_sign_push_payload(data_dir: str | Path, payload: dict[str, Any]) -> None:
    path = _push_path(data_dir)
    with _STORE_LOCK:
        atomic_write_json(path, payload)
