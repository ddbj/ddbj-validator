"""文字種・任意属性の値ルール（DB 非依存。フェーズ A 続き）。

- BS_R0058: 非 ASCII 文字が含まれる（属性値＋ XML の全要素。文字参照は対象外）
- BS_R0100: 任意属性に missing 値が入っている（任意は空でよい）
- BS_R0012: 特殊文字（℃/°C/μm/μ 等）を推奨表記へ置換（autofix）
"""
import re
from apps.biosample.rules.base import BsRule
from apps.biosample.rules._util import is_missing_value, is_empty
# 純テキストユーティリティは common に集約（bioproject と共有。app 間相互 import を避ける）。
from common.text import (
    _WS_RE, _HTML_RE, normalize_data_format, apply_special_chars, _non_ascii, _has_html,
)
# XML 全要素の走査（BS_R0058 が属性以外の要素も見るため）
from common.xmltext import non_ascii_values


class BS_R0013(BsRule):
    rule_id = "BS_R0013"
    level = "warning"
    target = "#attributes"
    description = "Invalid data format."

    def validate(self, submission, context):
        # autocleanup（ddbj の cleanup 相当）: 全属性値を正規化（連続空白畳み込み＋前後クオート除去）し
        # **in-place で置換**する。validator.run の最初に実行され、cleanup 後の値で後続ルールが評価される。
        # → 専用 autofix（geo/date 等）との二重提案は起きない（後続は正規化済みの値を見るため）。
        # missing 値は対象外。sample_name は autofix のサンプル同定キーのため除外。Ruby v invalid_data_format 準拠。
        # 正規化の実体は common/cleanup.clean_value（NBSP・全角空白・ゼロ幅空白も対象。2026-10-03）。
        out = []
        for rec in submission.records:
            for name, vals in rec.attributes.items():
                if name == "sample_name":
                    continue
                for i, v in enumerate(vals):
                    if is_empty(v) or is_missing_value(v):
                        continue
                    fixed = normalize_data_format(v)
                    if fixed and fixed != v:
                        vals[i] = fixed  # in-place cleanup（後続ルールが cleaned 値を読む）
                        if name == "sample_title" and rec.title == v:
                            rec.title = fixed   # Description/Title 由来（BS_R0003 の重複判定が読む）
                        out.append(self.autofix_result(
                            sample=rec.sample_id, target=name,
                            message=f"Invalid data format. ({name}: '{v}', Suggested: '{fixed}')",
                            attribute=name, old_value=v, new_value=fixed))
            # organism（Description/Organism/OrganismName）も対象（2026-10-03）。属性ではないので
            # 上のループに入らず、NBSP や二重空白のまま Taxonomy を引いて提案が付かなかった。
            # kind=organism の autofix として fixed XML の OrganismName に書き戻す。
            org = rec.organism
            if org and not is_missing_value(org):
                fixed = normalize_data_format(org)
                if fixed and fixed != org:
                    rec.organism = fixed
                    out.append(self.autofix_result(
                        sample=rec.sample_id, target="organism", kind="organism",
                        message=f"Invalid data format. (organism: '{org}', Suggested: '{fixed}')",
                        anno_cols=[{"key": "organism", "value": org}], target_key="organism",
                        old_value=org, new_value=fixed))
        return out


# 属性モデル側（rec.attributes / rec.organism）で既に見ている要素のパス。
# これらは BS_R0013(空白正規化) → BS_R0012(特殊文字) の autocleanup 後の値で評価されるので、
# XML 走査では飛ばす（℃ 等を R0012 と R0058 で二重に出さないため）。`Attributes/Attribute` も同様。
# 上の属性の検査で見たもの。Record ではその sample の中の位置。
_RECORD_MODEL_COVERED = {"alias", "title", "description", "organism.name"}


def _model_covered(el, path, raw_path):
    if raw_path is None:
        return el.tag == "Attribute" or path in _MODEL_COVERED
    within = path[len(raw_path) + 1:]
    return within.startswith("attributes.") or within in _RECORD_MODEL_COVERED


_MODEL_COVERED = {
    "BioSample/Description/Title",
    "BioSample/Description/SampleName",
    "BioSample/Description/Comment/Paragraph",
    "BioSample/Description/Organism",
    "BioSample/Description/Organism/OrganismName",
}


