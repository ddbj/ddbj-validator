"""BioProject ルールの登録と実行（ddbj/biosample validator と同型）。

ルールはここに明示列挙して順序を制御する。モード別スキップは能力フラグ（requires_rdb/network/auth）で行う。
現状の実装範囲: Step1(形式は xml_reader 側 R0001/0002/0037)＋Step2(taxonomy R0018/0020/0038/0039, 値 R0060/0059)。
"""
from apps.bioproject.rules.base import is_internal_ignore
from apps.bioproject.rules.value import BP_R0060, BP_R0059
from apps.bioproject.rules.taxonomy import BP_R0018, BP_R0020, BP_R0038, BP_R0039
from apps.bioproject.rules.content import (
    BP_R0004, BP_R0005, BP_R0006, BP_R0007, BP_R0008, BP_R0009, BP_R0010, BP_R0011,
    BP_R0012, BP_R0013, BP_R0014, BP_R0015, BP_R0019, BP_R0040, BP_R0070,
)
from apps.bioproject.rules.locus_tag import (
    BP_R0016, BP_R0021, BP_R0022, BP_R0041, BP_R0042,
)


class Validator:
    def __init__(self, context):
        self.context = context
        available_rules = [
            # --- 値・文字種（DB 非依存）---
            BP_R0060(),  # 非 ASCII
            BP_R0059(),  # データ形式（空白）
            # --- 内容（Step3）---
            BP_R0005(),  # title 20-250 字（min spec。旧 BP_R0005 ID 再利用）
            BP_R0006(),  # description 20-4000 字（min spec）
            BP_R0004(),  # 提出済み project と title+desc 重複（要 DB/account）
            BP_R0007(),  # Relevance 'Other' 説明欠落
            BP_R0008(),  # subtype eOther 説明欠落
            BP_R0009(),  # sample_scope eOther 説明欠落
            BP_R0010(),  # material eOther 説明欠落
            BP_R0011(),  # capture eOther 説明欠落
            BP_R0012(),  # method_type eOther 説明欠落
            BP_R0013(),  # data_type eOther 説明欠落
            BP_R0014(),  # publication id 形式
            BP_R0015(),  # publication reference 欠落
            BP_R0019(),  # multi-species は organism 説明必須
            BP_R0040(),  # ProjectTypeTopSingleOrganism は不正
            BP_R0070(),  # cv_terms（sample_scope/material/capture/method_type/subtype/data_type/db_type）
            # --- locus_tag / umbrella（Step4）---
            BP_R0022(),  # BioSample accession 形式
            BP_R0041(),  # locus_tag_prefix 形式
            BP_R0042(),  # umbrella に prefix 不可
            BP_R0016(),  # umbrella project 妥当性（要 DB）
            BP_R0021(),  # prefix ↔ BioSample ペア妥当性（要 DB）
            # --- taxonomy（DB/NCBI 依存。local ではスキップ）---
            BP_R0038(),  # organism ↔ taxonomy_id 不一致
            BP_R0039(),  # taxonomy 未解決 warning
            BP_R0018(),  # species/infraspecific rank
            BP_R0020(),  # Environment は metagenome
        ]
        self.active_rules = []
        for rule in available_rules:
            if context.skip_db and getattr(rule, "requires_rdb", False):
                continue
            if context.skip_ncbi and getattr(rule, "requires_network", False):
                continue
            if context.skip_auth and getattr(rule, "requires_auth", False):
                continue
            self.active_rules.append(rule)

    def run(self, submission):
        results = []
        for rule in self.active_rules:
            results.extend(rule.validate(submission, self.context))
        for r in results:
            r["external"] = is_internal_ignore(r["rule_id"])
        return results
