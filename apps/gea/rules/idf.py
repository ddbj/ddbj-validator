"""IDF ルール（GEA_C / COM / ED / EF / G / PB / PR / MAN / RC / REGEX）。

definitions.json の idf.* / value_formats を data 駆動で参照。
experiment_type（Both / Micro-array / HTS）は only_type（None/microarray/sequencing）で表現。
"""
import re
from apps.gea.rules.base import GeaRule, submission_type_value, null_values
from common.text import is_blank as _empty

_DATE_OK = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _idf(context):
    return (context.definitions or {}).get("idf", {})


# ---------------- Contact (Person) ----------------
class GEA_C0001(GeaRule):
    rule_id = "GEA_C0001"; level = "error"; target = "IDF/Person"
    description = "At least one contact must be specified."

    def validate(self, sub, context):
        if not sub.idf:
            return []
        return [] if any(not _empty(v) for v in sub.idf.get("Person Last Name")) else [self.result()]


class GEA_C0002(GeaRule):
    rule_id = "GEA_C0002"; level = "error"; target = "IDF/Person"
    description = "A contact must have last name specified."

    def validate(self, sub, context):
        if not sub.idf:
            return []
        # Person* のいずれかに値がある「人物列」で Last Name が空のものを検出
        keys = ["Person First Name", "Person Mid Initials", "Person Affiliation", "Person Roles"]
        last = sub.idf.get("Person Last Name")
        n = max([len(last)] + [len(sub.idf.get(k)) for k in keys])
        bad = 0
        for i in range(n):
            has_other = any(i < len(sub.idf.get(k)) and not _empty(sub.idf.get(k)[i]) for k in keys)
            has_last = i < len(last) and not _empty(last[i])
            if has_other and not has_last:
                bad += 1
        return [self.result(message=f"{self.description} ({bad} contact(s))")] if bad else []


class GEA_C0008(GeaRule):
    rule_id = "GEA_C0008"; level = "warning"; target = "IDF/Person"
    description = "A contact should have first name specified."

    def validate(self, sub, context):
        if not sub.idf:
            return []
        last = sub.idf.get("Person Last Name")
        first = sub.idf.get("Person First Name")
        bad = sum(1 for i in range(len(last)) if not _empty(last[i]) and (i >= len(first) or _empty(first[i])))
        return [self.result(message=f"{self.description} ({bad} contact(s))")] if bad else []


# ---------------- Comment / General ----------------
class GEA_COM0001(GeaRule):
    rule_id = "GEA_COM0001"; level = "error"; target = "IDF/Comment"
    description = "Non-empty value for 'Comment[Experiment Type]' must be provided in IDF."

    def validate(self, sub, context):
        if not sub.idf:
            return []
        return [] if not _empty(sub.idf.ae_experiment_type) else [self.result()]


class GEA_G0001(GeaRule):
    rule_id = "GEA_G0001"; level = "error"; target = "IDF/General"
    description = "Experiment title must be specified."

    def validate(self, sub, context):
        if not sub.idf:
            return []
        return [] if not _empty(sub.idf.first("Investigation Title")) else [self.result()]


class GEA_G0002(GeaRule):
    rule_id = "GEA_G0002"; level = "error"; target = "IDF/General"
    description = "Experiment description must be specified."

    def validate(self, sub, context):
        if not sub.idf:
            return []
        return [] if not _empty(sub.idf.first("Experiment Description")) else [self.result()]


class GEA_G0009(GeaRule):
    rule_id = "GEA_G0009"; level = "warning"; target = "IDF/General"
    description = "Experiment description should be between 20 and 4,000 characters including spaces."  # 2026-09-17

    def validate(self, sub, context):
        if not sub.idf:
            return []
        # 文字数は空白を含めて数える（前後の空白のみ除く）。空欄は G0008 の担当なのでここでは対象外。
        desc = sub.idf.first("Experiment Description").strip()
        mn = _idf(context).get("description_min_length", 20)
        mx = _idf(context).get("description_max_length", 4000)
        n = len(desc)
        return [self.result(message=f"{self.description} (Found: {n})")] if desc and (n < mn or n > mx) else []


