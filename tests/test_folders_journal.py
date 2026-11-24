# -*- coding: utf-8 -*-
"""多文件夹整理 + 移动记录与撤销 的测试。用法：python tests/test_folders_journal.py"""
import ctypes, importlib.util, os, sys, tempfile, time
from ctypes import wintypes

repo = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, repo)
spec = importlib.util.spec_from_file_location("dm", os.path.join(repo, "download_manager.py"))
dm = importlib.util.module_from_spec(spec); spec.loader.exec_module(dm)
import journal

fails = 0
def check(name, cond):
    global fails
    print(("PASS " if cond else "FAIL ") + name); fails += not cond


def set_ctime(path, ts):
    k32 = ctypes.windll.kernel32
    k32.CreateFileW.restype = wintypes.HANDLE
    h = k32.CreateFileW(path, 0x100, 7, None, 3, 0x02000000, None)
    ft = int((ts + 11644473600) * 10**7)
    f = wintypes.FILETIME(ft & 0xFFFFFFFF, ft >> 32)
    assert k32.SetFileTime(wintypes.HANDLE(h), ctypes.byref(f), None, None)
    k32.CloseHandle(wintypes.HANDLE(h))


def mk(path, data=b"x", age_days=0):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)
    if age_days:
        t = time.time() - age_days * 86400
        os.utime(path, (t, t))
        set_ctime(path, t)
    return path


base = tempfile.mkdtemp(prefix="dmfold_")
# 临时目录在 %LOCALAPPDATA%\Temp 下，而应用数据目录不允许被管理：测试里把它指向别处
os.environ["LOCALAPPDATA"] = os.path.join(os.path.dirname(base), "_not_here_lad")
dm.ROOT = os.path.join(base, "Downloads"); os.makedirs(dm.ROOT)
cfg_dir = os.path.join(base, "cfg")
journal.init(cfg_dir)
dm.BY_MONTH = True

# --- extra_problem ---
desk = os.path.join(base, "Desk"); os.makedirs(desk)
check("normal folder accepted", dm.extra_problem(desk) == "")
proj = os.path.join(base, "proj"); mk(os.path.join(proj, "package.json"), b"{}")
check("project folder refused", dm.extra_problem(proj) != "")
game = os.path.join(base, "SteamLibrary", "x"); os.makedirs(game)
check("game library path refused", "游戏" in dm.extra_problem(game))
check("overlap with primary refused", "重叠" in dm.extra_problem(os.path.join(dm.ROOT)))
inner = os.path.join(dm.ROOT, "sub"); os.makedirs(inner)
check("inside primary refused", "重叠" in dm.extra_problem(inner))
check("overlap with other extra refused", "重叠" in dm.extra_problem(desk, [base]))
check("missing folder refused", dm.extra_problem(os.path.join(base, "nope")) != "")

# --- sanitize / apply ---
c = dm.sanitize_cfg(dict(folders=[{"path": desk, "auto": True}, {"path": 3}, "bad",
                                  {"path": os.path.join(base, "unplugged"), "clean": True, "added": 5}]))
check("sanitize folders", len(c["folders"]) == 2 and c["folders"][0]["clean"] is False
      and c["folders"][1]["added"] == 5.0 and c["folders"][1]["auto"] is True)
c["folders"].append(dict(path=proj, auto=True, clean=False, added=0))
dm.apply_folders(c)
check("apply keeps unplugged, drops project", [os.path.basename(f["path"]) for f in dm.EXTRA] == ["Desk", "unplugged"])
check("roots only connected", dm.roots() == [dm.ROOT, desk])
check("skip list default", ".lnk" in dm.EXTRA_SKIP and ".exe" in dm.EXTRA_SKIP)

# --- 只整理加入之后的新文件 ---
old = mk(os.path.join(desk, "旧报告.pdf"), age_days=30)
dm.EXTRA[:] = [dict(path=desk, auto=True, clean=False, added=time.time() - 3600)]
new = mk(os.path.join(desk, "新照片.jpg"))
lnk = mk(os.path.join(desk, "微信.lnk"))
cfgf = mk(os.path.join(desk, "settings.json"), b"{}")
hid = mk(os.path.join(desk, "hidden.pdf"))
ctypes.windll.kernel32.SetFileAttributesW(hid, 2)
part = mk(os.path.join(desk, "movie.mp4.crdownload"))
subf = mk(os.path.join(desk, "项目资料", "图.png"))
cands, _ = dm.extra_candidates(dm.EXTRA[0], time.time(), 0, set())
names = sorted(e.name for e, _, _ in cands)
check("only new top-level ordinary files", names == ["新照片.jpg"])
cands_all, _ = dm.extra_candidates(dm.EXTRA[0], time.time(), 0, set(), only_new=False)
check("existing files listed for preview", sorted(e.name for e, _, _ in cands_all) == ["新照片.jpg", "旧报告.pdf"])

