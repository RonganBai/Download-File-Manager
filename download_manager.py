# -*- coding: utf-8 -*-
"""自动整理文件管理器（原名“下载管家”）：下载文件夹的可视化管理 + 自动整理 + 定期 / 容量阈值清理（界面风格与格式转换器一致）。"""
import collections
import ctypes
import hashlib
import json
import re
import os
import shutil
import subprocess
import sys
import threading
import time
import winreg
from ctypes import wintypes

import archive
import help_content
import journal
from datetime import datetime, timedelta

from PyQt6.QtCore import QVariantAnimation, QEasingCurve, QFileSystemWatcher, QProcess, QThread, pyqtSignal, Qt, QTimer, QSize, QRectF, QPropertyAnimation, pyqtProperty, QFileInfo, QUrl, QMimeData, QPoint
from PyQt6.QtGui import QCursor, QIcon, QPixmap, QPainter, QColor, QFont, QPen, QAction, QKeySequence, QShortcut, QPainterPath, QDesktopServices, QImage, QImageReader, QBrush
from PyQt6.QtNetwork import QLocalServer, QLocalSocket
from PyQt6.QtWidgets import (QApplication, QSizePolicy, QWidget, QFrame, QLabel, QPushButton, QLineEdit, QHBoxLayout, QVBoxLayout,
                             QGridLayout, QTreeWidget, QTreeWidgetItem, QAbstractItemView, QFileIconProvider, QMenu,
                             QStackedWidget, QScrollArea, QCheckBox, QSpinBox, QDoubleSpinBox, QComboBox, QTextBrowser,
                             QProgressBar, QSystemTrayIcon, QDialog, QFileDialog, QHeaderView, QSlider)

VERSION = "2.9.2"
APP = "下载管家"          # 内部标识：配置目录、开机启动项、密码本加密用它，改名后保持不变以免丢失设置
APP_NAME = "自动整理文件管理器"     # 显示给用户的名称
CFG_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), APP)
CFG_PATH = os.path.join(CFG_DIR, "config.json")
ASSETS = os.path.join(getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__))), "assets")
DEFAULTS = dict(auto=True, recent_days=30, clean_on=False, clean_days=30, cap_on=False, cap_gb=20.0, protect=["重要文件"],
                autostart=False, close="tray", theme="dark", side_open=True, side_mode="open",
                accent="blue", bg_image="", bg_vis=35, card_alpha=88, win_opacity=100, img_colors=[],
                sort_key="time", sort_desc=True, settle_sec=10, rules=[], root="", by_month=True,
                loose_dirs=False, zip_fmt="zip", zip_level=5, zip_method="aes", unzip_mode="smart",
                unzip_overwrite="rename", unzip_open=True, unzip_recycle=False, pw_book=[], tour_done=False,
                folders=[], extra_skip="", schemes=[])
# 其他文件夹（桌面、聊天软件的接收目录等）里默认不动的类型：快捷方式、程序 / 脚本（可能是绿色软件）、
# 配置和数据文件——它们往往被某个程序按固定路径读取，挪走会让程序找不到
DEFAULT_EXTRA_SKIP = (".lnk .url .exe .com .bat .cmd .ps1 .vbs .reg .msc .scr .dll .sys .ini .cfg .conf .json .xml "
                      ".yaml .yml .toml .db .sqlite .sqlite3 .dat .log .tmp .lock")
EXTRA_SUB = "已整理"                    # 其他文件夹里的分类都放进这个子文件夹，不和你自己的“图片”“代码”文件夹混在一起
CLOUD_ATTRS = 0x1000 | 0x40000 | 0x400000   # OFFLINE | RECALL_ON_OPEN | RECALL_ON_DATA_ACCESS：OneDrive 等“仅在线”文件
TEMP_PREFIX = archive.TEMP_PREFIX       # 压缩 / 解压进行中的临时文件，扫描、整理、清理都跳过
ZIP_METHODS = [("aes", "AES-256（更安全）"), ("zipcrypto", "ZipCrypto（Windows 自带解压也能打开）")]
UNZIP_MODES = [("smart", "智能：只有一个文件夹时直接放出，否则新建同名文件夹"),
               ("folder", "总是新建同名文件夹"), ("here", "直接放在压缩包所在的文件夹")]
OVERWRITE_MODES = [("rename", "自动重命名（两份都保留）"), ("overwrite", "覆盖（旧文件进回收站）"), ("skip", "跳过")]
BORDER = 6

DEFAULT_RULES = [
    ("重要文件", "", ".pdf .doc .docx .xls .xlsx .ppt .pptx .txt .md .csv .wps .et .dps .rtf .odt"),
    ("安装包", "", ".exe .msi .msix .appx .apk .dmg .iso"),
    ("压缩包", "", ".zip .rar .7z .tar .gz .bz2 .xz"),
    ("图片", "", ".jpg .jpeg .png .gif .bmp .webp .svg .heic .ico"),
    ("视频", "", ".mp4 .mkv .avi .mov .wmv .flv .webm"),
    ("音乐", "", ".mp3 .wav .flac .aac .m4a .ogg"),
    ("代码", "", ".py .js .html .css .json .java .c .cpp .ps1 .bat .sh"),
]
OTHER = "其他文件"                     # 兜底分类，固定存在
RESERVED_CATS = {OTHER, "未整理", "全部文件", "最近添加"}
RECENT = "最近添加"
RECENT_DAYS = 30                 # “最近添加”默认显示多少天内到达这台电脑的文件（可在设置里改）
RECENT_OPTIONS = (1, 3, 7, 14, 30, 60, 90, 180, 365)
# 左侧菜单：常驻展开 / 自动（鼠标靠近时展开，离开一会儿后收起）/ 常驻折叠
SIDE_MODES = {"open": ("\ue89f", "常驻展开"), "auto": ("\ue962", "自动：鼠标靠近时展开，离开后自动收起"),
              "closed": ("\ue8a0", "常驻折叠")}
SIDE_OPEN_W, SIDE_CLOSED_W = 196, 52


def days_label(n):
    return {1: "24 小时", 180: "半年", 365: "1 年"}.get(n, f"{n} 天")
DEFAULT_GLYPH = {r[0]: r[1] for r in DEFAULT_RULES}
DEFAULT_GLYPH.update({OTHER: "\ue7c3", "未整理": "\ue896", "全部文件": "\ue8b7", "最近添加": "\ue823"})
FOLDER_GLYPH = "\ue8b7"
# 以下是“当前生效”的规则，由 apply_rules() 原地更新（其他地方持有的引用保持有效）
RULES = list(DEFAULT_RULES)
CATS = [r[0] for r in RULES] + [OTHER]
GLYPH = dict(DEFAULT_GLYPH)
EXT_MAP = {}
KW_TEXT = {}                          # 分类名 → 关键词原文（设置页显示用）
KEYWORDS = []                         # [(分类名, 限定扩展名集合, [关键词正则])]，按规则顺序
BY_MONTH = True                       # 是否按“年-月”分子文件夹
SORTS = (("修改时间", "time"), ("名称", "name"), ("大小", "size"), ("分类", "cat"), ("类型（扩展名）", "ext"))
COL_KEYS = ("name", "cat", "size", "time")
COL_NAMES = ("名称", "分类", "大小", "修改时间")
TIME_FILTERS = (("全部时间", None), ("今天", 0), ("最近 7 天", 7), ("最近 30 天", 30), ("最近 1 年", 365), ("1 年以前", -365))
MB = 1024 * 1024
SIZE_FILTERS = (("全部大小", None), ("小于 1 MB", (0, MB)), ("1 – 100 MB", (MB, 100 * MB)),
                ("100 MB – 1 GB", (100 * MB, 1024 * MB)), ("大于 1 GB", (1024 * MB, 1 << 62)))
# 各浏览器 / 下载工具的未完成文件：Chrome/Edge、Firefox、Safari、Opera、迅雷、uTorrent、qBittorrent、
# BitComet、IDM、Free Download Manager、JDownloader、Chrome 文件系统 API 等
SKIP_EXT = {".crdownload", ".part", ".partial", ".download", ".tmp", ".temp", ".opdownload", ".xltd", ".td",
            ".!ut", ".!qb", ".bc!", ".fdmdownload", ".dtapart", ".crswap", ".filepart", ".downloading",
            ".aria2", ".jdownload", ".idm", ".~tmp"}
SKIP_SUFFIX = (".xltd.cfg", ".td.cfg")                            # 迅雷的任务配置文件
COMPANION_EXT = (".part", ".aria2", ".xltd", ".td", ".crdownload", ".!ut", ".!qb", ".bc!")
SKIP_NAMES = {"desktop.ini", "thumbs.db"}
THUMB_EXT = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".ico"}

# ---------------- 主题（与格式转换器 v1.13 相同的配色） ----------------
# 背景层（frame / nav / card / list）偏暗、偏平；可点击的控件（btn / inp）更亮并带明显描边，一眼区分
BASE_THEMES = {
    "dark": dict(frame="#101013", border="#2c2c33", text="#ececf0", muted="#b4b4be", faint="#9d9da8",
                 card="#1b1b20", cardb="#2a2a31", nav="#0d0d10", area="#222228", areab="#2e2e35",
                 btn="#2f2f38", btnh="#3b3b46", btnb="#4a4a56", inp="#26262d", list="#16161a",
                 sep="#2c2c33", tbp="#45454f", knob_off="#55555f", danger="#e5484d"),
    "light": dict(frame="#dfe3e9", border="#c9ced6", text="#14171c", muted="#3b424d", faint="#575e69",
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
#title QPushButton#titleHelp { font-size:13px; }
#sideModes { background:@btn; border:1px solid @btnb; border-radius:7px; }
#title #sideModes QPushButton#sideMode { background:transparent; border:1px solid transparent; border-radius:5px;
                     min-width:26px; max-width:26px; min-height:22px; max-height:22px; font-size:12px; }
#title #sideModes QPushButton#sideMode:hover { background:@btnh; color:@text; }
#title #sideModes QPushButton#sideMode:checked { background:@soft; color:@softt; border-color:@accent; }
#title QPushButton#titleHelp:checked { background:@soft; color:@softt; border-color:@accent; }
#themeIcon { color:@muted; font-family:"Segoe Fluent Icons","Segoe MDL2 Assets"; font-size:12px; }
#titleSep { background:@sep; min-width:1px; max-width:1px; min-height:16px; max-height:16px; }
#side { background:@navA; border-right:1px solid @cardb; border-bottom-left-radius:10px; }
#sideSep { background:@sep; margin:2px 6px; }
QPushButton#sideBtn { background:transparent; border:1px solid transparent; border-radius:8px; padding:0; text-align:left; }
QPushButton#sideBtn:hover { background:@btnh; border-color:@btnb; }
QPushButton#sideBtn:checked { background:@soft; border-color:@accent; }
QPushButton#tabBtn { background:transparent; border:1px solid transparent; border-radius:8px; padding:6px 16px; color:@muted; }
QPushButton#tabBtn:hover { background:@btnh; border-color:@btnb; color:@text; }
#tourRing { background:transparent; border:3px solid @accent; border-radius:10px; }
QPushButton#helpTopic { background:transparent; border:1px solid transparent; border-radius:8px; padding:7px 12px; text-align:left; color:@text; }
QPushButton#helpTopic:hover { background:@btnh; }
QPushButton#helpTopic:checked { background:@soft; border-color:@accent; color:@softt; font-weight:bold; }
QPushButton#tabBtn:checked { background:@soft; border-color:@accent; color:@softt; font-weight:bold; }
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
/* 设置 / 外观 / 帮助页顶部：和左侧菜单同样的底色，放在背景图上也看得清 */
#pageHead { background:@navA; border-bottom:1px solid @cardb; }
#tabBar { background:@btn; border:1px solid @btnb; border-radius:10px; }
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
QPushButton#backBtn { min-width:36px; max-width:36px; min-height:36px; max-height:36px; padding:0;
    font-family:"Segoe Fluent Icons","Segoe MDL2 Assets"; font-size:14px; }
QPushButton#recentBtn { background:transparent; border:none; }
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
EXTRA = []        # 其他管理的文件夹：[{path, auto 自动整理新文件, clean 参与自动清理, added 加入时间}]
EXTRA_SKIP = set(DEFAULT_EXTRA_SKIP.split())


def roots():
    """所有管理的文件夹：主文件夹 + 当前已连接（存在）的其他文件夹。"""
    return [ROOT] + [f["path"] for f in EXTRA if os.path.isdir(f["path"])]


def cat_base(root):
    """分类文件夹所在的位置：主文件夹直接放，其他文件夹放进“已整理”子文件夹。"""
    return root if root == ROOT else os.path.join(root, EXTRA_SUB)


def root_of(path):
    """path 属于哪个管理的文件夹（取最深的那个）；都不属于返回 None。"""
    p = _norm(path)
    best = None
    for r in roots():
        n = _norm(r)
        if (p + os.sep).startswith(n + os.sep) and (best is None or len(n) > len(_norm(best))):
            best = r
    return best


def extra_cfg(root):
    return next((f for f in EXTRA if _norm(f["path"]) == _norm(root)), None)


# ---------------- 可配置：分类规则 / 管理的文件夹 ----------------
def parse_exts(text):
    """“pdf, .DOCX  txt” → [".pdf", ".docx", ".txt"]（去重、保持顺序）。"""
    out = []
    for t in text.replace(",", " ").replace("，", " ").replace(";", " ").replace("；", " ").split():
        t = "." + t.strip().lstrip(".").lower()
        if len(t) > 1 and t not in out:
            out.append(t)
    return out


def parse_keywords(text):
    """“护照, Passport；I-20、签证” → ["护照", "passport", "i-20", "签证"]。关键词里可以有空格（如 green card）。"""
    out = []
    for t in re.split(r"[,，;；、\n]+", text or ""):
        t = " ".join(t.split()).lower()
        if t and t not in out:
            out.append(t)
    return out


def _kw_pattern(kw):
    """英文 / 数字关键词按“整词”匹配，避免 opt 误中 adopt；中文按包含匹配。
    文件名里的 _ - . 空格 都视为分隔符，所以 green card 也能匹配 green_card、Green-Card。"""
    if kw.isascii():
        body = r"[\s_.\-]*".join(re.escape(p) for p in re.split(r"[\s_.\-]+", kw) if p)
        # 4 个字母以上的词允许后面直接跟数字（lecture3、invoice2024）；cv、opt 这类短词严格整词，cv2 不算
        tail = r"(?![a-z])" if len(kw) >= 4 and kw[-1].isalpha() else r"(?![a-z0-9])"
        return re.compile(r"(?<![a-z0-9])" + body + tail)
    return re.compile(re.escape(kw))


def validate_rules(rows):
    """rows: [(分类名, 扩展名文本[, 关键词文本]), ...]。
    返回 (规范化后的 [[名, ".a .b"]] 或带关键词的 [[名, ".a", "kw1, kw2"]], 错误信息)。
    只填关键词不填扩展名 = 任意类型的文件，只要文件名含关键词就归入该分类。"""
    out, seen = [], set()
    for row in rows:
        if not isinstance(row, (list, tuple)) or len(row) not in (2, 3) or not all(isinstance(x, str) for x in row):
            return None, "分类规则格式不正确"
        name, exts = row[0].strip(), row[1]
        kws = parse_keywords(row[2]) if len(row) == 3 else []
        if not name:
            return None, "分类名不能为空"
        err = bad_filename(name)
        if err:
            return None, f"分类名“{name}”不可用：{err}"
        if name in RESERVED_CATS:
            return None, f"“{name}”是保留名称，请换一个"
        if name.lower() in seen:
            return None, f"分类“{name}”重复了"
        seen.add(name.lower())
        e = parse_exts(exts)
        if not e and not kws:
            return None, f"分类“{name}”需要填写扩展名或关键词（至少一种）"
        out.append([name, " ".join(e), ", ".join(kws)] if kws else [name, " ".join(e)])
    if not out:
        return None, "至少保留一个分类"
    return out, ""


class RuleSet:
    """一套编译好的分类规则（分类列表、扩展名映射、关键词）。
    主文件夹用 PRIMARY；其他文件夹可以选用自己的“规则方案”，彼此独立。"""

    def __init__(self, rules=None, name=""):
        self.name = name
        norm, self.err = validate_rules(rules) if rules else (None, "")
        self.keywords, self.kw_text, self.ext_map = [], {}, {}
        if norm is None:
            self.rules = list(DEFAULT_RULES)
        else:
            self.rules = [(r[0], DEFAULT_GLYPH.get(r[0], FOLDER_GLYPH), r[1]) for r in norm]
            for r in norm:
                if len(r) == 3:
                    self.kw_text[r[0]] = r[2]
                    self.keywords.append((r[0], set(r[1].split()), [_kw_pattern(k) for k in parse_keywords(r[2])]))
        self.cats = [r[0] for r in self.rules] + [OTHER]
        kw_names = {k[0] for k in self.keywords}
        for n, _, exts in reversed(self.rules):   # 同一扩展名出现在多个分类时，排在前面的优先
            if n in kw_names:
                continue                          # 关键词分类的扩展名只是“附加条件”，不单独按扩展名匹配
            for e in exts.split():
                self.ext_map[e] = n

    def category_for(self, filename):
        """文件应归入的分类：先看关键词分类（按规则顺序），再按扩展名。"""
        base, ext = os.path.splitext(filename)
        ext = ext.lower()
        low = base.lower()
        for n, exts, pats in self.keywords:
            if exts and ext not in exts:
                continue
            if any(p.search(low) for p in pats):
                return n
        return self.ext_map.get(ext, OTHER)

    def rows(self):
        """[[分类名, 扩展名(, 关键词)]]：编辑器显示、导出用。"""
        return [[n, e, self.kw_text[n]] if n in self.kw_text else [n, e] for n, _, e in self.rules]


RULES_FILE_FORMAT = "DownloadButler.rules"


def read_rules_file(path):
    """读取导出的规则文件，返回 (规范化后的规则, 建议名称, 错误信息)。
    也接受直接是 [[分类名, 扩展名, 关键词], ...] 的列表。"""
    try:
        with open(path, encoding="utf-8-sig") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        return None, "", f"文件无法读取（{e}）"
    name = os.path.splitext(os.path.basename(path))[0]
    if isinstance(data, dict):
        if isinstance(data.get("name"), str) and data["name"].strip():
            name = data["name"].strip()[:40]
        data = data.get("rules")
    if not isinstance(data, list):
        return None, "", "不是分类规则文件"
    norm, err = validate_rules([tuple(r) if isinstance(r, list) else r for r in data])
    if err:
        return None, "", err
    return norm, name, ""


PRIMARY_SCHEME = "主文件夹规则"          # 主文件夹使用的规则（就是设置里原来的那一套）
PRIMARY = None
SCHEMES = {}                              # 其他规则方案：名称 → RuleSet


def apply_rules(rules):
    """让主文件夹的分类规则生效；rules 为空或不合法时使用内置规则。返回错误信息（合法时为空）。"""
    global PRIMARY
    PRIMARY = RuleSet(rules, PRIMARY_SCHEME)
    RULES[:] = PRIMARY.rules
    CATS[:] = PRIMARY.cats
    KEYWORDS[:] = PRIMARY.keywords
    KW_TEXT.clear()
    KW_TEXT.update(PRIMARY.kw_text)
    EXT_MAP.clear()
    EXT_MAP.update(PRIMARY.ext_map)
    rebuild_glyphs()
    return PRIMARY.err


def apply_schemes(cfg):
    """让配置里的其他规则方案生效。"""
    SCHEMES.clear()
    for sc in cfg.get("schemes") or []:
        SCHEMES[sc["name"]] = RuleSet(sc["rules"], sc["name"])
    rebuild_glyphs()


def rebuild_glyphs():
    GLYPH.clear()
    GLYPH.update({c: DEFAULT_GLYPH.get(c, FOLDER_GLYPH) for c in all_cats()})
    GLYPH.update({k: DEFAULT_GLYPH[k] for k in RESERVED_CATS})


def ruleset_for(root=None):
    """某个管理的文件夹使用的规则：主文件夹 → PRIMARY；其他文件夹 → 它选的方案（没选就跟主文件夹一样）。"""
    if not root or root == ROOT:
        return PRIMARY
    f = next((x for x in EXTRA if x["path"] == root), None) or extra_cfg(root)
    if f is not None and f.get("scheme") in SCHEMES:
        return SCHEMES[f["scheme"]]
    return PRIMARY


def cats_for(root=None):
    return ruleset_for(root).cats


def root_cats(root):
    """扫描 / 清理空文件夹时要看的分类文件夹：主文件夹只看规则里的分类；
    其他文件夹的“已整理”是下载管家专用的，里面的子文件夹都算（包括换规则方案之前的旧分类）。"""
    cats = list(cats_for(root))
    if root != ROOT:
        try:
            with os.scandir(cat_base(root)) as it:
                cats += [e.name for e in it if e.is_dir(follow_symlinks=False) and e.name not in cats
                         and not e.name.startswith(TEMP_PREFIX)]
        except OSError:
            pass
    return cats


def all_cats():
    """所有管理的文件夹里用到的分类（主文件夹的在前），“其他文件”放最后。"""
    out = list(CATS[:-1])
    for f in EXTRA:
        for c in cats_for(f["path"])[:-1]:
            if c not in out:
                out.append(c)
    return out + [OTHER]


# 常用的“按主题”分类模板（关键词分类：文件名含关键词即归入，不论类型；可在设置里修改）
PRESETS = [
    ("移民身份文件", "", "护照, passport, 签证, visa, 绿卡, green card, 移民, 身份, 居留, residence permit, "
                       "i-20, i20, i-94, i94, i-797, i797, i-765, i-485, i-130, i-140, ds-160, ds160, ds-2019, "
                       "sevis, ead, uscis, h-1b, h1b, f-1, opt, cpt, 出生证明, birth certificate, 户口, 身份证"),
    ("工作文件", "", "offer, 录用, 简历, resume, cv, 合同, contract, 劳动合同, nda, 入职, onboarding, 离职, "
                    "工资, 薪资, payslip, paystub, 工作证明, employment, 周报, 月报, 会议纪要, 述职"),
    ("财务票据", "", "发票, invoice, 收据, receipt, 账单, 对账单, 报销, 税, tax, w-2, w2, 1099, "
                    "1040, 银行, bank, 保险, insurance, 房租, lease, 租房"),
    ("学习资料", "", "课程, course, 讲义, lecture, 作业, homework, assignment, 论文, thesis, 成绩单, "
                    "transcript, syllabus, 考试, exam, 笔记, 学位, diploma"),
]


def category_for(filename, root=None):
    """文件应归入的分类（按 root 所在文件夹使用的规则）。"""
    return ruleset_for(root).category_for(filename)


def _norm(p):
    return os.path.normcase(os.path.realpath(p)).rstrip("\\/")


def root_problem(path):
    """检查一个文件夹能否作为“管理的文件夹”；可以时返回空字符串。"""
    if not path or not os.path.isdir(path):
        return "文件夹不存在"
    try:
        if is_reparse(os.lstat(path)):
            return "不能选择符号链接或目录联接"
    except OSError:
        return "无法访问该文件夹"
    p = _norm(path)
    if len(p) <= 3 or p.startswith("\\\\") and p.count("\\") <= 4:   # C:\ 或 \\server\share 根
        return "不能选择整个磁盘（或网络共享）的根目录"
    env = os.environ
    home = _norm(env["USERPROFILE"]) if env.get("USERPROFILE") else None
    if p == home:
        return "不能选择用户主目录本身，请选择其中的某个文件夹"
    for k in ("SystemRoot", "WINDIR", "ProgramFiles", "ProgramFiles(x86)", "ProgramData", "APPDATA", "LOCALAPPDATA"):
        if env.get(k):
            d = _norm(env[k])
            if p == d or p.startswith(d + os.sep):
                return "不能选择系统、程序或应用数据目录"
    return ""


APP_DIR_HINTS = {"steamapps", "steamlibrary", "epic games", "riot games", "battle.net", "origin games", "ea games",
                 "ubisoft", "gog games", "xboxgames", "windowsapps", "$recycle.bin", "system volume information",
                 "node_modules", ".git", "virtualbox vms", "hyper-v", "wsl"}


def extra_problem(path, others=()):
    """检查一个文件夹能否加入“其他管理的文件夹”；可以时返回空字符串。
    比主文件夹更严格：不允许程序 / 游戏 / 项目目录、云盘根目录、与已管理的文件夹重叠。"""
    err = root_problem(path)
    if err:
        return err
    p = _norm(path)
    parts = {x.lower() for x in p.split(os.sep)}
    if parts & APP_DIR_HINTS:
        return "这个位置属于游戏库、程序、代码项目或系统目录，整理会让程序找不到文件"
    for k in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial"):
        if os.environ.get(k) and p == _norm(os.environ[k]):
            return "不能选择整个 OneDrive，请选择其中的某个文件夹（如“桌面”）"
    try:
        names = {x.lower() for x in os.listdir(path)}
    except OSError:
        return "无法访问该文件夹"
    if is_project_dir(names) or names & {"steam.dll", "steam_appid.txt", "unins000.exe", "uninstall.exe"}:
        return "这个文件夹看起来是程序、游戏或代码项目，整理会让它无法正常运行"
    for o in [ROOT] + list(others):
        n = _norm(o)
        if p == n or p.startswith(n + os.sep) or n.startswith(p + os.sep):
            return f"和已经管理的文件夹重叠：{o}"
    return ""


def resolve_root(cfg):
    p = cfg.get("root") or ""
    if p and not root_problem(p):
        return os.path.abspath(p)
    return downloads_dir()


apply_rules([])


class SHFILEOPSTRUCTW(ctypes.Structure):
    _fields_ = [("hwnd", wintypes.HWND), ("wFunc", wintypes.UINT), ("pFrom", ctypes.c_void_p), ("pTo", ctypes.c_void_p),
                ("fFlags", ctypes.c_ushort), ("fAnyOperationsAborted", wintypes.BOOL), ("hNameMappings", ctypes.c_void_p),
                ("lpszProgressTitle", wintypes.LPCWSTR)]


def recycle(paths):
    """移到回收站（可还原）。
    文件放不进回收站时（太大 / 网络盘 / 回收站被关闭），Windows 默认会直接永久删除；
    这里加 WANTNUKEWARNING，让系统先弹窗确认，绝不静默永久删除。"""
    if not paths:
        return
    buf = ctypes.create_unicode_buffer("\0".join(os.path.abspath(p) for p in paths) + "\0\0")
    op = SHFILEOPSTRUCTW()
    op.wFunc = 3                              # FO_DELETE
    op.pFrom = ctypes.cast(buf, ctypes.c_void_p)
    # ALLOWUNDO | NOCONFIRMATION | NOERRORUI | SILENT | WANTNUKEWARNING
    op.fFlags = 0x0040 | 0x0010 | 0x0400 | 0x0004 | 0x4000
    r = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    if r:
        raise OSError(f"删除失败（代码 {r}）")
    if op.fAnyOperationsAborted:
        raise OSError("删除已取消")


