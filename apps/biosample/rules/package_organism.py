"""package_vs_organism 検証（出力 rule_id は汎用 BS_R0048。現行 validator に準拠）。

rules.txt にチェック内容が明記されているため JSON では定義せず、**ハードコード**で実装する。
ただしルール変更時に直しやすいよう、**共通定義（lineage ノード名・特定 taxid・判定ヘルパ）を集約**し、
各パッケージの条件は 1 行の述語（predicate）で表す。判定材料は context.tax_data:
  organism 名 -> {lineage(文字列), tax_id, scientific_name, pl_code, status, ...}（common/db_taxonomy）。
lineage は utax の lineage 文字列に対する部分一致で判定（RDF 不要）。local（skip_ncbi）ではスキップ。
"""
from apps.biosample.rules.base import BsRule
# taxonomy 判定は ddbj と共通化するため common/db_taxonomy のヘルパを使う
from common.db_taxonomy import tax_has_lineage, tax_has_plastids

# ── 共通定義: lineage 文字列に現れる taxonomy ノード名 ─────────────────────
BACTERIA = "Bacteria"
ARCHAEA = "Archaea"
VIRUSES = "Viruses"
FUNGI = "Fungi"
VIROIDS = "Viroids"
METAZOA = "Metazoa"
EMBRYOPHYTA = "Embryophyta"
EUKARYOTA = "Eukaryota"
VIRIDIPLANTAE = "Viridiplantae"
UNCLASSIFIED = "unclassified sequences"
OTHER_SEQ = "other sequences"

# ── 共通定義: 特定種の taxonomy id ──────────────────────────────────────
TAXID_HUMAN = "9606"
TAXID_SARS2 = "2697049"
TAXID_WASTEWATER_METAGENOME = "527639"

METAGENOME = "metagenome"


# ── 判定ヘルパ（tax_data の info と record を受け取る）─────────────────────
# lineage 判定・plastid 判定は common/db_taxonomy と共通（ddbj/biosample で同一実装を使う）。
def has_lineage(info, names):
    """lineage 文字列に names のいずれかを含む（ANY）。common ヘルパへ委譲。"""
    return tax_has_lineage(info, names)


def lineage_none(info, names):
    """lineage 文字列に names のいずれも含まない。"""
    return not tax_has_lineage(info, names)


def has_plastids(info):
    """plastid genetic code を持つ（pl_code != 0）。common ヘルパへ委譲。"""
    return tax_has_plastids(info)


def taxid(info, rec):
    """taxonomy id（tax_data 優先、無ければ ann の taxonomy_id）。"""
    return str(info.get("tax_id") or rec.taxonomy_id or "").strip()


def sci_name(info, rec):
    """学名（tax_data の scientific_name 優先、無ければ organism）。"""
    return (info.get("scientific_name") or rec.organism or "").strip()


def is_metagenome_name(info, rec):
    return sci_name(info, rec).lower().endswith(METAGENOME)


# ── 各パッケージの「適合条件」述語: True=OK / False=違反 ───────────────────
# 共通ヘルパで 1 行表現。ルール変更時はここだけ直せばよい。
def _microbe(info, rec):
    # 原核 OR （真核 かつ 多細胞でない＝単細胞真核）
    prokaryote = has_lineage(info, [BACTERIA, ARCHAEA, VIRUSES, VIROIDS])
    unicellular_eukaryote = has_lineage(info, [EUKARYOTA]) and lineage_none(info, [METAZOA, EMBRYOPHYTA])
    return prokaryote or unicellular_eukaryote


def _model_organism(info, rec):
    return taxid(info, rec) != TAXID_HUMAN and lineage_none(
        info, [BACTERIA, ARCHAEA, VIRUSES, FUNGI, VIROIDS, UNCLASSIFIED, OTHER_SEQ])


def _metagenome(info, rec):
    return has_lineage(info, [UNCLASSIFIED]) and is_metagenome_name(info, rec)


def _plant(info, rec):
    return has_lineage(info, [VIRIDIPLANTAE]) or has_plastids(info)


def _no_homo_no_metagenome(info, rec):
    return taxid(info, rec) != TAXID_HUMAN and METAGENOME not in sci_name(info, rec).lower()


