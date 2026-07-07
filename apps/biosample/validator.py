"""BioSample ルールの登録と実行（ddbj validator.py と同型）。

ルールはここに明示列挙して順序を制御する（ddbj 同様、手作業で並べる）。
モード別スキップは能力フラグ（requires_rdb/network/auth）で行う。
"""
from apps.biosample.rules.base import is_internal_ignore
from apps.biosample.rules.mandatory import BS_R0018, BS_R0020, BS_R0025, BS_R0026, BS_R0027
from apps.biosample.rules.structure import BS_R0003, BS_R0061, BS_R0126
from apps.biosample.rules.value_format import BS_R0007, BS_R0009, BS_R0011, BS_R0040, BS_R0093, BS_R0101, BS_R0136, BS_R0139
from apps.biosample.rules.consistency import BS_R0024, BS_R0036, BS_R0062, BS_R0073, BS_R0135, BS_R0137, BS_R0132, BS_R0133, BS_R0001
from apps.biosample.rules.value_ascii import BS_R0058, BS_R0100, BS_R0012, BS_R0013
from apps.biosample.rules.identifier import BS_R0005, BS_R0069, BS_R0099, BS_R0102, BS_R0122, BS_R0109, BS_R0091
from apps.biosample.rules.geo import BS_R0008, BS_R0041, BS_R0094
from apps.biosample.rules.taxonomy import BS_R0004, BS_R0096, BS_R0059, BS_R0115, BS_R0106, BS_R0141, BS_R0045, BS_R0105, BS_R0134, BS_R0140, BS_R0104, BS_R0015
from apps.biosample.rules.package_organism import PackageOrganismValidator
from apps.biosample.rules.voucher import CultureCollectionValidator, SpecimenVoucherValidator, BioMaterialValidator
from apps.biosample.rules.account import BS_R0006, BS_R0129, BS_R0070, BS_R0095, BS_R0128
from apps.biosample.rules.controlled import BS_R0002, BS_R0138


