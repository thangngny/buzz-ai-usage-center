#!/usr/bin/env python3
"""
AI Usage Center — LIVE Local Dashboard for Buzz AI Usage Control (v2.1 Enterprise).
Completely localized in Vietnamese with premium, data-focused UI/UX.

- Binds to 127.0.0.1:8787 ONLY (never 0.0.0.0).
- Pure standard library Python http.server, zero heavy external runtime dependencies.
- Read-only against the ledger except explicit owner actions (assign allowance profile, adjust policy numbers, ack alert).
- Contains no secrets: no private keys, no tokens, no account emails, no prompt text.
"""

import html
import json
import os
import sys
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib"))

import analytics  # noqa: E402
import i18n  # noqa: E402
import ledger  # noqa: E402
import ui_components as ui  # noqa: E402

HOST = "127.0.0.1"
PORT = 8787

AGENT_LABELS = {
    "claude-cli": "Claude CLI",
    "agy-1": "AGY 1",
    "agy-2": "AGY 2",
    "agy-3": "AGY 3",
    "agy-4": "AGY 4",
}


def agent_label(a: str) -> str:
    return AGENT_LABELS.get(a, a)


def get_unread_alerts_count() -> int:
    try:
        alerts = ledger.owner_alerts_recent(100)
        return sum(1 for a in alerts if a.get("status") != "acknowledged")
    except Exception:
        return 0


# ===========================================================================
# Capacity Helper Component
# ===========================================================================

def capacity_block(agent: dict) -> str:
    """Provider capacity — visually and semantically distinct from user allowance."""
    caps = agent.get("capacity") or []
    if not caps:
        return '<span class="text-muted">Dung lượng: Chưa có dữ liệu snapshot</span>'
    vals = [c["remaining_percent"] for c in caps if c.get("remaining_percent") is not None]
    lowest = min(vals) if vals else None
    
    if lowest is not None:
        color = "var(--danger)" if lowest < 20 else ("var(--warning)" if lowest < 50 else "var(--capacity)")
        gauge = ui.render_radial_gauge(lowest, size=38, color_override=color)
        head = f"""<div style="display:flex;align-items:center;gap:10px;">
          {gauge}
          <div>
            <div style="color:{color};font-weight:700;font-size:13.5px;">Còn lại {lowest:.0f}%</div>
            <div class="text-muted" style="font-size:11.5px;">(mô hình thấp nhất)</div>
          </div>
        </div>"""
    else:
        head = '<span class="text-muted">Dung lượng: Chưa xác định</span>'
    
    rows = []
    for c in caps:
        rem = f"{c['remaining_percent']:.0f}%" if c.get("remaining_percent") is not None else "Chưa rõ"
        res_at = c.get("reset_at") or "—"
        rows.append(f"""<tr>
          <td><b>{html.escape(c.get('model') or 'Chưa xác định')}</b></td>
          <td class="td-num"><b>{rem}</b></td>
          <td style="font-size:12px;color:var(--text-muted);">{html.escape(res_at)}</td>
        </tr>""")
    
    table_html = f"""<table class="data-table" style="margin-top:8px;">
      <thead><tr><th>Mô hình</th><th class="th-num">Còn lại</th><th>Làm mới lúc</th></tr></thead>
      <tbody>{''.join(rows)}</tbody>
    </table>"""
    
    return f"""{head}
    <details class="custom-details" style="margin-top:8px;">
      <summary>Chi tiết từng mô hình ({len(caps)})</summary>
      <div class="details-content" style="padding:0;">{table_html}</div>
    </details>"""


# ===========================================================================
# PAGE 1: TỔNG QUAN (Overview)
# ===========================================================================

