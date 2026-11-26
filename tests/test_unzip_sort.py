# -*- coding: utf-8 -*-
"""分卷压缩包归类、解压后按分类放好的测试（全部在临时目录里）。用法：python tests/test_unzip_sort.py"""
import importlib.util, os, sys, tempfile, zipfile

repo = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, repo)
spec = importlib.util.spec_from_file_location("dm", os.path.join(repo, "download_manager.py"))
dm = importlib.util.module_from_spec(spec); spec.loader.exec_module(dm)
dm.apply_rules(None)

fails = 0
def check(name, cond):
    global fails
    print(("PASS " if cond else "FAIL ") + name); fails += not cond

ARC = dm.category_for("a.zip")
# ---------- 分卷压缩包 ----------
for n in ("11.26视频合集.zip.001", "11.26视频合集.zip.004", "备份.7z.002", "资料.z01", "资料.r00", "电影.mkv.003"):
    check(f"{n} -> {ARC}", dm.category_for(n) == ARC)
check("normal video untouched", dm.category_for("11.26春花秋月.mp4") != ARC)
check("plain .zip still archive", dm.category_for("x.ZIP") == ARC)
check("volume_name", dm.volume_name("a.zip.003") == "a.zip" and dm.volume_name("a.mkv.001") == "a.mkv.7z"
      and dm.volume_name("a.txt") == "a.txt")

# ---------- 解压后按分类放好 ----------
dm.ROOT = tempfile.mkdtemp(prefix="dmsort_")
dm.BY_MONTH = False
VID = dm.category_for("a.mp4")
arc_dir = os.path.join(dm.ROOT, ARC)
os.makedirs(arc_dir)


def make_zip(name, members):
    p = os.path.join(arc_dir, name)
    with zipfile.ZipFile(p, "w") as z:
        for m in members:
            z.writestr(m, b"x" * 100)
    return p


def run(p, mode):
    opts = dict(mode=mode, dest=None, overwrite="rename", sort=True, sorted=[])
    home = dm.archive_home(p)
    res, _ = dm.extract_sorted(p, home, opts, "", [], None, None)
    return res, opts


p = make_zip("三个视频.zip", ["a.mp4", "b.mp4", "c.mp4"])
check("archive_home finds category", dm.archive_home(p) == (dm.ROOT, ARC))
res, opts = run(p, "here")
check("here: videos moved to video category",
      sorted(os.listdir(os.path.join(dm.ROOT, VID))) == ["a.mp4", "b.mp4", "c.mp4"] and opts["sorted"] == [VID] * 3)
check("here: nothing left in archive folder", sorted(os.listdir(arc_dir)) == ["三个视频.zip"])

res, opts = run(p, "smart")
check("smart: folder of videos moved as a whole", os.path.isdir(res) and os.path.dirname(res) == os.path.join(dm.ROOT, VID)
      and sorted(os.listdir(res)) == ["a.mp4", "b.mp4", "c.mp4"])

q = make_zip("内含压缩包.zip", ["inner.zip"])
res, opts = run(q, "smart")
check("same category stays put, no toast category", os.path.dirname(res) == arc_dir and opts["sorted"] == [])

prog = make_zip("绿色软件.zip", ["tool/app.exe", "tool/core.dll"])
res, opts = run(prog, "smart")
check("program folder stays next to archive", os.path.dirname(res) == arc_dir)
check("no temp folder left", not any(n.startswith(dm.TEMP_PREFIX) for n in os.listdir(arc_dir)))

loose = os.path.join(dm.ROOT, "根目录.zip")
os.replace(p, loose)
check("archive in root -> not sorted", dm.archive_home(loose) is None)
deep = os.path.join(arc_dir, "归档文件夹"); os.makedirs(deep)
check("archive inside archived folder -> not sorted", dm.archive_home(os.path.join(deep, "x.zip")) is None)
check("setting default on", dm.sanitize_cfg({})["unzip_sort"] is True)

print("FAILURES:", fails); sys.exit(fails)
