import sys
import re
from pathlib import Path

ANN_EXTENSIONS = ('.ann', '.annt.tsv', '.ann.txt')
FASTA_EXTENSIONS = ('.fasta', '.seq.fa', '.fa', '.fna', '.seq')

MULTI_SPACE_PATTERN = re.compile(r' {2,}')
# 全角空白も削除
STRIP_CHARS = ' \t\r\n"　'

# 戻り値の2つ目は「FASTAのパス」ではなく「FASTAのファイル内容(文字列)」になる
def preprocess_files(ann_path_str: str, fasta_path_str: str) -> tuple[list, str, list]:
    ann_path = Path(ann_path_str)
    fasta_path = Path(fasta_path_str)
    warnings = []

    def _add_warn(level, rule, target, entry, msg, category, is_cleanup=False, file_name=ann_path.name, full_path=ann_path_str):
        """警告・エラー辞書を構築してリストに追加するヘルパー"""
        w = {
            "level": level, "rule": rule, "target": target, "entry": entry,
            "message": msg, "file": file_name, "full_path": full_path, "category": category
        }
        if is_cleanup:
            w["is_cleanup"] = True
        warnings.append(w)

    # 1. インメモリで保持するためのリスト
    cleaned_ann_lines = []
    ann_crlf_detected = False
    
    ann0180_count = 0
    ann0170_count = 0
    ann0185_count = 0
    
    with open(ann_path, 'r', encoding='utf-8', errors='replace') as f:
        content = f.read()
        
    if '\r\n' in content:
        ann_crlf_detected = True
        
    lines = content.splitlines()
    for line_no, clean_line in enumerate(lines, 1):
        if not clean_line or clean_line.isspace() or clean_line.startswith('#'):
            cleaned_ann_lines.append(clean_line)
            continue
            
        # 空白(スペース・タブ)をすべて除去し、小文字化して判定する
        normalized_line = re.sub(r'\s+', '', clean_line).lower()
        
        # 前方一致でヘッダーをキャッチする
        if normalized_line.startswith("entryfeature"):
            _add_warn("warning", "ANN0190", "file/format", "ALL", 
                      f"[Auto-cleanup] Header line was detected and automatically removed. (Line {line_no})", 
                      "annotation", is_cleanup=True)
            
            # データは破棄しつつ、下流での行番号ズレを防ぐために「空行」を格納する
            cleaned_ann_lines.append("") 
            continue  # これ以降のカラム分割やエントリーとしての格納処理はスキップ
        
        cols = clean_line.split('\t')
        num_cols = len(cols)
                
        if num_cols not in (3, 4, 5):
            entry_name = cols[0].strip() if cols[0].strip() else "ALL"
            base_msg = f"Invalid column count (Expected 3, 4 or 5, Found {num_cols})."
            msg = f"{base_msg} Columns 6 and beyond will be ignored." if num_cols > 5 else base_msg

            _add_warn("ERROR", "ANN0140", "file", entry_name, msg, "annotation")
            
            if num_cols > 5:
                # 6カラム以上の場合は、先頭5カラムに切り詰めて後続の処理へ進む
                cols = cols[:5]
            else:
                # 3カラム未満の場合は正常に処理できないため、元のまま追加してスキップ
                cleaned_ann_lines.append(clean_line)
                continue
                                                                
        # ANN0180, ANN0170, ANN0185 の処理
        cleaned_cols = []
        for i, val in enumerate(cols):
            if val:
                # 正規表現ではなく組み込みメソッドで高速に前後の空白・クォートを除去
                cleaned_val = val.strip(STRIP_CHARS)
                if cleaned_val != val:
                    ann0180_count += 1
                    val = cleaned_val
            
                if i == 4 and val:
                    # 連続スペースの縮約
                    new_val = MULTI_SPACE_PATTERN.sub(' ', val)
                    if new_val != val:
                        ann0170_count += 1
                        val = new_val
                        
                    if '"' in val:
                        ann0185_count += 1
                    
            cleaned_cols.append(val)
            
        entry_id = cleaned_cols[0] if cleaned_cols[0] else "UNKNOWN"

        if not clean_line.isascii():
            _add_warn("fatal", "ANN0040", "", entry_id, f"Non-ASCII characters detected. (Line {line_no})", "annotation")

        if len(clean_line) > 10000:
            _add_warn("fatal", "ANN0050", "", entry_id, f"Line exceeds 10,000 characters. (Line {line_no})", "annotation")
            
        cleaned_ann_lines.append('\t'.join(cleaned_cols))

    if ann0180_count > 0:
        _add_warn("warning", "ANN0180", "file/format", "ALL", 
                  f"[Auto-cleanup] Surrounding spaces or double-quotes were automatically removed. ({ann0180_count} items)", 
                  "annotation", is_cleanup=True)
    if ann0170_count > 0:
        _add_warn("warning", "ANN0170", "qualifier", "ALL", 
                  f"[Auto-cleanup] Consecutive spaces will be automatically reduced to a single space. ({ann0170_count} items)", 
                  "annotation", is_cleanup=True)
    if ann0185_count > 0:
        _add_warn("FATAL", "ANN0185", "qualifier", "ALL", 
                  'Double quotes (") are not allowed.', 
                  "annotation")

    # =========================================================
    # 3. FASTAファイルのCRLFチェックとインメモリ読み込み
    # =========================================================
    fasta_crlf_detected = False
    
    with open(fasta_path, 'r', encoding='utf-8', errors='replace') as fin:
        fasta_content = fin.read()
        if '\r\n' in fasta_content:
            fasta_crlf_detected = True

    if fasta_crlf_detected:
        _add_warn("warning", "ANN0035", "file/format", "ALL", 
                  "[Auto-cleanup] Line endings will be automatically converted to LF.", 
                  "sequence", is_cleanup=True, file_name=fasta_path.name, full_path=fasta_path_str)

    if ann_crlf_detected:
        _add_warn("warning", "ANN0035", "file/format", "ALL", 
                  "[Auto-cleanup] Line endings will be automatically converted to LF.", 
                  "annotation", is_cleanup=True)

    return cleaned_ann_lines, fasta_content, warnings