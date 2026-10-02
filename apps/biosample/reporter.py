"""BioSample 検証結果のレポート出力（ddbj reporter と同様の体裁、独立実装）。検証は SSUB 単位。

出力（CLI の -j で切替）:
- 既定（テキスト）: reports/validation_report_summary.txt（info ヘッダ＋レベル別集計）
  ＋ validation_report_details.txt（サンプル別）。summary は標準出力にも表示する。
- JSON（`-j`）: reports/validation_report.json（web validator の result.json 互換 flat 構造）。
- autofix があれば reports/autofix_confirmation_summary.txt を -j の有無に関わらず出力する。
サンプル数は "(N sample(s))" 表記。summary/details とも先頭に info ヘッダ（Validation Date/Process Time/Data/Version）。
"""
import json
from collections import OrderedDict
from functools import lru_cache
from pathlib import Path

_LEVEL_ORDER = {"error": 0, "warning": 1, "info": 2}
_LEVEL_SECTIONS = ["info", "warning", "error"]  # 表示順（info→warning→error）
# ルール解説ページ（現行 validator の reference と同じアンカー規約）
_DOC_BASE = "https://www.ddbj.nig.ac.jp/biosample/validation-e.html#"

# ruby v の rule_class（biosample の全ルールが "BioSample"）。result.json の method / object に使う。
_RULE_CLASS = "BioSample"


@lru_cache(maxsize=1)
def _official_messages():
    """ルール別の公式メッセージ（rule_id -> message）。D-way 本番と同一文言にするための正典。

    出所は docs/docs/biosample/rules-official.txt の Message 列（＝ruby rule_config と一致）を
    オフラインで焼き込んだ apps/biosample/resources/rule_messages.json。"""
    path = Path(__file__).resolve().parent / "resources" / "rule_messages.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _official_message(rule_id, fallback=""):
    """rule_id の公式メッセージ。無ければ fallback（従来の動的メッセージ）を使う。"""
    return _official_messages().get(rule_id) or fallback


# 入力形式ごとの公式文言の差し替え。(rule_id, input_format) -> 文言。
#
# rule_messages.json は D-way 本番と同一文言にするための正典なので中身は変えない。
# 一方 BS_R0097/R0098 の公式文言は "XML document ..." と入力形式を名指ししており、
# XML 以外の入力にそのまま出すと嘘になる。差分はルール側に散らさずここに閉じ込める
# （どのルールがどの形式で公式文言から外れるかが、この表を見れば分かる）。
_FORMAT_MESSAGES = {
    ("BS_R0097", "record"): "DDBJ Record (JSON) document is not well-formed.",
    ("BS_R0098", "record"): "DDBJ Record (JSON) document is invalid against the schema.",
}


def _message(r):
    """結果 1 件の表示用メッセージ。公式文言が既定、形式差だけ _FORMAT_MESSAGES で上書き。
    個別の理由（どのフィールドがなぜ）は message ではなく annotation 側に出る。"""
    override = _FORMAT_MESSAGES.get((r["rule_id"], r.get("input_format")))
    if override:
        return override
    return _official_message(r["rule_id"], r["message"])


def _sorted(results):
    return sorted(results, key=lambda x: (_LEVEL_ORDER.get(x["level"], 9), x["rule_id"]))


def _sample_count_str(n):
    return f"{n} sample" if n == 1 else f"{n} samples"


def _info_header(kind, sample_count, input_name, submission_id, package, version, when, elapsed):
    return [
        f"=== Validation {kind} ===",
        f"Validation Date: {when}",
        f"Process Time: {elapsed} seconds",
        "Data: BioSample",
        f"Version: {version}",
        "",
        f"File: {input_name}",
        f"Submission ID: {submission_id or '-'}",
        f"Package: {package or '-'}",
        f"Samples: {sample_count}",
        "",
    ]


def _by_level(results):
    by = {lv: [] for lv in _LEVEL_SECTIONS}
    for r in _sorted(results):
        by.setdefault(r["level"], []).append(r)
    return by


def build_summary(results, sample_count, input_name, submission_id, package, version, when, elapsed):
    """summary 本文（info ヘッダ＋レベル別のルール:メッセージ、同一行は重複排除）。標準出力/ファイル共通。"""
    lines = _info_header("Summary", sample_count, input_name, submission_id, package, version, when, elapsed)
    by = _by_level(results)
    for lv in _LEVEL_SECTIONS:
        rs = by.get(lv) or []
        if not rs:
            continue
        lines.append(f"[ {lv.upper()} ]")
        seen = set()
        for r in rs:
            line = f"{r['rule_id']}:{_message(r)}"
            if line in seen:
                continue
            seen.add(line)
            lines.append(line)
        lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"


