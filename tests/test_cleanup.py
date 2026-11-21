import ctypes, importlib.util, json, os, subprocess, sys, tempfile, time
from ctypes import wintypes

repo = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("dm", os.path.join(repo, "download_manager.py"))
dm = importlib.util.module_from_spec(spec); spec.loader.exec_module(dm)

def set_ctime(path, ts):
    k32 = ctypes.windll.kernel32
    k32.CreateFileW.restype = wintypes.HANDLE
    h = k32.CreateFileW(path, 0x100, 7, None, 3, 0x02000000, None)  # FILE_WRITE_ATTRIBUTES
    ft = int((ts + 11644473600) * 10**7)
    f = wintypes.FILETIME(ft & 0xFFFFFFFF, ft >> 32)
    assert k32.SetFileTime(wintypes.HANDLE(h), ctypes.byref(f), None, None)
    k32.CloseHandle(wintypes.HANDLE(h))

def mk(rel, size, age_days=0, ctime_days=None):
    p = os.path.join(dm.ROOT, rel); os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "wb") as f: f.write(b"x" * size)
    t = time.time() - age_days * 86400
    os.utime(p, (t, t))
    set_ctime(p, time.time() - (ctime_days if ctime_days is not None else age_days) * 86400)
    return p

deleted = []
dm.recycle = lambda paths: [deleted.append(p) or os.remove(p) for p in paths]
fails = 0
def check(name, cond):
    global fails
    print(("PASS " if cond else "FAIL ") + name); fails += not cond

def fresh():
    deleted.clear()
    dm.ROOT = tempfile.mkdtemp(prefix="dmtest_")

base = dict(dm.DEFAULTS)
GB = 1024 ** 3

# 1. 容量阈值：受保护文件本身超过阈值 -> 一个都不删
fresh()
dm.MB_save = dm.MB
cfg = dict(base, cap_on=True, cap_gb=0.5)
mk("重要文件/2024-01/big.pdf", 1)          # 用 monkeypatch 大小，避免写 GB 级文件
mk("图片/2024-01/a.png", 1, 10); mk("图片/2024-01/b.png", 1, 5)
real_scan = dm.scan
def fake_scan():
    items, dirs = real_scan()
    for x in items:
        if x["name"] == "big.pdf": x["size"] = int(0.8 * GB)
    return items, dirs
dm.scan = fake_scan
n, freed, notes = dm.cleanup(cfg)
check("cap: protected over cap deletes nothing", n == 0 and not deleted and notes)
dm.scan = real_scan

# 2. 容量阈值：可达成时只删最旧的、够用即止
fresh()
for i, age in enumerate((30, 20, 10)):
    mk(f"视频/2024-01/v{i}.mp4", 1, age)
def fake_scan2():
    items, dirs = real_scan()
    for x in items: x["size"] = int(0.3 * GB)
    return items, dirs
dm.scan = fake_scan2
n, freed, notes = dm.cleanup(dict(base, cap_on=True, cap_gb=0.7))
check("cap: deletes only oldest one", [os.path.basename(p) for p in deleted] == ["v0.mp4"])
dm.scan = real_scan

# 3. 旧 mtime 但刚到达的文件不被按天清理
fresh()
mk("压缩包/2019-01/old_but_new.zip", 10, age_days=2000, ctime_days=0)
mk("压缩包/2019-01/really_old.zip", 10, age_days=2000, ctime_days=100)
n, _, _ = dm.cleanup(dict(base, clean_on=True, clean_days=30))
check("age: uses arrival time", [os.path.basename(p) for p in deleted] == ["really_old.zip"])

# 4. 目录联接不越界
fresh()
outside = tempfile.mkdtemp(prefix="dmoutside_")
victim = os.path.join(outside, "victim.txt"); open(victim, "w").close()
t = time.time() - 400 * 86400; os.utime(victim, (t, t)); set_ctime(victim, t)
os.makedirs(os.path.join(outside, "emptydir"))
os.makedirs(os.path.join(dm.ROOT, "代码"))
subprocess.run(["cmd", "/c", "mklink", "/J", os.path.join(dm.ROOT, "代码", "link"), outside], check=True, capture_output=True)
mk("代码/2024-01/old.py", 5, 400)
items, _ = dm.scan()
check("junction: scan skips", all("victim" not in x["path"] for x in items))
dm.cleanup(dict(base, clean_on=True, clean_days=30))
check("junction: victim kept", os.path.exists(victim) and os.path.isdir(os.path.join(outside, "emptydir")))
check("junction: normal old file cleaned", any(p.endswith("old.py") for p in deleted))
check("inside_managed rejects junction path", not dm.inside_managed(os.path.join(dm.ROOT, "代码", "link", "victim.txt")))

# 5. 回收站容量检测
lim = dm.recycle_limit(dm.ROOT)
check(f"recycle_limit on temp drive > 0 ({lim // (1024**2)} MB)", lim > 0)
check("can_recycle rejects huge file", not dm.can_recycle(dm.ROOT, 1 << 50))
check("no recycle bin on network path", dm.recycle_limit(r"\\localhost\c$\Windows") == 0)

# 6. 配置：校验、损坏备份、原子写入
d = tempfile.mkdtemp(prefix="dmcfg_"); dm.CFG_DIR = d; dm.CFG_PATH = os.path.join(d, "config.json")
c = dm.sanitize_cfg(dict(clean_days=0, cap_gb="abc", protect=["重要文件", "bogus"], clean_on="yes", theme="x", future_key=1))
check("sanitize ranges/types", c["clean_days"] == 1 and c["cap_gb"] == 20.0 and c["protect"] == ["重要文件"]
      and c["clean_on"] is False and c["theme"] == "dark" and c["future_key"] == 1)
with open(dm.CFG_PATH, "w") as f: f.write("{broken")
c = dm.load_cfg()
check("corrupt cfg backed up", c == dm.DEFAULTS and any(n.startswith("config.json.bad-") for n in os.listdir(d)))
dm.save_cfg(dict(c, clean_days=7))
check("atomic save roundtrip", dm.load_cfg()["clean_days"] == 7 and not os.path.exists(dm.CFG_PATH + ".tmp"))

print("FAILURES:", fails); sys.exit(fails)
