"""BioProject 内容ルール（Step3。DB 非依存）。

- BP_R0005: title と description が同一 → error。
- BP_R0006: description が 100 文字未満 → error（present のときのみ）。
- BP_R0007: Relevance の 'Other' に説明が無い → error。
- BP_R0008: ProjectTypeTopAdmin subtype=eOther で DescriptionSubtypeOther が無い → error。
- BP_R0009/0010/0011: Target の sample_scope/material/capture=eOther で Target/Description が無い → error。
- BP_R0012: Method method_type=eOther で Method 本文が無い → error。
- BP_R0013: Data data_type=eOther で Data 本文が無い → error。
- BP_R0014: publication identifier（PubMed/PMC/DOI）が不正 → warning。
- BP_R0015: publication に id も reference も無い → error。
- BP_R0019: sample_scope=eMultispecies で organism 説明（Target/Description）が無い → error。
- BP_R0040: ProjectTypeTopSingleOrganism は不正な project type → error。
"""
import re
from apps.bioproject.rules.base import BpRule

_EMPTY = (None, "")


def _empty(v):
    return v is None or not str(v).strip()


class BP_R0005(BpRule):
    rule_id = "BP_R0005"
    level = "error"
    target = "Title, Description"
    description = "Project title and description are identical. Please provide more detailed description."

    def validate(self, submission, context):
        out = []
        for rec in submission.records:
            if rec.title and rec.description and rec.title.strip() == rec.description.strip():
                out.append(self.result(sample=rec.label, message=self.description))
        return out


class BP_R0006(BpRule):
    rule_id = "BP_R0006"
    level = "error"
    target = "Description"
    description = "Project description is too short. Description text must be more than 100 characters."

    def validate(self, submission, context):
        out = []
        for rec in submission.records:
            if rec.description is not None and len(rec.description.strip()) < 100:
                out.append(self.result(sample=rec.label, message=self.description))
        return out


# (attribute の説明必須系: eOther を選んだら対応する説明要素が必須) をデータ駆動で表現。
# 各 (rule_id, 条件, 説明取得, level, target, message) をまとめる。
class _OtherDescrRule(BpRule):
    """eOther を選んだフィールドに説明が無ければ error、の共通実装。"""
    level = "error"
    _cond = None      # rec -> bool（eOther が選ばれているか）
    _descr = None     # rec -> 説明文字列 or None

    def validate(self, submission, context):
        out = []
        for rec in submission.records:
            if self._cond(rec) and _empty(self._descr(rec)):
                out.append(self.result(sample=rec.label, message=self.description))
        return out


class BP_R0007(_OtherDescrRule):
    rule_id = "BP_R0007"
    target = "Relevance"
    description = "Text description for the Relevance 'Other' is not provided. Please provide description of the Relevance 'Other'."
    # Relevance/Other 要素があり text が空 → 説明無し
    _cond = staticmethod(lambda rec: rec.relevance_present and (rec.raw is not None) and _relevance_other_selected(rec))
    _descr = staticmethod(lambda rec: rec.relevance_other)


def _relevance_other_selected(rec):
    # Relevance/Other 要素が XML に存在するか（text の有無に関わらず）。存在＝Other を選択とみなす。
    r = rec.raw.find("./ProjectDescr/Relevance/Other") if rec.raw is not None else None
    return r is not None


class BP_R0008(_OtherDescrRule):
    rule_id = "BP_R0008"
    target = "subtype"
    description = "Text description for the subtype 'Other' is not provided. Please provide DescriptionSubtypeOther."
    _cond = staticmethod(lambda rec: (rec.top_admin_subtype or "") == "eOther")
    _descr = staticmethod(lambda rec: rec.subtype_other_descr)


class BP_R0009(_OtherDescrRule):
    rule_id = "BP_R0009"
    target = "sample_scope"
    description = "Text description for the sample_scope 'Other' is not provided. Please provide description of target."
    _cond = staticmethod(lambda rec: (rec.sample_scope or "") == "eOther")
    _descr = staticmethod(lambda rec: rec.target_description)


class BP_R0010(_OtherDescrRule):
    rule_id = "BP_R0010"
    target = "material"
    description = "Text description for the material 'Other' is not provided. Please provide description of target."
    _cond = staticmethod(lambda rec: (rec.material or "") == "eOther")
    _descr = staticmethod(lambda rec: rec.target_description)


class BP_R0011(_OtherDescrRule):
    rule_id = "BP_R0011"
    target = "capture"
    description = "Text description for the capture 'Other' is not provided. Please provide description of target."
    _cond = staticmethod(lambda rec: (rec.capture or "") == "eOther")
    _descr = staticmethod(lambda rec: rec.target_description)


class BP_R0012(_OtherDescrRule):
    rule_id = "BP_R0012"
    target = "method_type"
    description = "Text description for the method_type 'Other' is not provided. Please provide description of method."
    _cond = staticmethod(lambda rec: (rec.method_type or "") == "eOther")
    _descr = staticmethod(lambda rec: rec.method_text)


class BP_R0013(BpRule):
    rule_id = "BP_R0013"
    level = "error"
    target = "data_type"
    description = "Text description for the data_type 'Other' is not provided. Please provide description of data."

    def validate(self, submission, context):
        out = []
        for rec in submission.records:
            for d in rec.data_entries:
                if (d.get("type") or "") == "eOther" and _empty(d.get("text")):
                    out.append(self.result(sample=rec.label, message=self.description))
                    break
        return out


class BP_R0019(BpRule):
    rule_id = "BP_R0019"
    level = "error"
    target = "sample_scope, organism"
    description = "Organism description is required when sample scope is multi-species."

    def validate(self, submission, context):
        out = []
        for rec in submission.records:
            if (rec.sample_scope or "") == "eMultispecies" and _empty(rec.target_description):
                out.append(self.result(sample=rec.label, message=self.description))
        return out


# publication id: PubMed(数字) / PMC(PMC 数字) / DOI(10.xxxx/...) / URL
_PUB_RE = re.compile(r"^(\d+|PMC\d+|10\.\d+/\S+|https?://\S+)$", re.IGNORECASE)


class BP_R0014(BpRule):
    rule_id = "BP_R0014"
    level = "warning"
    target = "Publication"
    description = "Invalid publication identifier, enter valid pubmed id, pmc id or DOI."

    def validate(self, submission, context):
        out = []
        for rec in submission.records:
            for pub in rec.publications:
                if pub.id and not _PUB_RE.match(pub.id.strip()):
                    out.append(self.result(sample=rec.label,
                                           message=f"Invalid publication identifier. (Found: '{pub.id}')"))
        return out


class BP_R0015(BpRule):
    rule_id = "BP_R0015"
    level = "error"
    target = "Publication"
    description = "Publication reference is not provided. Please provide reference in free-text when id is not available."

    def validate(self, submission, context):
        out = []
        for rec in submission.records:
            for pub in rec.publications:
                if _empty(pub.id) and _empty(pub.reference):
                    out.append(self.result(sample=rec.label, message=self.description))
                    break
        return out


class BP_R0040(BpRule):
    rule_id = "BP_R0040"
    level = "error"
    target = "ProjectType"
    description = "ProjectTypeTopSingleOrganism is invalid project type."

    def validate(self, submission, context):
        out = []
        for rec in submission.records:
            if rec.project_kind == "single_organism":
                out.append(self.result(sample=rec.label, message=self.description))
        return out
