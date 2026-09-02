"""MAGE-TAB（MetaboBank / GEA）の BioSample ↔ SDRF 双方向 autofix（共通実装）。

SDRF は BioSample の引き写しのため、値不一致ルール（mb=MB_SR0023 / gea=GEA_BS0003）に対して双方向で提案する:
  - bs2sdrf: BioSample 値で SDRF を修正（<out>/fixed/ の SDRF に反映。入力 SDRF は変更しない）
  - sdrf2bs: SDRF 値で BioSample を更新（<out>/biosample/ の SSUB 更新 TSV に反映）
  - skip   : どちらも変更しない
対話は ddbj の -b autofix（apps/ddbj/autofix/manager）に倣い、属性ごとにキー入力で方向を選ぶ。
-b（biosample_mode）あり時のみ SDRF -> BioSample（[b]）を出す。無ければ BioSample -> SDRF のみ。
"""
import logging
from pathlib import Path

from common.magetab import biosample as _bs
from common.prompt import ask as _ask, is_interactive as _is_interactive

logger = logging.getLogger(__name__)

_ARROW = {"bs2sdrf": "BioSample -> SDRF", "sdrf2bs": "SDRF -> BioSample", "skip": "skip"}


def build_proposals(results, rule_id):
    """値不一致ルール（autofix=True）から双方向 autofix 提案を作る。既定方向は bs2sdrf。"""
    props = []
    for r in results:
        if r.get("rule_id") == rule_id and r.get("autofix"):
            props.append({
                "rule_id": r.get("rule_id"), "target": r.get("target") or "SDRF",
                "samd": r.get("samd"), "attr": r.get("attr"),
                "sdrf_value": r.get("sdrf_value", ""), "bs_value": r.get("bs_value", ""),
                "line": r.get("line"), "assay": r.get("assay", ""),
                "direction": "bs2sdrf",
            })
    return props


def review(proposals, force_fix=False, biosample_apply="bs2sdrf", biosample_mode=False):
    """各提案に direction を確定する（ddbj と同じ仕様）。

    - biosample_mode（-b あり）: SDRF -> BioSample 提案も出す（メニュー/interactive に [b]）。
    - biosample_mode 無し（-b なし）: BioSample -> SDRF のみ（[b] を出さない）。
    - force_fix / 非 TTY: 非対話。-b 無しなら常に bs2sdrf、あれば biosample_apply。
    """
    if not proposals:
        return proposals
    default = "sdrf2bs" if (biosample_mode and biosample_apply == "sdrf2bs") else "bs2sdrf"
    if force_fix or not _is_interactive():
        for p in proposals:
            p["direction"] = default
        return proposals

    if biosample_mode:
        menu = ("\nAuto-fix (BioSample <-> SDRF): [a] Apply all (BioSample -> SDRF), "
                "[b] Apply all (SDRF -> BioSample), [i] Interactive, [q] Quit/Skip all? ")
        item_prompt = "[y] BioSample -> SDRF, [b] SDRF -> BioSample, [n] skip? "
    else:
        menu = ("\nAuto-fix (BioSample -> SDRF): [a] Apply all, "
                "[i] Interactive, [q] Quit/Skip all? ")
        item_prompt = "[y] BioSample -> SDRF, [n] skip? "

    ans = _ask(menu, "q")
    if ans == "a":
        for p in proposals:
            p["direction"] = "bs2sdrf"
    elif ans == "b" and biosample_mode:
        for p in proposals:
            p["direction"] = "sdrf2bs"
    elif ans == "i":
        from collections import OrderedDict
        groups = OrderedDict()
        for p in proposals:
            groups.setdefault(p["attr"], []).append(p)
        keymap = {"y": "bs2sdrf", "n": "skip"}
        if biosample_mode:
            keymap["b"] = "sdrf2bs"
        for attr, ps in groups.items():
            rep = ps[0]
            first = rep.get("assay") or "-"
            assay_disp = f"{first} etc" if len(ps) > 1 else first
            k = _ask(f"\n  {len(ps)} lines:{assay_disp}\n"
                     f"  {attr} SDRF:'{rep['sdrf_value']}', BioSample:'{rep['bs_value']}'\n"
                     f"  {item_prompt}", "n")
            d = keymap.get(k, "skip")
            for p in ps:
                p["direction"] = d
    else:
        for p in proposals:
            p["direction"] = "skip"
    return proposals


