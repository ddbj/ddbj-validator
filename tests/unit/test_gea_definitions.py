"""definitions.json 内部の整合テスト（GEA）。

ルール実装が正しくても定義ファイル内の参照が食い違うと、投稿者がどうやっても通せない状態や、
逆に何も検査されない状態が生まれる。実際に次の取りこぼしが起きていた。

- `Comment[Submission Type]` の CV を `controlled_terms` 直下に置いてしまい、`GEA_COM0002` が
  `controlled_terms.idf.<level>` しか見ないため **どのルールからも読まれない死んだ定義**になっていた。
- `experiment_types` は technology 判定にしか使われず、`Comment[Experiment Type]` の CV が無かったため
  **任意の値が通っていた**（2026-09-18 に CV 化）。
- `RIP-chip by array` / `RIP-Chip by array` のように大文字小文字だけ違う語が二重にあった。

同種の取りこぼしを検出するための整合テスト。

実行: リポジトリルートで `.venv/bin/python -m pytest`
"""
import pytest

from apps.gea.defs import load_definitions

DEFS = load_definitions()
IDF = DEFS["idf"]
CT = DEFS["controlled_terms"]
CV_IDF = CT["idf"]
EXPERIMENT_TYPES = DEFS["experiment_types"]
#: types で定義された submission type（= ルールの only_type が取り得る値）
SUBMISSION_TYPES = {t["submission_type"] for t in DEFS["types"]}


def _alpha(names):
    """case-insensitive のアルファベット順（同値は文字コード順）。定義ファイルの並び規約。"""
    return sorted(names, key=lambda n: (n.lower(), n))


# --- Comment[Experiment Type]: experiment_types と CV の一致 ------------------

def test_experiment_type_cv_exists():
    """`Comment[Experiment Type]` の CV が `controlled_terms.idf.error` にあること。

    無いと GEA_COM0002 が検査せず、experiment type はどんな値でも通ってしまう。
    """
    assert "Comment[Experiment Type]" in CV_IDF["error"]


def test_experiment_types_and_cv_are_identical():
    """`experiment_types` のキー集合と `Comment[Experiment Type]` の CV が一致すること。

    CV にしか無い語は technology が引けず submission type が other に落ちる。
    experiment_types にしか無い語は GEA_COM0002 が CV 外として弾く。どちらも投稿者には直せない。
    """
    cv = set(CV_IDF["error"]["Comment[Experiment Type]"])
    keys = set(EXPERIMENT_TYPES)
    assert not keys - cv, f"CV に不足: {sorted(keys - cv)}"
    assert not cv - keys, f"experiment_types に不足: {sorted(cv - keys)}"


def test_experiment_type_cv_is_alphabetical():
    """CV はアルファベット順で維持すること（語の追加位置を人が探せるように）。"""
    cv = CV_IDF["error"]["Comment[Experiment Type]"]
    assert cv == _alpha(cv)


def test_experiment_types_keys_are_alphabetical():
    """`experiment_types` のキーもアルファベット順で維持すること。"""
    keys = list(EXPERIMENT_TYPES)
    assert keys == _alpha(keys)


def test_experiment_types_have_no_case_duplicates():
    """大文字小文字だけ違う語が二重に無いこと（`RIP-chip` / `RIP-Chip` の事故を防ぐ）。"""
    seen = {}
    for name in EXPERIMENT_TYPES:
        seen.setdefault(name.lower(), []).append(name)
    dup = {k: v for k, v in seen.items() if len(v) > 1}
    assert not dup, f"大文字小文字だけ違う語: {dup}"


@pytest.mark.parametrize("name", sorted(EXPERIMENT_TYPES))
def test_experiment_type_technology_is_known(name):
    """`experiment_types` の technology は types の submission_type のいずれかであること。

    未知の値だと GeaSubmission.submission_type がそれを返し、どの only_type にも一致しなくなる。
    """
    tech = EXPERIMENT_TYPES[name].get("technology")
    assert tech in SUBMISSION_TYPES, f"{name}: technology={tech!r}"


# --- Comment[Submission Type]: CV と submission_type_map ----------------------

def test_submission_type_cv_is_under_idf_error():
    """`Comment[Submission Type]` の CV が `controlled_terms.idf.error` にあること。

    `controlled_terms` 直下に置くと `_CvBase`（GEA_COM0002/0003）から読まれず死んだ定義になる。
    """
    assert "Comment[Submission Type]" in CV_IDF["error"]


