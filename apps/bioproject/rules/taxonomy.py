"""BioProject taxonomy ルール（common/db_taxonomy を biosample と共用）。

- BP_R0018: taxonomy が species 以下（infraspecific）でない（= BS_R0096 相当）。
- BP_R0020: sample_scope が Environment のとき organism は metagenome でなければならない（= BS_R0106 相当）。
- BP_R0038: organism と taxonomy_id が不一致（= BS_R0004 相当）。
- BP_R0039: organism が Taxonomy 未解決の警告（= BS_R0045 warning 相当）。
tax_data/taxid_info は cli で事前取得（DB or NCBI）。local（skip_ncbi）では空＝スキップ。
"""
from apps.bioproject.rules.base import BpRule
from common.db_taxonomy import tax_rank_invalid, tax_has_lineage


def _found(info):
    return bool(info) and info.get("status") != "not_found"


class BP_R0018(BpRule):
    rule_id = "BP_R0018"
    level = "error"
    target = "taxonomy_id"
    description = "Taxonomy should be species or infraspecific level."
    requires_network = True

    def validate(self, submission, context):
        out = []
        for rec in submission.records:
            if not rec.organism_name:
                continue
            taxid = str(rec.tax_id).strip() if rec.tax_id else None
            tinfo = context.taxid_info.get(taxid) if taxid else None
            if tinfo is not None:
                if tinfo.get("is_species_or_below") is False:
                    out.append(self.result(sample=rec.label,
                                           message=f"Taxonomy should be species or infraspecific level. (taxonomy_id: '{taxid}', rank: '{tinfo.get('rank')}')"))
                continue
            info = context.tax_data.get(rec.organism_name)
            if tax_rank_invalid(info):
                out.append(self.result(sample=rec.label,
                                       message=f"Taxonomy should be species or infraspecific level. (organism: '{rec.organism_name}', rank: '{info.get('rank')}')"))
        return out


class BP_R0020(BpRule):
    rule_id = "BP_R0020"
    level = "error"
    target = "sample_scope, organism"
    description = ("When sample_scope is \"Environment\", taxonomy must be a metagenome where lineage starts with "
                   "unclassified sequences and scientific name ends with 'metagenome'.")
    requires_network = True

    def validate(self, submission, context):
        out = []
        for rec in submission.records:
            # sample_scope の Environment（XSD 値 eEnvironment）のみ対象
            if not rec.organism_name or (rec.sample_scope or "").lower() not in ("eenvironment", "environment"):
                continue
            info = context.tax_data.get(rec.organism_name) or {}
            sci = (info.get("scientific_name") or "").lower()
            is_meta = tax_has_lineage(info, ["unclassified sequences"]) and sci.endswith("metagenome")
            if not is_meta:
                out.append(self.result(sample=rec.label,
                                       message=f"When sample_scope is Environment, taxonomy must be a metagenome. (organism: '{rec.organism_name}')"))
        return out


class BP_R0038(BpRule):
    rule_id = "BP_R0038"
    level = "error"
    target = "organism, taxonomy_id"
    description = "Organism and taxonomy id do not match."
    requires_network = True

    def validate(self, submission, context):
        out = []
        for rec in submission.records:
            if not rec.organism_name or not rec.tax_id:
                continue
            taxid = str(rec.tax_id).strip()
            name_of_taxid = (context.taxid_info.get(taxid) or {}).get("scientific_name")
            if name_of_taxid:
                if name_of_taxid != rec.organism_name.strip():
                    out.append(self.result(sample=rec.label,
                                           message=(f"Organism and taxonomy id do not match. (organism: '{rec.organism_name}', "
                                                    f"taxonomy_id: '{taxid}', Organism name of this taxonomy_id: '{name_of_taxid}')")))
                continue
            info = context.tax_data.get(rec.organism_name)
            if _found(info):
                db_taxid = info.get("tax_id")
                if db_taxid and taxid != str(db_taxid).strip():
                    out.append(self.result(sample=rec.label,
                                           message=f"Organism and taxonomy id do not match. (organism: '{rec.organism_name}', taxonomy_id: '{taxid}', expected: '{db_taxid}')"))
        return out


class BP_R0039(BpRule):
    rule_id = "BP_R0039"
    level = "warning"
    target = "organism"
    description = ("Submission processing may be delayed due to necessary curator review. "
                   "Please check spelling of organism.")
    requires_network = True

    def validate(self, submission, context):
        out = []
        for rec in submission.records:
            if not rec.organism_name:
                continue
            taxid = str(rec.tax_id).strip() if rec.tax_id else None
            # taxonomy_id が解決できていれば警告しない
            if taxid and context.taxid_info.get(taxid):
                continue
            if not _found(context.tax_data.get(rec.organism_name)):
                out.append(self.result(sample=rec.label,
                                       message=("Taxonomy error warning. Organism is not found in the Taxonomy database. "
                                                f"Please check spelling of organism. (organism: '{rec.organism_name}')")))
        return out
