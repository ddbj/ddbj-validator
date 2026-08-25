"""BioSample autofix 適用層。

方針（ddbj の対話式とは異なる）:
- **全自動適用**（対話なし）。検証結果のうち autofix 提案を持つものを全て適用する。
- 修正済みファイルを `<out_dir>/fixed/` に出力する。形式は入力に従う: XML/TSV 入力なら
  XML、DDBJ Record 入力なら Record（JSON）。提案そのもの（attribute/old_value/new_value）は
  形式に依らないので、形式ごとに違うのは適用先の書き方だけである。

autofix 提案は結果 dict に次を持つ（BsRule.result の extra 経由）:
    autofix=True, attribute=<attr_name>, old_value=<現値>, new_value=<修正値>
    （kind 省略時は "attribute_value" として属性値を置換）

サンプル対応付けは result["sample"]（sample_name か accession）と
XML の SampleName / Ids/Id を突き合わせる。
"""
import json
import xml.etree.ElementTree as ET
from pathlib import Path


def _sample_identity(bs_elem):
    """BioSample 要素の識別子候補（sample_name, accession）を返す。"""
    name = None
    n = bs_elem.find("./Description/SampleName")
    if n is not None and n.text:
        name = n.text.strip()
    if not name:
        for a in bs_elem.findall("./Attributes/Attribute"):
            if a.get("attribute_name") == "sample_name" and a.text:
                name = a.text.strip()
                break
    acc = None
    i = bs_elem.find("./Ids/Id")
    if i is not None and i.text:
        acc = i.text.strip()
    return name, acc


def collect_proposals(results):
    """検証結果から autofix 提案を抽出。
    戻り値: {sample_id: [proposal_dict, ...]}。proposal_dict は kind を含む結果 dict そのもの。
    対応 kind:
      - "attribute_value"（既定）: attribute/new_value（old_value 任意）で属性値を置換。
      - "organism": new_value(学名)＋new_taxid で Description/Organism を補正。"""
    by_sample = {}
    for r in results:
        if not r.get("autofix"):
            continue
        kind = r.get("kind", "attribute_value")
        if kind == "attribute_value":
            if r.get("attribute") is None or r.get("new_value") is None:
                continue
        elif kind == "organism":
            if r.get("new_value") is None and r.get("new_taxid") is None:
                continue
        else:
            continue
        by_sample.setdefault(r.get("sample"), []).append(r)
    return by_sample


def clean_fixed_dir(out_dir):
    """fixed/ 内の既存出力を削除（取り違え防止。reports/ と同様の運用）。"""
    fixed = Path(out_dir) / "fixed"
    if fixed.is_dir():
        for pattern in ("*.xml", "*.json"):
            for f in fixed.glob(pattern):
                f.unlink()


def apply_autofix(xml_source, results, out_dir, out_name):
    """autofix 提案を XML に全自動適用し <out_dir>/fixed/<out_name> に出力。

    戻り値: 適用件数（0 なら何も書き出さない）。
    """
    proposals = collect_proposals(results)
    if not proposals:
        return 0

    try:
        tree = ET.parse(xml_source)
    except ET.ParseError:
        return 0
    root = tree.getroot()

    applied = 0
    for bs in root.findall(".//BioSample"):
        name, acc = _sample_identity(bs)
        # sample 識別子（name か accession）にマッチする提案を集める
        fixes = []
        for key in (name, acc):
            if key is not None and key in proposals:
                fixes.extend(proposals[key])
        if not fixes:
            continue
        for p in fixes:
            kind = p.get("kind", "attribute_value")
            if kind == "organism":
                applied += _apply_organism(bs, p)
            else:
                applied += _apply_attribute_value(bs, p)

    if applied == 0:
        return 0

    fixed = Path(out_dir) / "fixed"
    fixed.mkdir(parents=True, exist_ok=True)
    tree.write(str(fixed / out_name), encoding="UTF-8", xml_declaration=True)
    return applied


# Description 要素由来の属性 → 書き戻し先 XPath（Ruby xml_convertor.xpath_from_attrname 準拠）
_DESC_XPATH = {
    "sample_title": "./Description/Title",
    "description": "./Description/Comment/Paragraph",
}


def _apply_attribute_value(bs, p):
    """属性値置換（kind=attribute_value）。適用件数(0/1)を返す。"""
    attr_name = p.get("attribute")
    old_value = p.get("old_value")
    new_value = p.get("new_value")
    # sample_title/description は Attribute でなく Description 要素へ書き戻す
    if attr_name in _DESC_XPATH:
        el = bs.find(_DESC_XPATH[attr_name])
        if el is not None:
            cur = (el.text or "").strip()
            if old_value is None or cur == old_value:
                el.text = new_value
                return 1
        # 要素が無ければ属性側にフォールバック
    for a in bs.findall("./Attributes/Attribute"):
        if a.get("attribute_name") != attr_name:
            continue
        cur = (a.text or "").strip()
        # old_value 指定があれば一致する要素のみ、無ければ属性名一致で置換
        if old_value is not None and cur != old_value:
            continue
        a.text = new_value
        return 1
    return 0


