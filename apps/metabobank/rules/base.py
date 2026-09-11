"""MetaboBank ルールの基底。共通 flags/result は common/rules/simple:SimpleRule に集約。"""
import re

from common.rules.simple import SimpleRule

# internal_ignore（＝管理システム側で無視する error）の rule_id 集合。
# MetaboBank ルール表の「Internal ignore」列に準拠（ai_logs/2026-09-04/mb-rules2.txt）。
# JSON 出力の `external` フィールドを駆動する。
INTERNAL_IGNORE_RULE_IDS = frozenset({
    # --- IDF ---
    "MB_IR0004",   # User-defined fields cannot be added by submitters.（登録者は変更できない）
    "MB_IR0005",   # IDF has missing mandatory field(s).
    "MB_IR0007",   # IDF has null value(s) for mandatory field(s).
    "MB_IR0011",   # Study description is short. Please provide more than 100 characters.
    "MB_IR0013",   # Invalid date format. Use YYYY-MM-DD.
    "MB_IR0017",   # Missing protocol type(s) for the submission type.
    "MB_IR0018",   # Missing protocol parameter(s) for the submission type.
    # residual（ASCII へ正規化しきれなかった非 ASCII）は error として出る。クラス属性の
    # level="warning" は既定値にすぎず、mapped=warning / residual=error を結果ごとに
    # 出し分けているので、warning が ignore に混じっているわけではない。
    "MB_IR0024",   # Non-ASCII characters in an IDF field were normalized to ASCII.
    "MB_IR0025",   # Invalid publication identifier (PubMed ID must be numeric).
    "MB_IR0037",   # Email address is required for the submitter.（非公開のため reminder）
    # --- SDRF ---
    "MB_SR0007",   # Invalid user-defined columns are added.（許容種別以外の列）
    "MB_SR0009",   # Missing or null value for a required column.
    "MB_SR0019",   # Invalid value format.
    "MB_SR0017",   # Factor value is constant across all rows.
    "MB_SR0023",   # Characteristics value and BioSample attribute value do not match.
    "MB_SR0030",   # Non-ASCII or control characters in an SDRF cell.
    "MB_SR0047",   # Experimental factor value is missing.
    # --- IDF↔SDRF ---
    "MB_CR0001",   # Experimental factor in SDRF does not match IDF Experimental Factor Name.
})


def is_internal_ignore(rule_id):
    """rule_id が internal_ignore（管理システムで無視する error）か。JSON の external フィールド用。"""
    return rule_id in INTERNAL_IGNORE_RULE_IDS


# --- 結果 JSON の annotation パターン（rule_id -> パターン名）------------------
#
# BS と同じ骨格（message は rule の固定文、個別情報は annotation 配列）にするための表。
# reporter がこの表を見て annotation を組む。パターンごとに rule 側が供給する追加キー:
#
#   sdrf_cell    行単位の値の問題。line / assay ＋ column / value
#                （MB_SR0023 は samd / bs_value、MB_SR0030 は new_value も）
#   sdrf_column  列の有無・列全体の問題。column（＋ rows）
#   idf_field    IDF 項目の問題。field / value
#   idf_protocol submission type ごとの protocol 要件。protocol_type / param
#   idf_sdrf     IDF↔SDRF の突合。idf_only / sdrf_only
#   general      個別情報を持たない（annotation なし。文だけ）
ANNOTATION_PATTERNS = {
    # --- SDRF: 行単位の値 ---
    "MB_SR0009": "sdrf_cell",
    "MB_SR0019": "sdrf_cell",
    "MB_SR0021": "sdrf_cell",
    "MB_SR0022": "sdrf_cell",
    "MB_SR0023": "sdrf_cell",
    "MB_SR0030": "sdrf_cell",
    "MB_SR0033": "sdrf_cell",
    "MB_SR0036": "sdrf_cell",
    "MB_SR0037": "sdrf_cell",
    "MB_SR0045": "sdrf_cell",
    "MB_SR0046": "sdrf_cell",
    "MB_SR0048": "sdrf_cell",
    # --- SDRF: 列単位 ---
    "MB_SR0003": "sdrf_column",
    "MB_SR0004": "sdrf_column",
    "MB_SR0005": "sdrf_column",
    "MB_SR0006": "sdrf_column",
    "MB_SR0007": "sdrf_column",
    "MB_SR0017": "sdrf_column",
    "MB_SR0018": "sdrf_column",
    "MB_SR0024": "sdrf_column",
    "MB_SR0026": "sdrf_column",
    "MB_SR0034": "sdrf_column",
    "MB_SR0035": "sdrf_column",
    "MB_SR0047": "sdrf_column",
    # --- IDF: 項目単位 ---
    "MB_IR0003": "idf_field",
    "MB_IR0004": "idf_field",
    "MB_IR0005": "idf_field",
    "MB_IR0006": "idf_field",
    "MB_IR0007": "idf_field",
    "MB_IR0008": "idf_field",
    "MB_IR0009": "idf_field",
    "MB_IR0010": "idf_field",
    "MB_IR0011": "idf_field",
    "MB_IR0013": "idf_field",
    "MB_IR0015": "idf_field",
    "MB_IR0016": "idf_field",
    "MB_IR0023": "idf_field",
    "MB_IR0024": "idf_field",
    "MB_IR0025": "idf_field",
    "MB_IR0033": "idf_field",
    "MB_IR0034": "idf_field",
    "MB_IR0038": "idf_field",
    "MB_IR0040": "idf_field",
    # MB_SR0041（旧 MB_IR0041）は SDRF の BioSample 参照だが、報告単位は列でも行でもなく
    # 「参照した accession」なので idf_field（field / value）の形をそのまま使う。
    "MB_SR0041": "idf_field",
    # --- IDF: protocol 要件 ---
    "MB_IR0017": "idf_protocol",
    "MB_IR0018": "idf_protocol",
    # --- IDF↔SDRF ---
    "MB_CR0001": "idf_sdrf",
    "MB_CR0002": "idf_sdrf",
    "MB_CR0003": "idf_sdrf",
    "MB_CR0004": "idf_sdrf",
    # --- 個別情報なし ---
    "MB_IR0020": "general",
    "MB_IR0037": "general",
}


