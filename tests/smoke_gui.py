# -*- coding: utf-8 -*-
"""界面冒烟测试：在不可见的窗口里构建主界面并操作设置页。
下载文件夹、配置、缩略图缓存全部重定向到临时目录，不会动真实文件。用法：python tests/smoke_gui.py"""
import importlib.util, os, sys, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["LOCALAPPDATA"] = tempfile.mkdtemp(prefix="dmlad_")
repo = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, repo)   # 让 download_manager 能导入同目录的 converter_link / archive
spec = importlib.util.spec_from_file_location("dm", os.path.join(repo, "download_manager.py"))
dm = importlib.util.module_from_spec(spec); spec.loader.exec_module(dm)
dm.ROOT = tempfile.mkdtemp(prefix="dmsmoke_")
dm.CFG_DIR = tempfile.mkdtemp(prefix="dmcfg_"); dm.CFG_PATH = os.path.join(dm.CFG_DIR, "config.json")
dm.set_autostart = lambda on: None
open(os.path.join(dm.ROOT, "x.pdf"), "w").close()
os.makedirs(os.path.join(dm.ROOT, "图片", "2024-01"))
open(os.path.join(dm.ROOT, "图片", "2024-01", "p.png"), "w").close()
from PyQt6.QtWidgets import QApplication, QMenu
from PyQt6.QtCore import QTimer
import time as _t
app = QApplication([]); app.setQuitOnLastWindowClosed(False)
w = dm.Main(start_hidden=False)
w.cfg["tour_done"] = True                         # 自动弹出的新手教程在下面单独测试
dm.Dialog.exec = lambda self: True                # 自动确认对话框

# 帮助中心：每个主题都能打开；搜索按标题 / 关键词 / 正文过滤
w.open_help()
assert w.pages.currentIndex() == 3 and w.btn_help.isChecked()
for tid, title, _, _ in dm.help_content.TOPICS:
    w.show_help_topic(tid)
    assert title.split("、")[0][:2] in w.help_view.toPlainText() or w.help_view.toPlainText().strip(), tid
w.help_search.setText("密码本")
shown = [t for t, b in w.help_btns.items() if not b.isHidden()]
assert "password" in shown and "browse" not in shown, shown
w.help_search.setText("完全不存在的词xyz")
assert not w.help_empty.isHidden()
w.help_search.clear()
assert all(not b.isHidden() for b in w.help_btns.values())
# 新手教程：每一步都能切到对应页面，完成后记住不再自动弹出
tabs = [b.text() for b in w.settings_tabs]
for _, _, where in dm.help_content.TOUR:
    assert not where.startswith("settings:") or where.split(":", 1)[1] in tabs, where
w.cfg["tour_done"] = False
w.start_tour()
for i, (_, _, where) in enumerate(dm.help_content.TOUR):
    w.tour.go(i); app.processEvents()
    if where != "home":                             # 每一步都要高亮到一个可见的控件
        tgt = w.tour_target(where)
        assert tgt is not None and tgt.isVisible(), where
w.tour.b_next.click()                              # 最后一步点“完成”
assert w.tour is None and dm.load_cfg()["tour_done"] and w.tour_ring.isHidden()
w.maybe_tour(); assert w.tour is None              # 看过以后不再自动弹出

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
assert ["电子书", ".epub .mobi .azw3"] in cfg["rules"] and any(r[0] == "Pictures" for r in cfg["rules"])
assert os.path.isfile(os.path.join(dm.ROOT, "Pictures", "2024-01", "p.png")), "category folder not renamed"
assert not os.path.exists(os.path.join(dm.ROOT, "图片"))
# 热更新：不重启，左侧分类、受保护分类、文件列表立即按新规则显示
assert "Pictures" in w.cat_btns and "图片" not in w.cat_btns and "电子书" in w.cat_btns
assert "电子书" in w.protect_boxes and "Pictures" in dm.CATS
assert any(x["cat"] == "Pictures" for x in w.items), "file list not refreshed"
assert w.pages.currentIndex() == 1 and any(r["name"].text() == "电子书" for r in w.rule_rows)

# 设置菜单栏：切换分栏；保存规则重建页面后仍停留在原来的分栏
assert [b.text() for b in w.settings_tabs][w.settings_stack.currentIndex()] in ("常规", "分类规则")
w.show_settings_tab("分类规则")
assert w.settings_tabs[w.settings_stack.currentIndex()].text() == "分类规则"