class _DateFormat(GeaRule):
    _field = None
    def validate(self, sub, context):
        if not sub.idf:
            return []
        v = sub.idf.first(self._field).strip()
        return [self.result(message=f"{self.description} ('{v}')")] if v and not _DATE_OK.match(v) else []


class GEA_G0004(_DateFormat):
    rule_id = "GEA_G0004"; level = "error"; target = "IDF/General"; _field = "Date of Experiment"
    description = "Date of Experiment must be in 'YYYY-MM-DD' format."


class GEA_G0006(_DateFormat):
    rule_id = "GEA_G0006"; level = "error"; target = "IDF/General"; _field = "Public Release Date"
    description = "Experiment public release date must be in 'YYYY-MM-DD' format."


class GEA_G0015(_DateFormat):
    # Comment[Submission Date] も Public Release Date と同じ日付形式で検査する（2026-09-18）。
    rule_id = "GEA_G0015"; level = "error"; target = "IDF/General"; _field = "Comment[Submission Date]"
    description = "Submission date must be in 'YYYY-MM-DD' format."


class GEA_G0007(GeaRule):
    rule_id = "GEA_G0007"; level = "error"; target = "IDF/General"
    description = "Reference to the SDRF file must be specified."

    def validate(self, sub, context):
        if not sub.idf:
            return []
        return [] if not _empty(sub.idf.first("SDRF File")) else [self.result()]


class GEA_G0012(GeaRule):
    rule_id = "GEA_G0012"; level = "error"; target = "IDF/General"; only_type = "microarray"
    description = "Number of channel should be specified."

    def validate(self, sub, context):
        if not sub.idf:
            return []
        return [] if not _empty(sub.idf.number_of_channel) else [self.result()]


class GEA_G0013(GeaRule):
    """**deprecated**（validator に登録しない。2026-09-18）。

    additional file（`Comment[AdditionalFile:TXT]`）の仕組みを新 GEA で廃止したため、検査対象が無くなった。
    本番 DB の利用実績はテストアカウント dradev の 2 件のみだった。クラスは rule 表・参照のために残す。
    """
    deprecated = True
    rule_id = "GEA_G0013"; level = "error"; target = "IDF/General"
    description = "An additional file name must only contain alphanumeric characters, underscores, hyphens and dots."

    def validate(self, sub, context):
        if not sub.idf:
            return []
        out = []
        for v in sub.idf.get("Comment[AdditionalFile:TXT]"):
            if v and v.strip() and not re.fullmatch(r"[A-Za-z0-9._-]+", v.strip()):
                out.append(self.result(message=f"{self.description} ('{v}')"))
        return out


def _dway(context, sub):
    """その submission type の protocol 既定（`protocols.dway_defaults[<CV 値>]`）。無ければ None。"""
    st = submission_type_value(sub, context)
    if not st:
        return st, None
    return st, ((context.definitions or {}).get("protocols", {})
                .get("dway_defaults", {}) or {}).get(st)


def _protocol_types(sub):
    return {t.strip() for t in sub.idf.get("Protocol Type") if t.strip()}


class GEA_PR0018(GeaRule):
    """submission type ごとに **raw の有無に関係なく必須**の protocol type が IDF に揃っているか。

    一覧は `protocols.dway_defaults[<type>].required`。raw があるときだけ必須のものは
    `GEA_PR0019` が別に見る（ルール表の Skip 列で管理を分けるため 2 本にしてある）。

    submission type が分からない／その type の定義が無いときは検査しない。
    """
    rule_id = "GEA_PR0018"; level = "error"; target = "IDF/Protocol"
    description = "Required Protocol Type is missing for the specified Submission Type."

    def validate(self, sub, context):
        if not sub.idf:
            return []
        st, dw = _dway(context, sub)
        required = (dw or {}).get("required")
        if not required:
            return []
        missing = [t for t in required if t not in _protocol_types(sub)]
        if not missing:
            return []
        return [self.result(message=f"{self.description} "
                                    f"(Submission Type: '{st}', missing: {', '.join(missing)})")]


