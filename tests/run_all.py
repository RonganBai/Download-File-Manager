# -*- coding: utf-8 -*-
"""运行全部测试：python tests/run_all.py
每个测试脚本都在临时目录里操作，不会动真实的下载文件夹、配置或回收站。"""
import os, subprocess, sys

here = os.path.dirname(os.path.abspath(__file__))
repo = os.path.dirname(here)
tests = ["test_cleanup.py", "test_organize_and_system.py", "test_rules_and_root.py", "test_keywords_junk.py", "test_converter_link.py", "smoke_gui.py"]
env = dict(os.environ, PYTHONIOENCODING="utf-8")
failed = []
for t in tests:
    print(f"===== {t}", flush=True)
    r = subprocess.run([sys.executable, "-I", os.path.join(here, t), repo], env=env)
    if r.returncode:
        failed.append(t)
print("\n全部通过" if not failed else f"\n失败：{', '.join(failed)}")
sys.exit(1 if failed else 0)