# 保存时点“取消”：撤销修改，恢复到修改之前
from PyQt6.QtWidgets import QPushButton
dm.Dialog.exec = lambda self: False
w.rule_rows[0]["name"].setText("改了但取消")
w.save_rules()
assert w.rule_rows[0]["name"].text() != "改了但取消" and dm.load_cfg()["rules"] == cfg["rules"]
# 删除分类需要二次确认：取消则保留，确认后才删掉这一行（保存前不影响文件）
n0 = len(w.rule_rows)
del_btn = lambda r: [b for b in r["w"].findChildren(QPushButton) if b.text() == "删除"][0]
del_btn(w.rule_rows[0]).click()
assert len(w.rule_rows) == n0
dm.Dialog.exec = lambda self: True
del_btn(w.rule_rows[0]).click()
assert len(w.rule_rows) == n0 - 1
w.revert_rules()
assert len(w.rule_rows) == n0

w.save_rules()
assert w.settings_tabs[w.settings_stack.currentIndex()].text() == "分类规则"

# 非法规则：不保存、不生效
before = list(w.cat_btns)
w.rule_rows[-1]["name"].setText("其他文件")
w.save_rules()
assert dm.load_cfg()["rules"] == cfg["rules"] and list(w.cat_btns) == before

# 恢复默认规则 → 保存时写回空列表（使用内置规则）
w.reset_rules(); w.save_rules()
assert dm.load_cfg()["rules"] == [] and "图片" in w.cat_btns and "电子书" not in w.cat_btns

# 常用分类模板 + 关键词：添加“移民身份文件”，保存后带关键词、并自动加入受保护分类
w.add_preset(*dm.PRESETS[0])
w.add_preset(*dm.PRESETS[0])                       # 重复添加被拒绝
assert sum(r["name"].text() == "移民身份文件" for r in w.rule_rows) == 1
w.save_rules()
cfg = dm.load_cfg()
assert "移民身份文件" in w.cat_btns and w.protect_boxes["移民身份文件"].isChecked()
assert any(r[0] == "移民身份文件" and len(r) == 3 and "passport" in r[2] for r in cfg["rules"])
assert "移民身份文件" in cfg["protect"]

# 重新整理已有文件：规则生效后，“图片”里的护照照片挪到“移民身份文件”
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
    if tree is not None and hasattr(tree, "topLevelItemCount"):   # 取消勾选 ._a.jpg 所在的组
        for i in range(tree.topLevelItemCount()):
            g = tree.topLevelItem(i)
            if "macOS" in g.text(0):
                g.setCheckState(0, dm.Qt.CheckState.Unchecked)
dm.Dialog.__init__ = init_and_uncheck
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

# 分析文件夹：空文件夹默认勾选并删除；“建议保留”的不动；列表里文件夹显示为一行
os.makedirs(os.path.join(dm.ROOT, "其他文件", "2024-01", "空文件夹"))
keep_dir = os.path.join(dm.ROOT, "其他文件", "2024-01", "相册")
os.makedirs(keep_dir); open(os.path.join(keep_dir, "a.jpg"), "wb").write(b"j")
w.tick(); app.processEvents()
assert any(x.get("is_dir") and x["path"] == keep_dir for x in w.items)
gone.clear()
dm.recycle = lambda paths: [gone.append(os.path.basename(p)) or (os.rmdir(p) if os.path.isdir(p) else os.remove(p))
                            for p in paths]
w.analyze_folders()
deadline = _t.time() + 20
while w._tasks and _t.time() < deadline:
    app.processEvents(); _t.sleep(0.02)
assert not w._tasks, "folder analysis did not finish"
assert gone == ["空文件夹"], gone
assert os.path.isdir(keep_dir)

# 在应用内打开文件夹：双击进入、子文件夹再进入、返回逐级回到分类
os.makedirs(os.path.join(keep_dir, "子相册")); open(os.path.join(keep_dir, "子相册", "b.jpg"), "wb").write(b"b")
w.select_cat("其他文件"); w.tick(); app.processEvents()
def row_of(path):
    for i in range(w.tree.topLevelItemCount()):
        top = w.tree.topLevelItem(i)
        for it in [top] + [top.child(j) for j in range(top.childCount())]:
            if it.data(0, dm.Qt.ItemDataRole.UserRole) == path:
                return it