class GEA_PR0019(GeaRule):
    """**raw データがあるときだけ必須**の protocol type が IDF に揃っているか。

    一覧は `protocols.dway_defaults[<type>].required_with_raw`（Microarray の Labeling /
    Hybridization / Scanning、Sequencing の Library construction / Sequencing）。
    raw が無い submission では出さない（`skip_conditions["raw-less"]` に登録。判定は `GeaRule.applies`）。
    Xenium は raw が無い形を想定しないので `required_with_raw` は空＝このルールは何も出さない。
    """
    rule_id = "GEA_PR0019"; level = "error"; target = "IDF/Protocol"
    description = "Protocol Type required for raw data is missing for the specified Submission Type."

    def validate(self, sub, context):
        if not sub.idf:
            return []
        st, dw = _dway(context, sub)
        required = (dw or {}).get("required_with_raw")
        if not required:
            return []
        missing = [t for t in required if t not in _protocol_types(sub)]
        if not missing:
            return []
        return [self.result(message=f"{self.description} "
                                    f"(Submission Type: '{st}', missing: {', '.join(missing)})")]


class GEA_PR0017(GeaRule):
    """その submission type では使わない protocol type が IDF に書かれていないか。

    `required + required_with_raw + optional` のどれにも無い値を報告する。
    - CV 外の値は **除外**（`GEA_PR0020` が別に拾うので二重に出さない）。
    - `allow_any_protocol` が立っている type（Other。何が来るか分からない）では検査しない。
    """
    rule_id = "GEA_PR0017"; level = "error"; target = "SDRF/Protocol"
    description = "Protocol Type is not used in the specified Submission Type."

    def validate(self, sub, context):
        if not sub.idf:
            return []
        st, dw = _dway(context, sub)
        if not dw or dw.get("allow_any_protocol"):
            return []
        allowed = set(dw.get("required", [])) | set(dw.get("required_with_raw", [])) | set(dw.get("optional", []))
        cv = set(((context.definitions or {}).get("controlled_terms", {})
                  .get("idf_protocol", {}).get("error", {}) or {}).get("Protocol Type", []))
        bad = sorted({t for t in _protocol_types(sub) if t in cv and t not in allowed})
        if not bad:
            return []
        return [self.result(message=f"{self.description} "
                                    f"(Submission Type: '{st}', Protocol Type: {', '.join(bad)})")]


class GEA_PR0007(GEA_PR0017):
    """**deprecated**（validator に登録しない。2026-09-20）。

    実装時に `GEA_PR0007` を割り当てたが、ルール表では同じ検査に `GEA_PR0017` が
    採番されていた。GEA 側の指示で **`GEA_PR0017` に統一**し、こちらは deprecated にした。
    クラスは rule 表・参照のために残す。
    """
    deprecated = True
    rule_id = "GEA_PR0007"


class GEA_PR0020(GeaRule):
    """`Protocol Type` の統制語彙。

    CV は `controlled_terms.idf_protocol.error` に置く。`controlled_terms.idf.*` に置くと
    `GEA_COM0002` / `GEA_COM0003` が拾ってしまい、**項目単位で level と internal ignore を
    決められない**ため（COM0002 は ignore ではないので取り込みを止めてしまう）。
    """
    rule_id = "GEA_PR0020"; level = "error"; target = "IDF/Protocol"
    description = "Value is not in controlled terms."

    def validate(self, sub, context):
        if not sub.idf:
            return []
        cv = ((context.definitions or {}).get("controlled_terms", {})
              .get("idf_protocol", {}).get("error", {}) or {})
        out = []
        for field_name, allowed in cv.items():
            for v in sub.idf.get(field_name):
                if v.strip() and v.strip() not in allowed:
                    out.append(self.result(message=f"{self.description} ({field_name}: '{v.strip()}')"))
        return out


