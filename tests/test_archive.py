# -*- coding: utf-8 -*-
"""压缩 / 解压测试：分别用 7-Zip（装了才测）和内置引擎，全部在临时目录里进行。用法：python tests/test_archive.py"""
import inspect, os, sys, tempfile, threading, uuid
repo = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, repo)
import archive as A

# 名称 / 分卷识别
assert A.archive_stem("资料.tar.gz") == "资料" and A.archive_stem("电影.part1.rar") == "电影"
assert A.archive_stem("备份.7z.001") == "备份" and A.archive_stem("a.zip") == "a"
assert A.is_archive("x.part1.rar") and not A.is_archive("x.part2.rar")
assert A.is_archive("x.7z.001") and not A.is_archive("x.7z.002") and not A.is_archive("a.pdf")
assert A._safe_join("C:\\out", "../evil.txt") is None and A._safe_join("C:\\out", "a/b:c.txt").endswith("b_c.txt")
d0 = tempfile.mkdtemp()
for n in ("v.part1.rar", "v.part2.rar", "other.rar"):
    open(os.path.join(d0, n), "w").close()
assert [os.path.basename(p) for p in A.volumes(os.path.join(d0, "v.part1.rar"))] == ["v.part1.rar", "v.part2.rar"]

# 找 7-Zip 不搜索 PATH / 当前目录（防止冒牌 7z.exe）
assert "which" not in inspect.getsource(A.seven_zip)

# 密码本加密：能解开，且不是明文
t = A.protect("秘密123")
assert A.unprotect(t) == "秘密123" and "秘密" not in t and A.unprotect("not-base64!") is None

# ZIP 密码只能是 ASCII；TAR 不支持密码
assert A.compress_problem("zip", "中文") and A.compress_problem("tar.gz", "pw")


def tree(root):
    return sorted(os.path.relpath(os.path.join(r, f), root).replace("\\", "/") for r, _, fs in os.walk(root) for f in fs)


backends = (["7z"] if A.refresh() else []) + ["builtin"]
for backend in backends:
    if backend == "builtin":
        A._7z = ""
    else:
        A.refresh()
    d = tempfile.mkdtemp(prefix="dmarc_")
    src = os.path.join(d, "资料")
    os.makedirs(os.path.join(src, "子目录"))
    open(os.path.join(src, "说明.txt"), "w", encoding="utf-8").write("你好" * 1000)
    open(os.path.join(src, "子目录", "b.bin"), "wb").write(os.urandom(50000))
    one = os.path.join(d, "单个.txt")
    open(one, "w").write("x")
    want = ["单个.txt", "资料/子目录/b.bin", "资料/说明.txt"]
    for fmt in ("zip", "7z", "tar.gz", "tar.xz"):
        for k, pw in enumerate(("", "pw!x", "密码pw")):
            if A.compress_problem(fmt, pw):
                continue
            prog = []
            out = A.compress([src, one], os.path.join(d, "out" + A.FORMAT_EXT[fmt]), fmt, 5, pw, encrypt_names=True,
                             progress=lambda v, s: prog.append(v))
            assert os.path.isfile(out)
            dest = os.path.join(d, f"x_{fmt}_{k}")
            if pw:
                for bad in ("", "wrong"):
                    try:
                        A.extract(out, dest, password=bad)
                        raise AssertionError(f"{backend} {fmt}: password {bad!r} accepted")
                    except A.PasswordError:
                        pass
            res, used = A.extract(out, dest, "smart", passwords=["nope", pw] if pw else ())
            assert used == pw and tree(res) == want, (backend, fmt, pw, tree(res))
            assert os.path.basename(res) == "out", res       # 多个顶层项 → 新建同名文件夹
            assert not [n for n in os.listdir(dest) if n.startswith(A.TEMP_PREFIX)], "temp folder left behind"
            assert not [n for n in os.listdir(d) if n.startswith(A.TEMP_PREFIX)], "temp archive left behind"
            os.remove(out)
    # 智能模式：只有一个顶层文件夹时直接放出来
    z = A.compress([src], os.path.join(d, "s.zip"), "zip")
    res, _ = A.extract(z, os.path.join(d, "smart"), "smart")
    assert os.path.basename(res) == "资料" and tree(res) == ["子目录/b.bin", "说明.txt"]
    res2, _ = A.extract(z, os.path.join(d, "smart"), "smart")
    assert os.path.basename(res2) == "资料 (1)"
    # 直接解压到当前文件夹：同名文件的三种处理
    z = A.compress([one], os.path.join(d, "one.zip"), "zip")
    for pol, names, content in (("rename", ["单个 (1).txt", "单个.txt"], "old"), ("skip", ["单个.txt"], "old"),
                                ("overwrite", ["单个.txt"], "x")):
        h = os.path.join(d, "here_" + pol)
        os.makedirs(h)
        open(os.path.join(h, "单个.txt"), "w").write("old")
        A.extract(z, h, "here", pol)
        assert sorted(os.listdir(h)) == names and open(os.path.join(h, "单个.txt")).read() == content, (backend, pol)
    # 覆盖时旧文件先交给 discard（应用里是回收站）；交不出去就两份都保留，绝不直接丢掉
    bin_ = os.path.join(d, "bin_" + backend)
    os.makedirs(bin_)
    for ok, names in ((True, ["单个.txt"]), (False, ["单个 (1).txt", "单个.txt"])):
        h = os.path.join(d, f"here_discard_{ok}")
        os.makedirs(h)
        open(os.path.join(h, "单个.txt"), "w").write("old")
        def discard(p, ok=ok):
            if ok:
                os.replace(p, os.path.join(bin_, uuid.uuid4().hex))
            return ok
        A.extract(z, h, "here", "overwrite", discard=discard)
        assert sorted(os.listdir(h)) == names, (backend, ok, os.listdir(h))
        assert open(os.path.join(h, "单个.txt")).read() == ("x" if ok else "old"), (backend, ok)
    assert [open(os.path.join(bin_, n)).read() for n in os.listdir(bin_)] == ["old"], "old file not kept"
    # 取消：不留下半个压缩包
    ev = threading.Event()
    ev.set()
    try:
        A.compress([src], os.path.join(d, "c.zip"), "zip", cancel=ev)
        raise AssertionError("not cancelled")
    except A.Cancelled:
        pass
    assert not os.path.exists(os.path.join(d, "c.zip"))
    assert not [n for n in os.listdir(d) if n.startswith(A.TEMP_PREFIX)]
    # 损坏的压缩包
    bad = os.path.join(d, "bad.zip")
    open(bad, "wb").write(b"not a zip at all")
    try:
        A.extract(bad, os.path.join(d, "bad"))
        raise AssertionError("bad archive accepted")
    except A.PasswordError:
        raise AssertionError("bad archive reported as password problem")
    except A.ArchiveError:
        pass
    print(f"{backend}: OK")
print("ARCHIVE OK")
