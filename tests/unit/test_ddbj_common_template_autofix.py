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
from apps.ddbj.biosample.sync import _filter_by_common, _is_common_template_feature
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
        assert _is_common_template_feature(sources[0]) is True


def test_entry_own_features_are_not_marked():
    records = _parse(_COMMON_ANN)
    rrna = [f for f in records["seq1"].features if f.type == "rRNA"]
    assert len(rrna) == 1
    assert _is_common_template_feature(rrna[0]) is False


def test_entry_level_source_is_not_marked():
    """COMMON テンプレートを使わない（entry ごとに source を書く）ファイルは従来どおり。"""
    ann = [
        "seq1\tsource\t1..40\torganism\tEscherichia coli",
        "\t\t\tmol_type\tgenomic DNA",
    ]
    records = _parse(ann, ">seq1\n" + "ATGC" * 10 + "\n//\n")
    source = [f for f in records["seq1"].features if f.type == "source"][0]
    assert _is_common_template_feature(source) is False


# ---------------- 突合対象の絞り込み ----------------
def _features():
    return [SimpleNamespace(type="source", from_common=True),
            SimpleNamespace(type="source", from_common=False)]


def test_filter_by_common_modes():
    common, own = _features()
    assert _filter_by_common([common, own], "all") == [common, own]
    assert _filter_by_common([common, own], "exclude") == [own]
    assert _filter_by_common([common, own], "only") == [common]


def test_filter_by_common_treats_a_missing_flag_as_entry_own():
    """from_common を持たない feature（テスト用のダミー等）は entry 固有として扱う。"""
    plain = SimpleNamespace(type="source")
    assert _filter_by_common([plain], "exclude") == [plain]
    assert _filter_by_common([plain], "only") == []


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
