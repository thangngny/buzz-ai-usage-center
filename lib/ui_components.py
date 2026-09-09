#!/usr/bin/env python3
"""
UI Component Library & Design System for AI Usage Center (v2.1 Enterprise).
Linear / Stripe / Vercel / Raycast quality:
- Obsidian Dark Mode (Default) + Seamless Light Mode Switcher
- Smooth Cubic-Bezier SVG Area Charts & Radial Gauges
- Live Client-Side Search, Filter & Column Sorting
- Auto-Refresh with Animated Countdown Spinner
- 1-Click Copy with Toast Feedback
- Zero external JS/CSS dependencies
"""

import html
import time
from typing import Any, Dict, List, Optional, Tuple
import i18n

BASE_CSS = """
<style>
/* ==========================================================================
   DESIGN TOKENS & CSS VARIABLES
   ========================================================================== */
:root {
  /* Dark Theme (Default Obsidian/Midnight) */
  --bg-page: #090a10;
  --bg-surface: #111420;
  --bg-card: #161a29;
  --bg-card-hover: #1c2134;
  --bg-subtle: #1c2032;
  --bg-muted: #272d45;
  --border-default: rgba(255, 255, 255, 0.08);
  --border-subtle: rgba(255, 255, 255, 0.04);
  --border-strong: rgba(255, 255, 255, 0.16);
  --border-glow: rgba(59, 130, 246, 0.35);
  
  --text-primary: #f8fafc;
  --text-secondary: #cbd5e1;
  --text-muted: #8492a6;
  --text-disabled: #4b5563;
  
  --primary: #3b82f6;
  --primary-hover: #60a5fa;
  --primary-subtle: rgba(59, 130, 246, 0.12);
  --primary-border: rgba(59, 130, 246, 0.3);
  --primary-glow: 0 0 20px -3px rgba(59, 130, 246, 0.4);
  
  --success: #10b981;
  --success-subtle: rgba(16, 185, 129, 0.12);
  --success-border: rgba(16, 185, 129, 0.3);
  
  --warning: #f59e0b;
  --warning-subtle: rgba(245, 158, 11, 0.12);
  --warning-border: rgba(245, 158, 11, 0.3);
  
  --danger: #ef4444;
  --danger-subtle: rgba(239, 68, 68, 0.12);
  --danger-border: rgba(239, 68, 68, 0.3);
  
  --capacity: #a855f7;
  --capacity-subtle: rgba(168, 85, 247, 0.12);
  --capacity-border: rgba(168, 85, 247, 0.35);
  --capacity-glow: 0 0 25px -4px rgba(168, 85, 247, 0.4);
  
  --radius-sm: 6px;
  --radius-md: 10px;
  --radius-lg: 14px;
  --radius-xl: 18px;
  
  --shadow-sm: 0 1px 2px 0 rgba(0, 0, 0, 0.4);
  --shadow-md: 0 4px 12px -2px rgba(0, 0, 0, 0.5), 0 2px 6px -1px rgba(0, 0, 0, 0.3);
  --shadow-lg: 0 12px 32px -4px rgba(0, 0, 0, 0.6), 0 4px 12px -2px rgba(0, 0, 0, 0.4);
  
  --font-sans: -apple-system, BlinkMacSystemFont, "Inter", "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
  --font-mono: ui-monospace, SFMono-Regular, "JetBrains Mono", Menlo, Monaco, Consolas, "Liberation Mono", monospace;
  
  --header-height: 64px;
  --sidebar-width: 260px;
}

/* Light Theme Override */
[data-theme="light"] {
  --bg-page: #f8fafc;
  --bg-surface: #ffffff;
  --bg-card: #ffffff;
  --bg-card-hover: #f1f5f9;
  --bg-subtle: #f1f5f9;
  --bg-muted: #e2e8f0;
  --border-default: #e2e8f0;
  --border-subtle: #f1f5f9;
  --border-strong: #cbd5e1;
  --border-glow: rgba(37, 99, 235, 0.25);
  
  --text-primary: #0f172a;
  --text-secondary: #334155;
  --text-muted: #64748b;
  --text-disabled: #94a3b8;
  
  --primary: #2563eb;
  --primary-hover: #1d4ed8;
  --primary-subtle: #eff6ff;
  --primary-border: #bfdbfe;
  --primary-glow: 0 0 15px -3px rgba(37, 99, 235, 0.2);
  
  --success: #16a34a;
  --success-subtle: #f0fdf4;
  --success-border: #bbf7d0;
  
  --warning: #d97706;
  --warning-subtle: #fffbeb;
  --warning-border: #fde68a;
  
  --danger: #dc2626;
  --danger-subtle: #fef2f2;
  --danger-border: #fecaca;
  
  --capacity: #7c3aed;
  --capacity-subtle: #f5f3ff;
  --capacity-border: #ddd6fe;
  --capacity-glow: 0 0 20px -4px rgba(124, 58, 237, 0.2);
  
  --shadow-sm: 0 1px 2px 0 rgba(0, 0, 0, 0.05);
  --shadow-md: 0 4px 12px -2px rgba(0, 0, 0, 0.08), 0 2px 4px -2px rgba(0, 0, 0, 0.04);
  --shadow-lg: 0 10px 25px -3px rgba(0, 0, 0, 0.1), 0 4px 6px -2px rgba(0, 0, 0, 0.05);
}

/* ==========================================================================
   GLOBAL BASE STYLES
   ========================================================================== */
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

body {
  font-family: var(--font-sans);
  background-color: var(--bg-page);
  background-image: 
    radial-gradient(ellipse 80% 50% at 50% -20%, rgba(59, 130, 246, 0.08), transparent 70%),
    radial-gradient(ellipse 60% 40% at 85% 10%, rgba(168, 85, 247, 0.05), transparent 60%);
  background-attachment: fixed;
  color: var(--text-primary);
  line-height: 1.5;
  font-size: 14px;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
  min-height: 100vh;
  transition: background-color 0.2s ease, color 0.2s ease;
}

/* ==========================================================================
   LAYOUT GRID & SIDEBAR
   ========================================================================== */
.app-layout {
  display: grid;
  grid-template-columns: var(--sidebar-width) 1fr;
  min-height: 100vh;
}

.sidebar {
  background: var(--bg-surface);
  border-right: 1px solid var(--border-default);
  display: flex;
  flex-direction: column;
  position: sticky;
  top: 0;
  height: 100vh;
  z-index: 40;
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
}

.sidebar-header {
  padding: 18px 20px;
  border-bottom: 1px solid var(--border-subtle);
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.brand {
  display: flex;
  align-items: center;
  gap: 12px;
  text-decoration: none;
  color: var(--text-primary);
}

.brand-logo-wrapper {
  position: relative;
}

.brand-logo {
  width: 34px;
  height: 34px;
  background: linear-gradient(135deg, #3b82f6 0%, #8b5cf6 100%);
  border-radius: var(--radius-md);
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  font-weight: 800;
  font-size: 15px;
  box-shadow: 0 0 16px rgba(59, 130, 246, 0.4);
}

.brand-title {
  font-size: 15px;
  font-weight: 700;
  letter-spacing: -0.02em;
  color: var(--text-primary);
  line-height: 1.2;
}

.brand-subtitle {
  font-size: 11px;
  color: var(--text-muted);
  font-weight: 500;
}

.brand-badge {
  font-size: 10px;
  background: var(--primary-subtle);
  color: var(--primary);
  border: 1px solid var(--primary-border);
  padding: 2px 7px;
  border-radius: 12px;
  font-weight: 700;
  letter-spacing: 0.04em;
  box-shadow: var(--primary-glow);
}

.sidebar-nav {
  padding: 18px 12px;
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 4px;
  overflow-y: auto;
}

.nav-section-title {
  font-size: 11px;
  font-weight: 700;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.06em;
  padding: 8px 12px 4px;
  margin-top: 8px;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 9px 12px;
  border-radius: var(--radius-md);
  color: var(--text-secondary);
  text-decoration: none;
  font-size: 13.5px;
  font-weight: 500;
  transition: all 0.15s cubic-bezier(0.4, 0, 0.2, 1);
  position: relative;
}

.nav-item:hover {
  background: var(--bg-subtle);
  color: var(--text-primary);
  transform: translateX(2px);
}

.nav-item.active {
  background: var(--primary-subtle);
  color: var(--primary);
  font-weight: 600;
  border: 1px solid var(--primary-border);
  box-shadow: var(--primary-glow);
}

.nav-item svg {
  width: 18px;
  height: 18px;
  stroke-width: 2;
  flex-shrink: 0;
  transition: transform 0.2s ease;
}

.nav-item:hover svg {
  transform: scale(1.08);
}

.nav-badge {
  margin-left: auto;
  background: var(--danger-subtle);
  color: var(--danger);
  border: 1px solid var(--danger-border);
  font-size: 11px;
  font-weight: 700;
  padding: 1px 7px;
  border-radius: 10px;
}

.sidebar-footer {
  padding: 16px 18px;
  border-top: 1px solid var(--border-subtle);
  background: var(--bg-surface);
  font-size: 12px;
}

.system-status-indicator {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--text-secondary);
  margin-bottom: 6px;
  font-weight: 500;
}

.status-dot-pulse {
  position: relative;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--success);
}

.status-dot-pulse::after {
  content: "";
  position: absolute;
  top: -3px;
  left: -3px;
  right: -3px;
  bottom: -3px;
  border-radius: 50%;
  background: var(--success);
  opacity: 0.4;
  animation: pulseRadar 2s infinite ease-out;
}

@keyframes pulseRadar {
  0% { transform: scale(0.9); opacity: 0.8; }
  70% { transform: scale(2.2); opacity: 0; }
  100% { transform: scale(2.2); opacity: 0; }
}

/* ==========================================================================
   TOP HEADER & TOOLBAR
   ========================================================================== */
.main-wrapper {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.top-header {
  background: var(--bg-surface);
  border-bottom: 1px solid var(--border-default);
  padding: 0 32px;
  height: var(--header-height);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  position: sticky;
  top: 0;
  z-index: 30;
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
}

.header-left {
  display: flex;
  align-items: center;
  gap: 14px;
}

.page-title {
  font-size: 19px;
  font-weight: 700;
  color: var(--text-primary);
  letter-spacing: -0.02em;
}

.page-subtitle-badge {
  font-size: 12px;
  color: var(--text-muted);
  background: var(--bg-subtle);
  padding: 3px 10px;
  border-radius: 12px;
  border: 1px solid var(--border-default);
  font-weight: 500;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 12px;
}

.header-control-pill {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 12px;
  background: var(--bg-subtle);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-md);
  font-size: 13px;
  color: var(--text-secondary);
}

.header-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 6px 12px;
  background: var(--bg-card);
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-md);
  color: var(--text-primary);
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.15s ease;
  min-height: 34px;
}

.header-btn:hover {
  background: var(--bg-card-hover);
  border-color: var(--primary);
  color: var(--primary);
  transform: translateY(-1px);
}

.header-btn-icon {
  width: 34px;
  height: 34px;
  padding: 0;
  border-radius: var(--radius-md);
}

.user-owner-badge {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 10px 4px 6px;
  background: var(--bg-subtle);
  border: 1px solid var(--border-default);
  border-radius: 20px;
  font-size: 12.5px;
  font-weight: 600;
  color: var(--text-primary);
}

.avatar-deterministic {
  width: 24px;
  height: 24px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 11px;
  font-weight: 800;
  color: #fff;
  text-shadow: 0 1px 2px rgba(0,0,0,0.3);
}

.refresh-countdown-svg {
  width: 14px;
  height: 14px;
  transform: rotate(-90deg);
}

.refresh-countdown-circle {
  stroke-dasharray: 44;
  stroke-dashoffset: 0;
  transition: stroke-dashoffset 1s linear;
}

.mobile-nav-bar {
  display: none;
  background: var(--bg-surface);
  border-bottom: 1px solid var(--border-default);
  padding: 8px 16px;
  overflow-x: auto;
  white-space: nowrap;
  gap: 8px;
  -webkit-overflow-scrolling: touch;
}

.mobile-nav-item {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 14px;
  border-radius: 20px;
  font-size: 13px;
  font-weight: 600;
  color: var(--text-secondary);
  text-decoration: none;
  background: var(--bg-subtle);
  border: 1px solid var(--border-default);
}

.mobile-nav-item.active {
  background: var(--primary-subtle);
  color: var(--primary);
  border-color: var(--primary-border);
}

/* ==========================================================================
   CONTENT CONTAINER & HERO SECTION
   ========================================================================== */
.content-container {
  padding: 28px 32px 64px;
  max-width: 1400px;
  width: 100%;
  margin: 0 auto;
}

.hero-card {
  background: linear-gradient(135deg, var(--bg-card) 0%, rgba(26, 32, 53, 0.4) 100%);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-xl);
  padding: 26px 30px;
  box-shadow: var(--shadow-md);
  margin-bottom: 24px;
  position: relative;
  overflow: hidden;
}

.hero-card::before {
  content: "";
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 2px;
  background: linear-gradient(90deg, #3b82f6, #8b5cf6, #10b981);
}

.hero-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 16px;
}

.hero-label {
  font-size: 12px;
  font-weight: 700;
  color: var(--primary);
  text-transform: uppercase;
  letter-spacing: 0.06em;
  display: flex;
  align-items: center;
  gap: 6px;
}

.hero-value-group {
  display: flex;
  align-items: baseline;
  gap: 16px;
  margin: 8px 0 14px;
}

.hero-value {
  font-size: 44px;
  font-weight: 800;
  color: var(--text-primary);
  letter-spacing: -0.03em;
  line-height: 1;
  font-variant-numeric: tabular-nums;
}

.hero-remaining {
  font-size: 18px;
  font-weight: 600;
  color: var(--text-muted);
}

.kpi-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(230px, 1fr));
  gap: 16px;
  margin-bottom: 24px;
}

.kpi-card {
  background: var(--bg-card);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-lg);
  padding: 20px 22px;
  box-shadow: var(--shadow-sm);
  display: flex;
  flex-direction: column;
  transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
  position: relative;
}

.kpi-card:hover {
  transform: translateY(-2px);
  border-color: var(--border-strong);
  box-shadow: var(--shadow-md);
}

.kpi-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-muted);
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.kpi-num {
  font-size: 30px;
  font-weight: 800;
  color: var(--text-primary);
  margin: 10px 0 4px;
  letter-spacing: -0.02em;
  line-height: 1.1;
  font-variant-numeric: tabular-nums;
}

.kpi-desc {
  font-size: 12.5px;
  color: var(--text-muted);
  line-height: 1.4;
}

.mode-banner {
  background: var(--bg-card);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-lg);
  padding: 14px 20px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 24px;
  font-size: 13px;
  color: var(--text-secondary);
}

.mode-pills {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.mode-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 12px;
  border-radius: 20px;
  font-weight: 600;
  font-size: 12px;
}

.mode-pill.active {
  background: var(--success-subtle);
  color: var(--success);
  border: 1px solid var(--success-border);
}

.mode-pill.inactive {
  background: var(--bg-subtle);
  color: var(--text-muted);
  border: 1px solid var(--border-default);
}

.card-section {
  background: var(--bg-card);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-xl);
  padding: 24px 26px;
  box-shadow: var(--shadow-sm);
  margin-bottom: 24px;
}

.section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 20px;
}

.section-title {
  font-size: 17px;
  font-weight: 700;
  color: var(--text-primary);
  letter-spacing: -0.02em;
}

.section-subtitle {
  font-size: 13px;
  color: var(--text-muted);
  margin-top: 3px;
}

.grid-2col {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 24px;
  margin-bottom: 24px;
}

/* ==========================================================================
   PROGRESS BARS & GAUGES
   ========================================================================== */
.progress-container {
  width: 100%;
}

.progress-track {
  background: var(--bg-muted);
  border-radius: 10px;
  overflow: hidden;
  height: 8px;
  position: relative;
}

.progress-fill {
  height: 100%;
  border-radius: 10px;
  transition: width 0.4s cubic-bezier(0.4, 0, 0.2, 1);
}

.progress-info {
  display: flex;
  justify-content: space-between;
  font-size: 12.5px;
  margin-top: 6px;
  color: var(--text-secondary);
}

.radial-gauge-container {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  position: relative;
}

.radial-gauge-text {
  position: absolute;
  font-size: 11px;
  font-weight: 700;
  color: var(--text-primary);
  font-variant-numeric: tabular-nums;
}

.badge {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 3px 10px;
  border-radius: 20px;
  font-size: 12px;
  font-weight: 600;
  line-height: 1.3;
}

.table-wrapper {
  overflow-x: auto;
  border-radius: var(--radius-lg);
  border: 1px solid var(--border-default);
  background: var(--bg-surface);
}

table.data-table {
  width: 100%;
  border-collapse: collapse;
  text-align: left;
  font-size: 13.5px;
}

table.data-table th {
  background: var(--bg-subtle);
  color: var(--text-secondary);
  font-weight: 600;
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  padding: 13px 16px;
  border-bottom: 1px solid var(--border-default);
  white-space: nowrap;
  user-select: none;
}

table.data-table th.sortable {
  cursor: pointer;
  transition: color 0.15s ease;
}

table.data-table th.sortable:hover {
  color: var(--primary);
}

table.data-table td {
  padding: 13px 16px;
  border-bottom: 1px solid var(--border-subtle);
  color: var(--text-primary);
  vertical-align: middle;
}

table.data-table tr:last-child td {
  border-bottom: none;
}

table.data-table tbody tr {
  transition: background-color 0.15s ease;
}

table.data-table tbody tr:hover {
  background-color: var(--bg-subtle);
}

.td-num {
  text-align: right;
  font-variant-numeric: tabular-nums;
}

th.th-num {
  text-align: right;
}

.capacity-box {
  background: linear-gradient(135deg, rgba(168, 85, 247, 0.08) 0%, rgba(99, 102, 241, 0.04) 100%);
  border: 1px solid var(--capacity-border);
  border-radius: var(--radius-xl);
  padding: 24px 28px;
  margin-bottom: 24px;
  box-shadow: var(--capacity-glow);
}

.capacity-title {
  color: var(--capacity);
  font-size: 16px;
  font-weight: 700;
  letter-spacing: -0.01em;
  display: flex;
  align-items: center;
  gap: 8px;
}

.capacity-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(230px, 1fr));
  gap: 16px;
  margin: 18px 0 8px;
}

.capacity-card {
  background: var(--bg-card);
  border: 1px solid var(--capacity-border);
  border-radius: var(--radius-lg);
  padding: 18px;
  transition: all 0.2s ease;
}

.capacity-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 6px 20px -3px rgba(168, 85, 247, 0.25);
}

.form-inline {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}

.input-control, select.select-control {
  font-family: inherit;
  font-size: 13px;
  color: var(--text-primary);
  background: var(--bg-card);
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-md);
  padding: 8px 14px;
  outline: none;
  transition: all 0.15s ease;
  min-height: 36px;
}

.input-control:focus, select.select-control:focus {
  border-color: var(--primary);
  box-shadow: 0 0 0 2px var(--primary-subtle);
}

.btn {
  font-family: inherit;
  font-size: 13px;
  font-weight: 600;
  padding: 8px 16px;
  border-radius: var(--radius-md);
  border: 1px solid transparent;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  transition: all 0.15s cubic-bezier(0.4, 0, 0.2, 1);
  text-decoration: none;
  min-height: 36px;
}

.btn:hover {
  transform: translateY(-1px);
}

.btn-primary {
  background: var(--primary);
  color: #fff;
  box-shadow: var(--primary-glow);
}

.btn-primary:hover {
  background: var(--primary-hover);
}

.btn-secondary {
  background: var(--bg-card);
  border-color: var(--border-strong);
  color: var(--text-primary);
}

.btn-secondary:hover {
  background: var(--bg-card-hover);
  border-color: var(--primary);
  color: var(--primary);
}

.btn-sm {
  padding: 5px 12px;
  font-size: 12px;
  min-height: 30px;
}

.filter-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
  margin-bottom: 20px;
}

.filter-group {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.filter-pill {
  padding: 6px 14px;
  border-radius: 20px;
  font-size: 13px;
  font-weight: 500;
  background: var(--bg-card);
  border: 1px solid var(--border-default);
  color: var(--text-secondary);
  text-decoration: none;
  cursor: pointer;
  transition: all 0.15s ease;
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.filter-pill:hover {
  background: var(--bg-card-hover);
  color: var(--text-primary);
}

.filter-pill.active {
  background: var(--primary-subtle);
  border-color: var(--primary-border);
  color: var(--primary);
  font-weight: 600;
  box-shadow: var(--primary-glow);
}

/* Tabs Navigation */
.tabs-nav {
  display: flex;
  gap: 8px;
  border-bottom: 1px solid var(--border-default);
  margin-bottom: 20px;
  padding-bottom: 2px;
}

.tab-item {
  padding: 8px 16px;
  font-size: 13.5px;
  font-weight: 600;
  color: var(--text-muted);
  text-decoration: none;
  border-bottom: 2px solid transparent;
  margin-bottom: -3px;
  transition: all 0.15s ease;
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.tab-item:hover {
  color: var(--text-primary);
}

.tab-item.active {
  color: var(--primary);
  border-bottom-color: var(--primary);
}

.btn-copy {
  background: transparent;
  border: none;
  color: var(--text-muted);
  cursor: pointer;
  padding: 2px 5px;
  border-radius: 4px;
  display: inline-flex;
  align-items: center;
  transition: all 0.15s ease;
}

.btn-copy:hover {
  color: var(--primary);
  background: var(--primary-subtle);
}

#toast-notification {
  position: fixed;
  bottom: 28px;
  right: 28px;
  background: var(--bg-card);
  color: var(--text-primary);
  border: 1px solid var(--primary-border);
  box-shadow: var(--shadow-lg), var(--primary-glow);
  padding: 10px 18px;
  border-radius: var(--radius-md);
  font-size: 13px;
  font-weight: 600;
  display: flex;
  align-items: center;
  gap: 8px;
  z-index: 1000;
  transform: translateY(100px);
  opacity: 0;
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
  pointer-events: none;
}

#toast-notification.show {
  transform: translateY(0);
  opacity: 1;
}

details.custom-details {
  border: 1px solid var(--border-default);
  border-radius: var(--radius-md);
  background: var(--bg-card);
  margin: 12px 0;
  overflow: hidden;
}

details.custom-details summary {
  padding: 12px 16px;
  font-size: 13px;
  font-weight: 600;
  color: var(--text-secondary);
  cursor: pointer;
  background: var(--bg-subtle);
  user-select: none;
  display: flex;
  align-items: center;
  justify-content: space-between;
}

details.custom-details summary:hover {
  color: var(--primary);
}

details.custom-details[open] summary {
  border-bottom: 1px solid var(--border-default);
}

.details-content {
  padding: 16px;
}

.empty-state {
  text-align: center;
  padding: 48px 24px;
  color: var(--text-muted);
}

.empty-icon {
  width: 48px;
  height: 48px;
  stroke: var(--text-disabled);
  margin: 0 auto 14px;
  display: block;
}

.empty-title {
  font-size: 16px;
  font-weight: 700;
  color: var(--text-primary);
  margin-bottom: 4px;
}

.empty-desc {
  font-size: 13px;
  max-width: 460px;
  margin: 0 auto;
}

.chart-container {
  width: 100%;
  position: relative;
  margin: 16px 0 8px;
}

.text-muted { color: var(--text-muted); }
.text-danger { color: var(--danger); }
.text-success { color: var(--success); }
.text-warning { color: var(--warning); }
.font-mono { font-family: var(--font-mono); }

@media (max-width: 1024px) {
  .app-layout { grid-template-columns: 1fr; }
  .sidebar { display: none; }
  .mobile-nav-bar { display: flex; }
  .grid-2col { grid-template-columns: 1fr; }
  .top-header { padding: 0 20px; }
  .content-container { padding: 20px 20px 48px; }
}

@media (max-width: 640px) {
  .header-right .header-control-pill { display: none; }
  .kpi-grid { grid-template-columns: 1fr; }
  .hero-value { font-size: 34px; }
}
</style>
"""