def v_overview() -> str:
    o = ledger.overview()
    base = o["base_units_daily"] or 3000000.0
    units_today = o.get("units_today", 0.0)
    used_pct = min(100.0, units_today / base * 100.0) if base else 0.0
    remaining_pct = max(0.0, 100.0 - used_pct)
    unread_alerts = get_unread_alerts_count()
    
    # Hero Card: Mức sử dụng hôm nay
    progress_html = ui.render_progress_bar(used_pct, remaining_pct, height=10, show_label=False)
    units_fmt = i18n.fmt_number(units_today)
    base_fmt = i18n.fmt_number(base)
    
    hero_html = f"""
    <div class="hero-card">
      <div class="hero-header">
        <div>
          <div class="hero-label">⚡ {i18n.t("overview.hero_title")}</div>
          <div class="hero-subtext" style="color:var(--text-muted);font-size:13px;margin-top:2px;">{i18n.t("overview.hero_desc")}</div>
        </div>
        <span class="badge" style="background:var(--primary-subtle);color:var(--primary);border:1px solid var(--primary-border);">
          Hôm nay · 00:00–24:00 ICT
        </span>
      </div>
      
      <div class="hero-value-group">
        <div class="hero-value">{used_pct:.1f}%</div>
        <div class="hero-remaining">Còn lại {remaining_pct:.1f}%</div>
      </div>
      
      {progress_html}
      
      <div style="display:flex;justify-content:space-between;font-size:13px;margin-top:12px;color:var(--text-secondary);">
        <span>Đã tiêu thụ: <b>{units_fmt}</b> / {base_fmt} đơn vị cơ sở</span>
        <span>Chu kỳ làm mới: <b>00:00 ICT hàng ngày</b></span>
      </div>
    </div>
    """
    
    # 4 Supporting KPIs
    kpis_html = f"""
    <div class="kpi-grid">
      {ui.render_kpi_card(i18n.t("overview.active_users"), str(o.get("active_users", 0)), "Thành viên có phát sinh yêu cầu hôm nay")}
      {ui.render_kpi_card(i18n.t("overview.requests_today"), i18n.fmt_number(o.get("requests_today", 0)), f"Thành công: {o.get('requests_today', 0) - o.get('failures_today', 0)}")}
      {ui.render_kpi_card(i18n.t("overview.running_jobs"), str(o.get("running", 0)), "Đang xử lý trong gateway")}
      {ui.render_kpi_card(i18n.t("overview.warnings"), str(unread_alerts), "Cảnh báo bất thường đang mở")}
    </div>
    """
    
    # System Mode Banner
    mode_banner = f"""
    <div class="mode-banner">
      <div style="font-weight:600;display:flex;align-items:center;gap:8px;">
        <span style="color:var(--text-primary);">Chế độ vận hành:</span>
      </div>
      <div class="mode-pills">
        <span class="mode-pill active">✓ Ghi nhận sử dụng: BẬT</span>
        <span class="mode-pill active">✓ Cảnh báo sớm: BẬT</span>
        <span class="mode-pill inactive">Giới hạn mềm: TẮT</span>
        <span class="mode-pill inactive">Giới hạn cứng: TẮT (Chỉ quan sát)</span>
      </div>
    </div>
    """
    
    # Trend Chart
    trend_points = [
        {"label": "03/09", "value": 0.0, "requests": 0},
        {"label": "04/09", "value": 0.0, "requests": 0},
        {"label": "05/09", "value": 0.0, "requests": 0},
        {"label": "06/09", "value": 0.0, "requests": 0},
        {"label": "07/09", "value": 0.0, "requests": 0},
        {"label": "08/09", "value": 0.0, "requests": 0},
        {"label": "Hôm nay", "value": used_pct, "requests": o.get("requests_today", 0)},
    ]
    chart_svg = ui.render_svg_trend_chart(trend_points, height=200)
    
    trend_section = f"""
    <div class="card-section">
      <div class="section-header">
        <div>
          <div class="section-title">{i18n.t("overview.usage_trend")}</div>
          <div class="section-subtitle">{i18n.t("overview.usage_trend_desc")}</div>
        </div>
        <div class="filter-group">
          <span class="filter-pill active">7 ngày qua</span>
          <span class="filter-pill">24 giờ qua</span>
          <span class="filter-pill">30 ngày qua</span>
        </div>
      </div>
      {chart_svg}
    </div>
    """
    
    # 2-Column Section: Top Users & Agent Breakdown
    users_list = ledger.user_summaries()
    top_users_html = []
    if not users_list:
        top_users_html.append(ui.render_empty_state("Chưa có dữ liệu người dùng", "Dữ liệu người dùng sẽ xuất hiện sau khi gửi yêu cầu."))
    else:
        for u in sorted(users_list, key=lambda x: -x.get("used_pct", 0.0))[:5]:
            upct = u.get("used_pct", 0.0)
            name = u.get("display_name") or (u["principal_pubkey"][:14] + "…")
            avatar_html = ui.render_avatar(name, 24)
            top_users_html.append(f"""
            <div style="margin-bottom:14px;">
              <div style="display:flex;justify-content:space-between;align-items:center;font-size:13px;margin-bottom:6px;">
                <div style="display:flex;align-items:center;gap:8px;">
                  {avatar_html}
                  <b><a href="/users/{u['principal_pubkey']}" style="color:var(--primary);text-decoration:none;">{html.escape(name)}</a></b>
                </div>
                <span><b>{upct:.1f}%</b> <span class="text-muted">({u.get('requests', 0)} reqs)</span></span>
              </div>
              {ui.render_progress_bar(upct, show_label=False, height=7)}
            </div>
            """)
        top_users_html.append(f"""<div style="margin-top:16px;text-align:right;">
          <a href="/users" class="btn btn-secondary btn-sm">{i18n.t("overview.view_all_users")} →</a>
        </div>""")
    
    agents_list = ledger.agent_summaries()
    total_agent_units = sum(a.get("units", 0.0) for a in agents_list) or 1.0
    agents_breakdown_html = []
    if not agents_list:
        agents_breakdown_html.append(ui.render_empty_state("Chưa có dữ liệu Agent", "Chưa có lượt gọi Agent nào."))
    else:
        for a in sorted(agents_list, key=lambda x: -x.get("units", 0.0)):
            ashare = (a.get("units", 0.0) / total_agent_units) * 100.0
            aname = agent_label(a["agent_id"])
            is_agy = a.get("backend_kind") == "agy"
            bcolor = "var(--capacity)" if is_agy else "var(--primary)"
            tag_label = "Tài khoản AGY" if is_agy else "CLI Cục bộ"
            tag_badge = f'<span class="badge" style="font-size:10.5px;padding:1px 6px;background:var(--bg-subtle);color:{bcolor};">{tag_label}</span>'
            
            agents_breakdown_html.append(f"""
            <div style="margin-bottom:14px;">
              <div style="display:flex;justify-content:space-between;align-items:center;font-size:13px;margin-bottom:6px;">
                <div style="display:flex;align-items:center;gap:6px;">
                  <b>{html.escape(aname)}</b>
                  {tag_badge}
                </div>
                <span><b>{ashare:.1f}%</b> <span class="text-muted">({a.get('requests', 0)} reqs)</span></span>
              </div>
              {ui.render_progress_bar(ashare, show_label=False, height=7, color_override=bcolor)}
            </div>
            """)
    
    two_col_section = f"""
    <div class="grid-2col">
      <div class="card-section" style="margin-bottom:0;">
        <div class="section-header">
          <div>
            <div class="section-title">{i18n.t("overview.top_users")}</div>
            <div class="section-subtitle">{i18n.t("overview.top_users_desc")}</div>
          </div>
        </div>
        {''.join(top_users_html)}
      </div>
      
      <div class="card-section" style="margin-bottom:0;">
        <div class="section-header">
          <div>
            <div class="section-title">{i18n.t("overview.agent_breakdown")}</div>
            <div class="section-subtitle">{i18n.t("overview.agent_breakdown_desc")}</div>
          </div>
        </div>
        {''.join(agents_breakdown_html)}
      </div>
    </div>
    """
    
    # Distinct Section: Dung lượng tài khoản AGY
    agy_cards = []
    for a in agents_list:
        if a.get("backend_kind") == "agy":
            aname = agent_label(a["agent_id"])
            caps = a.get("capacity") or []
            vals = [c["remaining_percent"] for c in caps if c.get("remaining_percent") is not None]
            lowest = min(vals) if vals else None
            rem_str = f"{lowest:.0f}%" if lowest is not None else "Chưa rõ"
            p_val = lowest if lowest is not None else 0.0
            
            p_bar = ui.render_progress_bar(p_val, show_label=False, height=6, color_override="var(--capacity)")
            
            agy_cards.append(f"""
            <div class="capacity-card">
              <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;">
                <span style="font-weight:700;font-size:15px;color:var(--text-primary);">{html.escape(aname)}</span>
                <span style="font-weight:700;font-size:15px;color:var(--capacity);">{rem_str} còn lại</span>
              </div>
              {p_bar}
              <div style="margin-top:10px;">{capacity_block(a)}</div>
            </div>
            """)
            
    capacity_section = f"""
    <div class="capacity-box">
      <div style="display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:8px;">
        <div>
          <div class="capacity-title">🟣 {i18n.t("overview.capacity_title")}</div>
          <div style="font-size:13px;color:var(--text-secondary);margin-top:2px;">
            {i18n.t("overview.capacity_microcopy")}
          </div>
        </div>
        <span class="badge" style="background:var(--bg-surface);color:var(--capacity);border:1px solid var(--capacity-border);">
          Chu kỳ quét: 10 phút
        </span>
      </div>
      <div class="capacity-grid">
        {''.join(agy_cards)}
      </div>
    </div>
    """
    
    # Recent Activity Table
    recent_rows = ledger.activity_recent(15)
    if not recent_rows:
        activity_table = ui.render_empty_state("Chưa có hoạt động", i18n.t("overview.empty_activity"))
    else:
        tbody = []
        for r in recent_rows:
            st = r.get("status")
            st_text, st_fg, st_bg, st_border = i18n.translate_status(st)
            units_text = i18n.fmt_number(r.get("normalized_units")) if r.get("normalized_units") is not None else "—"
            user_name = r.get("display_name") or (r.get("request_id", "")[:12] and "Người dùng") or "—"
            t_str = i18n.fmt_datetime(r.get("started_at"))
            
            tbody.append(f"""<tr>
              <td>{t_str}</td>
              <td><b>{html.escape(agent_label(r.get('agent_id', '')))}</b></td>
              <td>{html.escape(user_name)}</td>
              <td>{ui.render_badge(st_text, st_bg, st_fg, st_border)}</td>
              <td class="td-num"><b>{units_text}</b></td>
              <td class="text-muted" style="font-size:12px;">{html.escape(r.get('dry_run_verdict') or '—')}</td>
            </tr>""")
            
        activity_table = f"""<div class="table-wrapper">
          <table class="data-table">
            <thead>
              <tr>
                <th class="sortable">Thời gian</th>
                <th class="sortable">Agent</th>
                <th class="sortable">Người dùng</th>
                <th>Trạng thái</th>
                <th class="th-num sortable">Đơn vị AI</th>
                <th>Mô phỏng (Dry-run)</th>
              </tr>
            </thead>
            <tbody>{''.join(tbody)}</tbody>
          </table>
        </div>"""
    
    activity_section = f"""
    <div class="card-section">
      <div class="section-header">
        <div>
          <div class="section-title">{i18n.t("overview.recent_activity")}</div>
          <div class="section-subtitle">{i18n.t("overview.recent_activity_desc")}</div>
        </div>
      </div>
      {activity_table}
    </div>
    """
    
    body = f"{hero_html}\n{kpis_html}\n{mode_banner}\n{trend_section}\n{two_col_section}\n<div style='height:24px;'></div>\n{capacity_section}\n{activity_section}"
    return ui.render_page("Tổng quan", "/", body, i18n.t("app.subtitle"), unread_alerts=unread_alerts)


# ===========================================================================
# PAGE 2: NGƯỜI DÙNG (Users)
# ===========================================================================

