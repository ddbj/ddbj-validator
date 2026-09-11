"""definitions.json 内部の整合テスト（MetaboBank）。

ルール実装は正しくても定義ファイル内の参照が食い違うと、投稿者がどうやっても通せない
組み合わせが生まれる。実際に `required_experiment_types` の MALDI-MS が要求する語が
`Comment[Experiment type]` の CV に無く、MB_IR0034（語が必要）と MB_IR0015（CV 外は error）が
相互に矛盾する状態になっていた。同種の取りこぼしを検出するための整合テスト。

実行: リポジトリルートで `.venv/bin/python -m pytest`
"""
import re

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

    当たらないと MB_SR0007「Invalid user-defined columns are added.」（error）が
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


def _temperature_params():
    """required_protocol_parameters に現れる Temperature 系項目（出力対象）。"""
    return [(st, ptype, x)
            for st, protos in IDF["required_protocol_parameters"].items()
            for ptype, params in protos.items()
            for x in params if x == "Temperature" or x.startswith("Temperature ")]


def test_temperature_is_still_emitted_as_a_protocol_parameter():
    """Temperature 系は Protocol Parameters として出力し続けること（Excel に欄を残す）。

    `required_protocol_parameters` は登録システムが IDF/Excel を生成する際の出力項目を
    規定するキーなので、ここから消すと「任意になる」ではなく「欄自体が消える」。
    公式 Excel テンプレは 11 種すべてに Parameter Value[Temperature] を持つ
    （LC-DAD-MS は 2025-01-20 の改訂で追加された）ため、出力は維持する。
    """
    found = {(st, ptype) for st, ptype, _ in _temperature_params()}
    for expected in (("LC-MS", "Chromatography"), ("GC-MS", "Chromatography"),
                     ("LC-DAD-MS", "Chromatography"), ("GC-FID-MS", "Chromatography"),
                     ("GCGC-MS", "Chromatography"), ("NMR", "NMR sample")):
        assert expected in found, f"{expected} の Temperature が出力対象から消えている"


def test_no_protocol_parameter_is_mandatory():
    """必須 protocol parameter は現在 1 つも無いこと（MB_IR0018 が無発火である根拠）。

    公式 Excel テンプレ 11 種の Parameter Value 列 157 個を色で判定すると、以前は
    ORANGE(mandatory) が MSI の Data processing software / version の 2 個だけ
    （残り 155 個は BLUE=optional）だった。その 2 列も他 10 テンプレと揃えて BLUE に
    したため、必須は 0 個になった。テンプレは docs/（.gitignore 対象）にあり
    テストから読めないので、判定結果をここに固定する。

    IDF への宣言自体は required_protocol_parameters（出力仕様）側に残っており、
    test_msi_data_processing_is_still_emitted で担保する。

    空でも MB_IR0018 は deprecated にしていない（将来また必須パラメータが出てくる可能性が
    あるため、定義を足すだけで効く状態を保つ）。
    """
    assert IDF["protocol_parameters_required"] == {}


def test_msi_data_processing_is_still_emitted():
    """任意化しても IDF Protocol Parameters への出力は残すこと。

    出力を止めると登録システムが生成する IDF に宣言が無くなり、SDRF に列を書いた投稿が
    MB_CR0003（SDRF の Parameter Value が IDF に未宣言）で落ちる。
    """
    assert IDF["required_protocol_parameters"]["MSI"]["Data processing"] == [
        "Data processing software", "Data processing software version"]


def test_temperature_is_never_required():
    """Temperature 系は必須リストに載っていないこと（出力はするが任意）。

    以前は出力仕様のキー（required_protocol_parameters）をそのまま必須として読んでいたため、
    公開 114 study の 81%（92 件）で Temperature の未記入を誤ってエラーにしていた。
    """
    req = {x for protos in IDF["protocol_parameters_required"].values()
           for params in protos.values() for x in params}
    bad = sorted({x for _, _, x in _temperature_params() if x in req})
    assert not bad, f"Temperature が必須のまま: {bad}"


