"""Taxonomy 依存ルール（フェーズ B）。

context.tax_data（organism 名 -> {tax_id, rank, scientific_name, is_species_or_below, status, lineage}）を参照。
tax_data は DB(common/db_taxonomy) または NCBI API で取得。local（skip_ncbi）では空＝本ルール群はスキップ。

- BS_R0004: organism と taxonomy_id が一致しない
- BS_R0096: taxonomy が species 以下（infraspecific）でない
- BS_R0045: organism を学名へ補正し taxonomy_id を補完（autofix）
- BS_R0105: component_organism を学名へ補正（autofix）
"""
import re
from apps.biosample.rules.base import BsRule
from apps.biosample.rules._util import is_empty, is_missing_value, pkg_startswith, MIGS_BA_EU
from common.db_taxonomy import tax_has_lineage

# informal name（"Genus sp. strain"）判定用（R0104/R0134/R0140）
_SP_KEYWORDS = [
    re.compile(r"\ssp\.", re.I),      # "sp." は前が空白
    re.compile(r"\bbacterium\b", re.I),
    re.compile(r"\barchaeon\b", re.I),
]
_SP_END = re.compile(r"\ssp\.\s*$", re.I)                    # 末尾が " sp."
_SP_INEX = re.compile(r".+sp\.\s*\((in:|ex)\s.*\)$", re.I)   # "xxx sp. (in: yyy)" / "(ex yyy)"


def _found(info):
    """tax_data で organism が解決できた（status が not_found でない）か。R0004/R0096 用。"""
    return bool(info) and info.get("status") != "not_found"


def _resolved(info):
    """学名解決済み（found かつ scientific_name あり）。autofix 系（R0045/R0105/R0015）用。"""
    return _found(info) and bool(info.get("scientific_name"))