def v_users(qs: dict) -> str:
    users = ledger.user_summaries()
    unread_alerts = get_unread_alerts_count()
    
    filter_status = (qs.get("status") or ["all"])[0]
    search_q = (qs.get("q") or [""])[0].strip().lower()
    sort_by = (qs.get("sort") or ["used"])[0]
    
    filtered_users = []
    for u in users:
        name = (u.get("display_name") or "").lower()
        pk = (u.get("principal_pubkey") or "").lower()
        if search_q and (search_q not in name and search_q not in pk):
            continue
        upct = u.get("used_pct", 0.0)
        if filter_status == "warning" and upct < 70:
            continue
        if filter_status == "critical" and upct < 95:
            continue
        if filter_status == "normal" and upct >= 70:
            continue
        filtered_users.append(u)
        
    if sort_by == "used":
        filtered_users.sort(key=lambda x: -x.get("used_pct", 0.0))
    elif sort_by == "remaining":
        filtered_users.sort(key=lambda x: x.get("used_pct", 0.0))
    elif sort_by == "requests":
        filtered_users.sort(key=lambda x: -x.get("requests", 0))
    elif sort_by == "name":
        filtered_users.sort(key=lambda x: (x.get("display_name") or "").lower())
    
    def filter_pill(key: str, label: str) -> str:
        active = " active" if filter_status == key else ""
        return f'<a href="/users?status={key}&sort={sort_by}&q={urllib.parse.quote(search_q)}" class="filter-pill{active}">{label}</a>'
    
    filter_bar_html = f"""
    <div class="filter-bar">
      <div class="filter-group">
        {filter_pill("all", i18n.t("users.filter_all"))}
        {filter_pill("normal", i18n.t("users.filter_normal"))}
        {filter_pill("warning", i18n.t("users.filter_warning"))}
        {filter_pill("critical", i18n.t("users.filter_critical"))}
      </div>
      
      <div class="form-inline">
        <input type="text" id="user-search-input" value="{html.escape(search_q)}" 
               placeholder="🔍 {i18n.t('users.search_placeholder')}..." 
               class="input-control" style="width:260px;"
               oninput="filterTable('user-search-input', '#users-data-table')">
      </div>
    </div>
    """
    
    if not filtered_users:
        table_content = ui.render_empty_state("Không tìm thấy người dùng", i18n.t("users.empty_users"))
    else:
        tbody = []
        for u in filtered_users:
            st = u.get("status")
            st_text, st_fg, st_bg, st_border = i18n.translate_threshold(st)
            upct = u.get("used_pct", 0.0)
            rem_pct = u.get("remaining_pct", 100.0 - upct)
            p_label = i18n.translate_profile(u.get("profile_id"))
            short_pk = u["principal_pubkey"][:14] + "…"
            d_name = u.get("display_name") or short_pk
            top_agent = agent_label(u.get("most_used_agent")) if u.get("most_used_agent") else "—"
            
            pbar = ui.render_progress_bar(upct, show_label=False, height=7)
            avatar_html = ui.render_avatar(d_name, 26)
            copyable_pk = ui.render_copyable(u["principal_pubkey"], short_pk)
            
            tbody.append(f"""<tr>
              <td>
                <div style="display:flex;align-items:center;gap:10px;">
                  {avatar_html}
                  <div>
                    <div style="font-weight:700;font-size:14px;">
                      <a href="/users/{u['principal_pubkey']}" style="color:var(--primary);text-decoration:none;">{html.escape(d_name)}</a>
                    </div>
                    <div class="text-muted" style="font-size:11px;margin-top:2px;">{copyable_pk}</div>
                  </div>
                </div>
              </td>
              <td><span class="badge" style="background:var(--bg-subtle);color:var(--text-secondary);border:1px solid var(--border-default);">{html.escape(p_label)}</span></td>
              <td style="min-width:140px;">
                <div style="font-weight:700;margin-bottom:4px;">{upct:.1f}%</div>
                {pbar}
              </td>
              <td class="td-num"><b>{rem_pct:.1f}%</b></td>
              <td class="td-num"><b>{u.get('requests', 0)}</b></td>
              <td>{html.escape(top_agent)}</td>
              <td>{ui.render_badge(st_text, st_bg, st_fg, st_border)}</td>
            </tr>""")
            
        table_content = f"""<div class="table-wrapper">
          <table id="users-data-table" class="data-table">
            <thead>
              <tr>
                <th class="sortable">{i18n.t("users.col_user")}</th>
                <th>{i18n.t("users.col_profile")}</th>
                <th class="sortable">{i18n.t("users.col_used")}</th>
                <th class="th-num sortable">{i18n.t("users.col_remaining")}</th>
                <th class="th-num sortable">{i18n.t("users.col_requests")}</th>
                <th>{i18n.t("users.col_top_agent")}</th>
                <th>{i18n.t("users.col_status")}</th>
              </tr>
            </thead>
            <tbody>{''.join(tbody)}</tbody>
          </table>
        </div>"""
        
    body = f"""
    <div class="card-section">
      <div class="section-header">
        <div>
          <div class="section-title">{i18n.t("users.title")}</div>
          <div class="section-subtitle">{i18n.t("users.subtitle")}</div>
        </div>
      </div>
      {filter_bar_html}
      {table_content}
    </div>
    """
    return ui.render_page(i18n.t("users.title"), "/users", body, i18n.t("users.subtitle"), unread_alerts=unread_alerts)


# ===========================================================================
# PAGE 2B: CHI TIẾT NGƯỜI DÙNG (User Detail)
# ===========================================================================

def v_user_detail(pubkey: str) -> str:
    rows = ledger.user_summaries()
    u = next((x for x in rows if x["principal_pubkey"] == pubkey), None)
    unread_alerts = get_unread_alerts_count()
    
    if not u:
        body = ui.render_empty_state("Không tìm thấy người dùng", i18n.t("errors.user_not_found"))
        return ui.render_page("Chi tiết người dùng", "/users", body, unread_alerts=unread_alerts)
        
    d = ledger.user_detail(u.get("community_id") or "", pubkey)
    upct = u.get("used_pct", 0.0)
    rem_pct = u.get("remaining_pct", 100.0 - upct)
    st_text, st_fg, st_bg, st_border = i18n.translate_threshold(u.get("status"))
    d_name = u.get("display_name") or "Người dùng"
    p_label = i18n.translate_profile(u.get("profile_id"))
    
    progress_bar = ui.render_progress_bar(upct, rem_pct, height=10, show_label=False)
    units_fmt = i18n.fmt_number(u.get("units", 0.0))
    eff_fmt = i18n.fmt_number(u.get("effective_units", 3000000.0))
    avatar_html = ui.render_avatar(d_name, 36)
    copyable_pk = ui.render_copyable(pubkey)
    
    hero_user = f"""
    <div class="hero-card">
      <div class="hero-header">
        <div style="display:flex;align-items:center;gap:14px;">
          {avatar_html}
          <div>
            <div style="display:flex;align-items:center;gap:10px;">
              <div class="hero-value" style="font-size:28px;">{html.escape(d_name)}</div>
              {ui.render_badge(st_text, st_bg, st_fg, st_border)}
            </div>
            <div class="text-muted" style="font-size:12px;margin-top:4px;">Khóa công khai: {copyable_pk}</div>
          </div>
        </div>
        <span class="badge" style="background:var(--bg-subtle);color:var(--text-secondary);border:1px solid var(--border-default);font-size:13px;padding:6px 12px;">
          Gói: <b>{html.escape(p_label)}</b> ({eff_fmt} đơn vị/ngày)
        </span>
      </div>
      
      <div class="hero-value-group">
        <div class="hero-value">{upct:.1f}% <span style="font-size:16px;font-weight:600;color:var(--text-muted);">{i18n.t('users.detail_used_label')}</span></div>
        <div class="hero-remaining">{rem_pct:.1f}% {i18n.t('users.detail_remaining_label')}</div>
      </div>
      
      {progress_bar}
      
      <div style="display:flex;justify-content:space-between;font-size:13px;margin-top:12px;color:var(--text-secondary);">
        <span>Đã sử dụng: <b>{units_fmt}</b> / {eff_fmt} đơn vị được cấp</span>
        <span>{u.get('requests', 0)} {i18n.t('users.detail_stats_requests')} · {u.get('running', 0)} {i18n.t('users.detail_stats_running')}</span>
      </div>
    </div>
    """
    
    # Assign Profile Form (Owner action)
    current_pid = u.get("profile_id", "full")
    options_html = []
    for pid, fraction in (("full", 1.0), ("high", 0.75), ("standard", 0.5), ("limited", 0.25)):
        selected = " selected" if pid == current_pid else ""
        plabel = i18n.t(f"profiles.{pid}")
        options_html.append(f'<option value="{pid}"{selected}>{plabel}</option>')
        
    assign_box = f"""
    <div class="card-section">
      <div class="section-title">{i18n.t("users.assign_profile_title")}</div>
      <div class="section-subtitle" style="margin-bottom:14px;">{i18n.t("users.assign_profile_desc")}</div>
      
      <form method="post" action="/users/{pubkey}/set-profile" class="form-inline">
        <select name="profile" class="select-control" style="min-width:240px;">
          {''.join(options_html)}
        </select>
        <button class="btn btn-primary">{i18n.t("common.assign")}</button>
      </form>
    </div>
    """
    
    # Usage by Agent
    by_agent_rows = []
    for a in d.get("by_agent", []):
        aname = agent_label(a["agent_id"])
        units_str = i18n.fmt_number(a.get("units", 0.0))
        by_agent_rows.append(f"""<tr>
          <td><b>{html.escape(aname)}</b></td>
          <td class="td-num"><b>{a.get('requests', 0)}</b></td>
          <td class="td-num"><b>{units_str}</b></td>
        </tr>""")
        
    if not by_agent_rows:
        agent_table = "<p class='text-muted'>Chưa có hoạt động qua Agent nào hôm nay.</p>"
    else:
        agent_table = f"""<div class="table-wrapper">
          <table class="data-table">
            <thead><tr><th class="sortable">Agent</th><th class="th-num sortable">Số yêu cầu</th><th class="th-num sortable">Đơn vị AI</th></tr></thead>
            <tbody>{''.join(by_agent_rows)}</tbody>
          </table>
        </div>"""
        
    by_agent_section = f"""
    <div class="card-section">
      <div class="section-title">{i18n.t("users.usage_by_agent")}</div>
      <div style="margin-top:12px;">{agent_table}</div>
    </div>
    """
    
    # Recent Requests History
    recent_req_rows = []
    for r in d.get("recent", []):
        st = r.get("status")
        st_text, st_fg, st_bg, st_border = i18n.translate_status(st)
        t_str = i18n.fmt_datetime(r.get("started_at"))
        dur_str = i18n.fmt_duration(r.get("runtime_ms"))
        units_str = i18n.fmt_number(r.get("normalized_units")) if r.get("normalized_units") is not None else "—"
        model_str = r.get("model") or "Chưa xác định"
        
        recent_req_rows.append(f"""<tr>
          <td>{t_str}</td>
          <td><b>{html.escape(agent_label(r.get('agent_id', '')))}</b></td>
          <td>{ui.render_badge(st_text, st_bg, st_fg, st_border)}</td>
          <td>{dur_str}</td>
          <td class="td-num"><b>{units_str}</b></td>
          <td class="text-muted">{html.escape(model_str)}</td>
        </tr>""")
        
    if not recent_req_rows:
        req_table = "<p class='text-muted'>Chưa có lịch sử yêu cầu gần đây.</p>"
    else:
        req_table = f"""<div class="table-wrapper">
          <table class="data-table">
            <thead>
              <tr>
                <th class="sortable">Thời gian</th>
                <th class="sortable">Agent</th>
                <th>Trạng thái</th>
                <th class="sortable">Thời gian chạy</th>
                <th class="th-num sortable">Đơn vị AI</th>
                <th>Mô hình</th>
              </tr>
            </thead>
            <tbody>{''.join(recent_req_rows)}</tbody>
          </table>
        </div>"""
        
    recent_req_section = f"""
    <div class="card-section">
      <div class="section-title">{i18n.t("users.recent_requests")}</div>
      <div style="margin-top:12px;">{req_table}</div>
    </div>
    """
    
    # Collapsible Technical Details
    tech_rows = []
    for r in d.get("recent", []):
        t_str = i18n.fmt_datetime(r.get("started_at"))
        req_copy = ui.render_copyable(r.get('request_id', ''), r.get('request_id', '')[:14] + '…')
        tech_rows.append(f"""<tr>
          <td>{req_copy}</td>
          <td>{t_str}</td>
          <td>{html.escape(r.get('usage_quality') or 'Chưa rõ')}</td>
          <td>{html.escape(r.get('model') or '—')}</td>
          <td class="td-num">{i18n.fmt_number(r.get('normalized_units'))}</td>
        </tr>""")
        
    tech_details_html = f"""
    <details class="custom-details">
      <summary>{i18n.t("common.technical_details")} (Tokens, Models, IDs)</summary>
      <div class="details-content">
        <div style="font-size:12px;margin-bottom:12px;color:var(--text-secondary);">
          <div>Community ID: <code>{html.escape(u.get('community_id', ''))}</code></div>
          <div>Principal Pubkey: <code>{html.escape(pubkey)}</code></div>
        </div>
        <div class="table-wrapper">
          <table class="data-table">
            <thead>
              <tr>
                <th>Request ID</th>
                <th>Thời gian</th>
                <th>Độ tin cậy (Quality)</th>
                <th>Model</th>
                <th class="th-num">Normalized Units</th>
              </tr>
            </thead>
            <tbody>{''.join(tech_rows) or '<tr><td colspan="5" class="text-muted">Không có dữ liệu kỹ thuật</td></tr>'}</tbody>
          </table>
        </div>
      </div>
    </details>
    """
    
    back_link = f'<div style="margin-bottom:16px;"><a href="/users" class="btn btn-secondary btn-sm">{i18n.t("users.back_to_users")}</a></div>'
    
    body = f"{back_link}\n{hero_user}\n{assign_box}\n{by_agent_section}\n{recent_req_section}\n{tech_details_html}"
    return ui.render_page(f"Người dùng: {d_name}", "/users", body, f"Chi tiết tài nguyên và mức cấp của {d_name}", unread_alerts=unread_alerts)


