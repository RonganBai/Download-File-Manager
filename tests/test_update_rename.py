# -*- coding: utf-8 -*-
"""版本更新（不联网，模拟 GitHub 返回）与重命名重名处理的测试。用法：python tests/test_update_rename.py"""
import hashlib, importlib.util, io, os, sys, tempfile

repo = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, repo)
import updater
spec = importlib.util.spec_from_file_location("dm", os.path.join(repo, "download_manager.py"))
dm = importlib.util.module_from_spec(spec); spec.loader.exec_module(dm)

fails = 0
def check(name, cond):
    global fails
    print(("PASS " if cond else "FAIL ") + name); fails += not cond

# ---------- 版本号 ----------
check("parse_version", updater.parse_version("v2.10.1") == (2, 10, 1, 0) and updater.parse_version("2.9") == (2, 9, 0, 0))
check("parse_version rejects junk", updater.parse_version("latest") is None and updater.parse_version("v2.1-beta") is None)
check("2.10.0 newer than 2.9.2 (not string compare)", updater.is_newer("v2.10.0", "2.9.2"))
check("same / older not newer", not updater.is_newer("v2.10.0", "2.10.0") and not updater.is_newer("v2.9.9", "2.10.0"))
check("app version parses", updater.parse_version(dm.VERSION) is not None)

# ---------- 解析发布信息 ----------
payload = b"fake installer bytes" * 1000
sha = hashlib.sha256(payload).hexdigest()
P = updater.ASSET_PREFIX
def rel(**kw):
    a = dict(name="DownloadButler-Setup-9.0.0.exe", browser_download_url=P + "v9.0.0/DownloadButler-Setup-9.0.0.exe",
             size=len(payload), digest="sha256:" + sha)
    a.update(kw.pop("asset", {}))
    d = dict(tag_name="v9.0.0", body="新功能", html_url="https://github.com/" + updater.REPO + "/releases/tag/v9.0.0",
             draft=False, prerelease=False, assets=[dict(name="notes.txt", browser_download_url=P + "x/notes.txt"), a])
    d.update(kw)
    return d
info = updater.parse_release(rel(), "2.10.0")
check("release parsed", info and info["version"] == "9.0.0" and info["sha256"] == sha and info["size"] == len(payload))
check("installable", updater.can_install(info))
check("older release ignored", updater.parse_release(rel(tag_name="v1.0.0"), "2.10.0") is None)
check("prerelease ignored", updater.parse_release(rel(prerelease=True), "2.10.0") is None)
check("draft ignored", updater.parse_release(rel(draft=True), "2.10.0") is None)
i2 = updater.parse_release(rel(asset=dict(digest="")), "2.10.0")
check("no digest -> not installable (page only)", i2 and not updater.can_install(i2))
i3 = updater.parse_release(rel(asset=dict(browser_download_url="https://evil.example/DownloadButler-Setup-9.0.0.exe")), "2.10.0")
check("foreign download host rejected", i3 and not updater.can_install(i3))
i4 = updater.parse_release(rel(asset=dict(name="evil.exe")), "2.10.0")
check("unexpected asset name rejected", i4 and not updater.can_install(i4))
i5 = updater.parse_release(rel(html_url="https://evil.example/x"), "2.10.0")
check("foreign release page replaced", i5["page"] == updater.RELEASES_URL)
check("installer args", updater.installer_args(True)[-1] == "/relaunch=show" and "/SILENT" in updater.installer_args(False))

# ---------- 下载与校验（替换网络请求） ----------
class Resp(io.BytesIO):
    def __enter__(self): return self
    def __exit__(self, *a): self.close()
def fake_get(data):
    return lambda url, timeout, accept=None: Resp(data)
d = tempfile.mkdtemp(prefix="dmupd_")
open(os.path.join(d, "old-Setup.exe"), "wb").close()
updater._get = fake_get(payload)
seen = []
path = updater.download(info, d, progress=seen.append)
check("download ok + verified", os.path.isfile(path) and open(path, "rb").read() == payload and seen[-1] == 100)
check("old installers cleaned", sorted(os.listdir(d)) == [info["name"]])
for data, why in ((payload[:-1] + b"X", "hash mismatch"), (payload[:100], "truncated"), (payload + b"extra", "too big")):
    updater._get = fake_get(data)
    try:
        updater.download(info, d); ok = False
    except updater.UpdateError:
        ok = True
    check(f"download rejects {why}, leaves nothing", ok and os.listdir(d) == [])
try:
    updater.download(i2, d); ok = False
except updater.UpdateError:
    ok = True
