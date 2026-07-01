"""voucher 系属性（culture_collection / specimen_voucher / bio_material）の形式・機関コード検証。

- BS_R0113/0116/0118: 形式（"<institution-code>:[<collection-code>:]<id>"）。culture_collection は institution-code 必須、
  specimen_voucher / bio_material は institution-code 任意。
- BS_R0114/0117/0119: institution-code が NCBI BioCollections（coll_dump）に登録されているか。
  culture_collection=error(R0114)、specimen_voucher=warning(R0117)、bio_material=warning(R0119)。
機関コード集合は context.institution_codes（common/resources/coll_dump.txt）。
"""
from apps.biosample.rules.base import BsRule
from apps.biosample.rules._util import is_empty, is_missing_value


def _segments(v):
    return [s.strip() for s in v.split(":")]


def _malformed(v):
    """空セグメント（"::" や先頭/末尾コロン）があれば True。"""
    segs = _segments(v)
    return any(s == "" for s in segs)


def _institution_code(v):
    """institution-code（最初の ':' より前）。コロンが無ければ None（＝機関コードなし）。"""
    return _segments(v)[0] if ":" in v else None


class _VoucherBase(BsRule):
    attr_name = ""
    require_institution = False   # culture_collection は institution-code 必須
    format_rule = ""
    inst_rule = ""
    inst_level = "error"

    def validate(self, submission, context):
        out = []
        for rec in submission.records:
            v = rec.attr(self.attr_name)
            if is_empty(v) or is_missing_value(v):
                continue
            val = v.strip()
            # 形式チェック
            if self.require_institution and ":" not in val:
                out.append(self._res(rec, self.format_rule, self.level,
                                     f"Invalid {self.attr_name} format. (Found: '{val}')"))
                continue
            if _malformed(val):
                out.append(self._res(rec, self.format_rule, self.level,
                                     f"Invalid {self.attr_name} format. (Found: '{val}')"))
                continue
            # 機関コード登録チェック
            code = _institution_code(val)
            if code and code.lower() not in context.institution_codes:
                out.append(self._res(rec, self.inst_rule, self.inst_level,
                                     f"Institution code '{code}' is not registered in NCBI BioCollections."))
        return out

    def _res(self, rec, rule_id, level, message):
        return {"rule_id": rule_id, "level": level, "target": self.attr_name,
                "sample": (rec.sample_name or rec.accession), "message": message}


class CultureCollectionValidator(_VoucherBase):
    rule_id = "BS_R0113"
    level = "error"
    attr_name = "culture_collection"
    require_institution = True
    format_rule = "BS_R0113"
    inst_rule = "BS_R0114"
    inst_level = "error"


class SpecimenVoucherValidator(_VoucherBase):
    rule_id = "BS_R0116"
    level = "error"
    attr_name = "specimen_voucher"
    require_institution = False
    format_rule = "BS_R0116"
    inst_rule = "BS_R0117"
    inst_level = "warning"


class BioMaterialValidator(_VoucherBase):
    rule_id = "BS_R0118"
    level = "error"
    attr_name = "bio_material"
    require_institution = False
    format_rule = "BS_R0118"
    inst_rule = "BS_R0119"
    inst_level = "warning"
