"""ann→bs 上書き（SSUB TSV override）の純粋ロジック。

オーケストレータ（_generate_biosample_tsv）から呼ばれ、対話/force で `ann_wins` と
判定された提案だけを SSUB TSV の上書き・追加値に変換する。I/O や self 状態を持たない。
"""
from collections import defaultdict


def compute_overrides(proposals, clean_samds, samd_pkg_attrs, samd_sample):
    """ann_wins 判定の提案から SSUB TSV の上書き値を算出する（純粋）。

    対象は「クリーンな SAMD（ann↔bs 1:1）」かつ「そのパッケージ定義に含まれる属性」のみ。
    - 競合(ann≠BS, ann_wins): ann 値で上書き。organism を上書きした場合は taxonomy_id を空にする
      （ann に taxid は無く、管理システムが taxonomy_id を正として学名を引き直すのを防ぐため）。
    - ann限定追加(bs_addition+ann_wins): BS が空のときのみ追加。

    戻り値: (overrides, override_summary, added_summary, taxid_cleared)
      overrides        : {SAMD: {bs_attr: ann_value}}（taxonomy_id クリアを含む）
      override_summary : 表示用 {SAMD: {attr: value}}（競合上書き）
      added_summary    : 表示用 {SAMD: {attr: value}}（ann限定追加）
      taxid_cleared    : organism 上書きで taxonomy_id を空にした SAMD 集合
    """
    overrides = {}
    added_summary = defaultdict(dict)
    override_summary = defaultdict(dict)
    taxid_cleared = set()

    for p in proposals:
        if p.get("bs_decision") != "ann_wins":
            continue
        samd = p.get("source_db", "")
        if samd not in clean_samds:
            continue
        attr = p.get("bs_attr") or p.get("qualifier", "")
        if attr not in samd_pkg_attrs.get(samd, set()):
            continue
        ann_value = p.get("old_value", "")
        if p.get("bs_addition"):
            # ann限定追加: BS が空のときのみ追加
            bs_attrs = samd_sample.get(samd, {}).get("attributes", {})
            if str(bs_attrs.get(attr, "") or "").strip():
                continue
            overrides.setdefault(samd, {})[attr] = ann_value
            added_summary[samd][attr] = ann_value
        else:
            # 競合: ann 値で上書き
            overrides.setdefault(samd, {})[attr] = ann_value
            override_summary[samd][attr] = ann_value
            if attr == "organism":
                overrides[samd]["taxonomy_id"] = ""
                taxid_cleared.add(samd)

    return overrides, override_summary, added_summary, taxid_cleared
