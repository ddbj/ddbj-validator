"""DDBJ Record（v3 JSON）のパース。xml_reader と同じ契約でモデルを組む。

- BS_R0097: JSON well-formed（パース失敗で検出）。
- BS_R0098: 形状・スキーマ違反。`ddbj_record` があれば v3 スキーマで、無くても
  reader が前提にしている形だけは自前で確かめる（`_shape_errors`）。

入力レコードをパースして BioSampleSubmission を返す。ルールは XML/TSV/Record の
差異を意識しない（model.py の契約）。

v3 → BioSampleRecord の対応:

    samples[].accession              -> accession
    samples[].alias                  -> sample_name（無ければ属性 sample_name）
    samples[].title                  -> title（無ければ属性 sample_title）
    samples[].description            -> 属性 description
    samples[].organism.name          -> organism（無ければ属性 organism。属性側は取り込まない）
    samples[].organism.taxonomy_id   -> taxonomy_id（無ければ属性 taxonomy_id。同上）
    samples[].package                -> package
    samples[].attributes[]           -> attributes（同名は XML と同じくリストで保持）

typed slot を先に見るのは xml_reader と揃えるためで、`alias` は v3 における
サンプルの識別子でもある（正規化のキー、公開 XML の突合キー）。属性バッグを
先に見ると、typed slot だけが更新されたサンプルで、どこにも表示されない値を
識別子にしてしまう。逆に属性バッグを見ないと、typed slot に載せない producer の
レコードで taxonomy 系の 56 箇所が黙って何も判定しない。どちらも要る。

値は全て strip する。xml_reader は `_text` で全ての値を strip しており、
strip しないと " Microbe " が未知パッケージ（BS_R0026）になった上で、
パッケージ定義に依存する BS_R0027/R0036/R0001/R0100 が丸ごと黙って飛ぶ。

`organism` / `taxonomy_id` は typed slot へ引き上げたあと**属性バッグから外す**。
BioSample の XML はこの 2 つを `Description/Organism` に置き、`<Attributes>` には
残さない（D-way の実データで確認済み）。producer によっては v3 の両方に載せるが、
バッグにも残すと属性を総なめするルールが余分な行を見る。実害があるのは BS_R0024 で、
organism だけが違う 2 サンプルが「区別情報あり」と見なされ、本来出るはずの
「区別情報が無い」警告が出なくなる。ルール側は `organism` / `taxonomy_id` を
**属性としては一切読んでいない**（読むのは rec.organism / rec.taxonomy_id）ので、
外して失われる判定は無い。`sample_title` / `description` は逆に xml_reader が
バッグへ入れる側なので残す。

v3 に無いもの / 見ていないもの:

    submission_id  -- SSUB は record が持たない。呼び出し側（-s / web api の form）から渡す。
                      渡されないと BS_R0091 が自分自身の locus_tag_prefix を重複と報告するため、
                      無い場合は警告する。
    account        -- record の submission.submitters[] は email であって account id ではない。
    access         -- BioSample XML の @access に相当する slot が無い。ルールも参照していない。
    attributes[].unit -- BioSample の XML/TSV に単位の概念が無く、ルールも単位を見ない。
                      値だけを検証する。単位付きの値をどう検証するかは未決（README 参照）。
"""
import json
import sys
from pathlib import Path

from apps.biosample.model import BioSampleRecord, BioSampleSubmission

_SCHEMA_ERR_CAP = 20   # スキーマエラーは大量に出るため上限（xml_reader と同じ）
_warned_no_schema = False


def _format_error(rule_id, message, field=None, detail=None):
    """入力形式そのものの不備（BS_R0097/R0098）を 1 件組む。

    `input_format="record"` を載せるのは、これらの公式文言が "XML document ..." と
    入力形式を名指ししているから（reporter._FORMAT_MESSAGES が形式に合った文言へ差し替える）。
    どこがなぜ悪いかは message でなく anno_cols に置く。公式文言を使う経路では message が
    丸ごと差し替わってしまい、XML 入力では行番号が同じ理由で失われている。
    """
    r = {"rule_id": rule_id, "level": "error", "target": "#file_format",
         "sample": None, "message": message, "input_format": "record"}
    cols = []
    if field:
        cols.append({"key": "Field", "value": field})
    cols.append({"key": "Message", "value": detail or message})
    r["anno_cols"] = cols
    return r


def _schema_error(field, detail):
    return _format_error("BS_R0098", "Record is invalid against the DDBJ Record v3 schema.",
                         field=field, detail=detail)