# SVG Icons
ICON_CHART = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="M3 3v18h18"></path><path d="m19 9-5 5-4-4-3 3"></path></svg>'
ICON_USERS = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"></path><circle cx="9" cy="7" r="4"></circle><path d="M22 21v-2a4 4 0 0 0-3-3.87"></path><path d="M16 3.13a4 4 0 0 1 0 7.75"></path></svg>'
ICON_BOT = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="M12 8V4H8"></path><rect width="16" height="12" x="4" y="8" rx="2"></rect><path d="M2 14h2"></path><path d="M20 14h2"></path><path d="M15 13v2"></path><path d="M9 13v2"></path></svg>'
ICON_SCALE = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="m16 16 3-8 3 8c-.87.65-1.92 1-3 1s-2.13-.35-3-1Z"></path><path d="m2 16 3-8 3 8c-.87.65-1.92 1-3 1s-2.13-.35-3-1Z"></path><path d="M7 21h10"></path><path d="M12 3v18"></path><path d="M3 7h2c2 0 5-1 7-2 2 1 5 2 7 2h2"></path></svg>'
ICON_ALERT = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9"></path><path d="M10.3 21a1.94 1.94 0 0 0 3.4 0"></path></svg>'
ICON_SETTINGS = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"></path><circle cx="12" cy="12" r="3"></circle></svg>'
ICON_REFRESH = '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2"><path d="M21.5 2v6h-6M21.34 15.57a10 10 0 1 1-.57-8.38l5.67-5.67"></path></svg>'
ICON_COPY = '<svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2"><rect width="14" height="14" x="8" y="8" rx="2" ry="2"></rect><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"></path></svg>'
ICON_MOON = '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z"></path></svg>'
ICON_SUN = '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="4"></circle><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41"></path></svg>'