def _volume_guid(path):
    buf = ctypes.create_unicode_buffer(260)
    mount = ctypes.create_unicode_buffer(260)
    if not ctypes.windll.kernel32.GetVolumePathNameW(os.path.abspath(path), mount, 260):
        return None, None
    if not ctypes.windll.kernel32.GetVolumeNameForVolumeMountPointW(mount.value, buf, 260):
        return mount.value, None
    v = buf.value                              # \\?\Volume{GUID}\
    i, j = v.find("{"), v.find("}")
    return mount.value, (v[i:j + 1] if 0 <= i < j else None)


def recycle_limit(path):
    """该文件所在卷的回收站能容纳的单个文件上限（字节）；返回 0 表示这个位置没有回收站。"""
    try:
        mount, guid = _volume_guid(path)
        if not mount or ctypes.windll.kernel32.GetDriveTypeW(mount) != 3:   # 只有本地固定磁盘有回收站
            return 0
        total = shutil.disk_usage(mount).total
        if guid:
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                    r"Software\Microsoft\Windows\CurrentVersion\Explorer\BitBucket\Volume\\" + guid) as k:
                    try:
                        if winreg.QueryValueEx(k, "NukeOnDelete")[0]:
                            return 0
                    except OSError:
                        pass
                    try:
                        return int(winreg.QueryValueEx(k, "MaxCapacity")[0]) * MB
                    except OSError:
                        pass
            except OSError:
                pass
        return total // 20                     # 没有记录时按系统默认的约 5% 保守估计
    except Exception:
        return 0


def can_recycle(path, size):
    lim = recycle_limit(path)
    return lim > 0 and size < lim


def recycle_old(path):
    """解压“覆盖”时处理旧文件：移到回收站；放不进回收站时返回 False（改为自动重命名，绝不永久删除）。"""
    try:
        if not can_recycle(path, os.path.getsize(path)):
            return False
        recycle([path])
        return True
    except OSError:
        return False


FILE_ATTRIBUTE_REPARSE_POINT = 0x400


def is_reparse(st):
    """符号链接 / 目录联接（junction）等重解析点。"""
    return bool(getattr(st, "st_file_attributes", 0) & FILE_ATTRIBUTE_REPARSE_POINT)


def inside_managed(path):
    """真实路径必须位于某个分类文件夹之内，防止通过联接 / 链接删到下载文件夹以外。"""
    try:
        real = os.path.normcase(os.path.realpath(path))
        st = os.lstat(path)
    except OSError:
        return False
    if is_reparse(st):
        return False
    for r in roots():
        for c in root_cats(r):
            base = os.path.normcase(os.path.realpath(os.path.join(cat_base(r), c)))
            if real.startswith(base + os.sep):
                return True
    return False


RESERVED_NAMES = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}


def bad_filename(name):
    """返回文件名不合法的原因；合法时返回空字符串。"""
    if any(ch in name for ch in '\\/:*?"<>|') or any(ord(ch) < 32 for ch in name):
        return "文件名不能包含 \\ / : * ? \" < > | 或控制字符"
    if name != name.rstrip(". "):
        return "文件名不能以空格或句点结尾"
    if name.split(".")[0].strip().upper() in RESERVED_NAMES:
        return "这是 Windows 保留的设备名，不能用作文件名"
    if len(name) > 255:
        return "文件名太长（最多 255 个字符）"
    return ""


def shell_verb_ok(path, verb):
    """这种文件有没有注册“print / printto”命令（由打开它的程序提供，如 Acrobat、Word、记事本、照片查看器）。"""
    ext = os.path.splitext(path)[1]
    if not ext:
        return False
    f = ctypes.windll.shlwapi.AssocQueryStringW
    f.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPWSTR,
                  ctypes.POINTER(wintypes.DWORD)]
    buf = ctypes.create_unicode_buffer(2048)
    n = wintypes.DWORD(2048)
    # 0x400 = ASSOCF_INIT_IGNOREUNKNOWN（未知类型不当作支持）；1 = ASSOCSTR_COMMAND
    return f(0x400, 1, ext, verb, buf, ctypes.byref(n)) == 0 and bool(buf.value)


def shell_print(path, printer=None):
    """交给文件关联的程序打印：不指定打印机时用默认打印机。返回是否成功启动。"""
    se = ctypes.windll.shell32.ShellExecuteW
    se.argtypes = [wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.c_int]
    se.restype = ctypes.c_void_p
    verb, params = ("printto", f'"{printer}"') if printer else ("print", None)
    r = se(None, verb, path, params, os.path.dirname(path), 1)
    return (r or 0) > 32


def reveal_in_explorer(path):
    """在资源管理器中定位文件。直接调用 Shell API，不经过命令行拼接，路径里的特殊字符不会被误解析。"""
    try:
        sh = ctypes.windll.shell32
        sh.ILCreateFromPathW.restype = ctypes.c_void_p
        sh.ILCreateFromPathW.argtypes = (wintypes.LPCWSTR,)
        sh.SHOpenFolderAndSelectItems.argtypes = (ctypes.c_void_p, wintypes.UINT, ctypes.c_void_p, wintypes.DWORD)
        sh.ILFree.argtypes = (ctypes.c_void_p,)
        ctypes.windll.ole32.CoInitialize(None)
        pidl = sh.ILCreateFromPathW(os.path.abspath(path))
        if pidl:
            try:
                if sh.SHOpenFolderAndSelectItems(pidl, 0, None, 0) == 0:
                    return
            finally:
                sh.ILFree(pidl)
    except Exception:
        pass
    subprocess.Popen(["explorer.exe", "/select,", os.path.abspath(path)])


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


def sanitize_cfg(raw):
    """逐项校验类型与范围；不合法的值回退到默认值，避免手改配置导致大量误删。"""
    c = dict(DEFAULTS)
    if not isinstance(raw, dict):
        return c
    for k, dv in DEFAULTS.items():
        if k not in raw:
            continue
        v = raw[k]
        if isinstance(dv, bool):
            if isinstance(v, bool):
                c[k] = v
        elif isinstance(dv, (int, float)):
            if isinstance(v, (int, float)) and not isinstance(v, bool) and v == v:
                c[k] = type(dv)(v)
        elif isinstance(dv, str):
            if isinstance(v, str):
                c[k] = v
        elif isinstance(dv, list):
            if isinstance(v, list) and all(isinstance(x, str) for x in v):
                c[k] = list(v)
    c["clean_days"] = min(max(int(c["clean_days"]), 1), 3650)
    if c["side_mode"] not in SIDE_MODES:
        c["side_mode"] = "open"
    if "side_mode" not in raw:             # 旧版只有“展开 / 收起”：沿用原来的状态
        c["side_mode"] = "open" if c["side_open"] else "closed"
    c["recent_days"] = min(RECENT_OPTIONS, key=lambda d: abs(d - int(c["recent_days"])))
    c["cap_gb"] = min(max(float(c["cap_gb"]), 0.5), 10000.0)
    c["settle_sec"] = min(max(int(c["settle_sec"]), 3), 600)
    if isinstance(raw.get("rules"), list):
        norm, _ = validate_rules(raw["rules"])
        c["rules"] = norm or []            # 不合法时回到内置规则
    if c["root"] and root_problem(c["root"]):
        c["root"] = ""                     # 文件夹不可用时回到系统“下载”文件夹
    for k in ("bg_vis", "card_alpha", "win_opacity"):
        c[k] = min(max(int(c[k]), 0), 100)
    if c["theme"] not in BASE_THEMES:
        c["theme"] = DEFAULTS["theme"]
    if c["close"] not in ("tray", "quit"):
        c["close"] = DEFAULTS["close"]
    # 规则方案：名称不能重复、不能和“主文件夹规则”同名，规则不合法的方案丢弃
    schemes, seen = [], {PRIMARY_SCHEME.lower()}
    if isinstance(raw.get("schemes"), list):
        for sc in raw["schemes"]:
            if isinstance(sc, dict) and isinstance(sc.get("name"), str) and isinstance(sc.get("rules"), list):
                n = sc["name"].strip()[:40]
                norm, _ = validate_rules(sc["rules"])
                if n and norm and n.lower() not in seen:
                    seen.add(n.lower())
                    schemes.append(dict(name=n, rules=norm))
    c["schemes"] = schemes
    names_ok = {x["name"] for x in schemes}
    folders = []
    if isinstance(raw.get("folders"), list):
        for f in raw["folders"]:
            if isinstance(f, dict) and isinstance(f.get("path"), str) and f["path"].strip():
                added = f.get("added")
                folders.append(dict(path=os.path.abspath(f["path"]), auto=f.get("auto") is not False,
                                    clean=f.get("clean") is True,
                                    added=float(added) if isinstance(added, (int, float)) and not isinstance(added, bool)
                                    else time.time(),
                                    scheme=f.get("scheme") if f.get("scheme") in names_ok else ""))
    c["folders"] = folders
    names = [r[0] for r in c["rules"]] if c["rules"] else [r[0] for r in DEFAULT_RULES]
    names += [r[0] for sc in schemes for r in sc["rules"]]
    c["protect"] = [p for p in c["protect"] if p in names + [OTHER]]
    for k, options in (("zip_fmt", [(f, 0) for f, _, _ in archive.FORMATS]), ("zip_level", archive.LEVELS),
                       ("zip_method", ZIP_METHODS), ("unzip_mode", UNZIP_MODES), ("unzip_overwrite", OVERWRITE_MODES)):
        if c[k] not in [o[0] for o in options]:
            c[k] = DEFAULTS[k]
    # 保留未知键（新版本写入的设置），降级再升级时不丢
    for k, v in raw.items():
        if k not in DEFAULTS:
            c[k] = v
    return c


def load_cfg():
    try:
        with open(CFG_PATH, encoding="utf-8") as f:
            raw = json.load(f)
    except FileNotFoundError:
        return dict(DEFAULTS)
    except (OSError, ValueError):
        # 配置损坏：先备份，避免下次保存时把用户原来的设置覆盖掉
        try:
            os.replace(CFG_PATH, CFG_PATH + datetime.now().strftime(".bad-%Y%m%d-%H%M%S"))
        except OSError:
            pass
        log("配置文件损坏，已备份并使用默认设置")
        return dict(DEFAULTS)
    return sanitize_cfg(raw)


def init_settings(cfg):
    """启动时让“分类规则 / 管理的文件夹 / 年-月子文件夹”设置生效。"""
    global ROOT, BY_MONTH
    apply_rules(cfg.get("rules"))
    ROOT = resolve_root(cfg)
    BY_MONTH = bool(cfg.get("by_month", True))
    apply_folders(cfg)
    apply_schemes(cfg)


def apply_folders(cfg):
    """让“其他管理的文件夹”和“不整理的文件类型”设置生效。看起来是程序 / 项目的文件夹不会被整理。"""
    EXTRA[:] = [dict(f) for f in cfg.get("folders", [])
                if not os.path.isdir(f["path"]) or not extra_problem(f["path"])]   # 未连接的移动硬盘先保留
    EXTRA_SKIP.clear()
    EXTRA_SKIP.update(e if e.startswith(".") else "." + e
                      for e in (cfg.get("extra_skip") or DEFAULT_EXTRA_SKIP).lower().replace(",", " ").split())


def save_cfg(c):
    """原子写入：先写临时文件再替换，写到一半崩溃也不会损坏配置。"""
    os.makedirs(CFG_DIR, exist_ok=True)
    tmp = CFG_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(c, f, ensure_ascii=False, indent=1)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, CFG_PATH)


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
LOG_LOCK = threading.Lock()


def log(msg):
    with LOG_LOCK:             # 清理在后台线程运行，也会写日志
        LOGS.insert(0, datetime.now().strftime("%m-%d %H:%M:%S") + "  " + msg)
        del LOGS[300:]


def category_of(ext):
    return EXT_MAP.get(ext, OTHER)


def cat_dir(cat, mtime, root=None):
    """文件在分类下的目标文件夹：按设置决定是否再分“年-月”子文件夹。"""
    d = os.path.join(cat_base(root or ROOT), cat)
    return os.path.join(d, datetime.fromtimestamp(mtime).strftime("%Y-%m")) if BY_MONTH else d


def free_path(d, name):
    dest = os.path.join(d, name)
    base, ext = os.path.splitext(name)
    i = 1
    while os.path.exists(dest):
        dest = os.path.join(d, f"{base} ({i}){ext}")
        i += 1
    return dest


def is_partial(name, names):
    """是否是未下载完的文件：本身是临时文件，或旁边还有同名的临时 / 控制文件
    （Firefox 先放 0 字节占位文件 + .part；aria2 / 迅雷的控制文件与目标文件并存）。"""
    low = name.lower()
    if os.path.splitext(low)[1] in SKIP_EXT or low.endswith(SKIP_SUFFIX):
        return True
    return any(low + s in names for s in COMPANION_EXT)


def organize(settle=None, loose_dirs=False, label="自动整理"):
    """整理主文件夹和其他文件夹里的新文件。返回 (已移动的文件名, 多少秒后需要重试 或 None)。
    仍在下载的文件不需要定时重试：下载完成改名时文件夹监视会再次触发整理；
    只有“刚到达、还没稳定”或“被占用”的文件才安排重试。
    loose_dirs=True 时，根目录里散落的文件夹（解压出来的、软件导出的）也会按其主要内容整个归入分类。
    每次移动都记入移动记录（同一次整理为一批），可以一键撤销。"""
    settle = DEFAULTS["settle_sec"] if settle is None else settle
    moved, retry = [], None
    batch = journal.batch(label)
    keep = journal.no_auto()

    def later(sec):
        nonlocal retry
        retry = sec if retry is None else min(retry, sec)
    for f in EXTRA:
        if f.get("auto", True):
            m, r = organize_extra(f, settle, batch, keep)
            moved += m
            if r is not None:
                later(r)
    try:
        entries = list(os.scandir(ROOT))
    except OSError:
        return moved, retry
    names = {e.name.lower() for e in entries}
    now = time.time()
    cat_names = {c.lower() for c in CATS}
    for e in entries:
        try:
            if os.path.normcase(e.path) in keep:      # 撤销移回来的：不再自动整理
                continue
            if loose_dirs and e.is_dir(follow_symlinks=False) and e.name.lower() not in cat_names:
                r = organize_dir(e, now, settle, batch)
                if r is True:
                    moved.append(e.name + "\\")
                elif r:
                    later(r)
                continue
            if not e.is_file(follow_symlinks=False):
                continue
            st = e.stat(follow_symlinks=False)   # Windows 上 scandir 已带回属性，不会再次访问磁盘
            if st.st_file_attributes & 2 or is_reparse(st):
                continue
            if e.name.lower() in SKIP_NAMES or is_partial(e.name, names):
                continue
            age = now - arrived_time(st)
            if age < settle:                     # 刚下载完：留一会儿，浏览器的“打开 / 在文件夹中显示”还能找到它
                later(settle - age + 0.5)
                continue
            ext = os.path.splitext(e.name)[1].lower()
            cat = category_for(e.name)
            d = cat_dir(cat, st.st_mtime)
            os.makedirs(d, exist_ok=True)
            dst = free_path(d, e.name)
            os.rename(e.path, dst)                    # 文件仍被占用（下载中）时会失败，稍后重试
            batch.add(e.path, dst)
            log(f"整理：{e.name} → {cat}")
            moved.append(e.name)
        except OSError:
            later(3)
    return moved, retry


def extra_candidates(f, now, settle, keep, only_new=True):
    """其他文件夹最外层里可以整理的文件：[(DirEntry, stat, 分类)]，以及多少秒后需要重试。
    安全规则：只看最外层的普通文件，不进入任何子文件夹；跳过隐藏 / 系统文件、快捷方式和程序 / 配置 / 数据文件、
    “仅在线”的云盘文件、没下载完的文件、撤销移回的文件；only_new 时还跳过加入之前就在的文件；
    整个文件夹看起来像程序或代码项目时一个都不动。"""
    root = f["path"]
    out, retry = [], None
    try:
        entries = list(os.scandir(root))
    except OSError:
        return out, None                       # 未连接（移动硬盘拔出、网络断开）：跳过
    names = {e.name.lower() for e in entries}
    if is_project_dir(names):
        return out, None
    for e in entries:
        try:
            if not e.is_file(follow_symlinks=False) or e.name.startswith(TEMP_PREFIX):
                continue
            st = e.stat(follow_symlinks=False)
            attrs = getattr(st, "st_file_attributes", 0)
            if attrs & (2 | 4) or attrs & CLOUD_ATTRS or is_reparse(st):
                continue
            low = e.name.lower()
            if low in SKIP_NAMES or is_partial(e.name, names) or os.path.splitext(low)[1] in EXTRA_SKIP:
                continue
            if os.path.normcase(e.path) in keep:
                continue
            birth = getattr(st, "st_birthtime", None) or st.st_ctime
            if only_new and birth < f.get("added", 0):
                continue                       # 加入之前就在的文件：只有点“整理现有文件”并确认后才动
            age = now - max(birth, st.st_mtime)
            if age < settle:
                retry = settle - age + 0.5 if retry is None else min(retry, settle - age + 0.5)
                continue
            out.append((e, st, category_for(e.name, root)))
        except OSError:
            pass
    return out, retry


def organize_extra(f, settle, batch, keep):
    moved = []
    cands, retry = extra_candidates(f, time.time(), settle, keep)
    for e, st, cat in cands:
        try:
            d = cat_dir(cat, st.st_mtime, f["path"])
            os.makedirs(d, exist_ok=True)
            dst = free_path(d, e.name)
            os.rename(e.path, dst)
            batch.add(e.path, dst)
            log(f"整理：{e.name} → {os.path.basename(f['path'])}\\{EXTRA_SUB}\\{cat}")
            moved.append(e.name)
        except OSError:
            retry = 3 if retry is None else min(retry, 3)
    return moved, retry


DIR_SCAN_LIMIT = 5000      # 判断文件夹内容时最多看这么多个文件，避免超大文件夹拖慢整理


def dir_profile(path):
    """统计文件夹里的内容：返回 (各分类的字节数, 最新修改时间, 是否含未完成下载, 文件数)。不跟随链接 / 联接。"""
    sizes, newest, partial, n = {}, 0.0, False, 0
    stack = [path]
    while stack and n < DIR_SCAN_LIMIT:
        d = stack.pop()
        try:
            with os.scandir(d) as it:
                entries = list(it)
        except OSError:
            continue
        names = {x.name.lower() for x in entries}
        for x in entries:
            try:
                st = x.stat(follow_symlinks=False)
                if is_reparse(st):
                    continue
                newest = max(newest, st.st_mtime)
                if x.is_dir(follow_symlinks=False):
                    stack.append(x.path)
                    continue
                n += 1
                if is_partial(x.name, names):
                    partial = True
                if junk_reason(x.name, st, time.time()) is None:
                    c = category_for(x.name)
                    sizes[c] = sizes.get(c, 0) + max(st.st_size, 1)
            except OSError:
                pass
    return sizes, newest, partial, n


INSTALLER_NAMES = {"setup.exe", "set-up.exe", "install.exe", "installer.exe", "autorun.inf"}
APP_MARKERS = {"_internal", "unins000.exe", "uninstall.exe"}     # PyInstaller 打包的软件、已安装的程序


def _entries(d):
    try:
        with os.scandir(d) as it:
            return [(e.name.lower(), e.is_dir(follow_symlinks=False), e.path) for e in it]
    except OSError:
        return None


def dir_kind(path):
    """判断一个文件夹是什么：
    "app"       程序 / 绿色软件 / 代码项目：位置可能被快捷方式或其他程序引用，不搬动；
    "installer" 安装包（解压出来的驱动、软件安装程序）：归入“安装包”；
    None        普通文件夹：按里面占用空间最多的文件类型归类。
    只包着一个子文件夹的（如 win\\updream\\）会往里看，最多 3 层。"""
    ents = _entries(path)
    if ents is None:
        return None
    for _ in range(3):
        if len(ents) == 1 and ents[0][1]:
            sub = _entries(ents[0][2])
            if sub is None:
                break
            ents = sub
        else:
            break
    names = {n for n, _, _ in ents}
    if names & APP_MARKERS or names & PROJECT_DIR_MARKERS or names & PROJECT_FILE_MARKERS \
            or any(n.endswith(PROJECT_FILE_SUFFIX) for n in names):
        return "app"

    def has_installer(ns):
        return bool(ns & INSTALLER_NAMES) or any(n.endswith(".msi") for n in ns)
    if has_installer(names):
        return "installer"
    for _, is_dir, sub_path in ents:              # 安装程序放在下一层（如 BootUp\Setup.exe）
        if is_dir:
            sub = _entries(sub_path)
            if sub and has_installer({n for n, _, _ in sub}):
                return "installer"
    if is_project_dir(names):                     # 同时有 exe 和 dll：解压出来的绿色软件
        return "app"
    return None


def installer_cat(root=None):
    """安装包应归入的分类：规则里放 .msi / .exe 的那个分类（默认“安装包”）。"""
    rs = ruleset_for(root)
    return rs.ext_map.get(".msi") or rs.ext_map.get(".exe")


def dir_category(path, root=None):
    """整个文件夹应归入的分类；程序文件夹、空文件夹返回 None（不移动）。"""
    kind = dir_kind(path)
    if kind == "app":
        return None
    if kind == "installer" and installer_cat(root):
        return installer_cat(root)
    sizes = dir_profile(path)[0]
    return max(sizes, key=sizes.get) if sizes else None


def organize_dir(entry, now, settle, batch=None):
    """把根目录里一个散落的文件夹整个归入分类（按其中占用空间最多的文件类型）。
    返回 True=已移动，数字=多少秒后重试，None=跳过。"""
    st = entry.stat(follow_symlinks=False)
    if st.st_file_attributes & 2 or is_reparse(st) or entry.name.startswith((".", "$", "~")):
        return None
    kind = dir_kind(entry.path)
    if kind == "app":
        return None                            # 代码项目 / 绿色软件：位置可能被其他东西引用，不搬动
    sizes, newest, partial, n = dir_profile(entry.path)
    if partial:
        return None                            # 里面还有没下载完的文件：等它下载完，监视会再次触发
    wait = max(settle, 60)                     # 文件夹（如正在解压）多给一点时间
    if now - max(newest, arrived_time(st)) < wait:
        return wait - (now - max(newest, arrived_time(st))) + 1
    if not sizes:
        return None                            # 空文件夹或只有垃圾文件：交给“清理垃圾文件”
    cat = (installer_cat() if kind == "installer" else None) or max(sizes, key=sizes.get)
    d = cat_dir(cat, newest or st.st_mtime)
    os.makedirs(d, exist_ok=True)
    dst = free_path(d, entry.name)
    try:
        os.rename(entry.path, dst)
    except OSError:
        return 60                              # 文件夹正被某个程序使用：一分钟后再试
    if batch is not None:
        batch.add(entry.path, dst)
    log(f"整理文件夹：{entry.name}\\（{n} 个文件）→ {cat}")
    return True


def plan_reorganize(protect=()):
    """按当前规则找出“放错分类”的已整理文件。返回 [(路径, 现分类, 新分类)]。
    只看分类文件夹里直接存放（或在“年-月”子文件夹里）的文件；整个归档进来的文件夹保持完整，不拆散，
    只有安装包文件夹会整个挪到“安装包”。
    从受保护分类挪到不受保护分类的文件跳过，避免整理之后反而被自动清理。"""
    out = []
    protect = set(protect)
    for x in scan()[0]:
        if x["cat"] == "未整理" or (x["root"] == ROOT and x["cat"] not in CATS):
            continue
        rel = os.path.relpath(x["path"], os.path.join(cat_base(x["root"]), x["cat"])).split(os.sep)
        if len(rel) > 2 or (len(rel) == 2 and not re.fullmatch(r"\d{4}-\d{2}", rel[0])):
            continue
        if x.get("is_dir"):
            # 整个文件夹只在它是安装包时才挪（例如以前被放进“其他文件”的驱动安装包），整个挪、不拆散；
            # 其他文件夹保持原位，避免因为里面某个文件名含关键词就把整个文件夹搬走
            new = installer_cat(x["root"]) if dir_kind(x["path"]) == "installer" else None
            if new is None:
                continue
        else:
            new = category_for(x["name"], x["root"])
        if new != x["cat"] and not (x["cat"] in protect and new not in protect):
            out.append((x["path"], x["cat"], new))
    return out


# ---------------- 垃圾文件 ----------------
JUNK_NAMES = {"thumbs.db", "ehthumbs.db", "ehthumbs_vista.db", ".ds_store", ".localized"}
PARTIAL_JUNK_EXT = SKIP_EXT - {".tmp", ".temp", ".~tmp"}
DAY = 86400


def junk_reason(name, st, now):
    """判断单个文件是否是垃圾文件，返回原因；不是时返回 None。只认非常确定的类型。"""
    low = name.lower()
    ext = os.path.splitext(low)[1]
    age = now - st.st_mtime
    if low in JUNK_NAMES:
        return "系统缩略图 / 索引缓存（Thumbs.db 等）"
    if low.startswith("._") and st.st_size <= 4096:
        return "macOS 附带文件（._ 开头）"
    if low.startswith("~$") and st.st_size <= 4096 and age > DAY:
        return "Office 残留的临时锁文件（~$ 开头）"
    if ext in (".tmp", ".temp", ".~tmp") and age > DAY:
        return "过期的临时文件（.tmp）"
    if (ext in PARTIAL_JUNK_EXT or low.endswith(SKIP_SUFFIX)) and age > 7 * DAY:
        return "没下载完、7 天以上没有进展的残留"
    if st.st_size == 0 and age > DAY and low not in SKIP_NAMES:
        return "空文件（0 字节）"
    return None


_COPY_RE = re.compile(r"^(.*?)(?:\s?\(\d{1,3}\)|\s-\s(?:副本|copy)(?:\s\(\d{1,3}\))?|\s(?:copy|副本))$", re.I)


