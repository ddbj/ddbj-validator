import sys
from pathlib import Path
from collections import defaultdict
from apps.ddbj.preprocessor import ANN_EXTENSIONS, FASTA_EXTENSIONS

def find_file_pairs(directory_path):
    dir_path = Path(directory_path)
    if not dir_path.is_dir():
        print(f"[FATAL ERROR] Directory not found: {directory_path}", file=sys.stderr)
        sys.exit(1)

    ann_files = defaultdict(list)
    fasta_files = defaultdict(list)
    errors = []

    for file_path in dir_path.iterdir():
        if not file_path.is_file():
            continue
            
        file_name = file_path.name
        
        for ext in ANN_EXTENSIONS:
            if file_name.endswith(ext):
                base_name = file_name[:-len(ext)]
                ann_files[base_name].append(str(file_path))
                break
        else:
            # ANN拡張子にマッチしなかった場合のみ FASTA拡張子をチェック
            for ext in FASTA_EXTENSIONS:
                if file_name.endswith(ext):
                    base_name = file_name[:-len(ext)]
                    fasta_files[base_name].append(str(file_path))
                    break

    # ---------------------------------------------------
    # ANN0010: ファイルが全く見つからない場合のチェック
    # ---------------------------------------------------
    if not ann_files and not fasta_files:
        errors.append({
            "level": "FATAL", 
            "rule": "ANN0010", 
            "target": "file", 
            "entry": "ALL",
            "message": "No annotation or sequence files found.",
            "file": "ALL", 
            "category": "file_manager"
        })
        return [], errors

    pairs = []
    # ANN と FASTA の両方で見つかったすべてのベースネームを統合してチェック
    all_basenames = set(ann_files.keys()).union(fasta_files.keys())
    
    for base_name in all_basenames:
        ann_list = ann_files.get(base_name, [])
        fasta_list = fasta_files.get(base_name, [])
        
        ann_count = len(ann_list)
        seq_count = len(fasta_list)
        
        # ---------------------------------------------------
        # ANN0020: ペアの不整合チェック
        # 1対1でない場合（欠損・複数存在）は全てこのエラーにする
        # ---------------------------------------------------
        if ann_count != 1 or seq_count != 1:
            errors.append({
                "level": "FATAL", 
                "rule": "ANN0020", 
                "target": "file", 
                "entry": "ALL",
                "message": f"Invalid file pair for '{base_name}': {ann_count} annotation file(s) and {seq_count} sequence file(s).",
                "file": f"{base_name}.*", 
                "category": "file_manager"
            })
            continue 
            
        # 正常な場合（ANNとFASTAが1つずつ揃っている場合）のみペアとして登録
        pairs.append((ann_list[0], fasta_list[0]))
                        
    return pairs, errors

def get_short_path(path_str):
    """パスの末尾3階層分を返す（レポート表示用）"""
    p = Path(path_str)
    return "/".join(p.parts[-3:]) if len(p.parts) >= 3 else str(p)