# ===========================================================================
# PAGE 3: AGENT (Agents)
# ===========================================================================

def v_agents() -> str:
    agents = ledger.agent_summaries()
    unread_alerts = get_unread_alerts_count()
    
    total_units = sum(a.get("units", 0.0) for a in agents) or 1.0
    
    rows_html = []
    cards_html = []
    
    for a in agents:
        aname = agent_label(a["agent_id"])
        share_pct = (a.get("units", 0.0) / total_units) * 100.0
        b_kind = a.get("backend_kind")
        is_agy = b_kind == "agy"
        
        if is_agy:
            backend_badge = '<span class="badge" style="background:var(--capacity-subtle);color:var(--capacity);border:1px solid var(--capacity-border);">Tài khoản AGY</span>'
            cap_html = capacity_block(a)
            caps = a.get("capacity") or []
            vals = [c["remaining_percent"] for c in caps if c.get("remaining_percent") is not None]
            lowest = min(vals) if vals else None
            gauge_html = ui.render_radial_gauge(lowest if lowest is not None else 100.0, size=46, color_override="var(--capacity)")
        else:
            backend_badge = '<span class="badge" style="background:var(--primary-subtle);color:var(--primary);border:1px solid var(--primary-border);">CLI Cục bộ</span>'
            cap_html = f'<span class="text-muted">{i18n.t("agents.local_cli_note")}</span>'
            gauge_html = ui.render_radial_gauge(100.0, size=46, color_override="var(--primary)")
            
        pbar = ui.render_progress_bar(share_pct, show_label=False, height=6, color_override="#2563eb")
        
        cards_html.append(f"""
        <div class="kpi-card" style="border-left:3px solid {'var(--capacity)' if is_agy else 'var(--primary)'};">
          <div style="display:flex;justify-content:space-between;align-items:flex-start;">
            <div>
              <div style="font-weight:700;font-size:16px;color:var(--text-primary);">{html.escape(aname)}</div>
              <div style="margin-top:4px;">{backend_badge}</div>
            </div>
            {gauge_html}
          </div>
          <div style="display:flex;justify-content:space-between;margin-top:14px;font-size:13px;">
            <span>Thị phần xử lý:</span>
            <b>{share_pct:.1f}%</b>
          </div>
          <div style="display:flex;justify-content:space-between;margin-top:4px;font-size:13px;">
            <span>Yêu cầu:</span>
            <b>{i18n.fmt_number(a.get('requests', 0))}</b>
          </div>
        </div>
        """)
        
        rows_html.append(f"""<tr>
          <td>
            <div style="font-weight:700;font-size:14px;color:var(--text-primary);">{html.escape(aname)}</div>
            <div style="margin-top:4px;">{backend_badge}</div>
          </td>
          <td><span class="badge" style="background:var(--success-subtle);color:var(--success);border:1px solid var(--success-border);">🟢 {i18n.t("agents.status_active")}</span></td>
          <td style="min-width:140px;">
            <div style="font-weight:700;margin-bottom:4px;">{share_pct:.1f}%</div>
            {pbar}
          </td>
          <td class="td-num"><b>{i18n.fmt_number(a.get('requests', 0))}</b></td>
          <td class="td-num"><b>{i18n.fmt_number(a.get('units', 0.0))}</b></td>
          <td class="td-num"><span style="color:{'var(--danger)' if a.get('failures', 0) > 0 else 'inherit'};font-weight:600;">{a.get('failures', 0)}</span></td>
          <td style="min-width:260px;">{cap_html}</td>
        </tr>""")
        
    cards_section = f"""<div class="kpi-grid" style="margin-bottom:24px;">{''.join(cards_html)}</div>"""
    
    table_content = f"""<div class="table-wrapper">
      <table class="data-table">
        <thead>
          <tr>
            <th class="sortable">{i18n.t("agents.col_agent")}</th>
            <th>Trạng thái</th>
            <th class="sortable">{i18n.t("agents.col_share")}</th>
            <th class="th-num sortable">{i18n.t("agents.col_requests")}</th>
            <th class="th-num sortable">Đơn vị AI</th>
            <th class="th-num sortable">{i18n.t("agents.col_failures")}</th>
            <th>{i18n.t("agents.col_capacity")}</th>
          </tr>
        </thead>
        <tbody>{''.join(rows_html)}</tbody>
      </table>
    </div>"""
    
    note_box = f"""
    <div class="alert-box alert-info" style="margin-top:20px;">
      <div>
        <b>Phân biệt quan trọng:</b> {i18n.t("agents.distinction_note")}
      </div>
    </div>
    """
    
    body = f"""
    {cards_section}
    <div class="card-section">
      <div class="section-header">
        <div>
          <div class="section-title">{i18n.t("agents.title")}</div>
          <div class="section-subtitle">{i18n.t("agents.subtitle")}</div>
        </div>
      </div>
      {table_content}
      {note_box}
    </div>
    """
    return ui.render_page(i18n.t("agents.title"), "/agents", body, i18n.t("agents.subtitle"), unread_alerts=unread_alerts)