def pct_color(p: float) -> str:
    if p >= 95:
        return "var(--danger)"
    if p >= 85:
        return "#f97316"
    if p >= 70:
        return "var(--warning)"
    return "var(--success)"


def get_deterministic_color(identifier: str) -> str:
    palettes = [
        "linear-gradient(135deg, #3b82f6, #1d4ed8)",
        "linear-gradient(135deg, #8b5cf6, #6d28d9)",
        "linear-gradient(135deg, #ec4899, #be185d)",
        "linear-gradient(135deg, #10b981, #047857)",
        "linear-gradient(135deg, #f59e0b, #b45309)",
        "linear-gradient(135deg, #06b6d4, #0e7490)",
        "linear-gradient(135deg, #6366f1, #4338ca)"
    ]
    idx = sum(ord(c) for c in (identifier or "User")) % len(palettes)
    return palettes[idx]


def render_avatar(name_or_pk: str, size: int = 26) -> str:
    initial = (name_or_pk or "U")[:1].upper()
    bg = get_deterministic_color(name_or_pk)
    return f"""<div class="avatar-deterministic" style="width:{size}px;height:{size}px;background:{bg};">{html.escape(initial)}</div>"""


def render_copyable(text: str, label: Optional[str] = None, font_mono: bool = True) -> str:
    display = html.escape(label or text)
    mono_cls = " font-mono" if font_mono else ""
    return f"""<span style="display:inline-flex;align-items:center;gap:4px;">
      <span class="{mono_cls}">{display}</span>
      <button class="btn-copy" onclick="copyText('{html.escape(text)}')" title="Sao chép">{ICON_COPY}</button>
    </span>"""


