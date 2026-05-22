import csv
import json

def generate_biosample_json():
    # シンプルな基本構造
    output_data = {
        "metadata": {
            "version": "1.0",
            "description": "DDBJ BioSample package and attribute definition"
        },
        "attributes": {},
        "packages": {}
    }

    # 複数値を許容する属性のハードコードリスト
    MULTIPLE_ALLOWED_ATTRS = [
        "locus_tag_prefix",
        "component_organism",
        "culture_collection",
        "metagenome_source",
        "specimen_voucher",
        "virus_enrich_appr"
    ]

    # ==========================================
    # 1. attribute.tsv の読み込み（属性カタログ）
    # ==========================================
    with open("attribute.tsv", "r", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            harmonized_name = row.get("Harmonized name", "").strip()
            if not harmonized_name:
                continue

            # Synonym を配列化
            synonyms_str = row.get("Synonym", "").strip()
            synonyms = [s.strip() for s in synonyms_str.split(",") if s.strip()]

            # 基本の属性情報を辞書として作成
            attr_info = {
                "name": row.get("Name", "").strip(),
                "synonyms": synonyms,
                "format_pattern": row.get("Format", "").strip(),
                "cv_terms": []
            }

            # 複数許容の属性のみ "allow_multiple": true を追加
            if harmonized_name in MULTIPLE_ALLOWED_ATTRS:
                attr_info["allow_multiple"] = True

            output_data["attributes"][harmonized_name] = attr_info

    # ==========================================
    # 2. package.tsv の読み込み（パッケージのメタデータ）
    # ==========================================
    with open("package.tsv", "r", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            pkg_name = row.get("Package name", "").strip()
            if not pkg_name:
                continue

            # EnvPackageのクレンジング
            env_package = row.get("EnvPackage", "").strip()
            if env_package.lower() == "no environmental package":
                env_package = ""

            output_data["packages"][pkg_name] = {
                "full_name": row.get("DisplayName", "").strip(),
                "version": row.get("Version", "").strip(),
                "package_group": row.get("Group", "").strip(),
                "env_package": env_package,
                "not_recommended_for": [],
                "attributes": {}
            }

    # ==========================================
    # 3. package-attribute.tsv の読み込み（マトリックス）
    # ==========================================
    with open("package-attribute.tsv", "r", encoding="utf-8") as f:
        reader = csv.reader(f, delimiter="\t")
        headers = next(reader)
        
        # 3列目以降が属性名のヘッダー
        attribute_names = headers[2:]

        for row in reader:
            if not row or len(row) < 2:
                continue
            pkg_name = row[0].strip()
            
            # メタデータ(package.tsv)に存在しないパッケージはスキップ
            if pkg_name not in output_data["packages"]:
                continue

            pkg_ref = output_data["packages"][pkg_name]
            
            # 各属性のフラグをパース
            for attr_name, flag in zip(attribute_names, row[2:]):
                flag = flag.strip()
                
                # '-' や '-:N'、空文字の場合は含めない
                if flag.startswith("-") or not flag:
                    continue

                attr_info = {}
                
                # O:N などの亜種にも対応できるように startswith で判定
                if flag.startswith("M"):
                    attr_info["use"] = "mandatory"
                elif flag.startswith("O"):
                    attr_info["use"] = "optional"
                elif flag.startswith("E:"):
                    attr_info["use"] = "either_one_mandatory"
                    # グループ名を小文字に変換 (例: "E:Organism" -> "organism")
                    attr_info["group"] = flag.split(":", 1)[1].strip().lower()
                else:
                    attr_info["use"] = flag 

                # 辞書への追加順序がそのままTSVの出力順序として保持される
                pkg_ref["attributes"][attr_name] = attr_info

    # ==========================================
    # JSON 出力
    # ==========================================
    output_path = "packages.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)

    print(f"✅ 生成完了: {output_path}")

if __name__ == "__main__":
    generate_biosample_json()