#: `controlled_terms` の直下に置けるスコープ。どのルールが読むかが 1 対 1 で決まっている。
CV_SCOPES = {"idf", "sdrf", "idf_sdrf", "idf_protocol"}


def test_controlled_terms_has_only_scope_keys():
    """`controlled_terms` の直下はスコープだけであること。

    フィールド名を直下に置くと、どのルールからも読まれない定義になる。
    """
    assert set(CT) <= CV_SCOPES, f"想定外のキー: {sorted(set(CT) - CV_SCOPES)}"


def test_submission_type_map_keys_are_in_cv():
    """`submission_type_map` のキーは `Comment[Submission Type]` の CV に入っていること。

    CV に無い値をキーにしても到達しない（CV 外は GEA_COM0002 が弾く）。
    """
    cv = set(CV_IDF["error"]["Comment[Submission Type]"])
    missing = sorted(set(DEFS["submission_type_map"]) - cv)
    assert not missing, f"CV に無いキー: {missing}"


def test_submission_type_map_covers_cv():
    """CV の全語に submission_type_map の対応があること。

    対応が無い語は submission_type が旧 Comment[Experiment Type] へフォールバックし、
    投稿者から見て判定根拠が読めなくなる。
    """
    cv = set(CV_IDF["error"]["Comment[Submission Type]"])
    missing = sorted(cv - set(DEFS["submission_type_map"]))
    assert not missing, f"submission_type_map に不足: {missing}"


def test_submission_type_map_values_are_known():
    """`submission_type_map` の値は types の submission_type のいずれかであること。"""
    bad = {k: v for k, v in DEFS["submission_type_map"].items() if v not in SUBMISSION_TYPES}
    assert not bad, f"未知の submission type: {bad}"


def test_db_submission_type_map_keys_are_numeric():
    """`db_submission_type_map` のキーは DB の数値コードの文字列であること。

    DB から得た値は `str()` してから引くため、キーが数値文字列でないと必ず外れる。
    """
    bad = sorted(k for k in DEFS["db_submission_type_map"] if not k.isdigit())
    assert not bad, f"数値でないキー: {bad}"


def test_db_submission_type_map_values_are_in_cv():
    """`db_submission_type_map` の値は `Comment[Submission Type]` の CV 語であること。

    この値は IDF に Comment[Submission Type] が無いときの代替として
    `submission_type_map` を引くのに使う。CV 外の値を書くと黙って other に落ちる。
    """
    cv = set(CV_IDF["error"]["Comment[Submission Type]"])
    bad = sorted(set(DEFS["db_submission_type_map"].values()) - cv)
    assert not bad, f"CV に無い値: {bad}"


# --- GEA_COM0004 用スコープ（二重発火の防止）---------------------------------

def test_cv_scopes_do_not_overlap():
    """スコープ間で CV のキーが重複しないこと。

    重複すると同じ違反が 2 本のルールから出る。さらに専用スコープ側（`idf_sdrf` = GEA_COM0004、
    `idf_protocol` = GEA_PR0020）は internal ignore だが `idf` 側（GEA_COM0002）は違うので、
    重複させると ignore が効かなくなる。
    """
    def keys(scope):
        return {f for level in CT.get(scope, {}).values() for f in level}

    scopes = sorted(CV_SCOPES)
    for i, a in enumerate(scopes):
        for b in scopes[i + 1:]:
            dup = sorted(keys(a) & keys(b))
            assert not dup, f"{a} と {b} で重複: {dup}"


# --- 旧フィールド名の読み替え（後方互換）-------------------------------------

def test_renamed_idf_fields_point_to_known_fields():
    """`RENAMED_IDF_FIELDS` の改名先が `idf.fields` に存在すること。

    改名先が未知フィールドだと、旧い IDF を読んだあと誰も参照しない名前になり検査が抜ける。
    """
    from apps.gea.reader import RENAMED_IDF_FIELDS
    known = set(IDF["fields"])
    missing = sorted({new for new in RENAMED_IDF_FIELDS.values() if new not in known})
    assert not missing, f"idf.fields に無い改名先: {missing}"


def test_renamed_idf_fields_sources_are_legacy():
    """`RENAMED_IDF_FIELDS` の改名元が現行の `idf.fields` に残っていないこと。

    新旧が両方 fields にあると、どちらが正なのか定義から読めなくなる。
    """
    from apps.gea.reader import RENAMED_IDF_FIELDS
    known = set(IDF["fields"])
    leftover = sorted({old for old in RENAMED_IDF_FIELDS if old in known})
    assert not leftover, f"旧名が idf.fields に残っている: {leftover}"

