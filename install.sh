#!/usr/bin/env bash
# ==============================================================================
# 🚀 BUZZ DESKTOP ECOSYSTEM & UI ENHANCER — 1-CLICK TURNKEY INSTALLER
# ==============================================================================
# Tự động triển khai bộ công cụ nâng cấp toàn diện cho Buzz Desktop:
#  1. Glassmorphic Message Hub Drawer (Alt+M, lọc chưa xem, tìm kiếm tức thì)
#  2. ⚡ AI Catch-Up TL;DR (Tóm tắt nhanh tin tồn đọng đa nhóm)
#  3. Quick Reply & Action Chips (Trả lời nhanh 1 chạm trực tiếp trên thẻ)
#  4. Multi-Relay Real-Time Sound & Visual Notifier (Âm báo cho mọi tin nhắn)
#  5. Active Viewport Auto-Read (Tự động xóa tin chưa đọc khi đang xem)
#  6. AI Usage Center Backend & Dashboard (127.0.0.1:8787)
# ==============================================================================

set -euo pipefail

# Colors
C_RESET="\033[0m"
C_BOLD="\033[1m"
C_GREEN="\033[32m"
C_BLUE="\033[34m"
C_CYAN="\033[36m"
C_YELLOW="\033[33m"
C_RED="\033[31m"
C_PURPLE="\033[35m"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET_HOME="${HOME}"
APP_DATA_DIR="${TARGET_HOME}/.local/share/xyz.block.buzz.app"
BIN_DIR="${TARGET_HOME}/.local/bin"
LIB_DIR="${TARGET_HOME}/.local/lib"
CONFIG_DIR="${TARGET_HOME}/.config/buzz"
SYSTEMD_USER_DIR="${TARGET_HOME}/.config/systemd/user"
USAGE_CONTROL_DIR="${APP_DATA_DIR}/agents/usage-control"

echo -e "${C_CYAN}${C_BOLD}"
echo "======================================================================"
echo "   ⚡ BUZZ DESKTOP ENHANCER & ECOSYSTEM SUITE — CÀI ĐẶT TỰ ĐỘNG     "
echo "======================================================================"
echo -e "${C_RESET}"

# 1. Check requirements
echo -e "${C_BLUE}==> [1/6] Kiểm tra môi trường hệ thống...${C_RESET}"
if ! command -v python3 &>/dev/null; then
    echo -e "${C_RED}[LỖI] Không tìm thấy Python 3! Vui lòng cài đặt: sudo apt install python3${C_RESET}" >&2
    exit 1
fi
echo -e "  ${C_GREEN}✓ Python 3: $(python3 --version)${C_RESET}"

# Check for audio player
AUDIO_PLAYER=""
if command -v paplay &>/dev/null; then
    AUDIO_PLAYER="paplay"
elif command -v pw-play &>/dev/null; then
    AUDIO_PLAYER="pw-play"
elif command -v aplay &>/dev/null; then
    AUDIO_PLAYER="aplay"
fi
if [ -n "$AUDIO_PLAYER" ]; then
    echo -e "  ${C_GREEN}✓ Bộ phát âm thanh: $AUDIO_PLAYER${C_RESET}"
else
    echo -e "  ${C_YELLOW}⚠ Cảnh báo: Không tìm thấy paplay/pw-play. Để nghe âm thanh, cài: sudo apt install pulseaudio-utils${C_RESET}"
fi

# 2. Setup directory tree
echo -e "${C_BLUE}==> [2/6] Tạo cấu trúc thư mục...${C_RESET}"
mkdir -p "${APP_DATA_DIR}/sounds"
mkdir -p "${APP_DATA_DIR}/logs"
mkdir -p "${APP_DATA_DIR}/localstorage"
mkdir -p "${BIN_DIR}"
mkdir -p "${LIB_DIR}"
mkdir -p "${CONFIG_DIR}"
mkdir -p "${SYSTEMD_USER_DIR}"
mkdir -p "${USAGE_CONTROL_DIR}"
echo -e "  ${C_GREEN}✓ Đã chuẩn bị thư mục đích trong ${TARGET_HOME}${C_RESET}"

