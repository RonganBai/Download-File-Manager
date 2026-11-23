# -*- coding: utf-8 -*-
"""界面冒烟测试：在不可见的窗口里构建主界面并操作设置页。
下载文件夹、配置、缩略图缓存全部重定向到临时目录，不会动真实文件。用法：python tests/smoke_gui.py"""
import importlib.util, os, sys, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["LOCALAPPDATA"] = tempfile.mkdtemp(prefix="dmlad_")
repo = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, repo)   # 让 download_manager 能导入同目录的 converter_link
spec = importlib.util.spec_from_file_location("dm", os.path.join(repo, "download_manager.py"))
dm = importlib.util.module_from_spec(spec); spec.loader.exec_module(dm)
dm.ROOT = tempfile.mkdtemp(prefix="dmsmoke_")
dm.CFG_DIR = tempfile.mkdtemp(prefix="dmcfg_"); dm.CFG_PATH = os.path.join(dm.CFG_DIR, "config.json")
dm.set_autostart = lambda on: None
open(os.path.join(dm.ROOT, "x.pdf"), "w").close()
os.makedirs(os.path.join(dm.ROOT, "图片", "2024-01"))
open(os.path.join(dm.ROOT, "图片", "2024-01", "p.png"), "w").close()
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QTimer
app = QApplication([]); app.setQuitOnLastWindowClosed(False)
w = dm.Main(start_hidden=False)
restarts = []
w.restart = lambda: restarts.append(1)           # 不真的重启进程
dm.Dialog.exec = lambda self: True                # 自动确认对话框

# 等待时间 / 年-月子文件夹
w.open_settings(); w.s_settle.setValue(20)
assert dm.load_cfg()["settle_sec"] == 20
w.s_month.setChecked(False); w.s_month.toggled.emit(False)
assert dm.BY_MONTH is False and dm.load_cfg()["by_month"] is False
w.s_month.toggled.emit(True)

# 分类规则编辑器：把“图片”改名为“Pictures”，新增一个分类，保存
row = next(r for r in w.rule_rows if r["name"].text() == "图片")
row["name"].setText("Pictures")
w.add_rule_row("", "", None)
w.rule_rows[-1]["name"].setText("电子书"); w.rule_rows[-1]["exts"].setText("epub, mobi azw3")
w.save_rules()
cfg = dm.load_cfg()
assert restarts, "restart not requested"
assert ["电子书", ".epub .mobi .azw3"] in cfg["rules"] and any(r[0] == "Pictures" for r in cfg["rules"])
assert os.path.isfile(os.path.join(dm.ROOT, "Pictures", "2024-01", "p.png")), "category folder not renamed"
assert not os.path.exists(os.path.join(dm.ROOT, "图片"))

# 非法规则：不保存、不重启
restarts.clear()
w.rule_rows[-1]["name"].setText("其他文件")
w.save_rules()
assert not restarts and dm.load_cfg()["rules"] == cfg["rules"]

# 恢复默认规则 → 保存时写回空列表（使用内置规则）
w.reset_rules(); w.save_rules()
assert restarts and dm.load_cfg()["rules"] == []

# 常用分类模板 + 关键词：添加“移民身份文件”，保存后带关键词、并自动加入受保护分类
restarts.clear()
w.add_preset(*dm.PRESETS[0])
w.add_preset(*dm.PRESETS[0])                       # 重复添加被拒绝
assert sum(r["name"].text() == "移民身份文件" for r in w.rule_rows) == 1
w.save_rules()
cfg = dm.load_cfg()
assert restarts and any(r[0] == "移民身份文件" and len(r) == 3 and "passport" in r[2] for r in cfg["rules"])
assert "移民身份文件" in cfg["protect"]
w.cfg = cfg

# 重新整理已有文件：规则生效后，“图片”里的护照照片挪到“移民身份文件”
dm.apply_rules(cfg["rules"])
os.makedirs(os.path.join(dm.ROOT, "图片", "2023-05"), exist_ok=True)
open(os.path.join(dm.ROOT, "图片", "2023-05", "passport photo.jpg"), "w").close()
w.reorganize_existing()
assert any(f == "passport photo.jpg" for _, _, fs in os.walk(os.path.join(dm.ROOT, "移民身份文件")) for f in fs)

# 清理垃圾文件：列表对话框里取消勾选一项，只删其余的
os.makedirs(os.path.join(dm.ROOT, "散落"))
for n in ("Thumbs.db", "._a.jpg"):
    p = os.path.join(dm.ROOT, "散落", n); open(p, "w").write("x")
gone = []
dm.recycle = lambda paths: [gone.append(os.path.basename(p)) or os.remove(p) for p in paths]
orig_init = dm.Dialog.__init__
def init_and_uncheck(self, *a, **k):
    orig_init(self, *a, **k)
    tree = k.get("extra")
    if tree is not None:                       # 取消勾选 ._a.jpg 所在的组
        for i in range(tree.topLevelItemCount()):
            g = tree.topLevelItem(i)
            if "macOS" in g.text(0):
                g.setCheckState(0, dm.Qt.CheckState.Unchecked)
dm.Dialog.__init__ = init_and_uncheck
import time as _t
w.clean_junk()
assert w.__dict__.get("_tasks"), "junk scan should run in background"
w.clean_junk()                                     # 扫描中再点一次：不重复启动
assert len(w._tasks) == 1
deadline = _t.time() + 20
while w._tasks and _t.time() < deadline:           # 等后台扫描 → 弹窗确认 → 后台删除 全部完成
    app.processEvents(); _t.sleep(0.02)
assert not w._tasks, "background junk tasks did not finish"
dm.Dialog.__init__ = orig_init
assert gone == ["Thumbs.db"], gone
assert os.path.exists(os.path.join(dm.ROOT, "散落", "._a.jpg"))

# 管理的文件夹：拒绝系统目录
restarts.clear()
dm.QFileDialog.getExistingDirectory = staticmethod(lambda *a, **k: os.environ["WINDIR"])
w.choose_root(False)
assert not restarts and dm.load_cfg()["root"] == ""
newroot = tempfile.mkdtemp(prefix="dmnewroot_")
dm.QFileDialog.getExistingDirectory = staticmethod(lambda *a, **k: newroot)
w.choose_root(False)
assert restarts and dm.load_cfg()["root"] == os.path.abspath(newroot)

# 整理 + 后台清理
w.do_organize(manual=True)
ok = w.start_cleanup(manual=True)
assert ok and not w.start_cleanup(manual=True)     # 第二次不重复启动
def finish():
    assert w._clean_worker is None, "cleanup did not finish"
    print("SMOKE OK"); w.thumbs.stop(); app.quit()
QTimer.singleShot(3000, finish)
app.exec()