def test_required_parameters_are_also_emitted():
    """必須にする項目は出力仕様にも入っていること（出さないものは必須にできない）。"""
    emitted = IDF["required_protocol_parameters"]
    for st, protos in IDF["protocol_parameters_required"].items():
        for ptype, params in protos.items():
            have = emitted.get(st, {}).get(ptype, [])
            missing = sorted(set(params) - set(have))
            assert not missing, f"required_protocol_parameters['{st}']['{ptype}'] に無い: {missing}"


def test_required_protocol_parameters_have_a_column_position():
    """Protocol Parameters に出す項目は必ず sdrf.column_order にも位置を持つこと。

    登録システムは IDF `Protocol Parameters` を definitions からのみ生成するため、
    片方だけ更新すると SDRF に列があるのに IDF が宣言せず MB_CR0003
    （Parameter Value in SDRF is not declared as a Protocol Parameter in IDF）に化ける。
    実際に LC-DAD-MS の `Resolution` が公式 Excel テンプレにだけ存在して両方から欠けていた。
    """
    order = SDRF["column_order"]
    for st, protos in IDF["required_protocol_parameters"].items():
        if st not in order:
            continue
        cols = set(order[st])
        missing = sorted({x for params in protos.values() for x in params
                          if f"Parameter Value[{x}]" not in cols})
        assert not missing, f"sdrf.column_order['{st}'] に列が無い必須 parameter: {missing}"


def test_lc_dad_ms_declares_resolution_as_protocol_parameter():
    """LC-DAD-MS の Chromatography は Resolution を Protocol Parameters に出すこと。

    このキーは「IDF Protocol Parameters として出力する項目」を規定しており、
    必須／任意は規定していない（Excel には任意項目として現れる）。
    位置は Chromatography ブロックの末尾（Signal range の直後）。実データ 37 study の
    IDF Protocol Parameters、ruby 登録システムの protocols.txt、公式テンプレの SDRF ヘッダが
    すべて `...;Guard column;Detector;Signal range;Resolution` で一致する
    （テンプレの MB_Study_IDF / Protocol Parameters 行だけが Column type の直後で、
    自身の SDRF シートとも食い違う外れ値だった）。
    ここが欠けていると登録システムが IDF に宣言せず、SDRF に列があるのに MB_CR0003 に化ける。
    """
    ch = IDF["required_protocol_parameters"]["LC-DAD-MS"]["Chromatography"]
    assert "Resolution" in ch
    assert ch.index("Resolution") == ch.index("Signal range") + 1


def test_column_order_parameter_sequence_matches_protocol_parameters():
    """sdrf.column_order の Parameter Value 列の並びが Protocol Parameters の順と一致すること。

    MB_SR0026（Invalid column order）は `Parameter Value[x]` を種別に丸めて評価するので
    順序のずれ自体は発火しないが、登録システムは両方を使って Excel/IDF を生成するため
    ずれると出力の列順と宣言順が食い違う。実際に LC-DAD-MS は Temperature が
    Chromatography ブロックの末尾に、GC-FID-MS は Temperature が 2 回入っていた。
    """
    order = SDRF["column_order"]
    for st, protos in IDF["required_protocol_parameters"].items():
        if st not in order:
            continue
        seq = [m.group(1) for c in order[st]
               if (m := re.fullmatch(r"Parameter Value\[(.+)\]", c))]
        expected = [x for params in protos.values() for x in params]
        assert seq == expected, f"{st}: column_order={seq} / parameters={expected}"


def test_column_order_has_no_duplicate_parameter_value_columns():
    """同じ Parameter Value 列が column_order に 2 回現れないこと（GC-FID-MS の Temperature）。"""
    for st, cols in SDRF["column_order"].items():
        pv = [c for c in cols if c.startswith("Parameter Value[")]
        dup = sorted({c for c in pv if pv.count(c) > 1})
        assert not dup, f"column_order['{st}'] に重複: {dup}"


