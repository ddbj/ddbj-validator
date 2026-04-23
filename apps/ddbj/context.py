import json
from pathlib import Path
from dataclasses import dataclass, field
from apps.ddbj.db_metadata import fetch_valid_journals
import geopandas as gpd

@dataclass
class ValidationContext:
    """
    検証プロセス全体で共有されるコンテキスト（外部DBデータ、実行モード、および解析対象ファイル固有の状態）を保持するクラス
    """
    # 外部DB・環境データ
    is_curator_mode: bool = True
    bp_psubs: dict = field(default_factory=dict)
    dra_refs: dict = field(default_factory=dict)
    drr_status: dict = field(default_factory=dict)
    tax_data: dict = field(default_factory=dict)
    bs_data: dict = field(default_factory=dict)
    bs_submitters: dict = field(default_factory=dict)
    bs_smp_ids: dict = field(default_factory=dict)
    psub_to_prjdb: dict = field(default_factory=dict)
    smp_id_to_samd: dict = field(default_factory=dict)
    institution_codes: dict = field(default_factory=dict)
    cv_terms: dict = field(default_factory=dict)
    
    # JSON辞書を保持するフィールド
    ddbj_dict: dict = field(default_factory=dict)
    dra_crosscheck_dict: dict = field(default_factory=dict)
    dra_lib_meta: dict = field(default_factory=dict)

    # 地理情報バリデーション用データ
    geo_mapping: dict = field(default_factory=dict)
    geo_df: gpd.GeoDataFrame = None

    # DBから取得した有効なジャーナル名のセットを保持するフィールド
    valid_journals: set = field(default_factory=set)
    ncbi_private_accs: set = field(default_factory=set)
    
    # ファイル・サブミッション固有のメタデータ（判定キャッシュ）
    is_wgs: bool = False
    is_tsa: bool = False
    is_tpa: bool = False
    is_est: bool = False
    is_eukaryote: bool = False
    is_prokaryote: bool = False
    active_datatypes: set = field(default_factory=set)
    active_divisions: set = field(default_factory=set)
    
    def __post_init__(self):
        # プロジェクトルートの取得
        project_root = Path(__file__).resolve().parent.parent.parent
        
        # リソースディレクトリの定義
        ddbj_resources_dir = project_root / "apps" / "ddbj" / "resources"
        common_resources_dir = project_root / "common" / "resources"
        geo_dir = common_resources_dir / "geo"
        
        # 1. DDBJ Dictionary の読み込み
        dict_path = ddbj_resources_dir / "definitions.json"        
        if not self.ddbj_dict:
            if dict_path.is_file():
                with open(dict_path, "r", encoding="utf-8") as f:
                    self.ddbj_dict = json.load(f)
                self.cv_terms = self.ddbj_dict.get("cv_terms", {})
            else:
                print(f"Warning: Dictionary file not found at {dict_path}")
                self.ddbj_dict = {"features": {}, "qualifiers": {}}  
                self.cv_terms = {}  

        # 2. DRA Crosscheck の読み込み
        crosscheck_path = ddbj_resources_dir / "dra_crosscheck.json"
        if not self.dra_crosscheck_dict:
            if crosscheck_path.is_file():
                with open(crosscheck_path, "r", encoding="utf-8") as f:
                    self.dra_crosscheck_dict = json.load(f)
            else:
                print(f"Warning: DRA crosscheck file not found at {crosscheck_path}")
                self.dra_crosscheck_dict = {"crosscheck_rules": []}
                
        # 3. Institution Codes (coll_dump.txt) の読み込み (common/resources 参照へ変更)
        coll_path = common_resources_dir / "coll_dump.txt"
        if not self.institution_codes and coll_path.is_file():
            with open(coll_path, "r", encoding="utf-8") as f:
                for line in f:
                    # 最初のタブまでしか分割しない(メモリと速度の節約)
                    code = line.split('\t', 1)[0].strip()
                    if code:
                        self.institution_codes[code.lower()] = code

        # 4. 地理データとマッピングの読み込み (ANN1275用)
        mapping_path = geo_dir / "insdc_geo_mapping.json"
        if not self.geo_mapping:
            if mapping_path.exists():
                with open(mapping_path, "r", encoding="utf-8") as f:
                    self.geo_mapping = json.load(f)
            else:
                print(f"[WARN] Geo mapping file not found at {mapping_path}")
                self.geo_mapping = {}

        parquet_path = geo_dir / "countries_50m.parquet"
        if self.geo_df is None:
            if parquet_path.exists():
                try:
                    self.geo_df = gpd.read_parquet(parquet_path)
                    _ = self.geo_df.sindex  # 空間インデックス(R-tree)をメモリに強制展開
                except Exception as e:
                    print(f"[WARN] Failed to load geo_data: {e}")
                    self.geo_df = None
            else:
                print(f"[WARN] GeoParquet file not found at {parquet_path}. Geo-location validation will be skipped.")
                self.geo_df = None

    def load_valid_journals(self, journal_list, db_tax_conn):
        """
        抽出済みのジャーナル名リストをもとにDBに問い合わせて
        存在するジャーナル名のセットを self.valid_journals に格納する
        """
        if journal_list and db_tax_conn:
            self.valid_journals = fetch_valid_journals(db_tax_conn, journal_list)
            
    def analyze_records(self, records: dict):
        """
        ファイル内の全レコードを1度だけ走査し、WGS, TSA, 分類群などのメタデータを抽出・保持する。
        各ファイルごとに状態をリセットしてから解析する。
        """
        if not records:
            return

        # 解析のたびに状態をリセットする
        self.is_wgs = False
        self.is_tsa = False
        self.is_tpa = False
        self.is_est = False
        self.is_eukaryote = False
        self.is_prokaryote = False
        self.active_datatypes = set()
        self.active_divisions = set()

        # 1. DATATYPE と DIVISION の解析 (COMMONレコードから取得)
        common_rec = records.get("COMMON")
        if common_rec:
            # feature_result等でインデックス化されていれば features_by_type 等を使うと更に高速ですが
            # ここでは安全に features をループしています
            for feat in common_rec.features:
                if feat.type == "DATATYPE":
                    for dt in feat.qualifiers.get("type", []):
                        dt_upper = dt.strip().upper()
                        self.active_datatypes.add(dt_upper)
                        if dt_upper == "WGS": self.is_wgs = True
                        if dt_upper == "TSA": self.is_tsa = True
                        if dt_upper == "TPA": self.is_tpa = True
                        if dt_upper == "EST": self.is_est = True
                        
                elif feat.type == "DIVISION":
                    for div in feat.qualifiers.get("division", []):
                        self.active_divisions.add(div.strip().upper())

        # 2. Taxonomy (真核生物/原核生物) の解析
        for record in records.values():
            if record.id == "COMMON":
                continue
                
            for feat in record.features:
                if feat.type == "source":
                    for org in feat.qualifiers.get("organism", []):
                        org_name = org.strip()
                        # すでに self.tax_data に格納されている系統情報を利用
                        tax_info = self.tax_data.get(org_name, {})
                        lineage = tax_info.get("lineage", "")
                        
                        if "Eukaryota" in lineage:
                            self.is_eukaryote = True
                        if "Archaea" in lineage or "Bacteria" in lineage:
                            self.is_prokaryote = True
                            
            # 1つでも真核生物・原核生物の判定ができたら以降のレコードの走査は不要
            if self.is_eukaryote or self.is_prokaryote:
                break