row = row_of(keep_dir)
assert row is not None
w.tree.clearSelection(); row.setSelected(True)
opened = []
orig_open_path = w.open_path
w.open_path = lambda p: opened.append(p)
w.open_selected()
assert w.browse == keep_dir and not opened, (w.browse, opened)
assert {x["name"] for x in w.visible_items()} == {"a.jpg", "子相册"}
assert w.visible_items()[0]["name"] == "子相册"          # 子文件夹排在前面
assert w.page_title.text() == "相册" and w.b_back.isVisible()
w.tree.clearSelection(); row_of(os.path.join(keep_dir, "a.jpg")).setSelected(True)
w.open_selected()
assert opened == [os.path.join(keep_dir, "a.jpg")]       # 文件照常用默认程序打开
w.open_path = orig_open_path
w.enter_folder(os.path.join(keep_dir, "子相册"))
assert [x["name"] for x in w.visible_items()] == ["b.jpg"]
open(os.path.join(keep_dir, "子相册", "c.jpg"), "wb").write(b"c")
w.tick(organize_first=False)
assert {x["name"] for x in w.visible_items()} == {"b.jpg", "c.jpg"}   # 文件夹里有变化时刷新
w.browse_back()
assert w.browse == keep_dir
w.browse_back()
assert w.browse is None and w.page_title.text() == "其他文件" and not w.b_back.isVisible()
w.enter_folder(keep_dir)
w.select_cat("全部文件")                                  # 点左侧分类：退出文件夹
assert w.browse is None

# 最近添加：按到达时间，超过 30 天的不显示；时间列显示“添加时间”
old_f = os.path.join(dm.ROOT, "图片", "2020-01", "旧照片.jpg")
os.makedirs(os.path.dirname(old_f), exist_ok=True); open(old_f, "wb").write(b"o")
w.tick(organize_first=False)
for x in w.items:
    if x["path"] == old_f:
        x["arrived"] = x["mtime"] = _t.time() - 90 * 86400
w.select_cat(dm.RECENT)
names = [x["name"] for x in w.visible_items()]
assert "旧照片.jpg" not in names and "相册" in names, names
assert "添加时间" in w.tree.headerItem().text(3)
w.refresh_counts()
assert w.cat_btns[dm.RECENT].count == len(names)
assert w.btn_recent.isChecked()
assert not hasattr(w, "recent_box") and not w.act_bar.isVisible()        # 顶部下拉框、底部按钮行都已去掉
# 时间范围可以设置：改成 1 年后 90 天前的文件也出现，计数同步；三个入口保持一致
w.set_recent_days(365)
assert "旧照片.jpg" in [x["name"] for x in w.visible_items()]
assert dm.load_cfg()["recent_days"] == 365 and w.btn_recent.days == 365
assert w.s_recent.currentData() == 365
assert w.cat_btns[dm.RECENT].count == len(names) + 1
w.s_recent.setCurrentIndex(dm.RECENT_OPTIONS.index(7))
assert dm.load_cfg()["recent_days"] == 7 and w.btn_recent.days == 7
w.set_recent_days(30)
assert dm.sanitize_cfg(dict(recent_days=40))["recent_days"] == 30
# 独立按钮：不在分类区里，分类重建后仍然存在
assert w.cat_box.indexOf(w.btn_recent) == -1
w.build_cat_buttons()
assert w.cat_btns[dm.RECENT] is w.btn_recent
w.select_cat("全部文件")
assert not w.btn_recent.isChecked()
# 左侧菜单三种模式：常驻展开 / 自动 / 常驻折叠（标题栏图标），保存到设置
w.set_side_mode("closed")
for _ in range(30):
    app.processEvents(); _t.sleep(0.01)
assert w.side.width() == dm.SIDE_CLOSED_W and not w.side_open and w.title.mode_btns["closed"].isChecked()
assert dm.load_cfg()["side_mode"] == "closed"
w.title.mode_btns["open"].click()
for _ in range(30):
    app.processEvents(); _t.sleep(0.01)
