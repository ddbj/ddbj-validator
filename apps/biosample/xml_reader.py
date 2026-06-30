"""BioSample XML（<BioSampleSet>）のパースと整形チェック。

- R0097: XML well-formed（パース失敗で検出）。
- R0098: XSD スキーマ検証（lxml/xmlschema/xmllint が無い環境では当面スキップ。後続で導入）。
入力 XML をパースして BioSampleSubmission を返す。
"""
import xml.etree.ElementTree as ET
from pathlib import Path

from apps.biosample.model import BioSampleRecord, BioSampleSubmission

_XSD = Path(__file__).resolve().parent / "resources" / "xsd" / "biosample_set.xsd"
_SCHEMA_ERR_CAP = 20  # スキーマエラーは大量に出るため上限


def _text(elem, path):
    found = elem.find(path)
    return found.text.strip() if (found is not None and found.text) else None


def schema_validate(xml_path):
    """lxml(libxml2) で XSD スキーマ検証（R0098）。
    戻り値: 結果 dict のリスト（well-formed 失敗は R0097、schema 不適合は R0098）。
    lxml が無い／XSD 読込失敗時は空（検証スキップ）。
    """
    try:
        import lxml.etree as LE
    except ImportError:
        return []
    try:
        doc = LE.parse(str(xml_path))
    except LE.XMLSyntaxError as e:
        return [{"rule_id": "BS_R0097", "level": "error", "target": "#file_format",
                 "sample": None, "message": f"XML document is not well-formed. ({e})"}]
    try:
        schema = LE.XMLSchema(LE.parse(str(_XSD)))
    except Exception:
        return []  # XSD 自体が読めなければ検証スキップ
    if schema.validate(doc):
        return []
    out = []
    for err in list(schema.error_log)[:_SCHEMA_ERR_CAP]:
        out.append({"rule_id": "BS_R0098", "level": "error", "target": "#file_format",
                    "sample": None, "message": f"Invalid against schema (line {err.line}): {err.message}"})
    return out


def parse_xml(xml_path, submission_id=None, account=None):
    """XML ファイルを BioSampleSubmission へ。戻り値: (submission, errors)。
    errors は整形不正など、パース前段で確定する結果（R0097 等）のリスト。
    """
    # R0097(well-formed) / R0098(XSD) は lxml で検証
    errors = schema_validate(xml_path)
    if any(e["rule_id"] == "BS_R0097" for e in errors):
        return None, errors  # 整形不正はモデル構築不可

    try:
        tree = ET.parse(xml_path)
    except ET.ParseError as e:
        errors.append({
            "rule_id": "BS_R0097", "level": "error", "target": "#file_format",
            "sample": None, "message": f"XML document is not well-formed. ({e})",
        })
        return None, errors

    root = tree.getroot()
    sub = BioSampleSubmission(submission_id=submission_id, account=account)

    for bs in root.findall(".//BioSample"):
        rec = BioSampleRecord(raw=bs)
        rec.access = bs.get("access")
        rec.accession = _text(bs, "./Ids/Id")
        rec.sample_name = _text(bs, "./Description/SampleName")
        rec.title = _text(bs, "./Description/Title")
        org = bs.find("./Description/Organism")
        if org is not None:
            rec.taxonomy_id = org.get("taxonomy_id")
            rec.organism = _text(org, "./OrganismName") or (org.text.strip() if org.text else None)
        rec.package = _text(bs, "./Models/Model")
        for attr in bs.findall("./Attributes/Attribute"):
            name = attr.get("attribute_name")
            if name is None:
                continue
            rec.attributes.setdefault(name, []).append((attr.text or "").strip())
        # sample_name は属性側にもあるため、Description 側が無ければ属性から補完
        if not rec.sample_name:
            rec.sample_name = rec.attr("sample_name")
        sub.records.append(rec)

    # サブミッション代表パッケージ（通常は全サンプル共通）
    pkgs = {r.package for r in sub.records if r.package}
    if len(pkgs) == 1:
        sub.package = next(iter(pkgs))
    elif pkgs:
        sub.package = sorted(pkgs)[0]

    return sub, errors
