#!/usr/bin/env python3
"""
i18n / Localization module for AI Usage Center (Vietnamese default).
Provides centralized string lookups, locale-aware date/time/number formatters (vi-VN, Asia/Ho_Chi_Minh).
"""

import json
import os
import re
import time
import datetime as dt
from zoneinfo import ZoneInfo
from typing import Any, Dict, Optional, Union

ICT = ZoneInfo("Asia/Ho_Chi_Minh")
LOCALES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "locales")

_TRANSLATIONS: Dict[str, Any] = {}

def load_locale(locale: str = "vi") -> Dict[str, Any]:
    global _TRANSLATIONS
    path = os.path.join(LOCALES_DIR, f"{locale}.json")
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                _TRANSLATIONS = json.load(f)
        except Exception:
            pass
    return _TRANSLATIONS

# Initial load
load_locale("vi")

def t(key: str, default: Optional[str] = None, **kwargs) -> str:
    """Lookup a translation string using dot-notation, e.g. t('nav.overview')."""
    parts = key.split(".")
    val = _TRANSLATIONS
    for p in parts:
        if isinstance(val, dict) and p in val:
            val = val[p]
        else:
            return default if default is not None else key
    if isinstance(val, str):
        if kwargs:
            try:
                return val.format(**kwargs)
            except Exception:
                return val
        return val
    return str(val)

# ---------------------------------------------------------------------------
# Number & Percentage formatters (Vietnamese locale style)
# ---------------------------------------------------------------------------

def fmt_number(n: Union[int, float, None]) -> str:
    """Format number with dot thousand separators, e.g. 1248 -> 1.248, 3000000 -> 3.000.000"""
    if n is None:
        return "—"
    try:
        int_n = int(round(n))
        return f"{int_n:,}".replace(",", ".")
    except (ValueError, TypeError):
        return str(n)

def fmt_pct(p: Union[int, float, None], decimals: int = 0) -> str:
    """Format percentage, e.g. 8.35 -> 8% or 8,35%"""
    if p is None:
        return "—"
    try:
        val = float(p)
        if decimals == 0:
            return f"{round(val):.0f}%"
        s = f"{val:.{decimals}f}".replace(".", ",")
        return f"{s}%"
    except (ValueError, TypeError):
        return "—"

def fmt_units(v: Union[int, float, None], short: bool = False) -> str:
    """Format unit count in natural Vietnamese, e.g. 3000000 -> 3,0 tr đơn vị or 3.000.000 đơn vị"""
    if v is None:
        return "—"
    try:
        val = float(v)
        if short:
            if val >= 1_000_000:
                s = f"{val / 1_000_000:.1f}".replace(".", ",")
                return f"{s} tr đơn vị"
            if val >= 1_000:
                s = f"{val / 1_000:.0f}".replace(".", ",")
                return f"{s} nghìn đơn vị"
            return f"{int(val)} đơn vị"
        return f"{fmt_number(val)} đơn vị"
    except (ValueError, TypeError):
        return str(v)

def fmt_duration(ms: Union[int, float, None]) -> str:
    """Format runtime in milliseconds to natural Vietnamese, e.g. 134000 -> 2 phút 14 giây"""
    if ms is None or ms < 0:
        return "—"
    secs = int(ms) // 1000
    if secs < 1:
        return f"{ms} ms" if ms > 0 else "0 giây"
    if secs < 60:
        return f"{secs} giây"
    mins = secs // 60
    rem_secs = secs % 60
    if mins < 60:
        return f"{mins} phút {rem_secs} giây" if rem_secs else f"{mins} phút"
    hours = mins // 60
    rem_mins = mins % 60
    return f"{hours} giờ {rem_mins} phút"

# ---------------------------------------------------------------------------
# Date & Time formatters (Asia/Ho_Chi_Minh timezone)
# ---------------------------------------------------------------------------

def ts_to_dt(ts: Union[int, float, None]) -> Optional[dt.datetime]:
    if not ts:
        return None
    try:
        return dt.datetime.fromtimestamp(int(ts), ICT)
    except Exception:
        return None