def test_temperature_column_is_followed_by_a_unit_column():
    """`Parameter Value[Temperature]` の直後には必ず `Unit[temperature]` が来ること。

    公式 Excel テンプレは Parameter Value[Temperature] の直後に Unit[temperature] を置く。
    GC-FID-MS / NMR には入っていたが GC-MS / LC-MS / LC-DAD-MS で欠けていた。
    （GCGC-MS は Temperature 1 / 2 でテンプレ側にも Unit 列が無いため対象外。）
    """
    for st, cols in SDRF["column_order"].items():
        for i, c in enumerate(cols):
            if c == "Parameter Value[Temperature]":
                assert cols[i + 1:i + 2] == ["Unit[temperature]"], \
                    f"column_order['{st}'] の Temperature 直後が {cols[i + 1:i + 2]}"


def test_unit_columns_are_named():
    """`Unit[...]` は名前付きで定義すること（無名の `Unit[]` を残さない）。

    Unit の名前は登録者が決めるものではなく直前の Parameter Value で決まるため、
    公式 Excel テンプレと同じ名前を JSON に明記する。無名だと登録システムが生成する
    Excel に名前の無い `Unit[]` 列が出てしまう。
    """
    bare = [st for st, cols in SDRF["column_order"].items() if "Unit[]" in cols]
    assert not bare, f"無名の Unit[] が残っている: {bare}"


def test_unit_column_names_match_their_anchor_parameter():
    """`Unit[...]` の名前が直前の Parameter Value に対応していること（テンプレ準拠）。

    MSI は Section thickness / Spatial resolution / Pixel size x,y / Max dimension x,y の
    後がすべて `Unit[length]` で、列名から機械的には導けないためここに固定する。
    """
    expected = {
        "Parameter Value[Temperature]": "Unit[temperature]",
        "Parameter Value[Magnetic field strength]": "Unit[magnetic_field_strength]",
        "Parameter Value[Section thickness]": "Unit[length]",
        "Parameter Value[Spatial resolution]": "Unit[length]",
        "Parameter Value[Pixel size x]": "Unit[length]",
        "Parameter Value[Pixel size y]": "Unit[length]",
        "Parameter Value[Max dimension x]": "Unit[length]",
        "Parameter Value[Max dimension y]": "Unit[length]",
    }
    for st, cols in SDRF["column_order"].items():
        for i, c in enumerate(cols):
            if not c.startswith("Unit["):
                continue
            anchor = cols[i - 1]
            assert anchor in expected, f"column_order['{st}']: {c} の直前が想定外の {anchor}"
            assert c == expected[anchor], \
                f"column_order['{st}']: {anchor} の直後は {expected[anchor]} のはずが {c}"


def test_required_value_error_columns_are_not_existence_required():
    """`required_value_error` の列は存在必須にしないこと（列の有無と値の必須は別）。

    Raw Data File は raw を持たない投稿では列そのものを書かないのが正規なので、
    存在は required_columns_warning どまり。ただし列があるなら値は必須（MB_SR0009）。
    """
    for col in SDRF["required_value_error"]:
        assert col not in SDRF["required_columns_error"], f"{col} が存在必須になっている"
        assert any(col == p or col in p for p in SDRF["required_columns_warning"]), \
            f"{col} が推奨列にも無い（存在チェックが誰にも拾われない）"


def test_study_type_cv_has_third_party_reanalysis():
    """`Comment[Study type]` に "Third-party reanalysis" があること。

    第三者による再解析は「どんな測定をしたか」ではなく「どういう研究か」なので
    Comment[Experiment type]（測定手法の語彙）ではなく Comment[Study type] に置く。
    MB_IR0015 は strip 後の完全一致（大文字小文字も区別する）なので、この表記でだけ通る。
    """
    assert "Third-party reanalysis" in CV_IDF["error"]["Comment[Study type]"]
    assert "Third-party reanalysis" not in CV_IDF["error"]["Comment[Experiment type]"]


def test_publication_group_is_title_author_journal():
    """Publication group は Title / Author List / Journal の 3 点セット。

    Publication Status は group から外してある。publish 時に unpublished → published へ
    更新する運用が煩雑になるため（値の更新だけで validator が通らなくなるのを避ける）。
    MB_IR0008 は「group 内のどれか 1 つでも値があれば全部必須」という判定なので、
    Status が group に居ると Title/Author List を書いた時点で Status も強制される。
    """
    assert IDF["required_group_error"]["Publication"] == [
        "Publication Title", "Publication Author List", "Publication Journal"]
