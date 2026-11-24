# -*- coding: utf-8 -*-
"""整个归档进来的文件夹：识别（安装包 / 程序）、列表里显示为一行、分析能否删除 / 理顺。
用法：python tests/test_dirs_analyze.py"""
import importlib.util, os, shutil, sys, tempfile, time

repo = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, repo)
spec = importlib.util.spec_from_file_location("dm", os.path.join(repo, "download_manager.py"))
dm = importlib.util.module_from_spec(spec); spec.loader.exec_module(dm)
import journal

fails = 0
def check(name, cond):
    global fails
    print(("PASS " if cond else "FAIL ") + name); fails += not cond


def mk(path, data=b"x", age_days=0):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)
    if age_days:
        t = time.time() - age_days * 86400
        os.utime(path, (t, t))
    return path


base = tempfile.mkdtemp(prefix="dmdirs_")
os.environ["LOCALAPPDATA"] = os.path.join(os.path.dirname(base), "_not_here_lad")
dm.ROOT = os.path.join(base, "Downloads"); os.makedirs(dm.ROOT)
journal.init(os.path.join(base, "cfg"))
dm.BY_MONTH = True
# 测试里不碰真实回收站：直接删除
def fake_recycle(paths):
    for p in paths:
        shutil.rmtree(p) if os.path.isdir(p) else os.remove(p)
dm.recycle = fake_recycle
dm.recycle_limit = lambda p: 10 ** 12

other = os.path.join(dm.ROOT, "其他文件", "2024-01")
inst = os.path.join(dm.ROOT, "安装包", "2024-01")

# --- dir_kind ---
drv = os.path.join(other, "Driver")
mk(os.path.join(drv, "BootUp", "Setup.exe"), age_days=400); mk(os.path.join(drv, "data.cab"), b"y" * 50, age_days=400)
old = time.time() - 400 * 86400
for d in (os.path.join(drv, "BootUp"), drv):
    os.utime(d, (old, old))
check("installer in subfolder detected", dm.dir_kind(drv) == "installer")
app = os.path.join(other, "win")
mk(os.path.join(app, "updream", "updream.exe")); os.makedirs(os.path.join(app, "updream", "_internal"))
check("nested portable app (win\\updream) detected", dm.dir_kind(app) == "app")
proj = os.path.join(other, "proj"); mk(os.path.join(proj, "package.json"), b"{}")
check("code project is app", dm.dir_kind(proj) == "app")
check("installer goes to 安装包", dm.installer_cat() == "安装包")

# --- 列表里显示为一行 ---
photos = os.path.join(other, "相册"); mk(os.path.join(photos, "a.jpg"), b"1" * 10); mk(os.path.join(photos, "b.jpg"), b"2" * 20)
items = dm.scan()[0]
row = next((x for x in items if x["path"] == photos), None)
check("archived folder is one row", row is not None and row["is_dir"] and row["count"] == 2 and row["size"] == 30)
check("files inside not listed separately", not any(x["path"].startswith(photos + os.sep) for x in items))
check("inner names kept for search", row is not None and "a.jpg" in row["inner"])
flat = dm.scan(group_dirs=False)[0]
check("cleanup scan still lists files", any(x["path"] == os.path.join(photos, "a.jpg") for x in flat))

# --- 重新整理：只有安装包文件夹会整个挪 ---
plan = dm.plan_reorganize([])
check("reorganize moves installer folder whole", (drv, "其他文件", "安装包") in plan)
check("reorganize leaves app / normal folders", not any(p in (app, proj, photos) for p, _, _ in plan))

# --- 分析 ---
empty = os.path.join(other, "空的"); os.makedirs(empty)
mk(os.path.join(empty, "sub", "x.tmp"), b"", age_days=3)       # 只有垃圾
os.remove(os.path.join(empty, "sub", "x.tmp")); os.rmdir(os.path.join(empty, "sub"))
os.makedirs(os.path.join(empty, "deep"))
junk = os.path.join(other, "缓存"); mk(os.path.join(junk, "Thumbs.db"), b"t"); mk(os.path.join(junk, "a.tmp"), b"z", age_days=3)
dup = os.path.join(other, "相册 (1)"); shutil.copytree(photos, dup)
wrap = os.path.join(other, "资料包"); mk(os.path.join(wrap, "资料包", "内容", "a.pdf"), b"p"); mk(os.path.join(wrap, "资料包", "内容", "b.pdf"), b"q")
ext = os.path.join(other, "照片集"); mk(os.path.join(ext, "c.jpg"), b"c")
mk(os.path.join(dm.ROOT, "压缩包", "2024-01", "照片集.zip"), b"zip")
res = dm.analyze_dirs([])
def find(path, level=None):
    return [a for a in res if a["path"] == path and (level is None or a["level"] == level)]
