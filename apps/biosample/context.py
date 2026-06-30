"""BioSample validator の検証コンテキスト。

- パッケージ定義（属性順・必須/任意・lineage 条件）は **JSON が正**:
  apps/biosample/resources/attributes_packages.json を読み込む（DB ではなく JSON を参照）。
- skip_db / skip_ncbi / skip_auth でモード別に外部依存ルールをスキップ（ddbj と同じ骨格）。
"""
import json
from pathlib import Path
from dataclasses import dataclass, field
from typing import Any

_RES = Path(__file__).resolve().parent / "resources"
# 共通 CV（国名リスト等）は common/resources/definitions.json を再利用
_COMMON_DEF = Path(__file__).resolve().parents[2] / "common" / "resources" / "definitions.json"


def load_packages():
    """attributes_packages.json を読み込み (fixed_attributes, packages) を返す。"""
    data = json.loads((_RES / "attributes_packages.json").read_text(encoding="utf-8"))
    return data.get("fixed_attributes", {}), data.get("packages", {})


def load_cv_terms():
    """common/resources/definitions.json の cv_terms（countries 等）を返す。"""
    try:
        return json.loads(_COMMON_DEF.read_text(encoding="utf-8")).get("cv_terms", {})
    except Exception:
        return {}


@dataclass
class ValidationContext:
    account: Any = None
    skip_db: bool = False
    skip_ncbi: bool = False
    skip_auth: bool = False
    fixed_attributes: dict = field(default_factory=dict)
    packages: dict = field(default_factory=dict)
    cv_terms: dict = field(default_factory=dict)
    # organism 名 -> taxonomy 情報（common/db_taxonomy or NCBI で取得。local では空）
    tax_data: dict = field(default_factory=dict)

    def __post_init__(self):
        if not self.packages:
            self.fixed_attributes, self.packages = load_packages()
        if not self.cv_terms:
            self.cv_terms = load_cv_terms()

    def package_def(self, package_key):
        """パッケージ定義（attributes/lineage 等）を返す。無ければ None。"""
        return self.packages.get(package_key)

    def attribute_uses(self, package_key):
        """そのパッケージの属性名 -> use（fixed_attributes ＋ package.attributes）。"""
        uses = {n: info.get("use", "") for n, info in self.fixed_attributes.items()}
        pkg = self.packages.get(package_key) or {}
        for n, info in pkg.get("attributes", {}).items():
            uses[n] = info.get("use", "")
        return uses

    def mandatory_attributes(self, package_key):
        """そのパッケージで use=='mandatory' の属性名集合（fixed_attributes 含む）。"""
        return {n for n, u in self.attribute_uses(package_key).items() if u == "mandatory"}

    def either_one_attributes(self, package_key):
        """use=='either_one_mandatory' の属性名集合（「いずれか1つ必須」群）。"""
        return {n for n, u in self.attribute_uses(package_key).items() if u == "either_one_mandatory"}
