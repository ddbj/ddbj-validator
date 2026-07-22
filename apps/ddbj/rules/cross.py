import re
import logging
from common.rules.base import BaseRule
from Bio.SeqFeature import CompoundLocation, BeforePosition, AfterPosition
from Bio.Data import CodonTable
from Bio.Seq import Seq
from apps.ddbj.utils.location import get_introns_from_join, get_feature_positions
from apps.ddbj.db_metadata import get_expected_transl_table
from apps.ddbj.parser import _parse_location_string
from intervaltree import IntervalTree
from apps.ddbj.utils.translation import get_cds_translation_params, get_insdc_translation

logger = logging.getLogger(__name__)

# 翻訳ヘルパーは apps/ddbj/utils/translation.py に一本化（get_cds_translation_params / get_insdc_translation）。
# 旧 get_conceptual_translation は未使用（transl_except 非対応の簡易版）だったため削除した。

# 機器モデル名 → シーケンスプラットフォームの判定テーブル（_determine_platform 用）。
# 完全一致を先に評価し、その後で正規表現を「リストの順序どおり」に評価する（順序依存のため変更不可）。
_PLATFORM_EXACT_MAP = {
    "UG 100": "ULTIMA",
    "GENIUS": "GENAPSYS", "Genapsys Sequencer": "GENAPSYS", "GS111": "GENAPSYS",
    "GenoCare 1600": "GENEMIND", "GenoLab M": "GENEMIND", "FASTASeq 300": "GENEMIND",
    "SURFSeq 5000": "GENEMIND", "SURFSeq Q": "GENEMIND",
    "Tapestri": "TAPESTRI",
    "Sentosa SQ301": "VELA_DIAGNOSTICS",
    "Saluseq Nimbo": "SALUS", "Salus Pro": "SALUS", "Salus EVO": "SALUS",
    "G-seq500": "GENEUS_TECH",
    "G4": "SINGULAR_GENOMICS",
}
# (正規表現パターン, フラグ, プラットフォーム) を上から順に評価する。
_PLATFORM_REGEX_RULES = [
    (r'454', re.IGNORECASE, "LS454"),
    (r'illumina|nextseq|hiseq', re.IGNORECASE, "ILLUMINA"),
    (r'solid', re.IGNORECASE, "ABI_SOLID"),
    (r'pacbio', re.IGNORECASE, "PACBIO_SMRT"),
    (r'onso|revio', re.IGNORECASE, "PACBIO_SMRT"),
    (r'bgiseq|mgiseq|cycloneseq', re.IGNORECASE, "BGISEQ"),
    (r'dnbseq', re.IGNORECASE, "DNBSEQ"),
    # 「Nanopore …」表記は model の綴りに依らず OXFORD_NANOPORE と判定する。
    # （後段の case-sensitive な r'ION' は MinION/GridION/PromethION のみ拾い、
    #  "MinINO" のような綴り違いを取りこぼすため、語そのものを補完する。）
    (r'nanopore', re.IGNORECASE, "OXFORD_NANOPORE"),
    (r'AB 5500', 0, "ABI_SOLID"),
    (r'Ion', 0, "ION_TORRENT"),
    (r'Sequel', 0, "PACBIO_SMRT"),
    (r'ION', 0, "OXFORD_NANOPORE"),
    (r'AB 3', 0, "CAPILLARY"),
    (r'Helicos HeliScope', 0, "HELICOS"),
    (r'Complete', 0, "COMPLETE_GENOMICS"),
    (r'Element', 0, "ELEMENT"),
]

class AXS2080(BaseRule):
    rule_id = "AXS2080"
    alternate_id = "JP0039"
    target = "source"
    description = "The source feature location exceeds the sequence length."
    requires_rdb = False
    is_file_level = False

    def validate(self, record, context):
        results = []
        seq_len = len(record.seq)
        if seq_len == 0 or record.id == "COMMON": 
            return results
        
        for feature in self.get_features(record, "source"):
            if feature.location:
                # リモートエントリを除外したローカルパーツのみを抽出
                local_parts = [p for p in getattr(feature.location, "parts", [feature.location]) if getattr(p, "ref", None) is None]
                if not local_parts:
                    continue
                
                # ローカルパーツの中での最大値を計算
                end_val = max(int(p.end) for p in local_parts)
                if end_val > seq_len:
                    msg = f"{self.description} (Sequence length: {seq_len}, Local location end: {end_val})"
                    results.append(self.feature_result(record, feature, msg, level="error"))
                    
        return results


