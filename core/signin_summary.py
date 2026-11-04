from __future__ import annotations

import time
from datetime import datetime
from typing import Any

SUMMARY_DETAIL_MODES = ("issues_overview", "issues_only", "full")
SUMMARY_DETAIL_MODE_LABELS = {
    "issues_overview": "异常 + 用户概览",
    "issues_only": "仅异常",
    "full": "完整角色明细",
}
DEFAULT_SUMMARY_DETAIL_MODE = "issues_overview"

GIFT_STATE_LABELS = {
    "success": "成功",
    "partial": "部分失败",
    "failed": "失败",
    "none": "无可领",
    "off": "已关闭",
    "not_attempted": "未执行",
}

_SIGN_STATE_LABELS = {
    "success": "成功",
    "already_claimed": "已领取",
    "failed": "失败",
    "invalid": "数据异常",
}


def _clean_text(value: Any, limit: int = 120) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return f"{text[: max(1, limit - 1)]}…"


def _clean_names(values: Any, limit: int = 120) -> list[str]:
    if not isinstance(values, list):
        return []
    names = [_clean_text(value, 40) for value in values if str(value or "").strip()]
    return names[:12]


def classify_gift_result(gift_summary: Any) -> dict[str, Any]:
    """Normalize one role's gift-claim result for summaries."""
    if gift_summary is None:
        return {
            "gift_state": "not_attempted",
            "gift_success_count": 0,
            "gift_failed_count": 0,
            "claimed_gifts": [],
            "failed_gifts": [],
            "failed_reasons": [],
            "gift_skip_reason": "",
        }
    if not isinstance(gift_summary, dict):
        return {
            "gift_state": "failed",
            "gift_success_count": 0,
            "gift_failed_count": 1,
            "claimed_gifts": [],
            "failed_gifts": ["返回数据异常"],
            "failed_reasons": ["返回数据异常"],
            "gift_skip_reason": "",
        }

    success_count = max(0, int(gift_summary.get("success_count", 0) or 0))
    failed_count = max(0, int(gift_summary.get("failed_count", 0) or 0))
    skip_reason = _clean_text(gift_summary.get("skip_reason", ""), 120)
    claimed_gifts = _clean_names(gift_summary.get("claimed_gifts", []))
    failed_gifts = _clean_names(gift_summary.get("failed_gifts", []))
    failed_reasons = _clean_names(gift_summary.get("failed_reasons", []))

    if skip_reason == "礼包自动领取已关闭":
        state = "off"
        success_count = 0
        failed_count = 0
        claimed_gifts = []
        failed_gifts = []
        failed_reasons = []
    elif success_count > 0 and failed_count > 0:
        state = "partial"
    elif failed_count > 0:
        state = "failed"
    elif success_count > 0:
        state = "success"
    else:
        state = "none"

    return {
        "gift_state": state,
        "gift_success_count": success_count,
        "gift_failed_count": failed_count,
        "claimed_gifts": claimed_gifts,
        "failed_gifts": failed_gifts,
        "failed_reasons": failed_reasons,
        "gift_skip_reason": skip_reason,
    }


def build_role_summary_record(
    qq: str,
    role: Any,
    sign_state: str,
    sign_message: Any,
    gift_summary: Any = None,
) -> dict[str, Any]:
    gift = classify_gift_result(gift_summary)
    return {
        "qq": _clean_text(qq, 32),
        "role": _clean_text(role or "未知角色", 120),
        "sign_state": (sign_state if sign_state in _SIGN_STATE_LABELS else "failed"),
        "sign_message": _clean_text(sign_message or "未知结果", 120),
        **gift,
    }


def build_user_summary_record(
    qq: str,
    account_count: int,
    success_count: int,
    failed_count: int,
    role_records: list[dict[str, Any]],
    already_claimed_count: int = 0,
) -> dict[str, Any]:
    gift_counts = dict.fromkeys(GIFT_STATE_LABELS, 0)
    for record in role_records:
        state = str(record.get("gift_state", "not_attempted"))
        if state in gift_counts:
            gift_counts[state] += 1
    return {
        "qq": _clean_text(qq, 32),
        "account_count": max(0, int(account_count or 0)),
        "success_count": max(0, int(success_count or 0)),
        "already_claimed_count": max(0, int(already_claimed_count or 0)),
        "failed_count": max(0, int(failed_count or 0)),
        "gift_counts": gift_counts,
    }


def _is_issue(record: dict[str, Any]) -> bool:
    return record.get("sign_state") not in {
        "success",
        "already_claimed",
    } or record.get("gift_state") in {"partial", "failed"}


def _issue_sort_key(record: dict[str, Any]) -> tuple[int, str, str]:
    sign_state = record.get("sign_state")
    gift_state = record.get("gift_state")
    if sign_state == "invalid":
        severity = 0
    elif sign_state == "failed":
        severity = 1
    elif gift_state == "failed":
        severity = 2
    else:
        severity = 3
    return severity, str(record.get("qq", "")), str(record.get("role", ""))


def _format_gift_text(record: dict[str, Any]) -> str:
    state = str(record.get("gift_state", "not_attempted"))
    if state == "not_attempted":
        return ""
    label = GIFT_STATE_LABELS.get(state, state)
    if state == "off":
        return "礼包：已在管理页关闭"
    if state == "none":
        return "礼包：无可领取礼包"

    claimed = record.get("claimed_gifts") or []
    failed = record.get("failed_gifts") or []
    failed_reasons = record.get("failed_reasons") or []
    if state == "failed" and failed:
        text = f"礼包{label}：{'、'.join(str(name) for name in failed)}"
        if failed_reasons:
            text += f"（{'；'.join(str(reason) for reason in failed_reasons)}）"
        return text
    details: list[str] = []
    if claimed:
        details.append(f"已领 {'、'.join(str(name) for name in claimed)}")
    if failed:
        details.append(f"失败 {'、'.join(str(name) for name in failed)}")
    if failed_reasons:
        details.append(f"原因 {'；'.join(str(reason) for reason in failed_reasons)}")
    return f"礼包{label}：{'；'.join(details)}" if details else f"礼包{label}"


