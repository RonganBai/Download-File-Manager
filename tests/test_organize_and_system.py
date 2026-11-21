import importlib.util, os, sys, tempfile, time
os.environ["QT_QPA_PLATFORM"] = "offscreen"
repo = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("dm", os.path.join(repo, "download_manager.py"))
dm = importlib.util.module_from_spec(spec); spec.loader.exec_module(dm)
from PyQt6.QtCore import QCoreApplication, Qt
from PyQt6.QtNetwork import QLocalServer, QLocalSocket

fails = 0
def check(name, cond):
    global fails
    print(("PASS " if cond else "FAIL ") + name); fails += not cond

def touch(name, age=60, size=3):
    p = os.path.join(dm.ROOT, name)
    with open(p, "wb") as f: f.write(b"x" * size)
    t = time.time() - age; os.utime(p, (t, t))
    return p

# --- organize: partial downloads / companion files / settle delay ---
dm.ROOT = tempfile.mkdtemp(prefix="dmorg_")
# 文件刚创建，创建时间≈现在；为了测试“已稳定”的文件，settle 设为 0 秒以下不可能，这里用 settle=0 模拟
for n in ("a.crdownload", "b.zip.xltd", "c.zip.xltd.cfg", "d.!qB", "e.opdownload", "f.mkv.part"):
    touch(n)
touch("movie.mkv", size=0)                         # Firefox 占位文件，旁边有 movie.mkv.part
open(os.path.join(dm.ROOT, "movie.mkv.part"), "w").close()
touch("iso.iso"); open(os.path.join(dm.ROOT, "iso.iso.aria2"), "w").close()   # aria2 下载中
touch("done.pdf")
moved, retry = dm.organize(settle=0)
check("only finished file moved", moved == ["done.pdf"])
check("no retry for in-progress downloads", retry is None)
left = set(os.listdir(dm.ROOT))
check("partials & companions left in place", {"movie.mkv", "iso.iso", "a.crdownload", "c.zip.xltd.cfg"} <= left)

touch("fresh.png")                                  # 刚到达
moved, retry = dm.organize(settle=10)
check("fresh file waits for settle", "fresh.png" not in moved and retry is not None and 9 <= retry <= 11)

# --- bad_filename ---
check("reserved name CON.txt", dm.bad_filename("CON.txt"))
check("reserved name lpt1", dm.bad_filename("lpt1"))
check("trailing dot", dm.bad_filename("a.txt."))
check("trailing space", dm.bad_filename("a.txt "))
check("control char", dm.bad_filename("a\tb"))
check("normal ok", dm.bad_filename("报告 v2.pdf") == "" and dm.bad_filename("CONSOLE.txt") == "")

# --- settle_sec sanitize ---
check("settle clamp", dm.sanitize_cfg(dict(settle_sec=0))["settle_sec"] == 3 and
      dm.sanitize_cfg(dict(settle_sec=99999))["settle_sec"] == 600)

# --- single instance: per-user name, user-only pipe ---
uid = dm.current_user_id()
check(f"user SID resolved ({uid[:8]}…)", uid.startswith("S-1-5-"))
name = dm.instance_name()
check("instance name per user", name.startswith("DownloadButler-") and len(name) == 31)
app = QCoreApplication([])
srv = QLocalServer(); srv.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
check("listen with UserAccessOption", srv.listen(name + "-test"))
s = QLocalSocket(); s.connectToServer(name + "-test")
check("same user can connect", s.waitForConnected(1000))
srv.close()

# --- CleanupWorker in background thread ---
dm.ROOT = tempfile.mkdtemp(prefix="dmclean_")
os.makedirs(os.path.join(dm.ROOT, "图片", "2020-01"))
got = []
w = dm.CleanupWorker(None, dict(dm.DEFAULTS, clean_on=True))
w.done.connect(lambda n, f, notes: got.append((n, f, notes)), Qt.ConnectionType.DirectConnection)
w.start(); w.wait(10000)
check("worker emits done", got and got[0][0] == 0)
orig = dm.cleanup
dm.cleanup = lambda cfg: 1 / 0
got.clear(); w = dm.CleanupWorker(None, dm.DEFAULTS)
w.done.connect(lambda n, f, notes: got.append(notes), Qt.ConnectionType.DirectConnection)
w.start(); w.wait(10000)
check("worker reports exception", got and "清理出错" in got[0][0])
dm.cleanup = orig

# --- thumbnail cache prune ---
class Fake: pass
t = Fake(); t.cache_dir = tempfile.mkdtemp(prefix="dmthumb_"); t.MAX_FILES = 30
for i in range(40):
    p = os.path.join(t.cache_dir, f"{i:03}.png"); open(p, "w").close(); os.utime(p, (i, i))
dm.ThumbLoader.prune(t)
rest = sorted(os.listdir(t.cache_dir))
check(f"prune keeps newest 20 (kept {len(rest)})", len(rest) == 20 and rest[0] == "020.png")

print("FAILURES:", fails); sys.exit(fails)