def _same_content(a, b, size):
    if size > 2 * 1024 ** 3:
        return False                           # 超大文件不做比对，不算重复
    h = []
    for p in (a, b):
        m = hashlib.sha256()
        with open(p, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                m.update(chunk)
        h.append(m.digest())
    return h[0] == h[1]


PROJECT_DIR_MARKERS = {".git", ".svn", ".hg", ".venv", "venv", "env", "node_modules", ".idea", ".vscode", ".gradle",
                       "site-packages", "__pycache__"}
PROJECT_FILE_MARKERS = {"package.json", "pyproject.toml", "setup.py", "setup.cfg", "requirements.txt", "pipfile",
                        "cargo.toml", "go.mod", "pom.xml", "build.gradle", "cmakelists.txt", "makefile", "gemfile",
                        "composer.json", "pubspec.yaml", ".gitignore"}
PROJECT_FILE_SUFFIX = (".sln", ".csproj", ".vcxproj", ".xcodeproj", ".uproject", ".pyproj")


def is_project_dir(names):
    """文件夹看起来是代码项目或程序目录：里面的空文件夹、0 字节文件往往是必需的结构，整个不碰。
    names 为该文件夹里条目名（小写）的集合。"""
    if names & PROJECT_DIR_MARKERS or names & PROJECT_FILE_MARKERS:
        return True
    if any(n.endswith(PROJECT_FILE_SUFFIX) for n in names):
        return True
    exts = {os.path.splitext(n)[1] for n in names}
    return ".dll" in exts and ".exe" in exts            # 解压出来的绿色软件


def find_junk(protect=(), stats=None):
    """扫描整个管理文件夹（含散落的子文件夹）里的垃圾文件。
    返回 [dict(path, size, reason)]；不删除任何东西，交给用户确认。
    - 代码项目 / 程序文件夹整个跳过（数量记在 stats["projects"]）。
    - “空文件夹”和“0 字节文件”只在管理文件夹本层、分类文件夹及其“年-月”子文件夹这几层判断，
      不深入用户自己的文件夹结构（那里的空目录可能是有意保留的）。
    - 重复副本只认“同一文件夹里、文件名带 (1) / 副本 / copy、内容与原文件完全相同”的那一份。"""
    now = time.time()
    out, empty_dirs = [], []
    stats = stats if stats is not None else {}
    stats.update(projects=0, files=0, dirs=0)
    cat_lower = {c.lower(): c for c in CATS}
    protect_lower = {c.lower() for c in protect}

    def walk(d, level, prot):
        """level：root / cat / month / other。返回该文件夹是否“完全为空”（没有任何文件，子文件夹也都为空）。"""
        stats["dirs"] += 1
        try:
            with os.scandir(d) as it:
                entries = []
                for e in it:
                    try:
                        entries.append((e, e.stat(follow_symlinks=False)))
                    except OSError:
                        pass
        except OSError:
            return False
        names = {e.name.lower() for e, _ in entries}
        if level == "other" and is_project_dir(names):
            stats["projects"] += 1
            return False
        structural = level in ("root", "cat", "month")     # 只有这几层允许判断空文件夹 / 空文件
        files = {e.name.lower(): (e, st) for e, st in entries
                 if not is_reparse(st) and e.is_file(follow_symlinks=False)}
        empty = True
        for e, st in entries:
            if is_reparse(st) or e.name.startswith(TEMP_PREFIX):
                empty = False
                continue
            low = e.name.lower()
            if e.is_dir(follow_symlinks=False):
                if low == "__macosx":
                    empty = False
                    out.append(dict(path=e.path, size=dir_size(e.path), reason="macOS 压缩包残留（__MACOSX 文件夹）"))
                    continue
                if level == "root" and low in cat_lower:
                    sub_level, sub_prot = "cat", low in protect_lower
                elif level == "cat" and re.fullmatch(r"\d{4}-\d{2}", e.name):
                    sub_level, sub_prot = "month", prot
                else:
                    sub_level, sub_prot = "other", prot
                sub_empty = walk(e.path, sub_level, sub_prot)
                if sub_empty and structural and sub_level != "cat" and not prot and now - st.st_mtime > DAY:
                    empty_dirs.append(e.path)
                if not sub_empty or sub_level == "cat":
                    empty = False
                continue
            empty = False
            stats["files"] += 1
            r = junk_reason(e.name, st, now)
            if r and r.startswith("空文件") and (prot or not structural):
                r = None
            if r is None and not prot and st.st_size > 0:
                base, ext = os.path.splitext(e.name)
                m = _COPY_RE.match(base)
                orig = files.get((m.group(1) + ext).lower()) if m and m.group(1) else None
                if orig and orig[0].path != e.path and orig[1].st_size == st.st_size:
                    try:
                        if _same_content(orig[0].path, e.path, st.st_size):
                            r = f"重复下载的副本（与“{orig[0].name}”内容完全相同）"
                    except OSError:
                        pass
            if r:
                out.append(dict(path=e.path, size=st.st_size, reason=r))
        return empty

    walk(ROOT, "root", False)
    out.extend(dict(path=p, size=0, reason="空文件夹") for p in empty_dirs)
    return out


def dir_size(path):
    total, stack = 0, [path]
    while stack:
        d = stack.pop()
        try:
            with os.scandir(d) as it:
                for e in it:
                    st = e.stat(follow_symlinks=False)
                    if is_reparse(st):
                        continue
                    if e.is_dir(follow_symlinks=False):
                        stack.append(e.path)
                    else:
                        total += st.st_size
        except OSError:
            pass
    return total


def inside_root(path):
    """真实路径位于管理文件夹之内（且本身不是链接 / 联接）。"""
    try:
        if is_reparse(os.lstat(path)):
            return False
        r = root_of(path)
        return r is not None and _norm(path) != _norm(r)
    except OSError:
        return False


def delete_junk(items):
    """把确认过的垃圾文件移入回收站。放不进回收站的跳过。返回 (删除数, 释放字节, 跳过数)。"""
    n, freed, skipped = 0, 0, 0
    limits, ok = {}, []
    for x in items:
        p = x["path"]
        drive = os.path.splitdrive(os.path.abspath(p))[0].lower()
        if drive not in limits:                       # 回收站容量按磁盘只查一次
            limits[drive] = recycle_limit(p)
        if not inside_root(p) or not (0 < x["size"] < limits[drive] or (x["size"] == 0 and limits[drive] > 0)):
            skipped += 1
            continue
        ok.append(x)

    def done(x):
        nonlocal n, freed
        n += 1
        freed += x["size"]
        log(f"清理垃圾：{os.path.relpath(x['path'], ROOT)}（{x['reason']}）")

    # 一次交给系统一批（逐个调用时每次都有几百毫秒开销）；某一批失败时再逐个处理，找出失败的那几个
    for i in range(0, len(ok), 200):
        chunk = ok[i:i + 200]
        try:
            recycle([x["path"] for x in chunk])
            for x in chunk:
                if os.path.lexists(x["path"]):
                    skipped += 1
                else:
                    done(x)
        except OSError:
            for x in chunk:
                if not os.path.lexists(x["path"]):
                    done(x)
                    continue
                try:
                    recycle([x["path"]])
                    done(x)
                except OSError:
                    skipped += 1
    remove_empty_dirs()
    return n, freed, skipped


# ---------------- 分析文件夹：哪些可以删、哪些可以理顺 ----------------
ARCHIVE_EXTS = (".zip", ".rar", ".7z", ".tar", ".gz", ".tgz", ".xz", ".bz2", ".iso")
OLD_DAYS = 365
BIG_OLD = 100 * 1024 ** 2
FOLDER_SCAN_CAP = 20000          # 超过这么多文件的文件夹不做逐个比对（重复 / 垃圾判断）


def _wrapper_chain(path):
    """文件夹里只套着一个子文件夹（可能多层）时，返回最里面那个有实际内容的文件夹；否则返回 None。"""
    cur, depth = path, 0
    while depth < 5:
        ents = _entries(cur)
        if not ents or len(ents) != 1 or not ents[0][1]:
            break
        cur = ents[0][2]
        depth += 1
    return cur if depth else None


def _folder_detail(path, now):
    """逐个看文件夹里的文件：签名（相对路径 + 大小，用来判断重复）、是否全是垃圾文件。"""
    sig, all_junk, n, stack = [], True, 0, [path]
    while stack:
        d = stack.pop()
        try:
            it = os.scandir(d)
        except OSError:
            return None, False
        with it:
            for e in it:
                try:
                    st = e.stat(follow_symlinks=False)
                    if is_reparse(st):
                        continue
                    if e.is_dir(follow_symlinks=False):
                        if e.name.lower() == "__macosx":
                            continue
                        stack.append(e.path)
                        continue
                    n += 1
                    if n > FOLDER_SCAN_CAP:
                        return None, False
                    sig.append((os.path.relpath(e.path, path).lower(), st.st_size))
                    if all_junk and not junk_reason(e.name, st, now):
                        all_junk = False
                except OSError:
                    pass
    return tuple(sorted(sig)), all_junk and n > 0


def analyze_dirs(protect=(), only=None):
    """分析整个归档进来的文件夹（列表里显示为一行的那些），给出建议。不改动任何东西。
    返回 [dict(path, name, root, cat, size, count, mtime, level, reason, action)]：
      level  "delete" 建议删除 / "maybe" 可以考虑删除 / "fix" 可以理顺 / "keep" 建议保留
      action "delete" / "move:<分类>" / "unwrap" / None
    同一个文件夹可能同时有“可以考虑删除”和“可以理顺”两条。only：只分析这些路径。"""
    now = time.time()
    protect = set(protect)
    items = scan()[0]
    folders = [x for x in items if x.get("is_dir")]
    if only is not None:
        want = {os.path.normcase(os.path.abspath(p)) for p in only}
        targets = [x for x in folders if os.path.normcase(os.path.abspath(x["path"])) in want]
    else:
        targets = folders
    # 同一管理文件夹里的压缩包（按名字，不含扩展名）：判断“解压出来的文件夹和压缩包都还在”
    archives = {}
    for x in items:
        if not x.get("is_dir"):
            low = x["name"].lower()
            for ext in ARCHIVE_EXTS:
                if low.endswith(ext):
                    archives.setdefault((x["root"], low[:-len(ext)].removesuffix(".tar")), x["name"])
                    break
    details = {}

    def detail(x):
        if x["path"] not in details:
            details[x["path"]] = _folder_detail(x["path"], now)
        return details[x["path"]]

    by_parent = {}
    for x in folders:
        by_parent.setdefault(os.path.dirname(x["path"]), []).append(x)
    out = []

    def add(x, level, reason, action=None):
        out.append(dict(path=x["path"], name=x["name"], root=x["root"], cat=x["cat"], size=x["size"],
                        count=x["count"], mtime=x["mtime"], level=level, reason=reason, action=action))

    for x in targets:
        age = (now - x["mtime"]) / DAY
        if x["cat"] in protect:
            add(x, "keep", f"在受保护的分类“{x['cat']}”里")
            continue
        if x["count"] == 0:
            add(x, "delete", "空文件夹：里面没有任何文件", "delete")
            continue
        kind = dir_kind(x["path"])
        if kind == "app":
            add(x, "keep", "程序 / 绿色软件 / 代码项目：可能正在使用（快捷方式或其他程序会找它），不建议删除或搬动")
            continue
        sig, all_junk = detail(x)
        if all_junk:
            add(x, "delete", "里面只有垃圾文件（临时文件、缩略图缓存、没下载完的残留等）", "delete")
            continue
        # 重复的副本：同一位置有“名字 (1)”这样的文件夹，里面的文件（相对路径和大小）完全一样
        m = _COPY_RE.match(x["name"])
        if m and m.group(1) and sig:
            orig = next((y for y in by_parent.get(os.path.dirname(x["path"]), ())
                         if y["name"].lower() == m.group(1).lower() and y["count"] == x["count"]
                         and y["size"] == x["size"]), None)
            if orig and detail(orig)[0] == sig:
                add(x, "delete", f"重复的副本：与“{orig['name']}”里的文件完全相同（文件名和大小一致）", "delete")
                continue
        suggested = False
        arch = archives.get((x["root"], x["name"].lower()))
        if arch:
            add(x, "maybe", f"同名压缩包“{arch}”还在：解压出来的文件夹和压缩包留一个即可", "delete")
            suggested = True
        if kind == "installer":
            if age > 30:
                add(x, "maybe", "安装包：软件 / 驱动装好以后一般用不到了，需要时可以重新下载", "delete")
                suggested = True
            target = installer_cat(x["root"])
            if target and target != x["cat"]:
                add(x, "fix", f"安装包放在了“{x['cat']}”里，移到“{target}”", "move:" + target)
                suggested = True
        elif not arch and age > OLD_DAYS and x["size"] >= BIG_OLD:
            add(x, "maybe", f"超过 {int(age // 365)} 年没有改动，占用 {human(x['size'])}", "delete")
            suggested = True
        inner = _wrapper_chain(x["path"])
        if inner and dir_kind(inner) != "app":
            add(x, "fix", f"多套了一层文件夹：把里面的“{os.path.basename(inner)}”提出来", "unwrap")
            suggested = True
        if not suggested:
            add(x, "keep", "普通文件夹，没有发现问题" if age <= OLD_DAYS else "没有发现问题（时间较久但占用不大）")
    order = {"delete": 0, "maybe": 1, "fix": 2, "keep": 3}
    out.sort(key=lambda a: (order[a["level"]], -a["size"]))
    return out


def unwrap_dir(path, batch=None):
    """去掉多余的一层：把最里面有内容的文件夹移到 path 所在的位置，删掉空下来的外层。记入移动记录。返回新路径。"""
    inner = _wrapper_chain(path)
    if not inner:
        raise OSError("不是只套着一个子文件夹")
    parent = os.path.dirname(path)
    tmp = free_path(parent, os.path.basename(inner) + " (提出)")
    shutil.move(inner, tmp)
    d = os.path.dirname(inner)
    while _norm(d) != _norm(parent):         # 外层都已空：从里往外删
        os.rmdir(d)
        d = os.path.dirname(d)
    new = free_path(parent, os.path.basename(inner))
    os.rename(tmp, new)
    (batch or journal.batch("去掉多余的一层文件夹")).add(inner, new)
    log(f"去掉多余的一层：{os.path.relpath(path, parent)} → {os.path.basename(new)}")
    return new


def apply_dir_actions(chosen):
    """执行确认过的建议。删除进回收站；移动 / 去掉一层记入移动记录（可以撤销）。
    返回 (删除数, 释放字节, 理顺数, [问题])。同一个文件夹既要删又要理顺时只删。"""
    dels = [a for a in chosen if a["action"] == "delete"]
    gone = {a["path"] for a in dels}
    problems = []
    n, freed, skipped = delete_junk([dict(path=a["path"], size=a["size"], reason=a["reason"]) for a in dels]) \
        if dels else (0, 0, 0)
    if skipped:
        problems.append(f"{skipped} 个文件夹无法放入回收站（太大或正在使用），已跳过")
    fixed = 0
    batch = journal.batch("分析文件夹：理顺")
    for a in chosen:
        if a["path"] in gone or not a["action"] or a["action"] == "delete":
            continue
        try:
            if a["action"] == "unwrap":
                unwrap_dir(a["path"], batch)
            elif a["action"].startswith("move:"):
                move_to(a["path"], a["action"][5:], batch)
            fixed += 1
        except OSError as e:
            problems.append(f"{a['name']}：{e.strerror or e}")
    remove_empty_dirs()
    return n, freed, fixed, problems


MONTH_RE = re.compile(r"\d{4}-\d{2}")


# ---------- 扫描缓存：只为“文件夹变化通知触发的刷新”加速 ----------
# 每个目录读到的内容按目录记下来；文件夹监视器报告某个目录有变化时，只丢掉这个目录（以及它的上级、下级）的记录，
# 其余没变的目录直接复用，几万个文件时刷新从几百毫秒降到几十毫秒。
# 用户自己的操作（删除、移动、重命名等）和打开窗口时照旧完整重新扫描；每 5 分钟也完整扫描一次兜底。
# FAT / exFAT（U 盘、部分移动硬盘）和网络位置不缓存：这些位置的变化通知不可靠。
_SCAN_CACHE = {}               # normcase(目录) → (文件条目, [("walk", 子目录) | ("item", 整个文件夹条目)])
_CACHEABLE = {}                # 管理的文件夹 → 是否允许缓存


def _cacheable(root):
    ok = _CACHEABLE.get(root)
    if ok is None:
        ok = False
        try:
            mount = ctypes.create_unicode_buffer(260)
            fs = ctypes.create_unicode_buffer(64)
            k32 = ctypes.windll.kernel32
            if k32.GetVolumePathNameW(os.path.abspath(root), mount, 260) and k32.GetDriveTypeW(mount) == 3 \
                    and k32.GetVolumeInformationW(mount, None, 0, None, None, None, fs, 64):
                ok = fs.value.upper() in ("NTFS", "REFS")
        except (OSError, AttributeError):
            ok = False
        _CACHEABLE[root] = ok
    return ok


def scan_invalidate(path=None):
    """丢掉扫描缓存：不给 path 时全部丢掉；给了就丢掉这个目录、它的上级和下级目录的记录。"""
    if path is None:
        _SCAN_CACHE.clear()
        return
    n = os.path.normcase(os.path.abspath(path)).rstrip("\\/")
    for k in list(_SCAN_CACHE):
        if k == n or n.startswith(k + os.sep) or k.startswith(n + os.sep):
            _SCAN_CACHE.pop(k, None)


def scan(group_dirs=True, use_cache=False):
    """列出所有文件，同时返回需要监视的文件夹。用 scandir 的缓存属性，避免逐个 stat。
    use_cache=True：没有变化通知的目录复用上次读到的内容（只有界面刷新这样用）。"""
    items, dirs = [], []
    for r in roots():
        dirs.append(r)
        _scan_root(r, items, dirs, group_dirs, use_cache and group_dirs and _cacheable(r))
    return items, dirs


def _dir_item(e, st, cat, root):
    """整个归档进来的文件夹作为列表里的一项：总大小、文件数、里面最新的修改时间；
    记下里面的文件名（最多 3000 个），搜索时也能按里面的文件名找到这个文件夹。"""
    size, n, newest, inner, stack = 0, 0, st.st_mtime, [], [e.path]
    while stack:
        try:
            it = os.scandir(stack.pop())
        except OSError:
            continue
        with it:
            for x in it:
                try:
                    xs = x.stat(follow_symlinks=False)
                    if is_reparse(xs):
                        continue
                    if x.is_dir(follow_symlinks=False):
                        stack.append(x.path)
                        continue
                    size += xs.st_size
                    n += 1
                    newest = max(newest, xs.st_mtime)
                    if len(inner) < 3000:
                        inner.append(x.name.lower())
                except OSError:
                    pass
    return dict(name=e.name, path=e.path, cat=cat, root=root, ext="", size=size, mtime=newest,
                arrived=arrived_time(st), cloud=False, is_dir=True, count=n, inner=inner)


def _file_item(e, st, cat, root):
    return dict(name=e.name, path=e.path, cat=cat, root=root, ext=os.path.splitext(e.name)[1].lower(),
                size=st.st_size, mtime=st.st_mtime, arrived=arrived_time(st),
                cloud=bool(getattr(st, "st_file_attributes", 0) & CLOUD_ATTRS))


def list_folder(path, cat, root):
    """一个文件夹里的直接内容（在应用内打开文件夹时显示）：文件逐个列出，子文件夹各算一行。"""
    items = []
    try:
        it = os.scandir(path)
    except OSError:
        return items
    with it:
        for e in it:
            try:
                if e.name.startswith(TEMP_PREFIX):
                    continue
                st = e.stat(follow_symlinks=False)
                if is_reparse(st):
                    continue
                if e.is_dir(follow_symlinks=False):
                    items.append(_dir_item(e, st, cat, root))
                elif e.is_file(follow_symlinks=False):
                    items.append(_file_item(e, st, cat, root))
            except OSError:
                pass
    return items


def _scan_root(root, items, dirs, group_dirs=True, use_cache=False):
    """group_dirs=True（界面用）：分类 / 年-月 文件夹里的子文件夹各算一项；
    False（自动清理用）：照旧逐个列出里面的文件。"""
    base = cat_base(root)
    if base != root and os.path.isdir(base):
        dirs.append(base)

    def walk(d, cat, level=0):
        dirs.append(d)
        key = os.path.normcase(d) if use_cache else None
        hit = _SCAN_CACHE.get(key) if key else None
        if hit is None:
            files, subs = [], []
            try:
                it = os.scandir(d)
            except OSError:
                return
            with it:
                for e in it:
                    try:
                        if e.name.startswith(TEMP_PREFIX):
                            continue
                        st = e.stat(follow_symlinks=False)
                        if is_reparse(st):          # 跳过符号链接和目录联接，不越出下载文件夹
                            continue
                        if e.is_dir(follow_symlinks=False):
                            if not group_dirs or (level == 0 and MONTH_RE.fullmatch(e.name)):
                                subs.append(("walk", e.path))
                            else:
                                subs.append(("item", _dir_item(e, st, cat, root)))
                        elif e.is_file(follow_symlinks=False):
                            files.append(_file_item(e, st, cat, root))
                    except OSError:
                        pass
            if key:
                _SCAN_CACHE[key] = (files, subs)
        else:
            files, subs = hit
        items.extend(files)
        for kind, v in subs:
            if kind == "walk":
                walk(v, cat, level + 1)
            else:
                items.append(v)

    for c in root_cats(root):
        p = os.path.join(base, c)
        try:
            if os.path.isdir(p) and not is_reparse(os.lstat(p)):
                walk(p, c)
        except OSError:
            pass
    # 最外层的文件列为“未整理”（其他文件夹里的也列出来，方便在主页按文件夹查看；只是显示，不会因此被整理）
    try:
        with os.scandir(root) as it:
            for e in it:
                if e.is_file(follow_symlinks=False) and not e.name.startswith(TEMP_PREFIX):
                    st = e.stat(follow_symlinks=False)
                    if not st.st_file_attributes & (2 if root == ROOT else 6) and not is_reparse(st) \
                            and e.name.lower() not in SKIP_NAMES:
                        items.append(dict(name=e.name, path=e.path, cat="未整理", root=root,
                                          ext=os.path.splitext(e.name)[1].lower(),
                                          size=st.st_size, mtime=st.st_mtime, arrived=arrived_time(st),
                                          cloud=bool(st.st_file_attributes & CLOUD_ATTRS)))
    except OSError:
        pass


def arrived_time(st):
    """文件落到这台电脑的时间。解压 / 部分下载工具会保留原始修改时间，
    只看修改时间会把刚下载的“老文件”当成旧文件清理掉；同卷移动不改变创建时间。"""
    birth = getattr(st, "st_birthtime", None)
    if birth is None:
        birth = st.st_ctime            # Windows 上 Python < 3.12 的 st_ctime 即创建时间
    return max(birth, st.st_mtime)


def remove_empty_dirs():
    """自底向上删除分类文件夹里的空子文件夹；不进入符号链接 / 目录联接。"""
    for c in [(r, c) for r in roots() for c in root_cats(r)]:
        base = os.path.join(cat_base(c[0]), c[1])
        try:
            if not os.path.isdir(base) or is_reparse(os.lstat(base)):
                continue
        except OSError:
            continue
        stack = []

        def collect(d):
            try:
                with os.scandir(d) as it:
                    for e in it:
                        if e.is_dir(follow_symlinks=False) and not e.name.startswith(TEMP_PREFIX) \
                                and not is_reparse(e.stat(follow_symlinks=False)):
                            stack.append(e.path)
                            collect(e.path)
            except OSError:
                pass
        collect(base)
        if c[0] != ROOT:
            stack.append(base)            # 其他文件夹里空掉的分类文件夹也删掉，不留痕迹
        for dp in sorted(stack, key=len, reverse=True):
            try:
                if not os.listdir(dp):
                    os.rmdir(dp)
            except OSError:
                pass
    for r in roots()[1:]:
        try:
            os.rmdir(cat_base(r))          # 只有空的时候才会成功
        except OSError:
            pass


def move_to(path, dest, batch=None):
    """移到分类（在文件所在的管理文件夹里）或任意文件夹；记入移动记录。返回新路径。"""
    name = os.path.basename(path)
    if not os.path.isabs(dest):
        d = cat_dir(dest, os.stat(path).st_mtime, root_of(path) or ROOT)
    else:
        d = dest
    os.makedirs(d, exist_ok=True)
    new = free_path(d, name)
    shutil.move(path, new)
    (batch or journal.batch("移动")).add(path, new)
    log(f"移动：{name} → {dest}")
    return new


def cleanup(cfg):
    """把符合规则的文件移到回收站。返回 (文件数, 释放字节数, 提示信息列表)。
    安全措施：只删分类文件夹内的普通文件；放不进回收站的文件跳过（绝不永久删除）；
    容量阈值无法达到时不删任何文件。"""
    cfg = sanitize_cfg(cfg)
    n, freed, notes, skipped = 0, 0, [], 0
    items = scan(group_dirs=False)[0]
    protect = set(cfg["protect"])
    # 其他文件夹默认不参与自动清理（桌面等位置的旧文件往往仍有用），只有勾选了“参与自动清理”的才算
    clean_roots = {ROOT} | {f["path"] for f in EXTRA if f.get("clean")}     # scan() 的 root 就是这些字符串本身
    items = [x for x in items if x.get("root", ROOT) in clean_roots]
    eligible = sorted((x for x in items if x["cat"] != "未整理" and x["cat"] not in protect),
                      key=lambda x: x["arrived"])
    gone = set()

    def remove(x):
        nonlocal n, freed, skipped
        if not inside_managed(x["path"]) or not can_recycle(x["path"], x["size"]):
            skipped += 1
            log(f"清理跳过（无法放入回收站或不在管理范围内）：{x['name']}")
            return False
        try:
            recycle([x["path"]])
        except OSError:
            skipped += 1
            return False
        n += 1; freed += x["size"]; gone.add(x["path"])
        log(f"清理：{x['name']}")
        return True

    if cfg["clean_on"]:
        cutoff = time.time() - cfg["clean_days"] * 86400
        for x in eligible:
            if x["arrived"] < cutoff:
                remove(x)
    if cfg["cap_on"]:
        cap = cfg["cap_gb"] * 1024 ** 3
        total = sum(x["size"] for x in items if x["path"] not in gone)
        rest = [x for x in eligible if x["path"] not in gone]
        fixed = total - sum(x["size"] for x in rest)    # 受保护 / 未整理的文件，不会被删除
        if total > cap and fixed >= cap:
            # 就算把可清理的文件全删掉也降不到阈值以下：一个都不删，提醒用户
            msg = (f"受保护和未整理的文件已有 {human(fixed)}，超过容量阈值 {cfg['cap_gb']:g} GB，"
                   f"已跳过容量清理，请调高阈值或减少受保护分类")
            log(msg); notes.append(msg)
        else:
            for x in rest:
                if total <= cap:
                    break
                if remove(x):
                    total -= x["size"]
    remove_empty_dirs()
    if skipped:
        notes.append(f"{skipped} 个文件无法放入回收站，已跳过（不会被永久删除）")
    log(f"清理：{n} 个文件进回收站，释放 {human(freed)}" + (f"，跳过 {skipped} 个" if skipped else ""))
    return n, freed, notes


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
            self.setToolTip(getattr(self, "tip", None) or
                            self.text_ + (f"（{self.count}）" if self.count is not None else ""))
            return
        self.setToolTip(getattr(self, "tip", None) or "")
        f = self.font()
        f.setPixelSize(13)
        f.setBold(on)
        p.setFont(f)
        right = 8
        trail = getattr(self, "trail", None)
        if trail:
            p.setFont(icon_font(10))
            p.drawText(QRectF(self.width() - 26, 0, 18, self.height()), Qt.AlignmentFlag.AlignCenter, trail)
            p.setFont(f)
            right = 28
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


class RecentButton(SideButton):
    """左侧顶部单独的“最近添加”卡片：强调色底、两行文字（名称 + 时间范围）、数量徽标。"""
    def __init__(self):
        super().__init__("\ue823", RECENT)
        self.setObjectName("recentBtn")
        self.setCheckable(True)
        self.days = RECENT_DAYS
        self.setFixedHeight(52)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        on, hover = self.isChecked(), self.underMouse()
        acc = QColor(C("accent"))
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        if on:
            p.setBrush(acc)
            p.setPen(Qt.PenStyle.NoPen)
        else:
            bg = QColor(acc)
            bg.setAlpha(46 if hover else 26)
            line = QColor(acc)
            line.setAlpha(150 if hover else 90)
            p.setBrush(bg)
            p.setPen(QPen(line, 1))
        p.drawRoundedRect(r, 10, 10)
        fg = QColor("white") if on else acc
        p.setFont(icon_font(18))
        p.setPen(fg)
        if not self.expanded:
            p.drawText(r, Qt.AlignmentFlag.AlignCenter, self.glyph)
            if self.count:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor("white") if on else acc)
                p.drawEllipse(QRectF(r.right() - 11, r.top() + 5, 7, 7))
            self.setToolTip(f"{RECENT}：最近 {days_label(self.days)}（{self.count or 0} 个）\n右键：更改时间范围")
            return
        self.setToolTip("右键：更改时间范围")
        p.drawText(QRectF(0, 0, 40, self.height()), Qt.AlignmentFlag.AlignCenter, self.glyph)
        right = 10
        if self.count is not None:
            fb = self.font()
            fb.setPixelSize(11)
            fb.setBold(True)
            p.setFont(fb)
            txt = str(self.count)
            w = max(24, p.fontMetrics().horizontalAdvance(txt) + 12)
            br = QRectF(self.width() - w - 10, (self.height() - 20) / 2, w, 20)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("white") if on else acc)
            p.drawRoundedRect(br, 10, 10)
            p.setPen(acc if on else QColor("white"))
            p.drawText(br, Qt.AlignmentFlag.AlignCenter, txt)
            right = w + 16
        f = self.font()
        f.setPixelSize(13)
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor("white") if on else QColor(C("text")))
        p.drawText(QRectF(42, 7, self.width() - 42 - right, 20),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self.text_)
        f.setBold(False)
        f.setPixelSize(11)
        p.setFont(f)
        sub = QColor("white") if on else QColor(C("muted"))
        if on:
            sub.setAlpha(215)
        p.setPen(sub)
        p.drawText(QRectF(42, 26, self.width() - 42 - right, 18),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, f"最近 {days_label(self.days)}")