class AXS2090(BaseRule):
    rule_id = "AXS2090"
    alternate_id = "JP1034"
    target = "location"
    description = "Location is out of the sequence range."
    requires_rdb = False
    is_file_level = False

    def validate(self, record, context):
        results = []
        seq_len = len(record.seq)
        if seq_len == 0 or record.id == "COMMON": 
            return results
        
        for feature in self.get_features(record):
            if feature.type == "source": 
                continue
                
            if feature.location:
                # リモートエントリを除外したローカルパーツのみを抽出
                local_parts = [p for p in getattr(feature.location, "parts", [feature.location]) if getattr(p, "ref", None) is None]
                if not local_parts:
                    continue
                
                # ローカルパーツの中での最小startと最大endを計算
                start_val = min(int(p.start) for p in local_parts)
                end_val = max(int(p.end) for p in local_parts)
                
                if start_val < 0 or end_val > seq_len:
                    msg = f"{self.description} (Sequence length: {seq_len}, Local location range: {start_val+1}..{end_val})"
                    results.append(self.feature_result(record, feature, msg, level="error"))
                    
        return results
        

class AXS5090(BaseRule):
    rule_id = "AXS5090"
    alternate_id = "JP0045"
    target = "sequence"
    description = "Sequences annotated as gap or assembly_gap must consist entirely of 'N'."
    requires_rdb = False
    is_file_level = False

    def validate(self, record, context):
        results = []
        if record.id == "COMMON":
            return results

        for f_type in ("gap", "assembly_gap"):
            for feature in self.get_features(record, f_type):
                if not feature.location:
                    continue
                try:
                    feat_seq = str(feature.extract(record.seq)).upper()
                    if feat_seq and len(feat_seq.replace('N', '')) > 0:
                        results.append(self.feature_result(record, feature, self.description, level="error"))
                except Exception as e:
                    logger.debug(f"Failed to extract gap/assembly_gap sequence ({f_type}): {e}", exc_info=True)
                    
        return results
        
class AXS5100(BaseRule):
    rule_id = "AXS5100"
    alternate_id = "JP0112"
    target = "sequence"
    description = "Consecutive 'N's is longer than the corresponding gap feature."
    requires_rdb = False
    is_file_level = False

    def validate(self, record, context):
        results = []
        if record.id == "COMMON":
            return results

        seq_str = str(record.seq).upper()
        seq_len = len(seq_str)
        if seq_len == 0:
            return results

        for f_type in ("gap", "assembly_gap"):
            for feature in self.get_features(record, f_type):
                if not feature.location:
                    continue
                
                try:
                    parts = getattr(feature.location, "parts", [feature.location])
                    is_extended = False
                    
                    for part in parts:
                        start = int(part.start)
                        end = int(part.end)
                        
                        if start > 0 and seq_str[start - 1] == 'N':
                            is_extended = True
                        if end < seq_len and seq_str[end] == 'N':
                            is_extended = True
                            
                    if is_extended:
                        results.append(self.feature_result(record, feature, self.description, level="warning"))
                except Exception as e:
                    logger.debug(f"Failed to check consecutive Ns around gap feature ({f_type}): {e}", exc_info=True)
                    
        return results                

class AXS5290(BaseRule):
    rule_id = "AXS5290"
    alternate_id = "JP0046"
    target = "gap"
    description = "Consecutive 'N's must be annotated with a gap or assembly_gap feature."
    requires_rdb = False
    is_file_level = False

    def validate(self, record, context):
        results = []
        if record.id == "COMMON":
            return results

        seq_str = str(record.seq).upper()
        if not seq_str:
            return results

        n_stretches = [(m.start(), m.end()) for m in re.finditer(r'N{100,}', seq_str)]
        if not n_stretches:
            return results

        gap_intervals = []
        for f_type in ("gap", "assembly_gap"):
            for feature in self.get_features(record, f_type):
                if feature.location:
                    parts = getattr(feature.location, "parts", [feature.location])
                    for part in parts:
                        gap_intervals.append((int(part.start), int(part.end)))

        for n_start, n_end in n_stretches:
            uncovered_start = n_start
            overlapping_gaps = sorted([g for g in gap_intervals if g[1] > n_start and g[0] < n_end])
            
            for g_start, g_end in overlapping_gaps:
                if g_start <= uncovered_start:
                    uncovered_start = max(uncovered_start, g_end)
                    
            if uncovered_start < n_end:
                msg = f"{self.description} (Found >= 100 'N's at {n_start + 1}..{n_end})"
                results.append(self.format_result(
                    entry_id=record.id,
                    message=msg,
                    level="warning",
                    feature_type="sequence",
                    location=f"{n_start + 1}..{n_end}"
                ))

        return results
        