assert w.side.width() == dm.SIDE_OPEN_W and w.side_open and dm.load_cfg()["side_mode"] == "open"
w.set_side_mode("auto")
w.set_side(False)
assert dm.load_cfg()["side_mode"] == "auto"
w.set_side(True)                                    # 模拟鼠标靠近后展开；离开后（检查时鼠标不在菜单上）自动收起
w.side_near = lambda gp: False
w.side_auto_check()
for _ in range(30):
    app.processEvents(); _t.sleep(0.01)
assert not w.side_open and w.side.width() == dm.SIDE_CLOSED_W
del w.side_near
w.set_side_mode("open")
assert dm.sanitize_cfg(dict(side_open=False))["side_mode"] == "closed"
assert dm.sanitize_cfg(dict(side_mode="bad"))["side_mode"] == "open"
# 搜索框在“立即整理”“打开文件夹”左边
assert w.search_box.x() < w.b_organize.x() < w.btn_root.x()
# 帮助按钮在标题栏
w.title.btn_help.click()
assert w.pages.currentIndex() == 3 or w.btn_help.isChecked()
assert w.btn_help is w.title.btn_help and w.btn_help not in w.side_btns
w.select_cat("全部文件")
assert not w.btn_help.isChecked()
assert "添加时间" not in w.tree.headerItem().text(3)

# 管理的文件夹：拒绝系统目录；换成新文件夹后立即生效（不重启）
dm.QFileDialog.getExistingDirectory = staticmethod(lambda *a, **k: os.environ["WINDIR"])
w.choose_root(False)
assert dm.load_cfg()["root"] == ""
newroot = tempfile.mkdtemp(prefix="dmnewroot_")
dm.QFileDialog.getExistingDirectory = staticmethod(lambda *a, **k: newroot)
w.choose_root(False)
assert dm.load_cfg()["root"] == os.path.abspath(newroot) and dm.ROOT == os.path.abspath(newroot)
assert all(dm._norm(d).startswith(dm._norm(newroot)) for d in w.watcher.directories()), "old folder still watched"
assert w.btn_root.toolTip().endswith(os.path.abspath(newroot))
# 左侧菜单：两个清理入口合并成一个“清理”，立即整理 / 打开文件夹移到列表上方
side = [b.text_ for b in w.side_btns]
assert "清理" in side and not {"立即清理", "清理垃圾文件", "立即整理"} & set(side), side

# 压缩 / 解压：带密码压缩 → 解压时弹出密码框 → 输入密码后成功并保存到密码本
def wait_job():
    deadline = _t.time() + 30
    while w.job is not None and _t.time() < deadline:
        app.processEvents(); _t.sleep(0.02)
    assert w.job is None, "archive job did not finish"
    app.processEvents()
os.makedirs(os.path.join(newroot, "重要文件"))
src = os.path.join(newroot, "重要文件", "报告.txt"); open(src, "w", encoding="utf-8").write("内容" * 100)
here = os.path.dirname(src)
w.cfg["unzip_open"] = False
assert w.start_compress([src], os.path.join(here, "报告.zip"), "zip", 5, password="s3cret!")
assert not w.start_compress([src], os.path.join(here, "b.zip"), "zip", 5)   # 同一时间只进行一个任务
wait_job()
zpath = os.path.join(here, "报告.zip")
assert os.path.isfile(zpath) and not os.path.exists(os.path.join(here, "b.zip"))
asked = []
w.ask_password = lambda p, msg: (asked.append(msg) or ("s3cret!", True))
w.extract_paths([zpath], mode="folder")
wait_job()
assert asked and os.path.isfile(os.path.join(here, "报告", "报告.txt")), os.listdir(here)
assert w.pw_book() == ["s3cret!"] and "s3cret" not in open(dm.CFG_PATH, encoding="utf-8").read()
asked.clear()
w.session_pws.clear()
w.extract_paths([zpath], mode="folder")             # 第二次：密码本里有，不再询问
wait_job()
assert not asked and os.path.isdir(os.path.join(here, "报告 (1)"))
assert not [n for n in os.listdir(here) if n.startswith(dm.TEMP_PREFIX)]
# 右键菜单里有压缩 / 解压
w.select_cat("全部文件")
for i in range(w.tree.topLevelItemCount()):
    g = w.tree.topLevelItem(i)
    for j in range(g.childCount()):
        if g.child(j).data(0, dm.Qt.ItemDataRole.UserRole) == zpath:
            g.child(j).setSelected(True)
