"""patent app の定数。閾値・文字集合・許可する rule id をここ 1 か所にまとめる。

閾値（PAT0038 / PAT0040 / PAT0041）は特許担当と決める値なので、変えるときはここだけを直す。
"""
import json
from datetime import date
from pathlib import Path

# ---------------------------------------------------------------------------
# ddbj から借りる検査の rule id（依頼書 4.2 の表）。
# 前処理・parser・まとめ役の規則（ENTRY_CONSISTENCY / FASTA_FORMAT）は表に無い id も出すので、
# ここに無い id の結果は捨てる（runner.filter_results）。「外す規則」ではなく「使う規則」を選ぶ。
# ---------------------------------------------------------------------------
BORROWED_RULE_IDS = frozenset({
    "ANN0010", "ANN0020",              # ann と FASTA の組
    "ANN0040",                         # 非 ASCII の文字
    "ANN0050",                         # 長すぎる行
    "SEQ0080", "SEQ0110", "ANN0120",   # FASTA の見出し、entry 名の重複
    "ANN0140", "ANN0190",              # 列の数、qualifier 名の欠け
    "ANN0160",                         # entry 名
    "AXS0060", "AXS0070",              # ann と FASTA の entry の対応（ENTRY_CONSISTENCY）
    "ANN2010", "ANN2020", "ANN2030",   # source の location の有無と構文
    "AXS2080",                         # source の location が配列の長さを超える
    "SEQ5050",                         # 2.14 Gb を超える
})

# 重さ。flag は「通して印を返す」（TSM が qc_flags / insdc_exchange に使う）
LEVEL_FLAG = "flag"

# ---------------------------------------------------------------------------
# set の種類（ファイル名の `_na` / `_aa`）
# ---------------------------------------------------------------------------
KIND_NA = "na"
KIND_AA = "aa"


def set_kind(ann_path):
    """ファイル名から NA / AA を決める（`<順>_<公報>_na.ann` / `_aa.ann`）。どちらでもなければ None。"""
    stem = Path(ann_path).name.lower()
    for ext in (".ann", ".annt.tsv", ".ann.txt"):   # apps.ddbj.preprocessor.ANN_EXTENSIONS と同じ
        if stem.endswith(ext):
            stem = stem[:-len(ext)]
            break
    if stem.endswith("_na"):
        return KIND_NA
    if stem.endswith("_aa"):
        return KIND_AA
    return None


# ---------------------------------------------------------------------------
# 配列の文字
# ---------------------------------------------------------------------------
def _ddbj_cv_terms():
    path = Path(__file__).resolve().parents[1] / "ddbj" / "resources" / "definitions.json"
    return json.loads(path.read_text(encoding="utf-8")).get("cv_terms", {})


_CV = _ddbj_cv_terms()
# NA: IUPAC の塩基（ddbj の定義と同じ acgtmrwsykvhdbn）
NA_CHARS = frozenset(c.lower() for c in _CV.get("nucleic_acids", "acgtmrwsykvhdbn"))
# AA: ddbj で使えるアミノ酸の 1 文字（定義の code。J = Xle を含む。終止の `*` は除く）
AA_CHARS = frozenset(v["code"].upper() for v in _CV.get("amino_acids", {}).values()
                     if v.get("code", "").isalpha())
# アミノ酸の 3 文字表記（PAT0041 用。大文字）。修飾アミノ酸（type M。Aad など）は入れない。配列の 3 文字が偶然一致するのを減らすため
AA_THREE_LETTER = frozenset(k.upper() for k, v in _CV.get("amino_acids", {}).items()
                            if len(k) == 3 and k.isalpha() and v.get("type") != "M")
# NA の配列に現れたら「アミノ酸だけの文字」とみなす文字（PAT0039 = NAwithAA）
NA_AA_ONLY_CHARS = frozenset("efijlopqxz")
# AA の配列が塩基らしいかを見る文字（PAT0040 = AAwithNA）
AA_NA_LIKE_CHARS = "ACGTU"

# ---------------------------------------------------------------------------
# 閾値（仮。特許担当と決める）
# ---------------------------------------------------------------------------
MIN_LEN_NA = 10            # PAT0038: NA の短い配列（ST.26 の下限）
MIN_LEN_AA = 4             # PAT0038: AA の短い配列（ST.26 の下限）
AA_NA_LIKE_RATIO = 0.9     # PAT0040: A / C / G / T / U の割合
AA_NA_LIKE_MIN_LEN = 10    # PAT0040: この長さ以上だけ見る
AA_3L_RATIO = 0.5          # PAT0041: 3 文字表記が配列の長さに占める割合

# ---------------------------------------------------------------------------
# FF の形
# ---------------------------------------------------------------------------
FF_LINE_WIDTH = 68                      # PAT0036: COMMENT の line と journal の幅
EARLIEST_DATE = date(1980, 1, 1)        # PAT0009
DATE_NOT_PROVIDED = "NOT_PROVIDED"      # PF で日付の代わりに書いてよい値
DIVISION = "PAT"

# COMMENT の行の頭に書けるタグ（PAT0034）。KR の公報だけ KN / AN / AD も可
COMMENT_TAGS = frozenset({"OS", "PN", "PD", "PF", "PR", "PA", "PT", "PI", "PS", "FH", "FT", "DC"})
COMMENT_TAGS_KR = frozenset({"KN", "AN", "AD"})
COMMENT_REQUIRED_TAGS = ("OS", "PN", "PD", "PS", "FH")

# 書いてよい feature と qualifier（PAT0044）。ここに無いものは FF にそのまま出てしまうので error
ALLOWED_COMMON = {"DIVISION": frozenset({"division"})}
ALLOWED_ENTRY = {
    "KEYWORD": frozenset({"keyword"}),
    "REFERENCE": frozenset({"ab_name", "title", "journal"}),   # ab_name = 発明者（FF の AUTHORS）
    "COMMENT": frozenset({"line"}),
    "source": frozenset({"organism", "mol_type", "ff_definition"}),
}

# taxonomy に無くてもよい organism（PAT0043）
ORGANISM_ALWAYS_OK = frozenset({"unidentified", "synthetic construct"})
