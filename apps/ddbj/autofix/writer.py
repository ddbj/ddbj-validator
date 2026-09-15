"""フェーズ 3 の書き出し: 承認済み autofix の .ann への適用、クリーンな .ann / FASTA、CDS アミノ酸 FASTA。

`AutofixTask` と `_apply_autofix_worker` は ProcessPoolExecutor に渡すため**モジュールのトップレベル**に置く
（pickle 可能である必要がある）。他はファイル書き出しの純粋な関数。
2026-09-15 に apps/ddbj/orchestrator.py から移動（中身は不変）。
"""
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from apps.ddbj.preprocessor import preprocess_files, ANN_EXTENSIONS
from apps.ddbj.parser import parse_ddbj_submission
from apps.ddbj.utils.translation import get_cds_translation_params, get_insdc_translation
from common.features import get_features, get_expected_transl_table


@dataclass(frozen=True)
class AutofixTask:
    """Autofix 適用ワーカー (_apply_autofix_worker) へ渡す入力一式。"""
    ann_path: Any
    seq_path: Any
    file_updates: Any
    tax_data: Any
    cv_terms: Any
    report_out_dir: Any


# ============================================================================
# ワーカー2: Autofix 適用とファイル生成を行う
# ============================================================================
def _apply_autofix_worker(task):
    ann_path = task.ann_path
    seq_path = task.seq_path
    file_updates = task.file_updates
    tax_data = task.tax_data
    cv_terms = task.cv_terms
    report_out_dir = task.report_out_dir
    
    from apps.ddbj.preprocessor import preprocess_files
    from apps.ddbj.parser import parse_ddbj_submission
    
    ann_lines, fasta_content, _ = preprocess_files(ann_path, seq_path)
    records, _, _ = parse_ddbj_submission(fasta_content, ann_path, ann_lines, {})
    
    # -o オプションがあればそこへ。なければ入力ファイルの親へ
    base_out_dir = Path(report_out_dir) if report_out_dir else Path(ann_path).parent
    
    fixed_dir = base_out_dir / "fixed"
    fixed_dir.mkdir(parents=True, exist_ok=True)
    
    fixed_fasta = fixed_dir / Path(seq_path).name 
    fast_copy_and_fix_fasta(fasta_content, fixed_fasta)
                
    original_ann_name = Path(ann_path).name
    for ext in ANN_EXTENSIONS:
        if original_ann_name.endswith(ext):
            original_ann_name = original_ann_name[:-len(ext)] + ".ann"
            break
    else:
        original_ann_name = Path(ann_path).with_suffix(".ann").name
        
    fixed_ann = fixed_dir / original_ann_name
    
    if file_updates:
        write_autofix_to_file(ann_lines, file_updates, fixed_ann)
    else:
        write_clean_ann(ann_lines, fixed_ann)

    aa_dir = base_out_dir / "aa"
    base_name = original_ann_name[:-4] if original_ann_name.endswith('.ann') else Path(original_ann_name).stem
    aa_fasta_path = aa_dir / f"AA_{base_name}.faa"
    
    is_aa_written = write_aa_fasta(records, aa_fasta_path, tax_data, cv_terms)
    
    msgs = []
    if file_updates:
        msgs.append(f"  => Auto-fixed ANN saved to: {fixed_ann}")
    else:
        msgs.append(f"  => Cleaned ANN saved to: {fixed_ann}")
    msgs.append(f"  => Cleaned FASTA saved to: {fixed_fasta}")
    if is_aa_written:
        msgs.append(f"  => Translated AA FASTA saved to: {aa_fasta_path}")
        
    return "\n".join(msgs)
    
    


