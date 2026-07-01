"""Taxonomy 依存ルール（フェーズ B）。

context.tax_data（organism 名 -> {tax_id, rank, scientific_name, is_species_or_below, status, lineage}）を参照。
tax_data は DB(common/db_taxonomy) または NCBI API で取得。local（skip_ncbi）では空＝本ルール群はスキップ。

- BS_R0004: organism と taxonomy_id が一致しない
- BS_R0096: taxonomy が species 以下（infraspecific）でない
"""
from apps.biosample.rules.base import BsRule
from apps.biosample.rules._util import is_empty as _empty
from common.db_taxonomy import tax_has_lineage


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


def _sci_or_org(info, rec):
    return (info.get("scientific_name") if info else None) or rec.organism or ""


class BS_R0059(BsRule):
    rule_id = "BS_R0059"
    level = "warning"
    target = "organism, sex"
    description = "Attribute 'sex' is not appropriate."
    requires_network = True

    def validate(self, submission, context):
        out = []
        for rec in submission.records:
            if _empty(rec.attr("sex")) or _empty(rec.organism):
                continue
            info = context.tax_data.get(rec.organism)
            if not info:
                continue
            if tax_has_lineage(info, ["Bacteria", "Archaea"]):
                out.append(self.result(sample=(rec.sample_name or rec.accession),
                                       message="Attribute 'sex' is not appropriate for bacteria/archaea."))
        return out


class BS_R0115(BsRule):
    rule_id = "BS_R0115"
    level = "error"
    target = "specimen_voucher, organism"
    description = "Attribute 'specimen_voucher' is not appropriate for bacteria and unclassified sequences."
    requires_network = True

    def validate(self, submission, context):
        out = []
        for rec in submission.records:
            if _empty(rec.attr("specimen_voucher")) or _empty(rec.organism):
                continue
            info = context.tax_data.get(rec.organism)
            if not info:
                continue
            # Bacteria(Cyanobacteria を除く) または unclassified sequences は不可
            is_bacteria = tax_has_lineage(info, ["Bacteria"]) and not tax_has_lineage(info, ["Cyanobacteria"])
            if is_bacteria or tax_has_lineage(info, ["unclassified sequences"]):
                out.append(self.result(sample=(rec.sample_name or rec.accession),
                                       message="Attribute 'specimen_voucher' is not appropriate for bacteria/unclassified sequences."))
        return out


class BS_R0106(BsRule):
    rule_id = "BS_R0106"
    level = "error"
    target = "metagenome_source"
    description = "A metagenomic organism name in the taxonomy database should be used (e.g., 'soil metagenome')."

    def validate(self, submission, context):
        out = []
        for rec in submission.records:
            v = rec.attr("metagenome_source")
            if _empty(v):
                continue
            if not v.strip().lower().endswith("metagenome"):
                out.append(self.result(sample=(rec.sample_name or rec.accession),
                                       message=f"Invalid metagenome source. (Found: '{v}')"))
        return out


class BS_R0141(BsRule):
    rule_id = "BS_R0141"
    level = "error"
    target = "organism"
    description = "Organism names containing 'uncultured' cannot be used for MIMAG package."

    def validate(self, submission, context):
        out = []
        for rec in submission.records:
            if not rec.package or not rec.package.startswith("MIMAG"):
                continue
            if rec.organism and "uncultured" in rec.organism.lower():
                out.append(self.result(sample=(rec.sample_name or rec.accession),
                                       message=f"Organism containing 'uncultured' cannot be used for MIMAG. (organism: '{rec.organism}')"))
        return out
