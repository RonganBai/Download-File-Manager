# -*- coding: utf-8 -*-
"""检查更新 / 下载更新（GitHub Releases）。

只做网络与校验，不碰界面：
- check(current) 查询最新发布版，比当前版本新时返回更新信息，否则返回 None；
- download(info, dest) 下载安装包，校验大小与 SHA-256（GitHub 给每个附件算好的摘要）后才返回路径。
安全约束：只走 HTTPS；安装包地址必须是本项目 Releases 下的附件；没有 SHA-256 摘要的附件不自动安装。"""
import hashlib
import json
import os
import re
import urllib.error
import urllib.request

REPO = "RonganBai/Download-File-Manager"
API_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_URL = f"https://github.com/{REPO}/releases/latest"
ASSET_PREFIX = f"https://github.com/{REPO}/releases/download/"
ASSET_RE = re.compile(r"^DownloadButler-Setup-[0-9][0-9A-Za-z.\-]*\.exe$")
MAX_SIZE = 300 * 1024 * 1024          # 安装包不会这么大：超出视为异常
UA = "DownloadButler-Updater"


class UpdateError(Exception):
    pass


def parse_version(s):
    """'v2.10.1' → (2, 10, 1)；解析不了返回 None。"""
    m = re.fullmatch(r"[vV]?(\d+(?:\.\d+){0,3})", (s or "").strip())
    if not m:
        return None
    t = [int(x) for x in m.group(1).split(".")]
    return tuple(t + [0] * (4 - len(t)))


def is_newer(latest, current):
    a, b = parse_version(latest), parse_version(current)
    return a is not None and b is not None and a > b


def _get(url, timeout, accept="application/vnd.github+json"):
    if not url.startswith("https://"):
        raise UpdateError("只允许 HTTPS 连接")
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": accept})
    return urllib.request.urlopen(req, timeout=timeout)


def parse_release(data, current):
    """从 releases/latest 的 JSON 里取出更新信息；不比当前新、草稿 / 预发布时返回 None。"""
    if not isinstance(data, dict) or data.get("draft") or data.get("prerelease"):
        return None
    tag = str(data.get("tag_name") or "")
    if not is_newer(tag, current):
        return None
    info = dict(version=tag.lstrip("vV"), notes=str(data.get("body") or "").strip(),
                page=str(data.get("html_url") or RELEASES_URL), name="", url="", size=0, sha256="")
    if not info["page"].startswith(f"https://github.com/{REPO}/"):
        info["page"] = RELEASES_URL
    for a in data.get("assets") or []:
        if not isinstance(a, dict):
            continue
        name, url = str(a.get("name") or ""), str(a.get("browser_download_url") or "")
        if not ASSET_RE.match(name) or not url.startswith(ASSET_PREFIX):
            continue
        digest = str(a.get("digest") or "")
        m = re.fullmatch(r"sha256:([0-9a-fA-F]{64})", digest)
        size = a.get("size")
        info.update(name=name, url=url, size=size if isinstance(size, int) and 0 < size <= MAX_SIZE else 0,
                    sha256=m.group(1).lower() if m else "")
        break
    return info


def check(current, timeout=15):
    try:
        with _get(API_URL, timeout) as r:
            data = json.loads(r.read(2 * 1024 * 1024).decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise UpdateError("还没有发布版" if e.code == 404 else f"GitHub 返回 {e.code}")
    except (urllib.error.URLError, OSError) as e:
        raise UpdateError(f"无法连接 GitHub：{getattr(e, 'reason', e)}")
    except ValueError:
        raise UpdateError("GitHub 返回的内容无法解析")
    return parse_release(data, current)


def can_install(info):
    """有安装包、知道大小和 SHA-256，才允许程序内下载安装；否则只打开发布页让用户自己下载。"""
    return bool(info and info.get("url") and info.get("sha256") and info.get("size"))


def updates_dir():
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(base, "DownloadButler", "updates")


def download(info, dest_dir=None, progress=None, cancel=None, timeout=30):
    """下载并校验；成功返回安装包路径。校验不通过时删除文件并抛出 UpdateError。"""
    if not can_install(info):
        raise UpdateError("这个版本没有可校验的安装包")
    dest_dir = dest_dir or updates_dir()
    os.makedirs(dest_dir, exist_ok=True)
    for n in os.listdir(dest_dir):                 # 旧的安装包 / 下载残留
        try:
            os.remove(os.path.join(dest_dir, n))
        except OSError:
            pass
    final = os.path.join(dest_dir, info["name"])
    part = final + ".part"
    h, got = hashlib.sha256(), 0
    try:
        with _get(info["url"], timeout, accept="application/octet-stream") as r, open(part, "wb") as f:
            while True:
                if cancel is not None and cancel.is_set():
                    raise UpdateError("已取消")
                chunk = r.read(256 * 1024)
                if not chunk:
                    break
                got += len(chunk)
                if got > info["size"]:
                    raise UpdateError("下载的文件比预期大，已丢弃")
                h.update(chunk)
                f.write(chunk)
                if progress:
                    progress(got * 100 // info["size"])
        if got != info["size"]:
            raise UpdateError("下载不完整，请稍后重试")
        if h.hexdigest() != info["sha256"]:
            raise UpdateError("安装包校验失败（SHA-256 不一致），已丢弃")
        os.replace(part, final)
        return final
    except (urllib.error.URLError, OSError) as e:
        raise UpdateError(f"下载失败：{getattr(e, 'reason', None) or getattr(e, 'strerror', None) or e}")
    finally:
        if os.path.exists(part):
            try:
                os.remove(part)
            except OSError:
                pass


def installer_args(show):
    """静默安装参数：/relaunch 让安装程序装完后把本程序重新打开（show=True 打开窗口，否则只在托盘）。"""
    return ["/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/relaunch=" + ("show" if show else "min")]