class AXS5210(BaseRule):
    rule_id = "AXS5210"
    alternate_id = "SVP0020, AXS0001"
    target = "gap"
    description = "Gap content exceeds 50% of sequence."
    requires_rdb = False

    def validate(self, record, context):
        results = []
        seq_len = len(record.seq)
        
        if seq_len == 0:
            return results
            
        total_gap_length = 0
        for feature in self.get_features(record, "assembly_gap"):
            if feature.location:
                total_gap_length += len(feature.location)
                
        gap_ratio = total_gap_length / seq_len
        if gap_ratio > 0.5:
            results.append(self.format_result(
                entry_id=record.id, message=self.description, level="warning",
                feature_type="sequence"
            ))
            
        return results
        
class AXS6810(BaseRule):
    rule_id = "AXS6810"
    alternate_id = "SVP0510, AXS0002"
    target = "CDS, intron"
    description = "Non-canonical splice sites: GT-AG/GC-AG rule violation."
    requires_rdb = False

    def validate(self, record, context):
        results = []

        for feature in self.get_features(record, "intron"):
            if not feature.location:
                continue

            seq = feature.location.extract(record.seq).upper()
            seq_str = str(seq)
            if len(seq_str) >= 4:
                # canonical は GT-AG に加え、2 番目に多い GC-AG も許容（warning 多発防止）
                if not (seq_str.startswith(("GT", "GC")) and seq_str.endswith("AG")):
                    loc_str = getattr(feature, 'original_location', str(feature.location))
                    msg = f"{self.description} (Found: {seq_str[:2]}-{seq_str[-2:]} at {loc_str})"
                    results.append(self.feature_result(record, feature, msg, level="warning"))
                        
        for feature in self.get_features(record, "CDS"):
            if not feature.location:
                continue
                
            strand = feature.location.strand
            loc_str = getattr(feature, 'original_location', str(feature.location))
            
            for intron in get_introns_from_join(feature):
                intron_seq = record.seq[intron["start"]:intron["end"]]
                if strand == -1:
                    intron_seq = intron_seq.reverse_complement()
                
                intron_str = str(intron_seq).upper()
                if len(intron_str) >= 4:
                    # canonical は GT-AG に加え GC-AG も許容（warning 多発防止）
                    if not (intron_str.startswith(("GT", "GC")) and intron_str.endswith("AG")):
                        msg = f"{self.description} (Found: {intron_str[:2]}-{intron_str[-2:]} in CDS at {loc_str})"
                        results.append(self.feature_result(record, feature, msg, level="warning"))
                        
        return results
        
class AXS6820(BaseRule):
    rule_id = "AXS6820"
    alternate_id = "AXS0003"
    target = "feature"
    description = "Introns (3, 6 or 9 bp) consist entirely of stop codons."
    requires_rdb = True

    def validate(self, record, context):
        results = []
        
        table_id = get_expected_transl_table(record, context.tax_data)
        
        if table_id == 0:
            return results
            
        try:
            stop_codons = set(CodonTable.unambiguous_dna_by_id[table_id].stop_codons)
        except KeyError:
            stop_codons = {'TAA', 'TAG', 'TGA'}

        def check_intron_seq(seq_str, feature):
            if len(seq_str) % 3 != 0:
                return
            codons = [seq_str[i:i+3] for i in range(0, len(seq_str), 3)]
            if all(codon in stop_codons for codon in codons):
                msg = f"{self.description} (Found: {seq_str})"
                results.append(self.feature_result(record, feature, msg, level="warning"))

        for feature in self.get_features(record, "intron"):
            if not feature.location:
                continue

            length = len(feature.location)
            if length in [3, 6, 9]:
                seq_str = str(feature.location.extract(record.seq)).upper()
                check_intron_seq(seq_str, feature)
                    
        for feature in self.get_features(record, "CDS"):
            if not feature.location:
                continue
                
            strand = feature.location.strand
            for intron in get_introns_from_join(feature):
                if intron["length"] in [3, 6, 9]:
                    intron_seq = record.seq[intron["start"]:intron["end"]]
                    if strand == -1:
                        intron_seq = intron_seq.reverse_complement()
                        
                    seq_str = str(intron_seq).upper()
                    check_intron_seq(seq_str, feature)
                        
        return results
        
