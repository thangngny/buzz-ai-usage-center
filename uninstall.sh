#!/usr/bin/env bash
# ==============================================================================
# 🔄 BUZZ DESKTOP ECOSYSTEM — UNINSTALLER
# ==============================================================================
set -euo pipefail

C_RESET="\033[0m"
C_BOLD="\033[1m"
C_GREEN="\033[32m"
C_YELLOW="\033[33m"

TARGET_HOME="${HOME}"
BIN_DIR="${TARGET_HOME}/.local/bin"
LIB_DIR="${TARGET_HOME}/.local/lib"
SYSTEMD_USER_DIR="${TARGET_HOME}/.config/systemd/user"

echo -e "${C_YELLOW}${C_BOLD}Đang gỡ bỏ cài đặt Buzz Enhancer & Services...${C_RESET}"

# Stop and disable systemd services
if command -v systemctl &>/dev/null; then
    systemctl --user stop buzz-sound-notifier.service buzz-usage-dashboard.service 2>/dev/null || true
    systemctl --user disable buzz-sound-notifier.service buzz-usage-dashboard.service 2>/dev/null || true
fi
rm -f "${SYSTEMD_USER_DIR}/buzz-sound-notifier.service" "${SYSTEMD_USER_DIR}/buzz-usage-dashboard.service"
if command -v systemctl &>/dev/null; then
    systemctl --user daemon-reload 2>/dev/null || true
fi

# Restore original buzz-desktop binary if backup exists
if [ -f "${BIN_DIR}/buzz-desktop-bin" ]; then
    mv -f "${BIN_DIR}/buzz-desktop-bin" "${BIN_DIR}/buzz-desktop"
    echo -e "  ${C_GREEN}✓ Đã khôi phục binary gốc buzz-desktop${C_RESET}"
fi

# Remove injector library
rm -f "${LIB_DIR}/libbuzz_enhancer.so"
rm -f "${BIN_DIR}/buzz-sound"

echo -e "${C_GREEN}${C_BOLD}✓ Quá trình gỡ bỏ hoàn tất! Hệ thống Buzz Desktop đã trở về mặc định.${C_RESET}"
