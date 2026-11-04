"""攻略服务开关的持久化存储。

攻略服务依赖外部数据源（wechat-article-exporter）。数据源不可用时，管理员
可以在管理页一键关闭攻略相关指令与更新任务；开关状态保存在插件数据目录，
不随插件升级丢失。
"""

from __future__ import annotations

import copy
import json
import threading
from pathlib import Path
from typing import Any

from astrbot.api import logger

from .utils import atomic_write_json

STRATEGY_SETTINGS_DIR = "settings"
STRATEGY_SETTINGS_FILE = "strategy.json"
_STORE_LOCK = threading.RLock()


def default_strategy_settings() -> dict[str, Any]:
    """返回攻略服务的默认设置。

    Returns:
        默认设置字典，攻略服务默认开启以保持升级后的原有行为。
    """
    return {"version": 1, "service": {"enabled": True}}


def _settings_path(data_dir: str | Path) -> Path:
    """返回攻略服务设置文件路径。"""
    return Path(data_dir).resolve() / STRATEGY_SETTINGS_DIR / STRATEGY_SETTINGS_FILE


def _coerce_enabled(value: Any, default: bool = True) -> bool:
    """把配置中的开关值统一转换为布尔值。"""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return default


def normalize_strategy_settings(payload: Any) -> dict[str, Any]:
    """规范化攻略服务设置，保证字段齐全且类型正确。

    Args:
        payload: 读取到的原始设置。

    Returns:
        规范化后的设置字典。
    """
    normalized = copy.deepcopy(payload) if isinstance(payload, dict) else {}
    service_source = normalized.get("service")
    service = copy.deepcopy(service_source) if isinstance(service_source, dict) else {}
    service["enabled"] = _coerce_enabled(service.get("enabled"), True)
    normalized["version"] = 1
    normalized["service"] = service
    return normalized


def load_strategy_settings(data_dir: str | Path) -> dict[str, Any]:
    """读取攻略服务设置，文件缺失或损坏时回退默认值。

    Args:
        data_dir: 插件数据目录。

    Returns:
        设置字典。
    """
    path = _settings_path(data_dir)
    if not path.is_file():
        return default_strategy_settings()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.warning(f"读取攻略服务设置失败，将使用默认值: {exc}")
        return default_strategy_settings()
    if not isinstance(payload, dict):
        logger.warning("攻略服务设置格式异常，将使用默认值")
        return default_strategy_settings()
    return normalize_strategy_settings(payload)


def write_strategy_settings(
    data_dir: str | Path, payload: dict[str, Any]
) -> dict[str, Any]:
    """写入攻略服务设置。

    Args:
        data_dir: 插件数据目录。
        payload: 待写入的设置。

    Returns:
        规范化后实际写入的设置。
    """
    path = _settings_path(data_dir)
    normalized = normalize_strategy_settings(payload)
    with _STORE_LOCK:
        atomic_write_json(path, normalized)
    return normalized


def is_strategy_service_enabled(data_dir: str | Path) -> bool:
    """判断攻略服务是否开启。

    Args:
        data_dir: 插件数据目录。

    Returns:
        开关状态，默认开启。
    """
    settings = load_strategy_settings(data_dir)
    return bool(settings["service"]["enabled"])


def set_strategy_service_enabled(data_dir: str | Path, enabled: bool) -> dict[str, Any]:
    """设置攻略服务开关。

    Args:
        data_dir: 插件数据目录。
        enabled: 是否开启。

    Returns:
        保存后的设置字典。
    """
    settings = load_strategy_settings(data_dir)
    settings["service"]["enabled"] = bool(enabled)
    return write_strategy_settings(data_dir, settings)