class DRA_CROSSCHECK_VALIDATOR(BaseRule):
    rule_id = "DRA_CROSSCHECK_MASTER"
    target = "DBLINK"
    description = "Inconsistent SRA Experiment metadata"
    requires_rdb = True
    requires_auth = True
    is_file_level = True
    
    # このマスタークラスを構成するルールIDのリスト (テスト判定用)
    sub_rules = ["ANN0500", "ANN0510", "ANN0520", "ANN0530", "ANN0540", "ANN0550"]
    
    def validate_file(self, records, context, ann_path=None, seq_path=None):
        results = []
        rules = context.dra_crosscheck_dict.get("external_db", [])
        dra_lib_meta = context.dra_lib_meta or {}
        
        if not rules or not dra_lib_meta:
            return results

        datatypes = context.active_datatypes
        if not datatypes:
            return results

        matched_rules = []
        for rule in rules:
            rule_dts = [d.upper() for d in rule.get("datatypes", [])]
            if any(dt in rule_dts for dt in datatypes):
                matched_rules.append(rule)

        if not matched_rules:
            return results

        for entry_id, record in records.items():
            for feature in self.get_features(record, "DBLINK"):
                drrs = [d.strip().upper() for d in feature.qualifiers.get("sequence read archive", []) if d.strip().upper().startswith("DRR")]
                
                if not drrs:
                    continue
                    
                for drr_upper in drrs:
                    if drr_upper in dra_lib_meta:
                        meta = dra_lib_meta[drr_upper]
                        source = meta.get("source", "")
                        selection = meta.get("selection", "")
                        strategy = meta.get("strategy", "")
                        drx = meta.get("drx", "UNKNOWN")

                        for rule in matched_rules:
                            group = rule.get("group_name", "")
                            
                            if group == "TRANSCRIPTOMIC":
                                id_source, id_strat, id_sel = "ANN0500", "ANN0520", "ANN0540"
                                desc_prefix = "TSA"
                            else:
                                id_source, id_strat, id_sel = "ANN0510", "ANN0530", "ANN0550"
                                desc_prefix = "Genomic data types WGS/TLS/HTG"

                            valid_sources = rule.get("valid_library_source", [])
                            inv_selections = rule.get("invalid_library_selection", [])
                            inv_strategies = rule.get("invalid_library_strategy", [])

                            if valid_sources and source and source not in valid_sources:
                                msg = f"{desc_prefix}: Inconsistent SRA Experiment LIBRARY_SOURCE (Found: '{source}' in {drx} for {drr_upper})"
                                res = self.feature_result(record, feature, msg, level="warning", qualifier="sequence read archive", rule=id_source)
                                results.append(res)

                            if inv_strategies and strategy in inv_strategies:
                                msg = f"{desc_prefix}: Inconsistent SRA Experiment LIBRARY_STRATEGY (Found: '{strategy}' in {drx} for {drr_upper})"
                                res = self.feature_result(record, feature, msg, level="warning", qualifier="sequence read archive", rule=id_strat)
                                results.append(res)

                            if inv_selections and selection in inv_selections:
                                msg = f"{desc_prefix}: Inconsistent SRA Experiment LIBRARY_SELECTION (Found: '{selection}' in {drx} for {drr_upper})"
                                res = self.feature_result(record, feature, msg, level="warning", qualifier="sequence read archive", rule=id_sel)
                                results.append(res)

        return results
        