check("empty folder -> delete", find(empty, "delete") != [])
check("junk-only folder -> delete", find(junk, "delete") != [])
check("duplicate copy -> delete", find(dup, "delete") != [] and find(photos, "delete") == [])
check("app folder -> keep", [a["level"] for a in find(app)] == ["keep"])
check("project -> keep", [a["level"] for a in find(proj)] == ["keep"])
check("old installer -> maybe delete", find(drv, "maybe") != [])
check("misplaced installer -> move to 安装包", any(a["action"] == "move:安装包" for a in find(drv, "fix")))
check("wrapper folder -> unwrap", any(a["action"] == "unwrap" for a in find(wrap, "fix")))
check("extracted copy of archive -> maybe", find(ext, "maybe") != [])
check("normal folder -> keep", [a["level"] for a in find(photos)] == ["keep"])
check("only= limits analysis", {a["path"] for a in dm.analyze_dirs([], only=[photos])} == {photos})
check("protected category -> keep", all(a["level"] == "keep" for a in dm.analyze_dirs(["其他文件"])
                                         if a["cat"] == "其他文件"))

# --- 执行 ---
chosen = find(empty, "delete") + find(dup, "delete") + [a for a in find(wrap, "fix")] \
    + [a for a in find(drv, "fix")]
n, freed, fixed, problems = dm.apply_dir_actions(chosen)
check("deleted 2 folders", n == 2 and not os.path.exists(empty) and not os.path.exists(dup))
check("original kept", os.path.isdir(photos))
check("unwrapped one level", os.path.isfile(os.path.join(other, "内容", "a.pdf")) and not os.path.exists(wrap))
import glob
moved = glob.glob(os.path.join(dm.ROOT, "安装包", "*", "Driver", "BootUp", "Setup.exe"))
check("installer moved to 安装包", len(moved) == 1 and not os.path.exists(drv))
check("fixed count", fixed == 2 and not problems)
b = journal.batches()[0]
ok, probs = journal.undo(b["id"])
check("undo restores unwrap and move", os.path.isfile(os.path.join(wrap, "资料包", "内容", "a.pdf"))
      and os.path.isfile(os.path.join(drv, "BootUp", "Setup.exe")))
# 同名：外层和里层名字一样
same = os.path.join(other, "同名"); mk(os.path.join(same, "同名", "x.txt"))
dm.unwrap_dir(same)
check("unwrap same-name keeps name", os.path.isfile(os.path.join(other, "同名", "x.txt"))
      and not os.path.exists(os.path.join(other, "同名", "同名")))

# --- 扫描缓存：没有变化通知的目录复用；通知某个目录后重新读取它（以及上级、下级） ---
check("local NTFS folder is cacheable", dm._cacheable(dm.ROOT))
dm.scan_invalidate()
def names(**kw):
    return {x["name"] for x in dm.scan(**kw)[0]}
first = names(use_cache=True)
check("cached scan equals full scan", first == names())
newf = mk(os.path.join(other, "新图.jpg"))       # 已经缓存过的目录里新增文件
check("without notice cached result reused", "新图.jpg" not in names(use_cache=True))
check("full scan sees new file", "新图.jpg" in names())
dm.scan_invalidate(os.path.dirname(newf))
check("after notice new file visible", "新图.jpg" in names(use_cache=True))
inner = mk(os.path.join(other, "相册", "深层", "x.jpg"))
before = next(x for x in dm.scan(use_cache=True)[0] if x["path"] == photos)["count"]
dm.scan_invalidate(os.path.dirname(inner))              # 文件夹里面深处的变化：上级的整行也重新统计
after = next(x for x in dm.scan(use_cache=True)[0] if x["path"] == photos)["count"]
check("nested change refreshes folder row", after == before + 1)
os.remove(newf)
dm.scan_invalidate(os.path.dirname(os.path.dirname(newf)))   # 上级目录的通知也丢掉下级的记录
check("parent notice drops child cache", "新图.jpg" not in names(use_cache=True))
check("cleanup scan never cached", "新图.jpg" not in {x["name"] for x in dm.scan(group_dirs=False)[0]})

shutil.rmtree(base, ignore_errors=True)
print("FAILURES:", fails)
sys.exit(1 if fails else 0)
