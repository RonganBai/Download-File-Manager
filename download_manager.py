# -*- coding: utf-8 -*-
"""下载管家：下载文件夹的可视化管理 + 自动整理 + 定期 / 容量阈值清理（界面风格与格式转换器一致）。"""
import ctypes
import hashlib
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import winreg
from ctypes import wintypes
from datetime import datetime, timedelta

from PyQt6.QtCore import QFileSystemWatcher, QThread, pyqtSignal, Qt, QTimer, QSize, QRectF, QPropertyAnimation, pyqtProperty, QFileInfo, QUrl, QMimeData, QPoint
from PyQt6.QtGui import QIcon, QPixmap, QPainter, QColor, QFont, QPen, QAction, QKeySequence, QShortcut, QPainterPath, QDesktopServices, QImage, QImageReader
from PyQt6.QtNetwork import QLocalServer, QLocalSocket
from PyQt6.QtWidgets import (QApplication, QWidget, QFrame, QLabel, QPushButton, QLineEdit, QHBoxLayout, QVBoxLayout,
                             QGridLayout, QTreeWidget, QTreeWidgetItem, QAbstractItemView, QFileIconProvider, QMenu,
                             QStackedWidget, QScrollArea, QCheckBox, QSpinBox, QDoubleSpinBox, QComboBox, QTextBrowser,
                             QProgressBar, QSystemTrayIcon, QDialog, QFileDialog, QHeaderView, QSlider)

VERSION = "2.2.1"
APP = "下载管家"
CFG_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), APP)
CFG_PATH = os.path.join(CFG_DIR, "config.json")
ASSETS = os.path.join(getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__))), "assets")
DEFAULTS = dict(auto=True, clean_on=False, clean_days=30, cap_on=False, cap_gb=20.0, protect=["重要文件"],
                autostart=False, close="tray", theme="dark", side_open=True,
                accent="blue", bg_image="", bg_vis=35, card_alpha=88, win_opacity=100, img_colors=[],
                sort_key="time", sort_desc=True)
BORDER = 6

RULES = [
    ("重要文件", "", ".pdf .doc .docx .xls .xlsx .ppt .pptx .txt .md .csv .wps .et .dps .rtf .odt"),
    ("安装包", "", ".exe .msi .msix .appx .apk .dmg .iso"),
    ("压缩包", "", ".zip .rar .7z .tar .gz .bz2 .xz"),
    ("图片", "", ".jpg .jpeg .png .gif .bmp .webp .svg .heic .ico"),
    ("视频", "", ".mp4 .mkv .avi .mov .wmv .flv .webm"),
    ("音乐", "", ".mp3 .wav .flac .aac .m4a .ogg"),
    ("代码", "", ".py .js .html .css .json .java .c .cpp .ps1 .bat .sh"),
]
CATS = [r[0] for r in RULES] + ["其他文件"]
GLYPH = {r[0]: r[1] for r in RULES}
GLYPH.update({"其他文件": "", "未整理": "", "全部文件": ""})
SORTS = (("修改时间", "time"), ("名称", "name"), ("大小", "size"), ("分类", "cat"), ("类型（扩展名）", "ext"))
COL_KEYS = ("name", "cat", "size", "time")
COL_NAMES = ("名称", "分类", "大小", "修改时间")
TIME_FILTERS = (("全部时间", None), ("今天", 0), ("最近 7 天", 7), ("最近 30 天", 30), ("最近 1 年", 365), ("1 年以前", -365))
MB = 1024 * 1024
SIZE_FILTERS = (("全部大小", None), ("小于 1 MB", (0, MB)), ("1 – 100 MB", (MB, 100 * MB)),
                ("100 MB – 1 GB", (100 * MB, 1024 * MB)), ("大于 1 GB", (1024 * MB, 1 << 62)))
SKIP_EXT = {".crdownload", ".part", ".partial", ".download", ".tmp"}
THUMB_EXT = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".ico"}

# ---------------- 主题（与格式转换器 v1.13 相同的配色） ----------------
# 背景层（frame / nav / card / list）偏暗、偏平；可点击的控件（btn / inp）更亮并带明显描边，一眼区分
BASE_THEMES = {
    "dark": dict(frame="#101013", border="#2c2c33", text="#ececf0", muted="#a6a6b0", faint="#787882",
                 card="#1b1b20", cardb="#2a2a31", nav="#0d0d10", area="#222228", areab="#2e2e35",
                 btn="#2f2f38", btnh="#3b3b46", btnb="#4a4a56", inp="#26262d", list="#16161a",
                 sep="#2c2c33", tbp="#45454f", knob_off="#55555f", danger="#e5484d"),
    "light": dict(frame="#dfe3e9", border="#c9ced6", text="#22262d", muted="#545b67", faint="#80868f",
                  card="#f2f4f7", cardb="#d5dae1", nav="#d6dbe2", area="#e8ebf0", areab="#d3d8df",
                  btn="#ffffff", btnh="#f3f6fb", btnb="#b9c0ca", inp="#ffffff", list="#f8f9fb",
                  sep="#cdd2d9", tbp="#e2e6ec", knob_off="#b3bac4", danger="#d93036"),
}
ACCENTS = (("blue", "蓝", "#3b82f6"), ("violet", "紫", "#8b5cf6"), ("teal", "青", "#14b8a6"),
           ("green", "绿", "#22a06b"), ("orange", "橙", "#f97316"), ("pink", "粉", "#ec4899"), ("red", "红", "#ef4444"))
THEMES = {k: dict(v) for k, v in BASE_THEMES.items()}
THEME = "dark"


def C(k):
    return THEMES[THEME][k]


def _mix(a, b, t):
    a, b = QColor(a), QColor(b)
    return QColor(round(a.red() + (b.red() - a.red()) * t), round(a.green() + (b.green() - a.green()) * t),
                  round(a.blue() + (b.blue() - a.blue()) * t)).name()


def _lum(c):
    def ch(v):
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    c = QColor(c)
    return 0.2126 * ch(c.red()) + 0.7152 * ch(c.green()) + 0.0722 * ch(c.blue())


