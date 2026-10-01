"""COMMON テンプレート（source 1..E）の qualifier を entry 数ぶん重複して autofix しないこと。

COMMON の source に `1..E` を書くと、パーサはその生物学的フィーチャーを全 entry へ複製する。
ファイル上の実体は COMMON ブロックの 1 箇所だけなのに、BioSample 同期（ANN1130）が entry ごとに
突合すると同じ行に対する提案が entry 数ぶん作られ、autofix が COMMON へ同じ qualifier を
entry 数ぶん書き込んでいた（2026-10-01 の報告 NSUB003618。55,076 entry ぶん挿入された）。

ここでは (1) 複製された feature に印が付くこと (2) 突合対象の絞り込み (3) writer 側の重複ガード、
の 3 つを固定する。
"""
from types import SimpleNamespace

from apps.ddbj.autofix.writer import write_autofix_to_file
from apps.ddbj.biosample.sync import _source_features
from common.features import is_common_template_feature
from apps.ddbj.parser import parse_ddbj_submission


# COMMON の source が 1..E。entry 側には source を書かない（登録ファイルでよくある書き方）
_COMMON_ANN = [
    "COMMON\tDBLINK\t\tbiosample\tSAMD00000001",
    "\tsource\t1..E\torganism\tEscherichia coli",
    "\t\t\tmol_type\tgenomic DNA",
    "seq1\trRNA\t1..20\tproduct\t16S ribosomal RNA",
    "seq2\trRNA\t1..20\tproduct\t16S ribosomal RNA",
]
_FASTA = ">seq1\n" + "ATGC" * 10 + "\n//\n>seq2\n" + "ATGC" * 10 + "\n//\n"


def _parse(ann_lines, fasta=_FASTA):
    records, _errors, _fasta_only = parse_ddbj_submission(fasta, "t.ann", ann_lines)
    return records


# ---------------- パーサが付ける印 ----------------
def test_common_template_source_is_marked_in_every_entry():
    records = _parse(_COMMON_ANN)
    for entry in ("seq1", "seq2"):
        sources = [f for f in records[entry].features if f.type == "source"]
        assert len(sources) == 1
        # 複製元は COMMON の 2 行目。どの entry でも同じ行を指す
        assert sources[0].line_number == 2
        assert is_common_template_feature(sources[0]) is True


def test_entry_own_features_are_not_marked():
    records = _parse(_COMMON_ANN)
    rrna = [f for f in records["seq1"].features if f.type == "rRNA"]
    assert len(rrna) == 1
    assert is_common_template_feature(rrna[0]) is False


def test_entry_level_source_is_not_marked():
    """COMMON テンプレートを使わない（entry ごとに source を書く）ファイルは従来どおり。"""
    ann = [
        "seq1\tsource\t1..40\torganism\tEscherichia coli",
        "\t\t\tmol_type\tgenomic DNA",
    ]
    records = _parse(ann, ">seq1\n" + "ATGC" * 10 + "\n//\n")
    source = [f for f in records["seq1"].features if f.type == "source"][0]
    assert is_common_template_feature(source) is False


# ---------------- 突合対象の絞り込み ----------------
def _record(*features):
    return SimpleNamespace(features=list(features),
                           features_by_type={"source": [f for f in features if f.type == "source"]})


def test_source_features_split_common_and_entry_own():
    common = SimpleNamespace(type="source", from_common=True)
    own = SimpleNamespace(type="source", from_common=False)
    rec = _record(common, own)
    assert _source_features(rec, common_only=False) == [own]
    assert _source_features(rec, common_only=True) == [common]


def test_source_features_treat_a_missing_flag_as_entry_own():
    """from_common を持たない feature（テスト用のダミー等）は entry 固有として扱う。"""
    plain = SimpleNamespace(type="source")
    rec = _record(plain)
    assert _source_features(rec, common_only=False) == [plain]
    assert _source_features(rec, common_only=True) == []


def test_source_features_ignore_non_source_features():
    """突合属性はすべて source 専用なので CDS 等は見ない。"""
    cds = SimpleNamespace(type="CDS", from_common=False, qualifiers={"strain": ["x"]})
    rec = SimpleNamespace(features=[cds], features_by_type={"CDS": [cds]})
    assert _source_features(rec, common_only=False) == []