def fmt_date(ts: Union[int, float, None]) -> str:
    """Format date as DD/MM/YYYY, e.g. 09/09/2026"""
    d = ts_to_dt(ts)
    return d.strftime("%d/%m/%Y") if d else "—"

def fmt_time(ts: Union[int, float, None]) -> str:
    """Format time as HH:MM, e.g. 14:32"""
    d = ts_to_dt(ts)
    return d.strftime("%H:%M") if d else "—"

def fmt_datetime(ts: Union[int, float, None]) -> str:
    """Format datetime as DD/MM/YYYY · HH:MM, e.g. 09/09/2026 · 14:32"""
    d = ts_to_dt(ts)
    return d.strftime("%d/%m/%Y · %H:%M") if d else "—"

# ---------------------------------------------------------------------------
# Semantic status & enum mappings
# ---------------------------------------------------------------------------

STATUS_MAP = {
    "completed": ("Hoàn tất", "#16a34a", "#f0fdf4", "#bbf7d0"),
    "running": ("Đang chạy", "#2563eb", "#eff6ff", "#bfdbfe"),
    "failed": ("Thất bại", "#dc2626", "#fef2f2", "#fecaca"),
    "timeout": ("Quá thời gian", "#d97706", "#fffbeb", "#fde68a"),
    "cancelled": ("Đã hủy", "#64748b", "#f8fafc", "#e2e8f0"),
    "duplicate": ("Trùng lặp", "#64748b", "#f8fafc", "#e2e8f0"),
    "no_ai": ("Không dùng AI", "#16a34a", "#f0fdf4", "#bbf7d0"),
}

THRESHOLD_MAP = {
    None: ("Bình thường", "#16a34a", "#f0fdf4", "#bbf7d0"),
    "normal": ("Bình thường", "#16a34a", "#f0fdf4", "#bbf7d0"),
    "warning": ("Cảnh báo", "#d97706", "#fffbeb", "#fde68a"),
    "high": ("Mức cao", "#ea580c", "#fff7ed", "#fed7aa"),
    "critical": ("Rất cao", "#dc2626", "#fef2f2", "#fecaca"),
    "exhausted": ("Đã hết hạn mức", "#dc2626", "#fef2f2", "#fecaca"),
}

SEVERITY_MAP = {
    "Normal": ("Bình thường", "#16a34a", "#f0fdf4", "#bbf7d0"),
    "Unusual": ("Bất thường", "#d97706", "#fffbeb", "#fde68a"),
    "High Usage": ("Sử dụng cao", "#ea580c", "#fff7ed", "#fed7aa"),
    "Critical": ("Nghiêm trọng", "#dc2626", "#fef2f2", "#fecaca"),
}

ANOMALY_KIND_MAP = {
    "USAGE_SPIKE": "Mức sử dụng tăng đột biến",
    "CAPACITY_DROP": "Dung lượng AGY giảm nhanh",
    "CAPACITY_LOW": "Dung lượng AGY mức thấp",
    "HIGH_FAILURES": "Tỷ lệ lỗi cao",
    "CONCURRENCY_SPIKE": "Yêu cầu đồng thời cao",
    "QUALITY_DROP": "Độ tin cậy dữ liệu giảm",
}

READINESS_STATUS_MAP = {
    "PASS": ("ĐẠT", "#16a34a", "#f0fdf4", "#bbf7d0"),
    "NOT MET": ("CHƯA ĐẠT", "#dc2626", "#fef2f2", "#fecaca"),
    "UNPROVEN": ("CHƯA KIỂM CHỨNG", "#d97706", "#fffbeb", "#fde68a"),
    "PARTIAL": ("MỘT PHẦN", "#d97706", "#fffbeb", "#fde68a"),
    "TESTED OFFLINE": ("THỬ NGHIỆM OFFLINE", "#2563eb", "#eff6ff", "#bfdbfe"),
    "NOT DESIGNED": ("CHƯA THIẾT KẾ", "#dc2626", "#fef2f2", "#fecaca"),
}

