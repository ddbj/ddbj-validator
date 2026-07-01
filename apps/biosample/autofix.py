"""BioSample autofix 適用層。

方針（ddbj の対話式とは異なる）:
- **全自動適用**（対話なし）。検証結果のうち autofix 提案を持つものを全て適用する。
- 修正済み XML を `<out_dir>/fixed/` に出力する（入力が TSV の場合も XML として出力）。

autofix 提案は結果 dict に次を持つ（BsRule.result の extra 経由）:
    autofix=True, attribute=<attr_name>, old_value=<現値>, new_value=<修正値>
    （kind 省略時は "attribute_value" として属性値を置換）

サンプル対応付けは result["sample"]（sample_name か accession）と
XML の SampleName / Ids/Id を突き合わせる。
"""
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
    """検証結果から autofix 提案（属性値置換）を抽出。
    戻り値: {sample_id: [(attribute, old_value, new_value), ...]}。sample_id は name/accession いずれか。"""
    by_sample = {}
    for r in results:
        if not r.get("autofix"):
            continue
        if r.get("kind", "attribute_value") != "attribute_value":
            continue
        attr = r.get("attribute")
        new = r.get("new_value")
        if attr is None or new is None:
            continue
        old = r.get("old_value")
        by_sample.setdefault(r.get("sample"), []).append((attr, old, new))
    return by_sample


def clean_fixed_dir(out_dir):
    """fixed/ 内の既存 .xml を削除（取り違え防止。reports/ と同様の運用）。"""
    fixed = Path(out_dir) / "fixed"
    if fixed.is_dir():
        for f in fixed.glob("*.xml"):
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
        for attr_name, old_value, new_value in fixes:
            for a in bs.findall("./Attributes/Attribute"):
                if a.get("attribute_name") != attr_name:
                    continue
                cur = (a.text or "").strip()
                # old_value 指定があれば一致する要素のみ、無ければ属性名一致で置換
                if old_value is not None and cur != old_value:
                    continue
                a.text = new_value
                applied += 1
                break

    if applied == 0:
        return 0

    fixed = Path(out_dir) / "fixed"
    fixed.mkdir(parents=True, exist_ok=True)
    tree.write(str(fixed / out_name), encoding="UTF-8", xml_declaration=True)
    return applied
