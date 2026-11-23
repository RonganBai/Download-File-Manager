# -*- coding: utf-8 -*-
"""关键词分类 / 重新整理 / 垃圾文件 / 散落文件夹 的测试。用法：python tests/test_keywords_junk.py"""
import ctypes, importlib.util, os, sys, tempfile, time
from ctypes import wintypes

repo = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("dm", os.path.join(repo, "download_manager.py"))
dm = importlib.util.module_from_spec(spec); spec.loader.exec_module(dm)

fails = 0
def check(name, cond):
    global fails
    print(("PASS " if cond else "FAIL ") + name); fails += not cond

def set_times(path, days_ago):
    """同时改修改时间和创建时间（文件、文件夹都可以）。"""
    t = time.time() - days_ago * 86400
    os.utime(path, (t, t))
    k32 = ctypes.windll.kernel32
    k32.CreateFileW.restype = wintypes.HANDLE
    h = k32.CreateFileW(path, 0x100, 7, None, 3, 0x02000000, None)
    ft = int((t + 11644473600) * 10**7)
    f = wintypes.FILETIME(ft & 0xFFFFFFFF, ft >> 32)
    k32.SetFileTime(wintypes.HANDLE(h), ctypes.byref(f), None, ctypes.byref(f))
    k32.CloseHandle(wintypes.HANDLE(h))

def mk(rel, data=b"x", days=30):
    p = os.path.join(dm.ROOT, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "wb") as f: f.write(data)
    set_times(p, days)
    return p

def fresh():
    dm.ROOT = tempfile.mkdtemp(prefix="dmkw_")

# ---------- 关键词规则 ----------
check("parse_keywords", dm.parse_keywords("护照, Passport；I-20、green  card\n签证") ==
      ["护照", "passport", "i-20", "green card", "签证"])
norm, err = dm.validate_rules([("移民", "", "护照, passport"), ("图", "png", "")])
check("validate keyword-only rule", err == "" and norm == [["移民", "", "护照, passport"], ["图", ".png"]])
check("rule needs exts or keywords", dm.validate_rules([("空", "", "")])[0] is None)
check("presets valid", dm.validate_rules([list(p) for p in dm.PRESETS])[1] == "")

rules = [[r[0], r[2]] for r in dm.DEFAULT_RULES] + [list(p) for p in dm.PRESETS] + [["扫描件", "pdf", "scan, 扫描"]]
check("apply presets", dm.apply_rules(rules) == "" and "移民身份文件" in dm.CATS)
cases = {
    "Passport_scan.pdf": "移民身份文件", "护照扫描.jpg": "移民身份文件", "I-20 form.pdf": "移民身份文件",
    "i20.pdf": "移民身份文件", "Green-Card front.png": "移民身份文件", "OPT approval.pdf": "移民身份文件",
    "adopt a cat.pdf": "重要文件", "headphones.jpg": "图片",          # opt / ead 不会误中
    "offer letter.docx": "工作文件", "张三简历.pdf": "工作文件", "CV.docx": "工作文件",
    "cv2_tutorial.py": "代码",                                         # 短词严格整词
    "Invoice2024.pdf": "财务票据", "lecture3.pptx": "学习资料",       # 长词允许后跟数字
    "photo.png": "图片", "setup.exe": "安装包", "unknown.xyz": "其他文件",
    "scan_001.pdf": "扫描件", "scan_001.png": "图片",                 # 关键词 + 限定扩展名
}
for n, want in cases.items():
    got = dm.category_for(n)
    check(f"category_for({n}) = {want}", got == want) if got == want else check(f"category_for({n}) = {want} (got {got})", False)
c = dm.sanitize_cfg(dict(rules=rules, protect=["移民身份文件"]))
check("sanitize keeps keyword rules & protect", c["rules"][-1] == ["扫描件", ".pdf", "scan, 扫描"] and c["protect"] == ["移民身份文件"])

# ---------- 重新整理已有文件 ----------
fresh()
mk("重要文件/2024-01/passport.pdf")
mk("图片/2024-01/护照.jpg")
mk("图片/2024-01/cat.jpg")
mk("图片/2024-01/相册/offer.jpg")             # 整个归档进来的文件夹里的文件：不拆散
mk("其他文件/简历.pdf")
plan = dm.plan_reorganize(protect=["重要文件"])
got = sorted((os.path.basename(p), a, b) for p, a, b in plan)
check("plan: protected->unprotected skipped, folder kept, others moved",
      got == [("护照.jpg", "图片", "移民身份文件"), ("简历.pdf", "其他文件", "工作文件")])
plan = dm.plan_reorganize(protect=["重要文件", "移民身份文件"])
check("plan: protected->protected allowed", any(os.path.basename(p) == "passport.pdf" for p, _, _ in plan))

# ---------- 垃圾文件 ----------
fresh()
keep = [mk("图片/2024-01/a.jpg", b"img"), mk("散落/readme.txt", b"hi"), mk("散落/desktop.ini", b"x"),
        mk("散落/report.pdf", b"AAAA"), mk("散落/report (1).pdf", b"BBBB"),      # 同名不同内容：保留
        mk("散落/new.tmp", b"t", days=0), mk("散落/~$recent.docx", b"l", days=0),   # 太新：保留
        mk("散落/going.crdownload", b"p", days=2), mk("重要文件/空.txt", b"", days=5)]  # 受保护分类里的空文件：保留
