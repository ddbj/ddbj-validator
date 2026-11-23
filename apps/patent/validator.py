"""patent の規則の登録。ddbj の Validator（規則を回す loop）を継ぎ、規則の list だけを差し替える。

ddbj から借りる規則は「使うものを選ぶ」（外すものを選ぶのではない）。借りる検査の一覧は
constants.BORROWED_RULE_IDS で、前処理・parser・まとめ役の規則が出すそれ以外の id は runner が捨てる。
"""
from apps.ddbj.validator import Validator
from apps.ddbj.rules.annotation import ANN0160, ANN2010, ANN2030
from apps.ddbj.rules.cross import AXS2080
from apps.ddbj.rules.entry_consistency import ENTRY_CONSISTENCY_VALIDATOR
from apps.ddbj.rules.sequence import FASTA_FORMAT_VALIDATOR, SEQ5050
from apps.patent.rules.sequence import PAT_SEQUENCE
from apps.patent.rules.structure import (
    PAT0008, PAT0009, PAT0010, PAT0011, PAT0012, PAT0019, PAT0024, PAT0028, PAT0030,
    PAT0031, PAT0032, PAT0033, PAT0034, PAT0035, PAT0043, PAT0044, PAT0045, PAT_LINE_FORMAT,
)


class PatentValidator(Validator):
    def _register_rules(self):
        rules = [
            # --- ddbj から借りる規則 ---
            ENTRY_CONSISTENCY_VALIDATOR(),  # SEQ0110 / ANN0120 / AXS0060 / AXS0070: ann と FASTA の entry の対応、重複
            FASTA_FORMAT_VALIDATOR(),       # SEQ0080: FASTA の見出し
            ANN0160(),                      # entry 名
            ANN2010(),                      # source の location の有無
            ANN2030(),                      # location の構文
            AXS2080(),                      # source の location が配列の長さを超える
            SEQ5050(),                      # 2.14 Gb を超える

            # --- 特許の規則: ファイル ---
            PAT0045(),          # ファイル名の _na / _aa
            PAT0031(),          # COMMON の DIVISION が PAT
            PAT_LINE_FORMAT(),  # PAT0034（行の頭のタグ）/ PAT0036（幅）: ann の行をそのまま見る
            PAT_SEQUENCE(),     # PAT0020〜0023 / 0037〜0042: FASTA を 1 回なめる

            # --- 特許の規則: entry ---
            PAT0044(),  # 想定外の feature / qualifier
            PAT0032(),  # 必須の項目
            PAT0011(),  # source は 1 つ
            PAT0012(),  # 公報番号の形（KEYWORD）
            PAT0033(),  # 最初の journal の形
            PAT0034(),  # COMMENT の必須の行
            PAT0035(),  # 公報番号と配列番号の食い違い
            PAT0019(),  # mol_type（NA は必須、AA は不可）
            PAT0024(),  # source の location は 1..<長さ>
            PAT0028(),  # PD の日付
            PAT0008(),  # PF の日付
            PAT0030(),  # PR の日付
            PAT0009(),  # 日付の範囲
            PAT0010(),  # PD が PF より前
        ]
        # taxonomy を引いていないとき（-l）は PAT0043 を登録しない
        if getattr(self.context, "pat_known_organisms", None) is not None:
            rules.append(PAT0043())
        self.active_rules = rules