class Validator:
    def __init__(self, context):
        self.context = context
        ctx = context

        available_rules = [
            # --- フェーズ1: 必須・パッケージ（DB 非依存）---
            BS_R0126(),  # 複数 package
            BS_R0025(),  # Package 欠落
            BS_R0026(),  # 未知 Package
            BS_R0018(),  # sample_name 欠落
            BS_R0020(),  # organism 欠落
            BS_R0027(),  # 必須属性欠落
            # --- フェーズ A: 構造・重複・値形式（DB 非依存）---
            BS_R0061(),  # 同名属性の複数値
            BS_R0003(),  # sample_title 重複
            BS_R0007(),  # collection_date 形式
            BS_R0136(),  # collection_date 整形（autofix）
            BS_R0040(),  # collection_date 未来日
            BS_R0009(),  # lat_lon 形式（autofix）
            BS_R0139(),  # lat_lon 不正（error・補正不能）
            BS_R0093(),  # 整数属性
            BS_R0036(),  # either_one_mandatory 群欠落
            BS_R0137(),  # collection_date/geo_loc_name の reporting term
            BS_R0001(),  # 必須属性の missing 値表記を正規化（autofix）
            BS_R0073(),  # 冗長 taxonomy 属性
            BS_R0135(),  # 不正 strain 値
            BS_R0132(),  # genome/clinical で種以下識別子が null（error）
            BS_R0133(),  # Microbe で strain/isolate が null（warning）
            BS_R0058(),  # 非 ASCII 値（BS_R0012 の autocleanup 後に評価するため ℃ 等は既に置換済み）
            BS_R0100(),  # 任意属性の missing 値
            BS_R0005(),  # BioProject 形式
            BS_R0099(),  # locus_tag_prefix 形式
            BS_R0102(),  # locus_tag_prefix 重複(submission)
            BS_R0091(),  # locus_tag_prefix 重複(biosample DB・要 RDB)
            BS_R0109(),  # MIGS.ba/eu で locus_tag_prefix 空（warning）
            BS_R0011(),  # publication identifier
            BS_R0122(),  # GISAID accession
            BS_R0024(),  # 同一属性（区別情報なし）
            BS_R0008(),  # 不正 country（geo_loc_name）
            BS_R0094(),  # geo_loc_name 形式整形（autofix）
            BS_R0041(),  # lat_lon ↔ country 矛盾（geopandas。common/geo）
            BS_R0069(),  # BioProject 連番
            BS_R0062(),  # voucher 同一機関重複
            # --- フェーズ B: taxonomy（DB/NCBI 依存。local ではスキップ）---
            BS_R0004(),  # organism ↔ taxonomy_id 不一致
            BS_R0045(),  # organism→学名＋taxonomy_id 補完（autofix）
            BS_R0105(),  # component_organism→学名（autofix）
            BS_R0015(),  # host→学名（autofix。human→Homo sapiens 特例）
            BS_R0096(),  # species/infraspecific rank
            PackageOrganismValidator(),  # package_vs_organism（BS_R0048＋R0074-0130）
            BS_R0059(),  # sex for bacteria
            BS_R0115(),  # specimen_voucher for bacteria/unclassified
            BS_R0106(),  # metagenome_source
            BS_R0141(),  # uncultured × MIMAG
            BS_R0134(),  # organism vs strain/isolate 識別子不一致（MIGS.ba）
            BS_R0140(),  # genome informal name（Microbe/Pathogen で "genus sp."）
            BS_R0104(),  # genome informal name（MIGS.ba/eu の "genus sp." + taxid）
            # --- 値形式・voucher（A/E 群） ---
            BS_R0101(),  # sample_name 形式
            CultureCollectionValidator(),  # BS_R0113/0114
            SpecimenVoucherValidator(),    # BS_R0116/0117
            BioMaterialValidator(),        # BS_R0118/0119
            # --- フェーズ D: BioProject/account（実装可能分。requires_auth）---
            BS_R0006(),   # BioProject not in account
            BS_R0129(),   # derived_from BioSample not in account
            BS_R0070(),   # umbrella BioProject
            BS_R0095(),   # PSUB -> PRJDB 置換提案
            BS_R0128(),   # locus_tag_prefix に BioProject 必須（DB 非依存）
            # --- フェーズ C: controlled vocabulary（DB 非依存）---
            BS_R0002(),   # CV 大文字小文字違い → 正表記提案（autofix）
            BS_R0138(),   # CV に存在しない値（error）
            # 以降 D 残(R0028/0103/0108/0109) / G(JSON 入力) / autofix 適用層
        ]

        # BS_R0013(空白正規化) と BS_R0012(特殊文字→推奨表記) は autocleanup（前処理）として
        # 最初に in-place 実行し、以降のルールは置換済みの値を評価する（通常のルール列には含めない）。
        # 順序: R0013(空白) → R0012(特殊文字)。これにより ℃ 等は R0058 より先に ASCII 化される。
        self.cleanup_rule = BS_R0013()
        self.special_char_rule = BS_R0012()

        self.active_rules = []
        for rule in available_rules:
            if ctx.skip_db and getattr(rule, "requires_rdb", False):
                continue
            if ctx.skip_ncbi and getattr(rule, "requires_network", False):
                continue
            if ctx.skip_auth and getattr(rule, "requires_auth", False):
                continue
            self.active_rules.append(rule)

    def run(self, submission):
        """submission を全 active_rules で検証し、結果 dict のリストを返す。
        各結果に internal_ignore（=external）を rule_id 単位で付与する（docs rules.txt 準拠）。"""
        results = []
        # autocleanup: BS_R0013(空白正規化) → BS_R0012(特殊文字) の順に in-place 置換。
        # 後続ルールは cleaned 値を読む（℃ 等は R0058 より先に ASCII 化される）。
        results.extend(self.cleanup_rule.validate(submission, self.context))
        results.extend(self.special_char_rule.validate(submission, self.context))
        for rule in self.active_rules:
            results.extend(rule.validate(submission, self.context))
        for r in results:
            r["external"] = is_internal_ignore(r["rule_id"])
        return results