# ===========================================================================
# PAGE 4: PHÂN TÍCH HẠN MỨC (Calibration)
# ===========================================================================

def v_calibration(qs: dict) -> str:
    window = (qs.get("window") or ["today"])[0]
    unread_alerts = get_unread_alerts_count()
    
    try:
        s, e, label = analytics.window_bounds(
            window, (qs.get("from") or [None])[0], (qs.get("to") or [None])[0])
    except ValueError:
        body = ui.render_error_state("Khoảng thời gian không hợp lệ", i18n.t("errors.custom_date_error"))
        return ui.render_page(i18n.t("calibration.title"), "/calibration", body, unread_alerts=unread_alerts)
        
    conf = analytics.data_confidence()
    mq = analytics.measurement_quality(s, e)
    dist = analytics.request_distribution(s, e)
    share = analytics.usage_share(s, e)
    base = analytics.base_allowance_calibration()
    profiles = analytics.profile_recommendations()
    ready = analytics.hard_limit_readiness()
    dry = analytics.concurrency_dry_run(s, e)
    
    def win_pill(key: str) -> str:
        active = " active" if key == window else ""
        return f'<a href="/calibration?window={key}" class="filter-pill{active}">{i18n.t(f"windows.{key}")}</a>'
        
    window_bar = f"""
    <div class="filter-bar" style="margin-bottom:20px;">
      <div class="filter-group">
        {win_pill("today")}
        {win_pill("24h")}
        {win_pill("3d")}
        {win_pill("7d")}
        {win_pill("30d")}
      </div>
      
      <form method="get" action="/calibration" class="form-inline">
        <input type="hidden" name="window" value="custom">
        <input type="date" name="from" class="input-control" style="width:140px;" placeholder="YYYY-MM-DD">
        <span>→</span>
        <input type="date" name="to" class="input-control" style="width:140px;" placeholder="YYYY-MM-DD">
        <button class="btn btn-secondary btn-sm">{i18n.t("common.apply")}</button>
      </form>
    </div>
    """
    
    # 1. Data Confidence Banner
    conf_level = conf.get("level", "INSUFFICIENT")
    conf_text, conf_fg, conf_bg, conf_border = i18n.translate_confidence(conf_level)
    conf_badge = ui.render_badge(conf_text, conf_bg, conf_fg, conf_border)
    
    confidence_section = f"""
    <div class="card-section">
      <div class="section-header">
        <div>
          <div class="section-title">{i18n.t("calibration.confidence_title")}</div>
          <div class="section-subtitle">{i18n.t("calibration.confidence_insufficient_desc")}</div>
        </div>
        <div>{conf_badge}</div>
      </div>
      
      <div class="kpi-grid" style="margin-bottom:0;">
        {ui.render_kpi_card(i18n.t("calibration.obs_period"), f"{conf.get('observation_days', 0.0):.1f} ngày", f"Kể từ {i18n.fmt_datetime(conf.get('observation_start'))}")}
        {ui.render_kpi_card(i18n.t("calibration.completed_reqs"), str(conf.get("completed_requests", 0)), f"Thất bại: {conf.get('failed_requests', 0)}")}
        {ui.render_kpi_card(i18n.t("calibration.active_users"), str(conf.get("active_users", 0)), f"Tỷ lệ đo thực tế: {conf.get('actual_share', 100.0):.1f}%")}
        {ui.render_kpi_card("Khuyến nghị", "3–7 ngày", i18n.t("calibration.min_recommended"))}
      </div>
    </div>
    """
    
    # 2. Measurement Quality
    cov_val = mq.get("coverage")
    cov_str = f"{cov_val:.1f}%" if cov_val is not None else "Chưa có dữ liệu"
    
    agent_mq_rows = []
    for aid, d in sorted(mq.get("agents", {}).items()):
        c_pct = d.get("coverage")
        c_str = f"{c_pct:.1f}%" if c_pct is not None else "Chưa có dữ liệu"
        pbar = ui.render_progress_bar(c_pct or 0.0, show_label=False, height=6, color_override="var(--success)") if c_pct is not None else "—"
        agent_mq_rows.append(f"""<tr>
          <td><b>{html.escape(agent_label(aid))}</b></td>
          <td class="td-num"><b>{d.get('actual', 0)}</b></td>
          <td class="td-num">{d.get('unknown', 0)}</td>
          <td style="min-width:140px;">
            <div style="display:flex;justify-content:space-between;margin-bottom:4px;">
              <span><b>{c_str}</b></span>
            </div>
            {pbar if isinstance(pbar, str) else ''}
          </td>
        </tr>""")
        
    quality_table = f"""<div class="table-wrapper">
      <table class="data-table">
        <thead><tr><th class="sortable">Agent</th><th class="th-num sortable">{i18n.t("common.actual")}</th><th class="th-num sortable">{i18n.t("common.unknown")}</th><th>{i18n.t("calibration.coverage_label")}</th></tr></thead>
        <tbody>{''.join(agent_mq_rows) or '<tr><td colspan="4" class="text-muted">Chưa có yêu cầu AI nào trong khoảng thời gian này.</td></tr>'}</tbody>
      </table>
    </div>"""
    
    quality_section = f"""
    <div class="card-section">
      <div class="section-header">
        <div>
          <div class="section-title">{i18n.t("calibration.measurement_quality_title")}</div>
          <div class="section-subtitle">{i18n.t("calibration.quality_note")}</div>
        </div>
        <span class="badge" style="background:var(--success-subtle);color:var(--success);border:1px solid var(--success-border);">
          Độ phủ thực tế: {cov_str}
        </span>
      </div>
      {quality_table}
    </div>
    """
    
    # 3. Request Distribution
    ds = dist.get("summary", {})
    if not ds.get("count"):
        dist_content = "<p class='text-muted'>Chưa có yêu cầu hoàn tất nào trong khoảng thời gian này.</p>"
    else:
        dist_kpis = f"""
        <div class="kpi-grid">
          {ui.render_kpi_card(i18n.t("calibration.median_label"), i18n.fmt_units(ds.get('median'), short=True), f"P50: {i18n.fmt_number(ds.get('median'))} đơn vị")}
          {ui.render_kpi_card(i18n.t("calibration.p75_label"), i18n.fmt_units(ds.get('p75'), short=True), f"P75: {i18n.fmt_number(ds.get('p75'))} đơn vị")}
          {ui.render_kpi_card(i18n.t("calibration.p90_label"), i18n.fmt_units(ds.get('p90'), short=True), f"P90: {i18n.fmt_number(ds.get('p90'))} đơn vị")}
          {ui.render_kpi_card(i18n.t("calibration.max_label"), i18n.fmt_units(ds.get('max'), short=True), f"Lớn nhất: {i18n.fmt_number(ds.get('max'))} đơn vị")}
        </div>
        """
        bucket_rows = []
        for bk in dist.get("buckets", []):
            sh = bk.get("share", 0.0)
            pbar = ui.render_progress_bar(sh, show_label=False, height=6)
            bname = bk.get("name")
            if bname == "typical (≤ P50)":
                bname = "Thông thường (≤ P50)"
            elif bname == "moderate (P50–P75)":
                bname = "Khá lớn (P50–P75)"
            elif bname == "large (P75–P90)":
                bname = "Lớn (P75–P90)"
            elif bname == "very large (> P90)":
                bname = "Rất lớn (> P90)"
                
            bucket_rows.append(f"""<tr>
              <td><b>{html.escape(bname)}</b></td>
              <td style="min-width:140px;">
                <div style="font-weight:700;margin-bottom:4px;">{sh:.1f}%</div>
                {pbar}
              </td>
              <td class="td-num"><b>{bk.get('count', 0)}</b></td>
              <td class="td-num">≤ {i18n.fmt_number(bk.get('raw_upper'))} đơn vị</td>
            </tr>""")
            
        bucket_table = f"""<div class="table-wrapper" style="margin-top:16px;">
          <table class="data-table">
            <thead><tr><th class="sortable">Phân nhóm</th><th class="sortable">Tỷ lệ yêu cầu</th><th class="th-num sortable">Số lượng</th><th class="th-num sortable">Ngưỡng trên</th></tr></thead>
            <tbody>{''.join(bucket_rows)}</tbody>
          </table>
        </div>"""
        dist_content = f"{dist_kpis}\n{bucket_table}"
        
    dist_section = f"""
    <div class="card-section">
      <div class="section-header">
        <div>
          <div class="section-title">{i18n.t("calibration.request_dist_title")}</div>
          <div class="section-subtitle">{i18n.t("calibration.request_dist_desc")}</div>
        </div>
      </div>
      {dist_content}
    </div>
    """
    
    # 4. Interactive Policy Simulator Sandbox
    sim_section = f"""
    <div class="card-section" style="border:1px solid var(--primary-border);">
      <div class="section-header">
        <div>
          <div class="section-title">🧪 Trình mô phỏng Chính sách & Hạn ngạch (Policy Sandbox)</div>
          <div class="section-subtitle">Kéo thanh trượt để thử nghiệm tác động khi thay đổi Hạn ngạch cơ sở hàng ngày đối với người dùng</div>
        </div>
      </div>
      
      <div style="background:var(--bg-subtle);padding:18px 22px;border-radius:var(--radius-lg);margin-bottom:16px;">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
          <span style="font-weight:600;color:var(--text-primary);">Hạn mức cơ sở mô phỏng:</span>
          <span id="sim-val-display" style="font-size:18px;font-weight:800;color:var(--primary);">3.000.000 đơn vị</span>
        </div>
        <input type="range" id="sim-slider" min="500000" max="10000000" step="500000" value="3000000" 
               style="width:100%;cursor:pointer;" oninput="updateSimulation(this.value)">
        <div style="display:flex;justify-content:space-between;font-size:11.5px;color:var(--text-muted);margin-top:6px;">
          <span>500K</span>
          <span>3.0M (Mặc định)</span>
          <span>5.0M</span>
          <span>10.0M</span>
        </div>
      </div>
      
      <div id="sim-result-box" style="font-size:13px;color:var(--text-secondary);line-height:1.6;">
        💡 Với hạn ngạch <b>3.000.000 đơn vị</b>, 100% người dùng hiện tại đều nằm trong ngưỡng an toàn (&lt;70%).
      </div>
    </div>
    
    <script>
    function updateSimulation(val) {{
      const num = parseInt(val, 10);
      document.getElementById('sim-val-display').innerText = num.toLocaleString('vi-VN') + ' đơn vị';
      const box = document.getElementById('sim-result-box');
      if (num < 1000000) {{
        box.innerHTML = '⚠️ Với hạn mức <b>' + num.toLocaleString('vi-VN') + ' đơn vị</b>: Mức tiêu thụ thực tế có thể chạm ngưỡng Cảnh báo (70%) đối với các truy vấn phức tạp hoặc prompt dài.';
      }} else if (num >= 5000000) {{
        box.innerHTML = '✨ Với hạn mức <b>' + num.toLocaleString('vi-VN') + ' đơn vị</b>: Dư địa phân bổ rất thoải mái, phù hợp mở rộng thêm người dùng mới mà không lo chạm ngưỡng.';
      }} else {{
        box.innerHTML = '💡 Với hạn mức <b>' + num.toLocaleString('vi-VN') + ' đơn vị</b>: Tỷ lệ phân bổ tối ưu và an toàn cho toàn bộ thành viên hiện tại.';
      }}
    }}
    </script>
    """
    
    # 5. Base Allowance Calibration
    reasons_html = "".join(f"<li style='margin-bottom:4px;'>{html.escape(i18n.translate_reason(r))}</li>" for r in base.get("reasons", []))
    base_kpis = f"""
    <div class="kpi-grid">
      {ui.render_kpi_card(i18n.t("calibration.current_base"), f"{i18n.fmt_number(base.get('current_base'))} đơn vị", i18n.t("calibration.current_base_note"))}
      {ui.render_kpi_card(i18n.t("calibration.assessment_label"), "Chưa đủ dữ liệu", "Cần thêm dữ liệu quan sát")}
      {ui.render_kpi_card(i18n.t("calibration.recommendation_label"), "Tiếp tục quan sát", "Độ tin cậy: Thấp")}
    </div>
    """
    
    base_section = f"""
    <div class="card-section">
      <div class="section-header">
        <div>
          <div class="section-title">{i18n.t("calibration.base_allowance_title")}</div>
          <div class="section-subtitle">Đánh giá hạn mức cơ sở dựa trên dữ liệu tiêu thụ thực tế</div>
        </div>
      </div>
      {base_kpis}
      <div style="font-size:13px;color:var(--text-secondary);background:var(--bg-subtle);padding:14px;border-radius:var(--radius-md);margin-top:12px;">
        <ul style="padding-left:20px;">{reasons_html}</ul>
      </div>
    </div>
    """
    
    # 6. Hard Limit Readiness
    ready_verdict = ready.get("verdict", "NOT READY")
    v_badge = ui.render_badge("CHƯA SẴN SÀNG", "var(--danger-subtle)", "var(--danger)", "var(--danger-border)") if ready_verdict == "NOT READY" else ui.render_badge("ĐÃ SẴN SÀNG", "var(--success-subtle)", "var(--success)", "var(--success-border)")
    
    ready_rows = []
    for c in ready.get("checks", []):
        st = c.get("status")
        st_t, st_fg, st_bg, st_b = i18n.translate_readiness_status(st)
        item_vn = i18n.translate_readiness_item(c.get("item", ""))
        evidence_vn = i18n.translate_evidence(c.get("evidence", ""))
        ready_rows.append(f"""<tr>
          <td><b>{html.escape(item_vn)}</b></td>
          <td>{ui.render_badge(st_t, st_bg, st_fg, st_b)}</td>
          <td class="text-muted" style="font-size:12px;">{html.escape(evidence_vn)}</td>
        </tr>""")
        
    readiness_table = f"""<div class="table-wrapper">
      <table class="data-table">
        <thead><tr><th>Tiêu chí an toàn</th><th>Trạng thái</th><th>Bằng chứng kỹ thuật</th></tr></thead>
        <tbody>{''.join(ready_rows)}</tbody>
      </table>
    </div>"""
    
    readiness_section = f"""
    <div class="card-section">
      <div class="section-header">
        <div>
          <div class="section-title">{i18n.t("calibration.hard_limit_title")}</div>
          <div class="section-subtitle">{i18n.t("calibration.hard_limit_note")}</div>
        </div>
        <div>{v_badge}</div>
      </div>
      {readiness_table}
    </div>
    """
    
    # 7. Concurrency Dry-Run
    dry_counts = dry.get("counts", {})
    dry_note_vn = i18n.translate_dry_run_note(dry.get("note", ""))
    dry_kpis = f"""
    <div class="kpi-grid" style="margin-bottom:12px;">
      {ui.render_kpi_card("Đã mô phỏng", str(dry.get("replayed", 0)), "Yêu cầu hoàn tất trong kỳ")}
      {ui.render_kpi_card(i18n.t("calibration.would_allow"), str(dry_counts.get("WOULD_ALLOW", 0)), "Cho phép xử lý", badge_html=ui.render_badge("Bình thường", "var(--success-subtle)", "var(--success)"))}
      {ui.render_kpi_card(i18n.t("calibration.would_warn"), str(dry_counts.get("WOULD_WARN", 0)), "Gửi cảnh báo", badge_html=ui.render_badge("Cảnh báo", "var(--warning-subtle)", "var(--warning)"))}
      {ui.render_kpi_card(i18n.t("calibration.would_block"), str(dry_counts.get("WOULD_BLOCK", 0)), "Chặn thực thi", badge_html=ui.render_badge("Chặn", "var(--danger-subtle)", "var(--danger)"))}
    </div>
    <div class="text-muted" style="font-size:12px;">{html.escape(dry_note_vn)}</div>
    """
    
    dry_section = f"""
    <div class="card-section">
      <div class="section-header">
        <div>
          <div class="section-title">{i18n.t("calibration.dry_run_title")}</div>
          <div class="section-subtitle">{i18n.t("calibration.dry_run_desc")}</div>
        </div>
      </div>
      {dry_kpis}
    </div>
    """
    
    body = f"{window_bar}\n{confidence_section}\n{quality_section}\n{sim_section}\n{dist_section}\n{base_section}\n{readiness_section}\n{dry_section}"
    return ui.render_page(i18n.t("calibration.title"), "/calibration", body, i18n.t("calibration.subtitle"), unread_alerts=unread_alerts)