class BS_R0058(BsRule):
    """非 ASCII 文字が入っていれば error。

    対象は 2 系統:
    1. 属性値（＋ sample_name / sample_title / organism）。autocleanup 済みの値を見る。
    2. **それ以外の XML 要素すべて**（2026-09-28 に追加）。Owner/Name、Contact の氏名、
       Address、Ids など、属性モデルに取り込んでいない要素は素通りしていた。

    文字参照（`&#x201c;` 等）は対象外。XML パーサが実体へ展開してしまうため、
    `submission.source_non_ascii`（ソースに素で現れた非 ASCII）で絞り込む。
    """
    rule_id = "BS_R0058"
    level = "error"
    target = "#attributes"
    description = "Non-ASCII format characters detected."

    def _hit(self, rec, name, v):
        pos = "".join("[### Non-ASCII character ###]" if ord(c) > 127 else c for c in v)
        return self.result(sample=rec.sample_id, target=name,
                           anno_cols=[{"key": "Attribute", "value": name},
                                      {"key": "Attribute value", "value": v},
                                      {"key": "Position", "value": pos}],
                           message=f"Non-ASCII characters detected in '{name}'. (Found: '{v}')")

    def validate(self, submission, context):
        out = []
        # ソースに素で入っている非 ASCII 文字。文字参照で書かれたものはここに入らない。
        literal = getattr(submission, "source_non_ascii", None)

        def _literal_hit(v):
            if not _non_ascii(v):
                return False
            if literal is None:
                return True
            return any(ord(ch) > 0x7F and ch in literal for ch in v)

        for rec in submission.records:
            reported = set()   # 同じ値が属性と XML の両方に出てきても 1 回だけ報告する
            checked = dict(rec.attributes)
            # Description 由来も対象
            extra = {"sample_name": rec.sample_name, "sample_title": rec.title, "organism": rec.organism}
            for name, v in extra.items():
                if v:
                    checked.setdefault(name, [v])
            for name in sorted(checked):
                for v in checked[name]:
                    if v and _literal_hit(v):
                        reported.add(v)
                        out.append(self._hit(rec, name, v))
                        break
            # 属性モデルに載っていない要素（Owner / Contact / Address / Ids など）を XML から拾う。
            # Record（raw が dict）なら record の中の値すべてを、record の中の位置で。
            if rec.raw is None:
                continue
            prefix = rec.raw_path or "BioSample"
            for el, path, v in non_ascii_values(rec.raw, literal, prefix=prefix):
                if _model_covered(el, path, rec.raw_path) or v in reported:
                    continue
                reported.add(v)
                out.append(self._hit(rec, path, v))

        # Record では、XML なら各 BioSample の Owner にある連絡先・組織が sample の外の
        # `submission` にある。sample ごとではなく 1 回、record の中の位置で。
        shared = submission.raw_root
        if isinstance(shared, dict) and submission.records:
            first, seen = submission.records[0], set()
            for _el, path, v in non_ascii_values(shared, literal):
                # 同じ組織が連絡先ごとに写っている（repository の converter はそう書く）。
                # XML でも Owner/Name は 1 回なので、値で 1 回にする。
                if v in seen:
                    continue
                seen.add(v)
                out.append(self._hit(first, path, v))
        return out


class BS_R0142(BsRule):
    rule_id = "BS_R0142"
    level = "error"
    target = "#attributes"
    description = "Sample description should not include HTML markup."

    def validate(self, submission, context):
        # INSDC Sample Minimum Specification: メタデータに HTML マークアップを含めてはならない（reject 対象）。
        # R0058(非ASCII) は HTML タグ（ASCII）を捕まえないため専用に検出する。対象は属性値＋Description 由来。
        out = []
        for rec in submission.records:
            checked = dict(rec.attributes)
            extra = {"sample_name": rec.sample_name, "sample_title": rec.title, "organism": rec.organism}
            for name, v in extra.items():
                if v:
                    checked.setdefault(name, [v])
            for name in sorted(checked):
                for v in checked[name]:
                    if _has_html(v):
                        out.append(self.result(
                            sample=rec.sample_id, target=name,
                            message=f"HTML markup is not allowed in metadata; remove HTML tags. ({name}: '{v}')"))
                        break
        return out


class BS_R0100(BsRule):
    rule_id = "BS_R0100"
    level = "warning"
    target = "#attributes"
    description = "Missing values are not necessary for optional attributes. Leave values empty when there is no information."

    def validate(self, submission, context):
        # missing 系（INSDC CV）に加え、非推奨 null（NA / unknown / . / - 等 null_not_recommended）も
        # missing 相当として拾う（production 準拠。R0001 が NA→missing 補正するのと同じ null 集合）。
        nnr = context.null_not_recommended or []

        def _is_null(v):
            if is_missing_value(v):
                return True
            for pat in nnr:
                try:
                    if re.fullmatch(pat, v.strip(), re.I):
                        return True
                except re.error:
                    continue
            return False

        out = []
        for rec in submission.records:
            if not rec.package or context.package_def(rec.package) is None:
                continue
            uses = context.attribute_uses(rec.package)
            for name, vals in rec.attributes.items():
                use = uses.get(name, "")
                if use in ("mandatory", "either_one_mandatory"):
                    continue  # 任意属性のみ対象
                for v in vals:
                    if v and _is_null(v):
                        out.append(self.result(sample=rec.sample_id, target=name,
                                               anno_cols=[{"key": "Attribute name", "value": name},
                                                          {"key": "Attribute value", "value": v},
                                                          {"key": "Suggested value", "value": ""}],
                                               message=f"Missing value is unnecessary for optional attribute '{name}'."))
                        break
        return out


class BS_R0012(BsRule):
    rule_id = "BS_R0012"
    level = "warning"
    target = "#all"
    description = "Special character is included."

    def validate(self, submission, context):
        # 属性値の特殊文字（℃/°C/μm/μ 等）を推奨表記へ置換する autofix。
        # autocleanup（BS_R0013 の直後）として **in-place で置換** し、後続ルールは置換済みの値を読む。
        # → ℃ 等は R0058(非ASCII) より先に ASCII 表記へ直るため R0058 の二重検知を避けられる（production 準拠）。
        special = context.special_chars or {}
        if not special:
            return []
        out = []
        for rec in submission.records:
            for name, vals in rec.attributes.items():
                for i, v in enumerate(vals):
                    if not v or is_missing_value(v):
                        continue
                    fixed = apply_special_chars(v, special)
                    if fixed != v:
                        vals[i] = fixed  # in-place（後続ルールが置換済み値を読む）
                        out.append(self.autofix_result(
                            sample=rec.sample_id, target=name,
                            message=f"Special character is included. ({name}: '{v}', Suggested: '{fixed}')",
                            attribute=name, old_value=v, new_value=fixed, suggest_key="Suggestion"))
        return out