READINESS_ITEM_MAP = {
    "Trusted user identity": "Định danh người dùng đáng tin cậy",
    "Trusted channel identity": "Định danh kênh đáng tin cậy",
    "Duplicate-safe accounting": "Kế toán an toàn chống trùng lặp",
    "Sufficient observation history": "Đủ lịch sử quan sát thực tế",
    "Sufficient measurement quality": "Độ phủ dữ liệu đo lường đầy đủ",
    "Concurrent reservation mechanism tested": "Cơ chế giữ chỗ đồng thời đã thử nghiệm",
    "Restart safety tested": "An toàn khi khởi động lại dịch vụ",
    "Warning thresholds tested": "Đã kiểm thử các ngưỡng cảnh báo",
    "Owner override mechanism designed": "Cơ chế can thiệp thủ công của chủ sở hữu",
    "Provider capacity behavior understood": "Hành vi dung lượng nhà cung cấp được nắm rõ",
}

CONFIDENCE_MAP = {
    "INSUFFICIENT": ("CHƯA ĐỦ DỮ LIỆU", "#64748b", "#f8fafc", "#e2e8f0"),
    "LOW": ("THẤP", "#d97706", "#fffbeb", "#fde68a"),
    "MEDIUM": ("TRUNG BÌNH", "#2563eb", "#eff6ff", "#bfdbfe"),
    "HIGH": ("CAO", "#16a34a", "#f0fdf4", "#bbf7d0"),
    "MEDIUM/HIGH": ("TRUNG BÌNH / CAO", "#2563eb", "#eff6ff", "#bfdbfe"),
}

PROFILE_LABEL_MAP = {
    "full": "Toàn phần",
    "high": "Cao",
    "standard": "Tiêu chuẩn",
    "limited": "Giới hạn",
}

def translate_status(status: Optional[str]):
    return STATUS_MAP.get(status, (status or "Chưa xác định", "#64748b", "#f8fafc", "#e2e8f0"))

def translate_threshold(th: Optional[str]):
    return THRESHOLD_MAP.get(th, THRESHOLD_MAP[None])

def translate_severity(sev: Optional[str]):
    return SEVERITY_MAP.get(sev, (sev or "Thông tin", "#64748b", "#f8fafc", "#e2e8f0"))

def translate_anomaly_kind(kind: Optional[str]) -> str:
    return ANOMALY_KIND_MAP.get(kind, kind or "Cảnh báo hệ thống")

def translate_readiness_status(status: Optional[str]):
    return READINESS_STATUS_MAP.get(status, (status or "CHƯA XÁC ĐỊNH", "#64748b", "#f8fafc", "#e2e8f0"))

def translate_readiness_item(item: str) -> str:
    return READINESS_ITEM_MAP.get(item, item)

def translate_confidence(level: Optional[str]):
    return CONFIDENCE_MAP.get(level, CONFIDENCE_MAP["INSUFFICIENT"])

def translate_profile(p: Optional[str]) -> str:
    return PROFILE_LABEL_MAP.get(p, p or "Toàn phần")

def translate_reason(r: str) -> str:
    """Translate common technical reason strings into natural Vietnamese."""
    if not r:
        return ""
    if "AI requests ran concurrently" in r:
        m = re.search(r"(\d+)\s+AI requests ran concurrently", r)
        count = m.group(1) if m else "Nhiều"
        return f"Đã có {count} yêu cầu AI chạy đồng thời tại một thời điểm."
    if "More than 10 requests in a single hour" in r:
        return "Hơn 10 yêu cầu trong vòng 1 giờ."
    if "only" in r and "completed AI requests" in r:
        m = re.search(r"only\s+(\d+)\s+completed AI requests over\s+([\d\.]+)\s+days", r)
        if m:
            reqs, days = m.group(1), m.group(2).replace(".", ",")
            return f"Chỉ có {reqs} yêu cầu AI hoàn tất trong {days} ngày — chưa đủ lịch sử để đánh giá có ý nghĩa thống kê."
        return r.replace("only", "Chỉ có").replace("completed AI requests over", "yêu cầu AI hoàn tất trong").replace("days — too little history for a statistically meaningful assessment", "ngày — chưa đủ lịch sử để đánh giá có ý nghĩa thống kê.")
    return r

