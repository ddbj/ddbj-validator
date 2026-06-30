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


def load_packages():
    """attributes_packages.json を読み込み (fixed_attributes, packages) を返す。"""
    data = json.loads((_RES / "attributes_packages.json").read_text(encoding="utf-8"))
    return data.get("fixed_attributes", {}), data.get("packages", {})


@dataclass
class ValidationContext:
    account: Any = None
    skip_db: bool = False
    skip_ncbi: bool = False
    skip_auth: bool = False
    fixed_attributes: dict = field(default_factory=dict)
    packages: dict = field(default_factory=dict)

    def __post_init__(self):
        if not self.packages:
            self.fixed_attributes, self.packages = load_packages()

    def package_def(self, package_key):
        """パッケージ定義（attributes/lineage 等）を返す。無ければ None。"""
        return self.packages.get(package_key)

    def mandatory_attributes(self, package_key):
        """そのパッケージで use=='mandatory' の属性名集合（fixed_attributes 含む）。"""
        result = {n for n, info in self.fixed_attributes.items() if info.get("use") == "mandatory"}
        pkg = self.packages.get(package_key) or {}
        for n, info in pkg.get("attributes", {}).items():
            if info.get("use") == "mandatory":
                result.add(n)
        return result