class GEA_G0016(GeaRule):
    """`Comment[Submission Type]` と `Comment[Experiment Type]` の整合。

    submission type ごとに選べる experiment type は `idf.allowed_experiment_types` に定義してある。
    submission type が分からない（IDF にも DB にも無い）ときや、その type の選択肢が定義されていない
    ときは検査しない（投稿者に直しようが無いため）。
    """
    rule_id = "GEA_G0016"; level = "error"; target = "IDF"
    description = "Experiment Type is not allowed for the specified Submission Type."

    def validate(self, sub, context):
        if not sub.idf:
            return []
        st = submission_type_value(sub, context)
        allowed = ((context.definitions or {}).get("idf", {})
                   .get("allowed_experiment_types", {}) or {}).get(st)
        if not st or not allowed:
            return []
        return [self.result(message=f"{self.description} "
                                    f"(Submission Type: '{st}', Experiment Type: '{v.strip()}')")
                for v in sub.idf.get("Comment[Experiment Type]")
                if v.strip() and v.strip() not in allowed]


# ---------------- Experimental design / variable ----------------
class GEA_ED0001(GeaRule):
    rule_id = "GEA_ED0001"; level = "error"; target = "IDF/ExperimentalDesign"; only_type = "microarray"
    description = "Experiment must have at least one experimental design specified."

    def validate(self, sub, context):
        if not sub.idf:
            return []
        return [] if any(not _empty(v) for v in sub.idf.get("Experimental Design")) else [self.result()]


class GEA_EF0001(GeaRule):
    rule_id = "GEA_EF0001"; level = "error"; target = "IDF/ExperimentalVariable"
    description = "An experiment must have at least one experimental variable specified."

    def validate(self, sub, context):
        if not sub.idf:
            return []
        return [] if any(not _empty(v) for v in sub.idf.get("Experimental Factor Name")) else [self.result()]


class GEA_EF0003(GeaRule):
    rule_id = "GEA_EF0003"; level = "warning"; target = "IDF/ExperimentalVariable"
    description = "An experimental variable should have a type specified."

    def validate(self, sub, context):
        if not sub.idf:
            return []
        names = sub.idf.get("Experimental Factor Name")
        types = sub.idf.get("Experimental Factor Type")
        bad = sum(1 for i in range(len(names)) if not _empty(names[i]) and (i >= len(types) or _empty(types[i])))
        return [self.result(message=f"{self.description} ({bad})")] if bad else []


# ---------------- Publication ----------------
class GEA_PB0002(GeaRule):
    rule_id = "GEA_PB0002"; level = "error"; target = "IDF/Publication"
    description = "PubMed ID must be numeric."

    def validate(self, sub, context):
        if not sub.idf:
            return []
        nulls = null_values(context)
        out = []
        for v in sub.idf.get("PubMed ID"):
            if v and v.strip() and v.strip() not in nulls and not re.fullmatch(r"\d+", v.strip()):
                out.append(self.result(message=f"{self.description} ('{v}')"))
        return out


# ---------------- Protocol ----------------
class GEA_PR0001(GeaRule):
    rule_id = "GEA_PR0001"; level = "error"; target = "IDF/Protocol"
    description = "At least one protocol must be used in an experiment."

    def validate(self, sub, context):
        if not sub.idf:
            return []
        return [] if any(not _empty(v) for v in sub.idf.get("Protocol Name")) else [self.result()]


