"""BioProject XML のパース。

- BP_R0001: XML well-formed（パース失敗で検出）。
- BP_R0002: XSD スキーマ検証（XSD が bundle され lxml があるときのみ。無ければスキップ）。
- BP_R0037: 1 XML に複数 project → error。
戻り値: (BioProjectSubmission | None, pre_errors[])。パース不可なら submission=None。
"""
import defusedxml.ElementTree as ET
from apps.bioproject.model import BioProjectRecord, BioProjectSubmission, Publication


def _text(el):
    return el.text.strip() if el is not None and el.text else None


def _build_record(proj):
    """内側 Project 要素から BioProjectRecord を組む。"""
    rec = BioProjectRecord(raw=proj)
    arch = proj.find("./ProjectID/ArchiveID")
    if arch is not None:
        rec.accession = arch.get("accession")
        rec.archive = arch.get("archive")
    descr = proj.find("./ProjectDescr")
    if descr is not None:
        rec.title = _text(descr.find("./Title"))
        rec.description = _text(descr.find("./Description"))
        rec.release_date = _text(descr.find("./ProjectReleaseDate"))
        for pub in descr.findall("./Publication"):
            rec.publications.append(Publication(
                id=(pub.get("id") or "").strip() or None,
                db_type=_text(pub.find("./DbType")),
                reference=_text(pub.find("./Reference"))))
    ptype = proj.find("./ProjectType")
    if ptype is not None:
        if ptype.find("./ProjectTypeTopAdmin") is not None:
            rec.project_kind = "umbrella"
            rec.top_admin_subtype = ptype.find("./ProjectTypeTopAdmin").get("subtype")
        elif ptype.find("./ProjectTypeSubmission") is not None:
            rec.project_kind = "submission"
            tgt = ptype.find(".//Target")
            if tgt is not None:
                rec.sample_scope = tgt.get("sample_scope")
                rec.material = tgt.get("material")
                rec.capture = tgt.get("capture")
            m = ptype.find(".//Method")
            if m is not None:
                rec.method_type = m.get("method_type")
            for d in ptype.findall(".//Objectives/Data"):
                if d.get("data_type"):
                    rec.data_types.append(d.get("data_type"))
            for dt in ptype.findall(".//ProjectDataTypeSet/DataType"):
                if _text(dt):
                    rec.data_types.append(_text(dt))
        elif ptype.find("./ProjectTypeTopSingleOrganism") is not None:
            rec.project_kind = "single_organism"
        else:
            rec.project_kind = "other"
    # Organism は project_kind に依らず ProjectType 配下のどこかにある
    org = proj.find(".//Organism")
    if org is not None:
        rec.tax_id = org.get("taxID")
        rec.organism_name = _text(org.find("./OrganismName"))
    for ltp in proj.findall("./LocusTagPrefix"):
        rec.locus_tags.append({"prefix": _text(ltp), "biosample_id": ltp.get("biosample_id")})
    return rec


def parse_xml(xml_path, account=None):
    try:
        tree = ET.parse(xml_path)
    except Exception as e:
        return None, [{"rule_id": "BP_R0001", "level": "error", "target": "#file_format",
                       "sample": None, "message": f"XML document is not well-formed. ({e})"}]
    root = tree.getroot()
    projects = root.findall("./Package/Project/Project")
    if not projects:  # 構造が想定外（Project 無し）
        projects = root.findall(".//Project/Project")
    pre_errors = []
    if len(projects) > 1:
        pre_errors.append({"rule_id": "BP_R0037", "level": "error", "target": "#file_format",
                           "sample": None, "message": "Only one project is allowed in BioProject XML."})
    sub = BioProjectSubmission(records=[_build_record(p) for p in projects], account=account)
    return sub, pre_errors
