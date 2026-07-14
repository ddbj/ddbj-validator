"""MAGE-TAB の BioSample 整合の共通ロジック（MetaboBank / GEA で共有）。

SDRF の Characteristics[attr] を、参照 BioSample（Comment[BioSample] 等 = SAMD）の DB 属性と突合する
core を提供する。ルール ID / level / autofix の付け方は各 app のルールクラス側で行う。
比較対象は definitions.biosample_sync（biosample_ref_columns / sync_characteristics）。
"""
import re

_SAMD = re.compile(r"^SAMD\d+$")


def ref_columns(context, default=("Comment[BioSample]",)):
    """SDRF 上で SAMD を探す参照列（definitions.biosample_sync.biosample_ref_columns）。"""
    cols = (context.definitions or {}).get("biosample_sync", {}).get("biosample_ref_columns")
    return list(cols) if cols else list(default)


def referenced_samds(sub, cols):
    """SDRF が参照する BioSample(SAMD) の重複排除集合（ヘッダの "(N samples)" 用）。"""
    out = set()
    if not sub.sdrf:
        return out
    for col in cols:
        for i in sub.sdrf.col_indices(col):
            for row in sub.sdrf.rows:
                v = (row[i] if i < len(row) else "").strip()
                if _SAMD.match(v):
                    out.add(v)
    return out


def row_samd(sub, row, cols):
    for col in cols:
        for i in sub.sdrf.col_indices(col):
            v = (row[i] if i < len(row) else "").strip()
            if _SAMD.match(v):
                return v
    return None


def char_columns(sub, context):
    """比較対象の Characteristics[attr] → {attr: 先頭列 index}。

    definitions.biosample_sync.sync_characteristics が定義されていればその属性のみ（gea）、
    未定義/空なら **全ての Characteristics[attr]** を対象にする（mb: BS の引き写しのため全属性比較）。
    """
    sync = (context.definitions or {}).get("biosample_sync", {}).get("sync_characteristics", [])
    out = {}
    for h in sub.sdrf.header:
        m = re.fullmatch(r"Characteristics\[(.+)\]", h)
        if m and (not sync or m.group(1) in sync):
            out[m.group(1)] = sub.sdrf.col_indices(h)[0]
    return out


def assay_name(sub, row_index):
    """行（0-based）の Assay Name 値。レポートの location 用。無ければ空。"""
    if not sub.sdrf:
        return ""
    idxs = sub.sdrf.col_indices("Assay Name")
    if not idxs or row_index >= len(sub.sdrf.rows):
        return ""
    row = sub.sdrf.rows[row_index]
    return row[idxs[0]].strip() if idxs[0] < len(row) else ""


def iter_missing_attrs(sub, context, attrs, cols):
    """「SDRF Characteristics にあるが参照 BioSample に無い属性」の検出。yield (samd, attr, row_index)。

    「値が空」と「属性そのものが無い」は、BS 属性・SDRF Characteristics のどちらも **無い（not present）** ものとして扱う。
    - SDRF 値あり × BS 空/不在 → 値不一致（autofix 対象）として iter_value_mismatches が拾う。
    - SDRF 空 × BS 空/不在 → 両方 not present ＝ 報告しない。
    → 結果としてこの関数が報告するケースは残らない（何も yield しない）。SR0021 / GEA_BS0001 は発火しない。
    """
    return
    yield  # pragma: no cover  （ジェネレータ化のためのダミー。実際には yield されない）


def iter_unknown_biosamples(sub, attrs, cols):
    """account/DB に無い（属性ゼロ含む）参照 BioSample。yield (samd, row_index)（重複なし・初出行）。"""
    seen = set()
    for ri, row in enumerate(sub.sdrf.rows):
        samd = row_samd(sub, row, cols)
        if samd and samd not in seen:
            seen.add(samd)
            if samd not in attrs or not attrs[samd]:
                yield samd, ri


def iter_value_mismatches(sub, context, attrs, cols):
    """Characteristics 値と BioSample 属性値の不一致。yield (samd, attr, sdrf_value, bs_value, row_index)。"""
    cc = char_columns(sub, context)
    for ri, row in enumerate(sub.sdrf.rows):
        samd = row_samd(sub, row, cols)
        if not samd or samd not in attrs:
            continue
        bs = attrs[samd]
        for attr, idx in cc.items():
            sdrf_v = (row[idx] if idx < len(row) else "").strip()
            bs_v = str(bs.get(attr, "")).strip()   # BS 側が不在なら空文字扱い
            # 片方が空でも、値が異なり かつ少なくとも一方に値があれば不一致（autofix 対象）
            if sdrf_v != bs_v and (sdrf_v or bs_v):
                yield samd, attr, sdrf_v, bs_v, ri


def fetch_biosample_attrs(sub, cols):
    """参照 SAMD の BioSample 属性を内部 DB から取得。{SAMD: {attr: value}} を返す。

    参照 SAMD が無ければ {}。DB 例外は呼び出し側で捕捉する（ここでは投げる）。
    """
    from common.db_manager import DatabaseManager
    samds = set()
    if sub.sdrf:
        for col in cols:
            for i in sub.sdrf.col_indices(col):
                for row in sub.sdrf.rows:
                    v = (row[i] if i < len(row) else "").strip()
                    if _SAMD.match(v):
                        samds.add(v)
    if not samds:
        return {}
    conn = DatabaseManager().get_bs_conn()
    attrs = {}
    with conn.cursor() as cur:
        cur.execute(
            "SELECT acc.accession_id, attr.attribute_name, attr.attribute_value "
            "FROM mass.attribute attr JOIN mass.accession acc USING(smp_id) "
            "WHERE acc.accession_id = ANY(%s)", (sorted(samds),))
        for acc_id, name, value in cur.fetchall():
            attrs.setdefault(str(acc_id).strip(), {})[str(name).strip()] = value
    return attrs