def contrast(a, b):
    la, lb = _lum(a), _lum(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def readable_accent(color, theme):
    """把任意颜色调整成可用的强调色：按钮上的白字对比度 ≥ 4.5，并在当前背景上清楚可见。"""
    c = QColor(color)
    h, s = c.hslHueF(), c.hslSaturationF()
    if h < 0 or s < 0.12:            # 灰色图片：退回默认蓝
        return "#3b82f6" if theme == "dark" else "#3a73d6"
    s = min(max(s, 0.55), 0.85)
    l = 0.52 if theme == "dark" else 0.46
    out = QColor.fromHslF(h, s, l)
    while contrast("#ffffff", out.name()) < 4.5 and l > 0.18:
        l -= 0.02
        out = QColor.fromHslF(h, s, l)
    return out.name()


def image_colors(path, n=5):
    """提取图片的主色：按色相分桶，按饱和度 × 亮度加权，返回最突出的几种颜色。"""
    img = QImage(path)
    if img.isNull():
        return []
    img = img.scaled(64, 64, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
    buckets = {}
    for y in range(img.height()):
        for x in range(img.width()):
            c = img.pixelColor(x, y)
            h, s, v = c.hsvHueF(), c.hsvSaturationF(), c.valueF()
            if h < 0 or s < 0.22 or v < 0.2:
                continue
            k = int(h * 24) % 24
            b = buckets.setdefault(k, [0.0, 0.0, 0.0, 0.0])
            w = s * v
            b[0] += w; b[1] += c.red() * w; b[2] += c.green() * w; b[3] += c.blue() * w
    top = sorted(buckets.values(), key=lambda b: -b[0])[:n]
    out = [QColor(int(b[1] / b[0]), int(b[2] / b[0]), int(b[3] / b[0])).name() for b in top if b[0] > 0]
    if not out:   # 几乎无彩色：取平均色
        r = g = bl = 0
        for y in range(img.height()):
            for x in range(img.width()):
                c = img.pixelColor(x, y); r += c.red(); g += c.green(); bl += c.blue()
        t = img.width() * img.height()
        out = [QColor(r // t, g // t, bl // t).name()]
    return out


def compose_theme(cfg):
    """按外观设置生成当前配色：背景层混入少量图片主色，强调色来自预设或图片。"""
    theme = cfg.get("theme", "dark")
    t = dict(BASE_THEMES[theme])
    dark = theme == "dark"
    imgc = cfg.get("img_colors") or []
    if cfg.get("bg_image") and imgc:
        for k in ("frame", "card", "nav", "area", "list", "cardb", "border", "areab", "sep"):
            t[k] = _mix(t[k], imgc[0], 0.08 if dark else 0.10)
    acc = cfg.get("accent", "blue")
    if acc == "image":
        src = imgc[0] if imgc else "#3b82f6"
    elif acc.startswith("#"):
        src = acc
    else:
        src = dict((k, c) for k, _, c in ACCENTS).get(acc, "#3b82f6")
    a = readable_accent(src, theme)
    t.update(accent=a, accenth=_mix(a, "#ffffff", 0.18 if dark else 0.12),
             soft=_mix(t["card"], a, 0.24 if dark else 0.18),
             softt=_mix(a, "#ffffff", 0.5) if dark else _mix(a, "#000000", 0.35),
             sel=_mix(t["card"], a, 0.32 if dark else 0.26))
    # 文字对比度兜底
    if contrast(t["softt"], t["soft"]) < 4.5:
        t["softt"] = "#ffffff" if dark else "#111111"
    al = max(75, min(100, int(cfg.get("card_alpha", 88)))) / 100
    if not cfg.get("bg_image"):
        al = 1.0
    for k in ("card", "nav", "list", "area"):
        c = QColor(t[k])
        t[k + "A"] = f"rgba({c.red()},{c.green()},{c.blue()},{int(al * 255)})"
    return t


QSS_TEMPLATE = """
#frame { background:transparent; border:none; }
#frame[max="true"] { border:none; border-radius:0; }
QWidget { color:@text; font-family:"Microsoft YaHei UI"; font-size:13px; }
QLabel { background:transparent; }
#title { background:@navA; border-bottom:1px solid @cardb; border-top-left-radius:10px; border-top-right-radius:10px; }
#titleText { font-size:13px; font-weight:bold; color:@text; }
#version { font-size:11px; color:@faint; }
#title QPushButton { background:@btn; border:1px solid @btnb; border-radius:6px; min-width:30px; max-width:30px;
                     min-height:26px; max-height:26px; padding:0; color:@muted;
                     font-family:"Segoe Fluent Icons","Segoe MDL2 Assets"; font-size:10px; }
#title QPushButton:hover { background:@btnh; color:@text; border-color:@accent; }
#title QPushButton#close:hover { background:@danger; color:white; border-color:@danger; }
#themeIcon { color:@muted; font-family:"Segoe Fluent Icons","Segoe MDL2 Assets"; font-size:12px; }
#titleSep { background:@sep; min-width:1px; max-width:1px; min-height:16px; max-height:16px; }
#side { background:@navA; border-right:1px solid @cardb; border-bottom-left-radius:10px; }
#sideSep { background:@sep; margin:2px 6px; }
QPushButton#sideBtn { background:transparent; border:1px solid transparent; border-radius:8px; padding:0; text-align:left; }
QPushButton#sideBtn:hover { background:@btnh; border-color:@btnb; }
QPushButton#sideBtn:checked { background:@soft; border-color:@accent; }
#card { background:@cardA; border:1px solid @cardb; border-radius:12px; }
#cardTitle { font-size:14px; font-weight:bold; color:@text; }
#pageTitle { font-size:18px; font-weight:bold; color:@text; }
#hint { color:@faint; font-size:12px; }
#muted { color:@muted; }
#pill { background:@soft; color:@softt; border-radius:10px; padding:3px 10px; font-size:12px; }
#stat { background:@areaA; border:1px solid transparent; border-radius:10px; }
#statNum { font-size:16px; font-weight:bold; color:@text; }
#searchBox { background:@inp; border:1px solid @btnb; border-radius:10px; }
#searchBox[focus="true"] { border-color:@accent; }
#searchIcon { color:@faint; font-family:"Segoe Fluent Icons","Segoe MDL2 Assets"; font-size:13px; }
QLineEdit#search { background:transparent; border:none; padding:6px 2px; font-size:14px; min-width:0; }
QPushButton { background:@btn; border:1px solid @btnb; border-radius:8px; padding:6px 14px; color:@text; }
QPushButton:hover { background:@btnh; border-color:@accent; }
QPushButton:pressed { background:@tbp; }
QPushButton:disabled { color:@faint; border-color:@cardb; }
QPushButton#primary { background:@accent; border-color:@accent; color:white; font-weight:bold; }
QPushButton#primary:hover { background:@accenth; border-color:@accenth; }
QPushButton#primary:disabled { background:@btn; color:@faint; border-color:@btnb; }
QPushButton#danger:hover { background:@danger; border-color:@danger; color:white; }
QPushButton::menu-indicator { width:0; }
QProgressBar { border:none; background:@btnb; max-height:6px; min-height:6px; border-radius:3px; }
QProgressBar::chunk { background:@accent; border-radius:3px; }
QTreeWidget { background:@listA; border:1px solid @cardb; border-radius:10px; outline:none; font-size:13px; padding:2px; }
QTreeWidget::item { border:none; padding:5px 0; }
QTreeWidget::item:hover { background:@btnh; }
QTreeWidget::item:selected { background:@sel; color:@text; }
QTreeWidget::branch { background:transparent; image:none; border-image:none; }
QTreeWidget::branch:selected { background:@sel; }
QTreeWidget::branch:hover { background:@btnh; }
QHeaderView { background:transparent; border:none; }
QHeaderView::section { background:@area; color:@muted; border:none; padding:6px 8px; font-size:12px; }
QHeaderView::section:first { border-top-left-radius:8px; }
QHeaderView::section:last { border-top-right-radius:8px; }
QScrollBar:vertical { background:transparent; width:8px; margin:4px 2px 4px 0; }
QScrollBar::handle:vertical { background:@btnb; border-radius:4px; min-height:24px; }
QScrollBar:horizontal { background:transparent; height:8px; margin:0 4px 2px 4px; }
QScrollBar::handle:horizontal { background:@btnb; border-radius:4px; min-width:24px; }
QScrollBar::add-line, QScrollBar::sub-line { height:0; width:0; }
QScrollBar::add-page, QScrollBar::sub-page { background:transparent; }
QMenu { background:@card; color:@text; border:1px solid @cardb; border-radius:8px; padding:4px; }
QMenu::item { padding:6px 22px; border-radius:6px; } QMenu::item:selected { background:@accent; color:white; }
QMenu::item:disabled { color:@faint; }
QMenu::separator { height:1px; background:@sep; margin:4px 8px; }
QToolTip { background:@card; color:@text; border:1px solid @cardb; border-radius:6px; padding:4px 6px; }
QCheckBox { color:@text; spacing:8px; }
QCheckBox::indicator { width:16px; height:16px; border:1px solid @btnb; background:@inp; border-radius:4px; }
QCheckBox::indicator:hover { border-color:@accent; }
QCheckBox::indicator:checked { background:@accent; border-color:@accent; image:url(@check); }
QSpinBox, QDoubleSpinBox, QComboBox, QLineEdit { background:@inp; border:1px solid @btnb; border-radius:8px; padding:4px 8px;
                                 min-width:80px; min-height:20px; color:@text; }
QSpinBox:hover, QDoubleSpinBox:hover, QComboBox:hover, QLineEdit:hover,
QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus, QLineEdit:focus { border-color:@accent; }
QSpinBox:disabled, QDoubleSpinBox:disabled { color:@faint; background:@area; }
QSpinBox, QDoubleSpinBox { padding-right:24px; }
QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button, QDoubleSpinBox::down-button
    { subcontrol-origin:border; width:22px; border:none; background:transparent; }
QSpinBox::up-button, QDoubleSpinBox::up-button { subcontrol-position:top right; margin:3px 3px 0 0; }
QSpinBox::down-button, QDoubleSpinBox::down-button { subcontrol-position:bottom right; margin:0 3px 3px 0; }
QSpinBox::up-button:hover, QSpinBox::down-button:hover, QDoubleSpinBox::up-button:hover, QDoubleSpinBox::down-button:hover { background:@btnh; border-radius:5px; }
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow { image:url(@arrow_up); width:8px; height:8px; }
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow { image:url(@arrow_down); width:8px; height:8px; }
QComboBox { padding-right:26px; }
QComboBox::drop-down { subcontrol-origin:padding; subcontrol-position:center right; width:24px; border:none; }
QComboBox::down-arrow { image:url(@arrow_down); width:10px; height:10px; }
QComboBox QAbstractItemView { background:@card; border:1px solid @cardb; selection-background-color:@accent;
                              selection-color:white; outline:none; padding:4px; }
QScrollArea { background:transparent; border:none; }
QScrollArea > QWidget > QWidget { background:transparent; }
#pageBody { background:transparent; }
#pageSep { background:@sep; }
QTextBrowser { background:@listA; border:1px solid @cardb; border-radius:8px; font-family:Consolas,"Microsoft YaHei UI"; font-size:12px; }
#dialog { background:@card; border:1px solid @cardb; border-radius:12px; }
QSlider::groove:horizontal { height:6px; background:@btnb; border-radius:3px; }
QSlider::sub-page:horizontal { background:@accent; border-radius:3px; }
QSlider::handle:horizontal { background:white; border:2px solid @accent; width:14px; height:14px; margin:-6px 0; border-radius:9px; }
QSlider { min-height:22px; }
QPushButton#choice { padding:10px 18px; min-width:120px; }
QPushButton#choice:checked { background:@soft; border:2px solid @accent; color:@softt; font-weight:bold; }
#preview { background:@area; border:1px dashed @btnb; border-radius:10px; color:@faint; }
#filterLbl { color:@muted; font-size:12px; }
QPushButton#sortDir { min-width:30px; max-width:30px; padding:5px 0; font-family:"Segoe Fluent Icons","Segoe MDL2 Assets"; font-size:12px; }#toast { background:@soft; color:@softt; border:1px solid @accent; border-radius:8px; padding:6px 14px; }
"""


def _svgs(theme):
    t = THEMES[theme]
    d = os.path.join(os.environ.get("TEMP", CFG_DIR), "DownloadButler_ui")
    os.makedirs(d, exist_ok=True)
    out = {}
    for name, pts, col in (("arrow_down", "2,4.5 6,8.5 10,4.5", t["muted"]), ("arrow_up", "2,7.5 6,3.5 10,7.5", t["muted"]),
                           ("check", "2.5,6.2 5,8.6 9.5,3.6", "#ffffff")):
        p = os.path.join(d, f"{name}_{theme}.svg")
        with open(p, "w", encoding="utf-8") as f:
            f.write(f'<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 12 12">'
                    f'<polyline points="{pts}" fill="none" stroke="{col}" stroke-width="1.6" stroke-linecap="round" '
                    f'stroke-linejoin="round"/></svg>')
        out[name] = p.replace("\\", "/")
    return out


def build_qss(cfg):
    global THEME
    THEME = cfg.get("theme", "dark")
    THEMES[THEME] = compose_theme(cfg)
    t = dict(THEMES[THEME])
    t.update(_svgs(THEME))
    s = QSS_TEMPLATE
    for k in sorted(t, key=len, reverse=True):
        s = s.replace("@" + k, t[k])
    return s


def icon_font(px):
    f = QFont("Segoe Fluent Icons")
    f.setFamilies(["Segoe Fluent Icons", "Segoe MDL2 Assets"])
    f.setPixelSize(px)
    return f


def make_app_icon():
    for name in ("icon.ico", "icon.png"):
        p = os.path.join(ASSETS, name)
        if os.path.exists(p):
            return QIcon(p)
    pm = QPixmap(64, 64)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    path = QPainterPath()
    path.addRoundedRect(QRectF(2, 2, 60, 60), 14, 14)
    p.fillPath(path, QColor("#3b82f6"))
    pen = QPen(QColor("white"), 6, cap=Qt.PenCapStyle.RoundCap, join=Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.drawLine(32, 14, 32, 38)
    p.drawPolyline([QPoint(20, 28), QPoint(32, 40), QPoint(44, 28)])
    p.drawLine(18, 50, 46, 50)
    p.end()
    return QIcon(pm)


# ---------------- 系统 ----------------
def downloads_dir():
    try:
        class GUID(ctypes.Structure):
            _fields_ = [("a", ctypes.c_ulong), ("b", ctypes.c_ushort), ("c", ctypes.c_ushort), ("d", ctypes.c_ubyte * 8)]
        g = GUID(0x374DE290, 0x123F, 0x4565, (ctypes.c_ubyte * 8)(0x91, 0x64, 0x39, 0xC4, 0x92, 0x5E, 0x46, 0x7B))
        p = ctypes.c_wchar_p()
        if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(g), 0, None, ctypes.byref(p)) == 0:
            s = p.value
            ctypes.windll.ole32.CoTaskMemFree(p)
            return s
    except Exception:
        pass
    return os.path.join(os.path.expanduser("~"), "Downloads")


ROOT = downloads_dir()


class SHFILEOPSTRUCTW(ctypes.Structure):
    _fields_ = [("hwnd", wintypes.HWND), ("wFunc", wintypes.UINT), ("pFrom", ctypes.c_void_p), ("pTo", ctypes.c_void_p),
                ("fFlags", ctypes.c_ushort), ("fAnyOperationsAborted", wintypes.BOOL), ("hNameMappings", ctypes.c_void_p),
                ("lpszProgressTitle", wintypes.LPCWSTR)]


def recycle(paths):
    """移到回收站（可还原）。"""
    if not paths:
        return
    buf = ctypes.create_unicode_buffer("\0".join(os.path.abspath(p) for p in paths) + "\0\0")
    op = SHFILEOPSTRUCTW()
    op.wFunc = 3                              # FO_DELETE
    op.pFrom = ctypes.cast(buf, ctypes.c_void_p)
    op.fFlags = 0x0040 | 0x0010 | 0x0400 | 0x0004   # ALLOWUNDO | NOCONFIRMATION | NOERRORUI | SILENT
    r = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    if r:
        raise OSError(f"删除失败（代码 {r}）")


def is_hidden(path):
    try:
        return bool(os.stat(path).st_file_attributes & 2)
    except OSError:
        return True


def human(n):
    n = float(n)
    for u in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {u}" if u == "B" else f"{n:.1f} {u}" if n < 10 else f"{n:.0f} {u}"
        n /= 1024
    return f"{n:.1f} TB"


def load_cfg():
    c = dict(DEFAULTS)
    try:
        with open(CFG_PATH, encoding="utf-8") as f:
            c.update(json.load(f))
    except Exception:
        pass
    return c


def save_cfg(c):
    os.makedirs(CFG_DIR, exist_ok=True)
    with open(CFG_PATH, "w", encoding="utf-8") as f:
        json.dump(c, f, ensure_ascii=False, indent=1)


def autostart_enabled():
    """以注册表为准（安装程序也可能设置开机启动）。"""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run") as k:
            winreg.QueryValueEx(k, APP)
            return True
    except OSError:
        return False


def set_autostart(on):
    exe = sys.executable
    cmd = f'"{exe}" --min' if getattr(sys, "frozen", False) else \
        f'"{exe.replace("python.exe", "pythonw.exe")}" "{os.path.abspath(__file__)}" --min'
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0,
                            winreg.KEY_SET_VALUE) as k:
            if on:
                winreg.SetValueEx(k, APP, 0, winreg.REG_SZ, cmd)
            else:
                try:
                    winreg.DeleteValue(k, APP)
                except FileNotFoundError:
                    pass
    except OSError:
        pass


# ---------------- 整理 / 清理 ----------------
LOGS = []


def log(msg):
    LOGS.insert(0, datetime.now().strftime("%m-%d %H:%M:%S") + "  " + msg)
    del LOGS[300:]


def category_of(ext):
    for name, _, exts in RULES:
        if ext in exts.split():
            return name
    return "其他文件"


def free_path(d, name):
    dest = os.path.join(d, name)
    base, ext = os.path.splitext(name)
    i = 1
    while os.path.exists(dest):
        dest = os.path.join(d, f"{base} ({i}){ext}")
        i += 1
    return dest


def organize():
    """整理下载根目录里的新文件。返回 (已移动的文件名, 暂时无法整理的文件数)；
    后者是仍在下载 / 被占用 / 刚写入的文件，需要稍后重试。"""
    moved, pending = [], 0
    try:
        entries = list(os.scandir(ROOT))
    except OSError:
        return moved, pending
    now = time.time()
    for e in entries:
        try:
            if not e.is_file():
                continue
            st = e.stat()   # Windows 上 scandir 已带回属性，不会再次访问磁盘
            if st.st_file_attributes & 2:
                continue
            ext = os.path.splitext(e.name)[1].lower()
            if ext in SKIP_EXT or now - st.st_mtime < 3:
                pending += 1
                continue
            cat = category_of(ext)
            d = os.path.join(ROOT, cat, datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m"))
            os.makedirs(d, exist_ok=True)
            os.rename(e.path, free_path(d, e.name))   # 文件仍被占用（下载中）时会失败，稍后重试
            log(f"整理：{e.name} → {cat}")
            moved.append(e.name)
        except OSError:
            pending += 1
    return moved, pending


def scan():
    """列出所有文件，同时返回需要监视的文件夹。用 scandir 的缓存属性，避免逐个 stat。"""
    items, dirs = [], [ROOT]

    def walk(d, cat):
        dirs.append(d)
        try:
            it = os.scandir(d)
        except OSError:
            return
        with it:
            for e in it:
                try:
                    if e.is_dir(follow_symlinks=False):
                        walk(e.path, cat)
                    elif e.is_file():
                        st = e.stat()
                        items.append(dict(name=e.name, path=e.path, cat=cat,
                                          ext=os.path.splitext(e.name)[1].lower(),
                                          size=st.st_size, mtime=st.st_mtime))
                except OSError:
                    pass

    for c in CATS:
        p = os.path.join(ROOT, c)
        if os.path.isdir(p):
            walk(p, c)
    try:
        with os.scandir(ROOT) as it:
            for e in it:
                if e.is_file():
                    st = e.stat()
                    if not st.st_file_attributes & 2:
                        items.append(dict(name=e.name, path=e.path, cat="未整理",
                                          ext=os.path.splitext(e.name)[1].lower(),
                                          size=st.st_size, mtime=st.st_mtime))
    except OSError:
        pass
    return items, dirs


def remove_empty_dirs():
    for c in CATS:
        for dp, dn, fn in sorted(os.walk(os.path.join(ROOT, c)), key=lambda x: -len(x[0])):
            if dp != os.path.join(ROOT, c):
                try:
                    if not os.listdir(dp):
                        os.rmdir(dp)
                except OSError:
                    pass


def move_to(path, dest):
    name = os.path.basename(path)
    if dest in CATS:
        d = os.path.join(ROOT, dest, datetime.fromtimestamp(os.stat(path).st_mtime).strftime("%Y-%m"))
    else:
        d = dest
    os.makedirs(d, exist_ok=True)
    shutil.move(path, free_path(d, name))
    log(f"移动：{name} → {dest}")


def cleanup(cfg):
    n, freed = 0, 0

    def eligible():
        return sorted((x for x in scan()[0] if x["cat"] != "未整理" and x["cat"] not in cfg["protect"]),
                      key=lambda x: x["mtime"])
    if cfg["clean_on"]:
        cutoff = time.time() - cfg["clean_days"] * 86400
        old = [x for x in eligible() if x["mtime"] < cutoff]
        for x in old:
            try:
                recycle([x["path"]]); n += 1; freed += x["size"]
            except OSError:
                pass
    if cfg["cap_on"]:
        total = sum(x["size"] for x in scan()[0])
        cap = cfg["cap_gb"] * 1024 ** 3
        for x in eligible():
            if total <= cap:
                break
            try:
                recycle([x["path"]]); n += 1; freed += x["size"]; total -= x["size"]
            except OSError:
                pass
    remove_empty_dirs()
    log(f"清理：{n} 个文件进回收站，释放 {human(freed)}")
    return n, freed


# ---------------- 控件 ----------------
class Switch(QCheckBox):
    """滑块开关（同格式转换器）。"""
    def __init__(self, small=False):
        super().__init__()
        self.setFixedSize(*((34, 18) if small else (40, 22)))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._x = 0.0
        self.anim = QPropertyAnimation(self, b"knob", self)
        self.anim.setDuration(140)
        self.toggled.connect(self._go)

    def _go(self, on):
        self.anim.stop()
        self.anim.setStartValue(self._x)
        self.anim.setEndValue(1.0 if on else 0.0)
        self.anim.start()

    def get_knob(self):
        return self._x

    def set_knob(self, v):
        self._x = v
        self.update()

    knob = pyqtProperty(float, get_knob, set_knob)

    def setChecked(self, on):
        super().setChecked(on)
        self.anim.stop()
        self._x = 1.0 if on else 0.0
        self.update()

    def hitButton(self, pos):
        return self.rect().contains(pos)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        off, on, t = QColor(C("knob_off")), QColor(C("accent")), self._x
        p.setBrush(QColor(int(off.red() + (on.red() - off.red()) * t), int(off.green() + (on.green() - off.green()) * t),
                          int(off.blue() + (on.blue() - off.blue()) * t)))
        h = self.height()
        p.drawRoundedRect(self.rect(), h / 2, h / 2)
        p.setBrush(QColor("white"))
        d = h - 6
        p.drawEllipse(int(3 + t * (self.width() - d - 6)), 3, d, d)


class SideButton(QPushButton):
    """左侧导航项：Fluent 图标 + 文字 + 右侧数量徽标；折叠时只画图标。"""
    def __init__(self, glyph, text):
        super().__init__(objectName="sideBtn")
        self.glyph, self.text_, self.expanded, self.count = glyph, text, True, None
        self.setFixedHeight(38)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def paintEvent(self, e):
        super().paintEvent(e)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        on = self.isChecked()
        col = QColor(C("softt") if on else (C("text") if self.underMouse() else C("muted")))
        p.setFont(icon_font(16))
        p.setPen(col)
        p.drawText(QRectF(0, 0, 38, self.height()), Qt.AlignmentFlag.AlignCenter, self.glyph)
        if not self.expanded:
            if not self.text_ in ("收起菜单",):
                self.setToolTip(self.text_ + (f"（{self.count}）" if self.count is not None else ""))
            return
        self.setToolTip("")
        f = self.font()
        f.setPixelSize(13)
        f.setBold(on)
        p.setFont(f)
        right = 8
        if self.count is not None:
            fb = self.font()
            fb.setPixelSize(11)
            fb.setBold(True)
            p.setFont(fb)
            txt = str(self.count)
            w = max(22, p.fontMetrics().horizontalAdvance(txt) + 12)
            r = QRectF(self.width() - w - 8, (self.height() - 18) / 2, w, 18)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(C("accent") if on else C("area")))
            p.drawRoundedRect(r, 9, 9)
            p.setPen(QColor("white" if on else C("muted")))
            p.drawText(r, Qt.AlignmentFlag.AlignCenter, txt)
            right = w + 14
            p.setFont(f)
        p.setPen(col)
        p.drawText(QRectF(40, 0, self.width() - 40 - right, self.height()),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self.text_)


class ThumbLoader(QThread):
    """后台生成图片缩略图，并缓存到磁盘（按路径 + 修改时间），下次打开直接读取小图。"""
    ready = pyqtSignal(str, QImage)
    SIZE = 56   # 28px 图标的 2 倍，高分屏也清晰

    def __init__(self, parent):
        super().__init__(parent)
        self.cache_dir = os.path.join(os.environ.get("LOCALAPPDATA", CFG_DIR), "DownloadButler", "thumbs")
        os.makedirs(self.cache_dir, exist_ok=True)
        self.q, self.lock, self.cv = [], threading.Lock(), threading.Condition()

    def request(self, key, path):
        with self.cv:
            self.q.append((key, path))
            self.cv.notify()

    def clear(self):
        with self.cv:
            self.q.clear()

    def run(self):
        while True:
            with self.cv:
                while not self.q:
                    self.cv.wait()
                key, path = self.q.pop(0)
            if key is None:
                return
            cache = os.path.join(self.cache_dir, hashlib.md5(key.encode("utf-8")).hexdigest() + ".png")
            img = QImage(cache) if os.path.exists(cache) else QImage()
            if img.isNull():
                r = QImageReader(path)
                r.setAutoTransform(True)
                sz = r.size()
                if sz.isValid() and sz.width() > 0 and sz.height() > 0:
                    sz.scale(self.SIZE, self.SIZE, Qt.AspectRatioMode.KeepAspectRatio)
                    r.setScaledSize(sz)
                img = r.read()
                if img.isNull():
                    continue
                if max(img.width(), img.height()) > self.SIZE:
                    img = img.scaled(self.SIZE, self.SIZE, Qt.AspectRatioMode.KeepAspectRatio,
                                     Qt.TransformationMode.SmoothTransformation)
                img.save(cache, "PNG")
            self.ready.emit(key, img)

    def stop(self):
        with self.cv:
            self.q.insert(0, (None, None))
            self.cv.notify()
        self.wait(1500)


class BgFrame(QFrame):
    """窗口底板：主题底色 + 可选背景图（铺满裁切）+ 一层主题色蒙版保证文字清晰。"""
    def __init__(self):
        super().__init__(objectName="frame")
        self.src, self.cache, self.vis, self.maxed = None, None, 0.35, False

    def set_image(self, path, vis):
        self.src = QPixmap(path) if path and os.path.exists(path) else None
        if self.src is not None and self.src.isNull():
            self.src = None
        self.vis, self.cache = vis, None
        self.update()

    def resizeEvent(self, e):
        self.cache = None
        super().resizeEvent(e)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        rad = 0 if self.maxed else 10
        path = QPainterPath()
        path.addRoundedRect(r, rad, rad)
        p.setClipPath(path)
        base = QColor(C("frame"))
        p.fillRect(self.rect(), base)
        if self.src is not None:
            if self.cache is None or self.cache.size() != self.size():
                pm = self.src.scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                     Qt.TransformationMode.SmoothTransformation)
                x, y = (pm.width() - self.width()) // 2, (pm.height() - self.height()) // 2
                self.cache = pm.copy(x, y, self.width(), self.height())
            p.drawPixmap(0, 0, self.cache)
            base.setAlphaF(1 - self.vis)
            p.fillRect(self.rect(), base)
        p.setClipping(False)
        if not self.maxed:
            p.setPen(QPen(QColor(C("border")), 1))
            p.drawPath(path)


class TitleBar(QWidget):
    def __init__(self, win):
        super().__init__(objectName="title")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.win = win
        self.setFixedHeight(40)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 0, 8, 0)
        lay.setSpacing(4)
        ic = QLabel()
        ic.setPixmap(win.app_icon.pixmap(18, 18))
        lay.addWidget(ic)
        lay.addSpacing(6)
        lay.addWidget(QLabel(APP, objectName="titleText"))
        lay.addSpacing(6)
        lay.addWidget(QLabel("v" + VERSION, objectName="version"))
        lay.addStretch()
        moon = QLabel("", objectName="themeIcon")
        moon.setToolTip("深色模式")
        lay.addWidget(moon)
        lay.addSpacing(4)
        self.theme_switch = Switch(small=True)
        self.theme_switch.setChecked(THEME == "dark")
        self.theme_switch.setToolTip("深色模式")
        self.theme_switch.toggled.connect(lambda on: win.set_theme("dark" if on else "light"))
        lay.addWidget(self.theme_switch, 0, Qt.AlignmentFlag.AlignVCenter)
        lay.addSpacing(8)
        sep = QFrame(objectName="titleSep")
        lay.addWidget(sep, 0, Qt.AlignmentFlag.AlignVCenter)
        lay.addSpacing(6)
        self.btn_min = QPushButton("")
        self.btn_max = QPushButton("")
        self.btn_close = QPushButton("", objectName="close")
        self.btn_min.clicked.connect(win.showMinimized)
        self.btn_max.clicked.connect(win.toggle_max)
        self.btn_close.clicked.connect(win.close)
        for b in (self.btn_min, self.btn_max, self.btn_close):
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            lay.addWidget(b)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.win.windowHandle().startSystemMove()

    def mouseDoubleClickEvent(self, e):
        self.win.toggle_max()


class FileTree(QTreeWidget):
    """文件列表：按日期分组，可拖出到其他程序，回车打开、Delete 删除、F2 重命名。"""
    def __init__(self, main):
        super().__init__()
        self.main = main
        self.setColumnCount(4)
        self.setHeaderLabels(["名称", "分类", "大小", "修改时间"])
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setIconSize(QSize(28, 28))
        self.setRootIsDecorated(False)
        self.setIndentation(0)
        self.setUniformRowHeights(True)   # 行高一致，滚动和插入都更快
        self.setAnimated(True)
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        h = self.header()
        h.setStretchLastSection(False)
        h.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for i, w in ((1, 90), (2, 90), (3, 140)):
            h.setSectionResizeMode(i, QHeaderView.ResizeMode.Fixed)
            self.setColumnWidth(i, w)
        h.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

    def mimeData(self, items):
        md = QMimeData()
        md.setUrls([QUrl.fromLocalFile(i.data(0, Qt.ItemDataRole.UserRole)) for i in items
                    if i.data(0, Qt.ItemDataRole.UserRole)])
        return md

    def keyPressEvent(self, e):
        k = e.key()
        if k in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.main.open_selected()
        elif k == Qt.Key.Key_Delete:
            self.main.delete_selected()
        elif k == Qt.Key.Key_F2:
            self.main.rename_selected()
        else:
            super().keyPressEvent(e)


class Dialog(QDialog):
    """应用内样式的确认 / 输入框。"""
    def __init__(self, parent, title, msg, ok="确定", danger=False, edit=None, extra=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        card = QFrame(objectName="dialog")
        outer.addWidget(card)
        v = QVBoxLayout(card)
        v.setContentsMargins(22, 18, 22, 16)
        v.setSpacing(10)
        v.addWidget(QLabel(title, objectName="cardTitle"))
        lbl = QLabel(msg, objectName="muted")
        lbl.setWordWrap(True)
        v.addWidget(lbl)
        self.edit = None
        if edit is not None:
            self.edit = QLineEdit(edit)
            base = os.path.splitext(edit)[0]
            QTimer.singleShot(0, lambda: (self.edit.setFocus(), self.edit.setSelection(0, len(base))))
            v.addWidget(self.edit)
        if extra:
            v.addWidget(extra)
        h = QHBoxLayout()
        h.addStretch()
        b0 = QPushButton("取消")
        b0.clicked.connect(self.reject)
        b1 = QPushButton(ok, objectName="danger" if danger else "primary")
        b1.setDefault(True)
        b1.clicked.connect(self.accept)
        h.addWidget(b0)
        h.addWidget(b1)
        v.addSpacing(4)
        v.addLayout(h)
        self.setMinimumWidth(420)

    def value(self):
        return self.edit.text().strip() if self.edit else None


# ---------------- 主窗口 ----------------
class Main(QWidget):
    def __init__(self, start_hidden=False):
        super().__init__()
        self.cfg = load_cfg()
        self.cfg["autostart"] = autostart_enabled()
        QApplication.instance().setStyleSheet(build_qss(self.cfg))
        self.app_icon = make_app_icon()
        self.setWindowTitle(APP)
        self.setWindowIcon(self.app_icon)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMouseTracking(True)
        self.resize(1180, 760)
        self.setMinimumSize(900, 600)
        QApplication.instance().installEventFilter(self)

        self.items, self.sig, self.cur = [], None, "全部文件"
        self.icon_cache, self.provider = {}, QFileIconProvider()
        self.thumb_items = {}
        self.thumbs = ThumbLoader(self)
        self.thumbs.ready.connect(self.on_thumb)
        self.thumbs.start(QThread.Priority.LowPriority)
        self._edge_shape = None
        self.told_tray = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(BORDER, BORDER, BORDER, BORDER)
        self.frame = BgFrame()
        outer.addWidget(self.frame)
        fl = QVBoxLayout(self.frame)
        fl.setContentsMargins(1, 1, 1, 1)
        fl.setSpacing(0)
        self.title = TitleBar(self)
        fl.addWidget(self.title)
        mid = QHBoxLayout()
        mid.setContentsMargins(0, 0, 0, 0)
        mid.setSpacing(0)
        fl.addLayout(mid, 1)

        # ---- 左侧可折叠导航
        self.side = QFrame(objectName="side")
        sl = QVBoxLayout(self.side)
        sl.setContentsMargins(6, 8, 6, 8)
        sl.setSpacing(3)
        self.side_btns, self.cat_btns = [], {}

        def item(glyph, text, fn, checkable=False):
            b = SideButton(glyph, text)
            b.setCheckable(checkable)
            b.clicked.connect(fn)
            sl.addWidget(b)
            self.side_btns.append(b)
            return b
        self.btn_fold = item("", "收起菜单", self.toggle_side)
        s = QFrame(objectName="sideSep"); s.setFixedHeight(1); sl.addWidget(s)
        for c in ["全部文件"] + CATS + ["未整理"]:
            self.cat_btns[c] = item(GLYPH[c], c, lambda _=None, c=c: self.select_cat(c), True)
        s = QFrame(objectName="sideSep"); s.setFixedHeight(1); sl.addWidget(s)
        sl.addStretch()
        item("", "立即整理", lambda: self.do_organize(True))
        item("", "立即清理", self.do_cleanup)
        item("", "打开下载文件夹", lambda: os.startfile(ROOT))
        self.btn_appear = item("", "外观", self.open_appearance, True)
        self.btn_settings = item("", "设置", self.open_settings, True)
        mid.addWidget(self.side)

        self.pages = QStackedWidget()
        mid.addWidget(self.pages, 1)
        self.pages.addWidget(self.build_home())
        self.pages.addWidget(self.build_settings())
        self.pages.addWidget(self.build_appearance())
        self.apply_appearance(save=False, initial=True)
        self.set_side(self.cfg.get("side_open", True))
        self.select_cat("全部文件")

        # 托盘
        self.tray = QSystemTrayIcon(self.app_icon, self)
        self.tray.setToolTip(APP)
        m = QMenu()
        m.addAction("打开下载管家", self.show_main)
        m.addAction("立即整理", lambda: self.do_organize(True))
        m.addSeparator()
        m.addAction("退出", self.quit)
        self.tray.setContextMenu(m)
        self.tray.activated.connect(lambda r: self.show_main() if r in (
            QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick) else None)
        self.tray.show()

        for w in self.findChildren((QPushButton, QComboBox, QCheckBox, QSlider)):
            w.setCursor(Qt.CursorShape.PointingHandCursor)
        QShortcut(QKeySequence("Ctrl+F"), self, activated=lambda: (self.search.setFocus(), self.search.selectAll()))
        # 事件驱动：文件夹有变化时系统通知，不再定时扫描
        self.dirty = True
        self.watcher = QFileSystemWatcher(self)
        self.watcher.directoryChanged.connect(self.on_fs_change)
        self.fs_timer = QTimer(self, singleShot=True, interval=350, timeout=self.on_fs_settled)   # 合并连续变化
        self.retry_timer = QTimer(self, singleShot=True, interval=3000, timeout=self.on_fs_settled)  # 下载中的文件稍后重试
        self.safety_timer = QTimer(self, interval=5 * 60 * 1000, timeout=self.on_fs_settled)   # 兜底：防止漏掉通知
        self.safety_timer.start()
        self.clean_timer = QTimer(self, interval=30 * 60 * 1000, timeout=self.auto_cleanup)
        self.clean_timer.start()
        if self.cfg.get("autostart"):
            set_autostart(True)   # 程序位置变化（重新安装）后修正开机启动路径
        log("下载管家已启动，管理：" + ROOT)
        if start_hidden:
            # 开机后台启动：只整理和监视下载根目录，列表与缩略图等到第一次打开窗口再加载
            self.on_fs_settled()
            QTimer.singleShot(15000, self.warm_up)
        else:
            self.tick()
            self.show()

    # ---------- 主页 ----------
    def build_home(self):
        body = QWidget(objectName="pageBody")
        root = QVBoxLayout(body)
        root.setContentsMargins(14, 8, 14, 14)
        root.setSpacing(10)

        head = QHBoxLayout()
        head.setSpacing(12)
        tv = QVBoxLayout()
        tv.setSpacing(0)
        self.page_title = QLabel(objectName="pageTitle")
        self.page_sub = QLabel(objectName="hint")
        tv.addWidget(self.page_title)
        tv.addWidget(self.page_sub)
        head.addLayout(tv)
        head.addStretch()
        sb = QFrame(objectName="searchBox")
        sh = QHBoxLayout(sb)
        sh.setContentsMargins(10, 0, 6, 0)
        sh.setSpacing(6)
        sh.addWidget(QLabel("", objectName="searchIcon"))
        self.search = QLineEdit(objectName="search", placeholderText="搜索文件名（Ctrl+F，回车打开第一个）")
        self.search.setClearButtonEnabled(True)
        self.search_timer = QTimer(self, singleShot=True, interval=120, timeout=self.fill)   # 输入停顿后再筛选
        self.search.textChanged.connect(self.search_timer.start)
        self.search.returnPressed.connect(self.open_first)
        sh.addWidget(self.search)
        sb.setFixedWidth(380)
        self.search_box = sb
        self.search.installEventFilter(self)
        head.addWidget(sb)
        root.addLayout(head)

        # 状态卡片
        stats = QHBoxLayout()
        stats.setSpacing(10)

        def stat(title):
            f = QFrame(objectName="stat")
            v = QVBoxLayout(f)
            v.setContentsMargins(14, 10, 14, 10)
            v.setSpacing(2)
            v.addWidget(QLabel(title, objectName="hint"))
            n = QLabel(objectName="statNum")
            v.addWidget(n)
            stats.addWidget(f, 1)
            return f, v, n
        _, _, self.st_count = stat("文件总数")
        _, _, self.st_size = stat("占用空间")
        f, v, self.st_disk = stat("磁盘剩余")
        self.disk_bar = QProgressBar(textVisible=False)
        self.disk_bar.setRange(0, 1000)
        v.addWidget(self.disk_bar)
        f, v, self.st_auto = stat("自动整理")
        row = QHBoxLayout()
        self.auto_switch = Switch()
        self.auto_switch.setChecked(self.cfg["auto"])
        self.auto_switch.toggled.connect(lambda on: self.set_cfg("auto", on))
        v.removeWidget(self.st_auto)
        row.addWidget(self.st_auto)
        row.addStretch()
        row.addWidget(self.auto_switch)
        v.addLayout(row)
        root.addLayout(stats)

        # 文件列表卡片
        card = QFrame(objectName="card")
        cv = QVBoxLayout(card)
        cv.setContentsMargins(12, 12, 12, 12)
        cv.setSpacing(10)
        # 排序 / 筛选栏
        fb = QHBoxLayout()
        fb.setSpacing(8)
        fb.addWidget(QLabel("排序", objectName="filterLbl"))
        self.sort_box = QComboBox()
        for text, key in SORTS:
            self.sort_box.addItem(text, key)
        self.sort_box.setCurrentIndex([k for _, k in SORTS].index(self.cfg.get("sort_key", "time")))
        self.sort_box.currentIndexChanged.connect(lambda i: self.set_sort(SORTS[i][1], keep_dir=False))
        fb.addWidget(self.sort_box)
        self.sort_dir = QPushButton(objectName="sortDir")
        self.sort_dir.clicked.connect(lambda: self.set_sort(self.cfg["sort_key"], toggle=True))
        fb.addWidget(self.sort_dir)
        fb.addSpacing(10)
        fb.addWidget(QLabel("时间", objectName="filterLbl"))
        self.time_box = QComboBox()
        self.time_box.addItems([t for t, _ in TIME_FILTERS])
        self.time_box.currentIndexChanged.connect(self.fill)
        fb.addWidget(self.time_box)
        fb.addWidget(QLabel("大小", objectName="filterLbl"))
        self.size_box = QComboBox()
        self.size_box.addItems([t for t, _ in SIZE_FILTERS])
        self.size_box.currentIndexChanged.connect(self.fill)
        fb.addWidget(self.size_box)
        fb.addStretch()
        self.b_reset = QPushButton("清除筛选")
        self.b_reset.clicked.connect(self.reset_filters)
        fb.addWidget(self.b_reset)
        cv.addLayout(fb)
        self.tree = FileTree(self)
        self.tree.header().setSectionsClickable(True)
        self.tree.header().sectionClicked.connect(lambda col: self.set_sort(COL_KEYS[col], toggle=True))
        self.tree.itemDoubleClicked.connect(lambda it, _: self.open_selected())
        self.tree.itemSelectionChanged.connect(self.update_actions)
        self.tree.customContextMenuRequested.connect(self.context_menu)
        cv.addWidget(self.tree, 1)
        act = QHBoxLayout()
        act.setSpacing(8)
        self.b_open = QPushButton("打开", objectName="primary")
        self.b_open.clicked.connect(self.open_selected)
        self.b_reveal = QPushButton("打开所在位置")
        self.b_reveal.clicked.connect(self.reveal_selected)
        self.b_move = QPushButton("移动到  ▾")
        self.b_move.clicked.connect(lambda: self.move_menu().exec(self.b_move.mapToGlobal(QPoint(0, self.b_move.height() + 4))))
        self.b_rename = QPushButton("重命名")
        self.b_rename.clicked.connect(self.rename_selected)
        self.b_delete = QPushButton("删除", objectName="danger")
        self.b_delete.clicked.connect(self.delete_selected)
        for b in (self.b_open, self.b_reveal, self.b_move, self.b_rename, self.b_delete):
            act.addWidget(b)
        act.addStretch()
        self.sel_hint = QLabel(objectName="hint")
        act.addWidget(self.sel_hint)
        cv.addLayout(act)
        root.addWidget(card, 1)

        self.toast = QLabel(body, objectName="toast")
        self.toast.hide()
        self.toast_timer = QTimer(self, singleShot=True, timeout=self.toast.hide)
        return body

    # ---------- 设置页 ----------
    def build_settings(self):
        page = QWidget(objectName="pageBody")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        head = QHBoxLayout()
        head.setContentsMargins(20, 10, 20, 10)
        head.addWidget(QLabel("设置", objectName="pageTitle"))
        head.addStretch()
        back = QPushButton("←  返回文件列表")
        back.clicked.connect(lambda: self.select_cat(self.cur))
        head.addWidget(back)
        outer.addLayout(head)
        line = QFrame(objectName="pageSep")
        line.setFixedHeight(1)
        outer.addWidget(line)
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        holder = QWidget(objectName="pageBody")
        hh = QHBoxLayout(holder)
        body = QWidget(objectName="pageBody")
        body.setMaximumWidth(760)
        hh.addStretch(1)
        hh.addWidget(body, 30)
        hh.addStretch(1)
        sc.setWidget(holder)
        outer.addWidget(sc, 1)
        v = QVBoxLayout(body)
        v.setContentsMargins(0, 16, 0, 20)
        v.setSpacing(12)

        def card(title, hint=None):
            c = QFrame(objectName="card")
            cl = QVBoxLayout(c)
            cl.setContentsMargins(18, 14, 18, 16)
            cl.setSpacing(10)
            cl.addWidget(QLabel(title, objectName="cardTitle"))
            if hint:
                h = QLabel(hint, objectName="hint")
                h.setWordWrap(True)
                cl.addWidget(h)
            v.addWidget(c)
            return cl

        def row(layout, text, *widgets, sub=None):
            r = QHBoxLayout()
            tv = QVBoxLayout()
            tv.setSpacing(0)
            tv.addWidget(QLabel(text))
            if sub:
                tv.addWidget(QLabel(sub, objectName="hint"))
            r.addLayout(tv)
            r.addStretch()
            for w in widgets:
                r.addWidget(w)
            layout.addLayout(r)

        c = card("自动整理")
        self.s_auto = Switch()
        self.s_auto.setChecked(self.cfg["auto"])
        self.s_auto.toggled.connect(lambda on: self.set_cfg("auto", on))
        row(c, "有新文件下载到“下载”文件夹时自动整理", self.s_auto,
            sub="按类型放进 重要文件 / 安装包 / 压缩包 / 图片 … 文件夹，再按“年-月”分子文件夹；未下载完的文件会跳过")

        c = card("自动清理", "清理的文件进入回收站，可以还原；后台每 30 分钟检查一次。")
        self.s_clean = Switch()
        self.s_clean.setChecked(self.cfg["clean_on"])
        self.s_days = QSpinBox(minimum=1, maximum=3650, suffix=" 天")
        self.s_days.setValue(int(self.cfg["clean_days"]))
        self.s_clean.toggled.connect(lambda on: self.set_cfg("clean_on", on))
        self.s_days.valueChanged.connect(lambda x: self.set_cfg("clean_days", x))
        row(c, "定期清理旧文件", self.s_days, self.s_clean, sub="删除修改时间早于设定天数的文件")
        self.s_cap = Switch()
        self.s_cap.setChecked(self.cfg["cap_on"])
        self.s_gb = QDoubleSpinBox(minimum=0.5, maximum=10000, singleStep=0.5, decimals=1, suffix=" GB")
        self.s_gb.setValue(float(self.cfg["cap_gb"]))
        self.s_cap.toggled.connect(lambda on: self.set_cfg("cap_on", on))
        self.s_gb.valueChanged.connect(lambda x: self.set_cfg("cap_gb", x))
        row(c, "容量阈值清理", self.s_gb, self.s_cap, sub="下载文件总量超过阈值时，从最旧的文件开始清理")
        c.addWidget(QLabel("受保护的分类（清理时不动）：", objectName="hint"))
        g = QGridLayout()
        g.setHorizontalSpacing(18)
        self.protect_boxes = {}
        for i, cat in enumerate(CATS):
            cb = QCheckBox(cat)
            cb.setChecked(cat in self.cfg["protect"])
            cb.toggled.connect(self.save_protect)
            self.protect_boxes[cat] = cb
            g.addWidget(cb, i // 4, i % 4)
        c.addLayout(g)
        b = QPushButton("立即清理", objectName="primary")
        b.clicked.connect(self.do_cleanup)
        hb = QHBoxLayout()
        hb.addStretch()
        hb.addWidget(b)
        c.addLayout(hb)

        c = card("常规")
        s_start = Switch()
        s_start.setChecked(self.cfg["autostart"])
        s_start.toggled.connect(lambda on: (self.set_cfg("autostart", on), set_autostart(on)))
        row(c, "开机自动在后台运行", s_start, sub="启动后只显示托盘图标，照常自动整理")
        cb = QComboBox()
        cb.addItems(["隐藏到系统托盘", "完全退出"])
        cb.setCurrentIndex(0 if self.cfg["close"] == "tray" else 1)
        cb.currentIndexChanged.connect(lambda i: self.set_cfg("close", "tray" if i == 0 else "quit"))
        row(c, "点击 ✕ 关闭窗口时", cb)
        row(c, "下载文件夹位置", QLabel(ROOT, objectName="hint"))

        c = card("最近记录")
        self.log_view = QTextBrowser()
        self.log_view.setMinimumHeight(200)
        c.addWidget(self.log_view)
        v.addStretch()
        return page

    # ---------- 导航 ----------
    def set_side(self, open_):
        self.side_open = open_
        self.side.setFixedWidth(196 if open_ else 52)
        for b in self.side_btns:
            b.expanded = open_
            b.update()
        self.btn_fold.text_ = "收起菜单" if open_ else "展开菜单"
        self.btn_fold.setToolTip("" if open_ else "展开菜单")

    def toggle_side(self):
        self.set_side(not self.side_open)
        self.set_cfg("side_open", self.side_open)

    def select_cat(self, c):
        self.cur = c
        for k, b in self.cat_btns.items():
            b.setChecked(k == c)
        self.btn_settings.setChecked(False)
        self.btn_appear.setChecked(False)
        self.pages.setCurrentIndex(0)
        self.fill()

    def open_settings(self):
        for b in self.cat_btns.values():
            b.setChecked(False)
        self.btn_settings.setChecked(True)
        self.btn_appear.setChecked(False)
        self.log_view.setPlainText("\n".join(LOGS) or "暂无记录")
        self.pages.setCurrentIndex(1)

    def set_cfg(self, k, v):
        self.cfg[k] = v
        save_cfg(self.cfg)
        if k == "auto":
            for s in (self.auto_switch, self.s_auto):
                if s.isChecked() != v:
                    s.blockSignals(True); s.setChecked(v); s.blockSignals(False)
            self.st_auto.setText("已开启" if v else "已关闭")

    def save_protect(self):
        self.set_cfg("protect", [c for c, b in self.protect_boxes.items() if b.isChecked()])

    def set_theme(self, t):
        self.cfg["theme"] = t
        self.apply_appearance()

    def warm_up(self):
        """后台启动 15 秒后预先建好列表和图标，之后从托盘打开窗口几乎是瞬时的。"""
        if not self.isVisible() and self.sig is None:
            self.tick()

    def apply_appearance(self, save=True, initial=False):
        """重新生成配色并强制所有控件重新套用样式（解决部分控件切换主题后不刷新的问题）。"""
        if save:
            save_cfg(self.cfg)
        if not initial:   # 启动时样式表已经设置过，不必再全部重新套用
            app = QApplication.instance()
            app.setStyleSheet(build_qss(self.cfg))
            for w in [self] + self.findChildren(QWidget):
                w.style().unpolish(w)
                w.style().polish(w)
                w.update()
        self.frame.set_image(self.cfg.get("bg_image"), self.cfg.get("bg_vis", 35) / 100)
        self.setWindowOpacity(max(70, min(100, self.cfg.get("win_opacity", 100))) / 100)
        sw = self.title.theme_switch
        if sw.isChecked() != (THEME == "dark"):
            sw.blockSignals(True); sw.setChecked(THEME == "dark"); sw.blockSignals(False)
        if hasattr(self, "ap_dark"):
            self.sync_appearance_ui()
        self.sig = None
        if hasattr(self, "tray"):
            self.tick()

    # ---------- 外观页 ----------
    def open_appearance(self):
        for b in self.cat_btns.values():
            b.setChecked(False)
        self.btn_settings.setChecked(False)
        self.btn_appear.setChecked(True)
        self.sync_appearance_ui()
        self.pages.setCurrentIndex(2)

    def build_appearance(self):
        page = QWidget(objectName="pageBody")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        head = QHBoxLayout()
        head.setContentsMargins(20, 10, 20, 10)
        head.addWidget(QLabel("外观", objectName="pageTitle"))
        head.addStretch()
        reset = QPushButton("恢复默认外观")
        reset.clicked.connect(self.reset_appearance)
        head.addWidget(reset)
        back = QPushButton("←  返回文件列表")
        back.clicked.connect(lambda: self.select_cat(self.cur))
        head.addWidget(back)
        outer.addLayout(head)
        line = QFrame(objectName="pageSep")
        line.setFixedHeight(1)
        outer.addWidget(line)
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        holder = QWidget(objectName="pageBody")
        hh = QHBoxLayout(holder)
        body = QWidget(objectName="pageBody")
        body.setMaximumWidth(760)
        hh.addStretch(1)
        hh.addWidget(body, 30)
        hh.addStretch(1)
        sc.setWidget(holder)
        outer.addWidget(sc, 1)
        v = QVBoxLayout(body)
        v.setContentsMargins(0, 16, 0, 20)
        v.setSpacing(12)

        def card(title, hint=None):
            c = QFrame(objectName="card")
            cl = QVBoxLayout(c)
            cl.setContentsMargins(18, 14, 18, 16)
            cl.setSpacing(10)
            cl.addWidget(QLabel(title, objectName="cardTitle"))
            if hint:
                h = QLabel(hint, objectName="hint")
                h.setWordWrap(True)
                cl.addWidget(h)
            v.addWidget(c)
            return cl

        def slider(lo, hi, key, suffix="%"):
            row = QHBoxLayout()
            s = QSlider(Qt.Orientation.Horizontal)
            s.setRange(lo, hi)
            lbl = QLabel(objectName="muted")
            lbl.setFixedWidth(44)
            s.valueChanged.connect(lambda x: lbl.setText(f"{x}{suffix}"))
            s.valueChanged.connect(lambda x: self._defer_set(key, x))
            row.addWidget(s, 1)
            row.addWidget(lbl)
            return s, row

        # 主题模式
        c = card("主题模式")
        r = QHBoxLayout()
        self.ap_dark = QPushButton("☾  深色", objectName="choice", checkable=True)
        self.ap_light = QPushButton("☀  浅色", objectName="choice", checkable=True)
        self.ap_dark.clicked.connect(lambda: self.set_theme("dark"))
        self.ap_light.clicked.connect(lambda: self.set_theme("light"))
        r.addWidget(self.ap_dark)
        r.addWidget(self.ap_light)
        r.addStretch()
        c.addLayout(r)

        # 背景图片
        c = card("背景图片", "图片上会叠一层主题底色，模块保持半透明底板，保证文字始终清晰。")
        r = QHBoxLayout()
        r.setSpacing(16)
        self.ap_preview = QLabel("未设置背景图", objectName="preview")
        self.ap_preview.setFixedSize(240, 135)
        self.ap_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        r.addWidget(self.ap_preview)
        rv = QVBoxLayout()
        rv.setSpacing(8)
        b = QPushButton("选择图片…", objectName="primary")
        b.clicked.connect(self.pick_bg)
        self.ap_remove = QPushButton("移除背景图")
        self.ap_remove.clicked.connect(lambda: self.set_bg(""))
        rv.addWidget(b)
        rv.addWidget(self.ap_remove)
        rv.addStretch()
        r.addLayout(rv)
        r.addStretch()
        c.addLayout(r)
        c.addWidget(QLabel("背景图可见度", objectName="filterLbl"))
        self.ap_vis, row = slider(5, 60, "bg_vis")
        c.addLayout(row)

        # 强调色
        c = card("强调色", "用于按钮、选中项与高亮。颜色会自动调整明暗，保证按钮上的白字清晰。")
        c.addWidget(QLabel("预设", objectName="filterLbl"))
        r = QHBoxLayout()
        r.setSpacing(8)
        self.swatches = {}
        for key, name, col in ACCENTS:
            s = QPushButton()
            s.setFixedSize(30, 30)
            s.setToolTip(name)
            s.clicked.connect(lambda _=None, k=key: self.set_accent(k))
            self.swatches[key] = (s, col)
            r.addWidget(s)
        r.addStretch()
        c.addLayout(r)
        c.addWidget(QLabel("从背景图提取", objectName="filterLbl"))
        self.img_row = QHBoxLayout()
        self.img_row.setSpacing(8)
        self.img_auto = QPushButton("自动（主色）")
        self.img_auto.clicked.connect(lambda: self.set_accent("image"))
        self.img_row.addWidget(self.img_auto)
        self.img_swatches = []
        for i in range(5):
            s = QPushButton()
            s.setFixedSize(30, 30)
            s.clicked.connect(lambda _=None, i=i: self.set_accent(self.cfg["img_colors"][i]))
            self.img_swatches.append(s)
            self.img_row.addWidget(s)
        self.img_none = QLabel("先选择一张背景图，即可从中提取颜色", objectName="hint")
        self.img_row.addWidget(self.img_none)
        self.img_row.addStretch()
        c.addLayout(self.img_row)
        r = QHBoxLayout()
        r.addWidget(QLabel("效果预览：", objectName="hint"))
        r.addWidget(QPushButton("主按钮", objectName="primary"))
        r.addWidget(QPushButton("普通按钮"))
        r.addWidget(QLabel("已选中", objectName="pill"))
        r.addStretch()
        c.addLayout(r)

        # 透明度
        c = card("透明度", "模块不透明度只在设置了背景图时生效；最低 75%，避免背景干扰文字。")
        c.addWidget(QLabel("模块不透明度（标题栏、侧边菜单栏、卡片、列表）", objectName="filterLbl"))
        self.ap_alpha, row = slider(75, 100, "card_alpha")
        c.addLayout(row)
        c.addWidget(QLabel("整个窗口不透明度", objectName="filterLbl"))
        self.ap_opacity, row = slider(70, 100, "win_opacity")
        c.addLayout(row)
        v.addStretch()

        self._defer = QTimer(self, singleShot=True, interval=120, timeout=self.apply_appearance)
        return page

    def _defer_set(self, key, val):
        if getattr(self, "_syncing", False):
            return
        self.cfg[key] = val
        if key == "win_opacity":
            self.setWindowOpacity(val / 100)
            save_cfg(self.cfg)
        elif key == "bg_vis":
            self.frame.set_image(self.cfg.get("bg_image"), val / 100)
            save_cfg(self.cfg)
        else:
            self._defer.start()   # 拖动滑块时合并刷新

    def sync_appearance_ui(self):
        self._syncing = True
        self.ap_dark.setChecked(THEME == "dark")
        self.ap_light.setChecked(THEME == "light")
        self.ap_vis.setValue(int(self.cfg.get("bg_vis", 35)))
        self.ap_alpha.setValue(int(self.cfg.get("card_alpha", 88)))
        self.ap_opacity.setValue(int(self.cfg.get("win_opacity", 100)))
        self._syncing = False
        has = bool(self.cfg.get("bg_image")) and os.path.exists(self.cfg.get("bg_image", ""))
        if has:
            pm = QPixmap(self.cfg["bg_image"]).scaled(240, 135, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                                     Qt.TransformationMode.SmoothTransformation)
            self.ap_preview.setPixmap(pm.copy((pm.width() - 240) // 2, (pm.height() - 135) // 2, 240, 135))
        else:
            self.ap_preview.setPixmap(QPixmap())
            self.ap_preview.setText("未设置背景图")
        self.ap_remove.setEnabled(has)
        self.ap_vis.setEnabled(has)
        self.ap_alpha.setEnabled(has)
        acc = self.cfg.get("accent", "blue")
        ring = C("text")
        for key, (s, col) in self.swatches.items():
            s.setStyleSheet(f"background:{col};border-radius:15px;border:{3 if acc == key else 1}px solid "
                            f"{ring if acc == key else C('btnb')};")
        cols = self.cfg.get("img_colors") or []
        for i, s in enumerate(self.img_swatches):
            if has and i < len(cols):
                s.show()
                s.setToolTip(cols[i])
                s.setStyleSheet(f"background:{cols[i]};border-radius:15px;border:{3 if acc == cols[i] else 1}px solid "
                                f"{ring if acc == cols[i] else C('btnb')};")
            else:
                s.hide()
        self.img_auto.setVisible(has)
        self.img_auto.setObjectName("primary" if acc == "image" else "")
        self.img_auto.style().unpolish(self.img_auto); self.img_auto.style().polish(self.img_auto)
        self.img_none.setVisible(not has)

    def set_accent(self, key):
        self.cfg["accent"] = key
        self.apply_appearance()

    def pick_bg(self):
        p, _ = QFileDialog.getOpenFileName(self, "选择背景图片", os.path.join(ROOT, "图片"),
                                           "图片 (*.png *.jpg *.jpeg *.bmp *.webp *.gif)")
        if p:
            self.set_bg(p)

    def set_bg(self, src):
        if src:
            # 复制一份到配置目录，原图被移动或删除后背景仍然有效
            os.makedirs(CFG_DIR, exist_ok=True)
            for old in os.listdir(CFG_DIR):
                if old.startswith("background."):
                    try:
                        os.remove(os.path.join(CFG_DIR, old))
                    except OSError:
                        pass
            dst = os.path.join(CFG_DIR, "background" + os.path.splitext(src)[1].lower())
            try:
                shutil.copyfile(src, dst)
            except OSError as e:
                self.show_toast(f"无法读取图片：{e.strerror or e}")
                return
            cols = image_colors(dst)
            if not cols:
                self.show_toast("无法识别这张图片")
                return
            self.cfg.update(bg_image=dst, img_colors=cols, accent="image")
            # 根据图片明暗自动建议主题：亮图用浅色，暗图用深色，文字对比更好
            avg = QImage(dst).scaled(1, 1, Qt.AspectRatioMode.IgnoreAspectRatio,
                                     Qt.TransformationMode.SmoothTransformation).pixelColor(0, 0)
            self.cfg["theme"] = "light" if _lum(avg.name()) > 0.45 else "dark"
            self.show_toast("已应用背景图，并从中提取了强调色")
        else:
            self.cfg.update(bg_image="", img_colors=[])
            if self.cfg.get("accent") == "image" or str(self.cfg.get("accent", "")).startswith("#"):
                self.cfg["accent"] = "blue"
        self.apply_appearance()

    def reset_appearance(self):
        for k in ("theme", "accent", "bg_image", "bg_vis", "card_alpha", "win_opacity", "img_colors"):
            self.cfg[k] = DEFAULTS[k]
        self.apply_appearance()
        self.show_toast("已恢复默认外观")

    # ---------- 数据 ----------
    def on_fs_change(self, path):
        self.dirty = True
        self.fs_timer.start()

    def on_fs_settled(self):
        """文件夹变化稳定后：整理新文件；窗口可见才刷新列表，隐藏时只记下“需要刷新”。"""
        if self.cfg["auto"]:
            moved, pending = organize()
            if moved and not self.isVisible():
                self.tray.showMessage(APP, "已整理：" + moved[0] if len(moved) == 1 else f"已整理 {len(moved)} 个新文件",
                                      self.app_icon, 3000)
            if pending:
                self.retry_timer.start()
        if self.isVisible():
            self.tick(organize_first=False)
        else:
            self.dirty = True
            self.ensure_root_watched()

    def ensure_root_watched(self):
        if ROOT not in self.watcher.directories() and os.path.isdir(ROOT):
            self.watcher.addPath(ROOT)

    def tick(self, organize_first=True):
        if organize_first and self.cfg["auto"]:
            _, pending = organize()
            if pending:
                self.retry_timer.start()
        items, dirs = scan()
        self.dirty = False
        # 同步监视列表（新建的“年-月”文件夹也要监视）
        watched = set(self.watcher.directories())
        want = set(dirs)
        if want - watched:
            self.watcher.addPaths(list(want - watched))
        if watched - want:
            self.watcher.removePaths(list(watched - want))
        sig = (len(items), sum(x["size"] for x in items), max((x["mtime"] for x in items), default=0),
               hash(tuple(x["path"] for x in items)))
        if sig != self.sig:
            self.sig, self.items = sig, items
            self.refresh_counts()
            self.fill()
        self.refresh_stats()

    def refresh_counts(self):
        counts = {}
        for x in self.items:
            counts[x["cat"]] = counts.get(x["cat"], 0) + 1
        for c, b in self.cat_btns.items():
            b.count = len(self.items) if c == "全部文件" else counts.get(c, 0)
            b.update()
        self.cat_btns["未整理"].setVisible(counts.get("未整理", 0) > 0 or self.cur == "未整理")

    def refresh_stats(self):
        self.st_count.setText(str(len(self.items)))
        self.st_size.setText(human(sum(x["size"] for x in self.items)))
        try:
            du = shutil.disk_usage(ROOT)
            self.st_disk.setText(f"{human(du.free)} / {human(du.total)}")
            self.disk_bar.setValue(int((du.total - du.free) / du.total * 1000))
        except OSError:
            pass
        self.st_auto.setText("已开启" if self.cfg["auto"] else "已关闭")

    def icon_for(self, x, item=None):
        """图标缓存：同扩展名共用一个；exe 等按文件取图标；图片缩略图在后台逐批生成，不卡界面。"""
        thumb = x["ext"] in THUMB_EXT and x["size"] < 30 * 1024 * 1024
        key = ("t:" + x["path"] + str(x["mtime"])) if thumb else \
            (x["path"] if x["ext"] in (".exe", ".lnk", ".ico", ".url") else x["ext"])
        if key in self.icon_cache:
            return self.icon_cache[key]
        if thumb:
            if item is not None:
                self.thumb_items.setdefault(key, []).append(item)
                if len(self.thumb_items[key]) == 1:
                    self.thumbs.request(key, x["path"])
            gen = "g:" + x["ext"]
            if gen not in self.icon_cache:
                self.icon_cache[gen] = self.provider.icon(QFileInfo(x["path"]))
            return self.icon_cache[gen]
        self.icon_cache[key] = self.provider.icon(QFileInfo(x["path"]))
        return self.icon_cache[key]

    def on_thumb(self, key, img):
        """后台线程生成好一张缩略图：放进缓存并更新列表里对应的条目。"""
        self.icon_cache[key] = QIcon(QPixmap.fromImage(img))
        for item in self.thumb_items.pop(key, []):
            try:
                item.setIcon(0, self.icon_cache[key])
            except RuntimeError:   # 列表已重建，旧条目已删除
                pass

    @staticmethod
    def group_of(ts):
        d = datetime.fromtimestamp(ts)
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        if d >= today:
            return "今天"
        if d >= today - timedelta(days=1):
            return "昨天"
        if d >= today - timedelta(days=6):
            return "最近 7 天"
        if d.year == today.year and d.month == today.month:
            return "本月早些时候"
        return f"{d.year} 年 {d.month} 月"

    def visible_items(self):
        words = self.search.text().lower().split()
        now = time.time()
        today0 = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        tf = TIME_FILTERS[self.time_box.currentIndex()][1] if hasattr(self, "time_box") else None
        sf = SIZE_FILTERS[self.size_box.currentIndex()][1] if hasattr(self, "size_box") else None

        def ok(x):
            if self.cur != "全部文件" and x["cat"] != self.cur:
                return False
            if not all(w in x["name"].lower() for w in words):
                return False
            if tf is not None:
                if tf == 0 and x["mtime"] < today0:
                    return False
                if tf > 0 and x["mtime"] < now - tf * 86400:
                    return False
                if tf < 0 and x["mtime"] >= now + tf * 86400:
                    return False
            if sf is not None and not (sf[0] <= x["size"] < sf[1]):
                return False
            return True
        key = self.cfg.get("sort_key", "time")
        kf = {"time": lambda x: x["mtime"], "name": lambda x: x["name"].lower(), "size": lambda x: x["size"],
              "cat": lambda x: (CATS + ["未整理"]).index(x["cat"]) if x["cat"] in CATS + ["未整理"] else 99,
              "ext": lambda x: (x["ext"], x["name"].lower())}[key]
        items = [x for x in self.items if ok(x)]
        if key == "cat":   # 分类内部按时间新→旧
            items.sort(key=lambda x: -x["mtime"])
            return sorted(items, key=kf, reverse=self.cfg.get("sort_desc", True))
        return sorted(items, key=kf, reverse=self.cfg.get("sort_desc", True))

    def group_key(self, x):
        k = self.cfg.get("sort_key", "time")
        if k == "time":
            return self.group_of(x["mtime"])
        if k == "cat":
            return x["cat"]
        if k == "ext":
            return x["ext"][1:].upper() + " 文件" if x["ext"] else "无扩展名"
        return None

    def set_sort(self, key, toggle=False, keep_dir=True):
        if toggle and key == self.cfg.get("sort_key"):
            self.cfg["sort_desc"] = not self.cfg.get("sort_desc", True)
        elif key != self.cfg.get("sort_key"):
            self.cfg["sort_desc"] = key in ("time", "size")   # 时间 / 大小默认从大到小，名称等默认 A→Z
        self.cfg["sort_key"] = key
        save_cfg(self.cfg)
        self.sort_box.blockSignals(True)
        self.sort_box.setCurrentIndex([k for _, k in SORTS].index(key))
        self.sort_box.blockSignals(False)
        self.fill()

    def update_sort_ui(self):
        key, desc = self.cfg.get("sort_key", "time"), self.cfg.get("sort_desc", True)
        self.sort_dir.setText("" if desc else "")
        tip = {"time": ("新 → 旧", "旧 → 新"), "size": ("大 → 小", "小 → 大")}.get(key, ("Z → A", "A → Z"))
        self.sort_dir.setToolTip("当前：" + (tip[0] if desc else tip[1]) + "，点击切换")
        labels = [n + ((" ↓" if desc else " ↑") if k == key else "") for n, k in zip(COL_NAMES, COL_KEYS)]
        self.tree.setHeaderLabels(labels)
        filtered = self.time_box.currentIndex() or self.size_box.currentIndex()
        self.b_reset.setVisible(bool(filtered or self.search.text()))

    def reset_filters(self):
        for b in (self.time_box, self.size_box):
            b.blockSignals(True); b.setCurrentIndex(0); b.blockSignals(False)
        self.search.clear()
        self.fill()

    def fill(self):
        if not hasattr(self, "tree"):
            return
        sel = set(self.selected())
        collapsed = {self.tree.topLevelItem(i).text(0).split("  ·")[0] for i in range(self.tree.topLevelItemCount())
                     if not self.tree.topLevelItem(i).isExpanded()}
        sb = self.tree.verticalScrollBar().value()
        view = self.visible_items()
        self.tree.setUpdatesEnabled(False)
        self.thumb_items.clear()
        self.thumbs.clear()
        self.tree.clear()
        # 先在内存里建好所有条目，再一次性挂到列表上（逐条插入会反复重算布局，几百个文件就要好几秒）
        groups, top, selected_items = {}, [], []
        gfont = self.font()
        gfont.setBold(True)
        gfont.setPixelSize(12)
        muted = QColor(C("muted"))
        left = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        for x in view:
            gname = self.group_key(x)
            if gname is None:
                g = None
            else:
                g = groups.get(gname)
                if g is None:
                    gi = QTreeWidgetItem()
                    gi.setFlags(Qt.ItemFlag.ItemIsEnabled)
                    gi.setFont(0, gfont)
                    gi.setForeground(0, muted)
                    g = groups[gname] = [gi, []]
                    top.append(gi)
            it = QTreeWidgetItem([x["name"], x["cat"], human(x["size"]),
                                  datetime.fromtimestamp(x["mtime"]).strftime("%Y-%m-%d %H:%M")])
            it.setIcon(0, self.icon_for(x, it))
            it.setData(0, Qt.ItemDataRole.UserRole, x["path"])
            it.setToolTip(0, x["path"])
            for col in (1, 2, 3):
                it.setTextAlignment(col, left)
                it.setForeground(col, muted)
            if x["path"] in sel:
                selected_items.append(it)
            if g is None:
                top.append(it)
            else:
                g[1].append(it)
        for name, (gi, children) in groups.items():
            gi.setText(0, f"{name}  ·  {len(children)}")
            gi.addChildren(children)
        self.tree.addTopLevelItems(top)
        for name, (gi, _) in groups.items():
            gi.setFirstColumnSpanned(True)
            if name not in collapsed:
                gi.setExpanded(True)
        for it in selected_items:
            it.setSelected(True)
        self.tree.setUpdatesEnabled(True)
        self.tree.verticalScrollBar().setValue(sb)
        self.page_title.setText(self.cur)
        total = sum(x["size"] for x in view)
        self.page_sub.setText(f"{len(view)} 个文件 · {human(total)}" + (f" · 搜索“{self.search.text()}”" if self.search.text() else ""))
        if not view:
            ph = QTreeWidgetItem(self.tree, ["没有找到文件" if self.search.text() else "这里还没有文件"])
            ph.setFlags(Qt.ItemFlag.NoItemFlags)
            ph.setFirstColumnSpanned(True)
            ph.setForeground(0, QColor(C("faint")))
        self.update_sort_ui()
        self.update_actions()

    def selected(self):
        if not hasattr(self, "tree"):
            return []
        return [i.data(0, Qt.ItemDataRole.UserRole) for i in self.tree.selectedItems() if i.data(0, Qt.ItemDataRole.UserRole)]

    def update_actions(self):
        n = len(self.selected())
        for b in (self.b_open, self.b_reveal, self.b_move, self.b_delete):
            b.setEnabled(n > 0)
        self.b_rename.setEnabled(n == 1)
        self.sel_hint.setText(f"已选 {n} 项 · 可直接拖到其他程序" if n else "双击打开 · 右键更多操作 · 可多选")

    # ---------- 操作 ----------
    def show_toast(self, msg):
        self.toast.setText(msg)
        self.toast.adjustSize()
        p = self.toast.parentWidget()
        self.toast.move((p.width() - self.toast.width()) // 2, p.height() - self.toast.height() - 70)
        self.toast.raise_()
        self.toast.show()
        self.toast_timer.start(2600)

    def open_path(self, p):
        try:
            os.startfile(p)
        except OSError as e:
            self.show_toast(f"无法打开：{e.strerror or e}")

    def open_selected(self):
        for p in self.selected()[:10]:
            self.open_path(p)

    def open_first(self):
        v = self.visible_items()
        if v:
            self.open_path(v[0]["path"])

    def reveal_selected(self):
        s = self.selected()
        if s:
            subprocess.Popen(f'explorer /select,"{s[0]}"')

    def delete_selected(self):
        s = self.selected()
        if not s:
            return
        what = f"“{os.path.basename(s[0])}”" if len(s) == 1 else f"这 {len(s)} 个文件"
        if Dialog(self, "删除文件", f"把{what}移到回收站？之后可以在回收站还原。", ok="删除", danger=True).exec():
            try:
                recycle(s)
                for p in s:
                    log("删除：" + os.path.basename(p))
                self.show_toast(f"已删除 {len(s)} 个文件")
            except OSError as e:
                self.show_toast(str(e))
            remove_empty_dirs()
            self.tick()

    def rename_selected(self):
        s = self.selected()
        if len(s) != 1:
            return
        old = os.path.basename(s[0])
        d = Dialog(self, "重命名", "输入新的文件名：", ok="重命名", edit=old)
        if d.exec():
            new = d.value()
            if not new or new == old:
                return
            if any(ch in new for ch in '\\/:*?"<>|'):
                self.show_toast("文件名不能包含 \\ / : * ? \" < > |")
                return
            try:
                os.rename(s[0], os.path.join(os.path.dirname(s[0]), new))
                log(f"重命名：{old} → {new}")
            except OSError as e:
                self.show_toast(f"重命名失败：{e.strerror or e}")
            self.tick()

    def move_menu(self):
        m = QMenu(self)
        s = self.selected()
        for c in CATS:
            a = m.addAction(c, lambda c=c: self.move_selected(c))
        m.addSeparator()
        m.addAction("选择其他文件夹…", lambda: self.move_selected(None))
        m.setEnabled(bool(s))
        return m

    def move_selected(self, dest):
        s = self.selected()
        if not s:
            return
        if dest is None:
            dest = QFileDialog.getExistingDirectory(self, "移动到", ROOT)
            if not dest:
                return
        bad = 0
        for p in s:
            try:
                move_to(p, dest)
            except OSError:
                bad += 1
        remove_empty_dirs()
        self.show_toast(f"已移动 {len(s) - bad} 个文件" + (f"，{bad} 个失败" if bad else ""))
        self.tick()

    def context_menu(self, pos):
        if not self.selected():
            return
        m = QMenu(self)
        a = m.addAction("打开", self.open_selected)
        f = a.font(); f.setBold(True); a.setFont(f)
        m.addAction("打开所在位置", self.reveal_selected)
        if len(self.selected()) == 1:
            m.addAction("重命名\tF2", self.rename_selected)
        mv = self.move_menu()
        mv.setTitle("移动到")
        m.addMenu(mv)
        m.addAction("复制路径", lambda: QApplication.clipboard().setText("\n".join(self.selected())))
        m.addSeparator()
        m.addAction("删除\tDel", self.delete_selected)
        m.exec(self.tree.viewport().mapToGlobal(pos))

    def do_organize(self, manual=False):
        moved, _ = organize()
        self.tick()
        if manual:
            self.show_toast(f"整理了 {len(moved)} 个文件" if moved else "没有需要整理的文件")

    def do_cleanup(self):
        if not self.cfg["clean_on"] and not self.cfg["cap_on"]:
            self.open_settings()
            self.show_toast("请先开启“定期清理”或“容量阈值清理”")
            return
        rule = []
        if self.cfg["clean_on"]:
            rule.append(f"超过 {self.cfg['clean_days']} 天的文件")
        if self.cfg["cap_on"]:
            rule.append(f"总量超过 {self.cfg['cap_gb']:g} GB 时最旧的文件")
        prot = "、".join(self.cfg["protect"]) or "无"
        if Dialog(self, "立即清理", f"将把 {' 和 '.join(rule)} 移到回收站。\n受保护的分类：{prot}", ok="开始清理", danger=True).exec():
            n, freed = cleanup(self.cfg)
            self.tick()
            self.show_toast(f"清理了 {n} 个文件，释放 {human(freed)}")
            if self.pages.currentIndex() == 1:
                self.log_view.setPlainText("\n".join(LOGS))

    def auto_cleanup(self):
        if self.cfg["clean_on"] or self.cfg["cap_on"]:
            n, freed = cleanup(self.cfg)
            if n:
                self.tray.showMessage(APP, f"自动清理了 {n} 个文件，释放 {human(freed)}", self.app_icon, 3000)
            self.tick()

    # ---------- 窗口 ----------
    def show_main(self):
        if self.dirty:
            self.tick()   # 隐藏期间有变化：先刷新再显示
        else:
            self.refresh_stats()
        self.show()
        if self.isMinimized():
            self.showNormal()
        self.raise_()
        self.activateWindow()

    def quit(self):
        self.thumbs.stop()
        self.tray.hide()
        QApplication.instance().quit()

    def closeEvent(self, e):
        if self.cfg["close"] == "tray":
            e.ignore()
            self.hide()
            if not self.told_tray:
                self.told_tray = True
                self.tray.showMessage(APP, "仍在后台运行，会继续自动整理。右键托盘图标可退出。", self.app_icon, 3000)
        else:
            self.quit()

    def toggle_max(self):
        self.showNormal() if self.isMaximized() else self.showMaximized()

    def changeEvent(self, e):
        if e.type() == e.Type.WindowStateChange and hasattr(self, "frame"):
            mx = self.isMaximized()
            self.layout().setContentsMargins(*([0] * 4 if mx else [BORDER] * 4))
            self.frame.maxed = mx
            for wdg in (self.title, self.side):
                wdg.setProperty("max", "true" if mx else "false")
                wdg.style().unpolish(wdg); wdg.style().polish(wdg)
            self.frame.cache = None
            self.frame.update()
            self.title.btn_max.setText("" if mx else "")
        super().changeEvent(e)

    def edges_at(self, gp):
        if self.isMaximized():
            return Qt.Edge(0)
        p = self.mapFromGlobal(gp)
        r = self.rect()
        m = BORDER + 2
        e = Qt.Edge(0)
        if p.x() <= m: e |= Qt.Edge.LeftEdge
        if p.x() >= r.width() - m: e |= Qt.Edge.RightEdge
        if p.y() <= m: e |= Qt.Edge.TopEdge
        if p.y() >= r.height() - m: e |= Qt.Edge.BottomEdge
        return e

    def eventFilter(self, obj, ev):
        t = ev.type()
        if obj is getattr(self, "search", None) and t in (ev.Type.FocusIn, ev.Type.FocusOut):
            self.search_box.setProperty("focus", "true" if t == ev.Type.FocusIn else "false")
            self.search_box.style().unpolish(self.search_box)
            self.search_box.style().polish(self.search_box)
        if t in (ev.Type.MouseMove, ev.Type.MouseButtonPress, ev.Type.HoverMove) and not self.isMaximized() \
                and isinstance(obj, QWidget) and obj.window() is self:
            gp = ev.globalPosition().toPoint() if hasattr(ev, "globalPosition") else None
            if gp is not None:
                e = self.edges_at(gp)
                if t == ev.Type.MouseButtonPress and e and ev.button() == Qt.MouseButton.LeftButton:
                    self.windowHandle().startSystemResize(e)
                    return True
                shape = None
                if e in (Qt.Edge.LeftEdge, Qt.Edge.RightEdge): shape = Qt.CursorShape.SizeHorCursor
                elif e in (Qt.Edge.TopEdge, Qt.Edge.BottomEdge): shape = Qt.CursorShape.SizeVerCursor
                elif e in (Qt.Edge.LeftEdge | Qt.Edge.TopEdge, Qt.Edge.RightEdge | Qt.Edge.BottomEdge): shape = Qt.CursorShape.SizeFDiagCursor
                elif e: shape = Qt.CursorShape.SizeBDiagCursor
                if shape != self._edge_shape:   # 只在形状变化时设置光标
                    self._edge_shape = shape
                    if shape is not None:
                        self.setCursor(shape)
                    else:
                        self.unsetCursor()
        return super().eventFilter(obj, ev)


def main():
    # 命名互斥体：供安装 / 卸载程序检测本程序是否在运行
    ctypes.windll.kernel32.CreateMutexW(None, False, "DownloadButlerMutex")
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName(APP)
    # 单实例：再次启动时唤出已运行的窗口
    sock = QLocalSocket()
    sock.connectToServer("DownloadButler")
    if sock.waitForConnected(300):
        sock.write(b"show")
        sock.waitForBytesWritten(300)
        return
    QLocalServer.removeServer("DownloadButler")
    server = QLocalServer()
    server.listen("DownloadButler")
    w = Main(start_hidden="--min" in sys.argv)
    server.newConnection.connect(lambda: (server.nextPendingConnection(), w.show_main()))
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