class ANN0560(BaseRule):
    rule_id = "ANN0560"
    target = "DBLINK"
    description = "Inconsistent Sequencing Technology and SRA Experiment PLATFORM."
    requires_rdb = True
    requires_auth = True
    is_file_level = True

    def validate_file(self, records, context, ann_path=None, seq_path=None):
        results = []
        dra_lib_meta = context.dra_lib_meta or {}
        if not dra_lib_meta:
            return results

        seq_techs_raw = []
        ann_platforms = set()
        
        for entry_id, record in records.items():
            for feature in self.get_features(record, "ST_COMMENT"):
                for q_name, q_values in feature.qualifiers.items():
                    if q_name.lower() == "sequencing technology":
                        for val in q_values:
                            for tech in val.split(";"):
                                tech_clean = tech.strip()
                                if tech_clean:
                                    seq_techs_raw.append(tech_clean)
                                    plat = self._determine_platform(tech_clean)
                                    if plat != "UNKNOWN":
                                        ann_platforms.add(plat)

        if not ann_platforms:
            return results

        tech_str = "; ".join(seq_techs_raw)

        for entry_id, record in records.items():
            for feature in self.get_features(record, "DBLINK"):
                drrs = [d.strip().upper() for d in feature.qualifiers.get("sequence read archive", []) if d.strip().upper().startswith("DRR")]

                if not drrs:
                    continue

                # この DBLINK が参照する SRA experiment の platform 集合と instrument 文字列
                sra_platforms = set()
                sra_instruments = []
                for drr_upper in drrs:
                    if drr_upper in dra_lib_meta:
                        instrument = dra_lib_meta[drr_upper].get("instrument_model", "")
                        if instrument:
                            sra_instruments.append(instrument)
                            sp = self._determine_platform(instrument)
                            if sp != "UNKNOWN":
                                sra_platforms.add(sp)

                if not sra_instruments:
                    continue

                sra_str = "; ".join(sra_instruments)

                # forward: SRA experiment の platform が ann の Sequencing Technology に無い
                #   （experiment で使った技術が ann に申告漏れ）
                for sp in sorted(sra_platforms):
                    if sp not in ann_platforms:
                        msg = f"{self.description} (ST_COMMENT: '{tech_str}', SRA: '{sra_str}')"
                        results.append(self.feature_result(record, feature, msg, level="warning", qualifier="sequence read archive"))
                        break

                # reverse: ann の platform が SRA experiment に無い
                #   （対応する experiment が無い余計な technology を ann に記載）
                for sp in sorted(ann_platforms):
                    if sp not in sra_platforms:
                        msg = f"{self.description} (ST_COMMENT: '{tech_str}', SRA: '{sra_str}')"
                        results.append(self.feature_result(record, feature, msg, level="warning", qualifier="sequence read archive"))
                        break
        return results
        
    def _determine_platform(self, model: str) -> str:
        if not model:
            return "UNKNOWN"

        if model in _PLATFORM_EXACT_MAP:
            return _PLATFORM_EXACT_MAP[model]

        for pattern, flags, platform in _PLATFORM_REGEX_RULES:
            if re.search(pattern, model, flags):
                return platform

        return "UNKNOWN"
                