class CleanupWorker(QThread):
    """在后台线程执行清理：扫描 + 逐个移入回收站可能要几秒到几十秒，不能卡住界面。"""
    done = pyqtSignal(int, object, list)      # 文件数, 释放字节（可能超过 32 位）, 提示

    def __init__(self, parent, cfg):
        super().__init__(parent)
        self.cfg = dict(cfg)                  # 用快照，避免运行中被界面修改

    def run(self):
        try:
            n, freed, notes = cleanup(self.cfg)
        except Exception as e:                # 后台线程里的异常不能悄悄吞掉
            log(f"清理出错：{e}")
            n, freed, notes = 0, 0, [f"清理出错：{e}"]
        self.done.emit(n, freed, notes)


class TaskWorker(QThread):
    """在后台线程里运行一个函数，完成后通过 done 信号把结果（或异常）交回界面线程。"""
    done = pyqtSignal(object, object)         # 结果, 异常（无异常时为 None）

    def __init__(self, parent, fn):
        super().__init__(parent)
        self.fn = fn

    def run(self):
        try:
            self.done.emit(self.fn(), None)
        except Exception as e:
            log(f"后台任务出错：{e}")
            self.done.emit(None, e)


class ArchiveWorker(QThread):
    """后台压缩 / 解压：fn(progress, cancel) 在后台线程运行，进度通过信号回到界面线程。"""
    progress = pyqtSignal(int, str)
    done = pyqtSignal(object, object)

    def __init__(self, parent, fn):
        super().__init__(parent)
        self.fn = fn
        self.cancel = threading.Event()

    def run(self):
        try:
            self.done.emit(self.fn(lambda v, t: self.progress.emit(int(v), t), self.cancel), None)
        except Exception as e:
            if not isinstance(e, archive.ArchiveError):
                log(f"压缩 / 解压出错：{e}")
            self.done.emit(None, e)


class FileItem(QTreeWidgetItem):
    """文件列表的一行。分类 / 大小 / 时间三列用次要文字颜色：在 data() 里统一返回，
    比给每个单元格调用 setForeground 快得多（几万个文件时填充列表能省下一半时间）。"""
    muted = None

    def data(self, col, role):
        if col and role == Qt.ItemDataRole.ForegroundRole and FileItem.muted is not None:
            return FileItem.muted
        return super().data(col, role)


class ThumbLoader(QThread):
    """后台生成图片缩略图，并缓存到磁盘（按路径 + 修改时间），下次打开直接读取小图。"""
    ready = pyqtSignal(str, QImage)
    SIZE = 56   # 28px 图标的 2 倍，高分屏也清晰

    def __init__(self, parent):
        super().__init__(parent)
        self.cache_dir = os.path.join(os.environ.get("LOCALAPPDATA", CFG_DIR), "DownloadButler", "thumbs")
        os.makedirs(self.cache_dir, exist_ok=True)
        self.q, self.lock, self.cv = collections.deque(), threading.Lock(), threading.Condition()

    MAX_FILES = 3000      # 缓存上限；超过后删掉最久没用的，降到 2000 个

    def prune(self):
        try:
            files = [e for e in os.scandir(self.cache_dir) if e.is_file() and e.name.endswith(".png")]
            if len(files) <= self.MAX_FILES:
                return
            files.sort(key=lambda e: e.stat().st_mtime)
            for e in files[:len(files) - self.MAX_FILES * 2 // 3]:
                try:
                    os.remove(e.path)
                except OSError:
                    pass
        except OSError:
            pass

    def request(self, key, path):
        with self.cv:
            self.q.append((key, path))
            self.cv.notify()

    def clear(self):
        with self.cv:
            self.q.clear()

    def run(self):
        self.prune()
        while True:
            with self.cv:
                while not self.q:
                    self.cv.wait()
                key, path = self.q.popleft()
            if key is None:
                return
            cache = os.path.join(self.cache_dir, hashlib.md5(key.encode("utf-8"), usedforsecurity=False).hexdigest() + ".png")
            img = QImage(cache) if os.path.exists(cache) else QImage()
            if not img.isNull():
                try:
                    os.utime(cache)        # 记录最近使用，清理缓存时保留常用的
                except OSError:
                    pass
            if img.isNull():
                r = QImageReader(path)
                r.setAutoTransform(True)
                sz = r.size()
                if sz.isValid() and sz.width() > 0 and sz.height() > 0:
                    sz.scale(self.SIZE, self.SIZE, Qt.AspectRatioMode.KeepAspectRatio)
                    r.setScaledSize(sz)
                img = r.read()
                # 立即释放读取器：否则它会一直打开着这张图片，直到下一次请求，
                # 期间用户无法重命名 / 移动 / 删除这个文件（或其所在文件夹）
                r.setFileName("")
                del r
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
        lay.addWidget(QLabel(APP_NAME, objectName="titleText"))
        lay.addSpacing(6)
        lay.addWidget(QLabel("v" + VERSION, objectName="version"))
        lay.addStretch()
        seg = QFrame(objectName="sideModes")
        sg = QHBoxLayout(seg)
        sg.setContentsMargins(2, 2, 2, 2)
        sg.setSpacing(2)
        self.mode_btns = {}
        for mode, (glyph, tip) in SIDE_MODES.items():
            b = QPushButton(glyph, objectName="sideMode")
            b.setCheckable(True)
            b.setToolTip("左侧菜单：" + tip)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=False, m=mode: win.set_side_mode(m))
            sg.addWidget(b)
            self.mode_btns[mode] = b
        lay.addWidget(seg, 0, Qt.AlignmentFlag.AlignVCenter)
        lay.addSpacing(8)
        self.btn_help = QPushButton("\ue897", objectName="titleHelp")
        self.btn_help.setCheckable(True)
        self.btn_help.setToolTip("帮助（F1）")
        self.btn_help.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_help.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_help.clicked.connect(lambda: win.open_help())
        lay.addWidget(self.btn_help, 0, Qt.AlignmentFlag.AlignVCenter)
        lay.addSpacing(10)
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

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.BackButton and self.main.browse:
            self.main.browse_back()
            return
        super().mousePressEvent(e)

    def keyPressEvent(self, e):
        k = e.key()
        if k in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.main.open_selected()
        elif k == Qt.Key.Key_Delete:
            self.main.delete_selected()
        elif k == Qt.Key.Key_F2:
            self.main.rename_selected()
        elif k == Qt.Key.Key_Backspace and self.main.browse:
            self.main.browse_back()
        elif k == Qt.Key.Key_P and e.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.main.print_selected()
        else:
            super().keyPressEvent(e)


class Dialog(QDialog):
    """应用内样式的确认 / 输入框。"""
    def __init__(self, parent, title, msg, ok="确定", danger=False, edit=None, extra=None, validate=None):
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
        # validate()：点确定时检查输入，返回错误文字则显示在对话框里、不关闭
        self.validate = validate
        self.err = QLabel(objectName="dialogErr")
        self.err.setWordWrap(True)
        self.err.setStyleSheet("color:#e5534b;")
        self.err.hide()
        v.addWidget(self.err)
        h = QHBoxLayout()
        h.addStretch()
        b0 = QPushButton("取消")
        b0.clicked.connect(self.reject)
        b1 = QPushButton(ok, objectName="danger" if danger else "primary")
        b1.setDefault(True)
        b1.clicked.connect(self.try_accept)
        self.ok_btn = b1
        h.addWidget(b0)
        h.addWidget(b1)
        v.addSpacing(4)
        v.addLayout(h)
        self.setMinimumWidth(420)

    def try_accept(self):
        msg = self.validate() if self.validate else ""
        if msg:
            self.err.setText(msg)
            self.err.show()
            return
        self.accept()

    def value(self):
        return self.edit.text().strip() if self.edit else None


class TourDialog(QDialog):
    """新手教程：浮在主窗口右下角的说明卡片，逐步切换页面并高亮相关控件；不挡住操作。"""
    def __init__(self, main):
        super().__init__(main)
        self.main, self.i = main, 0
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        card = QFrame(objectName="dialog")
        outer.addWidget(card)
        v = QVBoxLayout(card)
        v.setContentsMargins(20, 16, 20, 14)
        v.setSpacing(8)
        self.step = QLabel(objectName="hint")
        self.title = QLabel(objectName="cardTitle")
        self.text = QLabel(objectName="muted")
        self.text.setWordWrap(True)
        self.text.setMinimumHeight(66)
        self.text.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        for x in (self.step, self.title, self.text):
            v.addWidget(x)
        h = QHBoxLayout()
        self.b_skip = QPushButton("跳过教程")
        self.b_prev = QPushButton("上一步")
        self.b_next = QPushButton("下一步", objectName="primary")
        self.b_skip.clicked.connect(self.finish)
        self.b_prev.clicked.connect(lambda: self.go(self.i - 1))
        self.b_next.clicked.connect(lambda: self.go(self.i + 1) if self.i + 1 < len(help_content.TOUR) else self.finish())
        h.addWidget(self.b_skip)
        h.addStretch()
        h.addWidget(self.b_prev)
        h.addWidget(self.b_next)
        v.addLayout(h)
        for b in (self.b_skip, self.b_prev, self.b_next):
            b.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedWidth(400)

    def go(self, i):
        n = len(help_content.TOUR)
        self.i = max(0, min(i, n - 1))
        title, text, where = help_content.TOUR[self.i]
        self.step.setText(f"新手教程 · {self.i + 1} / {n}")
        self.title.setText(title)
        self.text.setText(text)
        self.b_prev.setEnabled(self.i > 0)
        self.b_next.setText("完成" if self.i == n - 1 else "下一步")
        target = self.main.tour_target(where)
        self.adjustSize()
        g = self.main.geometry()
        self.move(g.right() - self.width() - 28, g.bottom() - self.height() - 84)
        QTimer.singleShot(30, lambda: self.main.tour_highlight(target))   # 等页面切换完成再定位

    def finish(self):
        self.main.end_tour()
        self.close()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape:
            self.finish()
        else:
            super().keyPressEvent(e)