# 3. Compile or copy WebKit Injector
echo -e "${C_BLUE}==> [3/6] Cài đặt WebKit Injector Library (libbuzz_enhancer.so)...${C_RESET}"
INJECTOR_SRC="${SCRIPT_DIR}/desktop-enhancer/injector/libbuzz_enhancer.c"
PRECOMPILED_SO="${SCRIPT_DIR}/desktop-enhancer/injector/libbuzz_enhancer.so"
TARGET_SO="${LIB_DIR}/libbuzz_enhancer.so"

COMPILED=0
if command -v gcc &>/dev/null && [ -f "$INJECTOR_SRC" ]; then
    echo -e "  🔨 Biên dịch thư viện từ mã nguồn C (gcc)..."
    if gcc -shared -fPIC -O2 "$INJECTOR_SRC" -o "$TARGET_SO" -ldl 2>/dev/null; then
        echo -e "  ${C_GREEN}✓ Đã biên dịch thành công: $TARGET_SO${C_RESET}"
        COMPILED=1
    fi
fi

if [ "$COMPILED" -eq 0 ]; then
    if [ -f "$PRECOMPILED_SO" ]; then
        echo -e "  📦 Sử dụng thư viện precompiled x86_64..."
        cp -f "$PRECOMPILED_SO" "$TARGET_SO"
        echo -e "  ${C_GREEN}✓ Đã cài đặt: $TARGET_SO${C_RESET}"
    else
        echo -e "${C_RED}[LỖI] Không tìm thấy mã nguồn hoặc file thư viện .so!${C_RESET}" >&2
        exit 1
    fi
fi
chmod 755 "$TARGET_SO"

# 4. Binary wrapper setup
echo -e "${C_BLUE}==> [4/6] Thiết lập Launcher Wrapper phi xâm lấn cho Buzz Desktop...${C_RESET}"
REAL_DESKTOP_BIN="${BIN_DIR}/buzz-desktop-bin"
DESKTOP_LAUNCHER="${BIN_DIR}/buzz-desktop"

# If buzz-desktop exists and is an ELF executable (not a script), back it up to buzz-desktop-bin
if [ -f "$DESKTOP_LAUNCHER" ] && [ ! -f "$REAL_DESKTOP_BIN" ]; then
    if file "$DESKTOP_LAUNCHER" 2>/dev/null | grep -q "ELF"; then
        echo -e "  📦 Phát hiện binary gốc $DESKTOP_LAUNCHER -> Sao lưu thành $REAL_DESKTOP_BIN"
        mv "$DESKTOP_LAUNCHER" "$REAL_DESKTOP_BIN"
    fi
fi

# Copy our wrapper script
cp -f "${SCRIPT_DIR}/bin/buzz-desktop" "$DESKTOP_LAUNCHER"
chmod +x "$DESKTOP_LAUNCHER"
echo -e "  ${C_GREEN}✓ Đã cài đặt launcher wrapper: $DESKTOP_LAUNCHER${C_RESET}"

# Install CLI buzz-sound
cp -f "${SCRIPT_DIR}/bin/buzz-sound" "${BIN_DIR}/buzz-sound"
chmod +x "${BIN_DIR}/buzz-sound"
echo -e "  ${C_GREEN}✓ Đã cài đặt CLI quản lý âm thanh: ${BIN_DIR}/buzz-sound${C_RESET}"

# 5. Deploy scripts, sounds & backend engine
echo -e "${C_BLUE}==> [5/6] Triển khai mã nguồn JS, Notifier, Âm thanh & Backend...${C_RESET}"
cp -f "${SCRIPT_DIR}/desktop-enhancer/buzz_ui_enhancer.js" "${APP_DATA_DIR}/buzz_ui_enhancer.js"
cp -f "${SCRIPT_DIR}/desktop-enhancer/buzz_sound_notifier.py" "${APP_DATA_DIR}/buzz_sound_notifier.py"
chmod +x "${APP_DATA_DIR}/buzz_sound_notifier.py"

if [ -f "${SCRIPT_DIR}/desktop-enhancer/chime_default.wav" ]; then
    cp -f "${SCRIPT_DIR}/desktop-enhancer/chime_default.wav" "${APP_DATA_DIR}/chime_default.wav"
fi

if [ -d "${SCRIPT_DIR}/desktop-enhancer/sounds" ]; then
    cp -rf "${SCRIPT_DIR}/desktop-enhancer/sounds/"* "${APP_DATA_DIR}/sounds/"
fi

