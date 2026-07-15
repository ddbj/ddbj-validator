"""MetaboBank validator のレポート出力（骨格は common/magetab/reporter に集約）。

MB 固有の差分のみここで定義する:
- 行単位判定: assay を持つ行が SDRF 行単位。
- detail の行単位形式: `{rule_id}:{tag}:SDRF:line {n}:{assay}:{message}`（target 無し）。
- summary の SDRF 行集約: samd を持つ行は SAMD を除いたメッセージで集約し、SAMD の違いを "first etc" に吸収。
"""
from collections import OrderedDict

from common import reporter as _r
from common.magetab import reporter as _mr

_TITLE = "MetaboBank"

# 後方互換（既存 import 用）
_counts = _r.counts
write_text_reports = _r.write_text_reports


def _is_row_level(r):
    """SDRF 行単位のメッセージ（assay を持つ）か。"""
    return "assay" in r


def _row_fmt(r):
    """MB の行単位 detail 行（SDRF:line prefix・target 無し）。
    行番号:assay name（assay name だけだとユニークでない場合があるため行番号を併記）。"""
    return (f"{r['rule_id']}:{_mr.tag(r)}:SDRF:line {r.get('line', '-')}:"
            f"{r.get('assay') or '-'}:{r.get('message','')}")


def _row_summary(results, is_err):
    """MB の SDRF 行単位 summary 集約。
    samd を持つ行（SR0021/SR0023 等）は SAMD を除いたメッセージで集約し、SAMD の違いを "first etc" に吸収
    （sdrf 行数 x samd 数 x 属性数 で膨らむのを 1 行にまとめる）。samd 無しは message で集約（従来）。"""
    groups = OrderedDict()
    for r in results:
        if not (_is_row_level(r) and (r.get("level") == "error") == is_err):
            continue
        rid, tag, msg = r["rule_id"], _mr.tag(r), r.get("message", "")
        samd = r.get("samd")
        key = (rid, tag, msg.replace(samd, "<samd>") if samd else msg)
        g = groups.get(key)
        if g is None:
            g = {"rid": rid, "tag": tag, "msg": msg, "samd": samd, "n": 0}
            groups[key] = g
        g["n"] += 1
    out = []
    for g in groups.values():
        msg = g["msg"]
        if g["samd"] and g["n"] > 1:   # SAMD を「first etc」に（複数 SAMD をまとめた印）
            msg = msg.replace(g["samd"], f"{g['samd']} etc", 1)
        out.append(f"{g['rid']}:{g['tag']}:SDRF:{g['n']} lines:{msg}")
    return out


def build_summary(results, fname, version, when, elapsed, sample_count=None, sub_type=None):
    return _mr.build_summary(results, fname, version, when, elapsed, app_title=_TITLE, data=_TITLE,
                             is_row_level=_is_row_level, row_summary=_row_summary,
                             sample_count=sample_count, sub_type=sub_type)


def build_details(results, fname, version, when, elapsed, sample_count=None, sub_type=None):
    return _mr.build_details(results, fname, version, when, elapsed, app_title=_TITLE, data=_TITLE,
                             is_row_level=_is_row_level, row_fmt=_row_fmt,
                             sample_count=sample_count, sub_type=sub_type)


def write_json_report(results, out_dir, fname, version):
    return _r.write_json_report(results, out_dir, fname, version, stats_key="input", include_object=False)
