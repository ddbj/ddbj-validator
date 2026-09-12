"""IDF ルール（MB_IR）。definitions.json の idf.* を data 駆動で参照。"""
import datetime
import re
from common.jst import today as jst_today
from apps.metabobank.rules.base import (MbRule, null_values, null_values_not_recommended,
                                        normalize_null, is_valid_related_study)

_DATE_OK = re.compile(r"^20\d{2}-\d{2}-\d{2}$")
_DATE_FIELDS = ("Public Release Date", "Comment[Submission Date]", "Comment[Last Update Date]", "Date of Experiment")
# 未来日判定の対象。Public Release Date は hold 中の公開予定日、Submission/Last Update Date は
# 登録システムが付ける日付で、いずれも未来日が正当になり得るため実験実施日のみを対象にする。
_FUTURE_DATE_FIELDS = ("Date of Experiment",)


def _idf(context):
    return (context.definitions or {}).get("idf", {})


def _empty(v):
    return v is None or str(v).strip() == ""


class MB_IR0003(MbRule):
    rule_id = "MB_IR0003"; level = "error"; target = "IDF"
    description = "Field names are duplicated."

    def validate(self, sub, context):
        if not sub.idf or not sub.idf.duplicate_fields:
            return []
        dup = ", ".join(sorted(set(sub.idf.duplicate_fields)))
        return [self.result(message=f"{self.description} ({dup})", field=dup)]


class MB_IR0004(MbRule):
    # MAGE-TAB 仕様上はフィールドを自由に追加できるが、MetaboBank では登録者に
    # フィールドの追加を許していない（テンプレート固定）ため error。
    # ただし管理システム側は登録後に追加し得るので internal ignore にする。
    rule_id = "MB_IR0004"; level = "error"; target = "IDF"
    description = "User-defined fields cannot be added by submitters."

    def validate(self, sub, context):
        if not sub.idf:
            return []
        allowed = set(_idf(context).get("fields", []))
        bad = [n for n in sub.idf.field_order if n not in allowed]
        if not bad:
            return []
        return [self.result(message=f"{self.description} ({', '.join(bad)})", field=", ".join(bad))]


class _RequiredBase(MbRule):
    _key = None
    def validate(self, sub, context):
        if not sub.idf:
            return []
        req = _idf(context).get(self._key, [])
        ignore = set(_idf(context).get("required_ignore_error", []))
        miss = [f for f in req if f not in ignore and _empty(" ".join(sub.idf.get(f)))]
        if not miss:
            return []
        return [self.result(message=f"{self.description} ({', '.join(miss)})", field=", ".join(miss))]


class MB_IR0005(_RequiredBase):
    rule_id = "MB_IR0005"; level = "error"; target = "IDF"; _key = "required_error"
    description = "IDF has missing mandatory field(s)."


class MB_IR0006(_RequiredBase):
    """**deprecated**（validator に登録しない）。

    参照する `idf.required_warning` が空のままで一度も発火しておらず、推奨項目という
    区分自体を設けない方針になったため廃止した。クラスは既存テストの参照のために残す。
    """
    deprecated = True
    rule_id = "MB_IR0006"; level = "warning"; target = "IDF"; _key = "required_warning"
    description = "IDF has missing mandatory field(s)."


class MB_IR0007(MbRule):
    rule_id = "MB_IR0007"; level = "error"; target = "IDF"
    description = "IDF has null value(s) for mandatory field(s)."

    def validate(self, sub, context):
        if not sub.idf:
            return []
        nulls = null_values(context)
        bad = []
        for f in _idf(context).get("required_not_null", []):
            vals = sub.idf.get(f)
            if vals and all(_empty(v) or v.strip() in nulls for v in vals):
                bad.append(f)
        if not bad:
            return []
        return [self.result(message=f"{self.description} ({', '.join(bad)})", field=", ".join(bad),
                            value=", ".join(sorted({v.strip() for f in bad for v in sub.idf.get(f) if v.strip()})))]


class _GroupBase(MbRule):
    _key = None
    def validate(self, sub, context):
        if not sub.idf:
            return []
        groups = _idf(context).get(self._key, {})
        out = []
        for gname, fields_ in (groups.items() if isinstance(groups, dict) else []):
            present = [f for f in fields_ if not _empty(" ".join(sub.idf.get(f)))]
            if present and len(present) < len(fields_):
                miss = [f for f in fields_ if _empty(" ".join(sub.idf.get(f)))]
                out.append(self.result(message=f"{self.description} ({gname}: {', '.join(miss)})",
                                       field=", ".join(miss), value=gname))
        return out


