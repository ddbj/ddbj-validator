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
                    "どう書くかが未確定。reader は umbrella のとき level=info で "
                    "「評価できなかった」をレポートに出す（validity には影響しない）。",
    },
    "BP_R0040/BP_R0040_1.fail.xml": {
        "BP_R0040": "v3 の project_type は primary / umbrella だけで、"
                    "ProjectTypeTopSingleOrganism を表現できない。",
    },
}

# record_reader が断る fixture（project と samples の同居など）。素通りさせず理由付きで列挙する。
_REFUSED = {}

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
        # converter と同じ落とし方をする。既定で pubmed_id に寄せると、DbType が
        # 未知/不在の publication が record 側だけ「ePubmed の id」に化けて、
        # 写像のずれをこのテストが見つけられなくなる。
        "publications": [pub for pub in (_publication(p) for p in rec.publications) if pub] or None,
        "relevance": _relevance(rec),
        "target":    _target(rec),
    }

    return {"schema_version": "v3.0",
            "project": {k: v for k, v in project.items() if v is not None}}


def _publication(pub):
    """Publication -> v3 の 1 件。converter に合わせて、既知の DbType 以外は id を落とす。"""
    out = {}
    key = _DB_TYPE_KEY.get(pub.db_type)
    if key and pub.id:
        out[key] = pub.id
    if pub.reference:
        out["title"] = pub.reference

    return out or None


def _relevance(rec):
    """モデルは「Relevance 要素があるか」と「Other の text」しか持たない。どのカテゴリが
    選ばれていたかは残らないので、その 2 つが round-trip する最小の dict を作る。
    Other が選ばれていなければ空 dict — reader は「キーがある＝要素がある」で present と
    見るので、存在しないキーをでっち上げずに済む。"""
    if not rec.relevance_present:
        return None
    if rec.relevance_other_selected:
        return {"other": rec.relevance_other or ""}
    return {}


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
    """発火した (rule_id, sample) の組。rule_id の集合だけで比べると、同じルールが
    2 件出るか 1 件出るかの違いを「一致」と言ってしまう。"""
    results = list(pre_errors)
    if submission is not None:
        results += Validator(_context()).run(submission)

    return {(r["rule_id"], r.get("sample"), r.get("level"))
            for r in results
            if r["rule_id"] not in _FORMAT_RULES
            # 「このルールは評価できなかった」という record 経路だけの注記。
            # 比較対象ではない（出ること自体は info として報告される）。
            and r.get("target") != "#not_evaluated"}


def main():
    fixtures = sorted(p for d in _HERE.iterdir() if d.is_dir() and d.name.startswith("BP_R")
                      for p in d.glob("*.xml"))
    matched = mismatched = 0
    diffs, gaps, refused, skipped = [], [], [], []

    for xml_path in fixtures:
        name = str(xml_path.relative_to(_HERE))
        submission, pre_errors = xml_reader.parse_xml(str(xml_path))
        if submission is None or not submission.records:
            # 整形不正 fixture。写す先が無い。数えて表に出す（黙って飛ばさない）。
            skipped.append(name)
            continue

        want = _fired(submission, pre_errors)
        record_path = None
        try:
            with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                             encoding="utf-8") as f:
                json.dump(_to_record(submission), f, ensure_ascii=False)
                record_path = f.name
            got_submission, got_pre = record_reader.parse_record(record_path)
        except record_reader.Unsupported as e:
            why = _REFUSED.get(name)
            if why:
                refused.append((name, why))
                matched += 1
            else:
                mismatched += 1
                diffs.append((name, [f"reader が断った: {e}"], []))
            continue
        finally:
            if record_path:
                Path(record_path).unlink(missing_ok=True)

        got   = _fired(got_submission, got_pre)
        known = _KNOWN_GAPS.get(name, {})

        only_xml    = sorted(want - got)
        only_record = sorted(got - want)
        unexplained = [r for r in only_xml if r[0] not in known] + only_record
        stale       = [r for r in known if r not in {entry[0] for entry in only_xml}]

        if not unexplained and not stale:
            matched += 1
            for rule_id, *_ in only_xml:
                gaps.append((name, rule_id, known[rule_id]))
        else:
            mismatched += 1
            diffs.append((name, unexplained, stale))

    # 表に挙げたまま fixture が消えると、永久に反証されない言い訳が残る。
    missing = sorted({*_KNOWN_GAPS, *_REFUSED} - {str(p.relative_to(_HERE)) for p in fixtures})

    print(f"\n[record parity] Matched: {matched}   "
          f"Mismatched: {RED if mismatched else GREEN}{mismatched}{END}")

    if gaps:
        print(f"  既知の差 {len(gaps)} 件（v3 が XML を表現しきれない箇所）:")
        for name, rule_id, why in gaps:
            print(f"    {rule_id} @ {name}\n      {why}")
    if refused:
        print(f"  reader が断った {len(refused)} 件:")
        for name, why in refused:
            print(f"    {name} — {why}")
    if skipped:
        print(f"  比較できなかった fixture {len(skipped)} 件（XML から model を組めない）: {skipped}")

    for name, unexplained, stale in diffs:
        print(f"  [{RED}MISMATCH{END}] {name}")
        if unexplained:
            print(f"      説明の無い差: {unexplained}")
        if stale:
            print(f"      _KNOWN_GAPS に挙がっているのに差が出ない（埋まった？表から消す）: {stale}")

    if missing:
        print(f"  [{RED}STALE{END}] 存在しない fixture が表に残っている（消すか直す）: {missing}")

    # 1 件も比較していないのに緑を返さない。fixture が読めなくなった / glob が
    # 壊れたときに「全部一致」と言うのが、このテストが防ぐはずの失敗そのもの。
    if not matched:
        print(f"  [{RED}FAIL{END}] 比較できた fixture が 1 件もありません")
        return 1

    return 1 if (mismatched or missing) else 0


if __name__ == "__main__":
    sys.exit(main())
