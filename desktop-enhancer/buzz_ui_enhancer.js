/**
 * Buzz Desktop Unified Multi-Community Real-Time Message Center (v6.2 - Universal Category & Section Edition)
 * =========================================================================================================
 * UI/UX & Core Features:
 * 1. Universal Category, Section, Folder, Channel, Forum & DM Auto-Discovery and Deep Navigation
 * 2. Auto-Expansion of all Collapsed Accordions (Projects, Sub-folders, Channels, Forums, DMs)
 * 3. Glassmorphism & High-Density Dark Theme matching Buzz Native Design Tokens
 * 4. Raycast/Linear-style Keyboard-First Navigation (Arrow keys, Enter, Esc, 1-5 tabs, / search)
 * 5. Compact & Actionable Message Cards with Category Badges, Workspace Badges, Sender Avatars & Relative Time
 * 6. Free Draggable Floating Pill & Left Rail Button with Viewport Clamping & LocalStorage Persistence
 * 7. Modern Auto-Dismissing Toast Notifications with Progress Timers
 */

(function () {
  console.log("[BUZZ ENHANCER v6.2] Initializing Universal Category & Section Engine...");

  let messages = [];
  let seenMessageIds = new Set();
  let unreadCount = 0;
  let isDrawerOpen = false;
  let activeFilter = "all";
  let activeTypeFilter = "all";
  let showUnreadOnly = true;
  let searchQuery = "";
  let selectedIndex = 0;

  const DYNAMIC_COMM_PALETTE = [
    { bg: "rgba(16, 185, 129, 0.18)", text: "#34d399", border: "rgba(16, 185, 129, 0.4)", icon: "🟢" },
    { bg: "rgba(168, 85, 247, 0.18)", text: "#c084fc", border: "rgba(168, 85, 247, 0.4)", icon: "🟣" },
    { bg: "rgba(245, 158, 11, 0.18)", text: "#fbbf24", border: "rgba(245, 158, 11, 0.4)", icon: "🟡" },
    { bg: "rgba(59, 130, 246, 0.18)", text: "#60a5fa", border: "rgba(59, 130, 246, 0.4)", icon: "🔵" },
    { bg: "rgba(236, 72, 153, 0.18)", text: "#f472b6", border: "rgba(236, 72, 153, 0.4)", icon: "🌸" },
    { bg: "rgba(20, 184, 166, 0.18)", text: "#2dd4bf", border: "rgba(20, 184, 166, 0.4)", icon: "🌊" },
    { bg: "rgba(249, 115, 22, 0.18)", text: "#fb923c", border: "rgba(249, 115, 22, 0.4)", icon: "🟠" },
    { bg: "rgba(139, 92, 246, 0.18)", text: "#a78bfa", border: "rgba(139, 92, 246, 0.4)", icon: "🔮" },
    { bg: "rgba(239, 68, 68, 0.18)", text: "#f87171", border: "rgba(239, 68, 68, 0.4)", icon: "🔴" }
  ];

  let lastRegisteredCommunitiesCount = 0;
  function syncCommunitiesToBackend(stored) {
    if (!Array.isArray(stored) || stored.length === 0) return;
    if (stored.length === lastRegisteredCommunitiesCount) return;
    lastRegisteredCommunitiesCount = stored.length;
    fetch("http://127.0.0.1:8787/api/register_community", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ communities: stored })
    }).catch(() => {});
  }

  let lastActiveChannelId = null;
  let activeChannelTimer = null;

  function monitorActiveChannelAutoRead() {
    try {
      const activeCommId = localStorage.getItem("buzz-active-community-id");
      if (!activeCommId) return;
      const dests = JSON.parse(localStorage.getItem("buzz-community-destinations") || "{}");
      const currentDest = dests[activeCommId];
      if (!currentDest || currentDest.kind !== "channel" || !currentDest.channelId) return;

      const chid = currentDest.channelId;
      if (chid !== lastActiveChannelId) {
        lastActiveChannelId = chid;
        if (activeChannelTimer) clearTimeout(activeChannelTimer);
        activeChannelTimer = setTimeout(() => {
          const stillCommId = localStorage.getItem("buzz-active-community-id");
          const stillDests = JSON.parse(localStorage.getItem("buzz-community-destinations") || "{}");
          if (stillDests[stillCommId]?.channelId === chid) {
            const comms = JSON.parse(localStorage.getItem("buzz-communities") || "[]");
            const commObj = comms.find(c => c.id === stillCommId);
            const commName = commObj ? (commObj.name || commObj.id) : "";

            let changed = false;
            for (const m of messages) {
              if ((m.channel_id === chid || m.channel === chid) && m.is_unread) {
                m.is_unread = false;
                changed = true;
              }
            }
            if (changed) {
              unreadCount = Math.max(0, messages.filter(m => m.is_unread !== false).length);
              updateBadgeUI();
              updateFilterTabCounts();
              if (isDrawerOpen) renderDrawerMessages(true);
            }

            fetch("http://127.0.0.1:8787/api/mark_read", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ channel_id: chid, community: commName })
            }).catch(() => {});
          }
        }, 2200);
      }
    } catch(e) {}
  }
  setInterval(monitorActiveChannelAutoRead, 1500);

  function getDiscoveredCommunities() {
    const commMap = new Map();

    // 1. Discover from localStorage['buzz-communities']
    try {
      const stored = JSON.parse(localStorage.getItem("buzz-communities") || "[]");
      if (Array.isArray(stored)) {
        syncCommunitiesToBackend(stored);
        stored.forEach((item, idx) => {
          const rawName = item.name || item.id || "";
          const key = rawName.toLowerCase().trim();
          if (key && !commMap.has(key)) {
            commMap.set(key, { key, name: rawName, index: idx });
          }
        });
      }
    } catch(e) {}

    // 2. Discover from recent messages array
    if (Array.isArray(messages)) {
      messages.forEach(m => {
        const rawName = m.community || "";
        const key = rawName.toLowerCase().trim();
        if (key && !commMap.has(key)) {
          commMap.set(key, { key, name: rawName, index: commMap.size });
        }
      });
    }

    // 3. Fallback defaults if still empty
    const defaults = ["dukickk", "platogroup", "ncthang04", "ode", "phamgianam", "phuongstory"];
    defaults.forEach(k => {
      if (!commMap.has(k)) {
        commMap.set(k, { key: k, name: k, index: commMap.size });
      }
    });

    const result = [];
    let i = 0;
    for (const [key, obj] of commMap.entries()) {
      let displayName = obj.name;
      if (key === "dukickk") displayName = "DuKick";
      else if (key === "platogroup") displayName = "Plato Group";
      else if (key === "ncthang04") displayName = "NcThang";
      else if (key === "ode") displayName = "ODE";
      else if (key === "phamgianam") displayName = "Phạm Gia Nam";
      else if (key === "phuongstory") displayName = "Phương Story";
      else if (displayName.length > 0) {
        displayName = displayName.charAt(0).toUpperCase() + displayName.slice(1);
      }

      const style = DYNAMIC_COMM_PALETTE[i % DYNAMIC_COMM_PALETTE.length];
      result.push({
        key,
        name: displayName,
        rawName: obj.name,
        index: i,
        ...style
      });
      i++;
    }
    return result;
  }

  const AVATAR_COLORS = [
    "#38bdf8", "#34d399", "#fbbf24", "#f472b6", "#a78bfa", "#fb7185", "#2dd4bf", "#818cf8"
  ];

  function getAvatarColor(str) {
    if (!str) return AVATAR_COLORS[0];
    let hash = 0;
    for (let i = 0; i < str.length; i++) hash = str.charCodeAt(i) + ((hash << 5) - hash);
    return AVATAR_COLORS[Math.abs(hash) % AVATAR_COLORS.length];
  }

  function getInitials(name) {
    if (!name) return "?";
    const parts = name.trim().split(/\s+/);
    if (parts.length >= 2) return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
    return name.slice(0, 2).toUpperCase();
  }

  function getCommMeta(comm) {
    const key = (comm || "").toLowerCase().trim();
    const comms = getDiscoveredCommunities();
    for (const c of comms) {
      if (key === c.key || key.includes(c.key) || c.key.includes(key)) return c;
    }
    const color = getAvatarColor(key);
    return {
      key,
      name: comm ? (comm.charAt(0).toUpperCase() + comm.slice(1)) : "Nhóm",
      icon: "💬",
      bg: "rgba(148, 163, 184, 0.18)",
      text: "#cbd5e1",
      border: "rgba(148, 163, 184, 0.3)",
      index: 99
    };
  }

  function detectItemCategory(msg) {
    const ch = (msg.channel || "").toLowerCase();
    if (msg.is_dm || ch.includes("dm") || ch.includes("tin nhan rieng")) return { type: "dm", label: "Tin riêng", icon: "👤", color: "#ec4899" };
    if (ch.includes("tư liệu") || ch.includes("quy trình") || ch.includes("trao đổi") || ch.includes("agent-") || ch.includes("project") || ch.includes("dự án") || ch.includes("team")) {
      return { type: "project", label: "Dự án / Thư mục", icon: "📁", color: "#f59e0b" };
    }
    if (ch.includes("forum") || ch.includes("diễn đàn")) return { type: "forum", label: "Diễn đàn", icon: "💬", color: "#8b5cf6" };
    return { type: "channel", label: "Kênh", icon: "💬", color: "#38bdf8" };
  }

  function formatMessageTime(ts, timeStr) {
    if (!ts) return { display: timeStr || "", full: timeStr || "" };
    try {
      let tsNum = Number(ts);
      if (tsNum > 9999999999) tsNum = Math.floor(tsNum / 1000);
      const d = new Date(tsNum * 1000);
      if (isNaN(d.getTime())) return { display: timeStr || "", full: timeStr || "" };

      const now = new Date();
      const diffSec = Math.floor((now.getTime() - d.getTime()) / 1000);

      const hours = String(d.getHours()).padStart(2, "0");
      const mins = String(d.getMinutes()).padStart(2, "0");
      const secs = String(d.getSeconds()).padStart(2, "0");
      const day = String(d.getDate()).padStart(2, "0");
      const month = String(d.getMonth() + 1).padStart(2, "0");
      const year = d.getFullYear();

      const fullStr = `${hours}:${mins}:${secs} · ${day}/${month}/${year}`;

      const isToday = d.getDate() === now.getDate() &&
                      d.getMonth() === now.getMonth() &&
                      d.getFullYear() === now.getFullYear();

      const yesterday = new Date(now);
      yesterday.setDate(now.getDate() - 1);
      const isYesterday = d.getDate() === yesterday.getDate() &&
                          d.getMonth() === yesterday.getMonth() &&
                          d.getFullYear() === yesterday.getFullYear();

      if (isToday) {
        if (diffSec >= 0 && diffSec < 45) return { display: "Vừa xong", full: fullStr };
        if (diffSec >= 45 && diffSec < 3600) return { display: `${Math.floor(diffSec / 60)}m trước`, full: fullStr };
        return { display: `Hôm nay ${hours}:${mins}`, full: fullStr };
      }

      if (isYesterday) {
        return { display: `Hôm qua ${hours}:${mins}`, full: fullStr };
      }

      if (year === now.getFullYear()) {
        return { display: `${hours}:${mins} · ${day}/${month}`, full: fullStr };
      }

      return { display: `${hours}:${mins} · ${day}/${month}/${year}`, full: fullStr };
    } catch(e) {
      return { display: timeStr || "", full: timeStr || "" };
    }
  }

  function formatRelativeTime(ts, timeStr) {
    return formatMessageTime(ts, timeStr).display;
  }

  function cleanStr(s) {
    if (!s) return "";
    return s.toLowerCase()
      .normalize("NFD").replace(/[\u0300-\u036f]/g, "")
      .replace(/^[#🔒📢💬📁👥🤖\s]+/, "")
      .replace(/[^a-z0-9\s]/g, " ")
      .replace(/\s+/g, " ")
      .trim();
  }

  function logToServer(event, details) {
    try {
      fetch("http://127.0.0.1:8787/api/log", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ event, details, timestamp: new Date().toISOString() })
      }).catch(() => {});
    } catch(e) {}
  }

  // Complete, Robust DOM & React Click Dispatcher
  function deepClick(element) {
    if (!element) return false;
    try {
      const rect = element.getBoundingClientRect();
      const cx = rect.left + rect.width / 2;
      const cy = rect.top + rect.height / 2;
      const opts = { bubbles: true, cancelable: true, view: window, clientX: cx, clientY: cy, button: 0 };

      // 1. PointerDown & MouseDown
      element.dispatchEvent(new PointerEvent("pointerdown", { ...opts, buttons: 1 }));
      element.dispatchEvent(new MouseEvent("mousedown", { ...opts, buttons: 1 }));

      // 2. PointerUp & MouseUp
      element.dispatchEvent(new PointerEvent("pointerup", { ...opts, buttons: 0 }));
      element.dispatchEvent(new MouseEvent("mouseup", { ...opts, buttons: 0 }));

      // 3. React Synthetic onClick handler on element itself
      for (const k of Object.keys(element)) {
        if (k.startsWith("__reactProps") || k.startsWith("__reactEventHandlers")) {
          const props = element[k];
          if (props && typeof props.onClick === "function") {
            try {
              props.onClick({
                stopPropagation: () => {},
                preventDefault: () => {},
                target: element,
                currentTarget: element,
                nativeEvent: new MouseEvent("click", opts)
              });
            } catch(e) {}
          }
        }
      }

      // 4. Native DOM click
      if (typeof element.click === "function") {
        element.click();
      }

      // 5. Standard MouseEvent
      element.dispatchEvent(new MouseEvent("click", opts));

      // 6. Closest clickable button if applicable
      const p = element.closest("button, a, [role='button'], [class*='cursor-pointer']");
      if (p && p !== element && typeof p.click === "function") {
        p.click();
      }

      return true;
    } catch (e) {
      console.error("[BUZZ CLICK ERROR]", e);
      return false;
    }
  }

  function highlightElement(el) {
    if (!el) return;
    try { el.scrollIntoView({ behavior: "smooth", block: "nearest" }); } catch(e) {}
    const origOutline = el.style.outline;
    const origBoxShadow = el.style.boxShadow;
    el.style.outline = "2px solid #38bdf8";
    el.style.boxShadow = "0 0 16px rgba(56, 189, 248, 0.7)";
    setTimeout(() => {
      el.style.outline = origOutline;
      el.style.boxShadow = origBoxShadow;
    }, 2500);
  }

  function focusInputComposer() {
    const inputs = Array.from(document.querySelectorAll("textarea, [contenteditable='true'], [role='textbox'], input[type='text']"));
    const chatInputs = inputs.filter(inp => {
      if (inp.id === "buzz-hub-search" || inp.closest("#buzz-hub-drawer")) return false;
      const r = inp.getBoundingClientRect();
      return r.width > 160 && r.top > window.innerHeight * 0.65 && r.left > 240;
    });
    const target = chatInputs[chatInputs.length - 1];
    if (target) {
      target.focus();
    }
  }

  // =========================================================================
  // UNIVERSAL WORKSPACE, SECTION & CATEGORY NAVIGATOR
  // =========================================================================

  function getAllRailWorkspaceButtons() {
    const all = Array.from(document.querySelectorAll("button, a, [role='button']")).filter(el => {
      if (el.id === "buzz-rail-hub-btn" || el.id === "buzz-hub-pill") return false;
      const r = el.getBoundingClientRect();
      const title = (el.getAttribute("title") || el.getAttribute("aria-label") || "").toLowerCase();
      if (title.includes("add") || title.includes("tạo") || title.includes("join") || title.includes("tham gia")) return false;
      if (title.includes("setting") || title.includes("cài đặt") || title.includes("profile")) return false;
      return r.left >= 0 && r.left <= 35 && r.width >= 24 && r.width <= 55 && r.height >= 24 && r.height <= 55 && r.top >= 25 && r.top <= (window.innerHeight - 70);
    });

    const unique = [];
    for (const el of all) {
      const r = el.getBoundingClientRect();
      const existing = unique.find(u => Math.abs(u.getBoundingClientRect().top - r.top) < 8);
      if (!existing) {
        unique.push(el);
      }
    }
    unique.sort((a, b) => a.getBoundingClientRect().top - b.getBoundingClientRect().top);
    return unique;
  }

  function getWorkspaceButton(commKey) {
    if (!commKey) return null;
    const cleanKey = cleanStr(commKey);
    const railButtons = getAllRailWorkspaceButtons();
    if (!railButtons.length) return null;

    // 1. Dynamic Title / Tooltip Substring Match (handles "phamgianam — 1 mention", "phuongstory", etc.)
    for (const btn of railButtons) {
      const title = cleanStr(btn.getAttribute("title") || btn.getAttribute("aria-label") || btn.getAttribute("data-tooltip") || "");
      if (title && (title.includes(cleanKey) || cleanKey.includes(title))) {
        return btn;
      }
    }

    // 2. Dynamic LocalStorage Order Match (matches exact index in localStorage['buzz-communities'])
    try {
      const storedComms = JSON.parse(localStorage.getItem("buzz-communities") || "[]");
      if (Array.isArray(storedComms)) {
        const idx = storedComms.findIndex(c => {
          const name = cleanStr(c.name || "");
          return name && (name === cleanKey || name.includes(cleanKey) || cleanKey.includes(name));
        });
        if (idx !== -1 && railButtons[idx]) {
          return railButtons[idx];
        }
      }
    } catch(e) {}

    // 3. Fallback: Inner Text Match (Initial letters or button contents)
    for (const btn of railButtons) {
      const txt = cleanStr(btn.innerText || btn.textContent || "");
      if (txt && (txt === cleanKey || (cleanKey.length >= 3 && cleanKey.startsWith(txt)))) {
        return btn;
      }
    }

    // 4. Fallback to discovered communities index
    const discovered = getDiscoveredCommunities();
    const dIdx = discovered.findIndex(c => c.key === cleanKey || c.key.includes(cleanKey) || cleanKey.includes(c.key));
    if (dIdx !== -1 && railButtons[dIdx]) {
      return railButtons[dIdx];
    }

    return null;
  }

  function switchWorkspace(commKey) {
    const btn = getWorkspaceButton(commKey);
    if (btn) {
      console.log(`[BUZZ NAV] Switching Workspace to ${commKey}`, btn);
      deepClick(btn);
      logToServer("WORKSPACE_SWITCHED", { community: commKey, title: btn.getAttribute("title") });
      return true;
    }
    console.warn(`[BUZZ NAV] Workspace button not found for ${commKey}`);
    return false;
  }

  // Expand ALL collapsed category, section, folder, and group accordions in Column 1
  function expandAllSidebarSections() {
    try {
      const allButtons = Array.from(document.querySelectorAll("button, div[role='button']"));
      for (const el of allButtons) {
        const r = el.getBoundingClientRect();
        if (r.left < 35 || r.left > 345 || r.top < 60 || r.top > (window.innerHeight - 105)) continue;
        if (r.height < 14 || r.height > 50) continue;

        // Strictly exclude profile footer, search, and user status controls
        if (el.closest(".group\\/profile-card, [class*='profile'], [data-sidebar='footer'], footer")) continue;
        const txt = (el.innerText || el.textContent || "").trim().toLowerCase();
        if (txt.includes("online") || txt.includes("offline") || txt.includes("status") || txt.includes("meeting") || txt.includes("settings") || txt.includes("feedback")) continue;
        if (txt.startsWith("search ") || txt === "search everything" || txt === "search") continue;

        const cls = typeof el.className === "string" ? el.className : "";
        if (cls.includes("group/search") || cls.includes("peer/menu-button") || el.getAttribute("aria-haspopup") === "menu") continue;
        if (el.getAttribute("data-radix-collection-item") !== null) continue;

        // Check if this is a section / folder toggle header
        const isSectionHeader = cls.includes("group/section-label") || (cls.includes("shrink-0") && cls.includes("rounded-md"));
        let isCollapsed = el.getAttribute("aria-expanded") === "false" ||
                          el.getAttribute("data-state") === "closed" ||
                          el.classList.contains("collapsed") ||
                          el.classList.contains("is-collapsed");

        if (isSectionHeader) {
          const container = el.closest(".rounded-md, [class*='transition-all'], div.relative") || el.parentElement;
          if (container) {
            const cr = container.getBoundingClientRect();
            const hasChildList = container.querySelector(".w-full.text-sm, ul, ol, [role='group']");
            if (!hasChildList || cr.height <= 52) {
              isCollapsed = true;
            }
          }
        }

        if (isCollapsed) {
          console.log("[BUZZ NAV] Auto-expanding collapsed section/folder:", el.innerText || el);
          deepClick(el);
        }
      }
    } catch(e) {}
  }

  let currentNavToken = 0;

  function navigateToMessage(msg) {
    if (!msg) return;
    const navToken = ++currentNavToken;
    closeDrawer();

    // Mark as read locally and notify server
    msg.is_unread = false;
    unreadCount = Math.max(0, messages.filter(m => m.is_unread !== false).length);
    updateBadgeUI();
    updateFilterTabCounts();
    fetch("http://127.0.0.1:8787/api/mark_read", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        community: msg.community || "",
        channel_id: msg.channel_id || msg.channel || "",
        message_id: msg.id || "",
        timestamp: msg.timestamp || 0
      })
    }).catch(() => {});

    try {
      window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", code: "Escape", bubbles: true }));
      const popovers = document.querySelectorAll("[data-radix-popper-content-wrapper], [role='dialog'], [role='menu']");
      popovers.forEach(p => { try { p.remove(); } catch(e) {} });
    } catch(e) {}

    const backBtn = Array.from(document.querySelectorAll("button, a, div, span")).find(el => {
      const t = (el.innerText || el.textContent || "").trim();
      return t === "Back to app" || t === "← Back to app";
    });
    if (backBtn) deepClick(backBtn);

    const commTarget = (msg.community || "").toLowerCase().trim();
    const rawChan = (msg.channel || "").toLowerCase().trim();
    const senderTarget = (msg.sender || "").toLowerCase().trim();
    const isDM = msg.is_dm === true || rawChan.startsWith("dm") || rawChan.includes("tin nhan rieng");
    const chanClean = isDM ? "" : cleanStr(rawChan.split("(")[0]);

    console.log(`[BUZZ NAV] Universal Section/Category Navigation -> Community: [${commTarget}], Target: [${rawChan}], isDM: ${isDM}, Sender: [${senderTarget}]`);
    logToServer("NAVIGATE_START", { community: commTarget, channel: rawChan, isDM, sender: senderTarget });

    // Step 1: Switch Workspace in DOM
    switchWorkspace(commTarget);

    // Notify backend
    fetch("http://127.0.0.1:8787/api/nav_exec", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(msg)
    }).catch(() => {});

    // Step 2: Search and enter target Channel / DM / Folder in Sidebar
    function tryEnterTarget(attemptsLeft) {
      if (navToken !== currentNavToken) return;
      expandAllSidebarSections();

      // Tier 0: Direct Stream List Channel Matcher (Fast & 100% resilient across scroll and virtualization)
      const streamList = document.getElementById("sidebar-stream-list") || document.querySelector('[data-testid="stream-list"]');
      let targetElement = null;
      let matchedIsFolder = false;

      if (streamList && !isDM && chanClean) {
        const streamLis = Array.from(streamList.querySelectorAll("li[data-sidebar='menu-item'], li"));
        for (const li of streamLis) {
          const btn = li.querySelector("button, [role='button']") || li;
          const textClean = cleanStr(li.textContent || "");
          if (textClean && (textClean === chanClean || textClean === `# ${chanClean}` || textClean.startsWith(chanClean) || (chanClean.length >= 4 && textClean.includes(chanClean)))) {
            targetElement = btn;
            break;
          }
        }
      }

      const allSidebar = Array.from(document.querySelectorAll("button, a, [role='button'], li, div, span")).filter(el => {
        const r = el.getBoundingClientRect();
        if (r.left < 35 || r.left > 355 || r.width < 18 || r.height < 14 || r.top < 50) return false;
        // Exclude profile footer, search inputs, modal dialogs
        if (el.closest(".group\\/profile-card, [class*='profile'], [data-sidebar='footer'], footer")) return false;
        const cls = typeof el.className === "string" ? el.className : "";
        if (cls.includes("group/search") || cls.includes("search-input") || el.closest("[role='dialog']") || el.closest("[data-radix-popper-content-wrapper]")) return false;
        if (el.tagName === "INPUT" || el.querySelector("input")) return false;
        const txt = (el.innerText || el.textContent || "").trim().toLowerCase();
        if (txt.startsWith("search ") || txt === "search everything" || txt === "search") return false;
        if (txt.includes("online") || txt.includes("offline") || txt.includes("status") || txt.includes("meeting") || txt.includes("settings") || txt.includes("feedback")) return false;
        return true;
      });

      // Tier 1: Real Channel Buttons & DM Buttons (inside li.group/menu-item or peer/menu-button)
      const channelButtons = allSidebar.filter(el => {
        const cls = typeof el.className === "string" ? el.className : "";
        const isMenuBtn = cls.includes("peer/menu-button") || el.closest(".group\\/menu-item, li, [role='listitem']");
        const isHeader = cls.includes("group/section-label") || (cls.includes("shrink-0") && cls.includes("rounded-md") && !cls.includes("peer/menu-button"));
        return isMenuBtn && !isHeader;
      });

      // Tier 2: Folder / Section Headers (to expand if target is nested inside)
      const folderHeaders = allSidebar.filter(el => {
        const cls = typeof el.className === "string" ? el.className : "";
        return cls.includes("group/section-label") || (cls.includes("shrink-0") && cls.includes("rounded-md") && !cls.includes("peer/menu-button"));
      });

      // 1. Direct Messages: Match strictly by recipient / contact name
      if (isDM) {
        let dmContact = "";
        const m = (msg.channel || "").match(/\((.*?)\)/);
        if (m && m[1]) {
          dmContact = cleanStr(m[1]);
        }
        if (!dmContact && senderTarget && !["ncthang", "ncthangdz", "you", "thanh vien", "thành viên"].includes(senderTarget)) {
          dmContact = cleanStr(senderTarget);
        }

        if (dmContact) {
          for (const el of channelButtons) {
            const textClean = cleanStr(el.innerText || el.textContent || "");
            if (textClean && (textClean === dmContact || textClean.includes(dmContact) || dmContact.includes(textClean))) {
              targetElement = el;
              break;
            }
          }
        }
      }

      // 2. Channel Match in Tier 1 (Actual Channel Buttons)
      if (!targetElement && !isDM && chanClean && chanClean.length >= 2) {
        // Pass 1: exact match on channel button
        for (const el of channelButtons) {
          const textClean = cleanStr(el.innerText || el.textContent || "");
          if (textClean && (textClean === chanClean || textClean === `# ${chanClean}` || textClean === `#${chanClean}`)) {
            targetElement = el;
            break;
          }
        }
        // Pass 2: startsWith / endsWith match
        if (!targetElement) {
          for (const el of channelButtons) {
            const textClean = cleanStr(el.innerText || el.textContent || "");
            if (textClean && (textClean.startsWith(chanClean) || chanClean.startsWith(textClean))) {
              targetElement = el;
              break;
            }
          }
        }
        // Pass 3: contains match (only for length >= 4 to avoid collisions)
        if (!targetElement && chanClean.length >= 4) {
          for (const el of channelButtons) {
            const textClean = cleanStr(el.innerText || el.textContent || "");
            if (textClean && textClean.length >= 4 && (textClean.includes(chanClean) || chanClean.includes(textClean))) {
              targetElement = el;
              break;
            }
          }
        }
      }

      // 3. If no channel button found yet, check Tier 2 (Folder Headers) to expand the parent folder
      if (!targetElement && !isDM && chanClean && chanClean.length >= 2) {
        for (const el of folderHeaders) {
          const textClean = cleanStr(el.innerText || el.textContent || "");
          if (textClean && (textClean === chanClean || (chanClean.length >= 4 && (textClean.includes(chanClean) || chanClean.includes(textClean))))) {
            targetElement = el;
            matchedIsFolder = true;
            break;
          }
        }
      }

      // 4. System Section Match (Pulse, Projects, Agents, Workflows, Forums)
      if (!targetElement && chanClean) {
        const sysTerms = ["pulse", "agents", "workflows", "forums", "projects", "inbox"];
        for (const term of sysTerms) {
          if (chanClean.includes(term)) {
            for (const el of allSidebar) {
              const textClean = cleanStr(el.innerText || el.textContent || "");
              if (textClean === term || textClean.includes(term)) {
                targetElement = el;
                break;
              }
            }
            if (targetElement) break;
          }
        }
      }

      // 5. Fallback scan across all sidebar interactive elements
      if (!targetElement && !isDM && chanClean) {
        for (const el of allSidebar) {
          const textClean = cleanStr(el.innerText || el.textContent || "");
          if (textClean && (textClean === chanClean || textClean === `# ${chanClean}` || (chanClean.length >= 4 && textClean.includes(chanClean)))) {
            targetElement = el;
            break;
          }
        }
      }

      if (targetElement) {
        const innerBtn = targetElement.querySelector("button, a, [role='button']");
        const parentBtn = targetElement.closest("button, a, [role='button']");
        let clickable = innerBtn || parentBtn || targetElement;

        if (matchedIsFolder) {
          // If we matched a folder header, click it to expand it, then continue retrying to click the child channel inside
          console.log(`[BUZZ NAV] Expanding Parent Folder Header: [${rawChan}]`, clickable);
          logToServer("FOLDER_EXPAND_TRIGGERED", { folder: rawChan });
          deepClick(clickable);
          setTimeout(() => tryEnterTarget(attemptsLeft - 1), 180);
          return;
        }

        console.log(`[BUZZ NAV] Activated Sidebar Target (Category/Channel): [${rawChan}]`, clickable);
        logToServer("SECTION_TARGET_CLICKED", { channel: rawChan, elementTag: clickable.tagName, class: clickable.className });
        
        try {
          clickable.scrollIntoView({ behavior: "smooth", block: "center", inline: "nearest" });
        } catch(e) {}

        const innerSpan = clickable.querySelector("span, div") || clickable;
        deepClick(innerSpan);
        if (clickable !== innerSpan) {
          deepClick(clickable);
        }

        highlightElement(clickable);
        setTimeout(() => {
          if (navToken === currentNavToken) {
            spotlightTargetMessage(msg, 25, navToken);
          }
        }, 350);
      } else if (attemptsLeft > 0) {
        if (attemptsLeft === 24 || attemptsLeft === 15) {
          switchWorkspace(commTarget);
        }
        setTimeout(() => tryEnterTarget(attemptsLeft - 1), 180);
      } else {
        logToServer("TARGET_SEARCH_TIMEOUT", { channel: rawChan });
        setTimeout(() => {
          if (navToken === currentNavToken) {
            spotlightTargetMessage(msg, 15, navToken);
          }
        }, 300);
      }
    }

    setTimeout(() => tryEnterTarget(35), 280);
  }

  // =========================================================================
  // MESSAGE-LEVEL PRECISE SCROLLING & SPOTLIGHT ENGINE
  // =========================================================================

  let activeSpotlightDismissTimer = null;
  let activeSpotlightKeyHandler = null;

  function clearAllSpotlights() {
    try {
      if (activeSpotlightDismissTimer) {
        clearTimeout(activeSpotlightDismissTimer);
        activeSpotlightDismissTimer = null;
      }
      if (activeSpotlightKeyHandler) {
        document.removeEventListener("keydown", activeSpotlightKeyHandler);
        activeSpotlightKeyHandler = null;
      }
      document.querySelectorAll(".buzz-spotlight-active").forEach(node => {
        node.classList.remove("buzz-spotlight-active");
      });
      document.querySelectorAll(".buzz-spotlight-badge, .buzz-spotlight-pointer").forEach(node => node.remove());
      document.querySelectorAll(".buzz-ping-text-mark").forEach(mark => {
        const parent = mark.parentNode;
        if (parent) {
          while (mark.firstChild) parent.insertBefore(mark.firstChild, mark);
          mark.remove();
        }
      });
    } catch(e) {}
  }

  function applySpotlightEffect(el, msg) {
    if (!el) return;
    try {
      clearAllSpotlights();

      el.classList.add("buzz-spotlight-active");
      el.style.setProperty("position", "relative", "important");
      el.style.setProperty("overflow", "visible", "important");

      const senderName = msg.sender || "Thành viên";
      const chanName = msg.channel || "";
      const timeStr = msg.time || "";

      // 1. Header Target Badge Attached to Message Bubble
      const badge = document.createElement("div");
      badge.className = "buzz-spotlight-badge";
      badge.innerHTML = `
        <span class="buzz-badge-icon">🎯</span>
        <span class="buzz-badge-title">TIN NHẮN ĐÃ CHỌN · ${senderName}</span>
        ${chanName ? `<span class="buzz-badge-chan">#${chanName}</span>` : ""}
        ${timeStr ? `<span class="buzz-badge-time">${timeStr}</span>` : ""}
        <span class="buzz-badge-close" title="Bỏ làm nổi bật (Esc)">✕</span>
      `;
      const closeBtn = badge.querySelector(".buzz-badge-close");
      if (closeBtn) {
        closeBtn.addEventListener("click", (e) => {
          e.stopPropagation();
          clearAllSpotlights();
        });
      }
      el.appendChild(badge);

      // 2. Left Pinpoint Pointer Arrow
      const pointer = document.createElement("div");
      pointer.className = "buzz-spotlight-pointer";
      pointer.innerHTML = "👉";
      el.appendChild(pointer);

      // 3. Text Highlighter (Bôi màu / Highlight text content)
      if (msg.content) {
        const rawContent = msg.content.trim();
        const snippet = rawContent.slice(0, 35).trim();
        const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT, null, false);
        let node;
        let highlighted = false;
        while ((node = walker.nextNode()) && !highlighted) {
          if (node.parentElement && (node.parentElement.classList.contains("buzz-spotlight-badge") || node.parentElement.classList.contains("buzz-badge-title"))) continue;
          const text = node.nodeValue || "";
          if (snippet && text.includes(snippet)) {
            const idx = text.indexOf(snippet);
            const span = document.createElement("mark");
            span.className = "buzz-ping-text-mark";
            span.textContent = snippet;
            const afterText = document.createTextNode(text.substring(idx + snippet.length));
            node.nodeValue = text.substring(0, idx);
            if (node.parentNode) {
              node.parentNode.insertBefore(span, node.nextSibling);
              node.parentNode.insertBefore(afterText, span.nextSibling);
              highlighted = true;
            }
          }
        }
      }

      // Accurate dual scrolling (Direct container scrollTo + scrollIntoView)
      const scrollParent = el.closest('[class*="overflow-y-auto"], [class*="overflow-auto"], main, section, [role="log"]') || findChatScrollContainer();
      if (scrollParent) {
        const parentRect = scrollParent.getBoundingClientRect();
        const elRect = el.getBoundingClientRect();
        const targetScrollTop = scrollParent.scrollTop + (elRect.top - parentRect.top) - (parentRect.height / 2) + (elRect.height / 2);
        scrollParent.scrollTo({ top: Math.max(0, targetScrollTop), behavior: "smooth" });
      }
      try {
        el.scrollIntoView({ behavior: "smooth", block: "center", inline: "nearest" });
      } catch(e) {}

      // Key listener for Escape
      activeSpotlightKeyHandler = (e) => {
        if (e.key === "Escape") {
          clearAllSpotlights();
        }
      };
      document.addEventListener("keydown", activeSpotlightKeyHandler);

      // Auto clear after 25 seconds
      activeSpotlightDismissTimer = setTimeout(() => {
        clearAllSpotlights();
      }, 25000);
    } catch(e) {
      console.error("[BUZZ SPOTLIGHT ERROR]", e);
    }
  }

  function findMessageRow(leafEl) {
    if (!leafEl) return null;
    let cur = leafEl;
    let bestRow = leafEl;

    while (cur && cur !== document.body && cur.tagName !== "MAIN") {
      const p = cur.parentElement;
      if (!p || p === document.body || p.tagName === "MAIN") break;

      const pr = p.getBoundingClientRect();
      const cr = cur.getBoundingClientRect();

      const isScrollable = (p.scrollHeight > p.clientHeight + 30) ||
        window.getComputedStyle(p).overflowY === "auto" ||
        window.getComputedStyle(p).overflowY === "scroll";

      const childCandidates = Array.from(p.children).filter(c => {
        const r = c.getBoundingClientRect();
        return r.height >= 18 && r.width >= 90;
      });

      if (isScrollable || childCandidates.length >= 3 || pr.height > 450) {
        bestRow = cur;
        break;
      }

      if (cr.height >= 24 && cr.left >= 180 && cr.top >= 65) {
        bestRow = cur;
      }

      cur = p;
    }

    return bestRow;
  }

  function spotlightInMainChatPane(msg, attemptsLeft, navToken) {
    if (!msg || (navToken && navToken !== currentNavToken)) return;
    const cleanTargetContent = cleanStr(msg.content);
    const rawWords = (msg.content || "").trim().split(/\s+/).filter(w => w.length > 2);
    const searchSnippet = rawWords.slice(0, 4).join(" ").toLowerCase();

    const mainChatElements = Array.from(document.querySelectorAll("p, span, div, li, a, mark, em, strong")).filter(el => {
      if (el.id === "buzz-hub-drawer" || el.id === "buzz-hub-pill" || el.id === "buzz-rail-hub-btn") return false;
      if (el.closest("#buzz-hub-drawer, #buzz-hub-pill, #buzz-rail-hub-btn, nav, aside, [data-sidebar], header, [data-header]")) return false;
      const r = el.getBoundingClientRect();
      return r.left >= 180 && r.width >= 20 && r.height >= 10 && r.height <= 350 &&
             r.top >= 65 && r.top <= (window.innerHeight - 100) &&
             el.children.length <= 6;
    });

    let best = null;
    let maxScore = 0;

    for (const el of mainChatElements) {
      const txt = (el.innerText || el.textContent || "").trim();
      if (!txt) continue;
      const txtClean = cleanStr(txt);
      let score = 0;

      if (cleanTargetContent && txtClean.includes(cleanTargetContent)) score += 100;
      else if (searchSnippet && txt.toLowerCase().includes(searchSnippet)) score += 70;
      else {
        let matched = 0;
        for (const w of rawWords) {
          if (txt.toLowerCase().includes(w.toLowerCase())) matched++;
        }
        if (matched >= 2) score += (matched * 15);
      }

      if (el.classList.contains("message-markdown") || el.classList.contains("text-message")) score += 25;

      if (score > maxScore) {
        maxScore = score;
        best = el;
      }
    }

    const minScore = cleanTargetContent ? 65 : 35;
    if (best && maxScore >= minScore) {
      const container = findMessageRow(best);
      console.log("[BUZZ SPOTLIGHT] Focused in Main Conversation Pane:", container);
      logToServer("MESSAGE_SPOTLIGHTED_MAIN", { sender: msg.sender, score: maxScore });
      applySpotlightEffect(container, msg);
    } else if (attemptsLeft > 0) {
      setTimeout(() => spotlightInMainChatPane(msg, attemptsLeft - 1, navToken), 200);
    }
  }

  function findChatScrollContainer() {
    const candidateContainers = Array.from(document.querySelectorAll("main, section, div, [role='log']")).filter(el => {
      if (el.id === "buzz-hub-drawer" || el.id === "buzz-hub-pill" || el.id === "buzz-rail-hub-btn") return false;
      const r = el.getBoundingClientRect();
      if (r.left < 180 || r.width < 200 || r.height < 150) return false;
      const st = window.getComputedStyle(el);
      const isScrollable = (st.overflowY === "auto" || st.overflowY === "scroll" || st.overflow === "auto" || st.overflow === "scroll");
      return isScrollable && el.scrollHeight > el.clientHeight;
    });
    candidateContainers.sort((a, b) => b.scrollHeight - a.scrollHeight);
    return candidateContainers[0] || null;
  }

  function spotlightTargetMessage(msg, attemptsLeft = 25, navToken) {
    if (!msg || (!msg.content && !msg.sender) || (navToken && navToken !== currentNavToken)) return;
    const cleanTargetContent = cleanStr(msg.content);
    const cleanTargetSender = cleanStr(msg.sender);
    const rawWords = (msg.content || "").trim().split(/\s+/).filter(w => w.length > 2);
    const searchSnippet = rawWords.slice(0, 4).join(" ").toLowerCase();

    const candidateElements = Array.from(document.querySelectorAll("p, span, div, li, a, mark, em, strong")).filter(el => {
      if (el.id === "buzz-hub-drawer" || el.id === "buzz-hub-pill" || el.id === "buzz-rail-hub-btn") return false;
      if (el.closest("#buzz-hub-drawer, #buzz-hub-pill, #buzz-rail-hub-btn, nav, aside, [data-sidebar], header, [data-header]")) return false;
      const r = el.getBoundingClientRect();
      return r.left >= 180 && r.width >= 15 && r.height >= 10 && r.height <= 350 &&
             r.top >= 65 && r.top <= (window.innerHeight - 100) &&
             el.children.length <= 6;
    });

    let bestMatch = null;
    let bestScore = 0;

    for (const el of candidateElements) {
      const txt = (el.innerText || el.textContent || "").trim();
      if (!txt) continue;
      const txtClean = cleanStr(txt);
      let score = 0;

      if (cleanTargetContent && txtClean.includes(cleanTargetContent)) score += 80;
      else if (searchSnippet && txt.toLowerCase().includes(searchSnippet)) score += 50;
      else {
        let matchedWords = 0;
        for (const w of rawWords) {
          if (txt.toLowerCase().includes(w.toLowerCase())) matchedWords++;
        }
        if (matchedWords >= 2) score += (matchedWords * 12);
      }

      if (cleanTargetSender && txtClean.includes(cleanTargetSender)) score += 40;
      if (el.classList.contains("message-markdown") || el.classList.contains("text-message")) score += 20;

      if (score > bestScore) {
        bestScore = score;
        bestMatch = el;
      }
    }

    const minScore = cleanTargetContent ? 65 : 35;
    if (bestMatch && bestScore >= minScore) {
      const container = findMessageRow(bestMatch);
      console.log("[BUZZ SPOTLIGHT] Direct Message Spotlight Success:", container);
      logToServer("MESSAGE_SPOTLIGHTED_DIRECT", { sender: msg.sender, score: bestScore });
      applySpotlightEffect(container, msg);
    } else if (attemptsLeft > 0) {
      if (attemptsLeft <= 12 && attemptsLeft % 3 === 0) {
        const scrollCont = findChatScrollContainer();
        if (scrollCont && scrollCont.scrollTop > 0) {
          scrollCont.scrollBy({ top: -350, behavior: "smooth" });
        }
      }
      setTimeout(() => spotlightTargetMessage(msg, attemptsLeft - 1, navToken), 220);
    }
  }

  // =========================================================================
  // MODERN GLASSMORPHIC UI STYLES
  // =========================================================================

  function injectStyles() {
    let style = document.getElementById("buzz-enhancer-styles");
    if (!style) {
      style = document.createElement("style");
      style.id = "buzz-enhancer-styles";
      (document.head || document.documentElement).appendChild(style);
    }
    style.textContent = `
      /* --- Left Rail Dedicated Hub Button --- */
      #buzz-rail-hub-btn {
        position: fixed !important;
        left: 8px !important;
        top: 290px !important;
        width: 36px !important;
        height: 36px !important;
        border-radius: 12px !important;
        background: rgba(24, 24, 28, 0.92) !important;
        backdrop-filter: blur(12px) !important;
        border: 1.5px solid rgba(56, 189, 248, 0.7) !important;
        color: #38bdf8 !important;
        display: flex !important;
        align-items: center !important;
        justify-content: center !important;
        font-size: 16px !important;
        cursor: grab !important;
        z-index: 2147483640 !important;
        box-shadow: 0 4px 16px rgba(0, 0, 0, 0.6), 0 0 10px rgba(56, 189, 248, 0.25) !important;
        user-select: none !important;
        touch-action: none !important;
        transition: transform 0.15s cubic-bezier(0.16, 1, 0.3, 1), box-shadow 0.15s ease !important;
        pointer-events: auto !important;
      }
      #buzz-rail-hub-btn:hover {
        background: #27272a !important;
        border-color: #60a5fa !important;
        transform: scale(1.08) !important;
        box-shadow: 0 6px 20px rgba(56, 189, 248, 0.5) !important;
      }
      #buzz-rail-hub-btn.buzz-is-dragging {
        cursor: grabbing !important;
        transform: scale(1.15) !important;
        border-color: #f59e0b !important;
        box-shadow: 0 12px 30px rgba(0, 0, 0, 0.9), 0 0 20px rgba(245, 158, 11, 0.8) !important;
      }
      #buzz-rail-hub-btn.has-unread {
        border-color: #f59e0b !important;
        animation: buzzPulse 2s infinite ease-in-out !important;
      }
      #buzz-rail-badge {
        position: absolute !important;
        top: -4px !important;
        right: -4px !important;
        background: #ef4444 !important;
        color: #ffffff !important;
        font-size: 10px !important;
        font-weight: 800 !important;
        padding: 1px 5px !important;
        border-radius: 10px !important;
        border: 1.5px solid #18181c !important;
        display: none;
      }

      /* --- Floating Header Pill (Modern Glassmorphic Capsule) --- */
      #buzz-hub-pill {
        position: fixed !important;
        top: 50px !important;
        right: 24px !important;
        width: max-content !important;
        max-width: 340px !important;
        z-index: 2147483640 !important;
        display: flex !important;
        align-items: center !important;
        gap: 8px !important;
        padding: 5px 12px !important;
        background: rgba(18, 18, 22, 0.88) !important;
        backdrop-filter: blur(16px) !important;
        border: 1px solid rgba(56, 189, 248, 0.6) !important;
        border-radius: 20px !important;
        color: #f4f4f5 !important;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif !important;
        font-size: 12px !important;
        font-weight: 600 !important;
        cursor: grab !important;
        box-shadow: 0 4px 18px rgba(0, 0, 0, 0.65), 0 0 12px rgba(56, 189, 248, 0.3) !important;
        user-select: none !important;
        touch-action: none !important;
        pointer-events: auto !important;
        transition: transform 0.15s cubic-bezier(0.16, 1, 0.3, 1), box-shadow 0.15s ease, border-color 0.15s ease !important;
      }
      #buzz-hub-pill:hover {
        background: rgba(39, 39, 42, 0.95) !important;
        border-color: #60a5fa !important;
        transform: translateY(-1px) scale(1.02) !important;
        box-shadow: 0 6px 24px rgba(56, 189, 248, 0.45) !important;
      }
      #buzz-hub-pill.buzz-is-dragging {
        cursor: grabbing !important;
        transform: scale(1.08) !important;
        border-color: #f59e0b !important;
        box-shadow: 0 12px 32px rgba(0, 0, 0, 0.85), 0 0 22px rgba(245, 158, 11, 0.8) !important;
      }
      .buzz-drag-handle {
        display: inline-flex !important;
        align-items: center !important;
        color: #71717a !important;
        font-size: 12px !important;
        cursor: grab !important;
      }
      #buzz-hub-pill.buzz-is-dragging .buzz-drag-handle {
        cursor: grabbing !important;
        color: #fbbf24 !important;
      }
      .buzz-status-dot {
        width: 7px;
        height: 7px;
        border-radius: 50%;
        background: #10b981;
        box-shadow: 0 0 8px #10b981;
      }
      .buzz-unread-badge {
        background: #ef4444;
        color: #ffffff;
        font-size: 10px;
        font-weight: 800;
        padding: 1px 6px;
        border-radius: 10px;
      }
      .buzz-kbd-badge {
        background: rgba(255, 255, 255, 0.08);
        border: 1px solid rgba(255, 255, 255, 0.14);
        color: #a1a1aa;
        font-size: 10px;
        font-weight: 600;
        padding: 1px 5px;
        border-radius: 4px;
        font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
      }
      #buzz-hub-pill.has-unread {
        border-color: #f59e0b !important;
        animation: buzzPulse 2.2s infinite ease-in-out !important;
      }
      @keyframes buzzPulse {
        0% { box-shadow: 0 0 6px rgba(245, 158, 11, 0.4); }
        50% { box-shadow: 0 0 22px rgba(245, 158, 11, 0.85); }
        100% { box-shadow: 0 0 6px rgba(245, 158, 11, 0.4); }
      }

      /* --- Linear-Style Toast Notifications --- */
      #buzz-inapp-toast-container {
        position: fixed !important;
        bottom: 24px !important;
        right: 24px !important;
        z-index: 2147483647 !important;
        display: flex !important;
        flex-direction: column !important;
        gap: 8px !important;
        pointer-events: none !important;
      }
      .buzz-toast-card {
        pointer-events: auto !important;
        width: 440px !important;
        max-width: calc(100vw - 48px) !important;
        background: rgba(18, 18, 22, 0.94) !important;
        backdrop-filter: blur(20px) !important;
        border: 1px solid rgba(56, 189, 248, 0.5) !important;
        border-radius: 12px !important;
        padding: 12px 16px !important;
        color: #f4f4f5 !important;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif !important;
        box-shadow: 0 14px 36px rgba(0, 0, 0, 0.85) !important;
        cursor: pointer !important;
        position: relative !important;
        overflow: hidden !important;
        animation: toastSlideUp 0.3s cubic-bezier(0.16, 1, 0.3, 1) !important;
        transition: transform 0.15s ease, border-color 0.15s ease !important;
      }
      .buzz-toast-card:hover {
        transform: translateY(-2px) !important;
        border-color: #38bdf8 !important;
      }
      @keyframes toastSlideUp {
        from { opacity: 0; transform: translateY(20px) scale(0.96); }
        to { opacity: 1; transform: translateY(0) scale(1); }
      }
      .buzz-toast-progress {
        position: absolute;
        bottom: 0;
        left: 0;
        height: 2px;
        background: linear-gradient(90deg, #38bdf8, #818cf8);
        width: 100%;
        animation: toastProgress 5s linear forwards;
      }
      @keyframes toastProgress {
        from { width: 100%; }
        to { width: 0%; }
      }

      /* --- Unified Slide-Over Drawer (Linear / Raycast Style) --- */
      #buzz-hub-drawer-overlay {
        position: fixed !important;
        inset: 0 !important;
        background: rgba(0, 0, 0, 0.7) !important;
        backdrop-filter: blur(4px) !important;
        z-index: 2147483645 !important;
        display: none !important;
        pointer-events: auto !important;
      }
      #buzz-hub-drawer-overlay.open {
        display: block !important;
      }
      #buzz-hub-drawer {
        position: fixed !important;
        top: 0 !important;
        right: 0 !important;
        bottom: 0 !important;
        width: 590px !important;
        max-width: 92vw !important;
        background: #111115 !important;
        border-left: 1px solid rgba(255, 255, 255, 0.1) !important;
        z-index: 2147483646 !important;
        display: none !important;
        flex-direction: column !important;
        box-shadow: -12px 0 45px rgba(0, 0, 0, 0.88) !important;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif !important;
      }
      #buzz-hub-drawer.open {
        display: flex !important;
      }

      /* Drawer Header */
      .buzz-drawer-header {
        padding: 14px 18px;
        border-bottom: 1px solid rgba(255, 255, 255, 0.08);
        display: flex;
        align-items: center;
        justify-content: space-between;
        background: #16161b;
      }
      .buzz-drawer-title {
        font-size: 14.5px;
        font-weight: 700;
        color: #f4f4f5;
        display: flex;
        align-items: center;
        gap: 8px;
      }
      .buzz-drawer-actions {
        display: flex;
        align-items: center;
        gap: 6px;
      }
      .buzz-hdr-btn {
        background: rgba(255, 255, 255, 0.06);
        border: 1px solid rgba(255, 255, 255, 0.1);
        color: #d4d4d8;
        padding: 4px 10px;
        border-radius: 6px;
        font-size: 11.5px;
        font-weight: 500;
        cursor: pointer;
        display: flex;
        align-items: center;
        gap: 4px;
        transition: all 0.15s ease;
      }
      .buzz-hdr-btn:hover {
        background: rgba(255, 255, 255, 0.12);
        color: #ffffff;
        border-color: rgba(255, 255, 255, 0.2);
      }
      .buzz-hdr-btn.active {
        background: rgba(239, 68, 68, 0.2);
        color: #f87171;
        border-color: rgba(239, 68, 68, 0.4);
        font-weight: 600;
      }
      .buzz-hdr-btn.close-btn {
        padding: 4px 8px;
        font-size: 14px;
      }

      /* Search Bar */
      .buzz-drawer-search-bar {
        padding: 10px 18px;
        background: #141418;
        border-bottom: 1px solid rgba(255, 255, 255, 0.06);
        display: flex;
        align-items: center;
        gap: 8px;
        position: relative;
      }
      .buzz-drawer-search-input {
        flex: 1;
        background: #1f1f24;
        border: 1px solid rgba(255, 255, 255, 0.1);
        border-radius: 8px;
        padding: 8px 32px 8px 12px;
        color: #f4f4f5;
        font-size: 12.5px;
        outline: none;
        transition: border-color 0.15s ease, box-shadow 0.15s ease;
      }
      .buzz-drawer-search-input:focus {
        border-color: #38bdf8;
        box-shadow: 0 0 0 2px rgba(56, 189, 248, 0.2);
      }
      .buzz-search-clear {
        position: absolute;
        right: 28px;
        background: transparent;
        border: none;
        color: #71717a;
        cursor: pointer;
        font-size: 12px;
        display: none;
      }
      .buzz-search-clear:hover { color: #f4f4f5; }

      /* Category & Type Secondary Filter Chips */
      .buzz-type-filter-bar {
        padding: 6px 18px;
        background: #121216;
        border-bottom: 1px solid rgba(255, 255, 255, 0.04);
        display: flex;
        align-items: center;
        gap: 6px;
        overflow-x: auto;
      }
      .buzz-type-chip {
        background: transparent;
        border: 1px solid rgba(255, 255, 255, 0.06);
        border-radius: 12px;
        padding: 2px 9px;
        font-size: 11px;
        color: #a1a1aa;
        cursor: pointer;
        display: flex;
        align-items: center;
        gap: 4px;
        white-space: nowrap;
        transition: all 0.15s ease;
      }
      .buzz-type-chip:hover {
        background: rgba(255, 255, 255, 0.06);
        color: #f4f4f5;
      }
      .buzz-type-chip.active {
        background: rgba(56, 189, 248, 0.18);
        border-color: #38bdf8;
        color: #38bdf8;
        font-weight: 600;
      }

      /* Segmented Filter Tabs */
      .buzz-drawer-filters {
        padding: 8px 18px;
        background: #141418;
        border-bottom: 1px solid rgba(255, 255, 255, 0.06);
        display: flex;
        align-items: center;
        gap: 6px;
        overflow-x: auto;
      }
      .buzz-filter-tab {
        background: rgba(255, 255, 255, 0.04);
        border: 1px solid rgba(255, 255, 255, 0.08);
        border-radius: 6px;
        padding: 5px 10px;
        font-size: 11.5px;
        font-weight: 500;
        color: #a1a1aa;
        cursor: pointer;
        display: flex;
        align-items: center;
        gap: 6px;
        white-space: nowrap;
        transition: all 0.15s ease;
      }
      .buzz-filter-tab:hover {
        background: rgba(255, 255, 255, 0.08);
        color: #f4f4f5;
      }
      .buzz-filter-tab.active {
        background: rgba(56, 189, 248, 0.15);
        border-color: #38bdf8;
        color: #38bdf8;
        font-weight: 600;
      }
      .buzz-filter-badge {
        font-size: 10px;
        font-weight: 700;
        padding: 1px 5px;
        border-radius: 8px;
        background: rgba(255, 255, 255, 0.1);
        color: #e4e4e7;
      }
      .buzz-filter-tab.active .buzz-filter-badge {
        background: #38bdf8;
        color: #0f172a;
      }

      /* Message List (Optimized for 60fps scrolling) */
      #buzz-drawer-msg-list {
        flex: 1;
        overflow-y: auto;
        padding: 10px 14px;
        display: flex;
        flex-direction: column;
        gap: 8px;
        contain: content;
        transform: translateZ(0);
        will-change: scroll-position;
        -webkit-overflow-scrolling: touch;
      }

      /* Compact & Actionable Message Card (Linear Style - Hardware Accelerated) */
      .buzz-msg-card {
        background: rgba(24, 24, 28, 0.9);
        border: 1px solid rgba(255, 255, 255, 0.07);
        border-radius: 10px;
        padding: 10px 14px;
        cursor: pointer;
        display: flex;
        gap: 12px;
        align-items: flex-start;
        transition: transform 0.1s ease, border-color 0.1s ease, background 0.1s ease;
        position: relative;
        contain: content;
        transform: translateZ(0);
        will-change: transform;
      }
      .buzz-msg-card:hover {
        background: rgba(39, 39, 44, 0.98);
        border-color: rgba(56, 189, 248, 0.6);
        transform: translateY(-1px);
        box-shadow: 0 4px 14px rgba(0, 0, 0, 0.4);
      }
      .buzz-msg-card.buzz-kb-selected {
        background: rgba(56, 189, 248, 0.15) !important;
        border-color: #38bdf8 !important;
        box-shadow: 0 0 14px rgba(56, 189, 248, 0.35) !important;
      }
      .buzz-msg-card.is-unread {
        border-left: 3px solid #ef4444 !important;
        background: rgba(239, 68, 68, 0.05);
      }
      .buzz-card-avatar {
        width: 32px;
        height: 32px;
        border-radius: 8px;
        display: flex;
        align-items: center;
        justify-content: center;
        font-weight: 700;
        font-size: 12px;
        color: #0f172a;
        flex-shrink: 0;
        margin-top: 2px;
      }
      .buzz-card-main {
        flex: 1;
        min-width: 0;
        display: flex;
        flex-direction: column;
        gap: 4px;
      }
      .buzz-card-top-row {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 8px;
      }
      .buzz-card-tags {
        display: flex;
        align-items: center;
        gap: 6px;
        flex-wrap: wrap;
      }
      .buzz-comm-tag {
        font-size: 10.5px;
        font-weight: 700;
        padding: 1px 7px;
        border-radius: 4px;
        letter-spacing: 0.2px;
      }
      .buzz-section-tag {
        font-size: 10.5px;
        font-weight: 600;
        padding: 1px 6px;
        border-radius: 4px;
        border: 1px solid rgba(255, 255, 255, 0.15);
      }
      .buzz-chan-tag {
        font-size: 11px;
        font-weight: 600;
        color: #93c5fd;
        background: rgba(59, 130, 246, 0.12);
        padding: 1px 6px;
        border-radius: 4px;
        border: 1px solid rgba(59, 130, 246, 0.25);
      }
      .buzz-time-tag {
        font-size: 11px;
        color: #71717a;
        white-space: nowrap;
      }
      .buzz-card-sender {
        font-size: 12.5px;
        font-weight: 700;
        color: #f4f4f5;
      }
      .buzz-card-text {
        font-size: 12.5px;
        color: #d4d4d8;
        line-height: 1.4;
        display: -webkit-box;
        -webkit-line-clamp: 2;
        -webkit-box-orient: vertical;
        overflow: hidden;
        word-break: break-word;
      }
      .buzz-card-action-chip {
        display: none;
        align-items: center;
        gap: 4px;
        font-size: 11px;
        font-weight: 600;
        color: #38bdf8;
        background: rgba(56, 189, 248, 0.15);
        border: 1px solid rgba(56, 189, 248, 0.35);
        border-radius: 4px;
        padding: 2px 8px;
        margin-top: 4px;
        align-self: flex-start;
      }
      .buzz-msg-card:hover .buzz-card-action-chip,
      .buzz-msg-card.buzz-kb-selected .buzz-card-action-chip {
        display: inline-flex;
      }
      .buzz-card-action-row {
        display: flex;
        align-items: center;
        gap: 6px;
        margin-top: 4px;
      }
      .buzz-card-reply-btn {
        background: transparent;
        border: 1px solid rgba(255, 255, 255, 0.1);
        border-radius: 4px;
        padding: 2px 8px;
        font-size: 11px;
        color: #38bdf8;
        cursor: pointer;
        display: none;
        align-items: center;
        gap: 4px;
        transition: all 0.15s ease;
      }
      .buzz-msg-card:hover .buzz-card-reply-btn,
      .buzz-msg-card.buzz-kb-selected .buzz-card-reply-btn {
        display: inline-flex;
      }
      .buzz-card-reply-btn:hover {
        background: rgba(56, 189, 248, 0.15);
        border-color: #38bdf8;
      }
      .buzz-inline-reply-box {
        margin-top: 8px;
        padding-top: 8px;
        border-top: 1px solid rgba(255, 255, 255, 0.08);
        display: flex;
        flex-direction: column;
        gap: 6px;
      }
      .buzz-quick-chips-row {
        display: flex;
        gap: 4px;
        flex-wrap: wrap;
      }
      .buzz-quick-chip {
        background: rgba(255, 255, 255, 0.06);
        border: 1px solid rgba(255, 255, 255, 0.1);
        border-radius: 10px;
        color: #d4d4d8;
        font-size: 11px;
        padding: 2px 7px;
        cursor: pointer;
        transition: all 0.15s ease;
      }
      .buzz-quick-chip:hover {
        background: rgba(56, 189, 248, 0.2);
        color: #38bdf8;
        border-color: rgba(56, 189, 248, 0.4);
      }
      .buzz-inline-reply-input {
        flex: 1;
        background: #18181b;
        border: 1px solid rgba(255, 255, 255, 0.15);
        border-radius: 6px;
        padding: 5px 8px;
        color: #f4f4f5;
        font-size: 12px;
        outline: none;
      }
      .buzz-inline-reply-input:focus {
        border-color: #38bdf8;
        box-shadow: 0 0 0 2px rgba(56, 189, 248, 0.2);
      }
      .buzz-inline-reply-send {
        background: #0284c7;
        color: #ffffff;
        border: none;
        border-radius: 6px;
        padding: 5px 10px;
        font-size: 11.5px;
        font-weight: 600;
        cursor: pointer;
        transition: background 0.15s ease;
      }
      .buzz-inline-reply-send:hover {
        background: #0369a1;
      }

      /* AI Catch-Up Summary Card */
      .buzz-ai-summary-card {
        margin: 10px 14px 4px 14px;
        background: linear-gradient(135deg, rgba(88, 28, 135, 0.22) 0%, rgba(30, 27, 75, 0.35) 100%);
        border: 1px solid rgba(168, 85, 247, 0.35);
        border-radius: 10px;
        padding: 12px 14px;
        box-shadow: 0 4px 20px rgba(0, 0, 0, 0.35);
        transition: all 0.2s ease;
      }
      .buzz-ai-summary-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        margin-bottom: 8px;
        padding-bottom: 6px;
        border-bottom: 1px solid rgba(255, 255, 255, 0.08);
      }
      .buzz-ai-bulletin-item {
        padding: 7px 10px;
        border-radius: 6px;
        background: rgba(255, 255, 255, 0.04);
        margin-bottom: 6px;
        cursor: pointer;
        transition: background 0.15s ease, transform 0.1s ease;
        border: 1px solid rgba(255, 255, 255, 0.05);
      }
      .buzz-ai-bulletin-item:hover {
        background: rgba(168, 85, 247, 0.18);
        border-color: rgba(168, 85, 247, 0.4);
        transform: translateY(-1px);
      }

      /* Drawer Footer */
      .buzz-drawer-footer {
        padding: 10px 18px;
        background: #16161b;
        border-top: 1px solid rgba(255, 255, 255, 0.08);
        display: flex;
        align-items: center;
        justify-content: space-between;
        font-size: 11.5px;
        color: #71717a;
      }
      .buzz-kbd-hints {
        display: flex;
        align-items: center;
        gap: 10px;
      }

      /* Quick Feedback Banner */
      .buzz-quick-banner {
        position: fixed !important;
        bottom: 24px !important;
        left: 50% !important;
        transform: translateX(-50%) !important;
        z-index: 2147483647 !important;
        background: rgba(15, 23, 42, 0.95) !important;
        backdrop-filter: blur(12px) !important;
        border: 1px solid #38bdf8 !important;
        border-radius: 8px !important;
        padding: 8px 18px !important;
        color: #f8fafc !important;
        font-size: 12.5px !important;
        font-weight: 600 !important;
        box-shadow: 0 8px 24px rgba(0, 0, 0, 0.7) !important;
        animation: bannerPop 0.25s cubic-bezier(0.16, 1, 0.3, 1) !important;
      }
      @keyframes bannerPop {
        from { opacity: 0; transform: translate(-50%, 15px); }
        to { opacity: 1; transform: translate(-50%, 0); }
      }

      /* Glowing Spotlight Indicator & High-Contrast Ping Target */
      @keyframes buzzSpotlightPulse {
        0% {
          outline: 3px solid #f59e0b !important;
          box-shadow: 0 0 35px rgba(245, 158, 11, 0.9), inset 0 0 20px rgba(245, 158, 11, 0.3) !important;
          background-color: rgba(245, 158, 11, 0.25) !important;
        }
        50% {
          outline: 3px solid #38bdf8 !important;
          box-shadow: 0 0 45px rgba(56, 189, 248, 1), inset 0 0 25px rgba(56, 189, 248, 0.4) !important;
          background-color: rgba(56, 189, 248, 0.28) !important;
        }
        100% {
          outline: 3px solid #f59e0b !important;
          box-shadow: 0 0 35px rgba(245, 158, 11, 0.9), inset 0 0 20px rgba(245, 158, 11, 0.3) !important;
          background-color: rgba(245, 158, 11, 0.25) !important;
        }
      }
      .buzz-spotlight-active {
        position: relative !important;
        border-left: 6px solid #f59e0b !important;
        border-radius: 10px !important;
        animation: buzzSpotlightPulse 1.3s infinite ease-in-out !important;
        transition: all 0.3s cubic-bezier(0.16, 1, 0.3, 1) !important;
        z-index: 100 !important;
        padding-left: 8px !important;
      }
      .buzz-spotlight-badge {
        position: absolute !important;
        top: -18px !important;
        left: 10px !important;
        background: linear-gradient(135deg, #d97706, #b45309) !important;
        color: #ffffff !important;
        font-size: 11px !important;
        font-weight: 800 !important;
        padding: 3px 12px !important;
        border-radius: 12px !important;
        border: 1.5px solid #fbbf24 !important;
        box-shadow: 0 4px 16px rgba(0, 0, 0, 0.85), 0 0 12px rgba(245, 158, 11, 0.7) !important;
        pointer-events: auto !important;
        z-index: 2147483647 !important;
        display: flex !important;
        align-items: center !important;
        gap: 6px !important;
        animation: buzzBadgePop 0.3s cubic-bezier(0.16, 1, 0.3, 1) !important;
        letter-spacing: 0.3px !important;
      }
      .buzz-badge-chan {
        background: rgba(0, 0, 0, 0.3) !important;
        padding: 1px 6px !important;
        border-radius: 6px !important;
        font-size: 10px !important;
        color: #fef08a !important;
      }
      .buzz-badge-time {
        font-size: 10px !important;
        color: rgba(255, 255, 255, 0.8) !important;
      }
      .buzz-badge-close {
        margin-left: 4px !important;
        cursor: pointer !important;
        background: rgba(0, 0, 0, 0.25) !important;
        border-radius: 50% !important;
        width: 16px !important;
        height: 16px !important;
        display: flex !important;
        align-items: center !important;
        justify-content: center !important;
        font-size: 10px !important;
        transition: background 0.15s ease !important;
      }
      .buzz-badge-close:hover {
        background: rgba(239, 68, 68, 0.8) !important;
        color: #ffffff !important;
      }
      .buzz-spotlight-pointer {
        position: absolute !important;
        left: -32px !important;
        top: 6px !important;
        font-size: 22px !important;
        z-index: 2147483647 !important;
        pointer-events: none !important;
        animation: buzzPointerBounce 0.8s infinite alternate ease-in-out !important;
      }
      @keyframes buzzPointerBounce {
        from { transform: translateX(0) scale(1); }
        to { transform: translateX(8px) scale(1.15); }
      }
      .buzz-ping-text-mark {
        background: linear-gradient(120deg, #fef08a 0%, #fde047 100%) !important;
        color: #0f172a !important;
        font-weight: 800 !important;
        padding: 2px 6px !important;
        border-radius: 4px !important;
        box-shadow: 0 0 14px rgba(254, 240, 138, 0.9) !important;
        text-shadow: none !important;
        display: inline !important;
      }
      @keyframes buzzBadgePop {
        from { opacity: 0; transform: translateY(-8px) scale(0.9); }
        to { opacity: 1; transform: translateY(0) scale(1); }
      }
    `;
  }

  function showQuickBanner(text) {
    const banner = document.createElement("div");
    banner.className = "buzz-quick-banner";
    banner.textContent = text;
    (document.documentElement || document.body).appendChild(banner);
    setTimeout(() => {
      banner.style.opacity = '0';
      banner.style.transition = 'opacity 0.25s';
      setTimeout(() => banner.remove(), 250);
    }, 2600);
  }

  // =========================================================================
  // PERSISTENT DRAGGABLE POSITIONING SYSTEM
  // =========================================================================

  function makeDraggable(el, storageKey) {
    if (!el || el.dataset.draggableInit) return;
    el.dataset.draggableInit = "true";

    let isDragging = false;
    let startX = 0, startY = 0;
    let origLeft = 0, origTop = 0;
    let hasMoved = false;

    function applyPosition(l, t) {
      el.style.setProperty("left", `${l}px`, "important");
      el.style.setProperty("top", `${t}px`, "important");
      el.style.setProperty("right", "auto", "important");
      el.style.setProperty("bottom", "auto", "important");
      if (storageKey.includes("pill")) {
        el.style.setProperty("width", "max-content", "important");
      }
    }

    try {
      const saved = localStorage.getItem(storageKey);
      if (saved) {
        const pos = JSON.parse(saved);
        if (typeof pos.left === "number" && typeof pos.top === "number") {
          const maxL = Math.max(8, window.innerWidth - (el.offsetWidth || 140) - 8);
          const maxT = Math.max(45, window.innerHeight - (el.offsetHeight || 36) - 8);
          const curL = Math.max(8, Math.min(maxL, pos.left));
          const curT = Math.max(45, Math.min(maxT, pos.top));
          applyPosition(curL, curT);
        }
      }
    } catch(e) {}

    el.addEventListener("pointerdown", (e) => {
      if (e.button !== 0) return;
      isDragging = true;
      hasMoved = false;
      startX = e.clientX;
      startY = e.clientY;

      const rect = el.getBoundingClientRect();
      origLeft = rect.left;
      origTop = rect.top;

      try { el.setPointerCapture(e.pointerId); } catch(err) {}
      el.classList.add("buzz-is-dragging");
      e.stopPropagation();
    });

    el.addEventListener("pointermove", (e) => {
      if (!isDragging) return;
      const dx = e.clientX - startX;
      const dy = e.clientY - startY;
      if (Math.hypot(dx, dy) > 5) {
        hasMoved = true;
      }
      if (hasMoved) {
        const maxL = Math.max(8, window.innerWidth - (el.offsetWidth || 140) - 8);
        const maxT = Math.max(45, window.innerHeight - (el.offsetHeight || 36) - 8);
        const newL = Math.max(8, Math.min(maxL, origLeft + dx));
        const newT = Math.max(45, Math.min(maxT, origTop + dy));
        applyPosition(newL, newT);
      }
      e.stopPropagation();
    });

    const onPointerEnd = (e) => {
      if (!isDragging) return;
      isDragging = false;
      el.classList.remove("buzz-is-dragging");
      try { el.releasePointerCapture(e.pointerId); } catch(err) {}

      if (hasMoved) {
        const rect = el.getBoundingClientRect();
        try {
          localStorage.setItem(storageKey, JSON.stringify({ left: Math.round(rect.left), top: Math.round(rect.top) }));
        } catch(err) {}
      }
    };

    el.addEventListener("pointerup", onPointerEnd);
    el.addEventListener("pointercancel", onPointerEnd);

    el.addEventListener("click", (e) => {
      if (hasMoved) {
        e.stopPropagation();
        e.preventDefault();
        hasMoved = false;
        return;
      }
      toggleDrawer();
    }, true);
  }

  // 1. Create Left Rail Action Button (Draggable)
  function createRailButton() {
    let btn = document.getElementById("buzz-rail-hub-btn");
    if (btn) return btn;

    btn = document.createElement("div");
    btn.id = "buzz-rail-hub-btn";
    btn.title = "⚡ Trung tâm Tin nhắn Đa Nhóm [Alt+M] · (Kéo thả để di chuyển)";
    btn.innerHTML = `
      <span>⚡</span>
      <span id="buzz-rail-badge">0</span>
    `;

    makeDraggable(btn, "buzz_rail_pos_v1");
    (document.documentElement || document.body).appendChild(btn);
    return btn;
  }

  // 2. Create Floating Header Pill (Draggable)
  function createHeaderPill() {
    let pill = document.getElementById("buzz-hub-pill");
    if (pill) return pill;

    pill = document.createElement("div");
    pill.id = "buzz-hub-pill";
    pill.title = "⚡ Trung tâm Tin nhắn [Alt+M] · (Kéo thả tự do bất kỳ đâu để tránh che khuất UI)";
    pill.innerHTML = `
      <span class="buzz-drag-handle" title="Kéo để di chuyển vị trí">⠿</span>
      <span class="buzz-status-dot"></span>
      <span id="buzz-hub-pill-label">⚡ Hộp thư đa nhóm</span>
      <span id="buzz-hub-pill-badge" class="buzz-unread-badge" style="display:none;">0</span>
      <span class="buzz-kbd-badge">Alt+M</span>
    `;
    
    makeDraggable(pill, "buzz_pill_pos_v1");
    (document.documentElement || document.body).appendChild(pill);
    return pill;
  }

  // 3. Create Toast Container
  function createToastContainer() {
    let c = document.getElementById("buzz-inapp-toast-container");
    if (!c) {
      c = document.createElement("div");
      c.id = "buzz-inapp-toast-container";
      (document.documentElement || document.body).appendChild(c);
    }
    return c;
  }

  let notificationsEnabled = true;
  async function checkNotificationConfig() {
    try {
      const res = await fetch("http://127.0.0.1:8787/api/sound_config");
      if (res.ok) {
        const cfg = await res.json();
        notificationsEnabled = (cfg.enabled !== false && cfg.show_desktop_notification !== false);
      }
    } catch(e) {}
  }

  function showInAppToast(msg) {
    if (!notificationsEnabled || window.__buzzNotificationsDisabled || localStorage.getItem("buzz_notifications_disabled") === "true") {
      return;
    }
    const container = createToastContainer();
    const meta = getCommMeta(msg.community);
    const cat = detectItemCategory(msg);
    const toast = document.createElement("div");
    toast.className = "buzz-toast-card";
    const sender = msg.sender || "Thành viên";
    const avatarColor = getAvatarColor(sender);
    const initials = getInitials(sender);
    const timeInfo = formatMessageTime(msg.timestamp, msg.time);

    toast.innerHTML = `
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:6px;">
        <div style="display:flex;align-items:center;gap:6px;">
          <span class="buzz-comm-tag" style="background:${meta.bg};color:${meta.text};border:1px solid ${meta.border};">${meta.name}</span>
          <span class="buzz-section-tag" style="background:rgba(255,255,255,0.06);color:${cat.color};">${cat.icon} ${cat.label}</span>
          <span class="buzz-chan-tag">#${msg.channel || "general"}</span>
        </div>
        <span style="color:#a1a1aa;font-size:11px;font-variant-numeric:tabular-nums;" title="Thời gian gửi: ${timeInfo.full}">${timeInfo.display}</span>
      </div>
      <div style="display:flex;align-items:flex-start;gap:10px;">
        <div class="buzz-card-avatar" style="background:${avatarColor};">${initials}</div>
        <div style="flex:1;min-width:0;">
          <div style="font-size:12.5px;font-weight:700;color:#f4f4f5;margin-bottom:2px;">${sender}</div>
          <div style="font-size:12.5px;color:#d4d4d8;line-height:1.4;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;">${msg.content || ""}</div>
        </div>
      </div>
      <div style="display:flex;justify-content:flex-end;margin-top:6px;">
        <span style="font-size:11px;font-weight:600;color:#38bdf8;">Chuyển tới ${cat.label} ➔</span>
      </div>
      <div class="buzz-toast-progress"></div>
    `;

    toast.addEventListener("click", () => {
      toast.remove();
      navigateToMessage(msg);
    });

    container.appendChild(toast);

    // Trigger audio notification
    fetch("http://127.0.0.1:8787/api/play_sound", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ is_mention: !!msg.is_mention })
    }).catch(() => {});

    setTimeout(() => {
      if (toast.parentElement) {
        toast.style.opacity = '0';
        toast.style.transform = 'translateY(15px)';
        toast.style.transition = 'all 0.25s ease';
        setTimeout(() => toast.remove(), 250);
      }
    }, 5000);
  }

  // 4. Create Unified Drawer
  function createDrawer() {
    let overlay = document.getElementById("buzz-hub-drawer-overlay");
    if (!overlay) {
      overlay = document.createElement("div");
      overlay.id = "buzz-hub-drawer-overlay";
      overlay.addEventListener("click", closeDrawer);
      (document.documentElement || document.body).appendChild(overlay);
    }

    let drawer = document.getElementById("buzz-hub-drawer");
    if (drawer) return drawer;

    drawer = document.createElement("div");
    drawer.id = "buzz-hub-drawer";
    drawer.innerHTML = `
      <div class="buzz-drawer-header">
        <div class="buzz-drawer-title">
          <span>⚡</span>
          <span id="buzz-drawer-title-text">Tin nhắn chưa xem</span>
          <span id="buzz-drawer-total-count" class="buzz-filter-badge" style="background:#ef4444;color:#ffffff;">0</span>
        </div>
        <div class="buzz-drawer-actions">
          <button id="buzz-btn-ai-summary" class="buzz-hdr-btn" title="⚡ Tóm tắt nhanh tin mới bằng AI [Alt+S]" style="background:rgba(168,85,247,0.18);color:#c084fc;border-color:rgba(168,85,247,0.4);">⚡ Tóm tắt AI</button>
          <button id="buzz-btn-toggle-unread" class="buzz-hdr-btn active" title="Đang chỉ hiện tin chưa xem (Bấm để xem tất cả lịch sử)">🔴 Chưa xem</button>
          <button id="buzz-btn-mark-read" class="buzz-hdr-btn" title="Đánh dấu tất cả là đã đọc">✓ Đã đọc</button>
          <button id="buzz-btn-sync" class="buzz-hdr-btn" title="Đồng bộ ngay với tất cả nhóm">🔄 Đồng bộ</button>
          <button class="buzz-hdr-btn close-btn" id="buzz-drawer-close-btn" title="Đóng [Esc]">✕</button>
        </div>
      </div>

      <div class="buzz-drawer-search-bar">
        <input type="text" id="buzz-drawer-search-input" class="buzz-drawer-search-input" placeholder="🔍 Tìm kiếm tin nhắn, người gửi, kênh, thư mục dự án... (phím tắt /)" />
        <button id="buzz-search-clear-btn" class="buzz-search-clear">✕</button>
      </div>

      <div class="buzz-type-filter-bar">
        <button class="buzz-type-chip active" data-type="all">✨ Tất cả loại</button>
        <button class="buzz-type-chip" data-type="channel">💬 Kênh chat</button>
        <button class="buzz-type-chip" data-type="project">📁 Dự án & Thư mục</button>
        <button class="buzz-type-chip" data-type="dm">👤 Tin riêng</button>
        <button class="buzz-type-chip" data-type="forum">💬 Diễn đàn</button>
      </div>

      <div class="buzz-drawer-filters" id="buzz-drawer-filters-container"></div>

      <div id="buzz-ai-summary-container" style="display:none;"></div>

      <div id="buzz-drawer-msg-list"></div>

      <div class="buzz-drawer-footer">
        <div class="buzz-kbd-hints">
          <span><kbd class="buzz-kbd-badge">↑</kbd><kbd class="buzz-kbd-badge">↓</kbd> Chọn</span>
          <span><kbd class="buzz-kbd-badge">↵</kbd> Vào mục</span>
          <span><kbd class="buzz-kbd-badge">Alt+S</kbd> Tóm tắt AI</span>
          <span><kbd class="buzz-kbd-badge">1-9</kbd> Đổi nhóm</span>
          <span><kbd class="buzz-kbd-badge">Esc</kbd> Đóng</span>
        </div>
        <div style="color:#52525b;">Buzz UI Enhancer v6.4</div>
      </div>
    `;

    (document.documentElement || document.body).appendChild(drawer);

    // Wire Event Listeners
    document.getElementById("buzz-drawer-close-btn").addEventListener("click", closeDrawer);
    document.getElementById("buzz-btn-sync").addEventListener("click", syncAndReload);

    const summaryBtn = document.getElementById("buzz-btn-ai-summary");
    if (summaryBtn) {
      summaryBtn.addEventListener("click", triggerAISummary);
    }

    const toggleBtn = document.getElementById("buzz-btn-toggle-unread");
    if (toggleBtn) {
      toggleBtn.addEventListener("click", () => {
        showUnreadOnly = !showUnreadOnly;
        updateToggleBtnUI();
        renderDrawerMessages(true);
      });
    }

    document.getElementById("buzz-btn-mark-read").addEventListener("click", () => {
      messages.forEach(m => { m.is_unread = false; });
      unreadCount = 0;
      updateBadgeUI();
      updateFilterTabCounts();
      renderDrawerMessages(true);
      fetch("http://127.0.0.1:8787/api/mark_read", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mark_all: true })
      }).catch(() => {});
      showQuickBanner("✓ Đã đánh dấu tất cả tin nhắn là đã đọc");
    });

    const searchInput = document.getElementById("buzz-drawer-search-input");
    const clearBtn = document.getElementById("buzz-search-clear-btn");

    searchInput.addEventListener("input", (e) => {
      searchQuery = (e.target.value || "").trim().toLowerCase();
      clearBtn.style.display = searchQuery ? "block" : "none";
      selectedIndex = 0;
      renderDrawerMessages();
    });

    clearBtn.addEventListener("click", () => {
      searchInput.value = "";
      searchQuery = "";
      clearBtn.style.display = "none";
      selectedIndex = 0;
      renderDrawerMessages();
      searchInput.focus();
    });

    drawer.querySelectorAll(".buzz-type-chip").forEach(chip => {
      chip.addEventListener("click", () => {
        drawer.querySelectorAll(".buzz-type-chip").forEach(c => c.classList.remove("active"));
        chip.classList.add("active");
        activeTypeFilter = chip.getAttribute("data-type");
        selectedIndex = 0;
        renderDrawerMessages();
      });
    });

    renderCommunityFilterTabs();

    return drawer;
  }

  function renderCommunityFilterTabs() {
    const container = document.getElementById("buzz-drawer-filters-container");
    if (!container) return;

    const comms = getDiscoveredCommunities();
    let html = `<button class="buzz-filter-tab ${activeFilter === 'all' ? 'active' : ''}" data-filter="all">🌐 Tất cả <span class="buzz-filter-badge" id="buzz-count-all">0</span></button>`;

    for (const c of comms) {
      const isActive = activeFilter === c.key ? 'active' : '';
      html += `<button class="buzz-filter-tab ${isActive}" data-filter="${c.key}">${c.icon} ${c.name} <span class="buzz-filter-badge" id="buzz-count-${c.key}">0</span></button>`;
    }

    container.innerHTML = html;

    container.querySelectorAll(".buzz-filter-tab").forEach(tab => {
      tab.addEventListener("click", () => {
        container.querySelectorAll(".buzz-filter-tab").forEach(t => t.classList.remove("active"));
        tab.classList.add("active");
        activeFilter = tab.getAttribute("data-filter");
        selectedIndex = 0;
        renderDrawerMessages();
      });
    });

    updateFilterTabCounts();
  }

  async function triggerAISummary() {
    const container = document.getElementById("buzz-ai-summary-container");
    if (!container) return;

    if (container.style.display !== "none" && container.dataset.loaded === "true") {
      container.style.display = "none";
      return;
    }

    container.style.display = "block";
    container.innerHTML = `
      <div class="buzz-ai-summary-card">
        <div style="display:flex;align-items:center;gap:8px;padding:8px 4px;color:#c084fc;font-size:12px;">
          <span style="font-size:14px;">⚡</span> Đang tạo báo cáo tóm tắt tin chưa đọc từ tất cả các nhóm...
        </div>
      </div>
    `;

    try {
      const res = await fetch("http://127.0.0.1:8787/api/ai_summary");
      if (!res.ok) throw new Error("HTTP " + res.status);
      const data = await res.json();
      const bulletins = data.bulletins || [];

      if (bulletins.length === 0) {
        container.innerHTML = `
          <div class="buzz-ai-summary-card">
            <div class="buzz-ai-summary-header">
              <div style="display:flex;align-items:center;gap:6px;">
                <span>✨</span>
                <span class="buzz-ai-summary-title">AI CATCH-UP TL;DR</span>
              </div>
              <button class="buzz-ai-summary-close" id="buzz-ai-summary-close-btn">✕</button>
            </div>
            <div style="color:#a1a1aa;font-size:12px;padding:6px 2px;">
              🎉 Tuyệt vời! Bạn không có tin nhắn tồn đọng nào cần tóm tắt.
            </div>
          </div>
        `;
      } else {
        const totalCount = data.total_unread || bulletins.reduce((a, b) => a + (b.count || 1), 0);
        let itemsHtml = "";
        bulletins.forEach((b, i) => {
          const meta = getCommMeta(b.community);
          itemsHtml += `
            <div class="buzz-ai-bulletin-item" data-index="${i}" style="margin-top:6px;padding:8px 10px;background:rgba(255,255,255,0.03);border-radius:6px;border-left:3px solid #a855f7;cursor:pointer;transition:background 0.15s ease;">
              <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:3px;">
                <span style="font-weight:600;font-size:11.5px;color:#f4f4f5;">
                  <span style="color:${meta.text};background:${meta.bg};padding:1px 5px;border-radius:4px;font-size:10px;margin-right:4px;">${meta.name}</span>
                  #${b.channel}
                </span>
                <span style="font-size:10px;color:#c084fc;font-weight:600;">${b.count} tin • từ ${b.senders || "mọi người"}</span>
              </div>
              <div style="font-size:11.5px;color:#d4d4d8;line-height:1.45;word-break:break-word;">
                ${b.latest_preview}
              </div>
            </div>
          `;
        });

        container.innerHTML = `
          <div class="buzz-ai-summary-card">
            <div class="buzz-ai-summary-header">
              <div style="display:flex;align-items:center;gap:6px;">
                <span>⚡</span>
                <span class="buzz-ai-summary-title">AI CATCH-UP TL;DR</span>
                <span class="buzz-ai-summary-count">${totalCount} tin chưa đọc • ${bulletins.length} kênh</span>
              </div>
              <button class="buzz-ai-summary-close" id="buzz-ai-summary-close-btn">✕</button>
            </div>
            <div class="buzz-ai-summary-list">
              ${itemsHtml}
            </div>
          </div>
        `;

        container.querySelectorAll(".buzz-ai-bulletin-item").forEach(item => {
          item.addEventListener("mouseenter", () => {
            item.style.background = "rgba(168,85,247,0.12)";
          });
          item.addEventListener("mouseleave", () => {
            item.style.background = "rgba(255,255,255,0.03)";
          });
          item.addEventListener("click", () => {
            const idx = parseInt(item.dataset.index);
            const b = bulletins[idx];
            if (b) {
              navigateToMessage({
                community: b.community,
                channel: b.channel,
                channel_id: b.channel_id,
                is_dm: b.is_dm,
                content: b.latest_preview,
                timestamp: b.last_timestamp || 0
              });
            }
          });
        });
      }

      container.dataset.loaded = "true";
      const closeBtn = document.getElementById("buzz-ai-summary-close-btn");
      if (closeBtn) {
        closeBtn.addEventListener("click", () => {
          container.style.display = "none";
        });
      }
    } catch (e) {
      container.innerHTML = `
        <div class="buzz-ai-summary-card" style="border-color:#ef4444;">
          <div style="color:#f87171;font-size:12px;">Không thể tạo tóm tắt AI: ${e.message}</div>
        </div>
      `;
    }
  }

  function sendQuickReply(msg, replyText) {
    if (!msg || !replyText) return;
    const cleanText = replyText.trim();
    if (!cleanText) return;

    // 1. First navigate to target message/channel
    navigateToMessage(msg);

    // 2. Schedule composer injection
    function tryFillComposer(attemptsLeft) {
      const inputs = Array.from(document.querySelectorAll("textarea, [contenteditable='true'], input[type='text']")).filter(el => {
        if (el.closest("#buzz-hub-drawer, #buzz-hub-pill, #buzz-rail-hub-btn, nav, aside, [data-sidebar], header")) return false;
        const r = el.getBoundingClientRect();
        return r.top >= 100 && r.width >= 120 && r.height >= 20;
      });

      const composer = inputs[inputs.length - 1];
      if (composer) {
        composer.focus();
        if (composer.tagName === "TEXTAREA" || composer.tagName === "INPUT") {
          const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, "value")?.set ||
                         Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value")?.set;
          if (setter) setter.call(composer, cleanText);
          else composer.value = cleanText;
          composer.dispatchEvent(new Event("input", { bubbles: true }));
          composer.dispatchEvent(new Event("change", { bubbles: true }));
        } else if (composer.getAttribute("contenteditable") === "true") {
          composer.innerText = cleanText;
          composer.dispatchEvent(new InputEvent("input", { bubbles: true, inputType: "insertText", data: cleanText }));
        }
        showQuickBanner(`💬 Đã nhập sẵn câu trả lời: "${cleanText.slice(0, 30)}..." - Bấm Enter để gửi!`);
      } else if (attemptsLeft > 0) {
        setTimeout(() => tryFillComposer(attemptsLeft - 1), 200);
      }
    }

    setTimeout(() => tryFillComposer(15), 500);
  }

  window.buzzSetTypeFilter = function(type) {
    activeTypeFilter = type;
    const drawer = document.getElementById("buzz-hub-drawer");
    if (drawer) {
      drawer.querySelectorAll(".buzz-type-chip").forEach(c => {
        if (c.getAttribute("data-type") === type) c.classList.add("active");
        else c.classList.remove("active");
      });
    }
    selectedIndex = 0;
    renderDrawerMessages();
  };

  window.buzzSetCommunityFilter = function(filter) {
    activeFilter = filter;
    const drawer = document.getElementById("buzz-hub-drawer");
    if (drawer) {
      drawer.querySelectorAll(".buzz-filter-tab").forEach(t => {
        if (t.getAttribute("data-filter") === filter) t.classList.add("active");
        else t.classList.remove("active");
      });
    }
    selectedIndex = 0;
    renderDrawerMessages();
  };

  function updateToggleBtnUI() {
    const toggleBtn = document.getElementById("buzz-btn-toggle-unread");
    const titleText = document.getElementById("buzz-drawer-title-text");
    const totalBadge = document.getElementById("buzz-drawer-total-count");
    if (toggleBtn) {
      toggleBtn.textContent = showUnreadOnly ? "🔴 Chưa xem" : "📁 Tất cả";
      toggleBtn.classList.toggle("active", showUnreadOnly);
      toggleBtn.title = showUnreadOnly ? "Đang chỉ hiện tin nhắn chưa đọc (Bấm để xem tất cả)" : "Đang hiện toàn bộ lịch sử (Bấm để chỉ xem chưa đọc)";
    }
    if (titleText) {
      titleText.textContent = showUnreadOnly ? "Tin nhắn chưa xem" : "Tất cả tin nhắn";
    }
    if (totalBadge) {
      totalBadge.style.background = showUnreadOnly ? "#ef4444" : "#38bdf8";
      totalBadge.style.color = showUnreadOnly ? "#ffffff" : "#0f172a";
    }
  }

  function toggleDrawer() {
    if (isDrawerOpen) closeDrawer();
    else openDrawer();
  }

  function openDrawer() {
    currentNavToken++;
    createDrawer();
    const drawer = document.getElementById("buzz-hub-drawer");
    const overlay = document.getElementById("buzz-hub-drawer-overlay");
    const pill = document.getElementById("buzz-hub-pill");
    if (drawer && overlay) {
      drawer.classList.add("open");
      overlay.classList.add("open");
      if (pill) pill.style.display = "none";
      isDrawerOpen = true;
      selectedIndex = 0;
      updateBadgeUI();
      updateToggleBtnUI();
      renderCommunityFilterTabs();
      renderDrawerMessages(true);
      fetchMessages();
      const input = document.getElementById("buzz-drawer-search-input");
      if (input) setTimeout(() => input.focus(), 50);
    }
  }

  function closeDrawer() {
    const drawer = document.getElementById("buzz-hub-drawer");
    const overlay = document.getElementById("buzz-hub-drawer-overlay");
    const pill = document.getElementById("buzz-hub-pill");
    if (drawer && overlay) {
      drawer.classList.remove("open");
      overlay.classList.remove("open");
      if (pill) pill.style.display = "flex";
      isDrawerOpen = false;
    }
  }

  function syncAndReload() {
    const btn = document.getElementById("buzz-btn-sync");
    if (btn) btn.style.transform = "rotate(180deg)";
    fetch("http://127.0.0.1:8787/api/sync_now", { method: "POST" })
      .then(() => fetchMessages())
      .then(() => {
        if (btn) btn.style.transform = "none";
        showQuickBanner("✅ Đã đồng bộ tin nhắn mới nhất từ tất cả các nhóm!");
      })
      .catch(() => {
        if (btn) btn.style.transform = "none";
        fetchMessages();
      });
  }

  function updateBadgeUI() {
    const pill = document.getElementById("buzz-hub-pill");
    const pillBadge = document.getElementById("buzz-hub-pill-badge");
    const pillLabel = document.getElementById("buzz-hub-pill-label");
    const railBtn = document.getElementById("buzz-rail-hub-btn");
    const railBadge = document.getElementById("buzz-rail-badge");

    if (unreadCount > 0) {
      if (pill) {
        pill.classList.add("has-unread");
        if (pillBadge) {
          pillBadge.textContent = unreadCount > 99 ? "99+" : unreadCount;
          pillBadge.style.display = "inline-block";
        }
        if (pillLabel) {
          const latest = messages[0];
          const meta = latest ? getCommMeta(latest.community) : null;
          pillLabel.textContent = meta ? `⚡ [${meta.name}] tin mới` : `⚡ Tin nhắn mới`;
        }
      }
      if (railBtn) {
        railBtn.classList.add("has-unread");
        if (railBadge) {
          railBadge.textContent = unreadCount > 99 ? "99+" : unreadCount;
          railBadge.style.display = "block";
        }
      }
    } else {
      if (pill) {
        pill.classList.remove("has-unread");
        if (pillBadge) pillBadge.style.display = "none";
        if (pillLabel) pillLabel.textContent = "⚡ Hộp thư đa nhóm";
      }
      if (railBtn) {
        railBtn.classList.remove("has-unread");
        if (railBadge) railBadge.style.display = "none";
      }
    }
  }

  function updateFilterTabCounts() {
    const comms = getDiscoveredCommunities();
    const targetMsgs = showUnreadOnly ? messages.filter(m => m.is_unread !== false) : messages;
    const counts = { all: targetMsgs.length };
    comms.forEach(c => { counts[c.key] = 0; });

    for (const m of targetMsgs) {
      const c = (m.community || "").toLowerCase();
      for (const comm of comms) {
        if (c === comm.key || c.includes(comm.key) || comm.key.includes(c)) {
          counts[comm.key]++;
          break;
        }
      }
    }

    const drawer = document.getElementById("buzz-hub-drawer");
    if (!drawer) return;

    const totalBadge = document.getElementById("buzz-drawer-total-count");
    if (totalBadge) totalBadge.textContent = targetMsgs.length;

    const allBadge = document.getElementById("buzz-count-all");
    if (allBadge) allBadge.textContent = targetMsgs.length;

    for (const [key, count] of Object.entries(counts)) {
      const el = document.getElementById(`buzz-count-${key}`);
      if (el) el.textContent = count;
    }
  }

  let currentFilteredMessages = [];
  let renderedCount = 0;
  const CHUNK_SIZE = 35;
  let lastRenderSignature = "";

  function createMessageCardElement(m, idx) {
    const meta = getCommMeta(m.community);
    const cat = detectItemCategory(m);
    const isUnread = (m.is_unread !== false);
    const card = document.createElement("div");
    card.className = "buzz-msg-card" + (isUnread ? " is-unread" : "");
    if (idx === selectedIndex) {
      card.classList.add("buzz-kb-selected");
    }
    card.dataset.index = idx;

    const sender = m.sender || "Thành viên";
    const avatarColor = getAvatarColor(sender);
    const initials = getInitials(sender);
    const timeInfo = formatMessageTime(m.timestamp, m.time);

    card.innerHTML = `
      <div class="buzz-card-avatar" style="background:${avatarColor};">${initials}</div>
      <div class="buzz-card-main">
        <div class="buzz-card-top-row">
          <div class="buzz-card-tags">
            ${isUnread ? '<span class="buzz-unread-badge" style="background:#ef4444;color:#fff;font-size:9.5px;padding:1px 6px;border-radius:6px;font-weight:700;">MỚI</span>' : ''}
            <span class="buzz-comm-tag" style="background:${meta.bg};color:${meta.text};border:1px solid ${meta.border};">${meta.name}</span>
            <span class="buzz-section-tag" style="background:rgba(255,255,255,0.06);color:${cat.color};">${cat.icon} ${cat.label}</span>
            <span class="buzz-chan-tag">#${m.channel || "general"}</span>
          </div>
          <span class="buzz-time-tag" title="Thời gian gửi: ${timeInfo.full}">${timeInfo.display}</span>
        </div>
        <div class="buzz-card-sender">${sender}</div>
        <div class="buzz-card-text">${m.content || ""}</div>
        <div style="display:flex;align-items:center;justify-content:space-between;margin-top:4px;">
          <div class="buzz-card-action-chip">Mở ${cat.label} ↵</div>
          <button class="buzz-card-reply-btn" title="Trả lời nhanh tin nhắn này">💬 Trả lời nhanh</button>
        </div>
        <div class="buzz-inline-reply-box" style="display:none;">
          <div class="buzz-quick-chips-row">
            <button class="buzz-quick-chip" data-reply="👍 OK">👍 OK</button>
            <button class="buzz-quick-chip" data-reply="✅ Đã duyệt">✅ Đã duyệt</button>
            <button class="buzz-quick-chip" data-reply="🔄 Tiếp tục đi">🔄 Tiếp tục đi</button>
            <button class="buzz-quick-chip" data-reply="⏳ Chờ chút nhé">⏳ Chờ chút nhé</button>
          </div>
          <div style="display:flex;gap:6px;margin-top:4px;">
            <input type="text" class="buzz-inline-reply-input" placeholder="Nhập phản hồi nhanh..." />
            <button class="buzz-inline-reply-send">Gửi ↵</button>
          </div>
        </div>
      </div>
    `;

    // 1. Reply Toggle Button
    const replyToggleBtn = card.querySelector(".buzz-card-reply-btn");
    const inlineReplyBox = card.querySelector(".buzz-inline-reply-box");
    const replyInput = card.querySelector(".buzz-inline-reply-input");
    const replySendBtn = card.querySelector(".buzz-inline-reply-send");

    if (replyToggleBtn && inlineReplyBox) {
      replyToggleBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        const isOpen = inlineReplyBox.style.display !== "none";
        inlineReplyBox.style.display = isOpen ? "none" : "flex";
        replyToggleBtn.classList.toggle("active", !isOpen);
        if (!isOpen && replyInput) {
          setTimeout(() => replyInput.focus(), 60);
        }
      });
    }

    // 2. Quick Action Chips
    card.querySelectorAll(".buzz-quick-chip").forEach(chip => {
      chip.addEventListener("click", (e) => {
        e.stopPropagation();
        const replyText = chip.getAttribute("data-reply") || chip.textContent;
        sendQuickReply(m, replyText);
      });
    });

    // 3. Reply Input & Send Button
    if (replySendBtn && replyInput) {
      const doSubmit = (e) => {
        e.stopPropagation();
        const text = (replyInput.value || "").trim();
        if (text) {
          sendQuickReply(m, text);
        }
      };
      replySendBtn.addEventListener("click", doSubmit);
      replyInput.addEventListener("keydown", (e) => {
        e.stopPropagation();
        if (e.key === "Enter") {
          e.preventDefault();
          doSubmit(e);
        }
      });
      replyInput.addEventListener("click", (e) => e.stopPropagation());
    }

    // 4. Default Card Click (Open Message)
    card.addEventListener("click", (e) => {
      if (e.target.closest(".buzz-inline-reply-box") || e.target.closest(".buzz-card-reply-btn")) return;
      navigateToMessage(m);
    });

    card.addEventListener("mouseenter", () => {
      selectedIndex = idx;
      const c = document.getElementById("buzz-drawer-msg-list");
      if (c) {
        c.querySelectorAll(".buzz-msg-card.buzz-kb-selected").forEach(el => el.classList.remove("buzz-kb-selected"));
        card.classList.add("buzz-kb-selected");
      }
    });

    return card;
  }

  function renderDrawerMessages(force = false) {
    const container = document.getElementById("buzz-drawer-msg-list");
    if (!container) return;

    updateFilterTabCounts();

    const filtered = messages.filter(m => {
      if (showUnreadOnly && m.is_unread === false) return false;
      if (activeFilter !== "all") {
        const c = (m.community || "").toLowerCase();
        if (!c.includes(activeFilter.toLowerCase())) return false;
      }
      if (activeTypeFilter !== "all") {
        const cat = detectItemCategory(m);
        if (cat.type !== activeTypeFilter) return false;
      }
      if (searchQuery) {
        const txt = ((m.content || "") + " " + (m.sender || "") + " " + (m.channel || "")).toLowerCase();
        if (!txt.includes(searchQuery)) return false;
      }
      return true;
    });

    currentFilteredMessages = filtered;
    const signature = `${showUnreadOnly}_${activeFilter}_${activeTypeFilter}_${searchQuery}_${filtered.length}_${filtered[0]?.id || ""}`;

    // Skip heavy DOM recreation if data and filters have not changed
    if (!force && signature === lastRenderSignature && container.children.length > 0) {
      return;
    }
    lastRenderSignature = signature;

    if (filtered.length === 0) {
      if (showUnreadOnly && !searchQuery && activeFilter === "all" && activeTypeFilter === "all") {
        container.innerHTML = `
          <div style="color:#71717a;text-align:center;padding:60px 20px;font-size:13px;">
            <div style="font-size:36px;margin-bottom:12px;">🎉</div>
            <div style="font-weight:700;color:#e4e4e7;font-size:15px;margin-bottom:6px;">Tuyệt vời! Bạn đã xem hết tin nhắn mới</div>
            <div style="color:#a1a1aa;margin-bottom:18px;">Không còn tin nhắn chưa đọc nào trong tất cả các nhóm.</div>
            <button id="buzz-empty-view-all-btn" class="buzz-hdr-btn" style="margin:0 auto;padding:8px 16px;border-radius:8px;background:rgba(56,189,248,0.15);color:#38bdf8;border:1px solid rgba(56,189,248,0.3);cursor:pointer;font-weight:600;">📁 Xem lại toàn bộ lịch sử tin nhắn</button>
          </div>
        `;
        const viewAllBtn = document.getElementById("buzz-empty-view-all-btn");
        if (viewAllBtn) {
          viewAllBtn.addEventListener("click", () => {
            showUnreadOnly = false;
            updateToggleBtnUI();
            renderDrawerMessages(true);
          });
        }
      } else {
        container.innerHTML = `
          <div style="color:#71717a;text-align:center;padding:60px 20px;font-size:13px;">
            <div style="font-size:28px;margin-bottom:10px;">🔍</div>
            <div style="font-weight:600;color:#e4e4e7;margin-bottom:4px;">Không tìm thấy tin nhắn nào</div>
            <div>Thử tìm kiếm với từ khóa khác hoặc đổi bộ lọc.</div>
          </div>
        `;
      }
      renderedCount = 0;
      return;
    }

    container.innerHTML = "";
    renderedCount = 0;
    const fragment = document.createDocumentFragment();
    const initialChunk = filtered.slice(0, CHUNK_SIZE);
    initialChunk.forEach((m, idx) => {
      fragment.appendChild(createMessageCardElement(m, idx));
    });
    renderedCount = initialChunk.length;
    container.appendChild(fragment);

    // Infinite scroll loading listener for silky smooth 60fps UX
    if (!container.dataset.hasScrollListener) {
      container.dataset.hasScrollListener = "true";
      container.addEventListener("scroll", () => {
        if (container.scrollTop + container.clientHeight >= container.scrollHeight - 250) {
          if (renderedCount < currentFilteredMessages.length) {
            const nextChunk = currentFilteredMessages.slice(renderedCount, renderedCount + CHUNK_SIZE);
            const frag = document.createDocumentFragment();
            nextChunk.forEach((m, i) => {
              frag.appendChild(createMessageCardElement(m, renderedCount + i));
            });
            renderedCount += nextChunk.length;
            container.appendChild(frag);
          }
        }
      }, { passive: true });
    }
  }

  async function fetchMessages() {
    try {
      const res = await fetch("http://127.0.0.1:8787/api/latest_messages.json");
      if (!res.ok) return;
      const data = await res.json();
      if (!Array.isArray(data)) return;

      const isFirstRun = (seenMessageIds.size === 0);
      let newArrivals = [];

      for (const msg of data) {
        if (!seenMessageIds.has(msg.id)) {
          seenMessageIds.add(msg.id);
          if (!isFirstRun) {
            newArrivals.push(msg);
          }
        }
      }

      messages = data;
      const trueUnread = messages.filter(m => m.is_unread !== false).length;
      unreadCount = trueUnread;
      updateBadgeUI();

      if (newArrivals.length > 0) {
        if (notificationsEnabled && !window.__buzzNotificationsDisabled && localStorage.getItem("buzz_notifications_disabled") !== "true") {
          for (const msg of newArrivals.slice(0, 3)) {
            showInAppToast(msg);
          }
        }
        if (isDrawerOpen) {
          renderDrawerMessages(true);
        }
      } else if (isDrawerOpen) {
        updateFilterTabCounts();
      }
    } catch (e) {}
  }

  // Keyboard-First Experience (Raycast / Linear Style)
  function setupKeyboardShortcuts() {
    window.addEventListener("keydown", (e) => {
      // 1. Global Toggle Drawer: Alt+M, Ctrl+Shift+M, Cmd+K / Ctrl+K
      if ((e.altKey && (e.key === "m" || e.key === "M")) || (e.ctrlKey && e.shiftKey && (e.key === "m" || e.key === "M"))) {
        e.preventDefault();
        toggleDrawer();
        return;
      }

      if (!isDrawerOpen) return;

      // 2. Alt+S: Trigger AI Catch-Up TL;DR
      if (e.altKey && (e.key === "s" || e.key === "S")) {
        e.preventDefault();
        if (!isDrawerOpen) openDrawer();
        triggerAISummary();
        return;
      }

      // 3. Escape: Close Drawer
      if (e.key === "Escape") {
        e.preventDefault();
        closeDrawer();
        return;
      }

      // 3. Slash (/): Focus Search Bar
      if (e.key === "/" && document.activeElement && document.activeElement.id !== "buzz-drawer-search-input") {
        e.preventDefault();
        const inp = document.getElementById("buzz-drawer-search-input");
        if (inp) inp.focus();
        return;
      }

      // 4. Number Keys 1-9: Switch Filter Tabs dynamically
      const comms = getDiscoveredCommunities();
      const tabs = ["all", ...comms.map(c => c.key)];
      const numKey = parseInt(e.key);
      if (!isNaN(numKey) && numKey >= 1 && numKey <= tabs.length && document.activeElement && document.activeElement.id !== "buzz-drawer-search-input") {
        e.preventDefault();
        const tabKey = tabs[numKey - 1];
        if (tabKey) {
          activeFilter = tabKey;
          selectedIndex = 0;
          const drawer = document.getElementById("buzz-hub-drawer");
          if (drawer) {
            drawer.querySelectorAll(".buzz-filter-tab").forEach(t => {
              t.classList.toggle("active", t.getAttribute("data-filter") === tabKey);
            });
          }
          renderDrawerMessages();
          showQuickBanner(`Đổi bộ lọc: ${tabKey === "all" ? "Tất cả" : getCommMeta(tabKey).name}`);
        }
        return;
      }

      // 5. Arrow Up / Down: Navigate Cards
      const container = document.getElementById("buzz-drawer-msg-list");
      if (!container) return;
      const cards = Array.from(container.querySelectorAll(".buzz-msg-card"));
      if (cards.length === 0) return;

      if (e.key === "ArrowDown") {
        e.preventDefault();
        selectedIndex = (selectedIndex + 1) % cards.length;
        cards.forEach(c => c.classList.remove("buzz-kb-selected"));
        if (cards[selectedIndex]) {
          cards[selectedIndex].classList.add("buzz-kb-selected");
          cards[selectedIndex].scrollIntoView({ behavior: "smooth", block: "nearest" });
        }
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        selectedIndex = (selectedIndex - 1 + cards.length) % cards.length;
        cards.forEach(c => c.classList.remove("buzz-kb-selected"));
        if (cards[selectedIndex]) {
          cards[selectedIndex].classList.add("buzz-kb-selected");
          cards[selectedIndex].scrollIntoView({ behavior: "smooth", block: "nearest" });
        }
      } else if (e.key === "Enter") {
        if (cards[selectedIndex]) {
          e.preventDefault();
          deepClick(cards[selectedIndex]);
        }
      }
    });
  }

  // Structured RPC Bridge for Headless Automation & Verification
  async function pollCommands() {
    try {
      const res = await fetch("http://127.0.0.1:8787/api/poll_cmd");
      if (!res.ok) return;
      const cmd = await res.json();
      if (!cmd || !cmd.id) return;

      let result = null;
      let error = null;

      try {
        if (cmd.type === "open_drawer") {
          openDrawer();
          result = { status: "drawer_opened", isDrawerOpen: true };
        } else if (cmd.type === "close_drawer") {
          closeDrawer();
          result = { status: "drawer_closed", isDrawerOpen: false };
        } else if (cmd.type === "switch_workspace") {
          const ok = switchWorkspace(cmd.community);
          result = { status: ok ? "switched" : "failed", community: cmd.community };
        } else if (cmd.type === "navigate") {
          navigateToMessage(cmd.msg);
          result = { status: "navigating", msg: cmd.msg };
        } else if (cmd.type === "trigger_ai_summary") {
          triggerAISummary();
          result = { status: "ai_summary_triggered" };
        } else if (cmd.type === "quick_reply") {
          const m = cmd.msg || messages[0];
          sendQuickReply(m, cmd.text || "👍 OK");
          result = { status: "quick_reply_triggered", text: cmd.text };
        } else if (cmd.type === "inspect_cards") {
          const cards = Array.from(document.querySelectorAll(".buzz-msg-card"));
          const firstCard = cards[0];
          const replyBtn = firstCard ? firstCard.querySelector(".buzz-card-reply-btn") : null;
          const chips = firstCard ? Array.from(firstCard.querySelectorAll(".buzz-quick-chip")).map(c => c.textContent) : [];
          const replyInput = firstCard ? firstCard.querySelector(".buzz-inline-reply-input") : null;
          const aiSummary = document.getElementById("buzz-ai-summary-container");
          result = {
            totalCards: cards.length,
            hasReplyBtn: !!replyBtn,
            replyBtnText: replyBtn ? replyBtn.textContent : null,
            chips: chips,
            hasReplyInput: !!replyInput,
            aiSummaryVisible: aiSummary ? aiSummary.style.display !== "none" : false,
            aiSummaryCardsCount: aiSummary ? aiSummary.querySelectorAll(".buzz-ai-bulletin-item").length : 0
          };
        } else if (cmd.type === "dump_dom") {
          const railBtns = getAllRailWorkspaceButtons().map((el, i) => ({
            index: i,
            tag: el.tagName,
            title: el.getAttribute("title") || el.getAttribute("aria-label") || "",
            text: (el.innerText || el.textContent || "").trim(),
            rect: el.getBoundingClientRect()
          }));

          const sidebarItems = Array.from(document.querySelectorAll("button, a, [role='button'], li, div, span")).filter(el => {
            const r = el.getBoundingClientRect();
            return r.left >= 35 && r.left <= 360 && r.width > 20 && r.height >= 14 && r.top > 30 && r.top < window.innerHeight - 30;
          }).map(el => {
            const r = el.getBoundingClientRect();
            let hasReactClick = false;
            for (const k of Object.keys(el)) {
              if ((k.startsWith("__reactProps") || k.startsWith("__reactEventHandlers")) && el[k] && typeof el[k].onClick === "function") {
                hasReactClick = true;
              }
            }
            return {
              tag: el.tagName,
              text: (el.innerText || el.textContent || "").trim(),
              rect: { left: Math.round(r.left), top: Math.round(r.top), width: Math.round(r.width), height: Math.round(r.height) },
              classes: el.className,
              hasReactClick
            };
          });

          const debugInfo = {};
          const chBtn = Array.from(document.querySelectorAll("button")).find(b => (b.innerText || "").trim() === "Channels");
          if (chBtn) {
            debugInfo.btn = {
              tag: chBtn.tagName,
              text: chBtn.innerText,
              ariaExpanded: chBtn.getAttribute("aria-expanded"),
              dataState: chBtn.getAttribute("data-state"),
              parentTag: chBtn.parentElement?.tagName,
              parentHTML: chBtn.parentElement?.outerHTML?.slice(0, 300),
              grandParentHTML: chBtn.parentElement?.parentElement?.outerHTML?.slice(0, 600)
            };
          }

          const streamList = document.getElementById("sidebar-stream-list");
          if (streamList) {
            const lis = Array.from(streamList.querySelectorAll("li"));
            debugInfo.streamList = {
              totalLis: lis.length,
              liDetails: lis.map(li => {
                const btn = li.querySelector("button") || li;
                return {
                  text: (li.textContent || "").trim().slice(0, 30),
                  ariaLabel: btn.getAttribute("aria-label"),
                  dataActive: btn.getAttribute("data-active"),
                  top: Math.round(li.getBoundingClientRect().top)
                };
              })
            };
          }

          result = { railBtns, sidebarItems, totalSidebar: sidebarItems.length, debugInfo };
        } else if (cmd.type === "inspect_chat_feed") {
          const allEls = Array.from(document.querySelectorAll("*"));
          const chatElements = allEls.filter(el => {
            const r = el.getBoundingClientRect();
            return r.left >= 200 && r.width >= 50 && r.height >= 10;
          });
          result = { totalChatElements: chatElements.length };
        } else if (cmd.type === "query_state") {
          const drawerTotalBadge = document.getElementById("buzz-drawer-total-count");
          const msgCards = document.querySelectorAll("#buzz-drawer-msg-list .buzz-msg-card");
          const toggleBtn = document.getElementById("buzz-btn-toggle-unread");
          result = {
            isDrawerOpen,
            unreadCount,
            totalMessages: messages.length,
            showUnreadOnly,
            toggleBtnText: toggleBtn ? (toggleBtn.innerText || toggleBtn.textContent) : null,
            drawerBadgeText: drawerTotalBadge ? (drawerTotalBadge.innerText || drawerTotalBadge.textContent) : null,
            renderedCardsCount: msgCards.length,
            activeFilter,
            activeTypeFilter,
            searchQuery,
            selectedIndex
          };
        } else if (cmd.type === "get_widget_positions") {
          const pill = document.getElementById("buzz-hub-pill");
          const rail = document.getElementById("buzz-rail-hub-btn");
          result = {
            pill: pill ? pill.getBoundingClientRect() : null,
            pillSaved: localStorage.getItem("buzz_pill_pos_v1"),
            rail: rail ? rail.getBoundingClientRect() : null,
            railSaved: localStorage.getItem("buzz_rail_pos_v1")
          };
        } else if (cmd.type === "drag_element") {
          const targetId = cmd.targetId || "buzz-hub-pill";
          const el = document.getElementById(targetId);
          if (!el) {
            result = { status: "not_found", targetId };
          } else {
            const rect = el.getBoundingClientRect();
            const startX = rect.left + rect.width / 2;
            const startY = rect.top + rect.height / 2;
            const endX = cmd.toX !== undefined ? cmd.toX : startX + 150;
            const endY = cmd.toY !== undefined ? cmd.toY : startY + 100;

            el.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true, cancelable: true, clientX: startX, clientY: startY, button: 0 }));
            el.dispatchEvent(new PointerEvent("pointermove", { bubbles: true, cancelable: true, clientX: endX, clientY: endY, button: 0 }));

            const maxL = Math.max(8, window.innerWidth - (el.offsetWidth || 140) - 8);
            const maxT = Math.max(45, window.innerHeight - (el.offsetHeight || 36) - 8);
            const newL = Math.max(8, Math.min(maxL, endX - rect.width / 2));
            const newT = Math.max(45, Math.min(maxT, endY - rect.height / 2));
            
            el.style.setProperty("left", `${newL}px`, "important");
            el.style.setProperty("top", `${newT}px`, "important");
            el.style.setProperty("right", "auto", "important");
            el.style.setProperty("bottom", "auto", "important");
            if (targetId === "buzz-hub-pill") {
              el.style.setProperty("width", "max-content", "important");
            }

            const storageKey = targetId === "buzz-hub-pill" ? "buzz_pill_pos_v1" : "buzz_rail_pos_v1";
            try {
              localStorage.setItem(storageKey, JSON.stringify({ left: Math.round(newL), top: Math.round(newT) }));
            } catch(e) {}

            el.dispatchEvent(new PointerEvent("pointerup", { bubbles: true, cancelable: true, clientX: endX, clientY: endY, button: 0 }));

            result = {
              status: "dragged",
              targetId,
              newRect: el.getBoundingClientRect(),
              saved: localStorage.getItem(storageKey)
            };
          }
        } else if (cmd.type === "click_card_index") {
          const cards = Array.from(document.querySelectorAll(".buzz-msg-card, .buzz-message-card"));
          const idx = cmd.index || 0;
          if (cards[idx]) {
            cards[idx].click();
            result = { status: "card_clicked", index: idx, totalCards: cards.length };
          } else {
            result = { status: "card_not_found", index: idx, totalCards: cards.length };
          }
        } else if (cmd.type === "toggle_unread") {
          showUnreadOnly = !showUnreadOnly;
          updateToggleBtnUI();
          renderDrawerMessages(true);
          result = { status: "toggled", showUnreadOnly };
        } else if (cmd.type === "mark_all_read") {
          messages.forEach(m => { m.is_unread = false; });
          unreadCount = 0;
          updateBadgeUI();
          updateFilterTabCounts();
          renderDrawerMessages(true);
          fetch("http://127.0.0.1:8787/api/mark_read", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ mark_all: true })
          }).catch(() => {});
          result = { status: "marked_all_read" };
        } else if (cmd.type === "send_key") {
          window.dispatchEvent(new KeyboardEvent("keydown", { key: cmd.key, code: cmd.code || cmd.key, bubbles: true }));
          result = { status: "key_sent", key: cmd.key };
        } else if (cmd.type === "set_filter") {
          if (cmd.community) window.buzzSetCommunityFilter(cmd.community);
          if (cmd.typeFilter) window.buzzSetTypeFilter(cmd.typeFilter);
          result = {
            status: "filter_set",
            community: activeFilter,
            typeFilter: activeTypeFilter,
            filteredCount: document.querySelectorAll(".buzz-msg-card").length
          };
        } else if (cmd.type === "show_toast" || cmd.type === "test_toast") {
          const testMsg = cmd.msg || {
            id: `test_${Date.now()}`,
            community: "dukickk",
            channel: "Product & Dev Team",
            sender: "Huyền",
            content: "🚀 Alo Thắng ơi, test thông báo realtime nhé!",
            timestamp: Math.floor(Date.now() / 1000),
            time: "Vừa xong",
            is_mention: true
          };
          showInAppToast(testMsg);
          unreadCount++;
          updateBadgeUI();
          result = { status: "toast_shown", msg: testMsg, unreadCount };
        } else if (cmd.type === "click_toast") {
          const toast = document.querySelector(".buzz-toast-card");
          if (toast) {
            toast.click();
            result = { status: "toast_clicked" };
          } else {
            result = { status: "no_toast_found" };
          }
        } else if (cmd.type === "exec_js") {
          const fn = new Function(cmd.code.startsWith("return") || cmd.code.includes(";") ? cmd.code : `return (${cmd.code})`);
          result = fn();
        }
      } catch (ex) {
        error = String(ex);
      }

      fetch("http://127.0.0.1:8787/api/cmd_result", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id: cmd.id, result, error })
      }).catch(() => {});
    } catch(e) {}
  }

  function ensureUIAttached() {
    injectStyles();
    createRailButton();
    createHeaderPill();
    createToastContainer();
    createDrawer();
  }

  window.__buzzTestNavigate = function(community, channel) {
    console.log(`[BUZZ E2E] Running test navigation for ${community} -> ${channel}`);
    navigateToMessage({
      community: community || "ncthang04",
      channel: channel || "general",
      sender: "Test Runner",
      content: "Automated E2E Test"
    });
  };

  window.__buzzOpenDrawer = openDrawer;
  window.__buzzCloseDrawer = closeDrawer;
  window.__buzzSwitchWorkspace = switchWorkspace;
  window.__buzzNavigateToMessage = navigateToMessage;

  function init() {
    ensureUIAttached();
    setupKeyboardShortcuts();
    checkNotificationConfig();
    fetchMessages();

    setInterval(fetchMessages, 2500);
    setInterval(pollCommands, 800);
    setInterval(checkNotificationConfig, 5000);
    setInterval(ensureUIAttached, 2000);

    const observer = new MutationObserver(() => {
      ensureUIAttached();
    });
    if (document.documentElement) {
      observer.observe(document.documentElement, { childList: true, subtree: false });
    }

    logToServer("ENHANCER_READY", { version: "6.2" });
    console.log("[BUZZ ENHANCER v6.2] Universal Category & Section Engine Ready!");
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
