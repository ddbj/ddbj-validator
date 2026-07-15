"""MAGE-TAB（GEA / MetaboBank）共通のレポート出力の骨格。

Input を IDF/SDRF ラベルで表示し、summary は件数＋メッセージ一覧、details は全件。
gea/mb で共通の骨格（header / 件数 / 非行単位 summary / build_summary・build_details）をここに置き、
app 固有の差分（SDRF 行単位メッセージの detail 整形・summary 集約・行単位判定）は hook 関数で受け取る。
counts / write_text_reports / write_json_report は common/reporter を利用する。
"""
from common import reporter as _r

counts = _r.counts
write_text_reports = _r.write_text_reports


def input_lines(fname, sample_count):
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


def header(app_title, data, section, fname, version, when, elapsed, sample_count, sub_type, with_time):
    """gea/mb 共通体裁のヘッダ（Data/Version→空行→IDF/SDRF(+samples)→Submission type→空行）。"""
    lines = [f"=== {app_title} Validation {section} ===", f"Validation Date: {when}"]
    if with_time:
        lines.append(f"Process Time: {elapsed}")
    lines += [f"Data: {data}", f"Version: {version}", ""]
    lines += input_lines(fname, sample_count)
    lines += [f"Submission type: {sub_type or '-'}", ""]
    return lines


def tag(r):
    """error→ERR / それ以外→WAR。"""
    return "ERR" if r.get("level") == "error" else "WAR"


def agg_msg(msg, n, noun):
    """代表メッセージ末尾の ')' 直前に " etc, N Noun" を挿入（acc 参照エラーの件数集約）。"""
    if n <= 1:
        return msg
    return (msg[:-1] + f" etc, {n} {noun})") if msg.endswith(")") else f"{msg} etc, {n} {noun}"


def _nonrow_summary(results, is_err, is_row_level):
    """非行単位 summary 行（agg_noun 付きは件数集約、無しは verbatim・初出順）。gea/mb 共通。"""
    out = []
    order, buckets = [], {}
    for r in results:
        if is_row_level(r) or (r.get("level") == "error") != is_err:
            continue
        noun = r.get("agg_noun")
        k = ("agg", r["rule_id"], tag(r), r.get("target") or "-", noun) if noun else ("plain", id(r))
        if k not in buckets:
            buckets[k] = []; order.append(k)
        buckets[k].append(r)
    for k in order:
        rs = buckets[k]
        if k[0] == "plain":
            r = rs[0]
            out.append(f"{r['rule_id']}:{tag(r)}:{r.get('target') or '-'}:{r.get('message','')}")
        else:
            _, rid, t, target, noun = k
            out.append(f"{rid}:{t}:{target}:{agg_msg(rs[0].get('message',''), len(rs), noun)}")
    return out


def fmt_detail(r, is_row_level, row_fmt):
    """details の 1 行。非行単位は共通形式、SDRF 行単位は app 固有 row_fmt に委譲。"""
    if is_row_level(r):
        return row_fmt(r)
    return f"{r['rule_id']}:{tag(r)}:{r.get('target') or '-'}:{r.get('message','')}"


def build_summary(results, fname, version, when, elapsed, *, app_title, data,
                  is_row_level, row_summary, sample_count=None, sub_type=None):
    """summary（件数＋[ ERROR ]/[ WARNING ] のメッセージ一覧）。row_summary は SDRF 行単位の集約 hook。"""
    c = _r.counts(results)
    lines = header(app_title, data, "Summary", fname, version, when, elapsed, sample_count, sub_type, True)
    lines += [f"Error: {c.get('error',0)}   Warning: {c.get('warning',0)}", ""]
    errs = _nonrow_summary(results, True, is_row_level) + row_summary(results, True)
    wars = _nonrow_summary(results, False, is_row_level) + row_summary(results, False)
    if errs:
        lines.append("[ ERROR ]"); lines += errs; lines.append("")
    if wars:
        lines.append("[ WARNING ]"); lines += wars
    return "\n".join(lines).rstrip("\n") + "\n"


def build_details(results, fname, version, when, elapsed, *, app_title, data,
                  is_row_level, row_fmt, sample_count=None, sub_type=None):
    """details（全件）。row_fmt は SDRF 行単位の detail 整形 hook。"""
    lines = header(app_title, data, "Details", fname, version, when, elapsed, sample_count, sub_type, False)
    errs = [r for r in results if r.get("level") == "error"]
    wars = [r for r in results if r.get("level") != "error"]
    if errs:
        lines.append("[ ERROR ]")
        lines += [fmt_detail(r, is_row_level, row_fmt) for r in errs]
        lines.append("")
    if wars:
        lines.append("[ WARNING ]")
        lines += [fmt_detail(r, is_row_level, row_fmt) for r in wars]
    return "\n".join(lines).rstrip("\n") + "\n"