# --- sub type ごとの experiment type 選択肢（idf.allowed_experiment_types）----

def test_allowed_experiment_types_covers_every_submission_type():
    """`Comment[Submission Type]` の CV 全語に選択肢リストがあること。

    欠けている sub type は D-way が選択肢を出せない。
    """
    cv = set(CV_IDF["error"]["Comment[Submission Type]"])
    keys = set(IDF["allowed_experiment_types"])
    assert keys == cv, f"不足: {sorted(cv - keys)} / 余分: {sorted(keys - cv)}"


def test_allowed_experiment_types_are_known_terms():
    """選択肢の語が全部 `experiment_types`（= CV）に入っていること。

    入っていない語を D-way が出すと、投稿後に GEA_COM0002 が CV 外として弾く。
    """
    known = set(EXPERIMENT_TYPES)
    for st, terms in IDF["allowed_experiment_types"].items():
        missing = sorted(set(terms) - known)
        assert not missing, f"{st}: experiment_types に無い語 {missing}"


def test_allowed_experiment_types_are_alphabetical_and_unique():
    """選択肢はアルファベット順・重複なしで維持すること。"""
    for st, terms in IDF["allowed_experiment_types"].items():
        assert len(terms) == len(set(terms)), f"{st}: 重複あり"
        assert terms == _alpha(terms), f"{st}: 並びがアルファベット順でない"


# --- sub type ごとの protocol type 既定（protocols.dway_defaults）--------------

def test_dway_default_protocols_cover_every_submission_type():
    """`Comment[Submission Type]` の CV 全語に protocol type の既定があること。"""
    cv = set(CV_IDF["error"]["Comment[Submission Type]"])
    keys = set(DEFS["protocols"]["dway_defaults"])
    assert keys == cv, f"不足: {sorted(cv - keys)} / 余分: {sorted(keys - cv)}"


def test_dway_default_protocols_required_and_optional_do_not_overlap():
    """同じ protocol type が required と optional の両方に入っていないこと。"""
    for st, v in DEFS["protocols"]["dway_defaults"].items():
        req = set(v["required"]) | set(v.get("required_with_raw", []))
        overlap = sorted(req & set(v["optional"]))
        assert not overlap, f"{st}: required と optional が重複 {overlap}"


def test_dway_default_protocols_have_no_duplicates():
    """required / optional のそれぞれに重複がないこと。"""
    for st, v in DEFS["protocols"]["dway_defaults"].items():
        for key in ("required", "optional"):
            terms = v[key]
            assert len(terms) == len(set(terms)), f"{st}.{key}: 重複あり"

def test_allowed_experiment_types_cover_all_terms():
    """`experiment_types` の全語がどこかの sub type の選択肢に入っていること。

    どの sub type からも選べない語は、CV は通るが D-way では選択できない宙に浮いた語になる。
    """
    covered = set()
    for terms in IDF["allowed_experiment_types"].values():
        covered |= set(terms)
    orphan = sorted(set(EXPERIMENT_TYPES) - covered)
    assert not orphan, f"どの sub type にも属さない語: {orphan}"


# --- protocol type の新旧マッピング（2026-09-18 の改名・統合）------------------

#: `Protocol Type` の CV は 2026-09-19 に専用スコープへ移した（GEA_PR0020 が error + ignore で見るため。
#: `controlled_terms.idf.*` に置くと GEA_COM0002/0003 が拾い、項目単位で level と ignore を決められない）。
PROTOCOL_CV = CT["idf_protocol"]["error"]["Protocol Type"]
RENAME_MAP = DEFS["protocols"]["rename_map"]


def test_protocol_rename_targets_are_in_cv():
    """`protocols.rename_map` の改名先が Protocol Type の CV にあること。

    無いと、旧名の IDF を読み替えた結果が CV 外になり GEA_COM0003 が全 protocol で発火する。
    """
    missing = sorted({v for v in RENAME_MAP.values() if v not in PROTOCOL_CV})
    assert not missing, f"CV に無い改名先: {missing}"


def test_protocol_rename_sources_are_not_in_cv():
    """`rename_map` のキー（旧名）が CV に残っていないこと。

    新旧が両方 CV にあると、どちらが正なのか定義から読めなくなる。
    """
    leftover = sorted({k for k in RENAME_MAP if k in PROTOCOL_CV})
    assert not leftover, f"旧名が CV に残っている: {leftover}"


