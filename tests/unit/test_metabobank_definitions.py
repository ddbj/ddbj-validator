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


def test_required_groups_have_at_least_two_members():
    """required_group_* のグループは 2 要素以上であること。

    MB_IR0008/0009 は「グループ内のどれかが埋まっていて、どれかが空」で発火するので、
    1 要素のグループは構造上発火しない＝定義だけ残った死んだ設定になる。
    """
    for key in ("required_group_error", "required_group_warning"):
        for name, members in IDF.get(key, {}).items():
            assert len(members) >= 2, f"idf.{key}['{name}'] が 1 要素（発火しない）"


def test_experimental_factor_is_fully_optional():
    """Experimental Factor Name / Type は必須ではない（任意項目）。

    factor は「書かない」が正規の書き方なので、必須にすると正規の書き方が error になる。
    Name は null value のみ不許可（required_not_null）で、Type は何も検証しない。
    """
    assert "Experimental Factor Name" not in IDF["required_error"]
    assert "Experimental Factor Type" not in IDF["required_error"]
    assert "Experimental Factor Type" not in IDF["required_not_null"]
    assert "Experimental Factor" not in IDF["required_group_error"]
    # Name は「書かない」は可・「missing と書く」は不可
    assert "Experimental Factor Name" in IDF["required_not_null"]


def test_experimental_factor_type_has_no_validation():
    """Type は CV も値形式も持たない（何もチェックしない任意項目）。"""
    for level in ("error", "warning"):
        assert "Experimental Factor Type" not in CV_IDF.get(level, {})
    assert "Experimental Factor Type" not in DEFS.get("value_formats", {}).get("idf", {})


def test_factor_value_column_is_not_required():
    """SDRF の Factor Value / Processed Data File / Metabolite Assignment File は任意。"""
    joined = " ".join(SDRF["required_columns_warning"] + SDRF["required_columns_error"])
    for token in ("Factor Value", "Processed Data File", "Metabolite Assignment File"):
        assert token not in joined, f"{token} が必須/推奨列に残っている"


def test_autofix_null_to_empty_fields_are_known_idf_fields():
    """autofix_null_to_empty の項目名は idf.fields に存在すること（誤記の検出）。"""
    unknown = sorted(set(IDF["autofix_null_to_empty"]) - set(IDF["fields"]))
    assert not unknown, f"idf.fields に無い項目名: {unknown}"


def test_autofix_null_to_empty_fields_are_not_mandatory():
    """null value を空にする項目は必須であってはならない（空にすると MB_IR0005 になる）。"""
    for f in IDF["autofix_null_to_empty"]:
        assert f not in IDF["required_error"], f"{f} は必須なので空にできない"
        assert f not in IDF["required_warning"], f"{f} は必須なので空にできない"


def test_temperature_is_never_a_required_protocol_parameter():
    """Temperature 系（Temperature / Temperature 1 / 2）はどの submission type でも必須にしない。

    公開 114 study で MB_IR0018 が発火した 92 件（81%）は、submission type を問わず全部この
    Temperature の欠落が原因だった（他パラメータの欠落は 1 件も無し）。記載負荷が高く、
    実運用と要求が合っていないため NMR sample も含めて任意とする。
    """
    left = [f"{st} / {ptype}: {x}"
            for st, protos in IDF["required_protocol_parameters"].items()
            for ptype, params in protos.items()
            for x in params if x == "Temperature" or x.startswith("Temperature ")]
    assert not left, f"Temperature が必須のまま: {left}"
