#!/usr/bin/env python3
"""XML 入力と DDBJ Record 入力の同値性テスト（DRA）。

XML のシナリオ全件を、いったん内部モデルへ読んでから v3 record へ写し直し、
record_reader で読み直して**同じルールが同じ object に発火する**ことを確かめる。
「ルールは入力形式を意識しない」（model.py）が本当かどうかを fixture 全部で毎回問う。

写し方は ddbj-repository の DRA::Converter（spec の sra.yml の対応表どおり）に合わせてある。
参照は object の中でなくルートの relations に、source を accession（無ければ alias と、
同じ alias の中での index）で書く。中身の無いまとまりは converter と同じく落とす。

record 側にだけ出る DRA_R0002（#file_format。v3 スキーマ違反や解決できない relation）も
差として数える。写した record が v3 として正しくなければ、それはこの写し方か reader の誤り。

使い方: .venv/bin/python apps/dra/tests/run_record_parity_test.py
戻り値: 全一致で 0、ミスマッチで 1。
"""
import json
import re
import sys
import tempfile
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parents[2]))
sys.path.insert(0, str(_HERE))

from apps.dra import record_reader, xml_reader  # noqa: E402
from apps.dra.validator import Validator  # noqa: E402
import run_tests as H  # noqa: E402

GREEN = "\033[92m"; RED = "\033[91m"; END = "\033[0m"

# XML の形式そのものの指摘（整形・役割ごとの XSD）は record に対応物が無いので比較しない。
_XML_FORMAT_RULES = {"DRA_R0001", "DRA_R0044", "DRA_R0045", "DRA_R0046", "DRA_R0047"}

# record 経路だけの注記（「読まなかった」「担当外の違反」）。比較対象ではない。
_NOTICE_TARGETS = {"#not_validated", "#out_of_scope"}

# v3 が XML を表現しきれず、同値にならないと**分かっている**組み合わせ。どちら側にだけ出る差も
# ここで説明する。シナリオ名 -> {rule_id: 理由}。
#
# 素通りさせるのではなく列挙するのは、埋まったときに気付くため。ここに挙げた差が
# 出なくなったらテストは失敗し、この表から消せと言う。
_KNOWN_GAPS = {
    "DRA_R0050_2.pass": {
        "DRA_R0050": "XML の文字参照（&#x...;）は record では文字そのものになり、区別が残らない。"
                     "repository の正準形は非 ASCII を素で書くので、record では報告されるのが正しい。",
    },
}

# 指摘の sample が、それが見つかったファイルの名前であるルール。XML は 4 つの文書の
# どれか（sub.xml など）、record は 1 つのファイルなので、名前では比べない。
_FILE_SAMPLE_RULES = {"DRA_R0050"}


def _alias_key(alias):
    """alias の比べ方（ddbj/ddbj-record-specifications#18）。reader のものを使わずに書く。"""
    return re.sub(r"\s+", " ", alias).strip() if alias is not None else None


def _pruned(value):
    """None と、中身の無い dict / list を落とす（converter の prune と同じ）。"""
    if isinstance(value, dict):
        value = {k: _pruned(v) for k, v in value.items()}
        value = {k: v for k, v in value.items() if v is not None}
        return value or None
    if isinstance(value, list):
        value = [v for v in (_pruned(v) for v in value) if v is not None]
        return value or None
    return value


def _source(kind, obj, objects):
    if obj.accession:
        return {"type": kind, "accession": obj.accession}
    namesakes = [o for o in objects if _alias_key(o.alias) == _alias_key(obj.alias)]
    index = next(i for i, o in enumerate(namesakes) if o is obj) if len(namesakes) > 1 else None
    return {"type": kind, "alias": obj.alias, "index": index}


def _relation(kind, obj, objects, type_, db, accession=None, id_=None):
    return {"type": type_, "source": _source(kind, obj, objects),
            "target": {"db": db, "accession": accession, "id": id_}}


def _nominal_length(value):
    """v3 の nominal_length は int。converter は数として読めるものだけを数にする。"""
    text = (value or "").strip()
    return int(text) if re.fullmatch(r"[+-]?\d+", text) else value


def _files(obj):
    if not obj.data_block_present:
        return None
    return [{"files": [{"filename": f.filename, "filetype": f.filetype,
                        "checksum_method": f.checksum_method, "checksum": f.checksum}
                       for f in obj.files]}]