def _shape_errors(record):
    """reader が前提にしている形だけを確かめる。

    スキーマ検証（`ddbj_record`）は任意インストールなので、これが無いと型の違う
    レコードで reader が AttributeError で落ちる。JSON では XML と違って
    「読めるが型が違う」があり、しかも落ち方が「終了コード 1」＝ web api では
    「検証は終わった」と同じ顔をする。前提は前提として自分で確かめる。

    フィールドパスは pydantic の loc と同じ書き方（`samples.3.attributes.2.value`）。
    """
    out = []

    def bad(field, expected, value):
        out.append(_schema_error(field, f"Expected {expected}, got {type(value).__name__}"))

    samples = record.get("samples")
    if samples is None:
        return out
    if not isinstance(samples, list):
        bad("samples", "a list", samples)
        return out

    for i, sample in enumerate(samples):
        if len(out) >= _SCHEMA_ERR_CAP:
            break
        at = f"samples.{i}"
        if not isinstance(sample, dict):
            bad(at, "an object", sample)
            continue
        for key in ("accession", "alias", "title", "description", "package"):
            value = sample.get(key)
            if value is not None and not isinstance(value, str):
                bad(f"{at}.{key}", "a string", value)
        organism = sample.get("organism")
        if organism is not None:
            if not isinstance(organism, dict):
                bad(f"{at}.organism", "an object", organism)
            else:
                if organism.get("name") is not None and not isinstance(organism["name"], str):
                    bad(f"{at}.organism.name", "a string", organism["name"])
                tax_id = organism.get("taxonomy_id")
                if tax_id is not None and not isinstance(tax_id, (int, str)):
                    bad(f"{at}.organism.taxonomy_id", "an integer", tax_id)
        attributes = sample.get("attributes")
        if attributes is None:
            continue
        if not isinstance(attributes, list):
            bad(f"{at}.attributes", "a list", attributes)
            continue
        for j, attr in enumerate(attributes):
            if not isinstance(attr, dict):
                bad(f"{at}.attributes.{j}", "an object", attr)
                continue
            for key in ("name", "value"):
                value = attr.get(key)
                if value is not None and not isinstance(value, str):
                    bad(f"{at}.attributes.{j}.{key}", "a string", value)
            if attr.get("name") is None:
                # スキーマ上は name も nullable だが、名前の無い属性は検証しようがない。
                # 黙って捨てると「登録者が書いていない」と報告することになる。
                out.append(_schema_error(
                    f"{at}.attributes.{j}.name",
                    f"Attribute without a name cannot be validated "
                    f"(value={attr.get('value')!r})"))

    return out[:_SCHEMA_ERR_CAP]


def _schema_validate(record):
    """BS_R0098: v3 スキーマ検証。`ddbj_record` が無ければ形状チェックだけに落とす。

    lxml が無いとき XSD 検証をスキップする xml_reader と同じ方針だが、スキップしたことは言う。
    黙ってスキップすると「スキーマ違反ゼロ」と区別が付かない。
    """
    global _warned_no_schema
    try:
        from ddbj_record.schema.v3 import DdbjRecord
        from pydantic import ValidationError
    except ImportError:
        if not _warned_no_schema:
            print("[WARN] ddbj-record が入っていないため v3 スキーマ検証 (BS_R0098) は "
                  "reader が前提とする形の確認のみになります (pip install '.[record]')",
                  file=sys.stderr)
            _warned_no_schema = True
        return []
    try:
        DdbjRecord.model_validate(record)
    except ValidationError as e:
        return [_schema_error(".".join(str(x) for x in err["loc"]), err["msg"])
                for err in e.errors()[:_SCHEMA_ERR_CAP]]
    return []


def _text(value):
    """値を xml_reader の `_text` と同じ形に揃える（strip、空は None）。"""
    if not isinstance(value, str):
        return None
    return value.strip() or None


def _attributes(sample):
    """v3 attributes[] -> {name: [value, ...]}。同名属性は XML と同じくリストで保持する
    （BS_R0061 の重複検出は「同名が複数ある」ことを見るため、ここで潰すと検出できない）。
    名前の無い属性は落とす。落としたことは `_shape_errors` が報告済み。"""
    out = {}
    for attr in sample.get("attributes") or []:
        name = attr.get("name")
        if not isinstance(name, str):
            continue
        value = attr.get("value")
        out.setdefault(name, []).append(value.strip() if isinstance(value, str) else "")
    return out


# typed slot へ引き上げたあと属性バッグから外す名前。理由はモジュール docstring 参照。
_LIFTED_OUT_OF_BAG = ("organism", "taxonomy_id")


