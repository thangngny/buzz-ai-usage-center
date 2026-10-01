#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Duong dan Buzz dung duoc ca Windows lan WSL.

UNC \\\\wsl$\\... khong mo duoc tu Python tren may nay. File nam trong WSL
(managed-agents, phien Codex cua agent) duoc doc bang `wsl.exe`. File nam
tren Windows (app Codex) doc truc tiep. CSDL usage.db luon o thu muc project
phia Windows /mnt/d de dashboard va quota cung mot process ghi.
"""
from __future__ import annotations

import glob
import json
import os
import subprocess
import sys

DISTRO = os.environ.get("BUZZ_WSL_DISTRO", "Ubuntu-24.04")
WSL_USER = os.environ.get("BUZZ_WSL_USER", "openclawboss")
APP_REL = ".local/share/xyz.block.buzz.app.dev"

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def in_wsl() -> bool:
    try:
        return "microsoft" in open("/proc/version", encoding="utf-8").read().lower()
    except OSError:
        return False


def in_windows() -> bool:
    return os.name == "nt"


def linux_home() -> str:
    return "/home/" + WSL_USER


def linux_app() -> str:
    return linux_home() + "/" + APP_REL


def win_to_wsl(path: str) -> str:
    path = os.path.abspath(path)
    if len(path) >= 2 and path[1] == ":":
        return "/mnt/" + path[0].lower() + path[2:].replace("\\", "/")
    return path.replace("\\", "/")


def wsl_run(args, timeout=180):
    cmd = ["wsl", "-d", DISTRO, "-u", WSL_USER, "--"] + list(args)
    # WSL tools emit UTF-8.  Windows' default text encoding can be cp1252,
    # which makes subprocess reader threads discard stdout on Vietnamese text.
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )


def wsl_bash(script: str, timeout=180):
    return wsl_run(["bash", "-lc", script], timeout=timeout)


def windows_codex_homes() -> list:
    out = []
    drive = os.environ.get("SystemDrive", "C:")
    if not drive.endswith(("\\", "/")):
        drive += os.sep
    users = os.path.join(drive, "Users")
    if not os.path.isdir(users):
        return out
    for name in os.listdir(users):
        if name in ("Public", "Default", "Default User", "All Users"):
            continue
        base = os.path.join(users, name)
        try:
            for ent in os.listdir(base):
                if not ent.startswith(".codex"):
                    continue
                p = os.path.join(base, ent)
                if os.path.isdir(p):
                    out.append(p)
        except OSError:
            continue
    return sorted(set(out))


def linux_codex_home_list() -> list:
    """Duong dan Linux (khong phai UNC) cua moi ~/.codex* trong WSL."""
    if in_wsl():
        found = glob.glob("/home/*/.codex*") + glob.glob("/root/.codex*")
        return sorted(p for p in found if os.path.isdir(p))
    r = wsl_bash("ls -d /home/*/.codex* /root/.codex* 2>/dev/null")
    return [ln.strip() for ln in (r.stdout or "").splitlines() if ln.strip()]