# Deploy backend usage-control suite (if running from separate cloned repo)
if [ "$SCRIPT_DIR" != "$USAGE_CONTROL_DIR" ]; then
    echo -e "  📂 Đồng bộ dữ liệu backend sang ${USAGE_CONTROL_DIR}..."
    cp -rf "${SCRIPT_DIR}/bin" "${USAGE_CONTROL_DIR}/"
    cp -rf "${SCRIPT_DIR}/lib" "${USAGE_CONTROL_DIR}/"
    cp -rf "${SCRIPT_DIR}/locales" "${USAGE_CONTROL_DIR}/"
    if [ -f "${SCRIPT_DIR}/usage.db" ] && [ ! -f "${USAGE_CONTROL_DIR}/usage.db" ]; then
        cp -f "${SCRIPT_DIR}/usage.db" "${USAGE_CONTROL_DIR}/usage.db"
    fi
fi
chmod +x "${USAGE_CONTROL_DIR}/bin/"* 2>/dev/null || true

# Initialize sound configuration if not present
if [ ! -f "${CONFIG_DIR}/sound-notifier.json" ]; then
    cat > "${CONFIG_DIR}/sound-notifier.json" <<EOF
{
  "enabled": true,
  "sound_message": "${APP_DATA_DIR}/sounds/elevenlabs_thang.wav",
  "sound_mention": "${APP_DATA_DIR}/sounds/mention.wav",
  "show_desktop_notification": true
}
EOF
    echo -e "  ${C_GREEN}✓ Khởi tạo cấu hình âm thanh ban đầu${C_RESET}"
fi

# 6. Install and start Systemd User Services
echo -e "${C_BLUE}==> [6/6] Kích hoạt các dịch vụ Systemd User Services...${C_RESET}"
cp -f "${SCRIPT_DIR}/systemd/buzz-usage-dashboard.service" "${SYSTEMD_USER_DIR}/buzz-usage-dashboard.service"
cp -f "${SCRIPT_DIR}/systemd/buzz-sound-notifier.service" "${SYSTEMD_USER_DIR}/buzz-sound-notifier.service"

if command -v systemctl &>/dev/null; then
    systemctl --user daemon-reload
    systemctl --user enable buzz-usage-dashboard.service buzz-sound-notifier.service
    systemctl --user restart buzz-usage-dashboard.service buzz-sound-notifier.service
    echo -e "  ${C_GREEN}✓ Dịch vụ buzz-usage-dashboard và buzz-sound-notifier đã được kích hoạt và khởi chạy!${C_RESET}"
fi

echo ""
echo -e "${C_GREEN}${C_BOLD}======================================================================${C_RESET}"
echo -e "${C_GREEN}${C_BOLD}   🎉 CÀI ĐẶT THÀNH CÔNG HỆ THỐNG BUZZ DESKTOP ECOSYSTEM!            ${C_RESET}"
echo -e "${C_GREEN}${C_BOLD}======================================================================${C_RESET}"
echo ""
echo -e "${C_CYAN}📋 Hướng dẫn sử dụng nhanh:${C_RESET}"
echo -e "  • ${C_BOLD}Khởi động ứng dụng:${C_RESET} Chạy lệnh: ${C_YELLOW}buzz-desktop${C_RESET} (hoặc mở Buzz Desktop từ menu)"
echo -e "  • ${C_BOLD}Mở Hộp thư nhanh:${C_RESET} Nhấn phím tắt ${C_PURPLE}Alt + M${C_RESET} trên bàn phím"
echo -e "  • ${C_BOLD}Tóm tắt AI tức thì:${C_RESET} Nhấn ${C_PURPLE}Alt + S${C_RESET} hoặc bấm nút ${C_PURPLE}⚡ Tóm tắt AI${C_RESET}"
echo -e "  • ${C_BOLD}Trả lời nhanh 1 chạm:${C_RESET} Bấm ${C_PURPLE}💬 Trả lời nhanh${C_RESET} trên bất kỳ thẻ tin nhắn nào"
echo -e "  • ${C_BOLD}Quản lý âm thanh:${C_RESET} Dùng lệnh: ${C_YELLOW}buzz-sound status${C_RESET} hoặc ${C_YELLOW}buzz-sound test${C_RESET}"
echo -e "  • ${C_BOLD}Xem Dashboard AI:${C_RESET} Truy cập trình duyệt: ${C_YELLOW}http://127.0.0.1:8787${C_RESET}"
echo ""
