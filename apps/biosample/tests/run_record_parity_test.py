#!/usr/bin/env python3
"""XML 入力と DDBJ Record 入力の同値性テスト。

XML fixture 全件を、いったん内部モデルへ読んでから v3 record へ写し直し、
record_reader で読み直して**同じルールが発火する**ことを確かめる。
「ルールは入力形式を意識しない」（model.py）が本当かどうかを、fixture 全部で毎回問う。

写し方は BioSample::Converter（ddbj-repository、D-way から v3 を作っている実装）に
合わせてある: sample_name は alias、sample_title/description/organism/taxonomy_id は
typed slot に上げつつ属性バッグにも残す。

使い方: .venv/bin/python apps/biosample/tests/run_record_parity_test.py
戻り値: 全一致で 0、ミスマッチで 1。
"""
import json
import sys
import tempfile
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parents[2]))
sys.path.insert(0, str(_HERE))

from apps.biosample import record_reader, xml_reader  # noqa: E402
from apps.biosample.validator import Validator  # noqa: E402
import run_tests as H  # noqa: E402

GREEN = "\033[92m"; RED = "\033[91m"; END = "\033[0m"

# 形式そのものの指摘は XML と Record で別物（XSD vs v3 スキーマ）なので比較しない。
_FORMAT_RULES = {"BS_R0097", "BS_R0098"}


def _to_record(submission):
    """内部モデル → v3 record。ddbj-repository の BioSample::Converter と同じ載せ方。"""
    samples = []
    for rec in submission.records:
        organism = {}
        if rec.organism:
            organism["name"] = rec.organism
        if rec.taxonomy_id:
            tax_id = str(rec.taxonomy_id)
            organism["taxonomy_id"] = int(tax_id) if tax_id.isdigit() else tax_id
        sample = {
            "alias": rec.sample_name,
            "accession": rec.accession,
            "title": rec.title,
            "description": rec.attr("description") or None,
            "package": rec.package,
            "organism": organism or None,
            "attributes": [{"name": name, "value": value}
                           for name, values in rec.attributes.items()
                           for value in values] or None,
        }
        samples.append({k: v for k, v in sample.items() if v is not None})
    return {"schema_version": "v3.0", "samples": samples}


def _context():
    return H.ValidationContext(
        skip_db=False, skip_ncbi=False, skip_auth=False,
        account=H.MOCK_ACCOUNT, tax_data=dict(H.MOCK_TAX),
        authorized_projects=set(H.MOCK_AUTH_PROJECTS), authorized_samds=set(H.MOCK_AUTH_SAMDS),
        bp_meta=dict(H.MOCK_BP_META), psub_to_prjd=dict(H.MOCK_PSUB_TO_PRJD),
        registered_locus_tag_prefixes=dict(H.MOCK_REGISTERED_PREFIXES),
    )


def _fired(submission, pre_errors):
    fired = {r["rule_id"] for r in pre_errors}
    if submission is not None:
        fired |= {r["rule_id"] for r in Validator(_context()).run(submission)}
    return fired - _FORMAT_RULES


def main():
    matched = mismatched = 0
    diffs, skipped = [], []
    for xml_path in sorted(p for d in _HERE.iterdir() if d.is_dir() and d.name.startswith("BS_R")
                           for p in d.glob("*.xml")):
        submission, pre_errors = xml_reader.parse_xml(str(xml_path))
        if submission is None:      # 整形不正 fixture。写す先が無い
            skipped.append(str(xml_path.relative_to(_HERE)))
            continue
        # BS_R0012/R0013 は rec.attributes を in-place で書き換えるので、
        # record への写しは検証を走らせる前に取る。
        record = _to_record(submission)
        want = _fired(submission, pre_errors)

        record_path = None
        try:
            with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                             encoding="utf-8") as f:
                json.dump(record, f, ensure_ascii=False)
                record_path = f.name
            got_submission, got_pre = record_reader.parse_record(
                record_path, submission_id=submission.submission_id)
        finally:
            if record_path:
                Path(record_path).unlink(missing_ok=True)
        got = _fired(got_submission, got_pre)

        if want == got:
            matched += 1
        else:
            mismatched += 1
            diffs.append((xml_path.relative_to(_HERE), sorted(want - got), sorted(got - want)))

    print(f"\n[record parity] Matched: {matched}   "
          f"Mismatched: {RED if mismatched else GREEN}{mismatched}{END}")
    if skipped:
        print(f"  比較できなかった fixture {len(skipped)} 件（XML から model を組めない）: {skipped}")
    for name, only_xml, only_record in diffs:
        print(f"  [{RED}MISMATCH{END}] {name}")
        print(f"      XML のみ:    {only_xml}")
        print(f"      Record のみ: {only_record}")

    # 1 件も比較していないのに緑を返さない。fixture が読めなくなったときに
    # 「全部一致」と言うのが、このテストが防ぐはずの失敗そのもの。
    if not matched:
        print(f"  [{RED}FAIL{END}] 比較できた fixture が 1 件もありません")
        return 1

    return 1 if mismatched else 0


if __name__ == "__main__":
    sys.exit(main())
