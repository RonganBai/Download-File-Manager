# -*- coding: utf-8 -*-
"""与「格式转换器」联动（可选）：装了格式转换器时，右键菜单多出「转换为 ▸」；没装则什么都不显示。

两个软件互不依赖，只通过格式转换器写出的 integration.json 约定（protocol 1）：
  - command：启动格式转换器的命令；
  - quick：常用目标格式（与它的悬浮球一致），每项的 "to" 直接传给 --to；
  - inputs：它能处理的输入扩展名（按 image / doc / sheet / vector / video 分类）。
调用方式：<command> --to <to> --from 下载管家 <文件…>。格式转换器已在运行时会把任务交给运行中的那个。
"""
import json
import os

from PyQt6.QtCore import QProcess

SOURCE = "下载管家"
DOWNLOAD_URL = "https://github.com/RonganBai/Universal-File-Format-Converter/releases/latest"
PROTOCOL = 1
INFO_PATH = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "格式转换器", "integration.json")
_cache = {"mtime": None, "info": None}


def load(path=None):
    """读取并校验 integration.json；格式转换器没装 / 已卸载 / 文件损坏时返回 None。"""
    path = path or INFO_PATH
    try:
        mt = os.path.getmtime(path)
    except OSError:
        return None
    if _cache["mtime"] != (path, mt):
        try:
            with open(path, encoding="utf-8") as f:
                info = json.load(f)
        except (OSError, ValueError):
            info = None
        _cache.update(mtime=(path, mt), info=info)
    info = _cache["info"]
    if not isinstance(info, dict) or info.get("protocol") != PROTOCOL:
        return None
    cmd = info.get("command")
    if not (isinstance(cmd, list) and cmd and all(isinstance(c, str) for c in cmd)):
        return None
    if not all(os.path.isfile(c) for c in cmd[:2] if c.lower().endswith((".exe", ".py"))):
        return None                       # 程序文件已不存在（已卸载）
    return info


def kinds_of(paths, info):
    """每个文件所属的输入类别；有任一文件无法处理时返回 None。"""
    inputs = info.get("inputs") or {}
    kinds = set()
    for p in paths:
        if not os.path.isfile(p):
            return None
        ext = os.path.splitext(p)[1].lower().lstrip(".")
        hit = [k for k, exts in inputs.items() if ext in exts]
        if not hit:
            return None
        kinds.update(hit)
    return kinds


def targets_for(paths, info):
    """可显示的常用格式。视频只给视频格式和动图（GIF / WEBP）；不含视频时不显示视频格式。"""
    kinds = kinds_of(paths, info)
    if not kinds:
        return []
    only_video = kinds == {"video"}
    out = []
    for q in info.get("quick") or []:
        if not isinstance(q, dict) or not q.get("to"):
            continue
        k, fmt = q.get("kind"), str(q.get("fmt", "")).upper()
        if only_video and k != "video" and fmt not in ("GIF", "WEBP"):
            continue
        if not only_video and k == "video":
            continue
        out.append(q)
    return out


def run(info, paths, to=None):
    cmd = info["command"]
    args = cmd[1:] + (["--to", to] if to else []) + ["--from", SOURCE] + list(paths)
    res = QProcess.startDetached(cmd[0], args)
    return res[0] if isinstance(res, tuple) else bool(res)


def add_menu(menu, paths, toast):
    """给右键菜单加「转换为 ▸」。没装格式转换器或文件无法转换时不加，返回是否添加。"""
    info = load()
    if not info or not paths or kinds_of(paths, info) is None:
        return False
    sub = menu.addMenu("转换为")

    def go(to, label):
        n = len(paths)
        if run(info, paths, to):
            toast(f"已交给格式转换器：{n} 个文件 → {label}" if to else f"已在格式转换器中打开 {n} 个文件")
        else:
            toast("无法启动格式转换器，请确认它已正确安装")

    for q in targets_for(paths, info):
        label = str(q.get("label") or q.get("fmt") or q["to"])
        sub.addAction(label, lambda to=q["to"], label=label: go(to, label))
    if sub.actions():
        sub.addSeparator()
    sub.addAction("更多格式…（在格式转换器中打开）", lambda: go(None, ""))
    return True


def status():
    """设置页「相关应用」显示的状态：(是否已安装, 说明文字)。"""
    info = load()
    if info:
        return True, f"已安装 v{info.get('version', '?')}：在文件上右键 →「转换为」即可直接转换。"
    return False, "批量转换图片、文档、表格和视频格式。安装后，这里的文件右键菜单会多出「转换为」。"
