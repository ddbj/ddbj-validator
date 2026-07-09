#!/usr/bin/env python3
"""現行 biosample v の出力（-t compare.txt … -j）と本番 result.json を sample × rule で突合する。

再利用可能な突合ユーティリティ（回帰スイート run_regression.py から利用）。
本番 json / 現行 v json の message は annotation の "Sample name" ＋ id(rule) で突き合わせる。
"""
import json
from collections import defaultdict


def _sample_name(msg):
    for a in msg.get("annotation") or []:
        if isinstance(a, dict) and a.get("key") == "Sample name":
            return str(a.get("value"))
    return None


def load_by_sample(path):
    """result.json を {sample_name: set(rule_id)} と「sample 無しの rule 集合」に分解して返す。"""
    data = json.load(open(path, encoding="utf-8"))
    by_sample = defaultdict(set)
    no_sample = set()
    for m in data.get("messages", []):
        s = _sample_name(m)
        (by_sample[s].add(m["id"]) if s else no_sample.add(m["id"]))
    return by_sample, no_sample, data


def diff(cur_json, prod_json):
    """現行 v json と本番 json を突合。戻り値: {matched, cur_only, prod_only, diffs, no_sample}。
    diffs: [(sample, sorted(cur_only), sorted(prod_only)), ...]（差分のある sample のみ）。"""
    cur, cur_ns, dc = load_by_sample(cur_json)
    prod, prod_ns, dp = load_by_sample(prod_json)
    samples = sorted(set(cur) | set(prod), key=lambda x: (len(x), x))
    matched = cur_only = prod_only = 0
    diffs = []
    for s in samples:
        c, p = cur.get(s, set()), prod.get(s, set())
        a, b = sorted(c - p), sorted(p - c)
        matched += len(c & p)
        cur_only += len(a)
        prod_only += len(b)
        if a or b:
            diffs.append((s, a, b))
    return {
        "matched": matched, "cur_only": cur_only, "prod_only": prod_only,
        "diffs": diffs,
        "cur_no_sample": sorted(cur_ns), "prod_no_sample": sorted(prod_ns),
        "cur_validity": dc.get("validity"), "prod_validity": dp.get("validity"),
        "cur_messages": len(dc.get("messages", [])), "prod_messages": len(dp.get("messages", [])),
    }
