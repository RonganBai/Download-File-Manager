# -*- coding: utf-8 -*-
"""可配置分类规则 / 管理的文件夹 / 年-月子文件夹 的测试。用法：python tests/test_rules_and_root.py"""
import importlib.util, os, sys, tempfile, time

repo = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("dm", os.path.join(repo, "download_manager.py"))
dm = importlib.util.module_from_spec(spec); spec.loader.exec_module(dm)

fails = 0
def check(name, cond):
    global fails
    print(("PASS " if cond else "FAIL ") + name); fails += not cond

# --- parse / validate ---
check("parse_exts normalizes", dm.parse_exts("PDF, .docx；txt  pdf") == [".pdf", ".docx", ".txt"])
norm, err = dm.validate_rules([("Docs", "pdf docx"), ("Pics", ".PNG,jpg")])
check("validate ok", err == "" and norm == [["Docs", ".pdf .docx"], ["Pics", ".png .jpg"]])
for rows, why in (([("", "pdf")], "empty name"), ([("a/b", "pdf")], "bad char"), ([("其他文件", "pdf")], "reserved"),
                  ([("A", "pdf"), ("a", "txt")], "duplicate"), ([("A", "  ")], "no exts"), ([], "no rules"),
                  ([("CON", "pdf")], "device name"), ([["A"]], "malformed")):
    check(f"validate rejects {why}", dm.validate_rules(rows)[0] is None)

# --- apply_rules ---
dm.apply_rules([["Docs", ".pdf .txt"], ["Media", ".mp4 .pdf"]])
check("custom cats", dm.CATS == ["Docs", "Media", "其他文件"])
check("ext map first wins", dm.category_of(".pdf") == "Docs" and dm.category_of(".mp4") == "Media")
check("unknown -> other", dm.category_of(".xyz") == "其他文件")
check("glyphs present", all(c in dm.GLYPH for c in dm.CATS + ["未整理", "全部文件"]))
check("invalid rules fall back", dm.apply_rules([["", ""]]) and dm.CATS[0] == "重要文件")
dm.apply_rules([])
check("default restored", dm.CATS == [r[0] for r in dm.DEFAULT_RULES] + ["其他文件"] and dm.category_of(".pdf") == "重要文件")

# --- sanitize ---
c = dm.sanitize_cfg(dict(rules=[["Docs", "pdf"]], protect=["Docs", "重要文件", "其他文件"], by_month="no"))
check("sanitize keeps valid rules & matching protect",
      c["rules"] == [["Docs", ".pdf"]] and c["protect"] == ["Docs", "其他文件"] and c["by_month"] is True)
check("sanitize drops bad rules", dm.sanitize_cfg(dict(rules=[["a/b", "x"]]))["rules"] == [])
check("sanitize drops unusable root", dm.sanitize_cfg(dict(root="Z:\\definitely\\missing"))["root"] == "")

# --- root_problem ---
ok_dir = tempfile.mkdtemp(prefix="dmroot_")
# 系统临时目录在 %LOCALAPPDATA% 里，按规则应被拒绝；之后临时隐藏该变量，用临时目录模拟普通文件夹
check("folder inside LOCALAPPDATA rejected", dm.root_problem(ok_dir) != "")
saved_lad = os.environ.pop("LOCALAPPDATA", None)
check("normal folder ok", dm.root_problem(ok_dir) == "")
check("drive root rejected", dm.root_problem("C:\\"))
check("windows dir rejected", dm.root_problem(os.environ["WINDIR"]))
check("system32 rejected", dm.root_problem(os.path.join(os.environ["WINDIR"], "System32")))
check("program files rejected", dm.root_problem(os.environ["ProgramFiles"]))
check("home itself rejected", dm.root_problem(os.environ["USERPROFILE"]))
check("missing rejected", dm.root_problem(os.path.join(ok_dir, "nope")))
check("resolve_root uses custom", dm.resolve_root(dict(root=ok_dir)) == os.path.abspath(ok_dir))
check("resolve_root falls back", dm.resolve_root(dict(root="")) == dm.downloads_dir())

# --- init_settings + organize with custom rules, no month folders ---
root = tempfile.mkdtemp(prefix="dmorg2_")
dm.init_settings(dict(dm.DEFAULTS, rules=[["Docs", ".pdf"]], root=root, by_month=False))
check("init sets root", dm.ROOT == os.path.abspath(root))
for n in ("a.pdf", "b.bin"):
    p = os.path.join(root, n); open(p, "w").close()
moved, _ = dm.organize(settle=0)
check("organized into custom cats without month dirs",
      os.path.isfile(os.path.join(root, "Docs", "a.pdf")) and os.path.isfile(os.path.join(root, "其他文件", "b.bin")))
items, _ = dm.scan()
check("scan sees custom cats", sorted(x["cat"] for x in items) == ["Docs", "其他文件"])
dm.BY_MONTH = True
p = os.path.join(root, "c.pdf"); open(p, "w").close()
dm.organize(settle=0)
check("month dirs when enabled", os.path.isfile(os.path.join(root, "Docs", time.strftime("%Y-%m"), "c.pdf")))
dm.init_settings(dict(dm.DEFAULTS))
if saved_lad is not None:
    os.environ["LOCALAPPDATA"] = saved_lad

print("FAILURES:", fails); sys.exit(fails)
