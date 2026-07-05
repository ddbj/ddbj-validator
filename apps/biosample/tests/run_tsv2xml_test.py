#!/usr/bin/env python3
"""TSV → XML 変換（tsv_to_xml）の E2E テスト。

apps/biosample/tests/tsv_to_xml/ に `<SSUBid>.<Package>.txt`（入力 TSV）と
expected/<SSUBid>.xml（登録システムが出力した参照 XML）を置く。
tsv_to_xml() の出力を参照 XML と **意味内容**（サンプル別の accession / sample_name / title /
organism / taxonomy_id / description / package(Model) / attributes）で比較する。
last_update / publication_date / Owner 等、TSV に無く登録システムが埋める揮発フィールドは比較対象外。

使い方: .venv/bin/python apps/biosample/tests/run_tsv2xml_test.py
戻り値: 全一致で 0、ミスマッチで 1。
"""
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from apps.biosample import tsv_to_xml  # noqa: E402

_DIR = Path(__file__).resolve().parent / "tsv_to_xml"


def _canon(root):
    """XML root → サンプル別の意味内容 dict リスト（揮発フィールドは含めない）。"""
    out = []
    for bs in root.findall(".//BioSample"):
        i = bs.find("./Ids/Id")
        org = bs.find("./Description/Organism")
        attrs = {a.get("attribute_name"): (a.text or "").strip()
                 for a in bs.findall("./Attributes/Attribute")}
        out.append({
            "accession": (i.text.strip() if i is not None and i.text else ""),
            "sample_name": (bs.findtext("./Description/SampleName") or "").strip(),
            "title": (bs.findtext("./Description/Title") or "").strip(),
            "organism": (bs.findtext("./Description/Organism/OrganismName") or "").strip(),
            "taxonomy_id": (org.get("taxonomy_id") if org is not None else "") or "",
            "description": (bs.findtext("./Description/Comment/Paragraph") or "").strip(),
            "package": (bs.findtext("./Models/Model") or "").strip(),
            "attributes": attrs,
        })
    return out


def _diff(ours, exp):
    """2 つの canonical リストの差分（文字列リスト）を返す。空なら一致。"""
    msgs = []
    if len(ours) != len(exp):
        return [f"sample count differs: ours={len(ours)} expected={len(exp)}"]
    for idx, (a, b) in enumerate(zip(ours, exp)):
        for k in ("accession", "sample_name", "title", "organism", "taxonomy_id", "description", "package"):
            if a[k] != b[k]:
                msgs.append(f"sample[{idx}] {k}: ours={a[k]!r} expected={b[k]!r}")
        ak, bk = set(a["attributes"]), set(b["attributes"])
        if ak - bk:
            msgs.append(f"sample[{idx}] attribute(s) only in ours: {sorted(ak - bk)}")
        if bk - ak:
            msgs.append(f"sample[{idx}] attribute(s) only in expected: {sorted(bk - ak)}")
        for k in ak & bk:
            if a["attributes"][k] != b["attributes"][k]:
                msgs.append(f"sample[{idx}] attribute[{k}]: ours={a['attributes'][k]!r} expected={b['attributes'][k]!r}")
    return msgs


def main():
    tsvs = sorted(_DIR.glob("*.txt")) + sorted(_DIR.glob("*.tsv"))
    if not tsvs:
        print("[tsv2xml] No fixtures found.")
        return 0
    matched = mismatched = 0
    for tsv in tsvs:
        sub_id, package = tsv_to_xml.parse_filename(str(tsv))
        exp_path = _DIR / "expected" / f"{sub_id}.xml"
        if not exp_path.exists():
            print(f"  [MISMATCH] {tsv.name}: expected XML not found ({exp_path.name})")
            mismatched += 1
            continue
        try:
            ours_xml = tsv_to_xml.tsv_to_xml(str(tsv), package=package, submission_id=sub_id)
            ours = _canon(ET.fromstring(ours_xml))
            exp = _canon(ET.parse(str(exp_path)).getroot())
        except Exception as e:
            print(f"  [MISMATCH] {tsv.name}: error -> {e}")
            mismatched += 1
            continue
        d = _diff(ours, exp)
        if d:
            print(f"  [MISMATCH] {tsv.name} (vs {exp_path.name}):")
            for m in d[:10]:
                print(f"      {m}")
            mismatched += 1
        else:
            print(f"  [Matched]  {tsv.name} (vs {exp_path.name}) — {len(ours)} sample(s)")
            matched += 1
    print(f"\n[tsv2xml] Matched: {matched}   Mismatched: {mismatched}")
    return 1 if mismatched else 0


if __name__ == "__main__":
    sys.exit(main())