def write_confirmation(proposals, out_dir, title):
    """reports/autofix_confirmation_summary.txt を出力（-j の有無に関わらず）。

    形式: {rule_id}:{target}:line {n}:{assay}:{attr}: SDRF '{sv}' / BioSample {samd} '{bv}', autofix: {方向}
    """
    reports = Path(out_dir) / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    lines = [f"=== {title} Auto-Fix Confirmation ===", ""]
    for p in proposals:
        lines.append(
            f"{p.get('rule_id', '')}:{p.get('target', 'SDRF')}:"
            f"line {p['line']}:{p['assay'] or '-'}:{p['attr']}: "
            f"SDRF:'{p['sdrf_value']}', BioSample {p['samd']}:'{p['bs_value']}', "
            f"autofix: {_ARROW[p['direction']]}")
    (reports / "autofix_confirmation_summary.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def apply_bs2sdrf(sub, proposals):
    """bs2sdrf: sub.sdrf.rows のセルを BioSample 値へ書き換える（fixed/ 出力は cli の _write_fixed が担う）。
    入力 SDRF ファイルは変更しない（メモリ上の sub.sdrf のみ）。"""
    if not sub.sdrf:
        return 0
    n = 0
    for p in proposals:
        if p["direction"] != "bs2sdrf" or not p.get("line"):
            continue
        ri = p["line"] - 1
        idxs = sub.sdrf.col_indices(f"Characteristics[{p['attr']}]")
        if not idxs or ri < 0 or ri >= len(sub.sdrf.rows):
            continue
        row = sub.sdrf.rows[ri]
        ci = idxs[0]
        if ci < len(row):
            row[ci] = p["bs_value"]
            n += 1
    return n


def build_ssub_tsvs(sub, proposals, out_dir, ref_cols):
    """sdrf2bs: SDRF 値で BioSample を更新する SSUB 単位 TSV を <out>/biosample/ に生成（内部 DB 必須）。

    ddbj の db_meta_biosample.fetch_biosample_ssub ＋ biosample.tsv.build_ssub_tsv を再利用。
    既存 biosample/*.txt は掃除してから生成する（取り違え防止）。保存メッセージは ddbj 体裁。
    """
    biosample_dir = Path(out_dir) / "biosample"
    if biosample_dir.exists():
        for f in biosample_dir.glob("*.txt"):
            f.unlink()

    sdrf2bs = [p for p in proposals if p["direction"] == "sdrf2bs"]
    if not sdrf2bs:
        return []

    from apps.ddbj.biosample import tsv as bstsv
    from apps.ddbj.db_meta_biosample import fetch_biosample_ssub
    from common.db_manager import DatabaseManager

    overrides = {}
    for p in sdrf2bs:
        overrides.setdefault(p["samd"], {})[p["attr"]] = p["sdrf_value"]

    conn = DatabaseManager().get_bs_conn()
    ssub_map, _found = fetch_biosample_ssub(conn, sorted(_bs.referenced_samds(sub, ref_cols)))
    fixed_attributes, packages = bstsv.load_biosample_definitions()

    biosample_dir.mkdir(parents=True, exist_ok=True)
    print("\n=== BioSample Submission TSV ===")
    written = []
    for ssub_id, data in ssub_map.items():
        text, pkgkey = bstsv.build_ssub_tsv(data["samples"], fixed_attributes, packages, overrides=overrides)
        if text is None:
            print(f"  [WARN] Package definition not resolved for SSUB {ssub_id}. Skipped.")
            continue
        touched = any(s.get("accession_id") in overrides for s in data["samples"])
        name = f"{ssub_id}{'' if touched else '_unmodified'}.txt"
        path = biosample_dir / name
        path.write_text(text, encoding="utf-8")
        n = len(data["samples"])
        print(f"  => {path}  (package={pkgkey}, {n} sample{'' if n == 1 else 's'})")
        written.append(path)
    return written