class MB_IR0008(_GroupBase):
    rule_id = "MB_IR0008"; level = "error"; target = "IDF"; _key = "required_group_error"
    description = "All fields are required for the field group."


class MB_IR0009(_GroupBase):
    rule_id = "MB_IR0009"; level = "warning"; target = "IDF"; _key = "required_group_warning"
    description = "All fields are required for the field group."


class MB_IR0010(MbRule):
    rule_id = "MB_IR0010"; level = "error"; target = "IDF"
    description = "Multiple values are provided for a single-value field."

    def validate(self, sub, context):
        if not sub.idf:
            return []
        single = _idf(context).get("single_value", [])
        bad = [f for f in single if len(sub.idf.get(f)) > 1]
        if not bad:
            return []
        return [self.result(message=f"{self.description} ({', '.join(bad)})", field=", ".join(bad))]


class MB_IR0011(MbRule):
    rule_id = "MB_IR0011"; level = "error"; target = "IDF"
    description = "Study description is short. Please provide more than 100 characters."

    def validate(self, sub, context):
        if not sub.idf:
            return []
        desc = sub.idf.first("Study Description")
        if desc and len(desc.strip()) < 100:
            return [self.result(message=f"{self.description} (Found: {len(desc.strip())} chars)",
                                field="Study Description", value=f"{len(desc.strip())} chars")]
        return []


class MB_IR0013(MbRule):
    rule_id = "MB_IR0013"; level = "error"; target = "IDF"
    description = "Invalid date format. Use YYYY-MM-DD."

    def validate(self, sub, context):
        if not sub.idf:
            return []
        out = []
        for f in _DATE_FIELDS:
            v = sub.idf.first(f).strip()
            if v and not _DATE_OK.match(v):
                out.append(self.result(message=f"{self.description} ({f}: '{v}')", field=f, value=v))
        return out


class MB_IR0033(MbRule):
    rule_id = "MB_IR0033"; level = "error"; target = "IDF"
    description = "Future date is not allowed."

    def validate(self, sub, context):
        if not sub.idf:
            return []
        # 投稿日付は JST。コンテナが UTC だと JST 00:00〜09:00 の間だけ当日が未来日になる
        today = jst_today()
        out = []
        for f in _FUTURE_DATE_FIELDS:
            v = sub.idf.first(f).strip()
            m = re.match(r"^(20\d{2})-(\d{2})-(\d{2})$", v)
            if m:
                try:
                    d = datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
                    if d > today:
                        out.append(self.result(message=f"{self.description} ({f}: {v})", field=f, value=v))
                except ValueError:
                    pass
        return out


class _CvBase(MbRule):
    _level_key = None   # "error" or "warning"
    def validate(self, sub, context):
        if not sub.idf:
            return []
        cv = ((context.definitions or {}).get("controlled_terms", {}).get("idf", {}).get(self._level_key, {}))
        out = []
        for field_name, allowed in cv.items():
            for v in sub.idf.get(field_name):
                if v and v.strip() and v.strip() not in allowed:
                    out.append(self.result(message=f"{self.description} ({field_name}: '{v}')",
                                           field=field_name, value=v))
        return out


class MB_IR0015(_CvBase):
    rule_id = "MB_IR0015"; level = "error"; target = "IDF"; _level_key = "error"
    description = "Value is not in controlled terms."


class MB_IR0016(_CvBase):
    # 対象は Protocol Type のみ。CV 外の値は「登録者が独自の protocol type を足した」
    # という意味になるので、汎用の CV 文ではなくその旨を伝えるメッセージにする。
    rule_id = "MB_IR0016"; level = "warning"; target = "IDF"; _level_key = "warning"
    description = "A user-defined protocol type was added."


class MB_IR0017(MbRule):
    rule_id = "MB_IR0017"; level = "error"; target = "IDF"
    description = "Missing protocol type(s) for the submission type."

    def validate(self, sub, context):
        if not sub.idf:
            return []
        st = sub.idf.submission_type
        req = _idf(context).get("required_protocol_types", {}).get(st)
        if not req:
            return []
        have = set(sub.idf.get("Protocol Type"))
        miss = [t for t in req if t not in have]
        if not miss:
            return []
        return [self.result(message=f"{self.description} ({st}: {', '.join(miss)})",
                            protocol_type=", ".join(miss))]