class GEA_PR0002(GeaRule):
    rule_id = "GEA_PR0002"; level = "error"; target = "IDF/Protocol"
    description = "Name of a protocol must be specified."

    def validate(self, sub, context):
        if not sub.idf:
            return []
        protos = sub.idf.protocols()
        bad = sum(1 for p in protos if _empty(p["Protocol Name"]) and not _empty(p["Protocol Type"]))
        return [self.result(message=f"{self.description} ({bad} Protocol{'s' if bad != 1 else ''})")] if bad else []


class GEA_PR0003(GeaRule):
    rule_id = "GEA_PR0003"; level = "error"; target = "IDF/Protocol"
    description = "A protocol type must be specified."

    def validate(self, sub, context):
        if not sub.idf:
            return []
        protos = sub.idf.protocols()
        bad = sum(1 for p in protos if not _empty(p["Protocol Name"]) and _empty(p["Protocol Type"]))
        return [self.result(message=f"{self.description} ({bad} Protocol{'s' if bad != 1 else ''})")] if bad else []


class GEA_PR0005(GeaRule):
    rule_id = "GEA_PR0005"; level = "error"; target = "IDF/Protocol"
    description = "Description of a protocol should be specified."

    def validate(self, sub, context):
        if not sub.idf:
            return []
        protos = sub.idf.protocols()
        bad = sum(1 for p in protos if not _empty(p["Protocol Name"]) and _empty(p["Protocol Description"]))
        return [self.result(message=f"{self.description} ({bad} Protocol{'s' if bad != 1 else ''})")] if bad else []


class GEA_PR0006(GeaRule):
    rule_id = "GEA_PR0006"; level = "warning"; target = "IDF/Protocol"
    description = "Description of a protocol should be over 30 characters long."  # 2026-09-17 100→30

    def validate(self, sub, context):
        if not sub.idf:
            return []
        mn = _idf(context).get("protocol_description_min_length", 30)
        protos = sub.idf.protocols()
        bad = sum(1 for p in protos if p["Protocol Description"] and 0 < len(p["Protocol Description"].strip()) < mn)
        return [self.result(message=f"{self.description} ({bad} Protocol{'s' if bad != 1 else ''})")] if bad else []


class _ProtocolRequired(GeaRule):
    """submission type ごとの必須 protocol type が Protocol Type 群に含まれるか。"""
    _ptype = None
    level = "error"; target = "IDF/Protocol"

    def validate(self, sub, context):
        if not sub.idf:
            return []
        have = {t.strip() for t in sub.idf.get("Protocol Type") if t.strip()}
        return [] if self._ptype in have else [self.result()]


class GEA_PR0013(_ProtocolRequired):
    """**deprecated**（validator に登録しない。2026-09-18）。

    submission type ごとの必須 protocol type の検査は **GEA_PR0018 / GEA_PR0019** に集約した
    （必須の一覧は `protocols.dway_defaults` の `required` / `required_with_raw`）。
    2026-09-18 は GEA_COM0005 に集約していたが、2026-09-19 に PR 系へ付け替えた。
    クラスは rule 表・参照のために残す。
    """
    deprecated = True
    rule_id = "GEA_PR0013"; _ptype = "Sample collection protocol"
    description = "Sample collection protocol is required for submissions."


class GEA_PR0014(_ProtocolRequired):
    """**deprecated**（validator に登録しない。2026-09-18）。

    submission type ごとの必須 protocol type の検査は **GEA_PR0018 / GEA_PR0019** に集約した
    （必須の一覧は `protocols.dway_defaults` の `required` / `required_with_raw`）。
    2026-09-18 は GEA_COM0005 に集約していたが、2026-09-19 に PR 系へ付け替えた。
    クラスは rule 表・参照のために残す。
    """
    deprecated = True
    rule_id = "GEA_PR0014"; _ptype = "Extraction protocol"
    description = "Extraction protocol is required for submissions."


