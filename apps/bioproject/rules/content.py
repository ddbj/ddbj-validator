"""BioProject 内容ルール（Step3）。

- BP_R0004: 提出済み project と title＋description が両方重複 → warning（要 DB/account）。
- BP_R0006: description が 20-4000 文字（inclusive）でない → error（INSDC min spec）。
- BP_R0005: title が 20-250 文字（inclusive）でない → error（INSDC min spec。旧 BP_R0005 廃止 ID を再利用）。
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
from apps.bioproject.defs import formats, compiled

_EMPTY = (None, "")


def _empty(v):
    return v is None or not str(v).strip()


def _len_range(context, key, default_min, default_max):
    """definitions.formats から (min, max) を取得（無ければ default）。"""
    f = ((context.definitions or {}).get("formats", {}) if context else {}) or formats()
    spec = f.get(key) or {}
    return spec.get("min", default_min), spec.get("max", default_max)


class BP_R0004(BpRule):
    """提出済み project と title＋description が両方一致 → warning。

    account の登録済み（accession 付き）project 一覧を context.project_names（DB 取得）から得て、
    title と description の両方が一致するものがあれば重複とみなす。登録途中（accession 無し）は対象外。
    """
    rule_id = "BP_R0004"
    level = "warning"
    requires_rdb = True
    requires_auth = True
    target = "Title, Description"
    description = "Both project title and description are duplicated with the submitted projects. Duplicated project should not be submitted."

    def validate(self, submission, context):
        out = []
        names = getattr(context, "project_names", None)
        if not names:
            return out
        self_sid = (getattr(context, "self_submission_id", None) or "")
        for rec in submission.records:
            title = (rec.title or "").strip()
            desc = (rec.description or "").strip()
            if not title or not desc:
                continue
            self_acc = (rec.accession or "").strip()
            for (t, d, acc, sid) in names:
                if (t or "").strip() != title or (d or "").strip() != desc:
                    continue
                # 自己除外: 検証対象自身の accession / PSUB と一致する既存 project は重複としない
                if self_acc and acc and acc == self_acc:
                    continue
                if self_sid and sid and sid == self_sid:
                    continue
                out.append(self.result(sample=rec.label, message=self.description))
                break
        return out


class BP_R0006(BpRule):
    rule_id = "BP_R0006"
    level = "error"
    target = "Description"
    description = ("Project description must be between 20 and 4000 characters in length, "
                   "inclusive (including spaces).")

    def validate(self, submission, context):
        out = []
        lo, hi = _len_range(context, "description_length", 20, 4000)
        for rec in submission.records:
            n = len((rec.description or "").strip())
            if not (lo <= n <= hi):
                out.append(self.result(sample=rec.label,
                                       message=f"{self.description} (Found: {n})"))
        return out


class BP_R0005(BpRule):
    # 旧 BP_R0005（title==description。廃止）の ID を再利用し、title 文字数制限（min spec）に割り当て。
    rule_id = "BP_R0005"
    level = "error"
    target = "Title"
    description = ("Project title must be between 20 and 250 characters in length, "
                   "inclusive (including spaces).")

    def validate(self, submission, context):
        out = []
        lo, hi = _len_range(context, "title_length", 20, 250)
        for rec in submission.records:
            n = len((rec.title or "").strip())
            if not (lo <= n <= hi):
                out.append(self.result(sample=rec.label,
                                       message=f"{self.description} (Found: {n})"))
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


class BP_R0014(BpRule):
    rule_id = "BP_R0014"
    level = "warning"
    target = "Publication"
    description = "Invalid publication identifier, enter valid pubmed id, pmc id or DOI."

    def validate(self, submission, context):
        out = []
        # publication id: PubMed(数字) / PMC(PMC 数字) / DOI(10.xxxx/...) / URL
        f = (context.definitions or {}).get("formats", {}) if context else formats()
        pub_re = compiled(f.get("publication_id", r"^(\d+|PMC\d+|10\.\d+/\S+|https?://\S+)$"), re.IGNORECASE)
        for rec in submission.records:
            for pub in rec.publications:
                if pub.id and not pub_re.match(pub.id.strip()):
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


class BP_R0070(BpRule):
    """管理語彙（cv_terms）に無い値 → error（旧 BP_R0070 title 長は BP_R0005 へ移設済み・ID 再利用）。

    検査対象フィールド（xxxxx）: sample_scope / material / capture / method_type / subtype /
    data_type / db_type。definitions.json の cv_terms（Core.xsd 由来）と照合する。
    """
    rule_id = "BP_R0070"
    level = "error"
    target = "controlled vocabulary"
    description = "Value is not defined in controlled vocabulary."

    def validate(self, submission, context):
        cv = context.cv_terms or {}
        out = []
        for rec in submission.records:
            checks = [
                ("sample_scope", rec.sample_scope, cv.get("sample_scope")),
                ("material", rec.material, cv.get("material")),
                ("capture", rec.capture, cv.get("capture")),
                ("method_type", rec.method_type, cv.get("method_type")),
                ("subtype", rec.top_admin_subtype, cv.get("top_admin_subtype")),
            ]
            for name, val, allowed in checks:
                v = (val or "").strip()
                if v and allowed and v not in allowed:
                    out.append(self.result(sample=rec.label, target=name,
                                           message=f"Value is not defined in controlled vocabulary ({name}). (Found: '{v}')"))
            for d in rec.data_entries:   # Objectives/Data@data_type
                v = (d.get("type") or "").strip()
                if v and cv.get("data_type") and v not in cv["data_type"]:
                    out.append(self.result(sample=rec.label, target="data_type",
                                           message=f"Value is not defined in controlled vocabulary (data_type). (Found: '{v}')"))
            for pub in rec.publications:
                v = (pub.db_type or "").strip()
                if v and cv.get("db_type") and v not in cv["db_type"]:
                    out.append(self.result(sample=rec.label, target="db_type",
                                           message=f"Value is not defined in controlled vocabulary (db_type). (Found: '{v}')"))
        return out