check("download refuses release without digest", ok)
# ---------- 重命名重名 ----------
t = tempfile.mkdtemp(prefix="dmren_")
a, b = os.path.join(t, "a.pdf"), os.path.join(t, "b.pdf")
for p in (a, b):
    open(p, "w").close()
check("free name kept", dm.rename_target(a, "c.pdf") == os.path.join(t, "c.pdf"))
check("clash -> numbered", dm.rename_target(a, "b.pdf") == os.path.join(t, "b (1).pdf"))
open(os.path.join(t, "b (1).pdf"), "w").close()
check("clash twice -> (2)", dm.rename_target(a, "b.pdf") == os.path.join(t, "b (2).pdf"))
check("case-only rename allowed", dm.rename_target(a, "A.pdf") == os.path.join(t, "A.pdf"))
os.makedirs(os.path.join(t, "v1.2")); os.makedirs(os.path.join(t, "src"))
check("folder clash keeps dotted name", dm.rename_target(os.path.join(t, "src"), "v1.2") == os.path.join(t, "v1.2 (1)"))

# ---------- 配置 ----------
c = dm.sanitize_cfg(dict(update_mode="weird", update_last="x"))
check("bad update settings fall back", c["update_mode"] == "notify" and c["update_last"] == 0.0)
check("valid update mode kept", dm.sanitize_cfg(dict(update_mode="auto"))["update_mode"] == "auto")

# ---------- 快速加后缀 ----------
t2 = tempfile.mkdtemp(prefix="dmsfx_")
f = os.path.join(t2, "报告.pdf"); open(f, "w").close()
check("suffix before extension", dm.add_suffix_name(f, "_已签字") == "报告_已签字.pdf")
check("{date} expanded", dm.add_suffix_name(f, "_{date}") == "报告_" + dm.time.strftime("%Y%m%d") + ".pdf")
g = os.path.join(t2, "备份.tar.gz"); open(g, "w").close()
check("tar.gz kept together", dm.add_suffix_name(g, "_v2") == "备份_v2.tar.gz")
h = os.path.join(t2, "报告_已签字.pdf"); open(h, "w").close()
check("no double suffix", dm.add_suffix_name(h, "_已签字") is None)
os.makedirs(os.path.join(t2, "资料v1.0"))
check("folder: appended at end", dm.add_suffix_name(os.path.join(t2, "资料v1.0"), "_旧") == "资料v1.0_旧")
check("parse_suffixes dedupes", dm.parse_suffixes(" _a \n\n_b\n_a") == (["_a", "_b"], ""))
check("parse_suffixes rejects bad chars", dm.parse_suffixes("_ok\n_a/b")[1] != "")
check("parse_suffixes rejects trailing dot", dm.parse_suffixes("_v1.")[1] != "")
check("sanitize drops bad suffixes", dm.sanitize_cfg(dict(name_suffixes=["_x", 3, "a:b"]))["name_suffixes"] == ["_x"])
check("default suffixes valid", dm.sanitize_cfg({})["name_suffixes"] == dm.DEFAULTS["name_suffixes"])

# ---------- 快速更改扩展名 ----------
t3 = tempfile.mkdtemp(prefix="dmext_")
f = os.path.join(t3, "资料.rar"); open(f, "w").close()
check("ext swapped", dm.change_ext_name(f, ".zip") == "资料.zip")
check("ext removed", dm.change_ext_name(f, "") == "资料")
check("same ext (case-insensitive) -> None", dm.change_ext_name(os.path.join(t3, "a.ZIP"), ".zip") is None)
check("tar.gz swapped whole", dm.change_ext_name(os.path.join(t3, "b.tar.gz"), ".zip") == "b.zip")
check("dotfile untouched", dm.change_ext_name(os.path.join(t3, ".gitignore"), ".txt") == ".gitignore.txt")
os.makedirs(os.path.join(t3, "dir.v1"))
check("folder -> None", dm.change_ext_name(os.path.join(t3, "dir.v1"), ".zip") is None)
check("parse_ext_list", dm.parse_ext_list("zip, .RAR  7z zip") == ([".zip", ".rar", ".7z"], ""))
check("parse_ext_list rejects bad", dm.parse_ext_list("zip a:b")[1] != "")
check("sanitize ext_list", dm.sanitize_cfg(dict(ext_list=[".zip", "a:b", 5, "JPG"]))["ext_list"] == [".zip", ".jpg"])
check("default ext_list valid", dm.sanitize_cfg({})["ext_list"] == dm.DEFAULTS["ext_list"])

print("FAILURES:", fails); sys.exit(fails)
