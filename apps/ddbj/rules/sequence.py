import json
from pathlib import Path
from common.rules.base import BaseRule

class FASTA_FORMAT_VALIDATOR(BaseRule):
    rule_id = "FASTA_FORMAT_MASTER"
    target = "file"
    description = "Check FASTA sequence format"
    requires_rdb = False
    is_file_level = True

    def validate_file(self, records, context, ann_path=None, seq_path=None, fasta_content=None):
        results = []
        if not seq_path: return results

        if fasta_content is not None:
            lines = fasta_content.splitlines()
        else:
            return results            

        # ---------------------------------------------------
        # SEQ0080: 最初の非空行が '>' で始まっているか
        # ---------------------------------------------------
        for line in lines:
            stripped = line.strip()
            if not stripped: continue
            if not stripped.startswith('>'):
                msg = "Missing FASTA definition line (>Entry name)."
                res = self.format_result(entry_id="ALL", message=msg, level="error", feature_type="sequence")
                # alternate_id = "JP0013"
                res["rule"], res["target"] = "SEQ0080", "sequence"
                results.append(res)
            break

        # ---------------------------------------------------
        # SEQ0100: 各エントリが '//' で終わっているか (WARNING)
        # ---------------------------------------------------
        current_entry = None
        has_terminator = False
        
        for line in lines:
            stripped = line.strip()
            if not stripped: continue

            if stripped.startswith('>'):
                if current_entry is not None and not has_terminator:
                    msg = "[Auto-cleanup] Missing sequence terminator (\"//\") was automatically appended."
                    res = self.format_result(entry_id=current_entry, message=msg, level="warning", feature_type="sequence")
                    # alternate_id = "JP0015"
                    res["rule"], res["target"] = "SEQ0100", "sequence"
                    res["autofix"] = True
                    res["is_cleanup"] = True
                    results.append(res)
                
                current_entry = stripped[1:].split()[0]
                has_terminator = False
            elif stripped == '//':
                has_terminator = True
            else:
                has_terminator = False
                
        if current_entry is not None and not has_terminator:
            msg = "[Auto-cleanup] Missing sequence terminator (\"//\") was automatically appended."
            res = self.format_result(entry_id=current_entry, message=msg, level="warning", feature_type="sequence")
            # alternate_id = "JP0015"
            res["rule"], res["target"] = "SEQ0100", "sequence"
            res["autofix"] = True
            res["is_cleanup"] = True
            results.append(res)

        return results
        
class SEQ0090(BaseRule):
    rule_id = "SEQ0090"
    alternate_id = "JP0014"
    target = "sequence"
    description = "Check for invalid nucleotide code in sequence"
    requires_rdb = False
    is_file_level = False

    def validate(self, record, context):
        results = []
        if record.id == "COMMON":
            return results

        seq_str = str(record.seq)
        
        cv_terms = context.cv_terms or {}
        nucleic_acids = cv_terms.get("nucleic_acids", [])
        # 小文字のリストに加えて、大文字に変換したリストも結合してSetにする
        allowed_chars = set(nucleic_acids + [b.upper() for b in nucleic_acids])

        # 集合(set)の差分を使った事前チェック
        invalid_chars = set(seq_str) - allowed_chars
        
        if invalid_chars:
            # 不正な文字が含まれている場合のみ、最初に出現する位置を特定する
            for i, char in enumerate(seq_str):
                if char not in allowed_chars:
                    msg = f"Invalid nucleotide code '{char}' at {i+1} position."
                    # 配列レベルのエラーなので format_result でスッキリ出力
                    results.append(self.format_result(
                        entry_id=record.id, 
                        message=msg, 
                        level="error", 
                        feature_type="sequence"
                    ))
                    break 

        return results
        
class SEQ5010(BaseRule):
    rule_id = "SEQ5010"
    alternate_id = "SVP0022, SEQ0001"
    target = "sequence"
    description = "More than 50% ambiguous bases ('N')."
    requires_rdb = False

    def validate(self, record, context):
        results = []
        seq_str = str(record.seq)
        seq_len = len(seq_str)
        
        if seq_len > 0:
            n_count = seq_str.count('n') + seq_str.count('N')
            n_ratio = n_count / seq_len
            
            if n_ratio > 0.5:
                results.append(self.format_result(
                    entry_id=record.id, message=self.description, level="warning",
                    feature_type="sequence"
                ))
                
        return results