def _to_record(sub):
    """内部モデル → v3 record。ddbj-repository の DRA::Converter と同じ載せ方。"""
    relations = []
    record = {"schema_version": "v3"}

    if sub.submission:
        m = sub.submission
        record["submission"] = {
            "accession": m.accession, "alias": m.alias, "center_name": m.center_name,
            "hold_date": m.hold_date,
            "sra": {"lab_name": m.lab_name, "submission_date": m.submission_date,
                    "contacts": m.contacts},
        }

    record["experiments"] = []
    for e in sub.experiments:
        record["experiments"].append({
            "accession": e.accession, "alias": e.alias, "center_name": e.center_name,
            "title": e.title, "description": e.description,
            "library": {
                "name": e.library_name, "strategy": e.library_strategy,
                "source": e.library_source, "selection": e.library_selection,
                "layout": e.library_layout.lower() if e.library_layout else None,
                "nominal_length": _nominal_length(e.nominal_length),
            } if e.library_descriptor_present else None,
            "platform": {"type": e.platform, "instrument_model": e.instrument_model}
            if e.platform_present else None,
        })
        if e.study_ref:
            relations.append(_relation("experiment", e, sub.experiments, "part_of", "project", e.study_ref))
        if e.sample_ref:
            relations.append(_relation("experiment", e, sub.experiments, "part_of", "sample", e.sample_ref))

    record["runs"] = []
    for r in sub.runs:
        record["runs"].append({"accession": r.accession, "alias": r.alias, "center_name": r.center_name,
                               "title": r.title, "data_blocks": _files(r)})
        if r.experiment_ref or r.experiment_refname:
            relations.append(_relation("run", r, sub.runs, "part_of", "experiment",
                                       r.experiment_ref, r.experiment_refname))

    record["analyses"] = []
    for a in sub.analyses:
        record["analyses"].append({"accession": a.accession, "alias": a.alias, "center_name": a.center_name,
                                   "title": a.title, "description": a.description,
                                   "data_blocks": _files(a)})
        if a.study_ref:
            relations.append(_relation("analysis", a, sub.analyses, "part_of", "project", a.study_ref))
        relations += [_relation("analysis", a, sub.analyses, "derived_from", "sample", acc)
                      for acc in a.sample_refs]
        relations += [_relation("analysis", a, sub.analyses, "derived_from", "run", acc)
                      for acc in a.run_refs]

    record["relations"] = relations

    # 中身の無い object 自体は落とさない（converter は落とさず断る。落とすと件数が変わる）。
    out = {}
    for key, value in record.items():
        if key in ("experiments", "runs", "analyses"):
            value = [_pruned(obj) or {} for obj in value] or None
        else:
            value = _pruned(value)
        if value is not None:
            out[key] = value
    return out


def _shown(entries, limit=5):
    """差の一覧は大きなシナリオ（数百 object）で数百行になるので、先頭だけ出して件数を添える。"""
    more = f" (+{len(entries) - limit} more)" if len(entries) > limit else ""
    return f"{entries[:limit]}{more}"


def _fired(submission, pre_errors):
    """発火した (rule_id, sample, level) の組。rule_id の集合だけで比べると、同じルールが
    別の object に出たことを「一致」と言ってしまう。"""
    results = list(pre_errors)
    if submission is not None:
        results += Validator(H._context()).run(submission)

    return {(r["rule_id"], "(file)" if r["rule_id"] in _FILE_SAMPLE_RULES else r.get("sample"), r.get("level"))
            for r in results
            if r["rule_id"] not in _XML_FORMAT_RULES and r.get("target") not in _NOTICE_TARGETS}


def main():
    scenarios = sorted(d for d in _HERE.iterdir()
                       if d.is_dir() and d.name.startswith("DRA_R") and any(d.glob("*.xml")))
    matched = mismatched = 0
    diffs, gaps = [], []

    for scenario in scenarios:
        name = scenario.name
        submission, pre_errors = xml_reader.parse_files(sorted(str(p) for p in scenario.glob("*.xml")))
        want = _fired(submission, pre_errors)

        record_path = None
        try:
            with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
                json.dump(_to_record(submission), f, ensure_ascii=False)
                record_path = f.name
            got_submission, got_pre = record_reader.parse_record(record_path)
        finally:
            if record_path:
                Path(record_path).unlink(missing_ok=True)

        got   = _fired(got_submission, got_pre)
        known = _KNOWN_GAPS.get(name, {})

        only_xml    = sorted(want - got)
        only_record = sorted(got - want, key=str)
        unexplained = [r for r in only_xml + only_record if r[0] not in known]
        stale       = [r for r in known if r not in {entry[0] for entry in only_xml + only_record}]

        if not unexplained and not stale:
            matched += 1
            for rule_id, *_ in only_xml + only_record:
                gaps.append((name, rule_id, known[rule_id]))
        else:
            mismatched += 1
            diffs.append((name, only_xml, only_record, unexplained, stale))

    # 表に挙げたまま fixture が消えると、永久に反証されない言い訳が残る。
    missing = sorted(set(_KNOWN_GAPS) - {d.name for d in scenarios})

    print(f"\n[record parity] Matched: {matched}   "
          f"Mismatched: {RED if mismatched else GREEN}{mismatched}{END}")

    if gaps:
        print(f"  既知の差 {len(gaps)} 件（v3 が XML を表現しきれない箇所）:")
        for name, rule_id, why in gaps:
            print(f"    {rule_id} @ {name}\n      {why}")

    for name, only_xml, only_record, unexplained, stale in diffs:
        print(f"  [{RED}MISMATCH{END}] {name}")
        if unexplained:
            print(f"      説明の無い差: XML だけ {_shown([r for r in only_xml if r in unexplained])} / "
                  f"record だけ {_shown([r for r in only_record if r in unexplained])}")
        if stale:
            print(f"      _KNOWN_GAPS に挙がっているのに差が出ない（埋まった？表から消す）: {stale}")

    if missing:
        print(f"  [{RED}STALE{END}] 存在しないシナリオが表に残っている（消すか直す）: {missing}")

    # 1 件も比較していないのに緑を返さない。fixture が読めなくなった / glob が
    # 壊れたときに「全部一致」と言うのが、このテストが防ぐはずの失敗そのもの。
    if not matched:
        print(f"  [{RED}FAIL{END}] 比較できたシナリオが 1 件もありません")
        return 1

    return 1 if (mismatched or missing) else 0


if __name__ == "__main__":
    sys.exit(main())