class CDS_TRANSLATION_VALIDATOR(BaseRule):
    rule_id = "CDS_TRANSLATION_MASTER"
    target = "CDS"
    description = "Validate translation of CDS features including start/stop/internal codons."
    requires_rdb = False
    is_file_level = False

    def validate(self, record, context):
        results = []
        if record.id == "COMMON":
            return results

        default_table_id = get_expected_transl_table(record, context.tax_data)

        for feature in self.get_features(record, "CDS"):
            if "pseudo" in feature.qualifiers or "pseudogene" in feature.qualifiers:
                continue

            # ヘルパー関数で table_id と codon_start を一括取得
            table_id, codon_start = get_cds_translation_params(feature, default_table_id)

            loc = feature.location
            if not loc:
                continue

            # parts の配列に依存せず、フィーチャー全体の最小(start)・最大(end)座標を使う
            if loc.strand == -1:
                is_5_complete = not isinstance(loc.end, AfterPosition)
                is_3_complete = not isinstance(loc.start, BeforePosition)
            else:
                is_5_complete = not isinstance(loc.start, BeforePosition)
                is_3_complete = not isinstance(loc.end, AfterPosition)

            try:
                # ここで str() に変換し、純粋な文字列として保持
                seq_str = str(feature.extract(record.seq))
            except Exception as e:
                logger.debug(f"Failed to extract feature sequence: {e}", exc_info=True)
                continue
                
            cds_seq = seq_str[codon_start - 1:]
            
            codons = []
            for i in range(0, len(cds_seq), 3):
                codon = cds_seq[i:i+3].upper()
                
                if len(codon) == 3:
                    codons.append(codon)
                else:
                    if not is_3_complete:
                        padded_codon = codon.ljust(3, 'N')
                        try:
                            # 翻訳は Seq オブジェクトが必要なので一時的に作成
                            aa = str(Seq(padded_codon).translate(table=table_id))
                            if aa != "X":
                                codons.append(padded_codon)
                        except Exception as e:
                            logger.debug(f"Failed to translate codon for stop-codon check: {e}", exc_info=True)
                                                        
            if not codons:
                continue

            try:
                codon_table = CodonTable.unambiguous_dna_by_id[table_id]
                start_codons = codon_table.start_codons
            except KeyError:
                continue

            location_str = getattr(feature, 'original_location', "")

            # -------------------------------------------------------------
            # CDS全体を「一括」で翻訳する (ループ内でのtranslate排除)
            # -------------------------------------------------------------
            valid_seq_str = "".join(codons)
            try:
                full_aa = str(Seq(valid_seq_str).translate(table=table_id))
            except Exception:
                full_aa = "X" * len(codons) # 万が一エラーになった場合のフォールバック

            # 開始コドンのチェック
            if is_5_complete and codon_start == 1:
                first_codon = codons[0]
                if first_codon not in start_codons:
                    msg = f'"{first_codon}" is not a valid start codon for the 5\' complete CDS. (Found: {first_codon} at {location_str})'
                    res = self.feature_result(record, feature, msg, level="error", rule="AXS6040", target="CDS")
                    results.append(res)

            # 終止コドンのチェック (一括翻訳の結果を再利用)
            if is_3_complete:
                last_codon = codons[-1]
                is_stop = (full_aa[-1] == "*") if full_aa else False

                if not is_stop:
                    # transl_except で aa:TERM が指定されている場合はエラーを回避
                    has_term_except = False
                    for te in feature.qualifiers.get("transl_except", []):
                        if re.search(r'aa:TERM\b', te, re.IGNORECASE):
                            has_term_except = True
                            break
                    
                    if not has_term_except:
                        msg = f'"{last_codon}" is not a valid stop codon for the 3\' complete CDS. (Found: {last_codon} at {location_str})'
                        res = self.feature_result(record, feature, msg, level="error", rule="AXS6050", target="CDS")
                        results.append(res)
                        
            has_transl_except = "transl_except" in feature.qualifiers
            
            # 内部コドンのチェック (一括翻訳した full_aa を zip で回すだけ)
            for i, (codon, aa) in enumerate(zip(codons, full_aa)):
                codon_pos = i + 1
                
                if aa == "X":
                    msg = f'Untranslatable codon "{codon}" detected in the sequence. These codons will be translated to \'X\' (unknown amino acids) after loading to the DDBJ database. (Found: {codon} at codon {codon_pos} in {location_str})'
                    res = self.feature_result(record, feature, msg, level="warning", rule="AXS6030", target="CDS")
                    results.append(res)
                    
                elif aa == "*":
                    if i < len(codons) - 1 and not has_transl_except:
                        msg = f'Internal stop codon within the CDS. (Found: {codon} at codon {codon_pos} in {location_str})'
                        res = self.feature_result(record, feature, msg, level="error", rule="AXS6060", target="CDS")
                        results.append(res)

        return results
                
TRANSL_EXCEPT_PATTERN = re.compile(r"^\(pos:(?P<pos>.+?),aa:(?P<aa>[a-zA-Z]+)\)$")

def find_sublist(parent, child):
    if not child: return -1
    try:
        first_idx = parent.index(child[0])
        for i, p in enumerate(child):
            if parent[first_idx + i] != p:
                return -1
        return first_idx
    except (ValueError, IndexError):
        return -1