def render_radial_gauge(percent: float, size: int = 44, stroke: int = 4, color_override: Optional[str] = None) -> str:
    p = max(0.0, min(100.0, float(percent or 0.0)))
    radius = (size - stroke) / 2
    circ = 2 * 3.141592653589793 * radius
    offset = circ - (p / 100.0) * circ
    color = color_override or pct_color(p)
    
    return f"""<div class="radial-gauge-container" style="width:{size}px;height:{size}px;">
      <svg width="{size}" height="{size}" style="transform:rotate(-90deg);">
        <circle cx="{size/2}" cy="{size/2}" r="{radius}" fill="none" stroke="var(--bg-muted)" stroke-width="{stroke}"></circle>
        <circle cx="{size/2}" cy="{size/2}" r="{radius}" fill="none" stroke="{color}" stroke-width="{stroke}"
                stroke-dasharray="{circ:.2f}" stroke-dashoffset="{offset:.2f}" stroke-linecap="round"
                style="transition:stroke-dashoffset 0.5s ease;"></circle>
      </svg>
      <span class="radial-gauge-text">{p:.0f}%</span>
    </div>"""


def render_progress_bar(used_pct: float, remaining_pct: Optional[float] = None, height: int = 8,
                        show_label: bool = True, color_override: Optional[str] = None) -> str:
    p = max(0.0, min(100.0, float(used_pct or 0.0)))
    color = color_override or pct_color(p)
    label_html = ""
    if show_label:
        rem_text = f"Còn lại {remaining_pct:.1f}%".replace(".", ",") if remaining_pct is not None else f"Còn lại {100.0 - p:.1f}%".replace(".", ",")
        used_text = f"Đã dùng {p:.1f}%".replace(".", ",")
        label_html = f"""<div class="progress-info">
          <span><b>{used_text}</b></span>
          <span class="text-muted">{rem_text}</span>
        </div>"""
    return f"""<div class="progress-container">
      <div class="progress-track" style="height:{height}px;">
        <div class="progress-fill" style="width:{p:.1f}%;background:{color};box-shadow:0 0 8px {color}66;"></div>
      </div>
      {label_html}
    </div>"""