# ---------------- 主窗口 ----------------
class Main(QWidget):
    def __init__(self, start_hidden=False):
        super().__init__()
        self.cfg = load_cfg()
        self.cfg["autostart"] = autostart_enabled()
        journal.init(CFG_DIR)
        apply_folders(self.cfg)
        apply_schemes(self.cfg)
        QApplication.instance().setStyleSheet(build_qss(self.cfg))
        self.app_icon = make_app_icon()
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(self.app_icon)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMouseTracking(True)
        self.resize(1180, 760)
        self.setMinimumSize(900, 600)
        QApplication.instance().installEventFilter(self)

        self.items, self.sig, self.cur = [], None, "全部文件"
        self.loc = None                    # 主页只看某一个管理的文件夹（None = 全部）
        self.browse = None                 # 在应用内打开的文件夹（None = 按分类浏览）
        self.browse_top, self.browse_items, self.browse_sig = None, [], None
        self.rule_scheme = ""              # 规则编辑器正在编辑的方案（"" = 主文件夹规则）
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

        def item(glyph, text, fn, checkable=False, layout=sl):
            b = SideButton(glyph, text)
            b.setCheckable(checkable)
            b.clicked.connect(fn)
            layout.addWidget(b)
            self.side_btns.append(b)
            return b
        self.side_item = item
        # 最上面是文件夹选择（原来的“收起菜单”位置）；收起 / 展开改到标题栏的三种模式里
        self.btn_loc = item("\ue8b7", "全部文件夹", lambda: self.loc_menu())
        self.btn_loc.trail = "\ue70d"
        # “最近添加”单独放在最上面，样式也和分类不同（它不是一个分类，而是按到达时间的快捷入口）
        sl.addSpacing(4)
        self.btn_recent = RecentButton()
        self.btn_recent.days = self.cfg["recent_days"]
        self.btn_recent.clicked.connect(lambda: self.select_cat(RECENT))
        self.btn_recent.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.btn_recent.customContextMenuRequested.connect(lambda pos: self.recent_menu(
            self.btn_recent.mapToGlobal(pos)))
        sl.addWidget(self.btn_recent)
        self.side_btns.append(self.btn_recent)
        sl.addSpacing(4)
        s = QFrame(objectName="sideSep"); s.setFixedHeight(1); sl.addWidget(s)
        # 分类按钮单独放在一个布局里：分类规则改了以后只重建这一段，不需要重启
        self.cat_box = QVBoxLayout()
        self.cat_box.setContentsMargins(0, 0, 0, 0)
        self.cat_box.setSpacing(3)
        sl.addLayout(self.cat_box)
        self.build_cat_buttons()
        s = QFrame(objectName="sideSep"); s.setFixedHeight(1); sl.addWidget(s)
        sl.addStretch()
        # 单击直接清理垃圾文件（最常用）；右键可以选“按自动清理规则清理旧文件”和清理设置
        self.btn_clean = item("\ue75c", "清理", lambda: self.clean_junk())
        self.btn_clean.setToolTip("清理所有垃圾文件（扫描后逐项确认）\n右键：更多清理选项")
        self.btn_clean.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.btn_clean.customContextMenuRequested.connect(lambda _: self.clean_menu())
        self.btn_appear = item("", "外观", self.open_appearance, True)
        self.btn_settings = item("", "设置", self.open_settings, True)
        self.btn_help = self.title.btn_help        # 帮助按钮在标题栏（深浅色开关左边）
        mid.addWidget(self.side)

        self.pages = QStackedWidget()
        mid.addWidget(self.pages, 1)
        self.pages.addWidget(self.build_home())
        self.refresh_loc_box()
        self.pages.addWidget(self.build_settings())
        self.pages.addWidget(self.build_appearance())
        self.pages.addWidget(self.build_help())
        self.apply_appearance(save=False, initial=True)
        self.side_timer = QTimer(self, singleShot=True, timeout=self.side_auto_check)
        self.side_expand_timer = QTimer(self, singleShot=True, interval=120,
                                        timeout=lambda: self.side_near(QCursor.pos()) and self.set_side(True, animate=True))
        self.set_side_mode(self.cfg["side_mode"])
        self.select_cat("全部文件")

        # 托盘
        self.tray = QSystemTrayIcon(self.app_icon, self)
        self.tray.setToolTip(APP_NAME)
        m = QMenu()
        m.addAction("打开自动整理文件管理器", self.show_main)
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
        QShortcut(QKeySequence("F1"), self, activated=lambda: self.open_help())
        QShortcut(QKeySequence("Alt+Left"), self, activated=lambda: self.browse and self.browse_back())
        self.tour = None
        self.tour_ring = QFrame(self, objectName="tourRing")      # 新手教程里高亮当前介绍的控件
        self.tour_ring.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.tour_ring.hide()
        # 事件驱动：文件夹有变化时系统通知，不再定时扫描
        self.dirty = True
        self.watcher = QFileSystemWatcher(self)
        self.watcher.directoryChanged.connect(self.on_fs_change)
        self.fs_timer = QTimer(self, singleShot=True, interval=350, timeout=self.on_fs_settled)   # 合并连续变化
        self.retry_timer = QTimer(self, singleShot=True, interval=3000, timeout=self.on_fs_settled)  # 下载中的文件稍后重试
        self.safety_timer = QTimer(self, interval=5 * 60 * 1000,          # 兜底：防止漏掉通知，完整重新扫描
                                   timeout=lambda: (scan_invalidate(), self.on_fs_settled()))
        self.safety_timer.start()
        self.clean_timer = QTimer(self, interval=30 * 60 * 1000, timeout=self.auto_cleanup)
        self.clean_timer.start()
        if self.cfg.get("autostart"):
            set_autostart(True)   # 程序位置变化（重新安装）后修正开机启动路径
        log("自动整理文件管理器已启动，管理：" + ROOT)
        if start_hidden:
            # 开机后台启动：只整理和监视下载根目录，列表与缩略图等到第一次打开窗口再加载
            self.on_fs_settled()
            QTimer.singleShot(15000, self.warm_up)
        else:
            self.tick()
            self.show()
            QTimer.singleShot(800, self.maybe_tour)     # 第一次使用：自动开始新手教程

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
        self.b_back = QPushButton("\ue72b", objectName="backBtn")
        self.b_back.setToolTip("返回上一级（Backspace / Alt+←）")
        self.b_back.clicked.connect(lambda: self.browse_back())
        self.b_back.hide()
        head.addWidget(self.b_back, 0, Qt.AlignmentFlag.AlignVCenter)
        # 标题不决定最小宽度：窗口较窄或文件夹名很长时只省略标题，右边的按钮和搜索框始终完整显示
        for lb in (self.page_title, self.page_sub):
            lb.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            lb.setMinimumWidth(120)
        head.addLayout(tv, 1)
        # 常用操作放在列表上方，随手可点；左侧菜单只保留导航
        self.b_organize = QPushButton("立即整理")
        self.b_organize.setToolTip("马上把最外层的新文件归入分类（开启自动整理时平时会自动进行）")
        self.b_organize.clicked.connect(lambda: self.do_organize(True))
        self.btn_root = QPushButton("打开文件夹")
        self.btn_root.setToolTip("在资源管理器中打开：" + ROOT)
        self.btn_root.clicked.connect(lambda: os.startfile(self.browse or self.loc or ROOT))
        # 管理了多个文件夹时：选择只看其中一个（左侧分类也换成这个文件夹使用的规则）
        # 文件夹选择在左侧菜单最上面（btn_loc）；这个下拉框只保存选项，不显示
        self.loc_box = QComboBox(body)
        self.loc_box.hide()
        self.loc_box.currentIndexChanged.connect(self.on_loc_changed)
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
        head.addWidget(sb)                     # 搜索框排在右侧这一组的最左边
        for b in (self.b_organize, self.btn_root):
            b.setFixedHeight(36)
            head.addWidget(b)
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
        self.b_arch = QPushButton("压缩 / 解压  ▾")
        self.b_arch.clicked.connect(lambda: self.archive_menu().exec(
            self.b_arch.mapToGlobal(QPoint(0, self.b_arch.height() + 4))))
        self.b_delete = QPushButton("删除", objectName="danger")
        self.b_delete.clicked.connect(self.delete_selected)
        for b in (self.b_open, self.b_reveal, self.b_move, self.b_rename, self.b_arch, self.b_delete):
            act.addWidget(b)
        act.addStretch()
        self.sel_hint = QLabel(objectName="hint")
        act.addWidget(self.sel_hint)
        # 压缩 / 解压进度条：后台进行，可以继续浏览，也可以随时取消
        self.job_bar = QWidget()
        jb = QHBoxLayout(self.job_bar)
        jb.setContentsMargins(0, 0, 0, 0)
        jb.setSpacing(10)
        self.job_lbl = QLabel(objectName="hint")
        self.job_prog = QProgressBar(textVisible=False)
        self.job_prog.setRange(0, 100)
        self.job_prog.setFixedWidth(240)
        self.job_cancel = QPushButton("取消")
        self.job_cancel.clicked.connect(self.cancel_job)
        jb.addWidget(self.job_lbl, 1)
        jb.addWidget(self.job_prog)
        jb.addWidget(self.job_cancel)
        self.job_bar.hide()
        self.job = None
        self.session_pws = []          # 本次运行里输入过的解压密码（只在内存中）
        cv.addWidget(self.job_bar)
        # 列表下方原来的一排操作按钮已去掉：打开、移动、重命名、压缩 / 解压、删除等都在右键菜单和快捷键里。
        # 按钮对象仍然保留（不显示），update_actions 等代码不需要改动
        self.act_bar = QWidget()
        self.act_bar.setLayout(act)
        self.act_bar.hide()
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
        top = QFrame(objectName="pageHead")
        tv = QVBoxLayout(top)
        tv.setContentsMargins(0, 0, 0, 0)
        tv.setSpacing(0)
        head = QHBoxLayout()
        head.setContentsMargins(20, 10, 20, 8)
        head.addWidget(QLabel("设置", objectName="pageTitle"))
        head.addStretch()
        back = QPushButton("←  返回文件列表")
        back.clicked.connect(lambda: self.select_cat(self.cur))
        head.addWidget(back)
        tv.addLayout(head)
        # 设置菜单栏：每一栏只显示相关的设置，更整洁；放在一条有底色的圆角栏里
        row = QHBoxLayout()
        row.setContentsMargins(20, 0, 20, 12)
        bar = QFrame(objectName="tabBar")
        tabs = QHBoxLayout(bar)
        tabs.setContentsMargins(4, 4, 4, 4)
        tabs.setSpacing(2)
        row.addWidget(bar)
        row.addStretch()
        tv.addLayout(row)
        outer.addWidget(top)
        self.settings_stack = QStackedWidget()
        outer.addWidget(self.settings_stack, 1)
        self.settings_tabs, self.settings_scrolls, layouts, cur = [], [], [], {}

        def section(name, first=False):
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
            v = QVBoxLayout(body)
            v.setContentsMargins(0, 16, 0, 20)
            v.setSpacing(12)
            i = self.settings_stack.count()
            self.settings_stack.addWidget(sc)
            self.settings_scrolls.append(sc)
            b = QPushButton(name, objectName="tabBtn")
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=None, i=i: self.show_settings_tab(i))
            tabs.insertWidget(0, b) if first else tabs.addWidget(b)
            self.settings_tabs.append(b)
            layouts.append(v)
            cur["v"] = v

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
            cur["v"].addWidget(c)
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

        section("管理的文件夹")
        c = card("主文件夹", "下载的文件默认在这里整理：最外层的新文件放进各个分类文件夹。")
        b_root = QPushButton("更改…")
        b_root.clicked.connect(lambda: self.choose_root(False))
        b_rdef = QPushButton("恢复为“下载”")
        b_rdef.setEnabled(bool(self.cfg["root"]))
        b_rdef.clicked.connect(lambda: self.choose_root(True))
        row(c, "主文件夹", b_root, b_rdef,
            sub=ROOT + ("" if self.cfg["root"] else "（系统“下载”文件夹）"))

        c = card("其他文件夹",
                 "还可以整理桌面、文档、移动硬盘上的某个文件夹。为了不影响程序读取文件，这里的规则更保守："
                 f"只整理文件夹最外层、加入之后新出现的文件，放进其中的“{EXTRA_SUB}”子文件夹；"
                 "不进入任何子文件夹，跳过快捷方式、程序和配置文件、“仅在线”的云盘文件；"
                 "看起来像程序、游戏或代码项目的文件夹不能添加。默认不参与自动清理。"
                 "每次移动都可以在“移动记录”里一键撤销。")
        for f in self.cfg["folders"]:
            self.add_folder_row(c, f)
        if not self.cfg["folders"]:
            c.addWidget(QLabel("还没有添加其他文件夹。", objectName="hint"))
        hb = QHBoxLayout()
        hb.addStretch()
        b_add = QPushButton("添加文件夹…", objectName="primary")
        b_add.clicked.connect(self.add_folder)
        hb.addWidget(b_add)
        c.addLayout(hb)

        c = card("其他文件夹里不整理的文件类型",
                 "这些类型的文件留在原处，不会被整理（主文件夹不受影响）。用空格或逗号分隔。")
        self.skip_edit = QLineEdit(self.cfg.get("extra_skip") or DEFAULT_EXTRA_SKIP)
        c.addWidget(self.skip_edit)
        hb = QHBoxLayout()
        hb.addStretch()
        b_sd = QPushButton("恢复默认")
        b_sd.clicked.connect(lambda: self.skip_edit.setText(DEFAULT_EXTRA_SKIP))
        b_ss = QPushButton("保存", objectName="primary")
        b_ss.clicked.connect(self.save_extra_skip)
        hb.addWidget(b_sd)
        hb.addWidget(b_ss)
        c.addLayout(hb)

        section("自动整理")
        c = card("自动整理")
        self.s_auto = Switch()
        self.s_auto.setChecked(self.cfg["auto"])
        self.s_auto.toggled.connect(lambda on: self.set_cfg("auto", on))
        row(c, "管理的文件夹里出现新文件时自动整理" if self.cfg.get("root") else "有新文件下载到“下载”文件夹时自动整理",
            self.s_auto,
            sub="按下方“分类规则”放进 " + " / ".join(CATS[:4]) + (" …" if len(CATS) > 4 else "")
                + " 等文件夹；未下载完的文件会跳过")
        self.s_settle = QSpinBox(minimum=3, maximum=600, suffix=" 秒")
        self.s_settle.setValue(int(self.cfg["settle_sec"]))
        self.s_settle.valueChanged.connect(lambda x: self.set_cfg("settle_sec", x))
        row(c, "下载完成后等待多久再整理", self.s_settle,
            sub="留出时间在浏览器里直接“打开”或“在文件夹中显示”刚下载的文件")
        self.s_month = Switch()
        self.s_month.setChecked(bool(self.cfg["by_month"]))
        self.s_month.toggled.connect(self.set_by_month)
        self.s_loose = Switch()
        self.s_loose.setChecked(bool(self.cfg["loose_dirs"]))
        self.s_loose.toggled.connect(lambda on: self.set_cfg("loose_dirs", bool(on)))
        row(c, "整理散落的文件夹", self.s_loose,
            sub="把直接放在这里的子文件夹（解压出来的、软件导出的）按其中主要的文件类型整个归入分类；里面的文件保持原样不拆散")
        row(c, "按“年-月”分子文件夹", self.s_month, sub="关闭后直接放在分类文件夹里；已经整理好的文件保持不变")

        section("分类规则")
        c = card("分类规则",
                 "每个分类可以按扩展名匹配，也可以按文件名里的关键词匹配（如“护照, passport, I-20”）。"
                 "填了关键词的分类优先：文件名含任一关键词就归入它，扩展名一栏留空表示不限类型。"
                 "英文关键词按整词匹配（opt 不会误中 adopt）。没有匹配的文件放进“其他文件”。"
                 "改名会同时重命名对应文件夹；删除分类不会删除文件夹和里面的文件。保存后立即生效。")
        # 规则方案：主文件夹用“主文件夹规则”；其他文件夹可以选用自己的方案（在“管理的文件夹”里选）
        if self.rule_scheme and self.rule_scheme not in SCHEMES:
            self.rule_scheme = ""
        hb = QHBoxLayout()
        hb.addWidget(QLabel("正在编辑："))
        self.scheme_box = QComboBox()
        self.scheme_box.addItem(PRIMARY_SCHEME, "")
        for n in SCHEMES:
            self.scheme_box.addItem(n, n)
        self.scheme_box.setCurrentIndex(max(0, self.scheme_box.findData(self.rule_scheme)))
        self.scheme_box.setMinimumWidth(170)
        self.scheme_box.currentIndexChanged.connect(lambda i: self.switch_scheme(self.scheme_box.itemData(i)))
        hb.addWidget(self.scheme_box)
        for text, fn, tip in (("新建方案…", self.new_scheme, "复制正在编辑的规则，另存为一个新方案"),
                              ("重命名…", self.rename_scheme, "给这个规则方案改名"),
                              ("删除方案", self.delete_scheme, "删除这个规则方案"),
                              ("导入…", self.import_rules, "从 .json 文件导入规则"),
                              ("导出…", self.export_rules, "把这套规则保存成 .json 文件，可以分享或在别的电脑导入")):
            b = QPushButton(text)
            b.setToolTip(tip)
            b.clicked.connect(fn)
            if text in ("重命名…", "删除方案"):
                b.setEnabled(bool(self.rule_scheme))
            hb.addWidget(b)
        hb.addStretch()
        c.addLayout(hb)
        used = self.scheme_users(self.rule_scheme)
        self.scheme_hint = QLabel("使用这套规则的文件夹：" + ("、".join(used) if used else "暂无（在“管理的文件夹”里给文件夹选用）"),
                                  objectName="hint")
        self.scheme_hint.setWordWrap(True)
        c.addWidget(self.scheme_hint)
        self.rules_box = QVBoxLayout()
        self.rules_box.setSpacing(6)
        c.addLayout(self.rules_box)
        self.rule_rows = []
        rs = self.edit_rs()
        for name, _, exts in rs.rules:
            self.add_rule_row(name, exts, name, rs.kw_text.get(name, ""))
        hb = QHBoxLayout()
        b_add = QPushButton("添加分类")
        b_add.clicked.connect(lambda: self.add_rule_row("", "", None))
        b_preset = QPushButton("添加常用分类 ▾")
        pm = QMenu(b_preset)
        for pname, pexts, pkws in PRESETS:
            pm.addAction(pname, lambda p=(pname, pexts, pkws): self.add_preset(*p))
        b_preset.setMenu(pm)
        b_def = QPushButton("恢复默认规则")
        b_def.clicked.connect(self.reset_rules)
        b_save = QPushButton("保存规则", objectName="primary")
        b_save.clicked.connect(self.save_rules)
        for b in (b_add, b_preset, b_def):
            hb.addWidget(b)
        hb.addStretch()
        hb.addWidget(b_save)
        c.addLayout(hb)
        hb = QHBoxLayout()
        lbl = QLabel("规则改了以后，已经整理好的文件不会自动挪动：", objectName="hint")
        b_re = QPushButton("按当前规则重新整理已有文件")
        b_re.clicked.connect(self.reorganize_existing)
        hb.addWidget(lbl)
        hb.addStretch()
        hb.addWidget(b_re)
        c.addLayout(hb)

        section("自动清理")
        c = card("自动清理", "清理的文件进入回收站，可以还原；后台每 30 分钟检查一次。")
        self.s_clean = Switch()
        self.s_clean.setChecked(self.cfg["clean_on"])
        self.s_days = QSpinBox(minimum=1, maximum=3650, suffix=" 天")
        self.s_days.setValue(int(self.cfg["clean_days"]))
        self.s_clean.toggled.connect(lambda on: self.set_cfg("clean_on", on))
        self.s_days.valueChanged.connect(lambda x: self.set_cfg("clean_days", x))
        row(c, "定期清理旧文件", self.s_days, self.s_clean, sub="清理下载到本机超过设定天数的文件（按到达时间，不受文件原始修改时间影响）")
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

        section("压缩与解压")
        c = card("压缩与解压", "在文件上点右键（或下方“压缩 / 解压”按钮）即可压缩、解压；这里是默认选项，"
                             "每次在“压缩…”“解压…”窗口里也可以单独修改。")
        self.arch_engine = QLabel(archive.engine_text(), objectName="hint")
        self.arch_engine.setWordWrap(True)
        b_det = QPushButton("重新检测")
        b_det.clicked.connect(lambda: (archive.refresh(), self.arch_engine.setText(archive.engine_text()),
                                       self.show_toast("已重新检测 7-Zip")))
        r = QHBoxLayout()
        r.addWidget(self.arch_engine, 1)
        r.addWidget(b_det)
        c.addLayout(r)

        def combo(key, options):
            cb = QComboBox()
            for k, text in options:
                cb.addItem(text, k)
            i = cb.findData(self.cfg.get(key))
            cb.setCurrentIndex(max(0, i))
            cb.currentIndexChanged.connect(lambda _: self.set_cfg(key, cb.currentData()))
            return cb
        row(c, "默认压缩格式", combo("zip_fmt", [(f, t) for f, _, t in archive.FORMATS]))
        row(c, "默认压缩级别", combo("zip_level", archive.LEVELS))
        row(c, "ZIP 加密方式", combo("zip_method", ZIP_METHODS),
            sub="AES-256 更安全；Windows 自带的解压不支持 AES，需要对方能直接双击打开时选 ZipCrypto")
        row(c, "解压位置", combo("unzip_mode", UNZIP_MODES))
        row(c, "遇到同名文件", combo("unzip_overwrite", OVERWRITE_MODES), sub="只在“直接放在当前文件夹”时会遇到")
        s_open = Switch()
        s_open.setChecked(bool(self.cfg["unzip_open"]))
        s_open.toggled.connect(lambda on: self.set_cfg("unzip_open", bool(on)))
        row(c, "解压完成后打开文件夹", s_open)
        s_rec = Switch()
        s_rec.setChecked(bool(self.cfg["unzip_recycle"]))
        s_rec.toggled.connect(lambda on: self.set_cfg("unzip_recycle", bool(on)))
        row(c, "解压成功后把压缩包移到回收站", s_rec, sub="分卷压缩包的所有分卷一起移走；可以在回收站还原")
        b_pw = QPushButton("管理密码本…")
        b_pw.clicked.connect(self.manage_pw_book)
        self.pw_sub = QLabel(objectName="hint")
        r = QHBoxLayout()
        tv = QVBoxLayout()
        tv.setSpacing(0)
        tv.addWidget(QLabel("解压密码本"))
        tv.addWidget(self.pw_sub)
        r.addLayout(tv)
        r.addStretch()
        r.addWidget(b_pw)
        c.addLayout(r)
        self.update_pw_sub()

        section("常规", first=True)
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

        section("移动记录")
        c = card("移动记录",
                 "自动整理文件管理器移动过的文件都记在这里（自动整理、立即整理、移动到、按规则重新整理）。"
                 "选中一次操作后点“撤销”，文件会移回原来的位置；原位置已有同名文件时自动改名，绝不覆盖。"
                 "撤销移回的文件之后不会再被自动整理。")
        self.journal_tree = QTreeWidget()
        self.journal_tree.setHeaderLabels(["时间", "操作", "文件", "状态"])
        self.journal_tree.setMinimumHeight(380)
        hd = self.journal_tree.header()
        hd.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for i in (0, 2, 3):
            hd.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
        c.addWidget(self.journal_tree)
        hb = QHBoxLayout()
        b_u = QPushButton("撤销这次", objectName="primary")
        b_u.clicked.connect(lambda: self.undo_selected(False))
        b_ua = QPushButton("撤销这次及之后的全部")
        b_ua.clicked.connect(lambda: self.undo_selected(True))
        b_rf = QPushButton("刷新")
        b_rf.clicked.connect(self.fill_journal)
        hb.addWidget(b_u)
        hb.addWidget(b_ua)
        hb.addStretch()
        hb.addWidget(b_rf)
        c.addLayout(hb)
        self.fill_journal()

        section("记录与关于")
        c = card("最近记录")
        self.log_view = QTextBrowser()
        self.log_view.setMinimumHeight(200)
        c.addWidget(self.log_view)
        import converter_link   # 相关应用：只是推荐，两个软件各自独立下载、独立运行
        c = card("相关应用")
        installed, text = converter_link.status()
        b_conv = QPushButton("访问下载页" if installed else "下载格式转换器")
        b_conv.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(converter_link.DOWNLOAD_URL)))
        row(c, "格式转换器", b_conv, sub=text)

        c = card("关于")
        b_help = QPushButton("帮助中心（F1）")
        b_help.clicked.connect(lambda: self.open_help())
        b_tour = QPushButton("重新查看新手教程")
        b_tour.clicked.connect(lambda: self.start_tour())
        row(c, f"自动整理文件管理器 v{VERSION}", b_help, b_tour, sub="设置、背景图与密码本保存在 " + CFG_DIR)
        for v in layouts:
            v.addStretch()
        tabs.addStretch()
        self.show_settings_tab("常规")
        return page

    # ---------- 导航 ----------
    def set_side(self, open_, animate=False):
        """展开 / 收起左侧菜单。自动模式下带一个很短的动画。"""
        self.side_open = open_
        anim = getattr(self, "_side_anim", None)
        if anim is not None:
            anim.stop()
        target = SIDE_OPEN_W if open_ else SIDE_CLOSED_W

        def labels(on):
            for b in self.side_btns:
                b.expanded = on
                b.update()
        if not animate or self.side.width() == target or not self.isVisible():
            self.side.setFixedWidth(target)
            labels(open_)
            return
        if open_:
            labels(True)                       # 展开时文字先出现（被宽度裁掉的部分随动画露出）
        anim = self._side_anim = QVariantAnimation(self, duration=140, startValue=self.side.width(), endValue=target)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.valueChanged.connect(lambda v: self.side.setFixedWidth(int(v)))
        if not open_:
            anim.finished.connect(lambda: labels(False) if not self.side_open else None)
        anim.start()

    def set_side_mode(self, mode):
        if mode not in SIDE_MODES:
            return
        if mode != self.cfg.get("side_mode"):
            self.set_cfg("side_mode", mode)
        for m, b in self.title.mode_btns.items():
            b.setChecked(m == mode)
        self.side_timer.stop()
        if mode == "open":
            self.set_side(True, animate=True)
        elif mode == "closed":
            self.set_side(False, animate=True)
        else:                                  # 自动：先收起，鼠标靠近时再展开
            self.set_side(self.side_near(QCursor.pos()), animate=True)

    def side_near(self, gp):
        """鼠标是否在左侧菜单上（收起时左右多留一点，靠近就算）。"""
        if not self.isVisible() or self.isMinimized():
            return False
        p = self.side.mapFromGlobal(gp)
        extra = 0 if self.side_open else 10
        return -4 <= p.x() <= self.side.width() + extra and 0 <= p.y() <= self.side.height()

    def side_auto_check(self):
        """自动模式：离开菜单一段时间后收起；弹出菜单（如右键菜单）打开时不收起。"""
        if self.cfg.get("side_mode") != "auto" or not self.side_open:
            return
        if QApplication.activePopupWidget() is not None or self.side_near(QCursor.pos()):
            self.side_timer.start(700)
            return
        self.set_side(False, animate=True)

    def set_recent_days(self, d):
        if d not in RECENT_OPTIONS:
            return
        if d != self.cfg["recent_days"]:
            self.set_cfg("recent_days", d)
        self.btn_recent.days = d
        for box in (getattr(self, "s_recent", None),):
            try:
                if box is not None and box.currentIndex() != RECENT_OPTIONS.index(d):
                    box.blockSignals(True); box.setCurrentIndex(RECENT_OPTIONS.index(d)); box.blockSignals(False)
            except RuntimeError:          # 设置页重建后旧的下拉框已删除
                pass
        self.refresh_counts()
        if self.cur == RECENT and self.pages.currentIndex() == 0:
            self.fill()

    def recent_menu(self, pos):
        m = QMenu(self)
        m.addAction("查看最近添加的文件", lambda: self.select_cat(RECENT))
        m.addSeparator()
        for d in RECENT_OPTIONS:
            a = m.addAction("最近 " + days_label(d), lambda d=d: self.set_recent_days(d))
            a.setCheckable(True)
            a.setChecked(d == self.cfg["recent_days"])
        m.exec(pos)

    def select_cat(self, c):
        self.browse = None
        self.cur = c
        for k, b in self.cat_btns.items():
            b.setChecked(k == c)
        self.btn_settings.setChecked(False)
        self.btn_appear.setChecked(False)
        self.btn_help.setChecked(False)
        self.pages.setCurrentIndex(0)
        self.fill()

    def open_settings(self):
        for b in self.cat_btns.values():
            b.setChecked(False)
        self.btn_settings.setChecked(True)
        self.btn_appear.setChecked(False)
        self.btn_help.setChecked(False)
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

    # ---------- 可配置：分类规则 / 管理的文件夹 ----------
    def set_by_month(self, on):
        global BY_MONTH
        BY_MONTH = bool(on)
        self.set_cfg("by_month", bool(on))

    def add_rule_row(self, name, exts, orig, kws="", protect=False):
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        n = QLineEdit(name, placeholderText="分类名")
        n.setFixedWidth(120)
        e = QLineEdit(" ".join(x.lstrip(".") for x in exts.split()), placeholderText="扩展名，如 pdf docx")
        k = QLineEdit(kws, placeholderText="文件名关键词（可选），逗号分隔")
        k.setToolTip(kws)
        e.setCursorPosition(0)                 # 内容较长时显示开头而不是结尾
        k.setCursorPosition(0)
        rm = QPushButton("删除")
        rm.setCursor(Qt.CursorShape.PointingHandCursor)
        h.addWidget(n)
        h.addWidget(e, 2)
        h.addWidget(k, 3)
        h.addWidget(rm)
        rec = dict(w=w, name=n, exts=e, kws=k, orig=orig, protect=protect)

        def remove():
            label = n.text().strip() or "这个分类"
            if n.text().strip() or e.text().strip() or k.text().strip():     # 空白行直接删，不打扰
                msg = (f"删除分类“{label}”？\n\n点“保存规则”后才会生效；“{rec['orig']}”文件夹和里面的文件保留原样，"
                       "只是不再显示、整理和清理。" if rec["orig"] else
                       f"删除“{label}”这一行？它还没有保存，删除不会影响任何文件。")
                if not Dialog(self, "删除分类", msg, ok="删除", danger=True).exec():
                    return
            if rec in self.rule_rows:
                self.rule_rows.remove(rec)
            w.deleteLater()
        rm.clicked.connect(remove)
        self.rules_box.addWidget(w)
        self.rule_rows.append(rec)
        if not name:
            n.setFocus()

    def reset_rules(self):
        for r in list(self.rule_rows):
            r["w"].deleteLater()
        self.rule_rows.clear()
        for name, _, exts in DEFAULT_RULES:
            self.add_rule_row(name, exts, name if name in self.edit_rs().cats else None)

    def add_preset(self, name, exts, kws):
        if any(r["name"].text().strip() == name for r in self.rule_rows):
            self.show_toast(f"已经有“{name}”分类了")
            return
        # 身份、工作、财务类文件很重要：默认加入“受保护的分类”，自动清理不会动它们
        self.add_rule_row(name, exts, None, kws, protect=True)
        self.show_toast(f"已添加“{name}”，可修改关键词后点“保存规则”")

    def save_rules(self):
        rows = [(r["name"].text(), r["exts"].text(), r["kws"].text()) for r in self.rule_rows]
        norm, err = validate_rules(rows)
        if err:
            self.show_toast(err)
            return
        names = [r[0] for r in norm]
        renames = [(r["orig"], n) for r, n in zip(self.rule_rows, names) if r["orig"] and r["orig"] != n]
        renamed_from = {o for o, _ in renames}
        rs = self.edit_rs()
        removed = [c for c in rs.cats if c != OTHER and c not in names and c not in renamed_from]
        if not renames and not removed and norm == [list(r) for r in self.current_rules()]:
            self.show_toast("分类规则没有变化")
            return
        def key(r):
            return r[1], (r[2] if len(r) > 2 else "")
        old = {r[0]: key(r) for r in self.current_rules()}
        targets = {n for _, n in renames}
        added = [r[0] for r in norm if r[0] not in old and r[0] not in targets]
        changed = [r[0] for r in norm if r[0] in old and key(r) != old[r[0]]]
        used = self.scheme_users(self.rule_scheme)
        msg = (f"确定修改“{rs.name}”吗？保存后立即生效，不需要重启。"
               + ("\n使用这套规则的文件夹：" + "、".join(used) if used else ""))
        if added:
            msg += "\n\n新增分类：" + "、".join(added)
        if renames:
            msg += "\n\n重命名（文件夹一起改名）：" + "、".join(f"{o} → {n}" for o, n in renames)
        if changed:
            msg += "\n\n修改了扩展名 / 关键词：" + "、".join(changed)
        if removed:
            msg += "\n\n删除的分类：" + "、".join(removed) + "\n（文件夹和里面的文件保留原样，只是不再显示、整理和清理）"
        msg += "\n\n点“取消”会撤销这次的修改，恢复到修改之前。"
        if not Dialog(self, "保存分类规则", msg, ok="保存修改", danger=bool(removed)).exec():
            self.revert_rules()
            self.show_toast("已撤销修改，分类规则保持不变")
            return
        # 文件夹监视会占用目录句柄，Windows 下被监视的文件夹无法改名：先全部释放
        if renames and self.watcher.directories():
            self.watcher.removePaths(self.watcher.directories())
        for (o, n), r in [(x, r) for x in renames for r in roots() if ruleset_for(r) is rs]:
            src, dst = os.path.join(cat_base(r), o), os.path.join(cat_base(r), n)
            try:
                if os.path.isdir(src) and not is_reparse(os.lstat(src)) and not os.path.exists(dst):
                    os.rename(src, dst)
                    log(f"分类改名：{o} → {n}")
            except OSError as e:
                log(f"分类文件夹改名失败：{o} → {n}（{e.strerror or e}）")
        mp = dict(renames)
        self.cfg["protect"] = [mp.get(p, p) for p in self.cfg["protect"] if mp.get(p, p) in names + [OTHER]]
        for r, n in zip(self.rule_rows, names):
            if r["protect"] and n not in self.cfg["protect"]:
                self.cfg["protect"].append(n)
        if self.rule_scheme:
            for sc in self.cfg["schemes"]:
                if sc["name"] == self.rule_scheme:
                    sc["rules"] = norm
        else:
            self.cfg["rules"] = [] if norm == [[n, e] for n, _, e in DEFAULT_RULES] else norm
        save_cfg(self.cfg)
        # 热更新：规则数据（RULES / CATS / 关键词）原地替换，再重建依赖分类列表的界面
        apply_rules(self.cfg["rules"])
        apply_schemes(self.cfg)
        self.categories_changed(dict(renames))
        log(f"分类规则已更新（{rs.name}）：" + "、".join(names))
        self.show_toast("分类规则已保存并生效" + ("，文件夹已改名" if renames else ""))

    def revert_rules(self):
        """把规则编辑器恢复成当前正在使用的规则（丢弃未保存的修改）。"""
        for r in list(self.rule_rows):
            r["w"].deleteLater()
        self.rule_rows.clear()
        rs = self.edit_rs()
        for name, _, exts in rs.rules:
            self.add_rule_row(name, exts, name, rs.kw_text.get(name, ""))

    def current_rules(self):
        return self.edit_rs().rows()

    # ---------- 规则方案 ----------
    def edit_rs(self):
        return SCHEMES.get(self.rule_scheme, PRIMARY) if self.rule_scheme else PRIMARY

    def scheme_users(self, name):
        """使用某个方案的文件夹（显示名）。"""
        out = [f"主文件夹（{os.path.basename(ROOT) or ROOT}）"] if not name else []
        return out + [os.path.basename(f["path"]) or f["path"] for f in self.cfg["folders"] if (f.get("scheme") or "") == name]

    def rules_dirty(self):
        rows = [(r["name"].text(), r["exts"].text(), r["kws"].text()) for r in self.rule_rows]
        return validate_rules(rows)[0] != self.current_rules()

    def switch_scheme(self, name, ask=True):
        if name == self.rule_scheme:
            return
        if ask and self.rules_dirty() and not Dialog(
                self, "切换规则方案", f"“{self.edit_rs().name}”有还没保存的修改，切换后会丢弃。继续？", ok="丢弃并切换").exec():
            self.scheme_box.blockSignals(True)
            self.scheme_box.setCurrentIndex(max(0, self.scheme_box.findData(self.rule_scheme)))
            self.scheme_box.blockSignals(False)
            return
        self.rule_scheme = name or ""
        self.rebuild_settings()

    def scheme_name_problem(self, n, old=None):
        n = n.strip()
        if not n:
            return "名称不能为空"
        if len(n) > 40:
            return "名称太长（最多 40 个字）"
        taken = {PRIMARY_SCHEME.lower()} | {x.lower() for x in SCHEMES if x != old}
        if n.lower() in taken:
            return f"已经有叫“{n}”的方案了"
        return ""

    def free_scheme_name(self, base):
        n, i = base, 2
        while self.scheme_name_problem(n):
            n, i = f"{base} {i}", i + 1
        return n

    def new_scheme(self, rules=None, name=None):
        base = name or (self.edit_rs().name + " 副本" if self.rule_scheme else "新规则方案")
        d = Dialog(self, "新建规则方案", "给新方案起个名字。会先复制正在编辑的规则，之后可以随意修改；"
                   "在“管理的文件夹”里给其他文件夹选用它。", ok="新建", edit=self.free_scheme_name(base),
                   validate=lambda: self.scheme_name_problem(d.value()))
        if not d.exec():
            return False
        n = d.value().strip()
        if self.scheme_name_problem(n):
            self.show_toast(self.scheme_name_problem(n))
            return False
        self.cfg["schemes"].append(dict(name=n, rules=rules or self.current_rules()))
        save_cfg(self.cfg)
        apply_schemes(self.cfg)
        log("新建规则方案：" + n)
        self.rule_scheme = n
        self.rebuild_settings()
        self.show_toast(f"已新建“{n}”")
        return True

    def rename_scheme(self):
        old = self.rule_scheme
        if not old:
            self.show_toast("主文件夹规则不能改名，可以新建一个方案")
            return
        d = Dialog(self, "重命名规则方案", f"把“{old}”改名为：", ok="重命名", edit=old,
                   validate=lambda: self.scheme_name_problem(d.value(), old))
        if not d.exec():
            return
        n = d.value().strip()
        if n == old or self.scheme_name_problem(n, old):
            return
        for sc in self.cfg["schemes"]:
            if sc["name"] == old:
                sc["name"] = n
        for lst in (self.cfg["folders"], EXTRA):
            for f in lst:
                if f.get("scheme") == old:
                    f["scheme"] = n
        save_cfg(self.cfg)
        apply_schemes(self.cfg)
        self.rule_scheme = n
        log(f"规则方案改名：{old} → {n}")
        self.categories_changed()
        self.show_toast(f"已改名为“{n}”")

    def delete_scheme(self):
        name = self.rule_scheme
        if not name:
            return
        used = self.scheme_users(name)
        msg = f"删除规则方案“{name}”？" + (
            f"\n\n这些文件夹会改用主文件夹规则：{'、'.join(used)}。\n已经整理好的文件保持原样，不会被移动或删除。" if used else "")
        if not Dialog(self, "删除规则方案", msg, ok="删除", danger=True).exec():
            return
        self.cfg["schemes"] = [sc for sc in self.cfg["schemes"] if sc["name"] != name]
        for lst in (self.cfg["folders"], EXTRA):
            for f in lst:
                if f.get("scheme") == name:
                    f["scheme"] = ""
        save_cfg(self.cfg)
        apply_schemes(self.cfg)
        self.rule_scheme = ""
        log("删除规则方案：" + name)
        self.categories_changed()
        self.show_toast(f"已删除“{name}”")

    def export_rules(self):
        rs = self.edit_rs()
        if self.rules_dirty():
            self.show_toast("有还没保存的修改：导出的是保存过的规则")
        start = os.path.join(os.path.expanduser("~"), "Documents", f"{rs.name}.json")
        p, _ = QFileDialog.getSaveFileName(self, "导出分类规则", start, "分类规则 (*.json)")
        if not p:
            return
        data = dict(format=RULES_FILE_FORMAT, version=1, name=rs.name, rules=rs.rows())
        try:
            with open(p, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=1)
        except OSError as e:
            self.show_toast(f"导出失败：{e.strerror or e}")
            return
        self.show_toast("已导出到 " + p)

    def import_rules(self):
        p, _ = QFileDialog.getOpenFileName(self, "导入分类规则", os.path.join(os.path.expanduser("~"), "Documents"),
                                           "分类规则 (*.json)")
        if not p:
            return
        norm, name, err = read_rules_file(p)
        if err:
            self.show_toast("无法导入：" + err)
            return
        box = QCheckBox(f"替换正在编辑的“{self.edit_rs().name}”（载入到编辑器，检查后点“保存规则”才生效）")
        d = Dialog(self, "导入分类规则",
                   f"从“{os.path.basename(p)}”读到 {len(norm)} 个分类：\n" + "、".join(r[0] for r in norm)
                   + "\n\n默认导入为一个新的规则方案，名称：", ok="导入", edit=self.free_scheme_name(name), extra=box,
                   validate=lambda: "" if box.isChecked() else self.scheme_name_problem(d.value()))
        if not d.exec():
            return
        if box.isChecked():
            for r in list(self.rule_rows):
                r["w"].deleteLater()
            self.rule_rows.clear()
            cats = self.edit_rs().cats
            for r in norm:
                self.add_rule_row(r[0], r[1], r[0] if r[0] in cats else None, r[2] if len(r) > 2 else "")
            self.show_toast("已载入，检查后点“保存规则”生效")
            return
        n = d.value().strip()
        if self.scheme_name_problem(n):
            self.show_toast(self.scheme_name_problem(n))
            return
        self.cfg["schemes"].append(dict(name=n, rules=norm))
        save_cfg(self.cfg)
        apply_schemes(self.cfg)
        self.rule_scheme = n
        log("导入规则方案：" + n)
        self.rebuild_settings()
        self.show_toast(f"已导入为“{n}”，可在“管理的文件夹”里给文件夹选用")

    def set_folder_scheme(self, path, name):
        for lst in (self.cfg["folders"], EXTRA):
            for f in lst:
                if _norm(f["path"]) == _norm(path):
                    f["scheme"] = name or ""
        save_cfg(self.cfg)
        log(f"{os.path.basename(path)} 改用规则：{name or PRIMARY_SCHEME}")
        self.categories_changed()
        self.show_toast(f"已改用“{name or PRIMARY_SCHEME}”；已经整理好的文件不会自动挪动，"
                        "可以在“分类规则”里点“按当前规则重新整理已有文件”")

    def refresh_loc_box(self):
        """主页的文件夹下拉框：只有管理了其他文件夹时才显示。"""
        b = self.loc_box
        b.blockSignals(True)
        b.clear()
        b.addItem("全部文件夹", None)
        b.addItem(f"{os.path.basename(ROOT) or ROOT}（主文件夹）", ROOT)
        b.setItemData(1, ROOT, Qt.ItemDataRole.ToolTipRole)
        for f in EXTRA:
            b.addItem(os.path.basename(f["path"]) or f["path"], f["path"])
            b.setItemData(b.count() - 1, f["path"], Qt.ItemDataRole.ToolTipRole)
        i = b.findData(self.loc) if self.loc else 0
        if i < 0:
            self.loc, i = None, 0
        b.setCurrentIndex(i)
        b.blockSignals(False)
        self.btn_root.setToolTip("在资源管理器中打开：" + (self.loc or ROOT))
        self.update_loc_btn()

    def update_loc_btn(self):
        if not hasattr(self, "btn_loc"):
            return
        if self.loc:
            name = os.path.basename(self.loc.rstrip("\\/")) or self.loc
            self.btn_loc.text_ = name + ("（主）" if self.loc == ROOT and EXTRA else "")
        else:
            self.btn_loc.text_ = "全部文件夹" if EXTRA else (os.path.basename(ROOT.rstrip("\\/")) or ROOT)
        where = self.loc or ("全部管理的文件夹" if EXTRA else ROOT)
        self.btn_loc.tip = f"正在查看：{where}\n点击切换文件夹"
        self.btn_loc.update()

    def loc_menu(self):
        m = QMenu(self)
        b = self.loc_box
        for i in range(b.count()):
            if i == 0 and not EXTRA:
                continue                       # 只管理一个文件夹时，“全部文件夹”就是它
            a = m.addAction(b.itemText(i), lambda i=i: b.setCurrentIndex(i))
            a.setCheckable(True)
            a.setChecked(i == b.currentIndex() or (not EXTRA and i == 1))
            if b.itemData(i):
                a.setToolTip(b.itemData(i))
        m.addSeparator()
        m.addAction("添加 / 管理文件夹…", lambda: (self.open_settings(), self.show_settings_tab("管理的文件夹")))
        m.setToolTipsVisible(True)
        m.exec(self.btn_loc.mapToGlobal(QPoint(0, self.btn_loc.height() + 2)))

    def on_loc_changed(self, i):
        self.loc = self.loc_box.itemData(i)
        self.browse = None
        self.update_loc_btn()
        self.btn_root.setToolTip("在资源管理器中打开：" + (self.loc or ROOT))
        self.build_cat_buttons()
        if self.cur not in self.cat_btns:
            self.cur = "全部文件"
        on_list = self.pages.currentIndex() == 0
        for k, b in self.cat_btns.items():
            b.setChecked(on_list and k == self.cur)
        self.refresh_counts()
        self.refresh_stats()
        self.fill()

    def build_cat_buttons(self):
        for c, b in self.cat_btns.items():
            if c == RECENT:                # 单独的“最近添加”按钮不在分类区里，不重建
                continue
            self.side_btns.remove(b)
            self.cat_box.removeWidget(b)
            b.hide()                       # deleteLater 要等事件循环处理，先隐藏，避免新旧按钮叠在一起
            b.deleteLater()
        self.cat_btns = {RECENT: self.btn_recent}
        loc = getattr(self, "loc", None)
        for c in ["全部文件"] + (cats_for(loc) if loc else all_cats()) + ["未整理"]:
            b = self.side_item(GLYPH.get(c, FOLDER_GLYPH), c, lambda _=None, c=c: self.select_cat(c), True, self.cat_box)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.expanded = getattr(self, "side_open", True)
            self.cat_btns[c] = b

    def rebuild_settings(self):
        """重新生成设置页（分类说明、规则列表、受保护分类、管理的文件夹都由它显示），保留滚动位置。"""
        old = self.pages.widget(1)
        tab = self.settings_stack.currentIndex()
        pos = self.settings_scrolls[tab].verticalScrollBar().value()
        showing = self.pages.currentIndex() == 1
        page = self.build_settings()
        self.show_settings_tab(tab)
        for w in page.findChildren((QPushButton, QComboBox, QCheckBox, QSlider)):
            w.setCursor(Qt.CursorShape.PointingHandCursor)
        self.pages.insertWidget(1, page)
        self.pages.removeWidget(old)
        old.deleteLater()
        if showing:
            self.pages.setCurrentIndex(1)
            self.log_view.setPlainText("\n".join(LOGS) or "暂无记录")
        QTimer.singleShot(0, lambda: self.settings_scrolls[tab].verticalScrollBar().setValue(pos))

    def show_settings_tab(self, i):
        if isinstance(i, str):
            i = next(k for k, b in enumerate(self.settings_tabs) if b.text() == i)
        self.settings_stack.setCurrentIndex(i)
        for k, b in enumerate(self.settings_tabs):
            b.setChecked(k == i)
        if self.settings_tabs[i].text() == "移动记录" and hasattr(self, "journal_tree"):
            self.fill_journal()

    def categories_changed(self, renames=None):
        """分类规则或管理的文件夹变了：重建左侧分类按钮、设置页，重新扫描。"""
        cur = (renames or {}).get(self.cur, self.cur)
        self.refresh_loc_box()
        self.build_cat_buttons()
        self.rebuild_settings()
        if cur not in self.cat_btns:
            cur = "全部文件"
        self.cur = cur
        on_list = self.pages.currentIndex() == 0
        for k, b in self.cat_btns.items():
            b.setChecked(on_list and k == cur)
        self.sig = None
        self.tick()

    def choose_root(self, reset):
        global ROOT
        if reset:
            p = ""
        else:
            p = QFileDialog.getExistingDirectory(self, "选择要管理的文件夹", ROOT)
            if not p:
                return
            err = root_problem(p)
            if err:
                self.show_toast(err)
                return
            p = os.path.abspath(p)
        target = p or downloads_dir()
        if _norm(target) == _norm(ROOT):
            self.show_toast("已经在管理这个文件夹")
            return
        t = _norm(target)
        for f in EXTRA:
            n = _norm(f["path"])
            if t == n or t.startswith(n + os.sep) or n.startswith(t + os.sep):
                self.show_toast("这个位置和“其他文件夹”里的 " + f["path"] + " 重叠，请先把它移除")
                return
        if Dialog(self, "更改管理的文件夹",
                  f"改为管理：\n{target}\n\n开启自动整理时，这个文件夹最外层的文件会被移进分类文件夹；"
                  f"原来文件夹里已整理的文件保持不动。确定更改？", ok="更改").exec():
            self.cfg["root"] = p
            save_cfg(self.cfg)
            # 热切换：停止监视旧文件夹，界面和监视列表都按新文件夹重建
            if self.watcher.directories():
                self.watcher.removePaths(self.watcher.directories())
            self.retry_timer.stop()
            ROOT = resolve_root(self.cfg)
            self.items = []
            self.btn_root.setToolTip("在资源管理器中打开：" + ROOT)
            log("改为管理：" + ROOT)
            self.categories_changed()
            self.show_toast("已改为管理：" + ROOT)

    # ---------- 其他管理的文件夹 ----------
    def folder_status(self, f):
        if not os.path.isdir(f["path"]):
            return "未连接：移动硬盘没插上或网络断开，连接后自动恢复整理"
        err = extra_problem(f["path"], [x["path"] for x in self.cfg["folders"] if x is not f])
        if err:
            return "已暂停：" + err
        return "正常" + ("，自动整理新文件" if f.get("auto", True) else "，不自动整理")

    def add_folder_row(self, layout, f):
        box = QFrame(objectName="card")
        v = QVBoxLayout(box)
        v.setContentsMargins(12, 8, 12, 8)
        v.setSpacing(4)
        name = QLabel(f["path"])
        name.setWordWrap(True)
        v.addWidget(name)
        v.addWidget(QLabel(self.folder_status(f), objectName="hint"))
        r0 = QHBoxLayout()
        r0.addWidget(QLabel("分类规则"))
        sc = QComboBox()
        sc.addItem(PRIMARY_SCHEME + "（和主文件夹一样）", "")
        for n in SCHEMES:
            sc.addItem(n, n)
        sc.setCurrentIndex(max(0, sc.findData(f.get("scheme") or "")))
        sc.setMinimumWidth(200)
        sc.currentIndexChanged.connect(lambda i, p=f["path"], sc=sc: self.set_folder_scheme(p, sc.itemData(i)))
        r0.addWidget(sc)
        b_ed = QPushButton("编辑规则…")
        b_ed.clicked.connect(lambda _=None, sc=sc: (self.switch_scheme(sc.currentData(), ask=True),
                                                    self.show_settings_tab("分类规则")))
        b_nw = QPushButton("为它新建规则…")
        b_nw.setToolTip("复制主文件夹规则作为这个文件夹专用的方案，之后单独修改")
        b_nw.clicked.connect(lambda _=None, p=f["path"]: self.new_scheme_for(p))
        r0.addWidget(b_ed)
        r0.addWidget(b_nw)
        r0.addStretch()
        v.addLayout(r0)
        r = QHBoxLayout()
        sw = Switch()
        sw.setChecked(f.get("auto", True))
        sw.toggled.connect(lambda on, p=f["path"]: self.set_folder_opt(p, "auto", on))
        r.addWidget(sw)
        r.addWidget(QLabel("自动整理新文件"))
        r.addSpacing(14)
        cb = QCheckBox("参与自动清理")
        cb.setToolTip("勾选后，“自动清理”的天数 / 容量规则也会清理这个文件夹里已整理的文件（进入回收站）")
        cb.setChecked(bool(f.get("clean")))
        cb.toggled.connect(lambda on, p=f["path"]: self.set_folder_opt(p, "clean", on))
        r.addWidget(cb)
        r.addStretch()
        b_ex = QPushButton("整理现有文件…")
        b_ex.setEnabled(os.path.isdir(f["path"]))
        b_ex.clicked.connect(lambda _=None, p=f["path"]: self.organize_existing(p))
        b_open = QPushButton("打开")
        b_open.setEnabled(os.path.isdir(f["path"]))
        b_open.clicked.connect(lambda _=None, p=f["path"]: os.startfile(p))
        b_rm = QPushButton("移除")
        b_rm.clicked.connect(lambda _=None, p=f["path"]: self.remove_folder(p))
        for b in (b_ex, b_open, b_rm):
            r.addWidget(b)
        v.addLayout(r)
        layout.addWidget(box)

    def new_scheme_for(self, path):
        """给某个其他文件夹建一套专用规则（从它当前使用的规则复制）并切过去编辑。"""
        rs = ruleset_for(path)
        if self.new_scheme(rs.rows(), os.path.basename(path) + " 的规则"):
            self.set_folder_scheme(path, self.rule_scheme)
            self.show_settings_tab("分类规则")

    def add_folder(self):
        p = QFileDialog.getExistingDirectory(self, "添加要整理的文件夹", os.path.expanduser("~"))
        if not p:
            return
        p = os.path.abspath(p)
        err = extra_problem(p, [f["path"] for f in self.cfg["folders"]])
        if err:
            self.show_toast("不能添加：" + err)
            return
        if not Dialog(self, "添加文件夹",
                      f"开始整理：\n{p}\n\n之后出现在这个文件夹最外层的新文件，会放进其中的“{EXTRA_SUB}\\分类\\”里。"
                      "现在已经在里面的文件不会动；如果也想整理，可以之后点“整理现有文件…”预览后再决定。"
                      "\n\n子文件夹、快捷方式、程序和配置文件始终不会动。", ok="添加").exec():
            return
        self.cfg["folders"].append(dict(path=p, auto=True, clean=False, added=time.time()))
        save_cfg(self.cfg)
        apply_folders(self.cfg)
        log("开始整理文件夹：" + p)
        self.categories_changed()
        self.show_toast("已添加：" + os.path.basename(p))

    def remove_folder(self, path):
        if not Dialog(self, "移除文件夹",
                      f"不再整理：\n{path}\n\n已经整理进“{EXTRA_SUB}”的文件保持原样；"
                      "需要的话可以在“移动记录”里撤销，把它们移回原处。", ok="移除").exec():
            return
        self.cfg["folders"] = [f for f in self.cfg["folders"] if _norm(f["path"]) != _norm(path)]
        save_cfg(self.cfg)
        apply_folders(self.cfg)
        log("不再整理文件夹：" + path)
        self.categories_changed()
        self.show_toast("已移除：" + os.path.basename(path))

    def set_folder_opt(self, path, key, on):
        for lst in (self.cfg["folders"], EXTRA):
            for f in lst:
                if _norm(f["path"]) == _norm(path):
                    f[key] = bool(on)
        save_cfg(self.cfg)

    def save_extra_skip(self):
        text = " ".join(parse_exts(self.skip_edit.text()))
        self.cfg["extra_skip"] = "" if set(text.split()) == set(DEFAULT_EXTRA_SKIP.split()) else text
        save_cfg(self.cfg)
        apply_folders(self.cfg)
        self.skip_edit.setText(text or DEFAULT_EXTRA_SKIP)
        self.show_toast("已保存，其他文件夹里这些类型的文件不会被整理")

    def organize_existing(self, path):
        """预览其他文件夹最外层已有的文件，勾选确认后再整理。"""
        f = extra_cfg(path)
        if f is None or not os.path.isdir(path):
            self.show_toast("这个文件夹现在无法整理（未连接或已暂停）")
            return
        cands, _ = extra_candidates(f, time.time(), 0, journal.no_auto(), only_new=False)
        if not cands:
            self.show_toast("没有可以整理的文件（子文件夹、快捷方式、程序和配置文件都不会动）")
            return
        tree = QTreeWidget()
        tree.setHeaderLabels(["文件", "放进"])
        tree.setMinimumSize(620, 320)
        tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        tree.setRootIsDecorated(False)
        for c in sorted(cands, key=lambda c: (c[2], c[0].name.lower())):
            it = QTreeWidgetItem(tree, [c[0].name, f"{EXTRA_SUB}\\{c[2]}"])
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(0, Qt.CheckState.Checked)
            it.cand = c
        d = Dialog(self, "整理现有文件",
                   f"{path} 最外层有 {len(cands)} 个文件可以整理，会放进“{EXTRA_SUB}”里对应的分类。"
                   "取消勾选的文件保持原样；整理后可以在“移动记录”里一键撤销。", ok="整理", extra=tree)
        if not d.exec():
            return
        chosen = [tree.topLevelItem(i).cand for i in range(tree.topLevelItemCount())
                  if tree.topLevelItem(i).checkState(0) == Qt.CheckState.Checked]
        batch = journal.batch("整理现有文件：" + os.path.basename(path))
        moved = bad = 0
        for e, st, cat in chosen:
            try:
                folder = cat_dir(cat, st.st_mtime, path)
                os.makedirs(folder, exist_ok=True)
                dst = free_path(folder, e.name)
                os.rename(e.path, dst)
                batch.add(e.path, dst)
                log(f"整理：{e.name} → {os.path.basename(path)}\\{EXTRA_SUB}\\{cat}")
                moved += 1
            except OSError:
                bad += 1
        self.tick()
        self.show_toast(f"整理了 {moved} 个文件" + (f"，{bad} 个失败（可能正在使用）" if bad else ""))

    # ---------- 移动记录 ----------
    def fill_journal(self):
        t = self.journal_tree
        t.clear()
        bs = journal.batches(300)
        for b in bs:
            n = len(b["moves"])
            it = QTreeWidgetItem(t, [datetime.fromtimestamp(b["t"]).strftime("%m-%d %H:%M:%S"), b["label"],
                                     f"{n} 个", "已撤销" if b["undone"] else ""])
            it.batch = b
            for src, dst in b["moves"][:200]:
                ch = QTreeWidgetItem(it, ["", os.path.basename(src), "", ""])
                ch.setToolTip(1, f"原位置：{src}\n现在：{dst}")
            if n > 200:
                QTreeWidgetItem(it, ["", f"…还有 {n - 200} 个", "", ""])
        if not bs:
            QTreeWidgetItem(t, ["", "还没有移动记录", "", ""])

    def undo_selected(self, since):
        it = self.journal_tree.currentItem()
        while it is not None and it.parent() is not None:
            it = it.parent()
        b = getattr(it, "batch", None) if it is not None else None
        if b is None:
            self.show_toast("先在列表里选中一次操作")
            return
        if since:
            bs = journal.batches(10 ** 9)
            idx = next((i for i, x in enumerate(bs) if x["id"] == b["id"]), 0)
            todo = [x for x in bs[:idx + 1] if not x["undone"]]
            if not todo:
                self.show_toast("这之后的操作都已经撤销过了")
                return
            n = sum(len(x["moves"]) for x in todo)
            msg = (f"撤销从 {datetime.fromtimestamp(b['t']).strftime('%m-%d %H:%M')}“{b['label']}”到现在的 "
                   f"{len(todo)} 次操作，共 {n} 个文件 / 文件夹，全部移回原来的位置？")
        else:
            if b["undone"]:
                self.show_toast("这次操作已经撤销过了")
                return
            n = len(b["moves"])
            msg = f"把“{b['label']}”移动的 {n} 个文件 / 文件夹移回原来的位置？"
        msg += "\n\n原位置已有同名文件时会自动改名，不会覆盖。移回的文件之后不会再被自动整理。"
        if not Dialog(self, "撤销移动", msg, ok="撤销").exec():
            return
        # 文件夹监视占着目录句柄，Windows 下会让移动失败：先全部释放，扫描时再重新监视
        if self.watcher.directories():
            self.watcher.removePaths(self.watcher.directories())
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            if since:
                k, problems, _ = journal.undo_since(b["id"])
            else:
                k, problems = journal.undo(b["id"])
            remove_empty_dirs()
        finally:
            QApplication.restoreOverrideCursor()
        log(f"撤销：{b['label']}（移回 {k} 个）")
        self.sig = None
        self.tick()
        self.fill_journal()
        if problems:
            more = f"\n…还有 {len(problems) - 15} 条" if len(problems) > 15 else ""
            Dialog(self, "撤销完成", f"移回了 {k} 个。有 {len(problems)} 条需要注意：\n\n"
                   + "\n".join(problems[:15]) + more, ok="知道了").exec()
        else:
            self.show_toast(f"已撤销，移回了 {k} 个")

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

    # ---------- 帮助中心 ----------
    def build_help(self):
        page = QWidget(objectName="pageBody")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        top = QFrame(objectName="pageHead")
        head = QHBoxLayout(top)
        head.setContentsMargins(20, 10, 20, 10)
        head.addWidget(QLabel("帮助中心", objectName="pageTitle"))
        head.addStretch()
        sb = QFrame(objectName="searchBox")
        sh = QHBoxLayout(sb)
        sh.setContentsMargins(10, 0, 6, 0)
        sh.addWidget(QLabel("", objectName="searchIcon"))
        self.help_search = QLineEdit(objectName="search", placeholderText="搜索帮助，例如：密码、清理、规则")
        self.help_search.setClearButtonEnabled(True)
        self.help_search.textChanged.connect(self.filter_help)
        sh.addWidget(self.help_search)
        sb.setFixedWidth(300)
        head.addWidget(sb)
        b_tour = QPushButton("新手教程")
        b_tour.clicked.connect(lambda: self.start_tour())
        head.addWidget(b_tour)
        back = QPushButton("←  返回文件列表")
        back.clicked.connect(lambda: self.select_cat(self.cur))
        head.addWidget(back)
        outer.addWidget(top)
        body = QHBoxLayout()
        body.setContentsMargins(16, 14, 16, 16)
        body.setSpacing(12)
        nav = QFrame(objectName="card")
        nav.setFixedWidth(210)
        nl = QVBoxLayout(nav)
        nl.setContentsMargins(8, 10, 8, 10)
        nl.setSpacing(2)
        self.help_btns = {}
        for tid, title, _, _ in help_content.TOPICS:
            b = QPushButton(title, objectName="helpTopic")
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=None, t=tid: self.show_help_topic(t))
            nl.addWidget(b)
            self.help_btns[tid] = b
        self.help_empty = QLabel("没有找到相关帮助", objectName="hint")
        self.help_empty.setWordWrap(True)
        self.help_empty.hide()
        nl.addWidget(self.help_empty)
        nl.addStretch()
        body.addWidget(nav)
        card = QFrame(objectName="card")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(18, 12, 18, 12)
        self.help_view = QTextBrowser()
        self.help_view.setOpenExternalLinks(True)
        self.help_view.setFrameShape(QFrame.Shape.NoFrame)
        self.help_view.setObjectName("helpView")
        self.help_view.setStyleSheet("font-family:'Segoe UI','Microsoft YaHei UI'; font-size:14px; background:transparent;")
        cl.addWidget(self.help_view)
        body.addWidget(card, 1)
        outer.addLayout(body, 1)
        self.help_topic = help_content.TOPICS[0][0]
        return page

    def open_help(self, topic=None):
        for b in self.cat_btns.values():
            b.setChecked(False)
        self.btn_settings.setChecked(False)
        self.btn_appear.setChecked(False)
        self.btn_help.setChecked(True)
        self.pages.setCurrentIndex(3)
        self.show_help_topic(topic or self.help_topic)

    def show_help_topic(self, tid):
        topic = next((t for t in help_content.TOPICS if t[0] == tid), help_content.TOPICS[0])
        self.help_topic = topic[0]
        for k, b in self.help_btns.items():
            b.setChecked(k == topic[0])
        html = topic[3].replace("{A}", C("accent")).replace("{M}", C("muted"))
        self.help_view.setHtml("<div style=\"line-height:150%; font-size:14px; font-family:'Segoe UI','Microsoft YaHei UI',"
                               f"'Microsoft YaHei'\">{html}</div>")

    def filter_help(self, text):
        """按标题、关键词和正文搜索；多个词用空格分开，全部包含才算匹配。"""
        words = text.lower().split()
        first = None
        for tid, title, kws, html in help_content.TOPICS:
            plain = re.sub(r"<[^>]+>", "", html)
            hay = (title + " " + kws + " " + plain).lower()
            ok = all(w in hay for w in words)
            self.help_btns[tid].setVisible(ok)
            if ok and first is None:
                first = tid
        self.help_empty.setVisible(first is None)
        if first is not None and not self.help_btns[self.help_topic].isVisible():
            self.show_help_topic(first)

    # ---------- 新手教程 ----------
    def maybe_tour(self):
        if not self.cfg.get("tour_done") and self.isVisible() and self.tour is None:
            self.start_tour()

    def start_tour(self):
        if self.tour is not None:
            self.tour.raise_()
            return
        self.show_main() if not self.isVisible() else None
        self.tour = TourDialog(self)
        self.tour.go(0)
        self.tour.show()

    def tour_target(self, where):
        """切到教程这一步要介绍的页面，返回要高亮的控件。"""
        if where.startswith("settings:"):
            self.open_settings()
            self.show_settings_tab(where.split(":", 1)[1])
            return self.settings_stack
        if where == "help":
            self.open_help("start")
            return self.btn_help
        if where == "sidemode":
            return self.title.mode_btns["open"].parentWidget()
        self.select_cat(RECENT if where == "recent" else
                        self.cur if self.pages.currentIndex() == 0 and self.cur != RECENT else "全部文件")
        return {"organize": self.auto_switch.parentWidget(), "search": self.search_box, "list": self.tree,
                "clean": self.btn_clean, "folder": self.btn_loc, "recent": self.btn_recent}.get(where)

    def tour_highlight(self, w):
        if w is None or not w.isVisible():
            self.tour_ring.hide()
            return
        r = w.rect().translated(w.mapTo(self, QPoint(0, 0)))
        self.tour_ring.setGeometry(r.adjusted(-5, -5, 5, 5))
        self.tour_ring.raise_()
        self.tour_ring.show()

    def end_tour(self):
        self.tour_ring.hide()
        self.tour = None
        self.set_cfg("tour_done", True)

    # ---------- 外观页 ----------
    def open_appearance(self):
        for b in self.cat_btns.values():
            b.setChecked(False)
        self.btn_settings.setChecked(False)
        self.btn_appear.setChecked(True)
        self.btn_help.setChecked(False)
        self.sync_appearance_ui()
        self.pages.setCurrentIndex(2)

    def build_appearance(self):
        page = QWidget(objectName="pageBody")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        top = QFrame(objectName="pageHead")
        head = QHBoxLayout(top)
        head.setContentsMargins(20, 10, 20, 10)
        head.addWidget(QLabel("外观", objectName="pageTitle"))
        head.addStretch()
        reset = QPushButton("恢复默认外观")
        reset.clicked.connect(self.reset_appearance)
        head.addWidget(reset)
        back = QPushButton("←  返回文件列表")
        back.clicked.connect(lambda: self.select_cat(self.cur))
        head.addWidget(back)
        outer.addWidget(top)
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

        # 列表显示
        c = card("列表显示")
        r = QHBoxLayout()
        tv = QVBoxLayout()
        tv.setSpacing(0)
        tv.addWidget(QLabel("“最近添加”显示的时间范围"))
        h = QLabel("按文件到达这台电脑的时间计算；也可以右键左侧的“最近添加”快速修改", objectName="hint")
        h.setWordWrap(True)
        tv.addWidget(h)
        r.addLayout(tv, 1)
        self.s_recent = QComboBox()
        for d in RECENT_OPTIONS:
            self.s_recent.addItem("最近 " + days_label(d), d)
        self.s_recent.setCurrentIndex(RECENT_OPTIONS.index(self.cfg["recent_days"]))
        self.s_recent.currentIndexChanged.connect(lambda i: self.set_recent_days(RECENT_OPTIONS[i]))
        r.addWidget(self.s_recent)
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
        scan_invalidate(path)
        self.dirty = True
        self.fs_timer.start()

    def on_fs_settled(self):
        """文件夹变化稳定后：整理新文件；窗口可见才刷新列表，隐藏时只记下“需要刷新”。"""
        if self.cfg["auto"]:
            moved, retry = organize(self.cfg["settle_sec"], self.cfg["loose_dirs"])
            if moved and not self.isVisible():
                self.tray.showMessage(APP_NAME, "已整理：" + moved[0] if len(moved) == 1 else f"已整理 {len(moved)} 个新文件",
                                      self.app_icon, 3000)
            self.schedule_retry(retry)
        if self.isVisible():
            self.tick(organize_first=False, fresh=False)
        else:
            self.dirty = True
            self.ensure_root_watched()

    def ensure_root_watched(self):
        watched = set(self.watcher.directories())
        for r in roots():
            if r not in watched:
                self.watcher.addPath(r)

    def schedule_retry(self, sec):
        """安排下一次整理重试；已有更早的重试就保留更早的。"""
        if sec is None:
            return
        ms = max(500, int(sec * 1000))
        if not self.retry_timer.isActive() or self.retry_timer.remainingTime() > ms:
            self.retry_timer.start(ms)

    def tick(self, organize_first=True, fresh=True):
        """刷新列表。fresh=False 只用于文件夹变化通知：没有变化的目录复用缓存。"""
        if organize_first and self.cfg["auto"]:
            _, retry = organize(self.cfg["settle_sec"], self.cfg["loose_dirs"])
            self.schedule_retry(retry)
        if fresh:
            scan_invalidate()
        items, dirs = scan(use_cache=True)
        self.dirty = False
        # 同步监视列表（新建的“年-月”文件夹也要监视）
        watched = set(self.watcher.directories())
        want = set(dirs)
        if self.browse and not os.path.isdir(self.browse):
            self.browse = None                 # 文件夹已被删除 / 移走：回到分类
            self.sig = None
        if self.browse:
            want.add(self.browse)
        if want - watched:
            self.watcher.addPaths(list(want - watched))
        if watched - want:
            self.watcher.removePaths(list(watched - want))
        sig = (len(items), sum(x["size"] for x in items), max((x["mtime"] for x in items), default=0),
               hash(tuple(x["path"] for x in items)))
        refill = False
        if sig != self.sig:
            self.sig, self.items = sig, items
            self.refresh_counts()
            refill = True
        if self.browse:
            refill = self.load_browse() or refill
        if refill:
            self.fill()
        self.refresh_stats()

    def refresh_counts(self):
        counts = {}
        here = [x for x in self.items if not self.loc or x.get("root") == self.loc]
        for x in here:
            counts[x["cat"]] = counts.get(x["cat"], 0) + 1
        for c, b in self.cat_btns.items():
            b.count = len(here) if c == "全部文件" else counts.get(c, 0)
        if RECENT in self.cat_btns:
            since = time.time() - self.cfg["recent_days"] * DAY
            self.cat_btns[RECENT].count = sum(1 for x in here if x["arrived"] >= since)
            self.cat_btns[RECENT].update()
            b.update()
        self.cat_btns["未整理"].setVisible(counts.get("未整理", 0) > 0 or self.cur == "未整理")

    def refresh_stats(self):
        here = [x for x in self.items if not self.loc or x.get("root") == self.loc]
        self.st_count.setText(str(len(here)))
        self.st_size.setText(human(sum(x["size"] for x in here)))
        try:
            du = shutil.disk_usage(self.loc or ROOT)
            self.st_disk.setText(f"{human(du.free)} / {human(du.total)}")
            self.disk_bar.setValue(int((du.total - du.free) / du.total * 1000))
        except OSError:
            pass
        self.st_auto.setText("已开启" if self.cfg["auto"] else "已关闭")

    def icon_for(self, x, item=None):
        """图标缓存：同扩展名共用一个；exe 等按文件取图标；图片缩略图在后台逐批生成，不卡界面。"""
        if x.get("is_dir"):
            if "<dir>" not in self.icon_cache:
                self.icon_cache["<dir>"] = self.provider.icon(QFileIconProvider.IconType.Folder)
            return self.icon_cache["<dir>"]
        # “仅在线”的云盘文件不生成缩略图：读取内容会触发下载
        thumb = x["ext"] in THUMB_EXT and x["size"] < 30 * 1024 * 1024 and not x.get("cloud")
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

    _day = [0.0, None]       # [有效期到, (今天 0 点, 昨天 0 点, 6 天前 0 点, 本月 1 日 0 点)]

    @staticmethod
    def group_of(ts):
        """按日期分组。分界时间每天只算一次（几万个文件时逐个调用 datetime.now() 很慢）。"""
        day = Main._day
        if time.time() >= day[0]:
            t = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            day[1] = (t.timestamp(), (t - timedelta(days=1)).timestamp(), (t - timedelta(days=6)).timestamp(),
                      t.replace(day=1).timestamp())
            day[0] = (t + timedelta(days=1)).timestamp()
        t0, t1, t6, m1 = day[1]
        if ts >= t0:
            return "今天"
        if ts >= t1:
            return "昨天"
        if ts >= t6:
            return "最近 7 天"
        if ts >= m1:
            return "本月早些时候"
        d = datetime.fromtimestamp(ts)
        return f"{d.year} 年 {d.month} 月"

    def visible_items(self):
        words = self.search.text().lower().split()
        now = time.time()
        today0 = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        tf = TIME_FILTERS[self.time_box.currentIndex()][1] if hasattr(self, "time_box") else None
        sf = SIZE_FILTERS[self.size_box.currentIndex()][1] if hasattr(self, "size_box") else None

        browsing = bool(self.browse)
        recent = self.cur == RECENT and not browsing
        tk = self._tkey = "arrived" if recent else "mtime"
        since = now - self.cfg["recent_days"] * DAY

        def ok(x):
            if not browsing:
                if self.loc and x.get("root") != self.loc:
                    return False
                if recent:
                    if x["arrived"] < since:
                        return False
                elif self.cur != "全部文件" and x["cat"] != self.cur:
                    return False
            if words:
                low = x["name"].lower()
                inner = x.get("inner")
                if not all(w in low or (inner and any(w in i for i in inner)) for w in words):
                    return False
            if tf is not None:
                if tf == 0 and x[tk] < today0:
                    return False
                if tf > 0 and x[tk] < now - tf * 86400:
                    return False
                if tf < 0 and x[tk] >= now + tf * 86400:
                    return False
            if sf is not None and not (sf[0] <= x["size"] < sf[1]):
                return False
            return True
        key = self.cfg.get("sort_key", "time")
        order = {c: i for i, c in enumerate(all_cats() + ["未整理"])}
        kf = {"time": lambda x: x[tk], "name": lambda x: x["name"].lower(), "size": lambda x: x["size"],
              "cat": lambda x: order.get(x["cat"], 99),
              "ext": lambda x: (x["ext"], x["name"].lower())}[key]
        items = [x for x in (self.browse_items if browsing else self.items) if ok(x)]
        if browsing:       # 文件夹里：子文件夹排在文件前面（和资源管理器一样）
            items.sort(key=kf, reverse=self.cfg.get("sort_desc", True))
            return sorted(items, key=lambda x: not x.get("is_dir"))
        if key == "cat":   # 分类内部按时间新→旧
            items.sort(key=lambda x: -x[tk])
            return sorted(items, key=kf, reverse=self.cfg.get("sort_desc", True))
        return sorted(items, key=kf, reverse=self.cfg.get("sort_desc", True))

    def group_key(self, x):
        k = self.cfg.get("sort_key", "time")
        if self.browse:
            return None                        # 文件夹里不分组，和资源管理器一样
        if k == "time":
            return self.group_of(x[getattr(self, "_tkey", "mtime")])
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
        names = list(COL_NAMES)
        arrived = getattr(self, "_tkey", "mtime") == "arrived"
        if arrived:
            names[3] = "添加时间"
        ti = [k for _, k in SORTS].index("time")
        self.sort_box.setItemText(ti, "添加时间" if arrived else SORTS[ti][0])
        labels = [n + ((" ↓" if desc else " ↑") if k == key else "") for n, k in zip(names, COL_KEYS)]
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
        FileItem.muted = QBrush(muted)
        fmt = self.__dict__.setdefault("fmt_cache", {})
        if len(fmt) > 2 * len(self.items) + 1000:
            fmt.clear()                        # 文件大量变化后丢掉旧的缓存
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
            tv = x[self._tkey]
            fk = (x["path"], tv, x["size"])
            ts = fmt.get(fk)
            if ts is None:                     # 格式化好的大小和时间缓存起来：重新扫描、搜索、筛选时不用再算
                ts = fmt[fk] = (human(x["size"]), datetime.fromtimestamp(tv).strftime("%Y-%m-%d %H:%M"))
            it = FileItem([f"{x['name']}  ·  {x['count']} 个文件" if x.get("is_dir") else x["name"],
                           x["cat"], ts[0], ts[1]])
            it.setIcon(0, self.icon_for(x, it))
            it.setData(0, Qt.ItemDataRole.UserRole, x["path"])
            it.setToolTip(0, x["path"] + (f"\n文件夹：{x['count']} 个文件，{ts[0]}。双击打开"
                                          if x.get("is_dir") else ""))
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
        total = sum(x["size"] for x in view)
        q = f" · 搜索“{self.search.text()}”" if self.search.text() else ""
        self.b_back.setVisible(bool(self.browse))
        if self.browse:
            # 文件夹名可能很长：超出部分用“…”省略，不把右边的按钮和搜索框挤出窗口
            el = Qt.TextElideMode.ElideMiddle
            name = os.path.basename(self.browse)
            self.page_title.setText(self.page_title.fontMetrics().elidedText(name, el, 300))
            self.page_title.setToolTip(name)
            rel = " › ".join(os.path.relpath(os.path.dirname(self.browse), cat_base(root_of(self.browse) or ROOT)).split(os.sep))
            tail = f" · {len(view)} 项 · {human(total)}" + q
            fm = self.page_sub.fontMetrics()
            self.page_sub.setText(fm.elidedText(rel, el, max(60, 250 - fm.horizontalAdvance(tail))) + tail)
            self.page_sub.setToolTip(self.browse)
        else:
            self.page_title.setText(self.cur)
            self.page_title.setToolTip("")
            self.page_sub.setText(f"{len(view)} 个文件 · {human(total)}"
                                  + (" · 按添加时间" if self.cur == RECENT else "") + q)
            self.page_sub.setToolTip("")
        self.btn_root.setToolTip("在资源管理器中打开：" + (self.browse or self.loc or ROOT))
        if not view:
            ph = QTreeWidgetItem(self.tree, ["没有找到文件" if self.search.text() else
                                             ("这个文件夹是空的" if self.browse else
                                              f"最近 {days_label(self.cfg['recent_days'])}没有新文件"
                                              if self.cur == RECENT else "这里还没有文件")])
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
        for b in (self.b_open, self.b_reveal, self.b_move, self.b_arch, self.b_delete):
            b.setEnabled(n > 0)
        self.b_rename.setEnabled(n == 1)
        self.sel_hint.setText(f"已选 {n} 项 · 可直接拖到其他程序" if n else
                              "双击打开 · Backspace 返回上一级 · 右键更多操作" if self.browse else
                              "双击打开 · 右键更多操作 · 可多选")

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
        s = self.selected()
        if len(s) == 1 and os.path.isdir(s[0]):
            self.enter_folder(s[0])
            return
        for p in s[:10]:
            self.open_path(p)

    # ---------- 在应用内打开文件夹 ----------
    def load_browse(self):
        """重新读取正在看的文件夹；内容有变化时返回 True。"""
        top = next((x for x in self.items if x["path"] == self.browse_top), None)
        cat = top["cat"] if top else ""
        root = top["root"] if top else (root_of(self.browse) or ROOT)
        items = list_folder(self.browse, cat, root)
        sig = tuple((x["path"], x["size"], x["mtime"]) for x in items)
        if sig == self.browse_sig:
            return False
        self.browse_items, self.browse_sig = items, sig
        return True

    def enter_folder(self, path):
        if not os.path.isdir(path):
            self.show_toast("文件夹已不存在")
            return
        if not self.browse:
            self.browse_top = path             # 列表里那一行对应的文件夹：从这里返回就回到分类
        self.browse, self.browse_sig = path, None
        self.watcher.addPath(path)
        self.load_browse()
        if self.search.text():
            self.search.blockSignals(True); self.search.clear(); self.search.blockSignals(False)
        self.tree.verticalScrollBar().setValue(0)
        self.fill()
        self.tree.verticalScrollBar().setValue(0)
        self.tree.setFocus()

    def browse_back(self):
        if not self.browse:
            return
        came_from = self.browse
        if _norm(self.browse) == _norm(self.browse_top or "") or not self.browse_top:
            self.browse = None
            self.browse_items, self.browse_sig = [], None
        else:
            self.browse, self.browse_sig = os.path.dirname(self.browse), None
            self.load_browse()
        self.fill()
        for i in range(self.tree.topLevelItemCount()):    # 选中刚才所在的文件夹，方便继续操作
            top = self.tree.topLevelItem(i)
            for it in [top] + [top.child(j) for j in range(top.childCount())]:
                if it.data(0, Qt.ItemDataRole.UserRole) == came_from:
                    self.tree.setCurrentItem(it)
                    self.tree.scrollToItem(it)
                    return

    def open_first(self):
        v = self.visible_items()
        if v:
            self.open_path(v[0]["path"])

    def reveal_selected(self):
        s = self.selected()
        if s:
            reveal_in_explorer(s[0])

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
            err = bad_filename(new)
            if err:
                self.show_toast(err)
                return
            try:
                dst = os.path.join(os.path.dirname(s[0]), new)
                if os.path.exists(dst) and os.path.normcase(dst) != os.path.normcase(s[0]):
                    self.show_toast("已有同名文件")
                    return
                os.rename(s[0], dst)
                log(f"重命名：{old} → {new}")
                # 新名字按规则属于另一个分类（改了扩展名，或加上 / 去掉了关键词）：放到新分类里
                r = root_of(s[0]) or ROOT
                parts = os.path.relpath(s[0], cat_base(r)).split(os.sep)
                new_cat = category_for(new, r)
                if not self.browse and not os.path.isdir(dst) and len(parts) > 1 and parts[0] in cats_for(r) and parts[0] != new_cat \
                        and new_cat != category_for(old, r):
                    try:
                        move_to(dst, new_cat, journal.batch("重命名后换分类"))
                        remove_empty_dirs()
                        self.show_toast(f"按分类规则已移到“{new_cat}”")
                    except OSError:
                        self.show_toast("已重命名，但移到新分类失败")
            except OSError as e:
                self.show_toast(f"重命名失败：{e.strerror or e}")
            self.tick()

    def move_menu(self):
        m = QMenu(self)
        s = self.selected()
        rs = {root_of(p) or ROOT for p in s}
        for c in (cats_for(rs.pop()) if len(rs) == 1 else CATS):
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
        batch = journal.batch("移动到 " + (dest if not os.path.isabs(dest) else os.path.basename(dest) or dest))
        for p in s:
            try:
                move_to(p, dest, batch)
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
        if len(self.selected()) == 1 and os.path.isdir(self.selected()[0]):
            m.addAction("在资源管理器中打开", lambda p=self.selected()[0]: self.open_path(p))
        m.addAction("打开所在位置", self.reveal_selected)
        if len(self.selected()) == 1:
            m.addAction("重命名\tF2", self.rename_selected)
        mv = self.move_menu()
        mv.setTitle("移动到")
        m.addMenu(mv)
        m.addSeparator()
        self.add_print_actions(m)
        self.add_archive_actions(m)
        m.addSeparator()
        import converter_link   # 可选联动：装了「格式转换器」才会多出「转换为 ▸」
        converter_link.add_menu(m, self.selected(), self.show_toast)
        m.addAction("复制路径", lambda: QApplication.clipboard().setText("\n".join(self.selected())))
        dirs = [p for p in self.selected() if os.path.isdir(p)]
        if dirs:
            m.addAction("分析这个文件夹…" if len(dirs) == 1 else f"分析这 {len(dirs)} 个文件夹…",
                        lambda: self.analyze_folders(dirs))
        m.addSeparator()
        m.addAction("删除\tDel", self.delete_selected)
        m.exec(self.tree.viewport().mapToGlobal(pos))

    def do_organize(self, manual=False):
        # 手动“立即整理”：用户明确要求，只保留 3 秒的最短等待
        moved, retry = organize(3 if manual else self.cfg["settle_sec"], self.cfg["loose_dirs"],
                                "立即整理" if manual else "自动整理")
        self.schedule_retry(retry)
        self.tick()
        if manual:
            self.show_toast(f"整理了 {len(moved)} 个文件" if moved else "没有需要整理的文件")

    def reorganize_existing(self):
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            plan = plan_reorganize(self.cfg["protect"])
        finally:
            QApplication.restoreOverrideCursor()
        if not plan:
            self.show_toast("已整理的文件都符合当前规则，不需要挪动")
            return
        by = {}
        for _, a, b in plan:
            by[(a, b)] = by.get((a, b), 0) + 1
        lines = "\n".join(f"  {a} → {b}：{n} 个" for (a, b), n in sorted(by.items(), key=lambda t: -t[1])[:12])
        sample = "\n".join("  " + os.path.basename(p) for p, _, _ in plan[:6])
        msg = (f"按当前分类规则，有 {len(plan)} 个已整理的文件应换到别的分类：\n{lines}\n\n例如：\n{sample}"
               + ("\n  …" if len(plan) > 6 else "")
               + "\n\n只是在分类之间移动，不会删除任何文件。你手动移动过的文件也可能被移回规则对应的分类。")
        if not Dialog(self, "重新整理已有文件", msg, ok=f"移动 {len(plan)} 个文件").exec():
            return
        bad = 0
        batch = journal.batch("按规则重新整理")
        for p, _, new in plan:
            try:
                move_to(p, new, batch)
            except OSError:
                bad += 1
        remove_empty_dirs()
        self.tick()
        self.show_toast(f"已重新整理 {len(plan) - bad} 个文件" + (f"，{bad} 个失败（可能正在使用）" if bad else ""))

    # ---------- 打印 ----------
    @staticmethod
    def printers():
        """(打印机列表, 默认打印机)；默认的排在最前面。"""
        from PyQt6.QtPrintSupport import QPrinterInfo
        names = QPrinterInfo.availablePrinterNames()
        default = QPrinterInfo.defaultPrinterName()
        return sorted(names, key=lambda n: n != default), default

    def add_print_actions(self, m):
        s = self.selected()
        if not s:
            return
        ok = [p for p in s if shell_verb_ok(p, "print")]
        if not ok:
            a = m.addAction("快速打印（这种文件不能直接打印）")
            a.setEnabled(False)
            return
        names, default = self.printers()
        what = "" if len(ok) == len(s) else f" {len(ok)} 个可打印的文件"
        label = f"快速打印{what}" + (f"（{default}）" if default else "") + "\tCtrl+P"
        m.addAction(label, lambda: self.print_paths(ok))
        if names and all(shell_verb_ok(p, "printto") for p in ok):
            sub = m.addMenu("打印到")
            for n in names:
                sub.addAction(n + ("（默认）" if n == default else ""), lambda n=n: self.print_paths(ok, n))

    def print_selected(self):
        ok = [p for p in self.selected() if shell_verb_ok(p, "print")]
        if ok:
            self.print_paths(ok)
        elif self.selected():
            self.show_toast("选中的文件不能直接打印，请先打开再打印")

    def print_paths(self, paths, printer=None):
        """一个文件直接打印；多个文件先确认，避免误点浪费纸张。"""
        where = printer or self.printers()[1] or "默认打印机"
        if len(paths) > 1 and not Dialog(self, "打印", f"用“{where}”打印这 {len(paths)} 个文件？\n\n"
                                         + "\n".join("· " + os.path.basename(p) for p in paths[:8])
                                         + ("\n…" if len(paths) > 8 else ""), ok="打印").exec():
            return
        bad = 0
        for p in paths:
            if shell_print(p, printer):
                log(f"打印：{os.path.basename(p)} → {where}")
            else:
                bad += 1
        self.show_toast((f"已发送到“{where}”打印" if len(paths) == 1 else f"已把 {len(paths) - bad} 个文件发送到“{where}”")
                        + (f"，{bad} 个失败" if bad else "") if bad < len(paths) else "打印失败：打开这种文件的程序不支持直接打印")

    # ---------- 压缩 / 解压 ----------
    def archive_menu(self):
        m = QMenu(self)
        self.add_archive_actions(m)
        return m

    def add_archive_actions(self, m):
        s = self.selected()
        if not s:
            return
        arcs = [p for p in s if archive.is_archive(p)]
        if arcs:
            if len(arcs) == 1:
                m.addAction(f"解压到“{archive.archive_stem(arcs[0])}\\”", lambda: self.extract_paths(arcs, mode="folder"))
            else:
                m.addAction(f"把 {len(arcs)} 个压缩包分别解压到同名文件夹", lambda: self.extract_paths(arcs, mode="folder"))
            m.addAction("解压到当前文件夹", lambda: self.extract_paths(arcs, mode="here"))
            m.addAction("解压…（密码、位置等选项）", lambda: self.extract_dialog(arcs))
        fmt = self.cfg["zip_fmt"] if not archive.compress_problem(self.cfg["zip_fmt"]) else "zip"
        name = self.default_archive_name(s) + archive.FORMAT_EXT[fmt]
        m.addAction(f"压缩为“{name}”", lambda: self.start_compress(s, os.path.join(os.path.dirname(s[0]), name),
                                                                  fmt, int(self.cfg["zip_level"])))
        m.addAction("压缩…（格式、密码等选项）", lambda: self.compress_dialog(s))

    @staticmethod
    def default_archive_name(paths):
        first = os.path.basename(paths[0])
        stem = archive.archive_stem(first) if archive.is_archive(first) else os.path.splitext(first)[0]
        stem = stem or first
        return stem if len(paths) == 1 else f"{stem} 等 {len(paths)} 个文件"

    # 后台任务（同一时间只进行一个，进度显示在文件列表下方）
    def start_job(self, label, fn, on_done):
        if self.job is not None:
            self.show_toast("正在处理上一个压缩 / 解压任务，请稍候")
            return False
        w = ArchiveWorker(self, fn)
        self.job = w
        self.job_lbl.setText(label)
        self.job_prog.setRange(0, 0)                 # 还没有进度时显示“忙碌”动画
        self.job_cancel.setEnabled(True)
        self.job_bar.show()

        def prog(v, text):
            if self.job is w:
                self.job_prog.setRange(0, 100)
                self.job_prog.setValue(v)
                self.job_lbl.setText(f"{text}… {v}%")

        def done(res, err):
            if self.job is w:
                self.job = None
                self.job_bar.hide()
            on_done(res, err)
        w.progress.connect(prog)
        w.done.connect(done)
        w.finished.connect(w.deleteLater)
        w.start(QThread.Priority.LowPriority)
        return True

    def cancel_job(self):
        if self.job is not None:
            self.job.cancel.set()
            self.job_cancel.setEnabled(False)
            self.job_lbl.setText("正在取消…")

    # 压缩
    def compress_dialog(self, paths):
        w = QWidget()
        g = QGridLayout(w)
        g.setContentsMargins(0, 4, 0, 0)
        g.setHorizontalSpacing(10)
        g.setVerticalSpacing(8)
        name = QLineEdit(self.default_archive_name(paths))
        ext = QLabel()
        fmt = QComboBox()
        for f, _, text in archive.FORMATS:
            fmt.addItem(text, f)
            why = archive.compress_problem(f)
            if why:                                   # 当前环境做不到的格式：灰掉并说明原因
                it = fmt.model().item(fmt.count() - 1)
                it.setEnabled(False)
                it.setToolTip(why)
                fmt.setItemText(fmt.count() - 1, f"{text}（{why}）")
        i = fmt.findData(self.cfg["zip_fmt"])
        fmt.setCurrentIndex(i if i >= 0 and not archive.compress_problem(self.cfg["zip_fmt"]) else 0)
        level = QComboBox()
        for k, text in archive.LEVELS:
            level.addItem(text, k)
        level.setCurrentIndex(max(0, level.findData(int(self.cfg["zip_level"]))))
        pw1 = QLineEdit(placeholderText="不设密码请留空")
        pw2 = QLineEdit(placeholderText="再输入一次密码")
        for e in (pw1, pw2):
            e.setEchoMode(QLineEdit.EchoMode.Password)
        show = QCheckBox("显示密码")
        show.toggled.connect(lambda on: [e.setEchoMode(QLineEdit.EchoMode.Normal if on else QLineEdit.EchoMode.Password)
                                         for e in (pw1, pw2)])
        method = QComboBox()
        for k, text in ZIP_METHODS:
            method.addItem(text, k)
        method.setCurrentIndex(max(0, method.findData(self.cfg["zip_method"])))
        enc_names = QCheckBox("同时加密文件名（不输入密码就看不到压缩包里有哪些文件）")
        enc_names.setChecked(True)
        remove = QCheckBox("压缩完成后把原文件移到回收站")
        dest_dir = [os.path.dirname(paths[0])]
        dest_lbl = QLabel(objectName="hint")
        dest_lbl.setWordWrap(True)
        b_dest = QPushButton("更改…")

        def pick():
            d = QFileDialog.getExistingDirectory(self, "压缩包保存到", dest_dir[0])
            if d:
                dest_dir[0] = os.path.abspath(d)
                dest_lbl.setText(dest_dir[0])
        b_dest.clicked.connect(pick)
        dest_lbl.setText(dest_dir[0])

        def sync():
            f = fmt.currentData()
            ext.setText(archive.FORMAT_EXT[f])
            has_pw = bool(pw1.text())
            tar = f.startswith("tar")
            for x in (pw1, pw2, show):
                x.setEnabled(not tar)
            method.setEnabled(f == "zip" and has_pw)
            enc_names.setEnabled(f == "7z" and has_pw)
            enc_names.setVisible(f == "7z")
            method.setVisible(f == "zip")
            lbl_method.setVisible(f == "zip")
        rows = [("文件名", name, ext), ("格式", fmt, None), ("压缩级别", level, None), ("密码", pw1, None),
                ("确认密码", pw2, show), ("加密方式", method, None)]
        for r, (t, a, b) in enumerate(rows):
            lab = QLabel(t)
            g.addWidget(lab, r, 0)
            g.addWidget(a, r, 1)
            if b is not None:
                g.addWidget(b, r, 2)
            if t == "加密方式":
                lbl_method = lab
        g.addWidget(enc_names, len(rows), 1, 1, 2)
        g.addWidget(QLabel("保存到"), len(rows) + 1, 0)
        g.addWidget(dest_lbl, len(rows) + 1, 1)
        g.addWidget(b_dest, len(rows) + 1, 2)
        g.addWidget(remove, len(rows) + 2, 1, 1, 2)
        g.setColumnStretch(1, 1)
        fmt.currentIndexChanged.connect(sync)
        pw1.textChanged.connect(sync)
        sync()

        def validate():
            n = name.text().strip()
            f = fmt.currentData()
            err = bad_filename(n + archive.FORMAT_EXT[f]) if n else "请输入文件名"
            if err:
                return err
            pw = pw1.text() if not f.startswith("tar") else ""
            if pw != pw2.text() and not f.startswith("tar"):
                return "两次输入的密码不一样"
            return archive.compress_problem(f, pw, method.currentData())
        what = f"“{os.path.basename(paths[0])}”" if len(paths) == 1 else f"选中的 {len(paths)} 个文件"
        d = Dialog(self, "压缩", f"把{what}压缩成一个压缩包。", ok="压缩", extra=w, validate=validate)
        d.setMinimumWidth(560)
        if not d.exec():
            return
        f = fmt.currentData()
        pw = "" if f.startswith("tar") else pw1.text()
        dest = os.path.join(dest_dir[0], name.text().strip() + archive.FORMAT_EXT[f])
        self.start_compress(paths, dest, f, level.currentData(), pw, enc_names.isChecked(), method.currentData(),
                            remove.isChecked())

    def start_compress(self, paths, dest, fmt, level, password="", enc_names=False, method="aes", remove=False):
        paths = list(paths)

        def job(progress, cancel):
            return archive.compress(paths, dest, fmt, level, password, enc_names, method, progress, cancel)

        def done(res, err):
            if err is not None:
                self.show_toast("已取消压缩" if isinstance(err, archive.Cancelled) else f"压缩失败：{err}")
                return
            log(f"压缩：{len(paths)} 个文件 → {os.path.basename(res)}" + ("（已加密）" if password else ""))
            msg = f"已压缩为“{os.path.basename(res)}”"
            if remove:
                try:
                    recycle(paths)
                    msg += "，原文件已移到回收站"
                except OSError as e:
                    msg += f"，但原文件移到回收站失败：{e}"
            self.show_toast(msg)
            self.tick()
        return self.start_job(f"正在压缩为“{os.path.basename(dest)}”…", job, done)

    # 解压
    def extract_dialog(self, arcs):
        w = QWidget()
        g = QGridLayout(w)
        g.setContentsMargins(0, 4, 0, 0)
        g.setHorizontalSpacing(10)
        g.setVerticalSpacing(8)
        where = QComboBox()
        where.addItem("压缩包所在的文件夹", "")
        where.addItem("选择其他文件夹…", "pick")
        dest = [None]

        def pick(i):
            if where.itemData(i) != "pick":
                dest[0] = None
                return
            d = QFileDialog.getExistingDirectory(self, "解压到", os.path.dirname(arcs[0]))
            if not d:
                where.setCurrentIndex(0)
                return
            dest[0] = os.path.abspath(d)
            if where.count() > 2:
                where.removeItem(2)
            where.addItem(dest[0], "chosen")
            where.blockSignals(True)
            where.setCurrentIndex(2)
            where.blockSignals(False)
        where.currentIndexChanged.connect(pick)
        mode = QComboBox()
        for k, text in UNZIP_MODES:
            mode.addItem(text.replace("压缩包所在的文件夹", "目标文件夹"), k)
        mode.setCurrentIndex(max(0, mode.findData(self.cfg["unzip_mode"])))
        pw = QLineEdit(placeholderText="没有密码请留空；会自动尝试密码本里的密码")
        pw.setEchoMode(QLineEdit.EchoMode.Password)
        show = QCheckBox("显示")
        show.toggled.connect(lambda on: pw.setEchoMode(QLineEdit.EchoMode.Normal if on else QLineEdit.EchoMode.Password))
        save_pw = QCheckBox("把这个密码保存到密码本")
        over = QComboBox()
        for k, text in OVERWRITE_MODES:
            over.addItem(text, k)
        over.setCurrentIndex(max(0, over.findData(self.cfg["unzip_overwrite"])))
        open_ = QCheckBox("完成后打开文件夹")
        open_.setChecked(bool(self.cfg["unzip_open"]))
        rec = QCheckBox("解压成功后把压缩包移到回收站")
        rec.setChecked(bool(self.cfg["unzip_recycle"]))
        rows = [("解压到", where, None), ("方式", mode, None), ("密码", pw, show), ("同名文件", over, None)]
        for r, (t, a, b) in enumerate(rows):
            g.addWidget(QLabel(t), r, 0)
            g.addWidget(a, r, 1)
            if b is not None:
                g.addWidget(b, r, 2)
        for i, cb in enumerate((save_pw, open_, rec)):
            g.addWidget(cb, len(rows) + i, 1, 1, 2)
        g.setColumnStretch(1, 1)
        over.setEnabled(mode.currentData() == "here")
        mode.currentIndexChanged.connect(lambda _: over.setEnabled(mode.currentData() == "here"))
        what = f"“{os.path.basename(arcs[0])}”" if len(arcs) == 1 else f"选中的 {len(arcs)} 个压缩包"
        d = Dialog(self, "解压", f"解压{what}。", ok="解压", extra=w)
        d.setMinimumWidth(560)
        if not d.exec():
            return
        if pw.text() and save_pw.isChecked():
            self.add_pw(pw.text())
        self.extract_paths(arcs, mode=mode.currentData(), dest=dest[0], password=pw.text(),
                           overwrite=over.currentData(), open_after=open_.isChecked(), recycle_after=rec.isChecked())

    def extract_paths(self, arcs, mode=None, dest=None, password="", overwrite=None, open_after=None,
                      recycle_after=None):
        opts = dict(mode=mode or self.cfg["unzip_mode"], dest=dest, password=password,
                    overwrite=overwrite or self.cfg["unzip_overwrite"],
                    open=self.cfg["unzip_open"] if open_after is None else open_after,
                    recycle=self.cfg["unzip_recycle"] if recycle_after is None else recycle_after)
        self.run_extract(list(arcs), opts, password, [])

    def run_extract(self, queue, opts, first_pw, results):
        """依次解压 queue；遇到需要密码的压缩包时暂停，回到界面问密码，再从它继续。"""
        book = [p for p in [opts["password"]] + self.session_pws + self.pw_book() if p]
        book = list(dict.fromkeys(book))

        def job(progress, cancel):
            out = []
            for i, p in enumerate(queue):
                tag = f"（{len(results) + i + 1}/{len(results) + len(queue)}）" if len(queue) + len(results) > 1 else ""

                def prog(v, text, p=p, tag=tag):
                    progress(v, f"{text}{tag}“{os.path.basename(p)}”")
                try:
                    res, used = archive.extract(p, opts["dest"] or os.path.dirname(p), opts["mode"], opts["overwrite"],
                                                first_pw if i == 0 else "", book, prog, cancel,
                                                discard=recycle_old)
                except archive.PasswordError as e:
                    return dict(done=out, need_pw=i, msg=str(e))
                except archive.Cancelled:
                    raise
                except (archive.ArchiveError, OSError) as e:
                    out.append((p, None, str(e)))
                    continue
                out.append((p, res, used))
            return dict(done=out, need_pw=None)

        def done(res, err):
            if err is not None:
                if isinstance(err, archive.Cancelled):
                    self.show_toast("已取消解压")
                    self.finish_extract(results, opts, quiet=True)
                else:
                    self.show_toast(f"解压失败：{err}")
                return
            results.extend(res["done"])
            i = res["need_pw"]
            if i is not None:
                p = queue[i]
                pw, save = self.ask_password(p, res["msg"])
                if pw is None:
                    results.append((p, None, "没有输入密码，已跳过"))
                    rest, nxt = queue[i + 1:], ""
                else:
                    self.session_pws.insert(0, pw)
                    if save:
                        self.add_pw(pw)
                    rest, nxt = queue[i:], pw
                if rest:
                    self.run_extract(rest, opts, nxt, results)
                    return
            self.finish_extract(results, opts)
        label = f"正在解压“{os.path.basename(queue[0])}”…"
        if not self.start_job(label, job, done):
            return

    def finish_extract(self, results, opts, quiet=False):
        ok = [(p, r, used) for p, r, used in results if r]
        bad = [(p, msg) for p, r, msg in results if not r]
        for p, r, used in ok:
            rel = r[len(ROOT) + 1:] if _norm(r).startswith(_norm(ROOT) + os.sep) else r
            log(f"解压：{os.path.basename(p)} → {rel}" + ("（使用密码）" if used else ""))
        if ok and opts["recycle"]:
            try:
                recycle([v for p, _, _ in ok for v in archive.volumes(p)])
            except OSError as e:
                bad.append(("移到回收站", str(e)))
        if ok and opts["open"] and not quiet:
            r = ok[0][1] if len(ok) == 1 else (opts["dest"] or os.path.dirname(ok[0][0]))
            if os.path.isdir(r):
                self.open_path(r)
            else:
                reveal_in_explorer(r)
        self.tick()
        if bad and not quiet:
            Dialog(self, "解压", (f"已解压 {len(ok)} 个，" if ok else "") + f"{len(bad)} 个没有解压：\n\n"
                   + "\n".join(f"· {os.path.basename(p)}：{m}" for p, m in bad[:10]), ok="知道了").exec()
        elif ok and not quiet:
            self.show_toast(f"已解压到“{os.path.basename(ok[0][1])}”" if len(ok) == 1 and opts["mode"] != "here"
                            else f"已解压 {len(ok)} 个压缩包")

    def ask_password(self, path, msg):
        """返回 (密码, 是否保存到密码本)；取消返回 (None, False)。"""
        box = QWidget()
        h = QHBoxLayout(box)
        h.setContentsMargins(0, 0, 0, 0)
        show = QCheckBox("显示密码")
        save = QCheckBox("保存到密码本（以后自动尝试）")
        h.addWidget(show)
        h.addStretch()
        h.addWidget(save)
        d = Dialog(self, "需要密码", f"“{os.path.basename(path)}”{msg}。请输入解压密码：", ok="解压", edit="", extra=box,
                   validate=lambda: "" if d.edit.text() else "请输入密码")
        d.edit.setEchoMode(QLineEdit.EchoMode.Password)
        show.toggled.connect(lambda on: d.edit.setEchoMode(QLineEdit.EchoMode.Normal if on else QLineEdit.EchoMode.Password))
        self.show_main()
        if not d.exec() or not d.edit.text():
            return None, False
        return d.edit.text(), save.isChecked()

    # 密码本：用 Windows 账户加密（DPAPI）后保存在配置里，只有本人在这台电脑上能解开
    def pw_book(self):
        return [p for p in (archive.unprotect(t) for t in self.cfg.get("pw_book", [])) if p]

    def add_pw(self, pw):
        if pw and pw not in self.pw_book():
            try:
                self.cfg["pw_book"] = self.cfg.get("pw_book", []) + [archive.protect(pw)]
            except OSError:
                self.show_toast("无法加密保存密码")
                return
            save_cfg(self.cfg)
            self.update_pw_sub()

    def update_pw_sub(self):
        if hasattr(self, "pw_sub"):
            n = len(self.pw_book())
            self.pw_sub.setText((f"已保存 {n} 个密码；" if n else "还没有保存密码；")
                                + "解压加密的压缩包时自动依次尝试。密码用你的 Windows 账户加密保存在本机")

    def manage_pw_book(self):
        box = QWidget()
        v = QVBoxLayout(box)
        v.setContentsMargins(0, 0, 0, 0)
        lst = QVBoxLayout()
        lst.setSpacing(4)
        v.addLayout(lst)

        def refresh():
            while lst.count():
                it = lst.takeAt(0)
                if it.widget():
                    it.widget().deleteLater()
            tokens = list(self.cfg.get("pw_book", []))
            if not tokens:
                lst.addWidget(QLabel("还没有保存密码", objectName="hint"))
            for t in tokens:
                pw = archive.unprotect(t)
                row = QWidget()
                h = QHBoxLayout(row)
                h.setContentsMargins(0, 0, 0, 0)
                lab = QLabel("（无法解密：可能来自别的电脑或账户）" if pw is None else "•" * min(len(pw), 16))
                h.addWidget(lab, 1)
                if pw is not None:
                    b = QPushButton("显示")
                    b.clicked.connect(lambda _=None, lab=lab, pw=pw, b=b: (
                        lab.setText(pw if b.text() == "显示" else "•" * min(len(pw), 16)),
                        b.setText("隐藏" if b.text() == "显示" else "显示")))
                    h.addWidget(b)
                rm = QPushButton("删除")
                rm.clicked.connect(lambda _=None, t=t: remove(t))
                h.addWidget(rm)
                lst.addWidget(row)

        def remove(t):
            self.cfg["pw_book"] = [x for x in self.cfg.get("pw_book", []) if x != t]
            save_cfg(self.cfg)
            self.update_pw_sub()
            refresh()
        h = QHBoxLayout()
        e = QLineEdit(placeholderText="输入要保存的密码")
        b = QPushButton("添加")

        def add():
            if e.text():
                self.add_pw(e.text())
                e.clear()
                refresh()
        b.clicked.connect(add)
        h.addWidget(e, 1)
        h.addWidget(b)
        v.addLayout(h)
        refresh()
        Dialog(self, "解压密码本", "解压有密码的压缩包时，会先试你输入的密码，再依次试这里的密码。"
               "密码用你的 Windows 账户加密后保存在本机，换电脑或换账户后无法读取。", ok="完成", extra=box).exec()

    def run_task(self, key, fn, on_done):
        """后台运行 fn；同一个 key 的任务正在运行时不重复启动。返回是否已启动。"""
        tasks = self.__dict__.setdefault("_tasks", {})
        w = tasks.get(key)
        if w is not None and w.isRunning():
            return False
        w = TaskWorker(self, fn)

        def finish(res, err):
            tasks.pop(key, None)
            on_done(res, err)
        w.done.connect(finish)
        w.finished.connect(w.deleteLater)
        tasks[key] = w
        w.start(QThread.Priority.LowPriority)
        return True

    def clean_junk(self):
        stats = {}
        protect = list(self.cfg["protect"])
        if not self.run_task("junk", lambda: find_junk(protect, stats),
                             lambda res, err: self.on_junk_scanned(res, err, stats)):
            self.show_toast("正在扫描垃圾文件，请稍候…")
            return
        self.show_toast("正在后台扫描垃圾文件，可以继续使用…")

    def on_junk_scanned(self, junk, err, stats):
        if err is not None:
            self.show_toast(f"扫描失败：{err}")
            return
        skipped = (f"已跳过 {stats.get('projects', 0)} 个代码项目 / 程序文件夹（里面的内容不会动）。"
                   if stats.get("projects") else "")
        if not junk:
            self.show_toast("没有发现垃圾文件" + ("；" + skipped if skipped else ""))
            return
        tree = QTreeWidget()
        tree.setHeaderLabels(["文件", "大小"])
        tree.setMinimumSize(620, 320)
        tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        groups = {}
        for x in junk:
            key = x["reason"].split("（与“")[0]
            g = groups.get(key)
            if g is None:
                g = QTreeWidgetItem(tree, [key, ""])
                g.setFlags(g.flags() | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsAutoTristate)
                g.setCheckState(0, Qt.CheckState.Checked)
                g.total = 0
                groups[key] = g
            it = QTreeWidgetItem(g, [os.path.relpath(x["path"], ROOT), human(x["size"])])
            it.setToolTip(0, x["reason"] + "\n" + x["path"])
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(0, Qt.CheckState.Checked)
            it.junk = x
            g.total += x["size"]
        for name, g in groups.items():
            g.setText(0, f"{name}（{g.childCount()} 项）")
            g.setText(1, human(g.total))
        total = sum(x["size"] for x in junk)
        d = Dialog(self, "清理垃圾文件",
                   f"在 {ROOT} 里找到 {len(junk)} 项可以清理的内容，共 {human(total)}。{skipped}"
                   "取消勾选可以保留；确认后移入回收站，可以还原。", ok="移到回收站", danger=True, extra=tree)
        if not d.exec():
            return
        chosen = []
        for i in range(tree.topLevelItemCount()):
            g = tree.topLevelItem(i)
            for j in range(g.childCount()):
                c = g.child(j)
                if c.checkState(0) == Qt.CheckState.Checked:
                    chosen.append(c.junk)
        if not chosen:
            return
        self.show_toast(f"正在把 {len(chosen)} 项移到回收站…")
        self.run_task("junk_delete", lambda: delete_junk(chosen), self.on_junk_deleted)

    def on_junk_deleted(self, res, err):
        if err is not None:
            self.show_toast(f"清理失败：{err}")
            return
        n, freed, skipped = res
        self.tick()
        self.show_toast(f"清理了 {n} 项垃圾，释放 {human(freed)}"
                        + (f"；{skipped} 项无法放入回收站，已跳过" if skipped else ""))

    def analyze_folders(self, only=None):
        protect = list(self.cfg["protect"])
        if not self.run_task("analyze", lambda: analyze_dirs(protect, only), self.on_folders_analyzed):
            self.show_toast("正在分析文件夹，请稍候…")
            return
        self.show_toast("正在后台分析文件夹，可以继续使用…")

    def on_folders_analyzed(self, res, err):
        if err is not None:
            self.show_toast(f"分析失败：{err}")
            return
        if not res:
            self.show_toast("没有整个归档进来的文件夹需要分析")
            return
        tree = QTreeWidget()
        tree.setHeaderLabels(["文件夹", "大小", "说明"])
        tree.setMinimumSize(820, 380)
        h = tree.header()
        h.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        h.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        tree.setColumnWidth(0, 340)
        titles = {"delete": "建议删除", "maybe": "可以考虑删除（请自己判断）",
                  "fix": "可以理顺（可撤销）", "keep": "建议保留"}
        groups = {}
        for a in res:
            g = groups.get(a["level"])
            if g is None:
                g = QTreeWidgetItem(tree, [titles[a["level"]], "", ""])
                if a["level"] != "keep":
                    g.setFlags(g.flags() | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsAutoTristate)
                g.total, g.n = 0, 0
                groups[a["level"]] = g
            rel = os.path.relpath(a["path"], cat_base(a["root"]))
            it = QTreeWidgetItem(g, [rel, human(a["size"]), a["reason"]])
            it.setToolTip(0, f"{a['path']}\n{a['count']} 个文件")
            it.setToolTip(2, a["reason"])
            if a["level"] != "keep":
                it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                it.setCheckState(0, Qt.CheckState.Checked if a["level"] in ("delete", "fix")
                                 else Qt.CheckState.Unchecked)
            it.act = a
            g.total += a["size"]
            g.n += 1
        for lv, g in groups.items():
            g.setText(0, f"{titles[lv]}（{g.n} 个）")
            g.setText(1, human(g.total))
            g.setExpanded(lv != "keep")
        dels = sum(a["size"] for a in res if a["level"] == "delete")
        d = Dialog(self, "分析文件夹",
                   f"分析了 {len({a['path'] for a in res})} 个整个归档进来的文件夹。"
                   + (f"建议删除的共 {human(dels)}。" if dels else "")
                   + "勾选要处理的项：删除的进回收站，可以还原；理顺（移到正确分类、去掉多余的一层）可以在“移动记录”里撤销。"
                   "程序 / 绿色软件文件夹不会被建议删除或移动。", ok="处理所选", extra=tree)
        if not d.exec():
            return
        chosen = []
        for i in range(tree.topLevelItemCount()):
            g = tree.topLevelItem(i)
            for j in range(g.childCount()):
                c = g.child(j)
                if c.act["action"] and c.checkState(0) == Qt.CheckState.Checked:
                    chosen.append(c.act)
        if not chosen:
            return
        self.show_toast(f"正在处理 {len(chosen)} 项…")
        self.run_task("analyze_apply", lambda: apply_dir_actions(chosen), self.on_folder_actions_done)

    def on_folder_actions_done(self, res, err):
        if err is not None:
            self.show_toast(f"处理失败：{err}")
            return
        n, freed, fixed, problems = res
        self.tick()
        parts = []
        if n:
            parts.append(f"删除了 {n} 个文件夹，释放 {human(freed)}")
        if fixed:
            parts.append(f"理顺了 {fixed} 个文件夹")
        self.show_toast("；".join(parts or ["没有处理任何文件夹"]) + ("；" + "；".join(problems[:3]) if problems else ""))

    def clean_menu(self):
        m = QMenu(self)
        m.addAction("清理垃圾文件…（临时文件、重复副本、空文件夹等）", self.clean_junk)
        m.addAction("分析文件夹…（哪些可以删除、哪些可以理顺）", lambda: self.analyze_folders())
        m.addAction("按“自动清理”规则清理旧文件…", self.do_cleanup)
        m.addSeparator()
        m.addAction("清理设置…", lambda: (self.open_settings(), self.show_settings_tab("自动清理")))
        b = self.btn_clean
        m.exec(b.mapToGlobal(QPoint(b.width() + 4, 0)))

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
            if self.start_cleanup(manual=True):
                self.show_toast("正在后台清理…")

    def auto_cleanup(self):
        if self.cfg["clean_on"] or self.cfg["cap_on"]:
            self.start_cleanup(manual=False)

    def start_cleanup(self, manual):
        """启动后台清理；已有清理在运行时不重复启动。"""
        w = getattr(self, "_clean_worker", None)
        if w is not None and w.isRunning():
            if manual:
                self.show_toast("清理正在进行中，请稍候")
            return False
        w = CleanupWorker(self, self.cfg)
        w.done.connect(lambda n, freed, notes: self.on_cleanup_done(manual, n, freed, notes))
        w.finished.connect(w.deleteLater)
        self._clean_worker = w
        w.start(QThread.Priority.LowPriority)
        return True

    def on_cleanup_done(self, manual, n, freed, notes):
        self._clean_worker = None
        if manual:
            self.show_toast(f"清理了 {n} 个文件，释放 {human(freed)}" + ("；" + "；".join(notes) if notes else ""))
        else:
            fresh = notes != getattr(self, "_last_clean_notes", None)   # 同样的提醒不每 30 分钟重复弹
            self._last_clean_notes = notes
            if n or (notes and fresh):
                msg = f"自动清理了 {n} 个文件，释放 {human(freed)}" if n else "自动清理未删除文件"
                self.tray.showMessage(APP_NAME, msg + ("\n" + "\n".join(notes) if notes else ""), self.app_icon, 5000)
        if self.isVisible():
            self.tick()
        else:
            self.dirty = True
        if self.pages.currentIndex() == 1:
            self.log_view.setPlainText("\n".join(LOGS))

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
        QTimer.singleShot(600, self.maybe_tour)

    def quit(self):
        w = getattr(self, "_clean_worker", None)
        if w is not None and w.isRunning():
            w.wait(15000)          # 不在清理途中强行退出
        for t in list(self.__dict__.get("_tasks", {}).values()):
            if t.isRunning():
                t.wait(15000)
        if self.job is not None and self.job.isRunning():
            self.job.cancel.set()      # 压缩 / 解压中途退出：取消并清理临时文件
            self.job.wait(15000)
        self.thumbs.stop()
        self.tray.hide()
        QApplication.instance().quit()

    def closeEvent(self, e):
        if self.cfg["close"] == "tray":
            e.ignore()
            self.hide()
            if not self.told_tray:
                self.told_tray = True
                self.tray.showMessage(APP_NAME, "仍在后台运行，会继续自动整理。右键托盘图标可退出。", self.app_icon, 3000)
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
        if t in (ev.Type.MouseMove, ev.Type.HoverMove, ev.Type.Leave) and self.cfg.get("side_mode") == "auto" \
                and hasattr(self, "side_timer") and isinstance(obj, QWidget) and obj.window() is self:
            near = self.side_near(QCursor.pos())
            if near:
                self.side_timer.stop()
                if not self.side_open and not self.side_expand_timer.isActive():
                    self.side_expand_timer.start()
            else:
                self.side_expand_timer.stop()
                if self.side_open and not self.side_timer.isActive():
                    self.side_timer.start(700)
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


