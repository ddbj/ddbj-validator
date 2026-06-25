"""BioSample SSUB 更新用 TSV の生成（-b/--biosample 機能）。

DBLINK の BioSample アクセッション番号から SSUB(submission) 単位で、登録システムと同じ
列順・必須(*)表記の TSV を生成する。列順は attributes_packages.json に焼き込み済みのため、
ここでは fixed_attributes ＋ package.attributes の定義順をそのまま用いる（順序ロジックは不要）。

このモジュールは DB に依存しない純粋なロジック（リソース読込＋整形）のみを持つ。
DB 取得は db_meta_biosample.fetch_biosample_ssub、オーケストレーションは orchestrator が担う。
"""
import json
from pathlib import Path

# MIxS 系のベースパッケージ（package_group == "MIxS" のときに複合キーを組む）
_MIXS_GROUP = "MIxS"


def _resource_path(*parts):
    # apps/ddbj/biosample/tsv.py -> parents[2] == apps/ ＝ リソース基点
    return Path(__file__).resolve().parents[2].joinpath(*parts)


def load_biosample_definitions():
    """attributes_packages.json を読み込み (fixed_attributes, packages) を返す。"""
    path = _resource_path("biosample", "resources", "attributes_packages.json")
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("fixed_attributes", {}), data.get("packages", {})


def load_biosample_sync():
    """ddbj definitions.json の biosample_sync（ann↔BioSample 対応）を返す。"""
    path = _resource_path("ddbj", "resources", "definitions.json")
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("biosample_sync", {"common": [], "mapping": []})


def resolve_package_key(package, env_package, package_group, packages):
    """DB の (package, env_package, package_group) から attributes_packages.json のキーを解決する。

    MIxS グループは `package.env_package` の複合キー（env が無い/no_package なら bare package に
    フォールバック）。Standard / Pathogen は package そのまま。見つからなければ None。
    """
    if not package:
        return None
    if package_group == _MIXS_GROUP:
        if env_package and env_package != "no_package":
            composite = f"{package}.{env_package}"
            if composite in packages:
                return composite
        if package in packages:
            return package
        return None
    # Standard / Pathogen など
    return package if package in packages else None


def ordered_attributes(package_key, fixed_attributes, packages):
    """パッケージの全属性を (name, use) のリストで返す（fixed_attributes ＋ package.attributes の定義順）。

    定義順 = 登録システム TSV の列順（attributes_packages.json に焼き込み済み）。
    """
    result = [(name, info.get("use", "")) for name, info in fixed_attributes.items()]
    pkg = packages.get(package_key, {})
    for name, info in pkg.get("attributes", {}).items():
        result.append((name, info.get("use", "")))
    return result


def _mark(name, use):
    """必須属性に '*' を付与する登録システム表記。"""
    return f"*{name}" if use == "mandatory" else name


def build_header(package_key, fixed_attributes, packages, with_accession=True):
    """TSV ヘッダ列のリストを返す。with_accession=True で先頭に biosample_accession を付ける。"""
    cols = []
    if with_accession:
        cols.append("biosample_accession")
    cols.extend(_mark(name, use) for name, use in ordered_attributes(package_key, fixed_attributes, packages))
    return cols


def _escape(value):
    """TSV セル値のエスケープ（タブ・改行を空白へ）。"""
    if value is None:
        return ""
    return str(value).replace("\t", " ").replace("\r", " ").replace("\n", " ")


def build_ssub_tsv(samples, fixed_attributes, packages, overrides=None):
    """SSUB 1 件分の TSV テキストを生成する。

    samples: [{"accession_id", "package", "env_package", "package_group",
               "attributes": {attr_name: value}}, ...]（SSUB 内の全サンプル）。
    overrides: {accession_id: {attr_name: ann_value}}。指定サンプルの属性を ann 値で上書き
               （autofix で ann_wins と判定された属性。ann の内容で BioSample を更新するため）。
    ヘッダは代表パッケージ（先頭サンプル）で決定する（通常 1 SSUB は同一パッケージ）。
    値は各サンプルの attributes から、ヘッダ順（'*' を除いた素の属性名）で取り出す。
    戻り値: (tsv_text, package_key)。package_key が解決できない場合は (None, None)。
    """
    if not samples:
        return None, None
    overrides = overrides or {}
    rep = samples[0]
    package_key = resolve_package_key(
        rep.get("package"), rep.get("env_package"), rep.get("package_group"), packages
    )
    if package_key is None:
        return None, None

    attr_order = [name for name, _ in ordered_attributes(package_key, fixed_attributes, packages)]
    pkg_set = set(attr_order)

    # パッケージ定義に無いが既存サンプルが現に持つ属性（extra）を末尾に付与する。
    # 登録システムの TSV と同様、サンプルの値を欠落させないため（更新作業で重要）。
    # 複数サンプルで出現する extra は初出順に集約する（DB の seq_no 順を保持）。
    extras = []
    seen = set(pkg_set)
    for s in samples:
        for name in s.get("attributes", {}):
            if name not in seen:
                seen.add(name)
                extras.append(name)

    full_order = attr_order + extras
    header = build_header(package_key, fixed_attributes, packages, with_accession=True)
    header.extend(extras)  # extra は必須マーク無し

    lines = ["\t".join(header)]
    for s in samples:
        attrs = dict(s.get("attributes", {}))
        # ann_wins の属性を ann 値で上書き（このサンプルが対象 SAMD の場合）
        acc = s.get("accession_id", "")
        if acc in overrides:
            attrs.update(overrides[acc])
        row = [_escape(acc)]
        row.extend(_escape(attrs.get(name, "")) for name in full_order)
        lines.append("\t".join(row))
    return "\n".join(lines) + "\n", package_key