moved, _ = dm.organize(settle=0, label="自动整理")
month = time.strftime("%Y-%m")
dst = os.path.join(desk, dm.EXTRA_SUB, "图片", month, "新照片.jpg")
check("extra file organized into 已整理", moved == ["新照片.jpg"] and os.path.isfile(dst))
check("old / lnk / config / hidden / partial / subfolder untouched",
      all(os.path.exists(p) for p in (old, lnk, cfgf, hid, part, subf)))

# 主文件夹照常整理，且同一次整理记为同一批
mk(os.path.join(dm.ROOT, "a.zip"))
dm.EXTRA[0]["added"] = 0
mk(os.path.join(desk, "b.docx"))
moved, _ = dm.organize(settle=0, label="立即整理")
bs = journal.batches()
check("one batch per organize run", bs[0]["label"] == "立即整理" and len(bs[0]["moves"]) == 3 and len(bs) == 2)
# 加入之前的旧文件也算新（added 改为 0）——b.docx、旧报告.pdf 和 a.zip

# --- scan / root keys ---
items, dirs = dm.scan()
by = {x["name"]: x for x in items}
check("scan lists extra organized files with root", by["新照片.jpg"]["root"] == desk and by["新照片.jpg"]["cat"] == "图片")
check("scan lists extra top-level as 未整理 (display only)",
      by["微信.lnk"]["cat"] == "未整理" and by["微信.lnk"]["root"] == desk and "hidden.pdf" not in by)
check("scan watches extra and 已整理", desk in dirs and os.path.join(desk, dm.EXTRA_SUB) in dirs)
check("root_of", dm.root_of(dst) == desk and dm.root_of(os.path.join(dm.ROOT, "x")) == dm.ROOT and dm.root_of(base) is None)

# --- move_to stays in the same managed folder ---
p = by["新照片.jpg"]["path"]
np_ = dm.move_to(p, "重要文件", journal.batch("移动到 重要文件"))
check("move_to category inside extra", np_.startswith(os.path.join(desk, dm.EXTRA_SUB, "重要文件")))

# --- undo ---
bs = journal.batches()
check("move recorded", bs[0]["label"] == "移动到 重要文件" and bs[0]["moves"][0][1] == np_)
k, probs = journal.undo(bs[0]["id"])
check("undo single move", k == 1 and not probs and os.path.isfile(dst) and not os.path.exists(np_))
check("undo twice refused", journal.undo(bs[0]["id"])[0] == 0)
first = [b for b in journal.batches() if b["label"] == "自动整理"][0]
# 原位置被占用时改名而不是覆盖
mk(os.path.join(desk, "新照片.jpg"), b"other")
total, probs, n = journal.undo_since(first["id"])
check("undo_since undoes all later batches", n == 2 and total == 4)
check("occupied original renamed, not overwritten",
      open(os.path.join(desk, "新照片.jpg"), "rb").read() == b"other"
      and os.path.isfile(os.path.join(desk, "新照片 (原位置已有同名).jpg")) and any("同名" in x for x in probs))
check("restored files back in place", os.path.isfile(os.path.join(desk, "b.docx")) and os.path.isfile(old)
      and os.path.isfile(os.path.join(dm.ROOT, "a.zip")))
dm.remove_empty_dirs()
check("empty 已整理 removed after undo", not os.path.exists(os.path.join(desk, dm.EXTRA_SUB)))
check("all batches marked undone", all(b["undone"] for b in journal.batches()))

# 撤销移回的文件不会马上又被整理走（包括重启之后）
moved, _ = dm.organize(settle=0)
check("restored files not re-organized", not set(moved) & {"b.docx", "旧报告.pdf", "a.zip"})
journal.init(cfg_dir)
moved, _ = dm.organize(settle=0)
check("no_auto survives restart", not set(moved) & {"b.docx", "旧报告.pdf", "a.zip"})
# 用户把撤销的文件移走后，名单自动失效
os.remove(os.path.join(dm.ROOT, "a.zip"))
check("no_auto drops gone files", os.path.normcase(os.path.join(dm.ROOT, "a.zip")) not in journal.no_auto())

# --- 移动记录损坏的行被忽略 ---
with open(os.path.join(cfg_dir, "moves.jsonl"), "a", encoding="utf-8") as f:
    f.write('{"b": "x", "t": 1, "s": "half\n')
check("corrupt line ignored", len(journal.batches()) >= 3)

# --- cleanup only touches extras with clean=True ---
deleted = []
dm.recycle = lambda paths: [deleted.append(p) or os.remove(p) for p in paths]
oldx = mk(os.path.join(desk, dm.EXTRA_SUB, "重要文件", "2020-01", "老文档.txt"), age_days=400)
oldp = mk(os.path.join(dm.ROOT, "重要文件", "2020-01", "老下载.txt"), age_days=400)
dm.cleanup(dict(dm.DEFAULTS, clean_on=True, clean_days=30, protect=[]))
check("cleanup skips extra folders by default", os.path.exists(oldx) and not os.path.exists(oldp))
dm.EXTRA[0]["clean"] = True
dm.cleanup(dict(dm.DEFAULTS, clean_on=True, clean_days=30, protect=[]))
check("cleanup includes extra with clean on", not os.path.exists(oldx))

