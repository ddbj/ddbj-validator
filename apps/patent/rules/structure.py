"""特許の ann の形を見る規則（PAT0008〜PAT0012、PAT0019、PAT0024、PAT0028、PAT0030〜PAT0036、PAT0043〜PAT0045）。

特許は出願に添付された配列情報をそのまま FF にする。科学的な正しさは見ず、FF が作れるか・壊れないかだけを見る。
error = FF が作れない / 壊れる。番号は今の ST.26 の CLI（PAT_R0008 など）を引き継ぐ。
"""
from datetime import date

from common.rules.base import BaseRule
from apps.patent import constants as C
from apps.patent.rules.fields import patent_fields, parse_date, KEYWORD_RE, JOURNAL_RE


class PatentEntryRule(BaseRule):
    """entry 単位の規則の土台。COMMON を飛ばし、取り出し済みの項目（PatentFields）を check に渡す。"""
    target = "entry"
    internal_ignore = False

    def validate(self, record, context):
        if record.id == "COMMON":
            return []
        return self.check(record, patent_fields(record), context) or []

    def check(self, record, f, context):
        raise NotImplementedError

    def comment_result(self, record, f, message, level="error"):
        """COMMENT の行についての結果（COMMENT が無ければ entry に付ける）。"""
        if f.comment_feats:
            return self.feature_result(record, f.comment_feats[0], message, level=level, qualifier="line")
        return self.format_result(record.id, message, level=level, feature_type="COMMENT", qualifier="line")


def _today(context):
    return getattr(context, "pat_today", None) or date.today()


class PAT0008(PatentEntryRule):
    rule_id = "PAT0008"
    description = "The filing date (PF) in COMMENT is not a valid date in DD-MON-YYYY."

    def check(self, record, f, context):
        token = f.first_token("PF")
        if token is None or token == C.DATE_NOT_PROVIDED or parse_date(token):
            return []
        return [self.comment_result(record, f, f"{self.description} (Found: '{token}')")]


class PAT0028(PatentEntryRule):
    rule_id = "PAT0028"
    description = "The publication date (PD) in COMMENT is missing or not a valid date in DD-MON-YYYY."

    def check(self, record, f, context):
        token = f.first_token("PD")
        if token and parse_date(token):
            return []
        found = "no PD line" if token is None else f"'{token}'"
        return [self.comment_result(record, f, f"{self.description} (Found: {found})")]


class PAT0030(PatentEntryRule):
    rule_id = "PAT0030"
    description = "The priority date (PR) in COMMENT is not a valid date in DD-MON-YYYY."

    def check(self, record, f, context):
        results = []
        for value in f.tags.get("PR", []):
            token = value.split(None, 1)[0] if value else ""
            if not parse_date(token):
                results.append(self.comment_result(record, f, f"{self.description} (Found: '{value}')"))
        return results


class PAT0009(PatentEntryRule):
    rule_id = "PAT0009"
    description = "The date in COMMENT is before 01-JAN-1980 or in the future."

    def check(self, record, f, context):
        results = []
        today = _today(context)
        for tag in ("PD", "PF"):
            d = f.date_of(tag)
            if d and (d < C.EARLIEST_DATE or d > today):
                results.append(self.comment_result(
                    record, f, f"{self.description} ({tag}: '{f.first_token(tag)}')"))
        return results


class PAT0010(PatentEntryRule):
    rule_id = "PAT0010"
    description = "The publication date (PD) is earlier than the filing date (PF)."

    def check(self, record, f, context):
        pd, pf = f.date_of("PD"), f.date_of("PF")
        if pd and pf and pd < pf:
            return [self.comment_result(
                record, f, f"{self.description} (PD: '{f.first_token('PD')}', PF: '{f.first_token('PF')}')")]
        return []


class PAT0011(PatentEntryRule):
    rule_id = "PAT0011"
    description = "An entry must have exactly one source feature."

    def check(self, record, f, context):
        n = len(f.source_feats)
        if n == 1:
            return []
        if n == 0:
            return [self.format_result(record.id, f"{self.description} (Found: 0)", level="error", feature_type="source")]
        return [self.feature_result(record, f.source_feats[1], f"{self.description} (Found: {n})", level="error")]


class PAT0012(PatentEntryRule):
    rule_id = "PAT0012"
    description = ("Invalid publication number in KEYWORD. "
                   "Expected '<office> <number>-<kind>/<sequence number>', e.g. 'JP 2026524816-A/1'.")

    def check(self, record, f, context):
        if not f.keywords:
            return []  # KEYWORD が無いのは PAT0032
        if len(f.keywords) == 1 and KEYWORD_RE.match(f.keywords[0]):
            return []
        found = ", ".join(f"'{k}'" for k in f.keywords)
        return [self.feature_result(record, f.keyword_feats[0], f"{self.description} (Found: {found})",
                                    level="error", qualifier="keyword")]