def build_details(results, records, sample_count, input_name, submission_id, package, version, when, elapsed):
    """details 本文（サンプル別）。行: rule_id:<識別子>:message。
    識別子は SAMD アクセッションがあれば SAMD のみ、無ければ sample_name（一文を短く保つ）。"""
    idmap = {}
    for rec in records or []:
        idmap[rec.sample_id] = (rec.accession, rec.sample_name)
    lines = _info_header("Details", sample_count, input_name, submission_id, package, version, when, elapsed)
    by = _by_level(results)
    for lv in _LEVEL_SECTIONS:
        rs = by.get(lv) or []
        if not rs:
            continue
        lines.append(f"[ {lv.upper()} ]")
        for r in rs:
            sid = r.get("sample")
            acc, name = idmap.get(sid, (None, sid))
            ident = acc or name or sid or "-"  # SAMD 優先（両方あれば SAMD のみ）
            msg = _message(r).replace(chr(10), " ")
            lines.append(f"{r['rule_id']}:{ident}:{msg}")
        lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"


def build_autofix_lines(results):
    """autofix 提案を (rule_id, old, new) で集約し 'N sample(s): 'old' -> 'new' [Rule: X]' の行リストを返す。"""
    agg = OrderedDict()
    for r in results:
        if not r.get("autofix"):
            continue
        old = r.get("old_value") or ""
        new = r.get("new_value")
        if new is None and r.get("new_taxid"):
            new = f"taxonomy_id={r.get('new_taxid')}"
        key = (r["rule_id"], old, new)
        agg.setdefault(key, set()).add(r.get("sample"))
    return [f"{_sample_count_str(len(s))}: '{old}' -> '{new}' [Rule: {rid}]"
            for (rid, old, new), s in agg.items()]


def write_text_reports(summary_text, details_text, out_dir):
    """summary/details テキストをファイルへ書き出す。"""
    if not out_dir:
        return
    reports = Path(out_dir) / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    (reports / "validation_report_summary.txt").write_text(summary_text, encoding="utf-8")
    (reports / "validation_report_details.txt").write_text(details_text, encoding="utf-8")


def write_autofix_confirmation(autofix_lines, out_dir):
    """autofix の内容を reports/autofix_confirmation_summary.txt に出力（-j の有無に関わらず）。"""
    if not out_dir or not autofix_lines:
        return
    reports = Path(out_dir) / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    body = "[ Auto-Fix ]\n" + "\n".join(autofix_lines) + "\n"
    (reports / "autofix_confirmation_summary.txt").write_text(body, encoding="utf-8")


def _annotation(r):
    """result dict から表示用 annotation 配列を構築（D-way 本番 ruby の表示パターンに合わせる）。

    annotation パターン（rule 表のコード。詳細は docs 参照）:
      GRP   group_no あり … Sample name ＋ "Sample group without distinguishing attribute"（BS_R0024）
      TAX   kind=organism ＋ old_taxid あり … organism/Suggested value (organism)/taxonomy_id/Suggested value (taxonomy_id)（BS_R0045）
      A1/A1F attribute あり … Attribute / Attribute value （＋autofix なら Suggested value）
    """
    sample = {"key": "Sample name", "value": r.get("sample") or ""}
    # GRP: 重複グループ番号（BS_R0024）
    if r.get("group_no") is not None:
        return [sample, {"key": "Sample group without distinguishing attribute", "value": str(r["group_no"])}]
    # TAX: organism/taxonomy 二重補正（BS_R0045）
    if r.get("kind") == "organism" and r.get("old_taxid") is not None:
        anno = [sample, {"key": "organism", "value": r.get("old_value") or ""}]
        if r.get("autofix") and r.get("new_value") is not None:
            anno.append({"key": "Suggested value (organism)", "suggested_value": [r.get("new_value")],
                         "target_key": "organism", "is_auto_annotation": True})
        anno.append({"key": "taxonomy_id", "value": r.get("old_taxid") or ""})
        if r.get("new_taxid"):
            anno.append({"key": "Suggested value (taxonomy_id)", "suggested_value": [str(r.get("new_taxid"))],
                         "target_key": "taxonomy_id", "is_auto_annotation": True})
        return anno
    # A2/A2F/MSG/NAMES/MULTI: rule が列を明示供給（anno_cols=[{key, value}, ...]）。
    # 名前付き属性列（現在値）や Attributes/Values・Message 等の固有列をそのまま並べる。
    cols = r.get("anno_cols")
    if cols:
        anno = [sample] + [{"key": c["key"], "value": c.get("value", "") or ""} for c in cols]
        # A2F: autofix があれば末尾に Suggested value（列見出しは "Suggested value"）。
        if r.get("autofix") and r.get("new_value") is not None:
            anno.append({"key": "Suggested value", "suggested_value": [r.get("new_value")],
                         "target_key": r.get("target_key") or "value", "is_auto_annotation": True})
        return anno
    # A1/A1F: 属性値系（Attribute / Attribute value ＋ autofix なら Suggested value）
    anno = [sample]
    attr = r.get("attribute")
    if attr:
        anno.append({"key": "Attribute", "value": attr})
        if r.get("old_value") is not None:
            anno.append({"key": "Attribute value", "value": r.get("old_value")})
    # autofix 提案（属性値置換 / organism 補正）
    if r.get("autofix") and r.get("new_value") is not None:
        target_key = "Attribute value" if attr else ("organism" if r.get("kind") == "organism" else "value")
        anno.append({
            "key": r.get("suggest_key") or "Suggested value",   # ruby の綴り差（例 R0012="Suggestion"）に対応
            "suggested_value": [r.get("new_value")],
            "target_key": target_key,
            "is_auto_annotation": True,
        })
    # organism 補正で taxonomy_id も補完する場合
    if r.get("new_taxid"):
        anno.append({
            "key": "Suggested value (taxonomy_id)",
            "suggested_value": [str(r.get("new_taxid"))],
            "target_key": "taxonomy_id",
            "is_auto_annotation": True,
        })
    return anno