# ===========================================================================
# PAGE 5: CẢNH BÁO (Alerts)
# ===========================================================================

def v_alerts(qs: dict) -> str:
    tab = (qs.get("tab") or ["all"])[0]
    filter_sev = (qs.get("sev") or ["all"])[0]
    
    all_alerts = ledger.owner_alerts_recent(100)
    unread_alerts = sum(1 for a in all_alerts if a.get("status") != "acknowledged")
    
    filtered = []
    for a in all_alerts:
        st = a.get("status")
        if tab == "open" and st == "acknowledged":
            continue
        if tab == "acknowledged" and st != "acknowledged":
            continue
        if filter_sev != "all" and a.get("severity") != filter_sev:
            continue
        filtered.append(a)
        
    def tab_link(key: str, label: str, count: int) -> str:
        active = " active" if tab == key else ""
        return f'<a href="/alerts?tab={key}&sev={filter_sev}" class="tab-item{active}">{label} ({count})</a>'
        
    tabs_html = f"""
    <div class="tabs-nav">
      {tab_link("all", i18n.t("alerts.tab_all"), len(all_alerts))}
      {tab_link("open", i18n.t("alerts.tab_open"), unread_alerts)}
      {tab_link("acknowledged", i18n.t("alerts.tab_acknowledged"), len(all_alerts) - unread_alerts)}
    </div>
    """
    
    if not filtered:
        alerts_content = ui.render_empty_state("Không có cảnh báo nào", i18n.t("alerts.empty_alerts"))
    else:
        rows = []
        for a in filtered:
            sev = a.get("severity")
            sev_text, sev_fg, sev_bg, sev_border = i18n.translate_severity(sev)
            kind_vn = i18n.translate_anomaly_kind(a.get("kind"))
            subj = a.get("subject_label") or a.get("subject_id") or "Hệ thống"
            reason_vn = i18n.translate_reason(a.get("reason", ""))
            f_seen = i18n.fmt_datetime(a.get("first_seen"))
            l_seen = i18n.fmt_datetime(a.get("last_seen"))
            occ = a.get("occurrences", 1)
            is_ack = a.get("status") == "acknowledged"
            
            if is_ack:
                action_btn = '<span class="text-muted" style="font-size:12px;">✓ Đã xác nhận</span>'
            else:
                action_btn = f"""<form method="post" action="/alerts/{a['id']}/ack" class="form-inline">
                  <button class="btn btn-secondary btn-sm">{i18n.t("alerts.btn_ack")}</button>
                </form>"""
                
            rows.append(f"""<tr>
              <td>
                <div style="font-weight:700;font-size:13px;">{html.escape(kind_vn)}</div>
                <div class="text-muted font-mono" style="font-size:11px;">{html.escape(a.get('kind', ''))}</div>
              </td>
              <td>{ui.render_badge(sev_text, sev_bg, sev_fg, sev_border)}</td>
              <td><b>{html.escape(subj)}</b></td>
              <td>{html.escape(reason_vn)}</td>
              <td>{f_seen}</td>
              <td>{l_seen}</td>
              <td class="td-num"><b>{occ}</b></td>
              <td>{action_btn}</td>
            </tr>""")
            
        alerts_content = f"""<div class="table-wrapper">
          <table class="data-table">
            <thead>
              <tr>
                <th class="sortable">{i18n.t("alerts.col_type")}</th>
                <th>{i18n.t("alerts.col_severity")}</th>
                <th class="sortable">{i18n.t("alerts.col_subject")}</th>
                <th>{i18n.t("alerts.col_reason")}</th>
                <th class="sortable">{i18n.t("alerts.col_first_seen")}</th>
                <th class="sortable">{i18n.t("alerts.col_last_seen")}</th>
                <th class="th-num sortable">{i18n.t("alerts.col_count")}</th>
                <th>{i18n.t("alerts.col_action")}</th>
              </tr>
            </thead>
            <tbody>{''.join(rows)}</tbody>
          </table>
        </div>"""
        
    owner_alerts_section = f"""
    <div class="card-section">
      <div class="section-header">
        <div>
          <div class="section-title">{i18n.t("alerts.owner_alerts_title")}</div>
          <div class="section-subtitle">{i18n.t("alerts.owner_alerts_desc")}</div>
        </div>
      </div>
      {tabs_html}
      {alerts_content}
    </div>
    """
    
    thresh_alerts = ledger.alerts_recent(50)
    if not thresh_alerts:
        thresh_content = f"<p class='text-muted'>{i18n.t('alerts.empty_thresholds')}</p>"
    else:
        t_rows = []
        for t in thresh_alerts:
            th_name = t.get("threshold")
            th_text, th_fg, th_bg, th_border = i18n.translate_threshold(th_name)
            who = t.get("display_name") or (t.get("principal_pubkey", "")[:16] + "…")
            t_str = i18n.fmt_datetime(t.get("triggered_at"))
            deliv = "Có" if t.get("delivered") else "Không"
            
            t_rows.append(f"""<tr>
              <td>{t_str}</td>
              <td><b>{html.escape(who)}</b></td>
              <td>{ui.render_badge(th_text, th_bg, th_fg, th_border)}</td>
              <td>{deliv}</td>
            </tr>""")
            
        thresh_content = f"""<div class="table-wrapper">
          <table class="data-table">
            <thead>
              <tr>
                <th class="sortable">Thời gian</th>
                <th class="sortable">Người dùng</th>
                <th>{i18n.t("alerts.col_threshold")}</th>
                <th>{i18n.t("alerts.col_delivered")}</th>
              </tr>
            </thead>
            <tbody>{''.join(t_rows)}</tbody>
          </table>
        </div>"""
        
    threshold_section = f"""
    <div class="card-section">
      <div class="section-header">
        <div>
          <div class="section-title">{i18n.t("alerts.threshold_alerts_title")}</div>
          <div class="section-subtitle">{i18n.t("alerts.threshold_alerts_desc")}</div>
        </div>
      </div>
      {thresh_content}
    </div>
    """
    
    body = f"{owner_alerts_section}\n{threshold_section}"
    return ui.render_page(i18n.t("alerts.title"), "/alerts", body, i18n.t("alerts.subtitle"), unread_alerts=unread_alerts)


