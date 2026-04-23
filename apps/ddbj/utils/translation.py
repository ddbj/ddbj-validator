import re
from Bio.Data import CodonTable
from Bio.Seq import Seq
from Bio.SeqFeature import BeforePosition, AfterPosition, FeatureLocation, ExactPosition

def get_cds_translation_params(feature, default_table_id):
    """
    CDSフィーチャーの transl_table と codon_start を安全に取得する共通関数
    """
    table_id = default_table_id
    if "transl_table" in feature.qualifiers:
        try:
            table_id = int(feature.qualifiers["transl_table"][0])
        except ValueError:
            pass
    if table_id == 0:
        table_id = 1
        
    codon_start = 1
    if "codon_start" in feature.qualifiers:
        try:
            codon_start = int(feature.qualifiers["codon_start"][0])
        except ValueError:
            pass
    if codon_start not in [1, 2, 3]:
        codon_start = 1
        
    return table_id, codon_start

def get_insdc_translation(feature, record, table_id, codon_start, cv_terms=None):
    """
    INSDC仕様に準拠した翻訳アミノ酸配列を生成する（端数処理、M強制置換、transl_except対応）
    """
    try:
        nuc_seq = feature.extract(record.seq)
    except Exception:
        return None

    cds_seq = nuc_seq[codon_start - 1:]
    main_len = len(cds_seq) - (len(cds_seq) % 3)
    main_seq = cds_seq[:main_len]
    remainder_seq = cds_seq[main_len:]

    aa_seq = str(main_seq.translate(table=table_id)) if main_len > 0 else ""
    loc = feature.location
    if not loc:
        return None

    first_part = loc.parts[0]
    last_part = loc.parts[-1]

    if loc.strand == -1:
        is_5_complete = not isinstance(first_part.end, AfterPosition)
        is_3_complete = not isinstance(last_part.start, BeforePosition)
    else:
        is_5_complete = not isinstance(first_part.start, BeforePosition)
        is_3_complete = not isinstance(last_part.end, AfterPosition)

    # 3' が不完全な場合の端数塩基のパディング処理
    if not is_3_complete and len(remainder_seq) > 0:
        padded_seq = str(remainder_seq).ljust(3, 'N')
        try:
            extra_aa = str(Seq(padded_seq).translate(table=table_id))
            if extra_aa != "X":
                aa_seq += extra_aa
        except Exception:
            pass

    # transl_except の処理
    if "transl_except" in feature.qualifiers:
        amino_acids_dict = cv_terms.get("amino_acids", {}) if cv_terms else {}
        aa_code_map = {k.lower(): v.get("code", "X") for k, v in amino_acids_dict.items()}
        
        aa_list = list(aa_seq)
        for te in feature.qualifiers["transl_except"]:
            match = re.search(r'pos:.*?(\d+)\.\.(\d+).*?aa:([a-zA-Z]{3,4})', te, re.IGNORECASE)
            if match:
                start_pos = int(match.group(1))
                end_pos = int(match.group(2))
                aa_code = match.group(3)
                
                aa_1letter = aa_code_map.get(aa_code.lower())
                
                if not aa_1letter:
                    if aa_code.lower() == "sec": aa_1letter = "U"
                    elif aa_code.lower() == "pyl": aa_1letter = "O"
                    elif aa_code.lower() == "ter": aa_1letter = "*"
                    else:
                        from Bio.Data.IUPACData import protein_letters_3to1
                        aa_1letter = protein_letters_3to1.get(aa_code.capitalize())
                
                if aa_1letter:
                    try:
                        te_loc = FeatureLocation(ExactPosition(start_pos-1), ExactPosition(end_pos), strand=loc.strand)
                        start_in_cds = 0
                        current_len = 0
                        for part in loc.parts:
                            p_start = int(part.start)
                            p_end = int(part.end)
                            
                            if (start_pos-1 >= p_start and start_pos-1 < p_end) or (end_pos > p_start and end_pos <= p_end):
                                if loc.strand == -1:
                                    offset = p_end - end_pos
                                else:
                                    offset = (start_pos-1) - p_start
                                start_in_cds = current_len + offset
                                break
                            current_len += len(part)
                        
                        aa_index = (start_in_cds - (codon_start - 1)) // 3
                        
                        if 0 <= aa_index < len(aa_list):
                            aa_list[aa_index] = aa_1letter
                    except Exception:
                        pass
        aa_seq = "".join(aa_list)

    # 開始コドンの 'M' 強制変換ロジック
    if is_5_complete and codon_start == 1 and len(cds_seq) >= 3:
        first_codon = str(cds_seq[:3]).upper()
        try:
            start_codons = CodonTable.unambiguous_dna_by_id[table_id].start_codons
            if first_codon in start_codons:
                aa_seq = "M" + aa_seq[1:]
        except KeyError:
            pass

    if aa_seq.endswith("*"):
        aa_seq = aa_seq[:-1]

    return aa_seq