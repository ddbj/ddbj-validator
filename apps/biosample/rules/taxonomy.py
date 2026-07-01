"""Taxonomy 依存ルール（フェーズ B）。

context.tax_data（organism 名 -> {tax_id, rank, scientific_name, is_species_or_below, status, lineage}）を参照。
tax_data は DB(common/db_taxonomy) または NCBI API で取得。local（skip_ncbi）では空＝本ルール群はスキップ。

- BS_R0004: organism と taxonomy_id が一致しない
- BS_R0096: taxonomy が species 以下（infraspecific）でない
"""
from apps.biosample.rules.base import BsRule
from apps.biosample.rules._util import is_empty as _empty


class BS_R0004(BsRule):
    rule_id = "BS_R0004"
    level = "error"
    target = "organism AND taxonomy_id"
    description = "Organism and taxonomy id do not match."
    requires_network = True  # taxonomy ソース（DB or NCBI）が要る。local ではスキップ

    def validate(self, submission, context):
        out = []
        for rec in submission.records:
            if _empty(rec.organism) or _empty(rec.taxonomy_id):
                continue
            info = context.tax_data.get(rec.organism)
            if not info or info.get("status") == "not_found":
                continue  # 解決できない organism は別ルール（taxonomy 未登録等）
            db_taxid = info.get("tax_id")
            if db_taxid and str(rec.taxonomy_id).strip() != str(db_taxid).strip():
                out.append(self.result(
                    sample=(rec.sample_name or rec.accession),
                    message=f"Organism and taxonomy id do not match. (organism: '{rec.organism}', taxonomy_id: '{rec.taxonomy_id}', expected: '{db_taxid}')"))
        return out


class BS_R0096(BsRule):
    rule_id = "BS_R0096"
    level = "error"
    target = "taxonomy_id"
    description = "Taxonomy should be species or infraspecific level."
    requires_network = True

    def validate(self, submission, context):
        out = []
        for rec in submission.records:
            if _empty(rec.taxonomy_id) or _empty(rec.organism):
                continue
            info = context.tax_data.get(rec.organism)
            if not info or info.get("status") == "not_found":
                continue
            if info.get("is_species_or_below") is False:
                out.append(self.result(
                    sample=(rec.sample_name or rec.accession),
                    message=f"Taxonomy should be species or infraspecific level. (organism: '{rec.organism}', rank: '{info.get('rank')}')"))
        return out