class MB_IR0018(MbRule):
    rule_id = "MB_IR0018"; level = "error"; target = "IDF"
    description = "Missing protocol parameter(s) for the submission type."

    def validate(self, sub, context):
        """submission type ごとに、必須の protocol parameter が宣言されているかを見る。

        参照するのは `protocol_parameters_required`。よく似た `required_protocol_parameters`
        は名前に反して「IDF Protocol Parameters として出力する項目」を規定するキーで
        （登録システムが Excel/IDF の生成に使う。キー名は互換のため変えていない）、
        必須／任意は規定していない。

        **現在 `protocol_parameters_required` は空なので、このルールは事実上発火しない。**
        公式 Excel テンプレ 11 種の Parameter Value 列 157 個のうち ORANGE（mandatory）は
        MSI の Data processing software / version の 2 個だけだったが、それも他 10 テンプレと
        揃えて BLUE（任意）にしたため必須が 0 になった。
        ただし将来また必須パラメータが出てくる可能性があるので **deprecated にはせず登録も残す**
        （definitions に足すだけで効くようにしておく）。

        以前は出力仕様のキー（`required_protocol_parameters`）をそのまま必須リストとして
        読んでいたため、公開 114 study の 81%（92 件）で Temperature の未記入を誤って
        エラーにしていた。
        """
        if not sub.idf:
            return []
        st = sub.idf.submission_type
        spec = _idf(context).get("protocol_parameters_required", {}).get(st, {})
        if not spec:
            return []
        out = []
        protos = {p["Protocol Type"]: p for p in sub.idf.protocols()}
        for ptype, params in spec.items():
            p = protos.get(ptype)
            have = set((p["Protocol Parameters"].split(";") if p else []))
            miss = [x for x in params if x not in have]
            if miss:
                out.append(self.result(message=f"{self.description} ({st} {ptype}: {', '.join(miss)})",
                                       protocol_type=ptype, param=", ".join(miss)))
        return out


class MB_IR0034(MbRule):
    rule_id = "MB_IR0034"; level = "error"; target = "IDF"
    description = "Missing experiment type for the submission type."

    def validate(self, sub, context):
        if not sub.idf:
            return []
        st = sub.idf.submission_type
        req = _idf(context).get("required_experiment_types", {}).get(st)
        if not req:
            return []
        have = set(sub.idf.get("Comment[Experiment type]"))
        miss = [t for t in req if t not in have]
        if not miss:
            return []
        return [self.result(message=f"{self.description} ({st}: {', '.join(miss)})",
                            field="Comment[Experiment type]", value=", ".join(miss))]


class MB_IR0020(MbRule):
    rule_id = "MB_IR0020"; level = "error"; target = "IDF"
    description = "At least one submitter must be specified."

    def validate(self, sub, context):
        if not sub.idf:
            return []
        roles = [r.strip().lower() for r in sub.idf.get("Person Roles")]
        return [] if "submitter" in roles else [self.result()]


class MB_IR0037(MbRule):
    rule_id = "MB_IR0037"; level = "error"; target = "IDF"
    description = "Email address is required for the submitter."

    def validate(self, sub, context):
        if not sub.idf:
            return []
        roles = sub.idf.get("Person Roles")
        emails = sub.idf.get("Person Email")
        for i, role in enumerate(roles):
            if role.strip().lower() == "submitter":
                if i >= len(emails) or _empty(emails[i]):
                    return [self.result()]
        return []


class MB_IR0025(MbRule):
    # PubMed ID が数値でないのは書式の誤りなので error。ただし管理システム側は
    # 登録後に手で直すことがあるため internal ignore にする。
    rule_id = "MB_IR0025"; level = "error"; target = "IDF"
    description = "Invalid publication identifier (PubMed ID must be numeric)."

    def validate(self, sub, context):
        if not sub.idf:
            return []
        nulls = null_values(context)
        out = []
        for v in sub.idf.get("PubMed ID"):
            if v and v.strip() and v.strip() not in nulls and not re.match(r"^\d+$", v.strip()):
                out.append(self.result(message=f"{self.description} (PubMed ID: '{v}')",
                                       field="PubMed ID", value=v))
        return out