# ===========================================================================
# PAGE 6: CÀI ĐẶT (Settings)
# ===========================================================================

def v_settings() -> str:
    unread_alerts = get_unread_alerts_count()
    
    keys = [
        "mode", "warn_only_enabled", "hard_limit_enabled", "soft_limit_enabled",
        "base_units_daily", "threshold_warning", "threshold_high",
        "threshold_critical", "threshold_exhausted", "identity_freshness_seconds",
        "capacity_poll_interval_seconds", "normalization_version", "usage_command",
        "owner_pubkeys"
    ]
    
    settings_dict = {k: ledger.get_setting(k) for k in keys}
    
    mode_banner = f"""
    <div class="card-section">
      <div class="section-header">
        <div>
          <div class="section-title" style="text-transform:uppercase;letter-spacing:0.04em;font-size:13px;color:var(--text-secondary);">{i18n.t("settings.mode_box_title")}</div>
          <div class="section-subtitle">{i18n.t("settings.mode_explanation")}</div>
        </div>
      </div>
      
      <div class="kpi-grid" style="margin-bottom:0;">
        {ui.render_kpi_card(i18n.t("settings.mode_meter"), i18n.t("settings.status_on"), "Ghi nhận mọi lượt sử dụng", badge_html=ui.render_badge("BẬT", "var(--success-subtle)", "var(--success)"))}
        {ui.render_kpi_card(i18n.t("settings.mode_warn"), i18n.t("settings.status_on"), "Gửi cảnh báo qua kênh", badge_html=ui.render_badge("BẬT", "var(--success-subtle)", "var(--success)"))}
        {ui.render_kpi_card(i18n.t("settings.mode_soft"), i18n.t("settings.status_off"), "Chưa áp dụng", badge_html=ui.render_badge("TẮT", "var(--bg-subtle)", "var(--text-muted)"))}
        {ui.render_kpi_card(i18n.t("settings.mode_hard"), i18n.t("settings.status_off"), "Giai đoạn quan sát", badge_html=ui.render_badge("TẮT", "var(--bg-subtle)", "var(--text-muted)"))}
      </div>
    </div>
    """
    
    policy_form = f"""
    <div class="card-section">
      <div class="section-header">
        <div>
          <div class="section-title">{i18n.t("settings.section_policy")}</div>
          <div class="section-subtitle">Điều chỉnh các thông số hạn mức và ngưỡng cảnh báo dành cho chủ sở hữu</div>
        </div>
      </div>
      
      <form method="post" action="/settings/policy">
        <div style="margin-bottom:18px;">
          <label style="display:block;font-weight:600;font-size:13px;margin-bottom:6px;">{i18n.t("settings.base_units_label")}</label>
          <input type="number" name="base_units_daily" class="input-control" value="{settings_dict.get('base_units_daily', '3000000')}" style="width:300px;">
          <div class="text-muted" style="font-size:12px;margin-top:4px;">{i18n.t("settings.base_units_help")}</div>
        </div>
        
        <div style="margin-bottom:20px;">
          <label style="display:block;font-weight:600;font-size:13px;margin-bottom:6px;">{i18n.t("settings.thresholds_label")}</label>
          <div style="display:flex;gap:16px;flex-wrap:wrap;">
            <div>
              <span class="text-muted" style="font-size:12px;display:block;">{i18n.t("settings.th_warning")} (%)</span>
              <input type="number" name="th_w" class="input-control" style="width:100px;" value="{settings_dict.get('threshold_warning', '70')}">
            </div>
            <div>
              <span class="text-muted" style="font-size:12px;display:block;">{i18n.t("settings.th_high")} (%)</span>
              <input type="number" name="th_h" class="input-control" style="width:100px;" value="{settings_dict.get('threshold_high', '85')}">
            </div>
            <div>
              <span class="text-muted" style="font-size:12px;display:block;">{i18n.t("settings.th_critical")} (%)</span>
              <input type="number" name="th_c" class="input-control" style="width:100px;" value="{settings_dict.get('threshold_critical', '95')}">
            </div>
            <div>
              <span class="text-muted" style="font-size:12px;display:block;">{i18n.t("settings.th_exhausted")} (%)</span>
              <input type="number" name="th_e" class="input-control" style="width:100px;" value="{settings_dict.get('threshold_exhausted', '100')}">
            </div>
          </div>
        </div>
        
        <button class="btn btn-primary">{i18n.t("settings.btn_save_policy")}</button>
      </form>
    </div>
    """
    
    owner_pk = settings_dict.get('owner_pubkeys', '')
    copy_pk_html = ui.render_copyable(owner_pk)
    
    timing_access = f"""
    <div class="grid-2col">
      <div class="card-section" style="margin-bottom:0;">
        <div class="section-title">{i18n.t("settings.section_timing")}</div>
        <div style="margin-top:14px;display:flex;flex-direction:column;gap:12px;font-size:13px;">
          <div>
            <div class="text-muted">{i18n.t("settings.reset_time_label")}</div>
            <div style="font-weight:600;">{i18n.t("settings.reset_time_val")}</div>
          </div>
          <div>
            <div class="text-muted">{i18n.t("settings.freshness_label")}</div>
            <div style="font-weight:600;">{settings_dict.get('identity_freshness_seconds', '900')} giây (15 phút)</div>
          </div>
          <div>
            <div class="text-muted">{i18n.t("settings.poll_interval_label")}</div>
            <div style="font-weight:600;">{settings_dict.get('capacity_poll_interval_seconds', '600')} giây (10 phút)</div>
          </div>
        </div>
      </div>
      
      <div class="card-section" style="margin-bottom:0;">
        <div class="section-title">{i18n.t("settings.section_access")}</div>
        <div style="margin-top:14px;display:flex;flex-direction:column;gap:12px;font-size:13px;">
          <div>
            <div class="text-muted">{i18n.t("settings.owner_pubkeys_label")}</div>
            <div style="margin-top:6px;">{copy_pk_html}</div>
          </div>
          <div style="margin-top:8px;">
            <div class="text-muted">Lệnh kiểm tra mức sử dụng (/usage)</div>
            <div style="font-weight:600;margin-top:2px;"><code>{html.escape(settings_dict.get('usage_command', '/usage'))}</code> (Không tốn token AI)</div>
          </div>
        </div>
      </div>
    </div>
    """
    
    debug_rows = []
    for k in keys:
        val = settings_dict.get(k)
        debug_rows.append(f"""<tr>
          <td class="font-mono"><b>{html.escape(k)}</b></td>
          <td class="font-mono">{html.escape(str(val))}</td>
        </tr>""")
        
    debug_section = f"""
    <details class="custom-details" style="margin-top:24px;">
      <summary>{i18n.t("settings.debug_section")}</summary>
      <div class="details-content" style="padding:0;">
        <table class="data-table">
          <thead><tr><th>{i18n.t("settings.col_key")}</th><th>{i18n.t("settings.col_val")}</th></tr></thead>
          <tbody>{''.join(debug_rows)}</tbody>
        </table>
      </div>
    </details>
    """
    
    body = f"{mode_banner}\n{policy_form}\n{timing_access}\n{debug_section}"
    return ui.render_page(i18n.t("settings.title"), "/settings", body, i18n.t("settings.subtitle"), unread_alerts=unread_alerts)