def translate_evidence(ev: str) -> str:
    """Translate readiness evidence strings into natural Vietnamese."""
    if not ev:
        return "—"
    if "recorded requests carry a relay-verified sender pubkey" in ev:
        m = re.search(r"(\d+/\d+)", ev)
        ratio = m.group(1) if m else "Tất cả"
        return f"{ratio} yêu cầu đã ghi nhận đều mang khóa công khai (pubkey) người gửi đã được relay xác thực"
    if "channel cross-checked against the signed trigger event" in ev:
        return "Đã đối chiếu kênh dựa trên sự kiện kích hoạt có chữ ký số hợp lệ"
    if "uniqueness via PK constraint" in ev:
        return "Đảm bảo tính duy nhất qua ràng buộc khóa chính; tin nhắn trùng lặp phát lại câu trả lời trong bộ nhớ đệm và ghi trạng thái 'trùng lặp' (không tính phí) — đã chứng minh qua kiểm thử"
    if "days observed" in ev and "completed requests" in ev:
        m = re.search(r"([\d\.]+)\s+days observed,\s+(\d+)\s+completed requests", ev)
        if m:
            days, reqs = m.group(1).replace(".", ","), m.group(2)
            return f"Đã quan sát {days} ngày, {reqs} yêu cầu hoàn tất → độ tin cậy: CHƯA ĐỦ DỮ LIỆU"
        return ev.replace("days observed", "ngày quan sát").replace("completed requests", "yêu cầu hoàn tất").replace("confidence INSUFFICIENT", "độ tin cậy: CHƯA ĐỦ DỮ LIỆU")
    if "actual usage coverage" in ev:
        m = re.search(r"([\d\.]+)%\s+\((\d+)\s+actual,\s+(\d+)\s+unknown requests\)", ev)
        if m:
            cov, act, unk = m.group(1).replace(".", ","), m.group(2), m.group(3)
            return f"Độ phủ dữ liệu sử dụng thực tế đạt {cov}% ({act} thực tế, {unk} chưa xác định)"
        return ev.replace("actual usage coverage", "Độ phủ dữ liệu thực tế").replace("actual", "thực tế").replace("unknown requests", "yêu cầu chưa xác định")
    if "reserve/settle/release/expiry paths verified offline" in ev:
        return "Các luồng giữ chỗ/quyết toán/giải phóng/hết hạn đã xác minh ngoại tuyến; chưa có giữ chỗ thực tế nào trong môi trường production"
    if "dashboard + poller restarts verified live" in ev:
        return "Khởi động lại dashboard và poller đã xác minh trực tiếp với lịch sử được bảo toàn; chu kỳ khởi động lại toàn bộ gateway chưa thực hiện trong production"
    if "all four thresholds verified once-each in the offline harness" in ev:
        return "Cả 4 ngưỡng cảnh báo đã kiểm thử thành công trong môi trường offline; chưa có lượt vượt ngưỡng nào trong production (mức dùng hiện dưới 70%)"
    if "manual owner allow/deny override for a hard-limit block is not yet designed" in ev:
        return "Cơ chế can thiệp thủ công (cho phép/chặn) của chủ sở hữu khi chạm giới hạn cứng chưa được thiết kế — bắt buộc trước khi bật cưỡng chế"
    if "agy-quota snapshots flow" in ev:
        return "Dữ liệu snapshot từ agy-quota đang ghi nhận liên tục (poller hoạt động); hành vi suy giảm dung lượng qua nhiều tuần chưa quan sát đủ"
    return ev

def translate_dry_run_note(note: str) -> str:
    if "Dry run only" in note:
        return "Chỉ là mô phỏng: tất cả các yêu cầu thực tế đều được cho phép trong hệ thống. Đánh giá này cho biết giới hạn tự động SẼ xử lý như thế nào nếu được bật."
    return note