class PAT0019(PatentEntryRule):
    rule_id = "PAT0019"
    description = "mol_type is required in source for a nucleotide set and not allowed for an amino acid set."

    def check(self, record, f, context):
        kind = getattr(context, "pat_kind", None)
        results = []
        for src in f.source_feats:
            has_mol_type = "mol_type" in src.qualifiers
            if kind == C.KIND_NA and not has_mol_type:
                results.append(self.feature_result(
                    record, src, "mol_type is missing in source of a nucleotide set.", level="error", qualifier="mol_type"))
            elif kind == C.KIND_AA and has_mol_type:
                results.append(self.feature_result(
                    record, src, "mol_type is not allowed in source of an amino acid set.", level="error", qualifier="mol_type"))
        return results


class PAT0024(PatentEntryRule):
    rule_id = "PAT0024"
    description = "The source location must be '1..<sequence length>'."

    def check(self, record, f, context):
        seq_len = len(record.seq) if record.seq is not None else 0
        if not seq_len:
            return []  # 配列が空なのは PAT0021
        expected = f"1..{seq_len}"
        results = []
        for src in f.source_feats:
            found = (getattr(src, "original_location", "") or "").replace(" ", "")
            if found != expected:
                results.append(self.feature_result(
                    record, src, f"{self.description} (Found: '{found}', Expected: '{expected}')", level="error"))
        return results


class PAT0031(BaseRule):
    rule_id = "PAT0031"
    target = "file"
    description = "DIVISION in COMMON must be 'PAT'."
    is_file_level = True
    internal_ignore = False

    def validate_file(self, records, context, ann_path=None, seq_path=None):
        common = records.get("COMMON")
        feats = self.get_features(common, "DIVISION") if common is not None else []
        values = [v for feat in feats for v in feat.qualifiers.get("division", [])]
        if values == [C.DIVISION]:
            return []
        found = ", ".join(f"'{v}'" for v in values) if values else "no DIVISION"
        msg = f"{self.description} (Found: {found})"
        if feats:
            return [self.feature_result(common, feats[0], msg, level="error", qualifier="division")]
        return [self.format_result("COMMON", msg, level="error", feature_type="DIVISION", qualifier="division")]


class PAT0032(PatentEntryRule):
    rule_id = "PAT0032"
    description = "A required item is missing in the entry."

    def check(self, record, f, context):
        missing = []
        if not f.keywords:
            missing.append("KEYWORD keyword")
        if not f.titles:
            missing.append("REFERENCE title")
        if not f.journals:
            missing.append("REFERENCE journal")
        if not f.lines:
            missing.append("COMMENT line")
        if not f.source_feats:
            missing.append("source")
        else:
            src = f.source_feats[0]
            for q in ("organism", "ff_definition"):
                if not any(v for v in src.qualifiers.get(q, [])):
                    missing.append(f"source {q}")
        if not missing:
            return []
        return [self.format_result(record.id, f"{self.description} (Missing: {', '.join(missing)})", level="error")]


class PAT0033(PatentEntryRule):
    rule_id = "PAT0033"
    description = ("The first journal in REFERENCE must be "
                   "'Patent: <office> <number>-<kind> <sequence number> DD-MON-YYYY;'.")

    def check(self, record, f, context):
        if not f.journals:
            return []  # journal が無いのは PAT0032
        first = f.journals[0]
        m = JOURNAL_RE.match(first)
        if m and parse_date(m.group(5)):
            return []
        return [self.feature_result(record, f.reference_feats[0], f"{self.description} (Found: '{first}')",
                                    level="error", qualifier="journal")]


class PAT0034(PatentEntryRule):
    """必須の行。行の頭のタグの形は ann の行をそのまま見る PAT_LINE_FORMAT が同じ id で出す。"""
    rule_id = "PAT0034"
    description = "A required line is missing in COMMENT."

    def check(self, record, f, context):
        if not f.lines:
            return []  # COMMENT が無いのは PAT0032
        missing = [t for t in C.COMMENT_REQUIRED_TAGS if t not in f.tags]
        if not missing:
            return []
        return [self.comment_result(record, f, f"{self.description} (Missing: {', '.join(missing)})")]