class GEA_PR0015(_ProtocolRequired):
    """**deprecated**（validator に登録しない。2026-09-18）。

    submission type ごとの必須 protocol type の検査は **GEA_PR0018 / GEA_PR0019** に集約した
    （必須の一覧は `protocols.dway_defaults` の `required` / `required_with_raw`）。
    2026-09-18 は GEA_COM0005 に集約していたが、2026-09-19 に PR 系へ付け替えた。
    クラスは rule 表・参照のために残す。
    """
    deprecated = True
    rule_id = "GEA_PR0015"; _ptype = "Data processing protocol"
    description = "Data processing protocol is required for submissions."


class GEA_PR0010(_ProtocolRequired):
    """**deprecated**（validator に登録しない。2026-09-18）。

    submission type ごとの必須 protocol type の検査は **GEA_PR0018 / GEA_PR0019** に集約した
    （必須の一覧は `protocols.dway_defaults` の `required` / `required_with_raw`）。
    2026-09-18 は GEA_COM0005 に集約していたが、2026-09-19 に PR 系へ付け替えた。
    クラスは rule 表・参照のために残す。
    """
    deprecated = True
    rule_id = "GEA_PR0010"; only_type = "microarray"; _ptype = "Labeling protocol"
    description = "Labeling protocol is required for Micro-array submissions."


class GEA_PR0011(_ProtocolRequired):
    """**deprecated**（validator に登録しない。2026-09-18）。

    submission type ごとの必須 protocol type の検査は **GEA_PR0018 / GEA_PR0019** に集約した
    （必須の一覧は `protocols.dway_defaults` の `required` / `required_with_raw`）。
    2026-09-18 は GEA_COM0005 に集約していたが、2026-09-19 に PR 系へ付け替えた。
    クラスは rule 表・参照のために残す。
    """
    deprecated = True
    rule_id = "GEA_PR0011"; only_type = "microarray"; _ptype = "Hybridization protocol"
    description = "Hybridization protocol is required for Micro-array submissions."


class GEA_PR0012(_ProtocolRequired):
    """**deprecated**（validator に登録しない。2026-09-18）。

    submission type ごとの必須 protocol type の検査は **GEA_PR0018 / GEA_PR0019** に集約した
    （必須の一覧は `protocols.dway_defaults` の `required` / `required_with_raw`）。
    2026-09-18 は GEA_COM0005 に集約していたが、2026-09-19 に PR 系へ付け替えた。
    クラスは rule 表・参照のために残す。
    """
    deprecated = True
    rule_id = "GEA_PR0012"; only_type = "microarray"; _ptype = "Scanning protocol"
    description = "Scanning protocol is required for Micro-array submissions."


class GEA_PR0008(_ProtocolRequired):
    """**deprecated**（validator に登録しない。2026-09-18）。

    submission type ごとの必須 protocol type の検査は **GEA_PR0018 / GEA_PR0019** に集約した
    （必須の一覧は `protocols.dway_defaults` の `required` / `required_with_raw`）。
    2026-09-18 は GEA_COM0005 に集約していたが、2026-09-19 に PR 系へ付け替えた。
    クラスは rule 表・参照のために残す。
    """
    deprecated = True
    rule_id = "GEA_PR0008"; only_type = "sequencing"; _ptype = "Library construction protocol"
    description = "Library construction protocol is required for HTS submissions."


class GEA_PR0009(_ProtocolRequired):
    """**deprecated**（validator に登録しない。2026-09-18）。

    submission type ごとの必須 protocol type の検査は **GEA_PR0018 / GEA_PR0019** に集約した
    （必須の一覧は `protocols.dway_defaults` の `required` / `required_with_raw`）。
    2026-09-18 は GEA_COM0005 に集約していたが、2026-09-19 に PR 系へ付け替えた。
    クラスは rule 表・参照のために残す。
    """
    deprecated = True
    rule_id = "GEA_PR0009"; only_type = "sequencing"; _ptype = "Sequencing protocol"
    description = "Sequencing protocol is required for HTS submissions."