class CDS_TRANSL_EXCEPT_VALIDATOR(BaseRule):
    rule_id = "CDS_TRANSL_EXCEPT_MASTER"
    target = "CDS"
    description = "Validate transl_except and codon_start in CDS features."
    requires_rdb = False
    is_file_level = False

    def validate(self, record, context):
        results = []
        if record.id == "COMMON":
            return results

        amino_acids_def = context.cv_terms.get("amino_acids", {}) if context.cv_terms else {}
        aa_lower_map = {k.lower(): k for k in amino_acids_def.keys()}

        default_table_id = get_expected_transl_table(record, context.tax_data)

        for feature in self.get_features(record, "CDS"):
            loc = feature.location
            if not loc:
                continue

            # 5' complete 判定はフィーチャー全体の座標（loc.end/loc.start）で行う。
            # minus 鎖の compound location は BioPython が parts を 5'→3' 順に並べるため、
            # parts[-1].end を見ると 3' 側 part の内部境界を掴んで誤判定する（多エクソン minus で顕在化）。
            # 同ファイル CDS_TRANSLATION_VALIDATOR と同方式に揃える（ANN6090 誤検出の修正）。
            if loc.strand == -1:
                is_5_complete = not isinstance(loc.end, AfterPosition)
            else:
                is_5_complete = not isinstance(loc.start, BeforePosition)

            codon_start = 1
            if "codon_start" in feature.qualifiers:
                cs_val = feature.qualifiers["codon_start"][0].strip()
                if cs_val not in ["1", "2", "3"]:
                    res = self.feature_result(record, feature, f'Invalid value "{cs_val}" for the codon_start qualifier.', level="error", qualifier="codon_start", rule="AXS6420", target="codon_start")
                    results.append(res)
                else:
                    codon_start = int(cs_val)

            if is_5_complete and codon_start != 1:
                res = self.feature_result(record, feature, 'The codon_start qualifier value must be "1" for the 5\' complete CDS.', level="error", qualifier="codon_start", rule="ANN6090", target="codon_start")
                results.append(res)

            transl_excepts = feature.qualifiers.get("transl_except", [])
            if not transl_excepts:
                continue

            table_id = default_table_id
            if "transl_table" in feature.qualifiers:
                try:
                    table_id = int(feature.qualifiers["transl_table"][0])
                except ValueError:
                    pass
            if table_id == 0: table_id = 1

            cds_positions = get_feature_positions(feature.location)
            used_positions = set()
            cds_seq_extracted = None

            for te_val in transl_excepts:
                m = TRANSL_EXCEPT_PATTERN.match(te_val.strip())
                if not m:
                    res = self.feature_result(record, feature, f'Invalid value "{te_val}" for the transl_except and codon_start qualifiers.', level="error", qualifier="transl_except", rule="AXS6420", target="transl_except")
                    results.append(res)
                    continue

                pos_str = m.group("pos")
                aa_str = m.group("aa")

                # アミノ酸略号を CV と照合する。完全一致なら OK。
                # 大文字小文字のみ異なる場合は誤記として error を出し、正しい case へ autofix で正す
                # （翻訳モジュールの case-insensitive 解釈と整合させるため）。
                # どちらにも一致しなければ無効としてエラー（autofix なし）。
                if aa_str in amino_acids_def:
                    aa_normalized = aa_str
                else:
                    correct_aa = aa_lower_map.get(aa_str.lower())
                    if correct_aa is None:
                        res = self.feature_result(record, feature, 'Invalid amino acid abbreviation code in the transl_except qualifier.', level="error", qualifier="transl_except", rule="AXS6410", target="transl_except")
                        results.append(res)
                        continue
                    new_val = te_val.strip().replace(f"aa:{aa_str}", f"aa:{correct_aa}", 1)
                    res = self.feature_result(record, feature, f"Invalid amino acid abbreviation code in the transl_except qualifier. Check character case (Expected: '{correct_aa}', Found: '{aa_str}').", level="error", qualifier="transl_except", rule="AXS6410", target="transl_except")
                    res["autofix"] = True
                    res["fix_target"] = "qualifier"
                    res["old_value"] = te_val.strip()
                    res["new_value"] = new_val
                    results.append(res)
                    aa_normalized = correct_aa
                
                try:
                    te_loc = _parse_location_string(pos_str, seq_length=len(record.seq))
                except Exception:
                    msg = f"Invalid base range in the transl_except qualifier. (Found: '{te_val.strip()}')"
                    res = self.feature_result(record, feature, msg, level="error", qualifier="transl_except", rule="AXS6440", target="transl_except")
                    results.append(res)
                    continue

                te_positions = get_feature_positions(te_loc)
                rel_start_idx = find_sublist(cds_positions, te_positions)
                
                if rel_start_idx == -1:
                    msg = f"Invalid base range in the transl_except qualifier. (Found: '{te_val.strip()}')"
                    res = self.feature_result(record, feature, msg, level="error", qualifier="transl_except", rule="AXS6440", target="transl_except")
                    results.append(res)
                    continue
                    
                te_pos_set = set(te_positions)
                if not te_pos_set.isdisjoint(used_positions):
                    res = self.feature_result(record, feature, 'Overlapping base ranges in multiple transl_except qualifiers.', level="error", qualifier="transl_except", rule="AXS6430", target="transl_except")
                    results.append(res)
                used_positions.update(te_pos_set)

                if (rel_start_idx - (codon_start - 1)) % 3 != 0:
                    res = self.feature_result(record, feature, 'The transl_except qualifier base range mismatches with the reading frame of the CDS feature.', level="error", qualifier="transl_except", rule="AXS6470", target="transl_except")
                    results.append(res)

                if cds_seq_extracted is None:
                    try:
                        cds_seq_extracted = feature.extract(record.seq)
                    except Exception:
                        cds_seq_extracted = Seq("")

                if len(te_positions) == 3 and len(cds_seq_extracted) > 0:
                    codon_seq = cds_seq_extracted[rel_start_idx : rel_start_idx + 3]
                    try:
                        actual_aa = str(codon_seq.translate(table=table_id))
                        target_aa_1 = amino_acids_def.get(aa_normalized, {}).get("code", "?")
                        
                        if actual_aa == target_aa_1:
                            res = self.feature_result(record, feature, 'Unnecessary transl_except: Specified amino acids are identical with the conceptual translation of the CDS feature.', level="error", qualifier="transl_except", rule="AXS6480", target="transl_except")
                            results.append(res)
                    except Exception as e:
                        logger.debug(f"Failed to check unnecessary transl_except: {e}", exc_info=True)

                codon_idx = (rel_start_idx - (codon_start - 1)) // 3
                num_codons = (len(cds_positions) - (codon_start - 1)) // 3

                if codon_idx == 0:
                    if aa_normalized != "Met":
                        res = self.feature_result(record, feature, 'Invalid start amino acid: [transl_except] at the 5\' end must be "Met".', level="warning", qualifier="transl_except", rule="AXS6490", target="transl_except")
                        results.append(res)

                if codon_idx == num_codons - 1:
                    if aa_normalized != "TERM":
                        res = self.feature_result(record, feature, 'Invalid stop amino acid: [transl_except] at the 3\' end must be "TERM".', level="error", qualifier="transl_except", rule="AXS6500", target="transl_except")
                        results.append(res)

                if codon_idx > 0 and codon_idx < num_codons - 1:
                    if aa_normalized == "TERM":
                        res = self.feature_result(record, feature, 'Unexpected internal stop: [transl_except] specifies "TERM" internally.', level="error", qualifier="transl_except", rule="AXS6510", target="transl_except")
                        results.append(res)

        return results      