def render_badge(text: str, bg: str, fg: str, border: Optional[str] = None) -> str:
    border_style = f"border:1px solid {border};" if border else ""
    return f"""<span class="badge" style="background:{bg};color:{fg};{border_style}">{html.escape(text)}</span>"""


def render_kpi_card(title: str, value: str, subtext: Optional[str] = None,
                    progress_html: Optional[str] = None, badge_html: Optional[str] = None) -> str:
    b = f"<div>{badge_html}</div>" if badge_html else ""
    p = f"<div style='margin-top:10px;'>{progress_html}</div>" if progress_html else ""
    s = f"<div class='kpi-desc'>{subtext}</div>" if subtext else ""
    return f"""<div class="kpi-card">
      <div class="kpi-title"><span>{title}</span>{b}</div>
      <div class="kpi-num">{value}</div>
      {s}
      {p}
    </div>"""


def render_svg_trend_chart(points: List[Dict[str, Any]], height: int = 190) -> str:
    if not points:
        return "<p class='text-muted' style='padding:20px;text-align:center;'>Chưa đủ dữ liệu biểu đồ.</p>"
    
    w = 640
    h = height
    pad_l = 45
    pad_r = 20
    pad_t = 20
    pad_b = 30
    
    chart_w = w - pad_l - pad_r
    chart_h = h - pad_t - pad_b
    
    vals = [p.get("value", 0.0) for p in points]
    max_val = max(max(vals) if vals else 10.0, 10.0) * 1.15
    min_val = 0.0
    
    n = len(points)
    dx = chart_w / max(1, n - 1) if n > 1 else chart_w / 2
    
    coords = []
    for i, p in enumerate(points):
        x = pad_l + (i * dx if n > 1 else chart_w / 2)
        y = pad_t + chart_h - ((p.get("value", 0.0) - min_val) / (max_val - min_val) * chart_h)
        coords.append((x, y, p))
    
    if len(coords) == 1:
        path_d = f"M {coords[0][0]} {coords[0][1]}"
    else:
        path_d = f"M {coords[0][0]:.1f} {coords[0][1]:.1f}"
        for i in range(len(coords) - 1):
            p0 = coords[i]
            p1 = coords[i + 1]
            cp1x = p0[0] + (p1[0] - p0[0]) * 0.4
            cp1y = p0[1]
            cp2x = p0[0] + (p1[0] - p0[0]) * 0.6
            cp2y = p1[1]
            path_d += f" C {cp1x:.1f} {cp1y:.1f}, {cp2x:.1f} {cp2y:.1f}, {p1[0]:.1f} {p1[1]:.1f}"
            
    area_d = f"{path_d} L {coords[-1][0]:.1f} {pad_t + chart_h:.1f} L {coords[0][0]:.1f} {pad_t + chart_h:.1f} Z"
    
    grid_lines = []
    for step in [0.25, 0.5, 0.75, 1.0]:
        gy = pad_t + chart_h * (1.0 - step)
        gval = max_val * step
        grid_lines.append(f'<line x1="{pad_l}" y1="{gy:.1f}" x2="{w - pad_r}" y2="{gy:.1f}" stroke="var(--border-default)" stroke-dasharray="3,3"/>')
        grid_lines.append(f'<text x="{pad_l - 8}" y="{gy + 4:.1f}" font-size="10" fill="var(--text-muted)" text-anchor="end">{gval:.0f}%</text>')
    
    x_labels = []
    for x, y, p in coords:
        label = html.escape(str(p.get("label", "")))
        x_labels.append(f'<text x="{x:.1f}" y="{h - 8}" font-size="11" fill="var(--text-muted)" text-anchor="middle">{label}</text>')
    
    dots = []
    for x, y, p in coords:
        val_str = f"{p.get('value', 0.0):.1f}%".replace(".", ",")
        reqs = p.get("requests", 0)
        dots.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4.5" fill="#3b82f6" stroke="var(--bg-card)" stroke-width="2.5" style="cursor:pointer;"><title>{p.get("label")}: {val_str} ({reqs} yêu cầu)</title></circle>')

    return f"""<div class="chart-container">
      <svg viewBox="0 0 {w} {h}" style="width:100%;height:{h}px;overflow:visible;">
        <defs>
          <linearGradient id="chartGradient" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stop-color="#3b82f6" stop-opacity="0.35"/>
            <stop offset="100%" stop-color="#3b82f6" stop-opacity="0.0"/>
          </linearGradient>
        </defs>
        {''.join(grid_lines)}
        <path d="{area_d}" fill="url(#chartGradient)"/>
        <path d="{path_d}" fill="none" stroke="#3b82f6" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" style="filter:drop-shadow(0 0 6px rgba(59,130,246,0.4));"/>
        {''.join(dots)}
        {''.join(x_labels)}
      </svg>
    </div>"""