# ---------------- 一意性 / 未定義 / CV / 形式 ----------------
class GEA_RC0001(GeaRule):
    rule_id = "GEA_RC0001"; level = "error"; target = "IDF"
    description = "Predefined comment fields must be unique."

    def validate(self, sub, context):
        if not sub.idf:
            return []
        dup = sorted(set(sub.idf.duplicate_fields))
        return [self.result(message=f"{self.description} ({', '.join(dup)})")] if dup else []


class GEA_MAN0001(GeaRule):
    rule_id = "GEA_MAN0001"; level = "error"; target = "IDF"; only_type = "microarray"
    description = "Mandatory field is required."

    def validate(self, sub, context):
        if not sub.idf:
            return []
        req = _idf(context).get("required_microarray", [])
        miss = [f for f in req if _empty(" ".join(sub.idf.get(f)))]
        return [self.result(message=f"{self.description} ({', '.join(miss)})")] if miss else []


class _CvBase(GeaRule):
    _level_key = None
    def validate(self, sub, context):
        if not sub.idf:
            return []
        cv = ((context.definitions or {}).get("controlled_terms", {}).get("idf", {}).get(self._level_key, {}))
        out = []
        for field_name, allowed in cv.items():
            for v in sub.idf.get(field_name):
                if v and v.strip() and v.strip() not in allowed:
                    out.append(self.result(message=f"{self.description} ({field_name}: '{v}')"))
        return out


class GEA_CV_ERR(_CvBase):
    rule_id = "GEA_COM0002"; level = "error"; target = "IDF"; _level_key = "error"
    description = "Value is not in controlled terms."


class GEA_CV_WARN(_CvBase):
    rule_id = "GEA_COM0003"; level = "warning"; target = "IDF"; _level_key = "warning"
    description = "Value is not in controlled terms."


class _IdfRegex(GeaRule):
    """value_formats のうち IDF 側フィールドの形式検査。"""
    rule_id = "GEA_REGEX0001"; level = "error"; target = "IDF"
    _fields = ()
    description = "Format Error"

    def validate(self, sub, context):
        if not sub.idf:
            return []
        fmts = (context.definitions or {}).get("value_formats", {})
        nulls = null_values(context)
        out = []
        for f in self._fields:
            pat = fmts.get(f)
            if not pat:
                continue
            for v in sub.idf.get(f):
                if v and v.strip() and v.strip() not in nulls and not re.fullmatch(pat, v.strip()):
                    out.append(self.result(message=f"Format Error '{f}' ('{v}')"))
        return out


class GEA_REGEX0001(_IdfRegex):
    rule_id = "GEA_REGEX0001"; _fields = ("Comment[GEA Accession]",)
    description = "Format Error 'Comment[GEA Accession]'"


class GEA_REGEX0002(_IdfRegex):
    """**deprecated**（validator に登録しない。2026-09-19）。

    新 GEA は protocol に accession（P-GEAD-n）を発行せず、`Protocol Name` は
    `Sample collection` のような**名前**になる（MetaboBank と同じ）。`value_formats` から
    `Protocol Name` を外したので検査対象が無くなった。名前で参照が解決するかは `GEA_REF0001` が見る。
    """
    deprecated = True
    rule_id = "GEA_REGEX0002"; _fields = ("Protocol Name",)
    description = "Format Error 'Protocol Name'"


class GEA_REGEX0003(_IdfRegex):
    rule_id = "GEA_REGEX0003"; _fields = ("Comment[BioProject]",)
    description = "Format Error 'Comment[BioProject]'"


class GEA_REGEX0004(_IdfRegex):
    rule_id = "GEA_REGEX0004"; _fields = ("Comment[Secondary Accession]",)
    description = "Format Error 'Comment[Secondary Accession]'"