def test_protocol_cv_matches_all_types():
    """`protocols.all_types` と Protocol Type の CV が一致すること（二重管理の崩れを防ぐ）。"""
    assert DEFS["protocols"]["all_types"] == list(PROTOCOL_CV)


def test_dway_default_protocols_are_in_cv():
    """`dway_defaults` の protocol type が全部 CV にあること。

    CV に無い名前を D-way が出すと、投稿後に GEA_COM0003 が CV 外として報告する。
    """
    cv = set(PROTOCOL_CV)
    for st, v in DEFS["protocols"]["dway_defaults"].items():
        missing = sorted((set(v["required"]) | set(v["optional"])) - cv)
        assert not missing, f"{st}: CV に無い protocol type {missing}"


def test_rule_protocol_types_are_in_cv():
    """ルールが必須として見る protocol type が全部 CV にあること。

    改名のときにルール側の値を直し忘れると、そのルールは**永久に発火しない**（誰も気づかない）。
    対象: GEA_PR0008-0015 の `_ptype`、node 系（EX0003/EX0004/LE0005/AN0003/AN0004/
    DADN0004/DADMN0004）の `_ptypes`、GEA_SR0008 の `_accept`。
    実際 2026-09-18 の改名で `_accept`（属性名が違う）の旧名が 2 つ残り、このテストで検出した。
    """
    import inspect
    from apps.gea.rules import idf as I, nodes as N
    cv = set(PROTOCOL_CV)
    bad = {}
    for mod in (I, N):
        for _, cls in inspect.getmembers(mod, inspect.isclass):
            rid = getattr(cls, "rule_id", None)
            if not rid:
                continue
            values = ([getattr(cls, "_ptype", None)]
                      + list(getattr(cls, "_ptypes", ()) or ())
                      + list(getattr(cls, "_accept", ()) or ()))   # GEA_SR0008 は _accept を使う
            outside = sorted({v for v in values if v and v not in cv})
            if outside:
                bad[rid] = outside
    assert not bad, f"CV に無い protocol type を参照しているルール: {bad}"

# --- raw なしのときスキップするルール（skip_conditions）--------------------

def test_skip_conditions_reference_registered_rules():
    """`skip_conditions["raw-less"]` の rule_id が実在し、validator に登録されていること。

    綴り違いや deprecated 化で存在しない rule_id を書いても**何も起きない**（黙って効かない）ので、
    ここで検出する。
    """
    from apps.gea.validator import Validator
    from apps.gea.context import ValidationContext
    registered = {r.rule_id for r in Validator(ValidationContext()).active_rules}
    listed = set(DEFS.get("skip_conditions", {}).get("raw-less", []))
    missing = sorted(listed - registered)
    assert not missing, f"登録されていない rule_id: {missing}"


def test_raw_none_columns_are_known_sdrf_fields():
    """`sdrf.raw_none_columns` が `sdrf.fields` にある列であること。

    定義に無い列名を書くと raw の判定が常に「raw なし」に倒れ、Skip = raw-less の
    ルールが全部黙って消える。
    """
    known = set(DEFS["sdrf"]["fields"]) | set(DEFS["sdrf"].get("legacy_fields", []))
    missing = sorted(set(DEFS["sdrf"].get("raw_none_columns", [])) - known)
    assert not missing, f"sdrf.fields に無い列: {missing}"


def test_dway_required_and_required_with_raw_do_not_overlap():
    """同じ protocol type が `required` と `required_with_raw` の両方に入っていないこと。

    両方にあると GEA_PR0018 と GEA_PR0019 が同じ欠落を二重に報告する。
    """
    for st, v in DEFS["protocols"]["dway_defaults"].items():
        overlap = sorted(set(v["required"]) & set(v.get("required_with_raw", [])))
        assert not overlap, f"{st}: required と required_with_raw が重複 {overlap}"

def test_internal_ignore_ids_are_registered():
    """`INTERNAL_IGNORE_RULE_IDS` の rule_id が validator に登録されていること。

    deprecated 化したルールの ID を ignore に残すと、**どこからも使われない定義**になる。
    ルールを外したときに ignore 側を消し忘れるのを検出する。
    """
    from apps.gea.validator import Validator
    from apps.gea.context import ValidationContext
    from apps.gea.rules.base import INTERNAL_IGNORE_RULE_IDS
    registered = {r.rule_id for r in Validator(ValidationContext()).active_rules}
    stale = sorted(set(INTERNAL_IGNORE_RULE_IDS) - registered)
    assert not stale, f"ignore に残っている未登録の rule_id: {stale}"