def render_empty_state(title: str, desc: str) -> str:
    return f"""<div class="empty-state">
      <svg class="empty-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
        <circle cx="12" cy="12" r="10"></circle>
        <line x1="12" y1="8" x2="12" y2="12"></line>
        <line x1="12" y1="16" x2="12.01" y2="16"></line>
      </svg>
      <div class="empty-title">{html.escape(title)}</div>
      <div class="empty-desc">{html.escape(desc)}</div>
    </div>"""


def render_error_state(title: str, desc: str, details: Optional[str] = None) -> str:
    d_html = f"""<details class="custom-details" style="margin-top:16px;text-align:left;">
      <summary>{i18n.t("errors.error_details")}</summary>
      <div class="details-content font-mono" style="font-size:12px;background:var(--bg-subtle);">{html.escape(details)}</div>
    </details>""" if details else ""
    return f"""<div class="empty-state">
      <svg class="empty-icon" viewBox="0 0 24 24" fill="none" stroke="var(--danger)" stroke-width="1.5">
        <circle cx="12" cy="12" r="10"></circle>
        <line x1="12" y1="8" x2="12" y2="12"></line>
        <line x1="12" y1="16" x2="12.01" y2="16"></line>
      </svg>
      <div class="empty-title" style="color:var(--danger);">{html.escape(title)}</div>
      <div class="empty-desc">{html.escape(desc)}</div>
      {d_html}
    </div>"""


