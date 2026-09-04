"""definitions.json 内部の整合テスト（MetaboBank）。

ルール実装は正しくても定義ファイル内の参照が食い違うと、投稿者がどうやっても通せない
組み合わせが生まれる。実際に `required_experiment_types` の MALDI-MS が要求する語が
`Comment[Experiment type]` の CV に無く、MB_IR0034（語が必要）と MB_IR0015（CV 外は error）が
相互に矛盾する状態になっていた。同種の取りこぼしを検出するための整合テスト。

実行: リポジトリルートで `.venv/bin/python -m pytest`
"""
import pytest

from apps.metabobank.defs import load_definitions

DEFS = load_definitions()
IDF = DEFS["idf"]
SDRF = DEFS["sdrf"]
CV_IDF = DEFS["controlled_terms"]["idf"]

# submission type をキーに持つ定義（キーは Comment[Submission type] の CV に無ければならない）
_SUBMISSION_TYPE_KEYED = [
    ("idf.required_protocol_types", IDF["required_protocol_types"]),
    ("idf.required_protocol_parameters", IDF["required_protocol_parameters"]),
    ("idf.required_experiment_types", IDF["required_experiment_types"]),
    ("sdrf.column_order", SDRF["column_order"]),
    ("sdrf.required_columns_error_exclude", SDRF.get("required_columns_error_exclude", {})),
]


def test_required_experiment_types_are_in_controlled_terms():
    """required_experiment_types の語は全部 Comment[Experiment type] の CV に入っていること。

    入っていないと MB_IR0034 が要求する語を MB_IR0015 が CV 外として弾き、その submission type は
    どんな値でも通せなくなる。
    """
    cv = set(CV_IDF["error"]["Comment[Experiment type]"])
    missing = sorted({t for terms in IDF["required_experiment_types"].values() for t in terms} - cv)
    assert not missing, f"controlled_terms.idf.error['Comment[Experiment type]'] に不足: {missing}"


def test_required_protocol_types_are_in_controlled_terms():
    """required_protocol_types の語は全部 Protocol Type の CV に入っていること。"""
    cv = set(CV_IDF["warning"]["Protocol Type"])
    missing = sorted({t for terms in IDF["required_protocol_types"].values() for t in terms} - cv)
    assert not missing, f"controlled_terms.idf.warning['Protocol Type'] に不足: {missing}"


@pytest.mark.parametrize("name, mapping", _SUBMISSION_TYPE_KEYED,
                         ids=[n for n, _ in _SUBMISSION_TYPE_KEYED])
def test_submission_type_keys_are_in_controlled_terms(name, mapping):
    """submission type をキーにする定義のキーは Comment[Submission type] の CV に入っていること。

    タイポや廃止済みの type が残っていると、その定義は永久に参照されない死んだ設定になる。
    """
    cv = set(CV_IDF["error"]["Comment[Submission type]"])
    unknown = sorted(set(mapping) - cv)
    assert not unknown, f"{name} に未知の submission type: {unknown}"


def test_required_protocol_parameters_reference_declared_protocol_types():
    """required_protocol_parameters の protocol 名は、同じ submission type の
    required_protocol_types に宣言されていること（MB_IR0018 が参照できない定義を防ぐ）。"""
    bad = [(st, pname)
           for st, params in IDF["required_protocol_parameters"].items()
           for pname in params
           if pname not in set(IDF["required_protocol_types"].get(st, []))]
    assert not bad, f"required_protocol_types に無い protocol を参照: {bad}"


def test_required_columns_error_exclude_targets_required_columns():
    """required_columns_error_exclude で除外する列は required_columns_error にある列であること
    （必須でない列を除外しても意味がなく、綴り違いの検出になる）。"""
    req = set(SDRF["required_columns_error"])
    bad = [(st, col) for st, cols in SDRF.get("required_columns_error_exclude", {}).items()
           for col in cols if col not in req]
    assert not bad, f"required_columns_error に無い列を除外: {bad}"
