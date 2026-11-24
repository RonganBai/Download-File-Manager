# -*- coding: utf-8 -*-
"""压缩 / 解压。

优先使用本机安装的 7-Zip（格式最全、支持 AES-256 密码、速度快）；没有 7-Zip 时：
  · zip：Python 内置 zipfile，加密 / 解密由 pyzipper 提供（AES-256，也能解开传统 ZipCrypto）
  · tar / tar.gz / tar.bz2 / tar.xz / 单个 .gz .bz2 .xz：Python 内置模块
  · rar / 7z / iso / cab 等：Windows 自带的 tar.exe（libarchive，仅限没有密码的压缩包）

所有函数都可以在后台线程里调用：progress(百分比 或 -1, 说明文字)、cancel（threading.Event）均为可选。
解压总是先放进目标位置里的隐藏临时文件夹，成功后再一次性移到最终位置：
密码不对、取消或出错时不会留下解压了一半的文件。"""
import base64
import bz2
import ctypes
import gzip
import lzma
import os
import re
import shutil
import subprocess
import tarfile
import threading
import time
import uuid
import winreg
import zipfile
import zlib
from ctypes import wintypes

try:
    import pyzipper
except ImportError:                     # 没装时只是不能处理加密 zip（有 7-Zip 时不受影响）
    pyzipper = None

TEMP_PREFIX = ".dlb-tmp-"               # 下载管家的扫描 / 整理 / 清理都会跳过这个前缀
NO_WINDOW = 0x08000000                  # CREATE_NO_WINDOW：不弹黑色控制台窗口
_DUMMY_PW = "\u2063dlb-no-password\u2063"   # 未提供密码时传给 7-Zip，避免它停下来等待输入


class ArchiveError(Exception):
    pass


class PasswordError(ArchiveError):
    """压缩包需要密码，或者密码不对。"""


class Cancelled(ArchiveError):
    pass


# ---------------- 格式 ----------------
ARCHIVE_EXT = (".zip", ".7z", ".rar", ".tar", ".tgz", ".tbz", ".tbz2", ".txz", ".tzst", ".gz", ".bz2", ".xz",
               ".zst", ".lzma", ".cab", ".iso", ".wim", ".arj", ".lzh", ".zipx")
TAR_SUFFIX = (".tar", ".tar.gz", ".tgz", ".tar.bz2", ".tbz", ".tbz2", ".tar.xz", ".txz")
SINGLE = {".gz": gzip.open, ".bz2": bz2.open, ".xz": lzma.open, ".lzma": lzma.open}

# (格式, 扩展名, 显示名)
FORMATS = [("zip", ".zip", "ZIP（兼容性最好，Windows 可直接打开）"),
           ("7z", ".7z", "7Z（压缩率更高）"),
           ("tar.gz", ".tar.gz", "TAR.GZ"),
           ("tar.xz", ".tar.xz", "TAR.XZ（压缩率高）")]
FORMAT_EXT = {f: e for f, e, _ in FORMATS}
LEVELS = [(0, "仅存储（不压缩，最快）"), (1, "最快"), (5, "标准"), (7, "较高"), (9, "极限（最慢）")]


def is_archive(path):
    """能否解压。分卷压缩包只认第一卷（.part1.rar / .001）。"""
    low = os.path.basename(path).lower()
    m = re.search(r"\.part(\d+)\.rar$", low)
    if m:
        return int(m.group(1)) == 1
    if re.search(r"\.\d{3}$", low):
        return low.endswith(".001")
    return low.endswith(ARCHIVE_EXT)


def archive_stem(path):
    """去掉压缩包扩展名后的名字：资料.tar.gz → 资料，电影.part1.rar → 电影，备份.7z.001 → 备份。"""
    name = os.path.basename(path)
    stem = re.sub(r"\.\d{3}$", "", name)
    stem = re.sub(r"\.part\d+(?=\.rar$)", "", stem, flags=re.I)
    stem, _ = os.path.splitext(stem)
    if stem.lower().endswith(".tar"):
        stem = stem[:-4]
    return stem.strip(" .") or name