# (パッケージマッチ, マッチ種別, rule_id, 適合述語)
# マッチ種別 exact/prefix。prefix は rec.package がその文字列で始まる場合に該当。
PACKAGE_RULES = [
    ("Pathogen.cl", "exact", "BS_R0074", lambda i, r: has_lineage(i, [BACTERIA, VIRUSES, FUNGI])),
    ("Pathogen.env", "exact", "BS_R0075", lambda i, r: has_lineage(i, [BACTERIA, VIRUSES, FUNGI])),
    ("Microbe", "exact", "BS_R0076", _microbe),
    ("Model.organism.animal", "exact", "BS_R0077", _model_organism),
    ("Metagenome.environmental", "exact", "BS_R0078", _metagenome),
    ("Human", "exact", "BS_R0080", lambda i, r: taxid(i, r) == TAXID_HUMAN),
    ("Plant", "exact", "BS_R0081", _plant),
    ("Virus", "exact", "BS_R0082", lambda i, r: has_lineage(i, [VIRUSES])),
    ("Beta-lactamase", "exact", "BS_R0089", lambda i, r: has_lineage(i, [BACTERIA])),
    ("MIMS.me", "prefix", "BS_R0083", _metagenome),
    ("MIMARKS.survey", "prefix", "BS_R0088", _metagenome),
    ("MIMARKS.specimen", "prefix", "BS_R0130", lambda i, r: not is_metagenome_name(i, r)),
    ("MIGS.ba", "prefix", "BS_R0084", lambda i, r: has_lineage(i, [BACTERIA, ARCHAEA])),
    ("MIGS.eu", "prefix", "BS_R0085", lambda i, r: has_lineage(i, [EUKARYOTA])),
    ("MIGS.vi", "prefix", "BS_R0086", lambda i, r: has_lineage(i, [VIRUSES])),
    ("MIMAG", "prefix", "BS_R0110", _no_homo_no_metagenome),
    ("MISAG", "prefix", "BS_R0111", _no_homo_no_metagenome),
    ("MIUVIG", "prefix", "BS_R0112", lambda i, r: has_lineage(i, [VIRUSES])),
    ("SARS-CoV-2.cl", "prefix", "BS_R0120", lambda i, r: taxid(i, r) == TAXID_SARS2),
    ("SARS-CoV-2.wwsurv", "prefix", "BS_R0121", lambda i, r: taxid(i, r) == TAXID_WASTEWATER_METAGENOME),
]


def _find_rule(package):
    """rec.package に対応する (rule_id, predicate) を返す。無ければ None。"""
    for name, mtype, rule_id, pred in PACKAGE_RULES:
        if (mtype == "exact" and package == name) or (mtype == "prefix" and package.startswith(name)):
            return rule_id, pred
    return None


# taxid が特定値かどうかだけで適合を判定する package（Human / SARS-CoV-2.cl / SARS-CoV-2.wwsurv）。
# これらは lineage を見ないため、organism が Taxonomy 未解決でも「宣言/数値 taxid ≠ 要求 taxid」なら不適合。
_TAXID_FIXED = {"BS_R0080", "BS_R0120", "BS_R0121"}


def resolve_effective_taxinfo(rec, context):
    """package/lineage 判定に使う **実効 taxonomy info** を返す（organism＋taxonomy_id の一元解決）。

    - organism を tax_data で解決。taxonomy_id が明示され taxid_info で lineage が引ければ、
      **taxid 由来（lineage/pl_code/tax_id/scientific_name）を正**とし organism 由来と混ぜない
      （誤情報取り込み防止。R0048 の pl_code 取りこぼしバグの再発防止）。
    - organism が Taxonomy 未解決なら None（呼び出し側で扱う）。
    注: R0004/R0096/R0045 は「記載 taxid の学名／is_species_or_below／数値 organism」を個別に使うため本ヘルパの対象外。
    """
    info = context.tax_data.get(rec.organism)
    if not info or info.get("status") == "not_found":
        return None
    tid = str(rec.taxonomy_id).strip() if getattr(rec, "taxonomy_id", None) else ""
    tinfo = context.taxid_info.get(tid) if tid else None
    if tinfo and tinfo.get("lineage"):
        return {"lineage": tinfo["lineage"], "pl_code": tinfo.get("pl_code", 0),
                "tax_id": tid, "scientific_name": tinfo.get("scientific_name") or ""}
    return info


class PackageOrganismValidator(BsRule):
    """パッケージと organism(taxonomy) の適合を検証する単一のデータ駆動ルール。

    判定は package 別の述語（PACKAGE_RULES）で行うが、**出力 rule_id は汎用 BS_R0048 で統一**する
    （現行 validator に合わせる）。organism が taxonomy 未解決（tax_data に無い / not_found）の場合は
    判定不能としてスキップ（taxonomy 未登録は別ルールの領分）。
    """
    rule_id = "BS_R0048"
    level = "error"
    target = "package, organism"
    requires_network = True  # taxonomy ソース（DB/NCBI）が要る。local ではスキップ

    def validate(self, submission, context):
        out = []
        for rec in submission.records:
            if not rec.package or not rec.organism:
                continue
            found = _find_rule(rec.package)
            if not found:
                continue  # package_vs_organism 対象外パッケージ
            _rule_id, pred = found  # 判定は package 別述語、出力 rule_id は汎用 BS_R0048（現行 validator 準拠）
            info = resolve_effective_taxinfo(rec, context)  # organism＋taxid の一元解決（taxid 優先）
            if info is None:
                # organism 未解決。taxid 固定 package は taxid だけで判定できる（要求 taxid と不一致なら不適合）。
                if _rule_id not in _TAXID_FIXED:
                    continue  # lineage 判定が要る package → 判定不能
                tid = str(rec.taxonomy_id).strip() if rec.taxonomy_id else ""
                eff = tid or (rec.organism.strip() if rec.organism.strip().isdigit() else "")
                info = {"tax_id": eff, "lineage": "", "pl_code": 0, "scientific_name": ""}
            if not pred(info, rec):
                out.append(self.result(
                    sample=rec.sample_id,
                    anno_cols=[{"key": "organism", "value": rec.organism or ""},
                               {"key": "taxonomy_id", "value": ("" if not rec.taxonomy_id else str(rec.taxonomy_id).strip())},
                               {"key": "package", "value": rec.package or ""},
                               {"key": "Message", "value": f"Organism is inappropriate for package '{rec.package}'."}],
                    message=f"Organism is inappropriate for package '{rec.package}'. (organism: '{rec.organism}')"))
        return out