# --- 规则改名：其他文件夹的分类文件夹也跟着改（在 GUI 中测试），项目文件夹始终不整理 ---
mk(os.path.join(desk, "Cargo.toml"))
mk(os.path.join(desk, "c.pdf"))
moved, _ = dm.organize(settle=0)
check("folder turned into a project is left alone", "c.pdf" not in moved)

# --- 规则方案：其他文件夹使用独立的分类规则 ---
os.remove(os.path.join(desk, "Cargo.toml"))
raw = dict(schemes=[{"name": "桌面规则", "rules": [["截图", "png jpg"], ["报价", "", "报价, quote"]]},
                    {"name": "主文件夹规则", "rules": [["X", "x"]]},          # 与主文件夹规则同名：丢弃
                    {"name": "坏的", "rules": [["a/b", "x"]]},                 # 规则不合法：丢弃
                    {"name": "桌面规则", "rules": [["Y", "y"]]}],              # 重名：丢弃
           folders=[{"path": desk, "scheme": "桌面规则"}, {"path": os.path.join(base, "u"), "scheme": "不存在"}],
           protect=["截图", "重要文件", "乱写"])
c = dm.sanitize_cfg(raw)
check("sanitize schemes", [x["name"] for x in c["schemes"]] == ["桌面规则"]
      and c["folders"][0]["scheme"] == "桌面规则" and c["folders"][1]["scheme"] == "")
check("protect may name a scheme category", c["protect"] == ["截图", "重要文件"])
dm.apply_folders(c); dm.apply_schemes(c)
check("folder uses its scheme", dm.cats_for(desk) == ["截图", "报价", "其他文件"] and dm.cats_for(dm.ROOT) == dm.CATS)
check("category_for per folder", dm.category_for("a.png", desk) == "截图" and dm.category_for("a.png") == "图片"
      and dm.category_for("客户报价单.pdf", desk) == "报价" and dm.category_for("x.pdf", desk) == "其他文件")
check("all_cats unions schemes", "截图" in dm.all_cats() and dm.all_cats()[-1] == "其他文件" and "图片" in dm.all_cats())
check("glyphs for scheme cats", "截图" in dm.GLYPH)
dm.EXTRA[0]["added"] = 0
mk(os.path.join(desk, "新截图.png"))
moved, _ = dm.organize(settle=0)
check("extra organized by its own scheme", os.path.isfile(os.path.join(desk, dm.EXTRA_SUB, "截图", month, "新截图.png")))
mk(os.path.join(dm.ROOT, "主.png"))
dm.organize(settle=0)
check("primary still uses primary rules", os.path.isfile(os.path.join(dm.ROOT, "图片", month, "主.png")))
# 换方案之前“已整理”里的旧分类文件夹仍会被扫描到，并能按新规则重新整理
old_cat = mk(os.path.join(desk, dm.EXTRA_SUB, "图片", "2024-01", "老图.png"))
items = {x["name"]: x for x in dm.scan()[0]}
check("old category under 已整理 still listed", items["老图.png"]["cat"] == "图片")
plan = {os.path.basename(a): b for a, _, b in dm.plan_reorganize()}
check("reorganize moves old-scheme files to new scheme", plan.get("老图.png") == "截图")
check("move_to with category name stays in folder",
      dm.move_to(old_cat, "截图", journal.batch("t")).startswith(os.path.join(desk, dm.EXTRA_SUB, "截图")))

# --- 规则文件导入 ---
rf = os.path.join(base, "rules.json")
open(rf, "w", encoding="utf-8").write('{"format": "DownloadButler.rules", "name": "朋友的规则", '
                                     '"rules": [["文档", "PDF, docx"], ["票据", "", "发票, invoice"]]}')
norm, name, err = dm.read_rules_file(rf)
check("read rules file", not err and name == "朋友的规则" and norm == [["文档", ".pdf .docx"], ["票据", "", "发票, invoice"]])
open(rf, "w", encoding="utf-8").write('[["A", "a"]]')
check("plain list rules file", dm.read_rules_file(rf)[0] == [["A", ".a"]] and dm.read_rules_file(rf)[1] == "rules")
for bad in ("not json", '{"rules": [["其他文件", "x"]]}', '{"x": 1}'):
    open(rf, "w", encoding="utf-8").write(bad)
    check(f"bad rules file rejected: {bad[:12]}", dm.read_rules_file(rf)[2] != "")

print("FAILURES:", fails)
sys.exit(1 if fails else 0)
