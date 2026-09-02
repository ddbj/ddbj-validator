from common.rules.base import BaseRule
import re
import logging

logger = logging.getLogger(__name__)

class ENTRY_CONSISTENCY_VALIDATOR(BaseRule):
    rule_id = "ENTRY_CONSISTENCY_MASTER"
    target = "file"
    description = "Check consistency of entry names, counts, and order between FASTA and ANN files"
    requires_rdb = False
    is_file_level = True

    def validate_file(self, records, context, ann_path=None, seq_path=None, ann_lines=None,
                      fasta_content=None):
        results = []
        if not ann_path or not seq_path:
            return results
        
        fasta_entries = []
        if fasta_content is not None:
            # 前処理済みの内容がメモリ上にあるのでディスクから読み直さない
            for line in fasta_content.splitlines():
                if line.startswith(">"):
                    fasta_entries.append(line[1:].split()[0].strip())
        else:
            try:
                with open(seq_path, 'r', encoding='utf-8') as f:
                    for line in f:
                        if line.startswith(">"):
                            fasta_entries.append(line[1:].split()[0].strip())
            except Exception as e:
                logger.debug(f"Failed to read FASTA for entry consistency check ({seq_path}): {e}", exc_info=True)

        all_ann_entries = [] # 重複チェック用 (COMMON含む全エントリ)
        ann_entries = []     # FASTA比較用 (COMMONを除いた実エントリ)
        has_common = False
        has_source = False
        has_e_loc = False
        
        if ann_lines is not None:
            current_entry_name = ""
            for line in ann_lines:
                if not line.strip() or line.startswith('#'): continue
                parts = line.split('\t')
                
                if parts[0] and not parts[0].startswith(' '):
                    current_entry_name = parts[0].strip()
                    all_ann_entries.append(current_entry_name)
                    
                    if current_entry_name == "COMMON":
                        has_common = True
                    else:
                        ann_entries.append(current_entry_name)
                        
                feat_type = parts[1].strip() if len(parts) > 1 else ""
                loc_str = parts[2].strip() if len(parts) > 2 else ""
                
                if current_entry_name == "COMMON":
                    if feat_type == "source":
                        has_source = True
                    if loc_str and re.search(r'\bE\b', loc_str, re.IGNORECASE):
                        has_e_loc = True

        # ファイル内重複チェック        
        seen_seq = set()
        for e in fasta_entries:
            if e in seen_seq:
                msg = f"Duplicate entry name in sequence."
                res = self.format_result(entry_id="ALL", message=msg, level="error", feature_type="file", rule="SEQ0110", target="file")
                results.append(res)
            seen_seq.add(e)

        # 統合された ANN0120 (COMMONもここで一緒にチェックする)
        seen_ann = set()
        for e in all_ann_entries:
            if e in seen_ann:
                msg = f"Duplicate entry name in annotation. ('{e}')"
                level = "error"
                res = self.format_result(entry_id="ALL", message=msg, level=level, feature_type="file", rule="ANN0120", target="file")
                results.append(res)
            seen_ann.add(e)

        # ファイル間の一致チェック
        unique_fasta = list(dict.fromkeys(fasta_entries))
        unique_ann = list(dict.fromkeys(ann_entries)) # COMMONが含まれていないので安全に比較できる

        is_template_mode = has_common and has_source and has_e_loc

        if is_template_mode and len(unique_fasta) > 0:
            msg = f"COMMON source information is propagated to {len(unique_fasta)} entries."
            res = self.format_result(entry_id="ALL", message=msg, level="info", feature_type="file", rule="MODE", target="file")
            results.append(res)

        if len(unique_fasta) != len(unique_ann):
            if not is_template_mode:
                msg = f"Entry count mismatch: annotation ({len(unique_ann)}) and sequence ({len(unique_fasta)})."
                res = self.format_result(entry_id="ALL", message=msg, level="error", feature_type="file", rule="AXS0060", target="file")
                results.append(res)

        if not (is_template_mode and len(unique_fasta) != len(unique_ann)):
            # 単純な zip 比較だと片側にエントリが 1 つ余分にあるだけで以降が全てずれて
            # 不一致だらけになるため、余分な側を読み飛ばして再同期しながら比較する。
            ann_set = set(unique_ann)
            fasta_set = set(unique_fasta)
            i = j = 0

            while i < len(unique_fasta) and j < len(unique_ann):
                f_ent = unique_fasta[i]
                a_ent = unique_ann[j]

                if f_ent == a_ent:
                    i += 1
                    j += 1
                    continue

                msg = f"Entry name mismatch: annotation {a_ent} and sequence {f_ent}."
                res = self.format_result(entry_id="ALL", message=msg, level="error", feature_type="file", rule="AXS0070", target="file")
                results.append(res)

                f_in_ann = f_ent in ann_set
                a_in_fasta = a_ent in fasta_set

                if not f_in_ann and a_in_fasta:
                    i += 1  # FASTA 側にのみ存在するエントリ
                elif f_in_ann and not a_in_fasta:
                    j += 1  # アノテーション側にのみ存在するエントリ
                else:
                    # 単なる並び順違い、または双方にしか無い名前同士
                    i += 1
                    j += 1

        return results
        