"""BioSample の package / attribute 定義を提供する（現行 ruby validator の packages API 相当）。

現行 ruby 版は SPARQL master endpoint から取得するが、こちらは **同梱の静的 JSON**
（`apps/biosample/resources/attributes_packages.json`。オフライン生成で列順・必須を焼き込み済み）
を参照する。列順ロジックは `apps/ddbj/biosample/tsv.py` の共通ヘルパを再利用する。

提供する 3 機能（app.py がルーティング）:
- package_list        … パッケージ一覧（メタ情報付き）
- attribute_list      … 指定パッケージの属性一覧（定義順・use・format・CV）
- attribute_template_file … 登録システムと同一のヘッダ 1 行 TSV テンプレート
"""
import json
from functools import lru_cache
from pathlib import Path

from apps.ddbj.biosample.tsv import build_header, ordered_attributes

_JSON = Path(__file__).resolve().parents[1] / "biosample" / "resources" / "attributes_packages.json"


@lru_cache(maxsize=1)
def _defs():
    """attributes_packages.json 全体を読み込む（プロセス内キャッシュ）。"""
    return json.loads(_JSON.read_text(encoding="utf-8"))


def version():
    """同梱定義のバージョン（metadata.version）。ruby の version パラメータ相当は単一版のみ。"""
    return _defs().get("metadata", {}).get("version", "")


def has_package(package):
    return package in _defs().get("packages", {})


def package_list():
    """全パッケージを (package, full_name, version, package_group, env_package) で返す。"""
    return [
        {
            "package": key,
            "full_name": p.get("full_name", ""),
            "version": p.get("version", ""),
            "package_group": p.get("package_group", ""),
            "env_package": p.get("env_package", ""),
        }
        for key, p in _defs().get("packages", {}).items()
    ]


def attribute_list(package):
    """指定パッケージの属性を定義順（fixed_attributes ＋ package.attributes）で返す。

    各属性に use（mandatory/optional 等）と、マスタ定義（top-level attributes）由来の
    format_pattern / synonyms / allowed_values を付与する。
    """
    d = _defs()
    master = d.get("attributes", {})
    out = []
    for name, use in ordered_attributes(package, d.get("fixed_attributes", {}), d.get("packages", {})):
        m = master.get(name, {})
        out.append({
            "name": name,
            "use": use,
            "format_pattern": m.get("format_pattern", ""),
            "synonyms": m.get("synonyms", []),
            "allowed_values": m.get("allowed_values", []),
        })
    return out


def template_tsv(package):
    """登録システムと同一のヘッダ 1 行 TSV テンプレートを返す（必須は '*' 接頭辞）。

    新規登録用テンプレートのため biosample_accession 列は付けない
    （docs/package-tsv の 229/230 と一致。accession 付きは更新用の別物）。
    """
    d = _defs()
    header = build_header(package, d.get("fixed_attributes", {}), d.get("packages", {}), with_accession=False)
    return "\t".join(header) + "\n"
