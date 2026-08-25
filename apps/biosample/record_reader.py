"""DDBJ Record（v3 JSON）のパース。xml_reader と同じ契約でモデルを組む。

- BS_R0097: JSON well-formed（パース失敗で検出）。
- BS_R0098: v3 スキーマ検証（`ddbj_record` が import できるときのみ。無ければスキップ）。
入力レコードをパースして BioSampleSubmission を返す。ルールは XML/TSV/Record の
差異を意識しない（model.py の契約）。

v3 → BioSampleRecord の対応:

    samples[].accession              -> accession
    samples[].alias                  -> sample_name（属性 sample_name があればそちら優先）
    samples[].title                  -> title（属性 sample_title からも補完）
    samples[].description            -> 属性 description
    samples[].organism.name          -> organism（属性 organism からも補完）
    samples[].organism.taxonomy_id   -> taxonomy_id（属性 taxonomy_id からも補完）
    samples[].package                -> package
    samples[].attributes[]           -> attributes（同名は XML と同じくリストで保持）

v3 に無いもの:

    submission_id  -- SSUB は record が持たない。呼び出し側（-s / web api の form）から渡す。
    account        -- record の submission.submitters[] は email であって account id ではない。
    access         -- BioSample XML の @access に相当する slot が無い。ルールも参照していない。

属性からの補完（organism / sample_name / title）は XML reader の同種の補完と同じ理由で
必要になる。v3 では typed slot と属性バッグの両方に同じ値が載り得て、どちらが埋まるかは
producer 次第だからである。片方しか見ないと、taxonomy 系 56 参照が黙って何も判定しない
という一番まずい壊れ方をする。
"""
import json
import sys
from pathlib import Path

from apps.biosample.model import BioSampleRecord, BioSampleSubmission

_SCHEMA_ERR_CAP = 20   # スキーマエラーは大量に出るため上限（xml_reader と同じ）
_warned_no_schema = False


def _format_error(rule_id, message, field=None, reason=None):
    """入力形式そのものの不備（BS_R0097/R0098）を 1 件組む。

    `official_message=False` を立てるのは、これらの公式文言が "XML document ..." と
    入力形式を名指ししているから。Record 入力にそのまま出すと嘘になる。
    どのフィールドが悪いかは message でなく anno_cols に置く。公式文言を使う経路では
    message が丸ごと差し替わってしまい、XML 入力では行番号が同じ理由で失われている。
    """
    r = {"rule_id": rule_id, "level": "error", "target": "#file_format",
         "sample": None, "message": message, "official_message": False}
    cols = []
    if field:
        cols.append({"key": "Field", "value": field})
    if reason:
        cols.append({"key": "Reason", "value": reason})
    if cols:
        r["anno_cols"] = cols
    return r


def _schema_validate(record):
    """BS_R0098: v3 スキーマ検証。`ddbj_record` が無ければスキップ（空）。

    lxml が無いとき XSD 検証をスキップする xml_reader と同じ方針。message の括弧内は
    v3 のフィールドパス（例 `samples.3.organism.taxonomy_id`）で、XML の行番号に相当する。
    """
    global _warned_no_schema
    try:
        from ddbj_record.schema.v3 import DdbjRecord
        from pydantic import ValidationError
    except ImportError:
        # スキップしたことは言う。黙ってスキップすると「スキーマ違反ゼロ」と区別が付かない。
        if not _warned_no_schema:
            print("[WARN] ddbj-record が入っていないため v3 スキーマ検証 (BS_R0098) をスキップします "
                  "(pip install '.[record]')", file=sys.stderr)
            _warned_no_schema = True
        return []
    try:
        DdbjRecord.model_validate(record)
    except ValidationError as e:
        return [_format_error("BS_R0098", "Record is invalid against the DDBJ Record v3 schema.",
                              field=".".join(str(x) for x in err["loc"]), reason=err["msg"])
                for err in e.errors()[:_SCHEMA_ERR_CAP]]
    return []


def _attributes(sample):
    """v3 attributes[] -> {name: [value, ...]}。同名属性は XML と同じくリストで保持する
    （BS_R0061 の重複検出は「同名が複数ある」ことを見るため、ここで潰すと検出できない）。"""
    out = {}
    for attr in sample.get("attributes") or []:
        name = attr.get("name")
        if name is None:
            continue
        out.setdefault(name, []).append((attr.get("value") or "").strip())
    return out


def _build_record(sample):
    rec = BioSampleRecord(raw=sample)
    rec.attributes = _attributes(sample)
    rec.accession = sample.get("accession")
    rec.package = sample.get("package")

    # typed slot 優先、無ければ属性バッグ（どちらに載るかは producer 次第）
    rec.sample_name = rec.attr("sample_name") or sample.get("alias")
    rec.title = sample.get("title") or rec.attr("sample_title")

    organism = sample.get("organism") or {}
    rec.organism = organism.get("name") or rec.attr("organism")
    tax_id = organism.get("taxonomy_id")
    # 属性由来の taxonomy_id は str、typed slot は int。ルールは str 前提（`str(...).isdigit()`）。
    rec.taxonomy_id = str(tax_id) if tax_id is not None else rec.attr("taxonomy_id")

    # XML reader と同じ lift: typed slot の値も属性として見えるようにする
    # （sample_title/description が R0013 autocleanup 等の属性処理対象になる）。
    if rec.title and "sample_title" not in rec.attributes:
        rec.attributes["sample_title"] = [rec.title]
    description = sample.get("description")
    if description and "description" not in rec.attributes:
        rec.attributes["description"] = [description]

    return rec


def parse_record(record_path, submission_id=None, account=None):
    """DDBJ Record ファイルを BioSampleSubmission へ。戻り値: (submission, errors)。
    errors は整形不正など、パース前段で確定する結果（BS_R0097/R0098）のリスト。
    submission=None は「JSON として読めなかった」だけを意味する。`samples` を持たない
    レコードは records=[] の submission を返す（xml_reader が空の BioSampleSet に対して
    そうするのと同じ）。「検証対象がゼロ」を「指摘ゼロ」と混同させないため、
    どう扱うかは呼び出し側の責任にしてある。
    """
    try:
        record = json.loads(Path(record_path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
        return None, [_format_error("BS_R0097", "JSON document is not well-formed.", reason=str(e))]
    if not isinstance(record, dict):
        return None, [_format_error("BS_R0097", "JSON document is not a DDBJ Record object.")]

    errors = _schema_validate(record)

    sub = BioSampleSubmission(submission_id=submission_id, account=account)
    sub.records = [_build_record(s) for s in record.get("samples") or []]

    # サブミッション代表パッケージ（xml_reader と同じ決め方。通常は全サンプル共通）
    pkgs = {r.package for r in sub.records if r.package}
    if len(pkgs) == 1:
        sub.package = next(iter(pkgs))
    elif pkgs:
        sub.package = sorted(pkgs)[0]

    return sub, errors