junk = [mk("散落/Thumbs.db", b"x"), mk("散落/._photo.jpg", b"x" * 100), mk("散落/~$old.docx", b"x" * 160),
        mk("散落/old.tmp", b"x"), mk("散落/stale.crdownload", b"x" * 10, days=10), mk("zero.bin", b""),
        mk("散落/data.zip", b"SAME"), mk("散落/data (1).zip", b"SAME"), mk("散落/data - 副本.zip", b"SAME"),
        mk("压缩包解压/__MACOSX/._x", b"x" * 50)]
os.makedirs(os.path.join(dm.ROOT, "空的", "更深", "最深")); set_times(os.path.join(dm.ROOT, "空的"), 3)
set_times(os.path.join(dm.ROOT, "空的", "更深"), 3); set_times(os.path.join(dm.ROOT, "空的", "更深", "最深"), 3)
os.makedirs(os.path.join(dm.ROOT, "视频")); set_times(os.path.join(dm.ROOT, "视频"), 3)   # 分类顶层文件夹：保留
# 用户自己的文件夹深处：空子文件夹、0 字节文件都保留（可能是有意的结构）
keep += [mk("散落/notes/empty.txt", b"")]
os.makedirs(os.path.join(dm.ROOT, "散落", "空子", "更深")); set_times(os.path.join(dm.ROOT, "散落", "空子"), 3)
# 代码项目 / 绿色软件：整个不碰，包括里面的 Thumbs.db、空 __init__.py、空文件夹、.tmp
keep += [mk("MyProj/.gitignore", b"x"), mk("MyProj/pkg/__init__.py", b""), mk("MyProj/Thumbs.db", b"x"),
         mk("MyProj/old.tmp", b"x"), mk("Tool/app.exe", b"x"), mk("Tool/core.dll", b"x"), mk("Tool/cfg/__init__.py", b"")]
os.makedirs(os.path.join(dm.ROOT, "MyProj", "logs")); set_times(os.path.join(dm.ROOT, "MyProj", "logs"), 3)
keep += [mk("Venv/.venv/Lib/site-packages/x/__init__.py", b"")]
stats = {}
found = {os.path.relpath(x["path"], dm.ROOT): x for x in dm.find_junk(protect=["重要文件"], stats=stats)}
check(f"project/program folders skipped (stats={stats})", stats.get("projects") == 3)
check("nothing inside projects listed", not any(k.split(os.sep)[0] in ("MyProj", "Tool", "Venv") for k in found))
expect = {"散落\\Thumbs.db", "散落\\._photo.jpg", "散落\\~$old.docx", "散落\\old.tmp", "散落\\stale.crdownload",
          "zero.bin", "散落\\data (1).zip", "散落\\data - 副本.zip", "压缩包解压\\__MACOSX", "空的"}
check("junk found exactly", set(found) == expect)
if set(found) != expect:
    print("   extra:", set(found) - expect, " missing:", expect - set(found))
check("original of duplicate kept", "散落\\data.zip" not in found)
check("__MACOSX size counted", found.get("压缩包解压\\__MACOSX", {}).get("size") == 50)
check("duplicate reason names original", "data.zip" in found.get("散落\\data (1).zip", {}).get("reason", ""))

deleted = []
dm.recycle = lambda paths: [deleted.append(p) or (dm.shutil.rmtree(p) if os.path.isdir(p) else os.remove(p)) for p in paths]
outside = dict(path=tempfile.mkdtemp(prefix="dmout_"), size=0, reason="x")
n, freed, skipped = dm.delete_junk(list(found.values()) + [outside])
check("delete_junk removes listed, refuses outside root", n == len(expect) and skipped == 1 and os.path.isdir(outside["path"]))
check("kept files survive", all(os.path.exists(p) for p in keep))

# ---------- 散落文件夹 ----------
fresh()
dm.BY_MONTH = False
mk("相册/1.jpg", b"x" * 1000); mk("相册/2.png", b"x" * 1000); mk("相册/说明.txt", b"x" * 10); mk("相册/Thumbs.db", b"x" * 99999)
set_times(os.path.join(dm.ROOT, "相册"), 30)
mk("解压中/a.mp4", b"x", days=0); set_times(os.path.join(dm.ROOT, "解压中"), 0)                 # 太新
mk("下载中/b.iso", b"x"); mk("下载中/b.iso.part", b"x"); set_times(os.path.join(dm.ROOT, "下载中"), 30)   # 有未完成下载
mk("只有垃圾/Thumbs.db", b"x"); set_times(os.path.join(dm.ROOT, "只有垃圾"), 30)
os.makedirs(os.path.join(dm.ROOT, "图片"))
moved, retry = dm.organize(settle=3, loose_dirs=False)
check("loose dirs untouched when option off", os.path.isdir(os.path.join(dm.ROOT, "相册")))
moved, retry = dm.organize(settle=3, loose_dirs=True)
check("folder moved by majority type (junk ignored)", os.path.isfile(os.path.join(dm.ROOT, "图片", "相册", "说明.txt")))
check("recent folder waits", os.path.isdir(os.path.join(dm.ROOT, "解压中")) and retry is not None and retry > 50)
check("folder with partial download skipped", os.path.isdir(os.path.join(dm.ROOT, "下载中")))
check("junk-only folder left for junk cleaner", os.path.isdir(os.path.join(dm.ROOT, "只有垃圾")))
mk("项目A/package.json", b"{}"); set_times(os.path.join(dm.ROOT, "项目A"), 30)
dm.organize(settle=3, loose_dirs=True)
check("project folder not moved by loose-folder organize", os.path.isdir(os.path.join(dm.ROOT, "项目A")))
check("category folder not moved into itself", os.path.isdir(os.path.join(dm.ROOT, "图片")) and moved == ["相册\\"])

print("FAILURES:", fails); sys.exit(fails)