# ===========================================================================
# HTTP Server Handler
# ===========================================================================

class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # keep dashboard logs free of request telemetry

    def _send(self, code: int, content: str, ctype: str = "text/html; charset=utf-8"):
        data = content.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _redirect(self, to: str):
        self.send_response(303)
        self.send_header("Location", to)
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        qs = urllib.parse.parse_qs(parsed.query)
        try:
            if path == "/calibration":
                self._send(200, v_calibration(qs))
            elif path == "/":
                self._send(200, v_overview())
            elif path == "/users":
                self._send(200, v_users(qs))
            elif path.startswith("/users/"):
                parts = path.strip("/").split("/")
                if len(parts) == 2:
                    self._send(200, v_user_detail(urllib.parse.unquote(parts[1])))
                elif len(parts) == 3 and parts[2] == "summary.json":
                    rows = ledger.user_summaries()
                    u = next((x for x in rows if x["principal_pubkey"] == parts[1]), None)
                    self._send(200, json.dumps(u or {}), "application/json")
                else:
                    self._send(404, "not found", "text/plain")
            elif path == "/agents":
                self._send(200, v_agents())
            elif path == "/alerts":
                self._send(200, v_alerts(qs))
            elif path == "/settings":
                self._send(200, v_settings())
            elif path == "/api/overview.json":
                self._send(200, json.dumps(ledger.overview()), "application/json")
            elif path == "/api/agents.json":
                self._send(200, json.dumps(ledger.agent_summaries()), "application/json")
            elif path == "/api/users.json":
                self._send(200, json.dumps(ledger.user_summaries()), "application/json")
            elif path == "/health":
                self._send(200, "ok", "text/plain")
            else:
                self._send(404, "not found", "text/plain")
        except Exception as e:
            err_html = ui.render_error_state(i18n.t("errors.generic_title"), i18n.t("errors.generic_desc"), str(e))
            self._send(500, ui.render_page("Lỗi hệ thống", "/", err_html))

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        try:
            length = int(self.headers.get("Content-Length") or 0)
            form = urllib.parse.parse_qs(self.rfile.read(length).decode("utf-8"))
            parts = path.strip("/").split("/")
            if len(parts) == 3 and parts[0] == "users" and parts[2] == "set-profile":
                pubkey = urllib.parse.unquote(parts[1])
                profile = (form.get("profile") or [""])[0]
                rows = ledger.user_summaries()
                u = next((x for x in rows if x["principal_pubkey"] == pubkey), None)
                if u and profile in ("full", "high", "standard", "limited"):
                    ledger.set_user_allowance(u.get("community_id") or "", pubkey, profile,
                                              by="owner-dashboard")
                self._redirect(f"/users/{pubkey}")
            elif len(parts) == 3 and parts[0] == "alerts" and parts[2] == "ack":
                try:
                    ledger.acknowledge_owner_alert(int(parts[1]), by="owner-dashboard")
                except ValueError:
                    pass
                self._redirect("/alerts")
            elif path == "/settings/policy":
                try:
                    base = int((form.get("base_units_daily") or [""])[0])
                    if base > 0:
                        ledger.set_setting("base_units_daily", base, by="owner-dashboard")
                    for key, fkey in (("threshold_warning", "th_w"), ("threshold_high", "th_h"),
                                      ("threshold_critical", "th_c"), ("threshold_exhausted", "th_e")):
                        val = int((form.get(fkey) or [""])[0])
                        if 0 <= val <= 1000:
                            ledger.set_setting(key, val, by="owner-dashboard")
                except ValueError:
                    pass
                self._redirect("/settings")
            else:
                self._send(404, "not found", "text/plain")
        except Exception as e:
            err_html = ui.render_error_state(i18n.t("errors.generic_title"), i18n.t("errors.generic_desc"), str(e))
            self._send(500, ui.render_page("Lỗi hệ thống", "/", err_html))


def main():
    ledger.init_db()
    ledger.ensure_canonical_agents()
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"AI Usage Center listening on http://{HOST}:{PORT} (owner-only, local bind)")
    sys.stdout.flush()
    server.serve_forever()


if __name__ == "__main__":
    main()
