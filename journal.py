# -*- coding: utf-8 -*-
"""移动记录与一键撤销。

下载管家每次移动文件 / 文件夹（自动整理、手动“移动到”、按规则重新整理、重命名后换分类）都记一笔
“原位置 → 新位置”，同一次操作的多条记录属于同一批。撤销时按相反顺序移回原位置；
原位置已被占用时自动改名，绝不覆盖。撤销回来的文件记入“不要自动整理”名单，避免马上又被整理走。

记录保存在配置目录下的 moves.jsonl（每行一个 JSON），只追加写入；超过上限时保留最近的记录。"""
import json
import os
import shutil
import threading
import time
import uuid

MAX_LINES = 20000            # 文件超过这么多行时压缩，只保留最近的
KEEP_DAYS = 180

_lock = threading.Lock()
_path = None
_back = set()                # 撤销时移回原位的路径（normcase）


def init(cfg_dir):
    global _path
    os.makedirs(cfg_dir, exist_ok=True)
    _path = os.path.join(cfg_dir, "moves.jsonl")
    _compact()
    _back.clear()
    for r in _read():
        _back.update(os.path.normcase(p) for p in r.get("back", ()))


def _append(rec):
    if not _path:
        return
    with _lock, open(_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _read():
    if not _path or not os.path.isfile(_path):
        return []
    out = []
    with _lock, open(_path, encoding="utf-8", errors="replace") as f:
        for line in f:
            try:
                out.append(json.loads(line))
            except ValueError:
                pass                       # 写到一半断电留下的残行：忽略
    return out


def _compact():
    recs = _read()
    if len(recs) <= MAX_LINES:
        return
    cutoff = time.time() - KEEP_DAYS * 86400
    recs = [r for r in recs if r.get("t", 0) >= cutoff][-MAX_LINES // 2:]
    tmp = _path + ".tmp"
    with _lock:
        with open(tmp, "w", encoding="utf-8") as f:
            for r in recs:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        os.replace(tmp, _path)


class Batch:
    """一次操作。第一次 add 时才真正写入，没有移动任何文件的操作不会留下空记录。"""
    def __init__(self, label):
        self.id = time.strftime("%Y%m%d%H%M%S") + "-" + uuid.uuid4().hex[:6]
        self.label = label
        self.count = 0

    def add(self, src, dst):
        _append({"b": self.id, "t": time.time(), "k": self.label, "s": os.path.abspath(src), "d": os.path.abspath(dst)})
        self.count += 1


def batch(label):
    return Batch(label)


def batches(limit=300):
    """最近的操作（新的在前）：[{id, t, label, moves:[(原, 新)], undone, undo_t}]"""
    by, order, undone = {}, [], {}
    for r in _read():
        if "undo" in r:
            undone[r["undo"]] = r.get("t", 0)
            continue
        b = r.get("b")
        if not b or "s" not in r or "d" not in r:
            continue
        if b not in by:
            by[b] = dict(id=b, t=r.get("t", 0), label=r.get("k", "移动"), moves=[])
            order.append(b)
        by[b]["moves"].append((r["s"], r["d"]))
    out = []
    for b in reversed(order[-limit:]):
        x = by[b]
        x["undone"] = b in undone
        x["undo_t"] = undone.get(b)
        out.append(x)
    return out


def _free(path):
    if not os.path.lexists(path):
        return path
    d, name = os.path.split(path)
    base, ext = os.path.splitext(name)
    i = 1
    while True:
        p = os.path.join(d, f"{base} (原位置已有同名) {i}{ext}" if i > 1 else f"{base} (原位置已有同名){ext}")
        if not os.path.lexists(p):
            return p
        i += 1


def undo(batch_id):
    """撤销一批移动。返回 (移回的数量, [问题说明])。"""
    b = next((x for x in batches(10 ** 9) if x["id"] == batch_id), None)
    if b is None:
        return 0, ["找不到这条记录"]
    if b["undone"]:
        return 0, ["这次操作已经撤销过了"]
    ok, problems, restored = 0, [], []
    for src, dst in reversed(b["moves"]):
        name = os.path.basename(src)
        if not os.path.lexists(dst):
            problems.append(f"{name}：已不在整理后的位置（可能已被删除或再次移动），跳过")
            continue
        target = _free(src)
        try:
            os.makedirs(os.path.dirname(target), exist_ok=True)
            shutil.move(dst, target)
        except OSError as e:
            problems.append(f"{name}：移回失败（{e.strerror or e}），可能正在被使用")
            continue
        if target != src:
            problems.append(f"{name}：原位置已有同名文件，已改名为“{os.path.basename(target)}”")
        restored.append(target)
        ok += 1
    rec = {"undo": batch_id, "t": time.time(), "back": restored}
    _append(rec)
    _back.update(os.path.normcase(os.path.abspath(p)) for p in restored)
    return ok, problems


def undo_since(batch_id):
    """撤销这一批以及它之后的所有操作（从最新的开始），用于“回到某个时间点之前”。返回 (移回数, 问题, 撤销的批数)。"""
    bs = batches(10 ** 9)
    idx = next((i for i, x in enumerate(bs) if x["id"] == batch_id), None)
    if idx is None:
        return 0, ["找不到这条记录"], 0
    total, problems, n = 0, [], 0
    for x in bs[:idx + 1]:                 # bs 是新的在前
        if x["undone"]:
            continue
        k, p = undo(x["id"])
        total += k
        problems += p
        n += 1
    return total, problems, n


def no_auto():
    """撤销移回的文件（仍在原处的）：自动整理跳过它们，否则刚移回去又会被整理走。"""
    gone = {p for p in _back if not os.path.lexists(p)}
    _back.difference_update(gone)          # 已被删除 / 移走的不用再记
    return set(_back)
