import xml.etree.ElementTree as ET
from typing import List, Dict, Any

class BioSampleXMLParser:
    """
    BioSampleのXMLをパースし、マルチバリュー対応の属性と
    フラットな管理情報・登録者情報を含む構造化辞書に変換するパーサー
    """
    def __init__(self, xml_source: str):
        self.xml_source = xml_source

    def parse(self) -> List[Dict[str, Any]]:
        tree = ET.parse(self.xml_source)
        root = tree.getroot()
        records = []

        for biosample in root.findall("BioSample"):
            record = {
                "sample_name": None,
                "submission_id": None,  # 後ほど値を取得（プレースホルダー）
                "accession": None,
                "package": None,
                "last_update": biosample.get("last_update"),
                "publication_date": biosample.get("publication_date"),
                "access": biosample.get("access"),
                "submission": {
                    "organization": None,
                    "submitters": []
                },
                # 重複を許容するため、値は必ずリストに格納する
                "attributes": {}
            }

            # 【ヘルパー関数】属性を追加（重複時はリストに追記）
            def add_attribute(name: str, value: str):
                if name not in record["attributes"]:
                    record["attributes"][name] = []
                record["attributes"][name].append(value)

            # 1. Accession ID の取得
            primary_id = biosample.find(".//Ids/Id[@is_primary='1']")
            if primary_id is not None and primary_id.text:
                record["accession"] = primary_id.text

            # 2. パッケージ名 (Model) の取得
            model = biosample.find(".//Models/Model")
            if model is not None and model.text:
                record["package"] = model.text

            # 3. Submission情報 (旧Owner) の取得
            owner_node = biosample.find("Owner")
            if owner_node is not None:
                # 組織名
                org_name = owner_node.find("Name")
                if org_name is not None and org_name.text:
                    record["submission"]["organization"] = org_name.text
                
                # 連絡先リスト (submitters)
                for contact in owner_node.findall(".//Contact"):
                    first_name = contact.find(".//First")
                    last_name = contact.find(".//Last")
                    
                    contact_info = {
                        "email": contact.get("email"),
                        "first_name": first_name.text if first_name is not None else None,
                        "last_name": last_name.text if last_name is not None else None,
                    }
                    record["submission"]["submitters"].append(contact_info)

            # 4. 専用タグ (<Description>) から必須属性を抽出
            desc = biosample.find("Description")
            if desc is not None:
                sample_name = desc.find("SampleName")
                if sample_name is not None and sample_name.text:
                    record["sample_name"] = sample_name.text # ルート階層にもセット
                    add_attribute("sample_name", sample_name.text)

                title = desc.find("Title")
                if title is not None and title.text:
                    add_attribute("sample_title", title.text)

                organism = desc.find("Organism")
                if organism is not None:
                    tax_id = organism.get("taxonomy_id")
                    if tax_id:
                        add_attribute("taxonomy_id", tax_id)
                    
                    org_name = organism.find("OrganismName")
                    if org_name is not None and org_name.text:
                        add_attribute("organism", org_name.text)

            # 5. <Attributes> タグ内の一般属性を抽出
            attributes_node = biosample.find("Attributes")
            if attributes_node is not None:
                for attr in attributes_node.findall("Attribute"):
                    attr_name = attr.get("attribute_name")
                    attr_value = attr.text
                    if attr_name and attr_value:
                        add_attribute(attr_name, attr_value)

            records.append(record)

        return records