def volumes(path):
    """分卷压缩包的全部分卷（解压后一起移到回收站）；普通压缩包返回 [path]。"""
    d, name = os.path.split(path)
    m = re.match(r"(.*)\.part(\d+)\.rar$", name, re.I) or re.match(r"(.*)\.(\d{3})$", name)
    if not m:
        return [path]
    if name.lower().endswith(".rar"):
        pat = re.compile(re.escape(m.group(1)) + r"\.part\d+\.rar$", re.I)
    else:
        pat = re.compile(re.escape(m.group(1)) + r"\.\d{3}$", re.I)
    try:
        return sorted(os.path.join(d, n) for n in os.listdir(d) if pat.match(n))
    except OSError:
        return [path]


def _is_tar(path):
    return os.path.basename(path).lower().endswith(TAR_SUFFIX)


# ---------------- 7-Zip ----------------
_7z = None


def seven_zip():
    """本机 7-Zip 的 7z.exe 路径；没装返回 None。结果会缓存，refresh() 可重新查找。"""
    global _7z
    if _7z is not None:
        return _7z or None
    cands = []
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
            try:
                with winreg.OpenKey(hive, r"SOFTWARE\7-Zip", 0, winreg.KEY_READ | view) as k:
                    cands.append(os.path.join(winreg.QueryValueEx(k, "Path")[0], "7z.exe"))
            except OSError:
                pass
    for env in ("ProgramW6432", "ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
        v = os.environ.get(env)
        if v:
            cands.append(os.path.join(v, "7-Zip", "7z.exe"))
            cands.append(os.path.join(v, "Programs", "7-Zip", "7z.exe"))
    # 不在 PATH / 当前目录里找：那里的 7z.exe 可能是别人放的冒牌程序
    _7z = next((c for c in cands if c and os.path.isfile(c)), "")
    return _7z or None


def refresh():
    global _7z
    _7z = None
    return seven_zip()


def engine_text():
    exe = seven_zip()
    if exe:
        return f"使用 7-Zip：{exe}"
    extra = "加密 zip 可用" if pyzipper else "不能处理加密 zip"
    return f"未找到 7-Zip，使用内置引擎（zip / tar；{extra}；rar、7z 只能解压没有密码的）。安装 7-Zip 后自动改用它"


def compress_problem(fmt, password="", zip_method="aes"):
    """检查当前环境能否按要求压缩；能返回空字符串，否则返回原因。"""
    if fmt not in FORMAT_EXT:
        return "不支持的格式"
    if fmt.startswith("tar") and password:
        return "TAR 格式不支持密码，请选择 ZIP 或 7Z"
    if fmt == "zip" and password and not password.isascii():
        return "ZIP 的密码只能用英文字母、数字和符号（其他软件才能正确解开）；中文密码请选择 7Z 格式"
    if seven_zip():
        return ""
    if fmt == "7z":
        return "压缩成 7Z 需要安装 7-Zip（免费）"
    if fmt == "zip" and password:
        if zip_method == "zipcrypto":
            return "传统 ZipCrypto 加密需要安装 7-Zip；可改用 AES-256"
        if pyzipper is None:
            return "给 zip 设置密码需要安装 7-Zip"
    return ""


def _run7z(args, progress, cancel, what):
    """运行 7z.exe，解析 -bsp1 输出的百分比；返回 (退出码, 错误文字)。"""
    _check(cancel)
    # 开关放在命令之后、“--”之前；“--”后面的都按文件名处理
    p = subprocess.Popen([seven_zip(), args[0], "-bsp1", "-bso0", "-bse2", "-sccUTF-8", "-y"] + args[1:],
                         stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         creationflags=NO_WINDOW)
    err = []

    def read_out():
        last = -1
        while True:
            chunk = p.stdout.read1(512) if hasattr(p.stdout, "read1") else p.stdout.read(512)
            if not chunk:
                break
            m = re.findall(rb"(\d{1,3})%", chunk)
            if m and progress:
                v = min(100, int(m[-1]))
                if v != last:
                    last = v
                    progress(v, what)

    def read_err():
        err.append(p.stderr.read())
    ts = [threading.Thread(target=read_out, daemon=True), threading.Thread(target=read_err, daemon=True)]
    for t in ts:
        t.start()
    while True:
        try:
            p.wait(0.2)
            break
        except subprocess.TimeoutExpired:
            if cancel is not None and cancel.is_set():
                p.kill()
                p.wait()
                raise Cancelled("已取消")
    for t in ts:
        t.join(2)
    text = b"".join(err).decode("utf-8", "replace").strip()
    return p.returncode, text


def _7z_error(code, text, password_tried):
    low = text.lower()
    if "wrong password" in low or "encrypted" in low and ("can not open" in low or "cannot open" in low):
        return PasswordError("密码不正确" if password_tried else "这个压缩包需要密码")
    lines = [l.strip() for l in text.splitlines() if l.strip() and not l.startswith(("7-Zip", "Scanning"))]
    detail = "；".join(lines[-3:]) if lines else f"7-Zip 返回代码 {code}"
    if "is not archive" in low or "can not open the file as archive" in low or "cannot open the file as archive" in low:
        return ArchiveError("不是有效的压缩包，或者文件已损坏")
    return ArchiveError(detail)


# ---------------- 工具 ----------------
def unique_path(p, keep_ext=True):
    """已存在时加上 (1)、(2)…；文件夹不拆分扩展名（v1.2 → v1.2 (1)）。"""
    if not os.path.lexists(p):
        return p
    d, name = os.path.split(p)
    base, ext = os.path.splitext(name) if keep_ext else (name, "")
    if keep_ext and base.lower().endswith(".tar"):
        base, ext = base[:-4], ".tar" + ext
    i = 1
    while True:
        q = os.path.join(d, f"{base} ({i}){ext}")
        if not os.path.lexists(q):
            return q
        i += 1


_BAD_CHARS = re.compile(r'[<>:"|?*\x00-\x1f]')


def _safe_join(base, name):
    """把压缩包里的路径安全地拼到 base 下：拒绝 ..、绝对路径；替换 Windows 不允许的字符。"""
    parts = []
    for part in name.replace("\\", "/").split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            return None
        part = _BAD_CHARS.sub("_", part).rstrip(" .")
        if part:
            parts.append(part)
    return os.path.join(base, *parts) if parts else None


def _rmtree(p):
    def onerr(func, path, _):
        try:
            os.chmod(path, 0o666)
            func(path)
        except OSError:
            pass
    if p and os.path.isdir(p):
        shutil.rmtree(p, onerror=onerr)


def _check(cancel):
    if cancel is not None and cancel.is_set():
        raise Cancelled("已取消")


def _collect(sources):
    """要压缩的文件：[(磁盘路径, 包内路径, 是否文件夹)]，包内重名的自动加编号。"""
    out, seen = [], set()

    def add(fp, arc, is_dir):
        key = arc.lower()
        if key in seen:
            base, ext = os.path.splitext(arc) if not is_dir else (arc, "")
            i = 1
            while f"{base} ({i}){ext}".lower() in seen:
                i += 1
            arc = f"{base} ({i}){ext}"
            key = arc.lower()
        seen.add(key)
        out.append((fp, arc, is_dir))
        return arc
    for src in sources:
        src = os.path.abspath(src)
        name = os.path.basename(src.rstrip("\\/"))
        if os.path.isdir(src):
            top = add(src, name, True)
            for d, dirs, files in os.walk(src):
                rel = os.path.relpath(d, src)
                prefix = top if rel == "." else top + "/" + rel.replace("\\", "/")
                for x in dirs:
                    out.append((os.path.join(d, x), prefix + "/" + x, True))
                for x in files:
                    out.append((os.path.join(d, x), prefix + "/" + x, False))
        elif os.path.isfile(src):
            add(src, name, False)
    return out


# ---------------- 压缩 ----------------
def compress(sources, dest, fmt="zip", level=5, password="", encrypt_names=False, zip_method="aes",
             progress=None, cancel=None):
    """把 sources（文件 / 文件夹）压缩成 dest。dest 已存在时自动改名。返回最终路径。"""
    err = compress_problem(fmt, password, zip_method)
    if err:
        raise ArchiveError(err)
    sources = [s for s in sources if os.path.exists(s)]
    if not sources:
        raise ArchiveError("没有可压缩的文件")
    d = os.path.dirname(os.path.abspath(dest))
    os.makedirs(d, exist_ok=True)
    tmp = os.path.join(d, TEMP_PREFIX + uuid.uuid4().hex[:10] + ".part")
    try:
        if fmt.startswith("tar"):
            _tar_compress(sources, tmp, fmt, level, progress, cancel)
        elif seven_zip():
            args = ["a", "-t" + fmt, f"-mx={level}", "-ssw"]
            if fmt == "zip":
                args.append("-mcu=on")                     # 文件名用 UTF-8，中文名在别的电脑上也不乱码
            if password:
                args.append("-p" + password)
                if fmt == "zip":
                    args.append("-mem=" + ("ZipCrypto" if zip_method == "zipcrypto" else "AES256"))
                elif encrypt_names:
                    args.append("-mhe=on")
            code, text = _run7z(args + ["--", tmp] + [os.path.abspath(s) for s in sources],
                                progress, cancel, "正在压缩")
            if code not in (0, 1):
                raise _7z_error(code, text, False)
        else:
            _zip_compress(sources, tmp, level, password, progress, cancel)
        final = unique_path(dest)
        os.replace(tmp, final)
        return final
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def _zip_compress(sources, tmp, level, password, progress, cancel):
    items = _collect(sources)
    total = sum(os.path.getsize(fp) for fp, _, isd in items if not isd) or 1
    method = zipfile.ZIP_STORED if level == 0 else zipfile.ZIP_DEFLATED
    kw = {} if level == 0 else {"compresslevel": max(1, min(9, level))}
    if password:
        z = pyzipper.AESZipFile(tmp, "w", compression=method, encryption=pyzipper.WZ_AES, **kw)
        z.setpassword(password.encode("utf-8"))
    else:
        z = zipfile.ZipFile(tmp, "w", compression=method, allowZip64=True, **kw)
    done = 0
    with z:
        for fp, arc, isd in items:
            _check(cancel)
            if isd:
                z.writestr(arc.rstrip("/") + "/", b"")
                continue
            z.write(fp, arc)
            done += os.path.getsize(fp)
            if progress:
                progress(int(done * 100 / total), "正在压缩")


def _tar_compress(sources, tmp, fmt, level, progress, cancel):
    items = _collect(sources)
    total = sum(os.path.getsize(fp) for fp, _, isd in items if not isd) or 1
    mode = "w:gz" if fmt == "tar.gz" else "w:xz"
    kw = {"compresslevel": max(1, min(9, level or 1))} if fmt == "tar.gz" else {"preset": max(0, min(9, level))}
    done = 0
    with tarfile.open(tmp, mode, **kw) as t:
        for fp, arc, isd in items:
            _check(cancel)
            t.add(fp, arc, recursive=False)
            if not isd:
                done += os.path.getsize(fp)
                if progress:
                    progress(int(done * 100 / total), "正在压缩")


# ---------------- 解压 ----------------
def extract(path, dest_dir, mode="smart", overwrite="rename", password="", passwords=(),
            progress=None, cancel=None, discard=None):
    """解压 path 到 dest_dir。
    mode：smart = 压缩包里只有一个文件夹 / 文件就直接放出来，否则新建同名文件夹；
          folder = 总是新建同名文件夹；here = 直接放进 dest_dir（同名文件按 overwrite 处理）。
    overwrite：rename 自动改名 / overwrite 覆盖 / skip 跳过（只对 here 有意义，其他模式不会重名）。
    discard：覆盖前处理旧文件的函数（例如移到回收站），返回 False 或出错时改为自动重命名，旧文件不会丢。
    先试 password，再依次试 passwords（密码本）；都不对时抛出 PasswordError。
    返回 (解压结果的路径, 实际用上的密码)。"""
    if not os.path.isfile(path):
        raise ArchiveError("压缩包不存在")
    os.makedirs(dest_dir, exist_ok=True)
    cands = [password or ""] + [p for p in passwords if p and p != password]
    tried_real = False
    for pw in cands:
        _check(cancel)
        tmp = os.path.join(dest_dir, TEMP_PREFIX + uuid.uuid4().hex[:10])
        try:
            _extract_raw(path, tmp, pw, progress, cancel)
        except PasswordError:
            _rmtree(tmp)
            tried_real = tried_real or bool(pw)
            continue
        except BaseException:
            _rmtree(tmp)
            raise
        try:
            return _place(path, tmp, dest_dir, mode, overwrite, discard), pw
        finally:
            _rmtree(tmp)
    raise PasswordError("密码不正确" if tried_real else "这个压缩包需要密码")


def _place(path, tmp, dest_dir, mode, overwrite, discard=None):
    entries = os.listdir(tmp) if os.path.isdir(tmp) else []
    if not entries:
        raise ArchiveError("压缩包是空的")
    if mode == "here":
        _merge(tmp, dest_dir, overwrite, discard)
        return dest_dir
    if mode == "smart" and len(entries) == 1:
        src = os.path.join(tmp, entries[0])
        final = unique_path(os.path.join(dest_dir, entries[0]), keep_ext=os.path.isfile(src))
        os.replace(src, final)
        return final
    final = unique_path(os.path.join(dest_dir, archive_stem(path)), keep_ext=False)
    os.replace(tmp, final)
    return final


def _merge(src, dst, policy, discard=None):
    os.makedirs(dst, exist_ok=True)
    for name in os.listdir(src):
        s, d = os.path.join(src, name), os.path.join(dst, name)
        if not os.path.lexists(d):
            os.replace(s, d)
        elif os.path.isdir(s) and os.path.isdir(d) and not os.path.islink(d):
            _merge(s, d, policy, discard)
        elif policy == "skip":
            continue
        elif policy == "overwrite" and os.path.isfile(s) and os.path.isfile(d):
            if discard is not None:
                try:
                    gone = discard(d) and not os.path.lexists(d)
                except OSError:
                    gone = False
                if not gone:                     # 旧文件没能放进回收站：两份都保留
                    os.replace(s, unique_path(d, keep_ext=True))
                    continue
            try:
                os.replace(s, d)
            except PermissionError:          # 只读文件：去掉只读属性再覆盖
                os.chmod(d, 0o666)
                os.replace(s, d)
        else:
            os.replace(s, unique_path(d, keep_ext=os.path.isfile(s)))


def _extract_raw(path, out, password, progress, cancel):
    """把压缩包完整解压进 out（全新的临时文件夹）。"""
    low = path.lower()
    if _is_tar(path) and tarfile.is_tarfile(path):
        return _tar_extract(path, out, progress, cancel)
    ext = os.path.splitext(low)[1]
    if ext in SINGLE and not seven_zip():
        return _single_extract(path, out, ext, progress, cancel)
    if seven_zip():
        os.makedirs(out, exist_ok=True)
        code, text = _run7z(["x", "-p" + (password or _DUMMY_PW), "-aou", "-o" + out, "--", path],
                            progress, cancel, "正在解压")
        if code not in (0, 1):
            raise _7z_error(code, text, bool(password))
        if _is_tar_layer(out):                   # .tgz 之类：7-Zip 只解开外层，里面还有一个 .tar
            inner = os.path.join(out, os.listdir(out)[0])
            sub = out + "-tar"
            _tar_extract(inner, sub, progress, cancel)
            _rmtree(out)
            os.replace(sub, out)
        return
    if zipfile.is_zipfile(path):
        return _zip_extract(path, out, password, progress, cancel)
    return _systar_extract(path, out, cancel)


def _is_tar_layer(out):
    names = os.listdir(out)
    return len(names) == 1 and names[0].lower().endswith(".tar") and tarfile.is_tarfile(os.path.join(out, names[0]))


def _zip_name(info):
    """没有 UTF-8 标记的 zip（Windows 自带压缩、旧版 WinRAR）里中文名是 GBK 编码的。"""
    if info.flag_bits & 0x800:
        return info.filename
    try:
        return info.filename.encode("cp437").decode("gbk")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return info.filename


def _zip_extract(path, out, password, progress, cancel):
    opener = pyzipper.AESZipFile if pyzipper else zipfile.ZipFile
    os.makedirs(out, exist_ok=True)
    try:
        z = opener(path)
    except zipfile.BadZipFile as e:
        raise ArchiveError("不是有效的压缩包，或者文件已损坏") from e
    with z:
        infos = z.infolist()
        if any(i.flag_bits & 1 for i in infos):
            if not password:
                raise PasswordError("这个压缩包需要密码")
            z.setpassword(password.encode("utf-8"))
        total = sum(i.file_size for i in infos) or 1
        done = 0
        for i in infos:
            _check(cancel)
            target = _safe_join(out, _zip_name(i))
            if target is None:
                continue
            if i.is_dir():
                os.makedirs(target, exist_ok=True)
                continue
            os.makedirs(os.path.dirname(target), exist_ok=True)
            target = unique_path(target)
            try:
                with z.open(i) as src, open(target, "wb") as dst:
                    shutil.copyfileobj(src, dst, 1 << 20)
            except RuntimeError as e:
                if "password" in str(e).lower() or i.flag_bits & 1:
                    raise PasswordError("密码不正确") from e
                raise ArchiveError(str(e)) from e
            except NotImplementedError as e:
                raise ArchiveError("这个 zip 用了不支持的压缩或加密方式，安装 7-Zip 后即可解压") from e
            except (zipfile.BadZipFile, zlib.error, EOFError) as e:
                if i.flag_bits & 1:              # 传统加密只有 1 字节校验，错误密码偶尔能通过校验，解出来是乱码
                    raise PasswordError("密码不正确") from e
                raise ArchiveError("压缩包已损坏") from e
            try:
                t = time.mktime(i.date_time + (0, 0, -1))
                os.utime(target, (t, t))
            except (OverflowError, ValueError, OSError):
                pass
            done += i.file_size
            if progress:
                progress(int(done * 100 / total), "正在解压")


def _tar_extract(path, out, progress, cancel):
    os.makedirs(out, exist_ok=True)
    kw = {"filter": "data"} if hasattr(tarfile, "data_filter") else {}
    try:
        t = tarfile.open(path, "r:*")
    except tarfile.TarError as e:
        raise ArchiveError("不是有效的压缩包，或者文件已损坏") from e
    with t:
        members = t.getmembers()
        total = sum(m.size for m in members) or 1
        done = 0
        for m in members:
            _check(cancel)
            if _safe_join(out, m.name) is None or m.issym() or m.islnk() or m.isdev():
                continue
            try:
                t.extract(m, out, **kw)
            except (tarfile.TarError, OSError):
                continue
            done += m.size
            if progress:
                progress(int(done * 100 / total), "正在解压")


def _single_extract(path, out, ext, progress, cancel):
    """单个压缩文件（不是 tar）：资料.csv.gz → 资料.csv"""
    os.makedirs(out, exist_ok=True)
    name = os.path.basename(path)[:-len(ext)] or "解压结果"
    try:
        with SINGLE[ext](path, "rb") as src, open(os.path.join(out, name), "wb") as dst:
            while True:
                _check(cancel)
                b = src.read(1 << 20)
                if not b:
                    break
                dst.write(b)
    except (OSError, EOFError, lzma.LZMAError) as e:
        raise ArchiveError("不是有效的压缩文件，或者文件已损坏") from e
    if progress:
        progress(100, "正在解压")


def _systar_extract(path, out, cancel):
    """没有 7-Zip 时用 Windows 10/11 自带的 tar.exe（libarchive）解压 rar / 7z / iso 等。"""
    exe = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "tar.exe")
    if not os.path.isfile(exe):
        raise ArchiveError("解压这种格式需要安装 7-Zip（免费）")
    os.makedirs(out, exist_ok=True)
    p = subprocess.Popen([exe, "-x", "-f", path, "-C", out], stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, creationflags=NO_WINDOW)
    err = []
    t = threading.Thread(target=lambda: err.append(p.stderr.read()), daemon=True)
    t.start()
    while True:
        try:
            p.wait(0.2)
            break
        except subprocess.TimeoutExpired:
            if cancel is not None and cancel.is_set():
                p.kill()
                p.wait()
                raise Cancelled("已取消")
    t.join(2)
    if p.returncode:
        text = b"".join(err).decode("utf-8", "replace").lower()
        if "passphrase" in text or "encrypt" in text:
            raise ArchiveError("这个压缩包有密码，需要安装 7-Zip（免费）才能解压")
        if "filename" in text:                   # 系统自带 tar 只能处理当前系统语言能表示的文件名
            raise ArchiveError("压缩包里的文件名系统自带解压工具无法识别，安装 7-Zip（免费）后再试")
        raise ArchiveError("无法解压这种格式，安装 7-Zip（免费）后再试")


# ---------------- 密码本：用 Windows 账户加密保存（DPAPI），只有本人在本机能解开 ----------------
class _Blob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _blob(data):
    buf = ctypes.create_string_buffer(data, len(data))
    return _Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), buf


def _crypt(fn, data):
    inp, _keep = _blob(data)
    out = _Blob()
    if not fn(ctypes.byref(inp), None, None, None, None, 0x1, ctypes.byref(out)):   # 0x1 = 不弹任何界面
        raise OSError("DPAPI 失败")
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(out.pbData)


def protect(text):
    c32 = ctypes.windll.crypt32
    return base64.b64encode(_crypt(lambda *a: c32.CryptProtectData(a[0], "下载管家", *a[2:]),
                                   text.encode("utf-8"))).decode("ascii")


def unprotect(token):
    """解不开（配置文件被拷到别的电脑 / 别的账户）时返回 None。"""
    try:
        data = base64.b64decode(token)
        return _crypt(ctypes.windll.crypt32.CryptUnprotectData, data).decode("utf-8")
    except (OSError, ValueError, UnicodeDecodeError):
        return None