def format_role_record(record: dict[str, Any], *, issue: bool = False) -> str:
    sign_state = str(record.get("sign_state", "failed"))
    sign_label = _SIGN_STATE_LABELS.get(sign_state, sign_state)
    sign_text = (
        f"今日已领取（{record.get('sign_message', '未知结果')}）"
        if sign_state == "already_claimed"
        else f"签到{sign_label}（{record.get('sign_message', '未知结果')}）"
    )
    parts = [
        f"QQ {record.get('qq', '')}",
        str(record.get("role", "未知角色")),
        sign_text,
    ]
    gift_text = _format_gift_text(record)
    if gift_text:
        parts.append(gift_text)
    prefix = "⚠️ " if issue else ""
    return f"- {prefix}{' · '.join(parts)}"


def _format_user_overview(row: dict[str, Any]) -> str:
    gift_counts = (
        row.get("gift_counts") if isinstance(row.get("gift_counts"), dict) else {}
    )
    attempted = any(
        int(gift_counts.get(state, 0) or 0) > 0
        for state in ("success", "partial", "failed", "none")
    )
    parts = [
        f"QQ {row.get('qq', '')}",
        f"签到 {int(row.get('success_count', 0) or 0)}/{int(row.get('account_count', 0) or 0)}",
    ]
    already_claimed = int(row.get("already_claimed_count", 0) or 0)
    if already_claimed > 0:
        parts.append(f"已领取 {already_claimed}")
    if attempted:
        parts.append(
            "礼包 "
            f"{int(gift_counts.get('success', 0) or 0)}/"
            f"{int(gift_counts.get('partial', 0) or 0)}/"
            f"{int(gift_counts.get('failed', 0) or 0)}/"
            f"{int(gift_counts.get('none', 0) or 0)}"
        )
    elif int(gift_counts.get("off", 0) or 0) > 0:
        parts.append("礼包 已关闭")
    return f"- {' · '.join(parts)}"


def _format_stats(stats: dict[str, Any]) -> list[str]:
    total_users = max(0, int(stats.get("total_users", 0) or 0))
    success_users = max(0, int(stats.get("success_users", 0) or 0))
    already_claimed_users = max(0, int(stats.get("already_claimed_users", 0) or 0))
    failed_users = max(0, int(stats.get("failed_users", 0) or 0))
    total_accounts = max(0, int(stats.get("total_accounts", 0) or 0))
    success_accounts = max(0, int(stats.get("success_accounts", 0) or 0))
    already_claimed_accounts = max(
        0, int(stats.get("already_claimed_accounts", 0) or 0)
    )
    failed_accounts = max(0, int(stats.get("failed_accounts", 0) or 0))
    gift_counts = (
        stats.get("gift_counts") if isinstance(stats.get("gift_counts"), dict) else {}
    )
    duration = max(0.0, float(stats.get("duration_seconds", 0) or 0))

    lines = [
        (
            f"- 用户：成功 {success_users} · 已领取 {already_claimed_users} · "
            f"失败 {failed_users} · 共 {total_users}"
        ),
        (
            f"- 账号：成功 {success_accounts} · 已领取 {already_claimed_accounts} · "
            f"失败 {failed_accounts} · 共 {total_accounts}"
        ),
        f"- 签到耗时：{duration:.1f} 秒",
    ]
    gift_total = sum(
        int(gift_counts.get(state, 0) or 0)
        for state in ("success", "partial", "failed", "none")
    )
    if gift_total > 0:
        lines.append(
            "- 礼包："
            f"成功 {int(gift_counts.get('success', 0) or 0)} · "
            f"部分失败 {int(gift_counts.get('partial', 0) or 0)} · "
            f"失败 {int(gift_counts.get('failed', 0) or 0)} · "
            f"无可领 {int(gift_counts.get('none', 0) or 0)}"
        )
    elif int(gift_counts.get("off", 0) or 0) > 0:
        lines.append("- 礼包：已在管理页关闭")
    return lines


def build_signin_summary(
    *,
    records: list[dict[str, Any]],
    users: list[dict[str, Any]],
    stats: dict[str, Any],
    detail_mode: str,
    generated_at: float | None = None,
) -> str:
    mode = (
        detail_mode
        if detail_mode in SUMMARY_DETAIL_MODES
        else DEFAULT_SUMMARY_DETAIL_MODE
    )
    timestamp = float(generated_at if generated_at is not None else time.time())
    run_time = datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M")
    lines = [
        f"# 最强蜗牛定时签到 · {run_time}",
        "",
        "## 运行汇总",
        *_format_stats(stats),
    ]

    issues = sorted(
        (record for record in records if _is_issue(record)), key=_issue_sort_key
    )
    lines.extend(["", "## 需要处理"])
    if issues:
        lines.extend(format_role_record(record, issue=True) for record in issues)
    else:
        lines.append("- ✅ 本次没有签到失败、数据异常或礼包异常")

    if mode == "issues_overview":
        lines.extend(
            [
                "",
                "## 用户概览",
                "- 图例：签到成功数/总数 · 礼包成功/部分失败/失败/无可领",
            ]
        )
        lines.extend(_format_user_overview(row) for row in users)
    elif mode == "full":
        lines.extend(["", "## 完整角色明细"])
        if records:
            lines.extend(format_role_record(record) for record in records)
        else:
            lines.append("- 本次没有可展示的角色记录")

    return "\n".join(lines).strip()