APP_JS = f"""
<script>
function initTheme() {{
  const saved = localStorage.getItem('buzz_theme') || 'dark';
  document.documentElement.setAttribute('data-theme', saved);
  updateThemeIcon(saved);
}}

function toggleTheme() {{
  const current = document.documentElement.getAttribute('data-theme') || 'dark';
  const next = current === 'dark' ? 'light' : 'dark';
  document.documentElement.setAttribute('data-theme', next);
  localStorage.setItem('buzz_theme', next);
  updateThemeIcon(next);
}}

function updateThemeIcon(theme) {{
  const btn = document.getElementById('theme-toggle-btn');
  if (btn) {{
    btn.innerHTML = theme === 'dark' ? '{ICON_SUN}' : '{ICON_MOON}';
    btn.title = theme === 'dark' ? 'Chuyển sang Giao diện Sáng' : 'Chuyển sang Giao diện Tối';
  }}
}}

function copyText(text) {{
  navigator.clipboard.writeText(text).then(() => {{
    showToast('✓ Đã sao chép: ' + (text.length > 24 ? text.substring(0, 24) + '…' : text));
  }}).catch(() => {{
    showToast('Lỗi khi sao chép');
  }});
}}

function showToast(msg) {{
  const t = document.getElementById('toast-notification');
  if (t) {{
    t.innerText = msg;
    t.classList.add('show');
    clearTimeout(window._toastTimer);
    window._toastTimer = setTimeout(() => t.classList.remove('show'), 2500);
  }}
}}

let refreshInterval = 0;
let refreshTimer = null;
let countdownSecs = 0;

function setAutoRefresh(seconds) {{
  refreshInterval = parseInt(seconds, 10) || 0;
  localStorage.setItem('buzz_auto_refresh', refreshInterval);
  clearInterval(refreshTimer);
  
  const ring = document.getElementById('refresh-countdown-ring');
  if (refreshInterval <= 0) {{
    if (ring) ring.style.strokeDashoffset = '44';
    return;
  }}
  
  countdownSecs = refreshInterval;
  refreshTimer = setInterval(() => {{
    countdownSecs--;
    if (ring) {{
      const frac = countdownSecs / refreshInterval;
      ring.style.strokeDashoffset = (44 * (1 - frac)).toFixed(1);
    }}
    if (countdownSecs <= 0) {{
      window.location.reload();
    }}
  }}, 1000);
}}

function filterTable(inputId, tableSelector) {{
  const input = document.getElementById(inputId);
  if (!input) return;
  const q = input.value.toLowerCase().trim();
  const rows = document.querySelectorAll(tableSelector + ' tbody tr');
  rows.forEach(tr => {{
    const text = tr.innerText.toLowerCase();
    tr.style.display = text.includes(q) ? '' : 'none';
  }});
}}

function initSortableTables() {{
  document.querySelectorAll('table.data-table th.sortable').forEach(th => {{
    th.addEventListener('click', () => {{
      const table = th.closest('table');
      const tbody = table.querySelector('tbody');
      const rows = Array.from(tbody.querySelectorAll('tr'));
      const colIdx = Array.from(th.parentNode.children).indexOf(th);
      const isAsc = th.classList.contains('asc');
      
      table.querySelectorAll('th').forEach(h => h.classList.remove('asc', 'desc'));
      th.classList.toggle('asc', !isAsc);
      th.classList.toggle('desc', isAsc);
      
      rows.sort((a, b) => {{
        const valA = a.children[colIdx]?.innerText.trim() || '';
        const valB = b.children[colIdx]?.innerText.trim() || '';
        const numA = parseFloat(valA.replace(/[^0-9.-]/g, ''));
        const numB = parseFloat(valB.replace(/[^0-9.-]/g, ''));
        
        if (!isNaN(numA) && !isNaN(numB)) {{
          return isAsc ? numB - numA : numA - numB;
        }}
        return isAsc ? valB.localeCompare(valA) : valA.localeCompare(valB);
      }});
      
      rows.forEach(r => tbody.appendChild(r));
    }});
  }});
}}

document.addEventListener('DOMContentLoaded', () => {{
  initTheme();
  initSortableTables();
  const savedRefresh = localStorage.getItem('buzz_auto_refresh') || '0';
  const sel = document.getElementById('auto-refresh-select');
  if (sel) {{
    sel.value = savedRefresh;
    setAutoRefresh(savedRefresh);
  }}
}});
</script>
"""


