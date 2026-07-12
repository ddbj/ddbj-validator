"""GEA validator のレポート出力（MetaboBank と同様の見せ方）。

- Input を IDF/SDRF ラベル付きで表示（Validity 行は出さない）。
- summary は Error/Warning 件数 ＋ メッセージ一覧。IDF 等は verbatim、SDRF 行単位（line/assay 付き）は
  (rule_id, message) ごとに "N lines" へ集約。
- details は全件。SDRF 行単位は location に line 行番号＋Assay Name を入れる
  （`{rule_id}:line {n}:{assay}:{target}:{message}`）。
共通の counts / write_text_reports / write_json_report は common/reporter を利用。
"""
from collections import OrderedDict

from common import reporter as _r

_TITLE = "GEA"
_DATA = "GEA"

# 後方互換（既存 import 用）
_counts = _r.counts
write_text_reports = _r.write_text_reports


def _input_lines(fname, sample_count):
    """"a.idf.txt b.sdrf.txt" → ["IDF: a.idf.txt", "SDRF: b.sdrf.txt (N samples)"]。"""
    lines = []
    for tok in (fname or "").split():
        if ".idf." in tok:
            lines.append(f"IDF: {tok}")
        elif ".sdrf." in tok:
            suffix = f" ({sample_count} samples)" if sample_count is not None else ""
            lines.append(f"SDRF: {tok}{suffix}")
        else:
            lines.append(f"Input: {tok}")
    return lines


def _header(title, fname, version, when, elapsed, sample_count, sub_type, with_time):
    """gea/mb 共通体裁のヘッダ（Data/Version→空行→IDF/SDRF(+samples)→Submission type→空行）。"""
    lines = [f"=== {_TITLE} Validation {title} ===", f"Validation Date: {when}"]
    if with_time:
        lines.append(f"Process Time: {elapsed}")
    lines += [f"Data: {_DATA}", f"Version: {version}", ""]
    lines += _input_lines(fname, sample_count)
    lines += [f"Submission type: {sub_type or '-'}", ""]
    return lines


def _is_row_level(r):
    """SDRF 行単位のメッセージ（line/assay を持つ）か。"""
    return "line" in r or "assay" in r


def _tag(r):
    """error→ERR / それ以外→WAR。"""
    return "ERR" if r.get("level") == "error" else "WAR"


def _fmt_detail(r):
    """details の 1 行。rule_id の直後に ERR/WAR タグを入れる。"""
    if _is_row_level(r):
        return (f"{r['rule_id']}:{_tag(r)}:line {r.get('line', '-')}:{r.get('assay') or '-'}:"
                f"{r.get('target') or '-'}:{r.get('message','')}")
    return f"{r['rule_id']}:{_tag(r)}:{r.get('target') or '-'}:{r.get('message','')}"


def _agg_msg(msg, n, noun):
    """代表メッセージ末尾の ')' 直前に " etc, N Noun" を挿入（acc 参照エラーの件数集約）。"""
    if n <= 1:
        return msg
    return (msg[:-1] + f" etc, {n} {noun})") if msg.endswith(")") else f"{msg} etc, {n} {noun}"


def _summary_lines(results, is_err):
    """指定レベル（error/それ以外）の summary 行。
    非行単位は verbatim（ただし agg_noun 付き＝acc 参照エラーは件数集約）、SDRF 行単位は N lines 集約。"""
    out = []
    # 非行単位: agg_noun 付きは (rule_id, tag, target, noun) で件数集約、無しは verbatim（初出順）
    order, buckets = [], {}
    for r in results:
        if _is_row_level(r) or (r.get("level") == "error") != is_err:
            continue
        noun = r.get("agg_noun")
        k = ("agg", r["rule_id"], _tag(r), r.get("target") or "-", noun) if noun else ("plain", id(r))
        if k not in buckets:
            buckets[k] = []; order.append(k)
        buckets[k].append(r)
    for k in order:
        rs = buckets[k]
        if k[0] == "plain":
            r = rs[0]
            out.append(f"{r['rule_id']}:{_tag(r)}:{r.get('target') or '-'}:{r.get('message','')}")
        else:
            _, rid, tag, target, noun = k
            out.append(f"{rid}:{tag}:{target}:{_agg_msg(rs[0].get('message',''), len(rs), noun)}")
    # SDRF 行単位は (rule_id, tag, message) ごとに N lines 集約
    groups = OrderedDict()
    for r in results:
        if _is_row_level(r) and (r.get("level") == "error") == is_err:
            key = (r["rule_id"], _tag(r), r.get("message", ""))
            groups[key] = groups.get(key, 0) + 1
    for (rid, tag, msg), n in groups.items():
        out.append(f"{rid}:{tag}:SDRF:{n} lines:{msg}")
    return out


def build_summary(results, fname, version, when, elapsed, sample_count=None, sub_type=None):
    c = _r.counts(results)
    lines = _header("Summary", fname, version, when, elapsed, sample_count, sub_type, with_time=True)
    lines += [f"Error: {c.get('error',0)}   Warning: {c.get('warning',0)}", ""]
    errs, wars = _summary_lines(results, True), _summary_lines(results, False)
    if errs:
        lines.append("[ ERROR ]"); lines += errs; lines.append("")
    if wars:
        lines.append("[ WARNING ]"); lines += wars
    return "\n".join(lines).rstrip("\n") + "\n"


def build_details(results, fname, version, when, elapsed, sample_count=None, sub_type=None):
    lines = _header("Details", fname, version, when, elapsed, sample_count, sub_type, with_time=False)
    errs = [r for r in results if r.get("level") == "error"]
    wars = [r for r in results if r.get("level") != "error"]
    if errs:
        lines.append("[ ERROR ]")
        lines += [_fmt_detail(r) for r in errs]
        lines.append("")
    if wars:
        lines.append("[ WARNING ]")
        lines += [_fmt_detail(r) for r in wars]
    return "\n".join(lines).rstrip("\n") + "\n"


def write_json_report(results, out_dir, fname, version):
    return _r.write_json_report(results, out_dir, fname, version, stats_key="input", include_object=False)