class AXS6085(BaseRule):
    rule_id = "AXS6085"
    target = "CDS"
    description = "The length of the complete CDS is not a multiple of 3. Verify the location or add a 'ribosomal_slippage' or 'transl_except' qualifier if appropriate."
    requires_rdb = False
    is_file_level = False

    def validate(self, record, context):
        results = []
        if record.id == "COMMON":
            return results

        for feature in self.get_features(record, "CDS"):
            loc = feature.location
            if not loc:
                continue

            is_partial = False
            for part in loc.parts:
                if isinstance(part.start, BeforePosition) or isinstance(part.end, AfterPosition):
                    is_partial = True
                    break
            
            if is_partial:
                continue

            # exception, transl_except, ribosomal_slippage のいずれかがあれば適用除外
            if any(q in feature.qualifiers for q in ["transl_except", "ribosomal_slippage", "exception"]):
                continue

            # ヘルパー関数を利用して codon_start のみを抽出 (transl_tableは不要なので '_' で受ける)
            _, codon_start = get_cds_translation_params(feature, 1)

            translated_len = max(0, len(loc) - (codon_start - 1))

            if translated_len % 3 != 0:
                loc_str = getattr(feature, 'original_location', str(loc))
                
                msg = f"{self.description} (Length: {len(loc)} bp, codon_start: {codon_start}, Found at {loc_str})"
                results.append(self.feature_result(record, feature, msg, level="warning"))

        return results
        

class AXS6087(BaseRule):
    rule_id = "AXS6087"
    target = "CDS"
    description = "Unnecessary exception: The conceptual translation perfectly matches the annotated translation."
    requires_rdb = False
    is_file_level = False

    def validate(self, record, context):
        results = []
        if record.id == "COMMON":
            return results

        default_table_id = get_expected_transl_table(record, context.tax_data)

        for feature in self.get_features(record, "CDS"):
            if "exception" not in feature.qualifiers or "translation" not in feature.qualifiers:
                continue

            annotated_raw = feature.qualifiers["translation"][0]
            annotated_clean = re.sub(r'\s+', '', annotated_raw).upper()
            if annotated_clean.endswith("*"):
                annotated_clean = annotated_clean[:-1]
            
            table_id, codon_start = get_cds_translation_params(feature, default_table_id)
            conceptual_translation = get_insdc_translation(
                feature, record, table_id, codon_start, cv_terms=context.cv_terms
            )
            
            if conceptual_translation == annotated_clean:
                exception_val = feature.qualifiers["exception"][0].strip()
                msg = f"{self.description} (Found: '{exception_val}')"
                res = self.feature_result(record, feature, msg, level="error", qualifier="exception")
                results.append(res)

        return results