from common.rules.base import BaseRule
import re

class ENTRY_CONSISTENCY_VALIDATOR(BaseRule):
    rule_id = "ENTRY_CONSISTENCY_MASTER"
    target = "file"
    description = "Check consistency of entry names, counts, and order between FASTA and ANN files"
    requires_rdb = False
    is_file_level = True

    def validate_file(self, records, context, ann_path=None, seq_path=None, ann_lines=None, fasta_content=None):
        results = []
        if not ann_path or not seq_path:
            return results
        
        fasta_entries = []

        # ディスクから読まずにメモリ上の fasta_content を処理
        if fasta_content is not None:
            for line in fasta_content.splitlines():
                if line.startswith(">"):
                    fasta_entries.append(line[1:].split()[0].strip())

        all_ann_entries = [] # 重複チェック用 (COMMON含む全エントリ)
        ann_entries = []     # FASTA比較用 (COMMONを除いた実エントリ)
        has_common = False
        has_source = False
        has_e_loc = False
        
class ENTRY_CONSISTENCY_VALIDATOR(BaseRule):
    rule_id = "ENTRY_CONSISTENCY_MASTER"
    target = "file"
    description = "Check consistency of entry names, counts, and order between FASTA and ANN files"
    requires_rdb = False
    is_file_level = True

    def validate_file(self, records, context, ann_path=None, seq_path=None, ann_lines=None):
        results = []
        if not ann_path or not seq_path:
            return results
        
        fasta_entries = []
        try:
            with open(seq_path, 'r', encoding='utf-8') as f:
                for line in f:
                    if line.startswith(">"):
                        fasta_entries.append(line[1:].split()[0].strip())
        except Exception:
            pass

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
                res = self.format_result(entry_id="ALL", message=msg, level="error", feature_type="file")
                res["rule"], res["target"] = "SEQ0110", "file"
                results.append(res)
            seen_seq.add(e)

        # 統合された ANN0120 (COMMONもここで一緒にチェックする)
        seen_ann = set()
        for e in all_ann_entries:
            if e in seen_ann:
                msg = f"Duplicate entry name in annotation. ('{e}')"
                level = "error"
                res = self.format_result(entry_id="ALL", message=msg, level=level, feature_type="file")
                res["rule"], res["target"] = "ANN0120", "file"
                results.append(res)
            seen_ann.add(e)

        # ファイル間の一致チェック
        unique_fasta = list(dict.fromkeys(fasta_entries))
        unique_ann = list(dict.fromkeys(ann_entries)) # COMMONが含まれていないので安全に比較できる

        is_template_mode = has_common and has_source and has_e_loc

        if is_template_mode and len(unique_fasta) > 0:
            msg = f"COMMON source information is propagated to {len(unique_fasta)} entries."
            res = self.format_result(entry_id="ALL", message=msg, level="info", feature_type="file")
            res["rule"], res["target"] = "MODE", "file"
            results.append(res)

        if len(unique_fasta) != len(unique_ann):
            if not is_template_mode:
                msg = f"Entry count mismatch: annotation ({len(unique_ann)}) and sequence ({len(unique_fasta)})."
                res = self.format_result(entry_id="ALL", message=msg, level="error", feature_type="file")
                res["rule"], res["target"] = "AXS0060", "file"
                results.append(res)

        if not (is_template_mode and len(unique_fasta) != len(unique_ann)):
            for f_ent, a_ent in zip(unique_fasta, unique_ann):
                if f_ent != a_ent:
                    msg = f"Entry name mismatch: annotation {a_ent} and sequence {f_ent}."
                    res = self.format_result(entry_id="ALL", message=msg, level="error", feature_type="file")
                    res["rule"], res["target"] = "AXS0070", "file"
                    results.append(res)
                    break 

        return results
        