class MB_IR0038(MbRule):
    rule_id = "MB_IR0038"; level = "warning"; target = "IDF"
    description = 'Related study should be specified as "DB:ID" or a MetaboBank accession (MTBKSnnn).'

    def validate(self, sub, context):
        """Comment[Related study]（再解析元の study）が参照表記として読める形か。

        認める形は 2 つ（判定は base.is_valid_related_study に集約）。
        - **MetaboBank の study accession**: `MTBKSnnn`。同じ DB なので `MetaboBank:` prefix は
          付けても付けなくてもよい（特別扱い）
        - **DB:ID 形式**: それ以外の DB は `DB:ID` で書く。DB 名の CV 化は未実施なので
          「`:` の左右が非空」だけを見る緩い判定にしてある
          （キュレータが入れる項目のため。error ではなく warning に留めるのも同じ理由）

        空値は素通し（Related study は任意項目。再解析でなければ書かない）。
        null value も素通し（そちらは MB_IR0023 の担当）。値が複数あれば各値ごとに 1 件報告。
        """
        if not sub.idf:
            return []
        nulls = null_values(context)
        out = []
        for v in sub.idf.get("Comment[Related study]"):
            s = v.strip() if v else ""
            if not s or s in nulls or is_valid_related_study(s):
                continue
            out.append(self.result(message=f"{self.description} (Comment[Related study]: '{v}')",
                                   field="Comment[Related study]", value=v))
        return out


class MB_IR0023(MbRule):
    rule_id = "MB_IR0023"; level = "warning"; target = "IDF"
    description = "Null value is provided for an optional field."

    def validate(self, sub, context):
        """任意項目に null value が書かれていないか。補正できる値は autofix 提案として出す。

        必須項目の null は MB_IR0007（error）の担当なので除外する。
        補正の判定は base.normalize_null に一本化しており、`cli._write_fixed` が fixed/ へ
        書き出す値と必ず一致する。
        - `idf.autofix_null_to_empty` の項目（Experimental Factor Name / Type）は値を消す
          （任意項目に null を書くこと自体が不正で「書かない」が正規の書き方）
        - それ以外は推奨 null の正規表記へ（`Not Applicable` → `not applicable`、`NA` → `missing`）

        **何をどう直したかを message に入れる**（biosample の BS_R0001 と同じ方針）。
        暗黙に fixed/ を書き換えるだけだと登録者が次回も同じ書き方をするため。
        補正対象にならない null（既に正規表記で、消す対象でもない）は従来どおり warning のみ。
        """
        if not sub.idf:
            return []
        accepted = null_values(context)
        not_recommended = null_values_not_recommended(context)
        idf = _idf(context)
        required = set(idf.get("required_error", [])) | set(idf.get("required_not_null", []))
        to_empty = set(idf.get("autofix_null_to_empty", []))
        out = []
        for f in sub.idf.field_order:
            if f in required:
                continue
            for v in sub.idf.get(f):
                fixed = normalize_null(v, accepted, not_recommended, to_empty=f in to_empty)
                if fixed is None and v.strip() not in accepted:
                    continue                      # null value ではない
                if fixed is None:                 # null だが補正の余地が無い
                    out.append(self.result(message=f"{self.description} ({f}: '{v}')",
                                           field=f, value=v))
                else:
                    shown = "value removed" if fixed == "" else f"'{fixed}'"
                    out.append(self.result(
                        message=f"{self.description} ({f}: '{v}', Suggested: {shown})",
                        field=f, value=v, autofix=True, old_value=v, new_value=fixed))
                break
        return out


class MB_IR0024(MbRule):
    rule_id = "MB_IR0024"; level = "warning"; target = "IDF"
    # IDF フィールド値の非 ASCII 文字を ASCII へ強制正規化（reader で適用済み）。
    # mapped は warning（autofix 報告）、正規化しきれず残った非 ASCII は error。
    description = "Non-ASCII characters in an IDF field were normalized to ASCII."

    def validate(self, sub, context):
        from apps.metabobank.charnorm import fix_warning_message, residual_error_message
        if not sub.idf:
            return []
        out = []
        for fx in getattr(sub, "char_fixes", []):
            if fx["target"] != "IDF":
                continue
            if fx["mapped"]:
                out.append(self.result(
                    message=fix_warning_message(fx["where"], fx["mapped"]), level="warning",
                    field=fx["where"], value="".join(sorted(fx["mapped"]))))
            if fx["residual"]:
                out.append(self.result(
                    message=residual_error_message(fx["where"], fx["residual"]), level="error",
                    field=fx["where"], value="".join(sorted(fx["residual"]))))
        return out