_AUTO_ANNOTATION_MSG = "An automatically-generated correction will be applied."

# ruby が message 末尾に AUTO_ANNOTATION_MSG を付与する rule（add_error(auto_annotation: true)）。
# ruby staging API を全 fixture で実測して確定。annotation の is_auto_annotation とは独立で、
# 例えば R0045（organism/taxonomy 補正）は autofix だが接尾辞は付かない。
_AUTO_SUFFIX_RULES = frozenset({
    "BS_R0001", "BS_R0002", "BS_R0009", "BS_R0013", "BS_R0015",
    "BS_R0094", "BS_R0095", "BS_R0105", "BS_R0136",
})


def _error_obj(r, source):
    """result dict を web validator 互換の error_obj へ写像。"""
    msg = _message(r)
    # ruby と同様、対象 rule のみ公式文言の末尾に補正告知を付与する。
    if r["rule_id"] in _AUTO_SUFFIX_RULES:
        msg = f"{msg} {_AUTO_ANNOTATION_MSG}"
    return {
        "id": r["rule_id"],
        "message": msg,
        "reference": _DOC_BASE + r["rule_id"],
        "level": r["level"],
        "external": bool(r.get("external", False)),
        "method": "biosample",          # D-way は db 名(小文字)を期待。配列/大文字化は Jackson デシリアライズ失敗→画面空
        "object": _RULE_CLASS,          # 文字列 "BioSample"（配列にしない。同上）
        "source": source,
        "annotation": _annotation(r),
    }


def _stats(results):
    error_count = sum(1 for r in results if r["level"] == "error")
    warning_count = sum(1 for r in results if r["level"] == "warning")
    ext_err = sum(1 for r in results if r["level"] == "error" and r.get("external"))
    ext_warn = sum(1 for r in results if r["level"] == "warning" and r.get("external"))
    return {
        "error_count": error_count,
        "warning_count": warning_count,
        "error_type_count": {
            "common_error": error_count - ext_err,
            "common_warning": warning_count - ext_warn,
            "external_error": ext_err,
            "external_warning": ext_warn,
        },
        # biosample 単一 filetype のみ出力。D-way staging の AutoCorrectDataType enum に無いキーを送ると
        # Jackson デシリアライズが Duplicate key null 例外 → result_json=null → 画面が空になるため、
        # 全 db キー（all_db/bioproject/... 計13）は出さず biosample のみに戻した（enum の安全な部分集合）。
        "autocorrect": {"biosample": any(r.get("autofix") for r in results)},
    }


def build_result_json(results, input_name, version="unknown"):
    """web validator の result.json 互換（flat）な結果オブジェクトを返す。"""
    stats = _stats(results)
    return {
        "version": version,
        "validity": stats["error_count"] == 0,  # warning は validity を落とさない（ddbj と同じ）
        "stats": stats,
        "messages": [_error_obj(r, input_name) for r in _sorted(results)],
    }


def write_json_report(results, out_dir, input_name, version="unknown"):
    """<out_dir>/reports/validation_report.json に result.json 互換の JSON を出力。戻り値: 結果 dict。"""
    result = build_result_json(results, input_name, version)
    if out_dir:
        reports = Path(out_dir) / "reports"
        reports.mkdir(parents=True, exist_ok=True)
        (reports / "validation_report.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result