def write_autofix_to_file(ann_lines, updates, out_path):
    current_entry = ""
    update_count = 0
    pending_new_features = [u for u in updates if u.get("action") == "add_feature"]
    
    with open(out_path, "w", encoding="utf-8", newline="\n") as fout:
        for line_no_0, line in enumerate(ann_lines):
            line_no = line_no_0 + 1
            clean_line = line.rstrip("\r\n")

            if not clean_line or clean_line.isspace():
                continue

            cols = clean_line.split("\t")
            
            if len(cols) > 0 and cols[0].strip():
                new_entry = cols[0].strip()
                
                if current_entry and new_entry != current_entry:
                    for u in list(pending_new_features):
                        if u.get("entry") == current_entry:
                            fout.write(f"\t{u.get('feature_type', '')}\t\t{u.get('qualifier', '')}\t{u.get('new_value', '')}\n")
                            update_count += 1
                            pending_new_features.remove(u)
                            
                current_entry = new_entry
                
            active_entry = current_entry

            if len(cols) < 3:
                fout.write(line + "\n")
                continue
                                
            entry = cols[0]
            feat_type = cols[1]
            loc_str = cols[2]
            qualifier = cols[3] if len(cols) > 3 else ""
            value = cols[4] if len(cols) > 4 else ""
            
            line_modified = False

            for u in updates:
                target_entry = str(u.get("entry", "")).strip()
                
                is_target_match = (
                    target_entry == active_entry or 
                    target_entry == "ALL_ENTRIES" or 
                    active_entry in ("", "COMMON")
                )

                if is_target_match:
                    action = u.get("action", "")
                    
                    if action == "update_location":
                        if feat_type.strip() == str(u.get("feature_type", "")).strip() and loc_str.strip().replace(" ", "") == str(u.get("old_value", "")).strip().replace(" ", ""):
                            cols[2] = str(u["new_value"])
                            loc_str = cols[2]
                            line_modified = True
                            update_count += 1
                            
                    elif action == "update_qualifier":
                        q_file = qualifier.strip()
                        q_target = str(u.get("qualifier", "")).strip()
                        v_file = str(value).strip()
                        v_target = str(u.get("old_value", "")).strip()

                        if q_target == q_file and v_file == v_target:
                            if len(cols) == 3:
                                cols.extend([str(u["qualifier"]), str(u["new_value"])])
                            elif len(cols) == 4:
                                cols.append(str(u["new_value"]))
                            else:
                                cols[4] = str(u["new_value"])
                                
                            qualifier = cols[3] if len(cols) > 3 else ""
                            value = cols[4] if len(cols) > 4 else ""
                            line_modified = True
                            update_count += 1
                                        
            if line_modified:
                fout.write("\t".join(cols) + "\n")
            else:
                fout.write(line + "\n")

            for u in updates:
                if u.get("action") == "add_qualifier" and u.get("feature_line") == line_no:
                    fout.write(f"\t\t\t{u['qualifier']}\t{u['new_value']}\n")
                    update_count += 1
                    
        for u in pending_new_features:
            if u.get("entry") == current_entry or current_entry == "":
                fout.write(f"\t{u.get('feature_type', '')}\t\t{u.get('qualifier', '')}\t{u.get('new_value', '')}\n")
                update_count += 1

    return update_count > 0
    
def write_clean_ann(ann_lines, out_path):
    with open(out_path, "w", encoding="utf-8", newline="\n") as fout:
        for line in ann_lines:
            clean_line = line.rstrip("\r\n")

            if not clean_line or clean_line.isspace():
                continue
                
            cols = clean_line.split("\t")
            if len(cols) not in (3, 4, 5):
                continue
            fout.write(line + "\n")

def write_aa_fasta(records, out_path, tax_data=None, cv_terms=None):
    has_output = False
    out_lines = []

    for entry_id, record in records.items():
        if entry_id == "COMMON":
            continue

        cds_serial = 1
        default_table_id = get_expected_transl_table(record, tax_data) if tax_data else 1

        for feature in get_features(record, "CDS"):
            if any(q in feature.qualifiers for q in ("pseudo", "pseudogene", "exception")):
                cds_serial += 1
                continue

            table_id, codon_start = get_cds_translation_params(feature, default_table_id)
            aa_seq = get_insdc_translation(feature, record, table_id, codon_start, cv_terms)

            if aa_seq:
                loc_str = getattr(feature, 'original_location', str(feature.location))
                header = f">{entry_id}.{cds_serial} {loc_str}"
                
                seq_lines = [aa_seq[i:i+60] for i in range(0, len(aa_seq), 60)]
                
                out_lines.append(header)
                out_lines.extend(seq_lines)
                out_lines.append("//")
                
                has_output = True
            
            cds_serial += 1

    if has_output:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8", newline="\n") as fout:
            fout.write("\n".join(out_lines) + "\n")
        return True
        
    return False    
                                        
def fast_copy_and_fix_fasta(fasta_content, dst_fasta_path):
    if not fasta_content:
        return

    data = fasta_content
    if data.startswith('>'):
        data = data[1:]

    blocks = data.split('\n>')
    
    with open(dst_fasta_path, 'w', encoding='utf-8', newline='\n') as f:
        for block in blocks:
            if not block or block.isspace():
                continue
                
            idx = block.find('\n')
            if idx == -1:
                # 配列がなくヘッダーのみの場合
                f.write(f">{block}\n//\n")
            else:
                header = block[:idx]
                raw_seq = block[idx+1:].lower()
                
                # 1. 末尾の正しい '//' を安全に除去（改行や空白が連続していても対応）
                raw_seq = re.sub(r'//\s*$', '', raw_seq)
                
                # 2. 不正な文字（タブ、スペース等の空白、ハイフン、途中の //）のみを削除
                # 元の改行（折り返し）はそのまま維持される
                clean_seq = re.sub(r'[ \t\f\v　]|-|//', '', raw_seq)
                
                # 3. ヘッダー出力後、配列を出力し、最後に // を追加
                f.write(f">{header}\n")
                if clean_seq:
                    # 末尾の余分な改行を一旦整理して出力
                    f.write(clean_seq.rstrip('\r\n') + "\n")
                f.write("//\n")
                
                