def _build_record(sample):
    rec = BioSampleRecord(raw=sample)
    rec.attributes = _attributes(sample)
    rec.accession = _text(sample.get("accession"))
    rec.package = _text(sample.get("package"))

    # typed slot 優先、無ければ属性バッグ（どちらに載るかは producer 次第）
    rec.sample_name = _text(sample.get("alias")) or rec.attr("sample_name")
    rec.title = _text(sample.get("title")) or rec.attr("sample_title")

    organism = sample.get("organism") or {}
    rec.organism = _text(organism.get("name")) or rec.attr("organism")
    tax_id = organism.get("taxonomy_id")
    # 属性由来の taxonomy_id は str、typed slot は int。ルールは str を前提にしている
    # （`is_missing_value` が値を strip するので、int が来ると AttributeError になる）。
    rec.taxonomy_id = str(tax_id).strip() if tax_id is not None else rec.attr("taxonomy_id")
    dropped = {name: rec.attributes.pop(name) for name in _LIFTED_OUT_OF_BAG
               if name in rec.attributes}

    # XML reader と同じ lift: typed slot の値も属性として見えるようにする
    # （sample_title/description が R0013 autocleanup 等の属性処理対象になる）。
    _warn_if_disagreed(rec, dropped)

    if rec.title and "sample_title" not in rec.attributes:
        rec.attributes["sample_title"] = [rec.title]
    description = _text(sample.get("description"))
    if description and "description" not in rec.attributes:
        rec.attributes["description"] = [description]

    return rec


_disagreements = 0   # parse_record 1 回ごとにリセットする（ハーネスは同一プロセスで何度も呼ぶ）


def _warn_if_disagreed(rec, dropped):
    """バッグから外した organism / taxonomy_id が typed slot と食い違っていたら言う。

    typed slot を採るのが本 reader の方針だが、食い違いは producer 側の不整合であって
    黙って捨てるべきものではない。ルール ID を持たないので stderr に出す。
    件数が出るので最初の 1 件だけ具体的に書き、以降は数える。
    """
    global _disagreements
    for name, values in dropped.items():
        current = rec.organism if name == "organism" else rec.taxonomy_id
        if values and values[0] and current and values[0] != str(current):
            _disagreements += 1
            if _disagreements == 1:
                print(f"[WARN] typed slot と属性で {name} が食い違っています。typed slot を"
                      f"採用します (sample={rec.sample_id!r}: {current!r} / 属性={values[0]!r})。"
                      f"以降の食い違いは件数のみ数えます。", file=sys.stderr)


def parse_record(record_path, submission_id=None, account=None):
    """DDBJ Record ファイルを BioSampleSubmission へ。戻り値: (submission, errors)。

    errors は整形不正など、パース前段で確定する結果（BS_R0097/R0098）のリスト。
    submission=None は「モデルを組めなかった」を意味する。JSON として読めなかった場合と、
    形が違う場合の両方。**形が違うレコードでモデルを組もうとしない**のが XML との違いで、
    XML なら中身は全て文字列なので不正でもモデルは組めるが、JSON のスキーマ違反は
    そのまま型違反であり、読み進めれば落ちる。

    `samples` を持たないレコードは records=[] の submission を返す（xml_reader が空の
    BioSampleSet に対してそうするのと同じ）。「検証対象がゼロ」を「指摘ゼロ」と
    混同させないため、どう扱うかは呼び出し側の責任にしてある。
    """
    try:
        record = json.loads(Path(record_path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, RecursionError) as e:
        return None, [_format_error("BS_R0097", "JSON document is not well-formed.", detail=str(e))]
    if not isinstance(record, dict):
        return None, [_format_error("BS_R0097", "JSON document is not a DDBJ Record object.")]

    # 形が違えばモデルは組めないのでここで止まる。スキーマ違反のうち reader が触らない
    # 部分（未知のキー等）は報告したうえで検証は続ける。触る部分は _shape_errors が
    # 全て見ているので、続けても落ちない。
    shape_errors = _shape_errors(record)
    if shape_errors:
        return None, shape_errors

    errors = _schema_validate(record)

    global _disagreements
    _disagreements = 0

    sub = BioSampleSubmission(submission_id=submission_id, account=account)
    sub.records = [_build_record(s) for s in record.get("samples") or []]

    # サブミッション代表パッケージ（xml_reader と同じ決め方。通常は全サンプル共通）
    pkgs = {r.package for r in sub.records if r.package}
    if len(pkgs) == 1:
        sub.package = next(iter(pkgs))
    elif pkgs:
        sub.package = sorted(pkgs)[0]

    if _disagreements > 1:
        print(f"[WARN] typed slot と属性の食い違いは全部で {_disagreements} 件でした。",
              file=sys.stderr)

    return sub, errors