class BS_R0004(BsRule):
    rule_id = "BS_R0004"
    level = "error"
    target = "organism AND taxonomy_id"
    description = "Organism and taxonomy id do not match."
    requires_network = True  # taxonomy ソース（DB or NCBI）が要る。local ではスキップ

    def validate(self, submission, context):
        out = []
        for rec in submission.records:
            if is_empty(rec.organism) or is_empty(rec.taxonomy_id):
                continue
            info = context.tax_data.get(rec.organism)
            if not _found(info):
                continue  # 解決できない organism は別ルール（taxonomy 未登録等）
            db_taxid = info.get("tax_id")
            if db_taxid and str(rec.taxonomy_id).strip() != str(db_taxid).strip():
                out.append(self.result(
                    sample=rec.sample_id,
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
            if is_empty(rec.taxonomy_id) or is_empty(rec.organism):
                continue
            info = context.tax_data.get(rec.organism)
            if not _found(info):
                continue
            if info.get("is_species_or_below") is False:
                out.append(self.result(
                    sample=rec.sample_id,
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
            if is_empty(rec.attr("sex")) or is_empty(rec.organism):
                continue
            info = context.tax_data.get(rec.organism)
            if not info:
                continue
            if tax_has_lineage(info, ["Bacteria", "Archaea"]):
                out.append(self.result(sample=rec.sample_id,
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
            if is_empty(rec.attr("specimen_voucher")) or is_empty(rec.organism):
                continue
            info = context.tax_data.get(rec.organism)
            if not info:
                continue
            # Bacteria(Cyanobacteria を除く) または unclassified sequences は不可
            is_bacteria = tax_has_lineage(info, ["Bacteria"]) and not tax_has_lineage(info, ["Cyanobacteria"])
            if is_bacteria or tax_has_lineage(info, ["unclassified sequences"]):
                out.append(self.result(sample=rec.sample_id,
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
            if is_empty(v):
                continue
            if not v.strip().lower().endswith("metagenome"):
                out.append(self.result(sample=rec.sample_id,
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
            if not pkg_startswith(rec.package, "MIMAG"):
                continue
            if rec.organism and "uncultured" in rec.organism.lower():
                out.append(self.result(sample=rec.sample_id,
                                       message=f"Organism containing 'uncultured' cannot be used for MIMAG. (organism: '{rec.organism}')"))
        return out


class BS_R0045(BsRule):
    rule_id = "BS_R0045"
    level = "warning"
    target = "organism, taxonomy_id"
    description = "Taxonomy error warning."
    requires_network = True

    def validate(self, submission, context):
        # organism が taxonomy で学名解決できる場合、学名へ補正＋taxonomy_id を補完（autofix）。
        # 解決できない（novel）場合は補正しない。
        out = []
        for rec in submission.records:
            if is_empty(rec.organism):
                continue
            info = context.tax_data.get(rec.organism)
            if not _resolved(info):
                continue
            sci = info.get("scientific_name")
            taxid = info.get("tax_id")
            need_name = bool(sci) and sci != rec.organism
            need_taxid = bool(taxid) and (
                is_empty(rec.taxonomy_id) or str(rec.taxonomy_id).strip() != str(taxid).strip())
            if not (need_name or need_taxid):
                continue
            detail = f"organism: '{rec.organism}'"
            if need_name:
                detail += f", Suggested: '{sci}'"
            if need_taxid:
                detail += f", taxonomy_id: '{taxid}'"
            msg = ("Taxonomy error warning. organism will be corrected to the scientific name "
                   f"and/or taxonomy id filled. ({detail})")
            out.append(self.autofix_result(
                sample=rec.sample_id, message=msg,
                kind="organism",
                old_value=rec.organism,
                new_value=(sci if need_name else None),
                new_taxid=(str(taxid) if need_taxid else None)))
        return out


class BS_R0105(BsRule):
    rule_id = "BS_R0105"
    level = "warning"
    target = "component_organism"
    description = "Taxonomy warning."
    requires_network = True

    def validate(self, submission, context):
        # component_organism を学名へ補正（autofix）。属性値置換（kind=attribute_value）。
        out = []
        for rec in submission.records:
            for v in rec.attr_values("component_organism"):
                if is_empty(v):
                    continue
                info = context.tax_data.get(v)
                if not _resolved(info):
                    continue
                sci = info.get("scientific_name")
                if sci and sci != v:
                    out.append(self.autofix_result(
                        sample=rec.sample_id,
                        message=f"Taxonomy warning. component_organism will be corrected to the scientific name. (Found: '{v}', Suggested: '{sci}')",
                        attribute="component_organism", old_value=v, new_value=sci))
        return out


class BS_R0015(BsRule):
    rule_id = "BS_R0015"
    level = "warning"
    target = "host"
    description = "Invalid host organism name."
    requires_network = True  # host 名の taxonomy 解決に tax_data を参照

    def validate(self, submission, context):
        # biosample の /host は **学名のみ許容**（ddbj /host より厳格）。
        # - "human" は "Homo sapiens" に特例 autofix。
        # - taxonomy で学名解決でき、入力が学名と異なる → 学名へ autofix。
        # - taxonomy に無い（＝生物名でない）host → warning（autofix なし）。
        out = []
        for rec in submission.records:
            host = rec.attr("host")
            if is_empty(host) or is_missing_value(host):
                continue
            if host.casefold() == "human":
                out.append(self.autofix_result(
                    sample=rec.sample_id,
                    message="Invalid host organism name. (host: 'human', Suggested: 'Homo sapiens')",
                    attribute="host", old_value=host, new_value="Homo sapiens"))
                continue
            info = context.tax_data.get(host)
            if not _resolved(info):
                # taxonomy 未解決＝学名でない → warning（autofix しない）
                out.append(self.result(sample=rec.sample_id,
                                       message=f"Invalid host organism name. Use a scientific name. (host: '{host}')"))
                continue
            sci = info.get("scientific_name")
            if sci and sci != host:
                out.append(self.autofix_result(
                    sample=rec.sample_id,
                    message=f"Invalid host organism name. (host: '{host}', Suggested: '{sci}')",
                    attribute="host", old_value=host, new_value=sci))
        return out


class BS_R0134(BsRule):
    rule_id = "BS_R0134"
    level = "warning"
    target = "organism, strain, isolate"
    description = "Non-identical identifiers among organism/strain/isolate."

    def validate(self, submission, context):
        # MIGS.ba.* で organism の "sp./bacterium/archaeon" 以降の識別子が strain/isolate と一致しない場合に警告。
        out = []
        for rec in submission.records:
            if not pkg_startswith(rec.package, "MIGS.ba"):
                continue
            org = rec.organism
            if is_empty(org):
                continue
            m = None
            for rx in _SP_KEYWORDS:
                m = rx.search(org)
                if m:
                    break
            if not m:
                continue
            suffix = org[m.end():].strip()
            if not suffix:
                continue
            strain = rec.attr("strain")
            isolate = rec.attr("isolate")
            if strain and not is_missing_value(strain) and suffix == strain:
                continue
            if isolate and not is_missing_value(isolate) and suffix == isolate:
                continue
            out.append(self.result(
                sample=rec.sample_id,
                message=(f"Non-identical identifiers among organism/strain/isolate. "
                         f"(organism: '{org}', strain: '{strain or ''}', isolate: '{isolate or ''}')")))
        return out


class BS_R0140(BsRule):
    rule_id = "BS_R0140"
    level = "warning"
    target = "organism"
    description = "Invalid taxonomy for genome sample."

    _PKG = ("Microbe", "Pathogen.cl", "Pathogen.env")

    def validate(self, submission, context):
        # Microbe / Pathogen.cl / Pathogen.env（完全一致）で organism が " sp." 終わりなら警告。
        out = []
        for rec in submission.records:
            if rec.package not in self._PKG:
                continue
            org = rec.organism
            if is_empty(org):
                continue
            if _SP_END.search(org):
                out.append(self.result(
                    sample=rec.sample_id,
                    message=f"Invalid taxonomy for genome sample. (organism: '{org}')"))
        return out


class BS_R0104(BsRule):
    rule_id = "BS_R0104"
    level = "error"
    target = "organism"
    description = "Invalid taxonomy for genome sample."
    requires_network = True  # taxonomy_id の rank 判定に tax_data を参照

    def validate(self, submission, context):
        # MIGS.ba/eu で organism が "genus sp." 形式のとき:
        #   taxonomy_id 未指定/無効 → 新規種の可能性でエラー（strain 名を促す）
        #   taxonomy_id あり & infraspecific（種以下）→ エラー
        #   taxonomy_id あり & 種より上位 → R0096 の領分としてスルー
        out = []
        for rec in submission.records:
            if not pkg_startswith(rec.package, *MIGS_BA_EU):
                continue
            org = rec.organism
            if is_empty(org):
                continue
            if not (org.lower().endswith("sp.") or _SP_INEX.search(org)):
                continue
            taxid = rec.taxonomy_id
            if is_empty(taxid) or str(taxid).strip() == "1":
                fire = True
            else:
                info = context.tax_data.get(org)
                # 種以下（infraspecific）なら error、上位/未解決ならスルー
                fire = bool(info) and bool(info.get("is_species_or_below"))
            if fire:
                out.append(self.result(
                    sample=rec.sample_id,
                    message=f"Invalid taxonomy for genome sample. (organism: '{org}')"))
        return out