# ---------------- writer の重複ガード ----------------
def test_add_qualifier_is_written_once_per_line_even_if_proposed_twice(tmp_path):
    """同じ行へ同じ qualifier/値を足す提案が重複して届いても 1 行しか書かない。"""
    out = tmp_path / "out.ann"
    add = {"action": "add_qualifier", "entry": "COMMON", "feature_type": "source",
           "feature_line": 2, "qualifier": "isolate", "new_value": "2020-Tateyama"}
    assert write_autofix_to_file(_COMMON_ANN, [dict(add), dict(add), dict(add)], out)
    lines = out.read_text().splitlines()
    assert lines.count("\t\t\tisolate\t2020-Tateyama") == 1


def test_add_qualifier_still_writes_different_values_on_the_same_line(tmp_path):
    """値が違えば別の追加なので両方書く（重複ガードが効きすぎないこと）。"""
    out = tmp_path / "out.ann"
    updates = [
        {"action": "add_qualifier", "entry": "COMMON", "feature_type": "source",
         "feature_line": 2, "qualifier": "isolate", "new_value": "A"},
        {"action": "add_qualifier", "entry": "COMMON", "feature_type": "source",
         "feature_line": 2, "qualifier": "isolation_source", "new_value": "marine"},
    ]
    write_autofix_to_file(_COMMON_ANN, updates, out)
    body = out.read_text()
    assert "\t\t\tisolate\tA\n" in body
    assert "\t\t\tisolation_source\tmarine\n" in body


# ---------------- COMMON 由来 source と entry ごとの BioSample ----------------
from apps.ddbj.autofix.external_db import propose_qualifiers_updates


def _entry(entry_id, samd, line_dblink):
    """entry 固有の DBLINK を持ち、COMMON テンプレート由来の source を共有する record。"""
    dblink = SimpleNamespace(type="DBLINK", qualifiers={"biosample": [samd]}, line_number=line_dblink)
    source = SimpleNamespace(type="source", qualifiers={"organism": ["Escherichia coli"]},
                             line_number=2, from_common=True)
    return SimpleNamespace(id=entry_id, features=[dblink, source],
                           features_by_type={"DBLINK": [dblink], "source": [source]})


def _records_with_two_biosamples():
    return {"seq1": _entry("seq1", "SAMD00000001", 10),
            "seq2": _entry("seq2", "SAMD00000002", 20)}


def test_common_source_is_matched_once_against_all_covered_biosamples_when_they_agree():
    """COMMON の値は複製先の全 entry に効くので、突合相手はそれらの BioSample 全部。値が揃っていれば 1 件。"""
    bs = {"SAMD00000001": {"isolate": "X1"}, "SAMD00000002": {"isolate": "X1"}}
    props, warns, skips = propose_qualifiers_updates(_records_with_two_biosamples(), bs, "t.ann")
    adds = [p for p in props if p["qualifier"] == "isolate"]
    assert len(adds) == 1
    assert adds[0]["entry"] == "COMMON"
    assert adds[0]["new_value"] == "X1"
    assert [w["entry"] for w in warns if w["qualifier"] == "isolate"] == ["COMMON"]
    assert skips == []


def test_common_source_is_not_filled_when_covered_biosamples_disagree():
    """entry ごとに BioSample の値が違うなら、どれか 1 つを COMMON に書くのは誤り。追加提案を出さない。"""
    bs = {"SAMD00000001": {"isolate": "X1"}, "SAMD00000002": {"isolate": "X2"}}
    props, warns, skips = propose_qualifiers_updates(_records_with_two_biosamples(), bs, "t.ann")
    assert [p for p in props if p["qualifier"] == "isolate"] == []
    assert [w for w in warns if w["qualifier"] == "isolate"] == []


def test_common_source_mismatch_with_disagreeing_biosamples_is_reported_as_skipped():
    """ann にも値があり BioSample 側が割れている → 混在スキップとして 1 件（entry は COMMON）。"""
    records = _records_with_two_biosamples()
    for r in records.values():
        r.features[1].qualifiers["isolate"] = ["X0"]
    bs = {"SAMD00000001": {"isolate": "X1"}, "SAMD00000002": {"isolate": "X2"}}
    props, warns, skips = propose_qualifiers_updates(records, bs, "t.ann")
    assert [p for p in props if p["qualifier"] == "isolate"] == []
    assert len(skips) == 1
    assert skips[0]["entry"] == "COMMON" and skips[0]["attr"] == "isolate"
    assert skips[0]["values"] == {"X1", "X2"}