def current_user_id():
    """当前用户的 SID（拿不到时退回 域\\用户名）。"""
    try:
        adv = ctypes.windll.advapi32
        k32 = ctypes.windll.kernel32
        tok = wintypes.HANDLE()
        k32.GetCurrentProcess.restype = wintypes.HANDLE
        adv.OpenProcessToken.argtypes = (wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE))
        if adv.OpenProcessToken(k32.GetCurrentProcess(), 0x0008, ctypes.byref(tok)):   # TOKEN_QUERY
            try:
                need = wintypes.DWORD()
                adv.GetTokenInformation(tok, 1, None, 0, ctypes.byref(need))            # TokenUser
                buf = ctypes.create_string_buffer(need.value)
                if adv.GetTokenInformation(tok, 1, buf, need, ctypes.byref(need)):
                    psid = ctypes.cast(buf, ctypes.POINTER(ctypes.c_void_p))[0]
                    s = wintypes.LPWSTR()
                    if adv.ConvertSidToStringSidW(ctypes.c_void_p(psid), ctypes.byref(s)):
                        v = s.value
                        k32.LocalFree(s)
                        return v
            finally:
                k32.CloseHandle(tok)
    except Exception:
        pass
    return os.environ.get("USERDOMAIN", "") + "\\" + os.environ.get("USERNAME", "")


def instance_name():
    return "DownloadButler-" + hashlib.sha256(current_user_id().encode("utf-8")).hexdigest()[:16]


def main():
    # 命名互斥体：供安装 / 卸载程序检测本程序是否在运行
    ctypes.windll.kernel32.CreateMutexW(None, False, "DownloadButlerMutex")
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName(APP)
    # 单实例：再次启动时唤出已运行的窗口
    # Windows 命名管道是全机共享的：名字里带上当前用户，避免同一台电脑上不同用户的实例互相“唤出”后退出
    name = instance_name()
    sock = QLocalSocket()
    sock.connectToServer(name)
    if sock.waitForConnected(300):
        sock.write(b"show")
        sock.waitForBytesWritten(300)
        return
    QLocalServer.removeServer(name)
    server = QLocalServer()
    server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)   # 只允许当前用户连接
    server.listen(name)
    init_settings(load_cfg())
    w = Main(start_hidden="--min" in sys.argv)
    w.server = server
    server.newConnection.connect(lambda: (server.nextPendingConnection(), w.show_main()))
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