def annotation_pattern(rule_id):
    """rule_id の annotation パターン名。表に無ければ "general"（annotation なし）。"""
    return ANNOTATION_PATTERNS.get(rule_id, "general")


# --- 再解析元 study の参照表記（MB_IR0038 / MB_CR0004 で共用）---------------
#
# Comment[Related study] は `DB:ID` 形式で書く。ただし MetaboBank の study accession
# （MTBKS＋自然数）は **同じ DB なので特別扱い**で、`MetaboBank:` prefix を付けても
# 付けなくてもよい。DB 名の CV 化は未実施で、キュレータが入れる項目なので緩く見る。
#
# この特別扱いの判定は **case-sensitive**。`MetaboBank:MTBKS1` / `MTBKS1` の表記でのみ
# accession として扱う（accession 自体が大文字表記なので揺れを認めない）。
_MTBKS_RE = re.compile(r"^(?:MetaboBank:)?(MTBKS\d+)$")
# DB:ID 形式。DB 側は `:` を含まない 1 文字以上、ID 側は 1 文字以上（中身は問わない）。
DB_ID_RE = re.compile(r"^[^:]+:.+$", re.S)


def mtbks_accession(value):
    """MetaboBank study accession なら prefix を外した `MTBKSnnn` を返す。違えば None。

    `MTBKS123` / `MetaboBank:MTBKS123` のどちらでも同じ値になる（prefix の有無だけを吸収）。
    判定は **case-sensitive** なので `mtbks123` / `metabobank:MTBKS123` は accession 扱いにしない。
    MB_CR0004 が IDF 側と SDRF 側の accession を突き合わせるのにも使う。
    """
    m = _MTBKS_RE.match((value or "").strip())
    return m.group(1) if m else None


def is_valid_related_study(value):
    """Comment[Related study] の値として認める形か（MTBKS 形式 または DB:ID 形式）。"""
    v = (value or "").strip()
    return bool(v) and (mtbks_accession(v) is not None or bool(DB_ID_RE.match(v)))


def null_values(context):
    nv = (context.definitions or {}).get("null_values", {})
    return set(nv.get("accepted", []))


def null_values_not_recommended(context):
    """非推奨 null 値の正規表現リスト（NA / N/A / Unknown / . / - 等）。"""
    nv = (context.definitions or {}).get("null_values", {})
    return list(nv.get("not_recommended", []))


def normalize_null(value, accepted, not_recommended, to_empty=False):
    r"""null 値の表記揺れ／非推奨表記を正規表記へ補正した値を返す（補正不要なら None）。

    biosample の `common/insdc_missing.normalize_null`（Ruby rule:1 準拠）と同じ二段構え。
    MB_IR0023 の autofix 提案と `cli._write_fixed` の書き出しを同じ判定で揃えるため、
    ここに一本化している。

    (a) 推奨 null の表記揺れ揃え: 小文字化＋空白除去して accepted と一致すれば正規表記へ
        （`Not Applicable` → `not applicable`）
    (b) 非推奨 null → `missing`: not_recommended の正規表現に値全体が一致（re.fullmatch,
        大文字小文字無視）したら `missing` へ（`N.A.` → `missing`）

    `to_empty=True`（`idf.autofix_null_to_empty` の項目）なら、null と判定できた時点で `""`
    にする。任意項目に null 値を書くこと自体が不正で「書かない」が正規の書き方のため。
    """
    v = (value or "").strip()
    if not v:
        return None
    fixed = None
    low_ns = re.sub(r"\s+", "", v.lower())
    for a in accepted:                                  # (a) 表記揺れ揃え
        if re.sub(r"\s+", "", a.lower()) == low_ns:
            fixed = a
            break
    if fixed is None:                                   # (b) 非推奨 null → missing
        for pat in not_recommended:
            try:
                if re.fullmatch(pat, v, re.I):
                    fixed = "missing"
                    break
            except re.error:
                continue
    if fixed is None:
        return None
    if to_empty:
        fixed = ""
    return None if fixed == value else fixed


class MbRule(SimpleRule):
    rule_id = "MB_RXXXX"

    def result(self, message=None, level=None, target=None, **extra):
        """SimpleRule.result に `desc`（rule の固定文）を必ず載せる。

        結果 JSON では `message` を rule の固定文にし、括弧書きの個別情報は annotation に
        移す（同じ文で束ねられるようにするため）。内部 dict の `message` は従来どおり
        1 行形式のまま残し（テキストレポートと CLI がこれを使う）、reporter が JSON を
        組むときに `desc` を message、従来の `message` を `detail` に写す。
        """
        r = super().result(message=message, level=level, target=target, **extra)
        r.setdefault("desc", self.description)
        return r