def render_page(title: str, active_route: str, body_html: str, subtitle: str = "",
                unread_alerts: int = 0) -> str:
    def nav_link(href: str, name: str, icon: str, badge_num: int = 0) -> str:
        is_active = " active" if href == active_route else ""
        badge = f"<span class='nav-badge'>{badge_num}</span>" if badge_num > 0 else ""
        return f"""<a href="{href}" class="nav-item{is_active}">
          {icon}
          <span>{name}</span>
          {badge}
        </a>"""
        
    def mobile_nav_link(href: str, name: str) -> str:
        is_active = " active" if href == active_route else ""
        return f'<a href="{href}" class="mobile-nav-item{is_active}">{name}</a>'
    
    curr_time = time.strftime("%H:%M", time.localtime())
    curr_date = time.strftime("%d/%m/%Y", time.localtime())
    
    return f"""<!doctype html>
<html lang="vi" data-theme="dark">
<head>
  <meta charset="utf-8">
  <title>{html.escape(title)} · AI Usage Center</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  {BASE_CSS}
</head>
<body>
  <div class="app-layout">
    <!-- Sidebar -->
    <aside class="sidebar">
      <div class="sidebar-header">
        <a href="/" class="brand">
          <div class="brand-logo-wrapper">
            <div class="brand-logo">AI</div>
          </div>
          <div>
            <div class="brand-title">AI Usage Center</div>
            <div class="brand-subtitle">Buzz AI Infrastructure</div>
          </div>
        </a>
        <span class="brand-badge">v2.0</span>
      </div>
      
      <nav class="sidebar-nav">
        <div class="nav-section-title">Trung tâm điều khiển</div>
        {nav_link("/", i18n.t("nav.overview"), ICON_CHART)}
        {nav_link("/users", i18n.t("nav.users"), ICON_USERS)}
        {nav_link("/agents", i18n.t("nav.agents"), ICON_BOT)}
        
        <div class="nav-section-title">Phân tích & Giám sát</div>
        {nav_link("/calibration", i18n.t("nav.calibration"), ICON_SCALE)}
        {nav_link("/alerts", i18n.t("nav.alerts"), ICON_ALERT, unread_alerts)}
        {nav_link("/settings", i18n.t("nav.settings"), ICON_SETTINGS)}
      </nav>
      
      <div class="sidebar-footer">
        <div class="system-status-indicator">
          <div class="status-dot-pulse"></div>
          <span>{i18n.t("app.health_ok")}</span>
        </div>
        <div style="color:var(--text-muted);font-size:11px;">METER_ONLY · ICT UTC+7</div>
      </div>
    </aside>

    <!-- Main Wrapper -->
    <div class="main-wrapper">
      <!-- Top Header -->
      <header class="top-header">
        <div class="header-left">
          <h1 class="page-title">{html.escape(title)}</h1>
          <span class="page-subtitle-badge">{html.escape(subtitle or i18n.t("app.subtitle"))}</span>
        </div>
        
        <div class="header-right">
          <!-- Time indicator -->
          <div class="header-control-pill">
            <span>📅 {curr_date}</span>
            <span>·</span>
            <span>🕒 {curr_time} ICT</span>
          </div>
          
          <!-- Auto Refresh Selector -->
          <div class="header-control-pill" style="gap:6px;" title="Tự động làm mới dữ liệu">
            <svg class="refresh-countdown-svg" viewBox="0 0 16 16">
              <circle cx="8" cy="8" r="7" fill="none" stroke="var(--border-strong)" stroke-width="2"></circle>
              <circle id="refresh-countdown-ring" class="refresh-countdown-circle" cx="8" cy="8" r="7" fill="none" stroke="var(--primary)" stroke-width="2"></circle>
            </svg>
            <select id="auto-refresh-select" class="select-control" style="padding:2px 6px;min-height:26px;font-size:12px;background:transparent;border:none;color:var(--text-primary);" onchange="setAutoRefresh(this.value)">
              <option value="0">Tắt tự làm mới</option>
              <option value="15">15 giây</option>
              <option value="30">30 giây</option>
              <option value="60">60 giây</option>
            </select>
          </div>
          
          <!-- Theme Toggle -->
          <button id="theme-toggle-btn" class="header-btn header-btn-icon" onclick="toggleTheme()" title="Chuyển chế độ Sáng/Tối">
            {ICON_SUN}
          </button>
          
          <!-- Owner Profile Badge -->
          <div class="user-owner-badge" title="Chủ sở hữu hệ thống">
            {render_avatar("NcThang", 22)}
            <span>NcThang</span>
          </div>
          
          <!-- Reload button -->
          <button class="header-btn" onclick="window.location.reload();" title="Tải lại trang">
            {ICON_REFRESH}
            <span>Làm mới</span>
          </button>
        </div>
      </header>

      <!-- Mobile Navigation Bar -->
      <div class="mobile-nav-bar">
        {mobile_nav_link("/", i18n.t("nav.overview"))}
        {mobile_nav_link("/users", i18n.t("nav.users"))}
        {mobile_nav_link("/agents", i18n.t("nav.agents"))}
        {mobile_nav_link("/calibration", i18n.t("nav.calibration"))}
        {mobile_nav_link("/alerts", i18n.t("nav.alerts"))}
        {mobile_nav_link("/settings", i18n.t("nav.settings"))}
      </div>

      <!-- Main Content -->
      <main class="content-container">
        {body_html}
      </main>
    </div>
  </div>

  <!-- Toast Notification Container -->
  <div id="toast-notification">✓ Đã sao chép!</div>

  {APP_JS}
</body>
</html>"""
