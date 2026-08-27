#!/usr/bin/env python3
"""XML 入力と DDBJ Record 入力の同値性テスト（BioProject）。

XML fixture 全件を、いったん内部モデルへ読んでから v3 record へ写し直し、
record_reader で読み直して**同じルールが発火する**ことを確かめる。
「ルールは入力形式を意識しない」（model.py）が本当かどうかを fixture 全部で毎回問う。

写し方は ddbj-repository の BioProject::Converter に合わせてある。

使い方: .venv/bin/python apps/bioproject/tests/run_record_parity_test.py
戻り値: 全一致で 0、ミスマッチで 1。
"""
import json
import sys
import tempfile
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parents[2]))
sys.path.insert(0, str(_HERE))

from apps.bioproject import record_reader, xml_reader  # noqa: E402
from apps.bioproject.validator import Validator  # noqa: E402
import run_tests as H  # noqa: E402

GREEN = "\033[92m"; RED = "\033[91m"; END = "\033[0m"

# 形式そのものの指摘は XML と Record で別物（XSD vs v3 スキーマ）なので比較しない。
# BP_R0037（1 XML に複数 project）は v3 では起こり得ない（project は 1 つ）。
_FORMAT_RULES = {"BP_R0001", "BP_R0002", "BP_R0037"}

# v3 が XML を表現しきれず、同値にならないと**分かっている**組み合わせ。
# fixture 名 -> {rule_id: 理由}。
#
# 素通りさせるのではなく列挙するのは、埋まったときに気付くため。ここに挙げた差が
# 出なくなったらテストは失敗し、この表から消せと言う。
_KNOWN_GAPS = {
    "BP_R0015/BP_R0015_1.fail.xml": {
        "BP_R0015": "v3 の Publication は構造化引用で、XML の <Reference>（自由記述）に "
                    "あたる slot が無い。id も reference も無い publication を表現できない。",
    },
    "BP_R0016/BP_R0016_1.fail.xml": {
        "BP_R0016": "umbrella の member（XML の ProjectLinks/.../MemberID）を v3 の relations で "
                    "どう書くかが未確定。reader は umbrella のとき警告を出す。",
    },
    "BP_R0040/BP_R0040_1.fail.xml": {
        "BP_R0040": "v3 の project_type は primary / umbrella だけで、"
                    "ProjectTypeTopSingleOrganism を表現できない。",
    },
}

_PROJECT_TYPE = {"submission": "primary", "umbrella": "umbrella"}
_DB_TYPE_KEY  = {"ePubmed": "pubmed_id", "eDOI": "doi"}


def _to_record(submission):
    """内部モデル → v3 record。ddbj-repository の BioProject::Converter と同じ載せ方。"""
    rec = submission.records[0]

    project = {
        "accession":                    rec.accession,
        "title":                        rec.title,
        "description":                  rec.description,
        "project_type":                 _PROJECT_TYPE.get(rec.project_kind),
        "umbrella_subtype":             rec.top_admin_subtype,
        "umbrella_subtype_description": rec.subtype_other_descr,
        "organism": {k: v for k, v in (
            ("name", rec.organism_name),
            ("taxonomy_id", int(rec.tax_id) if (rec.tax_id or "").isdigit() else None),
        ) if v is not None} or None,
        "locus_tag_prefix": [
            {k: v for k, v in lt.items() if v} for lt in rec.locus_tags
        ] or None,
        "publications": [
            {_DB_TYPE_KEY.get(p.db_type, "pubmed_id"): p.id} for p in rec.publications if p.id
        ] or None,
        "relevance": _relevance(rec),
        "target":    _target(rec),
    }

    return {"schema_version": "v3.0",
            "project": {k: v for k, v in project.items() if v is not None}}


def _relevance(rec):
    """モデルは「Relevance 要素があるか」と「Other の text」しか持たない。どのカテゴリが
    選ばれていたかは残っていないので、その 2 つが round-trip する最小の dict を作る。
    ここだけは実データの写しではなく、同値性を問うための合成。"""
    if not rec.relevance_present:
        return None
    if rec.relevance_other_selected:
        return {"other": rec.relevance_other or ""}
    return {"unspecified": ""}


def _target(rec):
    descriptions = {d["type"]: d["text"] for d in rec.data_entries if d.get("type") and d.get("text")}
    target = {
        "sample_scope":           rec.sample_scope,
        "material":               rec.material,
        "capture":                rec.capture,
        "method":                 rec.method_type,
        "method_description":     rec.method_text,
        "description":            rec.target_description,
        "data_types":             [d["type"] for d in rec.data_entries if d.get("type")] or None,
        "data_type_descriptions": descriptions or None,
    }
    target = {k: v for k, v in target.items() if v is not None}

    return target or None


def _context():
    return H.ValidationContext(
        skip_db=False, skip_ncbi=False, skip_auth=False,
        tax_data=dict(H.MOCK_TAX), taxid_info=dict(H.MOCK_TAXID),
        umbrella_ok=set(H.MOCK_UMBRELLA_OK),
        bs_locus_prefix={k: set(v) for k, v in H.MOCK_BS_LOCUS.items()},
        project_names=list(H.MOCK_PROJECT_NAMES),
    )


def _fired(submission, pre_errors):
    fired = {r["rule_id"] for r in pre_errors}
    if submission is not None:
        fired |= {r["rule_id"] for r in Validator(_context()).run(submission)}
    return fired - _FORMAT_RULES


def main():
    matched = mismatched = 0
    diffs = []
    gaps  = []
    for xml_path in sorted(p for d in _HERE.iterdir() if d.is_dir() and d.name.startswith("BP_R")
                           for p in d.glob("*.xml")):
        submission, pre_errors = xml_reader.parse_xml(str(xml_path))
        if submission is None or not submission.records:
            continue      # 整形不正 fixture。写す先が無い

        want = _fired(submission, pre_errors)
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
            json.dump(_to_record(submission), f, ensure_ascii=False)
            record_path = f.name
        got_submission, got_pre = record_reader.parse_record(record_path)
        Path(record_path).unlink()
        got = _fired(got_submission, got_pre)

        name  = str(xml_path.relative_to(_HERE))
        known = _KNOWN_GAPS.get(name, {})

        only_xml    = sorted(want - got)
        only_record = sorted(got - want)
        unexplained = [r for r in only_xml if r not in known] + only_record
        stale       = [r for r in known if r not in only_xml]

        if not unexplained and not stale:
            matched += 1
            for rule_id in only_xml:
                gaps.append((name, rule_id, known[rule_id]))
        else:
            mismatched += 1
            diffs.append((name, unexplained, stale))

    print(f"\n[record parity] Matched: {matched}   "
          f"Mismatched: {RED if mismatched else GREEN}{mismatched}{END}")

    if gaps:
        print(f"  既知の差 {len(gaps)} 件（v3 が XML を表現しきれない箇所）:")
        for name, rule_id, why in gaps:
            print(f"    {rule_id} @ {name}\n      {why}")

    for name, unexplained, stale in diffs:
        print(f"  [{RED}MISMATCH{END}] {name}")
        if unexplained:
            print(f"      説明の無い差: {unexplained}")
        if stale:
            print(f"      _KNOWN_GAPS に挙がっているのに差が出ない（埋まった？表から消す）: {stale}")

    return 1 if mismatched else 0


if __name__ == "__main__":
    sys.exit(main())
