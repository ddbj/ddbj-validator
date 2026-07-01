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


def load_cv_attr():
    """属性別の controlled vocabulary（attribute_name -> 許容値リスト）。
    apps/biosample/resources/controlled_terms.json（登録システムの conf と同一）。R0002/R0138 用。"""
    try:
        return json.loads((_RES / "controlled_terms.json").read_text(encoding="utf-8"))
    except Exception:
        return {}


def load_special_chars():
    """特殊文字→置換文字の対応（℃→degree Celsius 等）。R0012 用。
    apps/biosample/resources/special_characters.json（登録システム conf と同一）。"""
    try:
        return json.loads((_RES / "special_characters.json").read_text(encoding="utf-8"))
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
    cv_terms: dict = field(default_factory=dict)
    # 属性別 controlled vocabulary {attr_name: [許容値]}（R0002/R0138）
    cv_attr: dict = field(default_factory=dict)
    # 特殊文字→置換 {"℃": "degree Celsius", ...}（R0012）
    special_chars: dict = field(default_factory=dict)
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
            self.fixed_attributes, self.packages = load_packages()
        if not self.cv_terms:
            self.cv_terms = load_cv_terms()
        if not self.cv_attr:
            self.cv_attr = load_cv_attr()
        if not self.special_chars:
            self.special_chars = load_special_chars()
        if not self.institution_codes:
            self.institution_codes = load_institution_codes()

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
