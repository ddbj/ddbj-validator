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
    """attributes_packages.json を読み込み (fixed_attributes, packages, attributes) を返す。
    attributes は属性グローバル定義 {name: {allowed_values, format_pattern, synonyms, invalid_values, ...}}。"""
    data = json.loads((_RES / "attributes_packages.json").read_text(encoding="utf-8"))
    return data.get("fixed_attributes", {}), data.get("packages", {}), data.get("attributes", {})


def load_cv_terms():
    """common/resources/definitions.json の cv_terms（countries 等）を返す。"""
    try:
        return json.loads(_COMMON_DEF.read_text(encoding="utf-8")).get("cv_terms", {})
    except Exception:
        return {}


def build_cv_attr(attributes):
    """属性グローバル定義から controlled vocabulary {attr_name: [許容値]} を構築（R0002/R0138）。
    CV は attributes_packages.json の attributes[name].allowed_values に集約済み
    （旧 controlled_terms.json は廃止）。missing 系の値は R0002/R0138 側で別途スキップ。"""
    return {n: info["allowed_values"] for n, info in attributes.items()
            if isinstance(info, dict) and info.get("allowed_values")}


def load_value_autofix():
    """autofix 用の値補正辞書（special_characters / null_not_recommended）をまとめて返す。
    apps/biosample/resources/value_autofix.json。R0012（特殊文字）/ R0001（非推奨 null 値）用。"""
    try:
        return json.loads((_RES / "value_autofix.json").read_text(encoding="utf-8"))
    except Exception:
        return {}


_COLL_DUMP = Path(__file__).resolve().parents[2] / "common" / "resources" / "coll_dump.txt"


def load_institution_codes():
    """NCBI BioCollections の機関コード集合（common/resources/coll_dump.txt。ddbj と同一ファイル）。
    戻り値: {code_lower: code}。"""
    codes = {}
    try:
        with _COLL_DUMP.open("r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("#"):
                    continue
                code = line.split("\t", 1)[0].strip()
                if code:
                    codes[code.lower()] = code
    except Exception:
        pass
    return codes


@dataclass
class ValidationContext:
    account: Any = None
    skip_db: bool = False
    skip_ncbi: bool = False
    skip_auth: bool = False
    fixed_attributes: dict = field(default_factory=dict)
    packages: dict = field(default_factory=dict)
    # 属性グローバル定義 {name: {allowed_values, format_pattern, synonyms, ...}}（attributes_packages.json）
    attributes: dict = field(default_factory=dict)
    cv_terms: dict = field(default_factory=dict)
    # 属性別 controlled vocabulary {attr_name: [許容値]}（R0002/R0138。attributes から構築）
    cv_attr: dict = field(default_factory=dict)
    # 特殊文字→置換 {"℃": "degree Celsius", ...}（R0012）
    special_chars: dict = field(default_factory=dict)
    # 非推奨 null 値の正規表現リスト（R0001）
    null_not_recommended: list = field(default_factory=list)
    # organism 名 -> taxonomy 情報（common/db_taxonomy or NCBI で取得。local では空）
    tax_data: dict = field(default_factory=dict)
    # NCBI BioCollections 機関コード {code_lower: code}
    institution_codes: dict = field(default_factory=dict)
    # account 所属アクセッション（--account 指定時に取得。R0006/R0129 用）
    authorized_projects: set = field(default_factory=set)
    authorized_samds: set = field(default_factory=set)
    # BioProject メタ {PRJDBxxxx: {project_type, status_id}}（R0070 umbrella 判定）
    bp_meta: dict = field(default_factory=dict)
    # PSUB -> {accession(PRJDB), status_id}（R0095 置換提案）
    psub_to_prjd: dict = field(default_factory=dict)
    # biosample DB 登録済み locus_tag_prefix -> {submission_id, ...}（R0091 DB 重複）
    registered_locus_tag_prefixes: dict = field(default_factory=dict)

    def __post_init__(self):
        if not self.packages:
            self.fixed_attributes, self.packages, self.attributes = load_packages()
        if not self.cv_terms:
            self.cv_terms = load_cv_terms()
        if not self.cv_attr:
            self.cv_attr = build_cv_attr(self.attributes)
        if not self.special_chars or not self.null_not_recommended:
            vc = load_value_autofix()
            if not self.special_chars:
                self.special_chars = vc.get("special_characters", {})
            if not self.null_not_recommended:
                self.null_not_recommended = vc.get("null_not_recommended", [])
        if not self.institution_codes:
            self.institution_codes = load_institution_codes()

    def package_def(self, package_key):
        """パッケージ定義（attributes/lineage 等）を返す。無ければ None。"""
        return self.packages.get(package_key)

    def country_terms(self):
        """許可される国名集合（cv_terms.countries ∪ historical_countries）。R0008/R0094 で共用。"""
        return set(self.cv_terms.get("countries", [])) | set(self.cv_terms.get("historical_countries", []))

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
