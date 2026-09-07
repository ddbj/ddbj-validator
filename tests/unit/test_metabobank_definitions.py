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


def test_column_order_entries_are_known_sdrf_fields():
    """`sdrf.column_order`（投稿テンプレートの列順）に載っている列は、すべて
    `sdrf.fields`（既知の列パターン）に当たること。

    当たらないと MB_SR0006「User-defined columns are used.」が
    **テンプレートどおりに書いた投稿に対して出る**。実際 NMR の
    `Acquisition Parameter Data File` / `Free Induction Decay Data File` がこの状態だった。
    """
    from apps.metabobank.rules.sdrf import _matches_any
    fields = SDRF["fields"]
    bad = {}
    for st, cols in SDRF["column_order"].items():
        # column_order の "Protocol REF:<type>" は列種別としては Protocol REF
        norm = ["Protocol REF" if c.startswith("Protocol REF") else c for c in cols]
        miss = sorted({c for c in norm if c and not _matches_any(c, fields)})
        if miss:
            bad[st] = miss
    assert not bad, f"sdrf.fields に無い列がテンプレートにある: {bad}"


def test_protocol_positions_cover_declared_protocol_types():
    """`protocol_positions` の protocol type が `required_protocol_types` と過不足なく一致すること。

    このデータは MB 登録システムが SDRF テンプレートの列順を組むために使う。
    **validator は参照しない**ので、綴り違いや追加漏れを検出できるのはここだけ。
    """
    declared = {t for types in IDF["required_protocol_types"].values() for t in types}
    positions = set(DEFS["protocol_positions"])
    assert positions == declared, (
        f"protocol_positions に無い: {sorted(declared - positions)} / "
        f"required_protocol_types に無い: {sorted(positions - declared)}")


def test_protocol_positions_reference_known_columns():
    """`before` / `fallback` が指す先が、既知の列か既知の protocol type であること。"""
    from apps.metabobank.rules.sdrf import _matches_any
    positions = DEFS["protocol_positions"]
    bad = []
    for name, spec in positions.items():
        for key in ("before", "fallback"):
            col = spec.get(key)
            if not col:
                continue
            if col.startswith("Protocol REF:"):
                if col.split(":", 1)[1] not in positions:
                    bad.append((name, key, col, "未知の protocol type"))
            elif not _matches_any(col, SDRF["fields"]):
                bad.append((name, key, col, "sdrf.fields に無い列"))
    assert not bad, f"参照先が解決できない: {bad}"


def test_required_columns_error_exclude_targets_required_columns():
    """required_columns_error_exclude で除外する列は required_columns_error にある列であること
    （必須でない列を除外しても意味がなく、綴り違いの検出になる）。"""
    req = set(SDRF["required_columns_error"])
    bad = [(st, col) for st, cols in SDRF.get("required_columns_error_exclude", {}).items()
           for col in cols if col not in req]
    assert not bad, f"required_columns_error に無い列を除外: {bad}"
