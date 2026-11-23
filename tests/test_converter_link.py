# -*- coding: utf-8 -*-
"""与「格式转换器」的可选联动：没装时不显示菜单；装了时按文件类型给出常用格式。全部在临时目录中进行。"""
import json, os, sys, tempfile

repo = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
tmp = tempfile.mkdtemp()
os.environ["APPDATA"] = tmp
sys.path.insert(0, repo)
from PyQt6.QtWidgets import QApplication, QMenu   # noqa: E402
import converter_link as cl                          # noqa: E402

app = QApplication([])
info_path = os.path.join(tmp, "格式转换器", "integration.json")
assert cl.INFO_PATH == info_path
files = {}
for name in ("a.jpg", "b.heic", "c.mp4", "d.zip", "e.pdf"):
    files[name] = os.path.join(tmp, name)
    open(files[name], "wb").write(b"x")


def menu_for(*names):
    m = QMenu()
    toasts = []
    ok = cl.add_menu(m, [files[n] for n in names], toasts.append)
    sub = next((a.menu() for a in m.actions() if a.menu()), None)
    return ok, [a.text() for a in sub.actions() if a.text()] if sub else []


# 1. 没装格式转换器：不显示
assert menu_for("a.jpg") == (False, [])

# 2. 装了：写一份 integration.json，command 指向一个真实存在的 exe
os.makedirs(os.path.dirname(info_path))
info = {"protocol": 1, "command": [sys.executable],
        "quick": [{"to": "image:PNG", "label": "PNG", "fmt": "PNG", "kind": "image"},
                  {"to": "doc:PDF", "label": "PDF", "fmt": "PDF", "kind": "doc"},
                  {"to": "image:GIF", "label": "GIF", "fmt": "GIF", "kind": "image"},
                  {"to": "video:MP4", "label": "MP4", "fmt": "MP4", "kind": "video"}],
        "inputs": {"image": ["jpg", "heic"], "doc": ["pdf"], "video": ["mp4"]}}
json.dump(info, open(info_path, "w", encoding="utf-8"))
ok, items = menu_for("a.jpg", "b.heic")
assert ok and items[:3] == ["PNG", "PDF", "GIF"] and "MP4" not in items, items
assert items[-1].startswith("更多格式")
ok, items = menu_for("c.mp4")
assert ok and items[:2] == ["GIF", "MP4"], items           # 视频：只给视频格式和动图
assert menu_for("d.zip") == (False, [])                    # 不能处理的文件：不显示
assert menu_for("a.jpg", "d.zip") == (False, [])

# 3. 卸载后（程序文件不存在）：不显示
info["command"] = [os.path.join(tmp, "gone", "FormatConverter.exe")]
json.dump(info, open(info_path, "w", encoding="utf-8"))
os.utime(info_path, (1, 1))
assert menu_for("a.jpg") == (False, [])

# 4. 文件损坏 / 版本不对：不显示
open(info_path, "w").write("{broken")
os.utime(info_path, (2, 2))
assert menu_for("a.jpg") == (False, [])
print("converter_link OK")
