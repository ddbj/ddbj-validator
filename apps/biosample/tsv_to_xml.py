"""TSV（登録 SSUB TSV 形式）を BioSample XML（<BioSampleSet>）へ変換する。

- TSV: 先頭行ヘッダ（属性名、必須は先頭 '*'）、`biosample_accession` 先頭列、2 行目以降が各サンプル値。
- パッケージ: ファイル名 `SSUBxxxxxx_<Package>.txt` から取得（最初の '_' で分割。Package 名のドットは保持）。
- Owner（登録者）/access/管理日付は TSV に無いため **固定値テンプレート**を埋め込む（テスト用途）。
変換後の XML 文字列を返し、検証は XML 一本のパスで行う（既存 bs validator の置換方針）。
"""
import csv
import datetime
import xml.etree.ElementTree as ET
from pathlib import Path
from xml.dom import minidom
from common.jst import today as jst_today

# テスト用固定値（ハーネス/CLI から差し替え可能）
DEFAULT_FIXED = {
    "access": "public",
    "organization": "BSI",
    "contacts": [
        ("Hanako", "Mishima", "test1@ddbj.nig.ac.jp"),
        ("Fuji", "Mishima", "test2@ddbj.nig.ac.jp"),
        ("Rakuju", "Mishima", "test3@ddbj.nig.ac.jp"),
    ],
}

# Description/Ids へ振り分ける特別列（残りは Attributes へ）。
# sample_title/description/organism/taxonomy_id は Description 要素へ（登録システム xml_convertor 準拠）。
_SPECIAL = {"biosample_accession", "sample_title", "description", "organism", "taxonomy_id"}


def parse_filename(tsv_path):
    """`<SSUBid>.<Package>.txt` から (submission_id, package) を返す。最初の '.' で分割。
    submission_id は SSUB\\d+ でドットを含まないため、package 名がドットを含む場合（MIGS.ba /
    Pathogen.cl / SARS-CoV-2.cl 等）も正しく分離できる。例: SSUB000001.MIGS.ba.txt → (SSUB000001, MIGS.ba)。
    パターンに合わなければ (stem, None)。"""
    stem = Path(tsv_path).stem  # 末尾拡張子（.txt/.tsv）を除去
    if "." in stem:
        sub_id, package = stem.split(".", 1)
        return sub_id, package
    return stem, None


def _today():
    # 出力は +09:00 を付けた JST 表記なので、日付も JST で取る（コンテナ TZ に依存させない）
    return jst_today().isoformat()


def tsv_to_xml(tsv_path, fixed=None, package=None, submission_id=None):
    """TSV ファイルを XML 文字列へ変換して返す。"""
    fixed = fixed or DEFAULT_FIXED
    fn_sub, fn_pkg = parse_filename(tsv_path)
    submission_id = submission_id or fn_sub
    package = package or fn_pkg

    with open(tsv_path, encoding="utf-8", newline="") as f:
        reader = csv.reader(f, delimiter="\t")
        rows = [r for r in reader]
    if not rows:
        return None
    header = [h.lstrip("*").strip() for h in rows[0]]  # '*'（必須マーク）を除去

    today = _today()
    root = ET.Element("BioSampleSet")
    for row in rows[1:]:
        if not any(c.strip() for c in row):
            continue
        cells = dict(zip(header, row))
        bs = ET.SubElement(root, "BioSample", {
            "last_update": f"{today}T00:00:00+09:00",
            "publication_date": f"{today}T00:00:00+09:00",
            "access": fixed["access"],
        })
        # Ids
        ids = ET.SubElement(bs, "Ids")
        acc = cells.get("biosample_accession", "").strip()
        id_el = ET.SubElement(ids, "Id", {"namespace": "BioSample", "is_primary": "1"})
        id_el.text = acc
        # Description
        desc = ET.SubElement(bs, "Description")
        sn = ET.SubElement(desc, "SampleName"); sn.text = cells.get("sample_name", "").strip()
        ti = ET.SubElement(desc, "Title"); ti.text = cells.get("sample_title", "").strip()
        org_attrs = {}
        tax = cells.get("taxonomy_id", "").strip()
        if tax:
            org_attrs["taxonomy_id"] = tax
        org = ET.SubElement(desc, "Organism", org_attrs)
        on = ET.SubElement(org, "OrganismName"); on.text = cells.get("organism", "").strip()
        # description → Description/Comment/Paragraph（登録システム準拠。Attribute にはしない）
        desc_text = cells.get("description", "").strip()
        if desc_text:
            comment = ET.SubElement(desc, "Comment")
            ET.SubElement(comment, "Paragraph").text = desc_text
        # Owner（固定値）
        owner = ET.SubElement(bs, "Owner")
        oname = ET.SubElement(owner, "Name"); oname.text = fixed["organization"]
        contacts = ET.SubElement(owner, "Contacts")
        for first, last, email in fixed["contacts"]:
            c = ET.SubElement(contacts, "Contact", {"email": email})
            nm = ET.SubElement(c, "Name")
            ET.SubElement(nm, "First").text = first
            ET.SubElement(nm, "Last").text = last
        # Models（パッケージ）
        models = ET.SubElement(bs, "Models")
        ET.SubElement(models, "Model").text = package or ""
        # Attributes（special 列以外、空値は省略＝実 XML と同様）
        attrs = ET.SubElement(bs, "Attributes")
        for name in header:
            if name in _SPECIAL:
                continue
            val = cells.get(name, "").strip()
            if val == "":
                continue
            a = ET.SubElement(attrs, "Attribute", {"attribute_name": name})
            a.text = val

    rough = ET.tostring(root, encoding="utf-8")
    return minidom.parseString(rough).toprettyxml(indent="  ", encoding="UTF-8").decode("utf-8")