class PAT0035(PatentEntryRule):
    rule_id = "PAT0035"
    description = "The publication number or the sequence number is inconsistent within the entry."

    def check(self, record, f, context):
        if len(f.keywords) != 1:
            return []
        keyword = f.keywords[0]
        m = KEYWORD_RE.match(keyword)
        if not m:
            return []  # 形が違うのは PAT0012
        office, number, kind, seq_no = m.groups()
        diffs = []
        if record.id != seq_no:
            diffs.append(f"entry name '{record.id}'")
        for definition in (v for src in f.source_feats for v in src.qualifiers.get("ff_definition", [])):
            pos = definition.find(keyword)
            after = definition[pos + len(keyword):pos + len(keyword) + 1] if pos >= 0 else ""
            if pos < 0 or after.isdigit():
                diffs.append(f"ff_definition '{definition[:40]}'")
        if f.journals:
            jm = JOURNAL_RE.match(f.journals[0])
            if jm and jm.groups()[:4] != (office, number, kind, seq_no):
                diffs.append(f"journal '{f.journals[0]}'")
        for value in f.tags.get("PN", []):
            if value != keyword:
                diffs.append(f"PN '{value}'")
        for value in f.tags.get("PS", []):
            if value != seq_no:
                diffs.append(f"PS '{value}'")
        if not diffs:
            return []
        return [self.format_result(
            record.id, f"{self.description} (KEYWORD: '{keyword}', Different: {', '.join(diffs)})", level="error")]


class PAT_LINE_FORMAT(BaseRule):
    """ann の行をそのまま見る検査（PAT0034 の行の頭のタグ、PAT0036 の幅）。

    parser は値の前後の空白を取るので、桁を見る検査は parser を通した値ではなく行で行う。
    """
    rule_id = "PAT_LINE_FORMAT"
    target = "file"
    is_file_level = True
    internal_ignore = False

    def validate_file(self, records, context, ann_path=None, seq_path=None, ann_lines=None):
        results = []
        entry, feature, tags = "", "", C.COMMENT_TAGS
        for line_no, line in enumerate(ann_lines or [], 1):
            cols = line.split("\t")
            if len(cols) != 5:
                continue  # 列の数が違う行は ANN0140
            if cols[0].strip():
                entry = cols[0].strip()
                feature = ""
                tags = C.COMMENT_TAGS | C.COMMENT_TAGS_KR if self._office(records, entry) == "KR" else C.COMMENT_TAGS
            if cols[1].strip():
                feature = cols[1].strip()
            qualifier, value = cols[3].strip(), cols[4]
            if feature == "COMMENT" and qualifier == "line":
                if value[:2] not in tags or value[2:5] != "   ":
                    results.append(self.format_result(
                        entry, "A line in COMMENT must start with a two-letter tag followed by three spaces. "
                               f"(Found: '{value[:20]}')",
                        level="error", feature_type="COMMENT", qualifier="line", line_number=line_no, rule="PAT0034"))
            elif not (feature == "REFERENCE" and qualifier == "journal"):
                continue
            width = len(value.rstrip())
            if width > C.FF_LINE_WIDTH:
                results.append(self.format_result(
                    entry, f"The value is longer than {C.FF_LINE_WIDTH} characters, the width of the flat file. "
                           f"(Found: {width} characters)",
                    level="error", feature_type=feature, qualifier=qualifier, line_number=line_no, rule="PAT0036"))
        return results

    @staticmethod
    def _office(records, entry):
        record = records.get(entry)
        if record is None or entry == "COMMON":
            return ""
        keywords = patent_fields(record).keywords
        return keywords[0][:2] if keywords else ""


class PAT0043(PatentEntryRule):
    rule_id = "PAT0043"
    description = "The organism name is not found in the Taxonomy database."
    requires_rdb = True

    def check(self, record, f, context):
        known = getattr(context, "pat_known_organisms", None)
        if known is None:
            return []
        results = []
        for src in f.source_feats:
            for name in src.qualifiers.get("organism", []):
                if name and name not in C.ORGANISM_ALWAYS_OK and name not in known:
                    results.append(self.feature_result(
                        record, src, f"{self.description} (Found: '{name}')", level="info", qualifier="organism"))
        return results


class PAT0044(BaseRule):
    rule_id = "PAT0044"
    target = "entry"
    description = "A feature or qualifier that is not used in patent entries."
    internal_ignore = False

    def validate(self, record, context):
        allowed = C.ALLOWED_COMMON if record.id == "COMMON" else C.ALLOWED_ENTRY
        results = []
        for feat in record.features:
            quals = allowed.get(feat.type)
            if quals is None:
                results.append(self.feature_result(
                    record, feat, f"{self.description} (Feature: '{feat.type}')", level="error"))
                continue
            for q in feat.qualifiers:
                if q not in quals:
                    results.append(self.feature_result(
                        record, feat, f"{self.description} (Qualifier: '{q}' in '{feat.type}')",
                        level="error", qualifier=q))
        return results


class PAT0045(BaseRule):
    rule_id = "PAT0045"
    target = "file"
    description = "The file name must end with '_na' (nucleotide set) or '_aa' (amino acid set)."
    is_file_level = True
    internal_ignore = False

    def validate_file(self, records, context, ann_path=None, seq_path=None):
        if getattr(context, "pat_kind", None) in (C.KIND_NA, C.KIND_AA):
            return []
        return [self.format_result("ALL", self.description, level="error", feature_type="file")]