m = QMenu(); w.add_archive_actions(m)
texts = [a.text() for a in m.actions()]
assert any(t.startswith("解压到“报告") for t in texts) and any(t.startswith("压缩…") for t in texts), texts
# 快速打印：不真的打印；不支持打印的类型显示为灰色
pm = QMenu(); w.add_print_actions(pm)                   # 选中的是 zip：不能直接打印
assert pm.actions()[0].text().startswith("快速打印（这种文件不能直接打印") and not pm.actions()[0].isEnabled()
printed = []
dm.shell_verb_ok = lambda p, verb: p.endswith(".txt")
dm.shell_print = lambda p, printer=None: printed.append((os.path.basename(p), printer)) or True
w.print_paths([src])
assert printed == [("报告.txt", None)]
w.print_paths([src, src], "Microsoft Print to PDF")      # 多个文件：先确认（测试里自动确认）
assert printed[-1] == ("报告.txt", "Microsoft Print to PDF") and len(printed) == 3
printed.clear()
for i in range(w.tree.topLevelItemCount()):
    g = w.tree.topLevelItem(i)
    for j in range(g.childCount()):
        g.child(j).setSelected(g.child(j).data(0, dm.Qt.ItemDataRole.UserRole) == src)
m = QMenu(); w.add_print_actions(m)
assert m.actions()[0].text().startswith("快速打印") and m.actions()[0].isEnabled()
w.print_selected()
assert printed == [("报告.txt", None)]

# 其他文件夹：拒绝项目文件夹；添加后出现在“管理的文件夹”分栏；“整理现有文件”预览确认后移动
assert "管理的文件夹" in [b.text() for b in w.settings_tabs] and "移动记录" in [b.text() for b in w.settings_tabs]
projd = tempfile.mkdtemp(prefix="dmproj_"); open(os.path.join(projd, "package.json"), "w").close()
dm.QFileDialog.getExistingDirectory = staticmethod(lambda *a, **k: projd)
w.add_folder()
assert dm.load_cfg()["folders"] == []
extra = tempfile.mkdtemp(prefix="dmextra_")
for n in ("旧照片.jpg", "快捷方式.lnk"):
    open(os.path.join(extra, n), "w").close()
dm.QFileDialog.getExistingDirectory = staticmethod(lambda *a, **k: extra)
w.add_folder()
assert [f["path"] for f in dm.load_cfg()["folders"]] == [os.path.abspath(extra)] and dm.roots()[-1] == os.path.abspath(extra)
assert os.path.isfile(os.path.join(extra, "旧照片.jpg")), "existing files must not move automatically"
assert w.settings_tabs[w.settings_stack.currentIndex()].text() in ("管理的文件夹", "常规", "分类规则")
w.show_settings_tab("管理的文件夹")
w.organize_existing(extra)
moved_to = os.path.join(extra, dm.EXTRA_SUB, "图片")
assert any("旧照片.jpg" in fs for _, _, fs in os.walk(moved_to)), os.listdir(extra)
assert os.path.isfile(os.path.join(extra, "快捷方式.lnk"))
assert any(x["root"] == os.path.abspath(extra) for x in w.items), "extra folder files not listed"
w.set_folder_opt(extra, "clean", True)
assert dm.load_cfg()["folders"][0]["clean"] and dm.EXTRA[0]["clean"]
# 移动记录：最新一条是“整理现有文件”，撤销后文件回到原处，且不会马上又被整理
w.show_settings_tab("移动记录")
top = w.journal_tree.topLevelItem(0)
assert top.text(1).startswith("整理现有文件") and top.text(2) == "1 个", [top.text(i) for i in range(4)]
w.journal_tree.setCurrentItem(top.child(0))
w.undo_selected(False)
assert os.path.isfile(os.path.join(extra, "旧照片.jpg")) and not os.path.exists(os.path.join(extra, dm.EXTRA_SUB))
assert w.journal_tree.topLevelItem(0).text(3) == "已撤销"
w.do_organize(manual=True)
assert os.path.isfile(os.path.join(extra, "旧照片.jpg"))
# 主页按文件夹查看：下拉框出现，选中其他文件夹后只显示那里的文件（最外层的显示为“未整理”）
assert w.loc_box.count() == 3 and w.btn_loc.text_ == "全部文件夹"
# 左侧最上面的文件夹选择：菜单里列出全部文件夹、主文件夹、其他文件夹，点一下就切换
from PyQt6.QtWidgets import QMenu as _QMenu
picked = []
orig_exec = _QMenu.exec
def pick_extra(menu, *a):
    acts = [x for x in menu.actions() if x.text()]
    picked.extend(x.text() for x in acts)
    next(x for x in acts if x.text() == os.path.basename(extra)).trigger()