def _apply_organism(bs, p):
    """Description/Organism の OrganismName（学名）と taxonomy_id を補正（kind=organism）。
    属性側にも organism/taxonomy_id があれば併せて更新する。適用件数を返す。"""
    applied = 0
    new_name = p.get("new_value")
    new_taxid = p.get("new_taxid")
    org = bs.find("./Description/Organism")
    if org is not None:
        if new_name:
            on = org.find("./OrganismName")
            if on is not None:
                on.text = new_name
            else:
                org.text = new_name
            applied += 1
        if new_taxid:
            org.set("taxonomy_id", str(new_taxid))
            applied += 1
    # 属性側 organism / taxonomy_id も存在すれば揃える
    for a in bs.findall("./Attributes/Attribute"):
        an = a.get("attribute_name")
        if an == "organism" and new_name:
            a.text = new_name
        elif an == "taxonomy_id" and new_taxid:
            a.text = str(new_taxid)
    return applied


# ---- DDBJ Record（v3 JSON）への適用 ----
# 提案は形式非依存（attribute / old_value / new_value / kind）なので、XML 版と違うのは
# 「どこに書き戻すか」だけ。識別子の取り方も record_reader の組み方と一致させてある。

# 属性バッグと typed slot の両方に載り得る値。片方だけ直すと record が自己矛盾するので両方直す。
_RECORD_TYPED_SLOTS = {
    "sample_title": "title",
    "description": "description",
}


def _record_sample_identity(sample):
    """v3 sample の識別子候補（sample_name, accession）。属性優先は record_reader と同じ順。"""
    name = None
    for attr in sample.get("attributes") or []:
        if attr.get("name") == "sample_name" and attr.get("value"):
            name = attr["value"].strip()
            break
    if not name:
        name = sample.get("alias")
    return name, sample.get("accession")


def _record_set_attribute(sample, name, old_value, new_value):
    """属性バッグの name を new_value へ。old_value 指定時は一致するものだけ。適用したら True。"""
    for attr in sample.get("attributes") or []:
        if attr.get("name") != name:
            continue
        if old_value is not None and (attr.get("value") or "").strip() != old_value:
            continue
        attr["value"] = new_value
        return True
    return False


def _apply_record_attribute_value(sample, p):
    """属性値置換（kind=attribute_value）。適用件数(0/1)を返す。"""
    attr_name = p.get("attribute")
    old_value = p.get("old_value")
    new_value = p.get("new_value")
    changed = _record_set_attribute(sample, attr_name, old_value, new_value)
    slot = _RECORD_TYPED_SLOTS.get(attr_name)
    if slot and sample.get(slot) is not None:
        if old_value is None or (sample.get(slot) or "").strip() == old_value:
            sample[slot] = new_value
            changed = True
    return 1 if changed else 0


def _apply_record_organism(sample, p):
    """organism（学名）と taxonomy_id を補正（kind=organism）。typed slot と属性の両方を揃える。"""
    new_name = p.get("new_value")
    new_taxid = p.get("new_taxid")
    organism = sample.get("organism")
    changed = False
    if new_name:
        if isinstance(organism, dict):
            organism["name"] = new_name
            changed = True
        changed = _record_set_attribute(sample, "organism", None, new_name) or changed
    if new_taxid:
        if isinstance(organism, dict):
            # v3 の taxonomy_id は int。数字でない提案（ありえないが）はそのまま載せて
            # スキーマ検証に落とさせる — 黙って捨てるより気付ける。
            organism["taxonomy_id"] = int(new_taxid) if str(new_taxid).isdigit() else new_taxid
            changed = True
        changed = _record_set_attribute(sample, "taxonomy_id", None, str(new_taxid)) or changed
    return 1 if changed else 0


def apply_autofix_record(record_source, results, out_dir, out_name):
    """autofix 提案を DDBJ Record に全自動適用し <out_dir>/fixed/<out_name> に出力。

    戻り値: 適用件数（0 なら何も書き出さない）。
    """
    proposals = collect_proposals(results)
    if not proposals:
        return 0

    try:
        record = json.loads(Path(record_source).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return 0

    applied = 0
    for sample in record.get("samples") or []:
        name, acc = _record_sample_identity(sample)
        fixes = []
        for key in (name, acc):
            if key is not None and key in proposals:
                fixes.extend(proposals[key])
        for p in fixes:
            if p.get("kind", "attribute_value") == "organism":
                applied += _apply_record_organism(sample, p)
            else:
                applied += _apply_record_attribute_value(sample, p)

    if applied == 0:
        return 0

    fixed = Path(out_dir) / "fixed"
    fixed.mkdir(parents=True, exist_ok=True)
    (fixed / out_name).write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n",
                                  encoding="utf-8")
    return applied