class SEQ5020(BaseRule):
    rule_id = "SEQ5020"
    alternate_id = "SVP0070, SVP0071"
    target = "sequence"
    description = "Sequence begins and/or ends with 'N'. Terminal 'N's must be removed unless exempted."
    requires_rdb = False
    is_file_level = True

    def validate_file(self, records, context, ann_path=None, seq_path=None):
        results = []

        # 1. COMMON エントリから TOPOLOGY circular を取得
        common_circular = False
        common_rec = records.get("COMMON")
        if common_rec:
            for feat in self.get_features(common_rec, "TOPOLOGY"):
                if "circular" in feat.qualifiers:
                    common_circular = True
                    break

        # 2. 各エントリのチェック
        for entry_id, record in records.items():
            if entry_id == "COMMON":
                continue

            seq_str = str(record.seq).lower()
            starts_with_n = seq_str.startswith("n")
            ends_with_n = seq_str.endswith("n")

            if not (starts_with_n or ends_with_n):
                continue

            # まずCOMMONでcircularが指定されていれば除外
            is_exempt = common_circular
            
            # まだ除外判定されていなければ、エントリ固有のフィーチャーを確認
            if not is_exempt:
                # 個別エントリに TOPOLOGY circular がある場合
                for feat in self.get_features(record, "TOPOLOGY"):
                    if "circular" in feat.qualifiers:
                        is_exempt = True
                        break
                        
            if not is_exempt:
                # centromere, telomere の確認
                if self.get_features(record, "centromere") or self.get_features(record, "telomere"):
                    is_exempt = True
                    
            if not is_exempt:
                # assembly_gap の gap_type 確認
                for feat in self.get_features(record, "assembly_gap"):
                    gap_types = feat.qualifiers.get("gap_type", [])
                    if any(gt.strip().lower() in ["telomere", "centromere", "heterochromatin", "contamination"] for gt in gap_types):
                        is_exempt = True
                        break

            if not is_exempt:
                # 状態に応じて begins / ends / begins and ends を動的に決定
                if starts_with_n and ends_with_n:
                    state = "begins and ends"
                elif starts_with_n:
                    state = "begins"
                else:
                    state = "ends"

                msg = (f"Sequence {state} with 'N'. "
                       "Please remove terminal 'N's unless the molecule is circular, "
                       "the region is annotated as telomere/centromere/heterochromatin, or represents a contamination gap.")

                results.append(self.format_result(
                    entry_id=record.id, 
                    message=msg, 
                    level="warning",
                    feature_type="sequence"
                ))

        return results
                        
class SEQ5040(BaseRule):
    rule_id = "SEQ5040"
    alternate_id = "SVP0130, SEQ0004"
    target = "sequence"
    description = "Minimal size is 100 nucleotides unless there is a biological reason to accept smaller like complete tRNA or microRNA or the sample is from a patent or an ancient DNA/historical specimen."
    requires_rdb = False
    is_file_level = False

    def validate(self, record, context):
        results = []
        
        if record.id == "COMMON":
            return results
            
        seq_len = len(record.seq)
        
        # 配列長が0の場合、FASTAに実体が存在しない（ANNと名前が不一致等）ためスキップ
        if seq_len == 0:
            return results
            
        if seq_len < 100:
            msg = f"{self.description} (Length: {seq_len} bases)"
            res = self.format_result(
                entry_id=record.id, 
                message=msg, 
                level="warning",  
                feature_type="sequence"
            )
            res["rule"] = self.rule_id
            res["target"] = self.target
            results.append(res)
            
        return results        
        
class SEQ5050(BaseRule):
    rule_id = "SEQ5050"
    alternate_id = "SEQ0005"
    target = "sequence"
    description = "Sequence longer than 1Gbases."
    requires_rdb = False
    is_file_level = False

    def validate(self, record, context):
        results = []
        
        if record.id == "COMMON":
            return results
            
        # 1Gbases (1,000,000,000 bases) を超える場合にエラー
        if len(record.seq) > 1_000_000_000:
            msg = f"{self.description} (Length: {len(record.seq):,} bases)"
            res = self.format_result(
                entry_id=record.id,
                message=msg,
                level="error",
                feature_type="sequence"
            )
            res["rule"] = self.rule_id
            res["target"] = self.target
            results.append(res)
            
        return results
        