_QMenu.exec = pick_extra
w.loc_menu()
_QMenu.exec = orig_exec
assert picked[0] == "全部文件夹" and "添加 / 管理文件夹…" in picked, picked
assert w.loc == os.path.abspath(extra) and w.btn_loc.text_ == os.path.basename(extra)
names = [x["name"] for x in w.visible_items()]
assert "旧照片.jpg" in names and "快捷方式.lnk" in names and "报告.txt" not in names, names
w.loc_box.setCurrentIndex(0)
assert w.btn_loc.text_ == "全部文件夹"
assert "报告.txt" in [x["name"] for x in w.visible_items()]
# 独立的分类规则：为这个文件夹新建方案 → 改名 → 导出 → 导入为新方案 → 删除
w.new_scheme_for(extra)
cfg = dm.load_cfg()
sname = cfg["folders"][0]["scheme"]
assert sname and [s["name"] for s in cfg["schemes"]] == [sname] and w.rule_scheme == sname
assert w.settings_tabs[w.settings_stack.currentIndex()].text() == "分类规则" and w.scheme_box.currentData() == sname
w.rule_rows[0]["name"].setText("桌面文档")
w.save_rules()
assert dm.cats_for(os.path.abspath(extra))[0] == "桌面文档" and dm.CATS[0] == "重要文件"
assert dm.load_cfg()["rules"] == [] or dm.load_cfg()["rules"][0][0] != "桌面文档"
orig_value = dm.Dialog.value
dm.Dialog.value = lambda self: "我的桌面规则"
w.rename_scheme()
dm.Dialog.value = orig_value
cfg = dm.load_cfg()
assert cfg["schemes"][0]["name"] == "我的桌面规则" and cfg["folders"][0]["scheme"] == "我的桌面规则"
exp = os.path.join(tempfile.mkdtemp(prefix="dmexp_"), "规则.json")
dm.QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (exp, ""))
w.export_rules()
import json as _json
data = _json.load(open(exp, encoding="utf-8"))
assert data["name"] == "我的桌面规则" and data["rules"][0][0] == "桌面文档"
dm.QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: (exp, ""))
w.import_rules()                                   # 同名：自动起一个不重复的名字
cfg = dm.load_cfg()
assert len(cfg["schemes"]) == 2 and cfg["schemes"][1]["name"] != cfg["schemes"][0]["name"]
w.switch_scheme(cfg["schemes"][1]["name"])
w.delete_scheme()
assert len(dm.load_cfg()["schemes"]) == 1
w.switch_scheme("")
assert w.scheme_box.currentData() == "" and w.rule_rows[0]["name"].text() == dm.CATS[0]
# 文件夹改回主文件夹规则
w.set_folder_scheme(extra, "")
assert dm.load_cfg()["folders"][0]["scheme"] == "" and dm.cats_for(os.path.abspath(extra)) == dm.CATS
# 左侧“清理”：单击直接清理垃圾文件
called = []
orig_cj = w.clean_junk
w.clean_junk = lambda: called.append(1)
w.btn_clean.click()
w.clean_junk = orig_cj
assert called == [1]
w.remove_folder(extra)
assert dm.load_cfg()["folders"] == [] and dm.EXTRA == [] and w.loc_box.isHidden()

# 整理 + 后台清理
w.do_organize(manual=True)
ok = w.start_cleanup(manual=True)
assert ok and not w.start_cleanup(manual=True)     # 第二次不重复启动
def finish():
    assert w._clean_worker is None, "cleanup did not finish"
    print("SMOKE OK"); w.thumbs.stop(); app.quit()
QTimer.singleShot(3000, finish)
app.exec()
