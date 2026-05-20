from apps.ddbj.rules.sequence import *
from apps.ddbj.rules.cross import *
from apps.ddbj.rules.annotation import *
from apps.ddbj.context import ValidationContext
from apps.ddbj.rules.definitions import ANN_DICT_VALIDATOR
from apps.ddbj.rules.entry_consistency import ENTRY_CONSISTENCY_VALIDATOR
from apps.ddbj.rules.division_datatype import *
from pathlib import Path
import inspect
from collections import defaultdict

class Validator:
    def __init__(self, context: ValidationContext):
        self.context = context
        self.active_rules = []
        self._register_rules()
        
    def _register_rules(self):
        ctx = self.context
        
        # 【フェーズ1 & 2】フォーマットチェックと静的辞書ルール
        self.active_rules.append(ENTRY_CONSISTENCY_VALIDATOR()) # [FATAL/ERROR] Entry count/name mismatch
        self.active_rules.append(FASTA_FORMAT_VALIDATOR())      # [ERROR/WARNING] Missing FASTA definition line / Sequence not terminated by "//"
        self.active_rules.append(DIV_TYPE_STATIC_VALIDATOR())   # [ERROR] DATATYPE static checks
        self.active_rules.append(DIV_TYPE_DYNAMIC_VALIDATOR())  # [ERROR] Dynamic DATATYPE edge cases
        
        available_rules = [
            # 【フェーズ1続き】塩基配列文字やエントリ名のエラー
            SEQ0090(), # [ERROR] Invalid nucleotide code [#LETTER] at [#N] position
            ANN0160(), # [ERROR] Invalid entry name
            
            # 【フェーズ3】外部DBアクセッション・リンク整合性チェック (Taxonomyの前に移動)
            ANN0342(), # [ERROR] The 'Published Only in Database' must be the first REFERENCE.
            ANN0343(), # [ERROR] More than one 'Published Only in Database' REFERENCE. Please provide only one.
            ANN0345(), # [WARNING] Invalid journal name. Not in the controlled values.
            ANN0410(), # [WARNING] Missing BioProject accession
            ANN0420(), # [WARNING] BioProject accession is not found in the BioProject database
            ANN0425(), # [ERROR] BioProject accession is cancelled/permanently suppressed/withdrawn in the BioProject database.
            ANN0430(), # [WARNING] BioProject mismatches with DRR linked project
            ANN0440(), # [WARNING] BioProject mismatches with BioSample linked project
            ANN0445(), # [ERROR] BioProject is an Umbrella project
            ANN0450(), # [WARNING] Missing BioSample accession
            ANN0460(), # [WARNING] BioSample accession not found in the BioSample database
            ANN0461(), # [WARNING] Accession is not publicly available or invalid in NCBI/EBI."
            ANN0462(), # [ERROR] Multiple BioSample accessions are permitted only for TSA entries.
            ANN0463(), # [ERROR] BioSample accession is cancelled/permanently suppressed/withdrawn in the BioSample database.
            ANN0470(), # [WARNING] Missing DRR accession
            ANN0480(), # [WARNING] DRR accession not found in the DRA database
            ANN0485(), # [ERROR] DRR accession is cancelled/permanently suppressed/withdrawn
            ANN0490(), # [WARNING] BioSample mismatches with DRR linked sample
            ANN0560(), # [WARNING] Inconsistent Sequencing Technology and SRA Experiment PLATFORM.

            # 【フェーズ4】Taxonomy・生物名チェック
            ANN1010(), # [ERROR] Missing organism
            ANN1020(), # [WARNING] The organism name is not found in the Taxonomy database
            ANN1040(), # [ERROR] Invalid taxonomic rank
            ANN1060(), # [ERROR] The metagenome_source qualifier value must be a valid scientific name
            ANN1050(), # [ERROR] The transl_table qualifier value mismatches with the Taxonomy database
            ANN1100(), # [ERROR] strain not permitted for environmental samples
            ANN1140(), # [WARNING] Source qualifiers must be identical across all WGS entries.            
            ANN1320(), # [ERROR] Specimen voucher for prokaryotes and unclassified sequences.
            ANN4210(), # [WARNING] Joined locations without a 'ribosomal_slippage' (TaxDB bacterial check)

            # 【フェーズ5】配列自体の品質チェック
            SEQ5010(), # [ERROR] Sequence should contain no more than 50% Ns
            SEQ5020(), # [WARNING] Sequences do not begin or end with Ns
            SEQ5040(), # [ERROR] Sequence shorter than 100 bases
            ANN5045(), # [ERROR] Minimal size for sequences in a eukaryote or prokaryotic genome is 1,000 nucleotides
            SEQ5050(), # [ERROR] Sequence longer than 1Gbases

            # 【フェーズ6】ロケーション構文・範囲チェック
            ANN2010(), # [ERROR] Location is missing
            ANN2030(), # [ERROR] Invalid character(s) in the location value
            AXS2080(), # [ERROR] The source feature location exceeds the sequence length
            AXS2090(), # [ERROR] Location is out of the sequence range
            ANN2100(), # [WARNING] Adjacent locations should be merged
            #ANN2110(), # [WARNING] Overlapping location intervals
            ANN2130(), # [WARNING] The unsure feature location exceeds 10 bases

            # 【フェーズ7】マルチファイル・サブミッション全体チェック
            ANN2510(), # [ERROR] Duplicate locus tag prefix
            ANN2520(), # [ERROR] Duplicate locus tag

            # 【フェーズ8】アノテーション・メタデータ詳細
            ANN0230(), # [ERROR] At least one submitter's 'ab_name' must match the contact person.
            ANN0250(), # [WARNING] Contact person not included in the associated BioSample.
            ANN0260(), # [WARNING] Contact person email not included in the associated BioSample
            ANN0270(), # [WARNING] No submitter ab_name shared with the associated BioSample
            ANN0300(), # [WARNING] Invalid reference information
            ANN0310(), # [WARNING] Invalid reference title
            ANN0350(), # [WARNING] Trailing comma is detected
            ANN0640(), # [ERROR] Keyword requires specific DATATYPE/type
            ANN0800(), # [WARNING] Invalid Assembly Method version format
            ANN0810(), # [WARNING] Invalid Genome Coverage/Coverage format
            ANN0820(), # [WARNING] Assembly Name required for eukaryotes
            ANN0830(), # [ERROR] Invalid ST_COMMENT qualifier value
            ANN0940(), # [ERROR] The REFERENCE status "Published Only in Database" is not allowed for TPA
            ANN1110(), # [WARNING] The strain matches an institution code
            ANN1240(), # [ERROR] Future collection date is not allowed
            ANN1275(), # [WARNING] Values provided for 'lat_lon' and 'geo_loc_name' contradict each other
            ANN1250(), # [WARNING] Invalid country. Not in the country list
            ANN1280(), # [WARNING] Sex qualifier is not valid for prokaryotes
            ANN1290(), # [WARNING] Invalid institution code
            ANN1330(), # [ERROR] Invalid specimen_voucher format
            ANN1350(), # [ERROR] Invalid bio_material format
            ANN1365(), # [WARNING] Multiple voucher qualifiers detected with the same institution code
            ANN1410(), # [ERROR] Inconsistent sample qualifiers
            ANN1420(), # [ERROR] Inconsistent sample qualifiers
            ANN1580(), # [ERROR] A main source feature must cover the entire sequence
            ANN1620(), # [ERROR] All source features must have the same 'mol_type' value.
            ANN1625(), # [ERROR] The rRNA and tRNA features are not permitted when mol_type is 'mRNA'
            ANN1626(), # [ERROR] The tRNA and CDS features are not permitted when the mol_type is 'rRNA'
            ANN1810(), # [ERROR] The clone qualifier value is not unique
            ANN1820(), # [ERROR] The submitter_seqid qualifier value must be unique
            ANN1830(), # [ERROR] Invalid submitter_seqid qualifier value format
            ANN2530(), # [WARNING] Missing locus_tag
            ANN2540(), # [ERROR] Invalid locus tag prefix format
            ANN2542(), # [ERROR] Duplicate locus_tag found across different features
            ANN2544(), # [WARNING] Invalid locus_tag length or digit format
            ANN2545(), # [WARNING] DFAST-generated 'LOCUS' detected
            ANN2555(), # [WARNING] Invalid CDS:mRNA or CDS:misc_feature ratio
            ANN2560(), # [ERROR] Invalid chromosome name
            ANN2570(), # [ERROR] Invalid plasmid name
            ANN2580(), # [WARNING] Partial rRNA feature annotated by DFAST
            ANN2590(), # [ERROR] Complement CDS/mRNA/tRNA/rRNA features in TSA
            ANN2594(), # [ERROR] Multiple CDS features are not permitted in TSA entries
            ANN2600(), # [WARNING] Unexpected rRNA length
            ANN2610(), # [WARNING] Unexpected tRNA length
            ANN2620(), # [WARNING] Unexpected tmRNA length
            ANN2625(), # [WARNING] Unexpected lncRNA length
            ANN2630(), # [ERROR] Entry must contain at least one feature in addition to the source
            ANN2660(), # [ERROR] Feature cannot be used
            ANN2661(), # [ERROR] Feature is not defined.
            ANN2670(), # [ERROR] Usage of the feature is not recommended
            ANN2680(), # [WARNING] Identical feature and location
            ANTICODON_VALIDATOR(), # [ERROR] Validate /anticodon logical constraints
            ANN2750(), # [ERROR] The strand of the 'anticodon' base position mismatch with the tRNA feature.
            ANN3020(), # [ERROR] Qualifier cannot be used
            ANN3021(), # [ERROR] Qualifier is not defined.
            ANN3170(), # [WARNING] No qualifier found after the location column
            ANN3240(), # [ERROR] The artificial_location qualifier is restricted
            ANN3260(), # [WARNING] Historical country name is used
            ANN3350(), # [WARNING] Set hold date at least 10 days from today
            ANN4100(), # [WARNING] DDBJ, GenBank or ENA detected in the inference qualifier
            ANN4200(), # [ERROR] All WGS entries are annotated as 'circular'
            ANN4220(), # [WARNING] There is a pair of genes with the same span but on different strands
            ANN4240(), # [ERROR] For prokaryote genomes, features can be partial...
            ANN4300(), # [WARNING] Complete CDS must be at least 90 bases
            ANN4400(), # [WARNING] The '/allele' qualifier value must be different from the '/gene' qualifier value.
            ANN4410(), # [WARNING] The '/altitude' qualifier value must end with ' m'
            
            FF_DEFINITION_VALIDATOR(), # [WARNING/ERROR] (Groups definition line checks)
            OPERON_MASTER_VALIDATOR(), # [WARNING/ERROR] (Groups operon checks)
            
            # 【フェーズ9】アセンブリ・ギャップ関連
            AXS5090(), # [ERROR] Sequences annotated as gap or assembly_gap must consist entirely of 'N'
            AXS5100(), # [WARNING] Consecutive 'N's is longer than the corresponding gap feature
            AXS5210(), # [ERROR] Gap content exceeds 50% of sequence
            ANN5220(), # [WARNING] Unknown gap length exceeds 1,000 bases
            ANN5230(), # [WARNING] All unknown assembly_gap features must have a uniform length
            ANN5240(), # [WARNING] All known assembly_gap features have a uniform length
            ANN5242(), # [WARNING] Location operators cannot be used in 'assembly_gap'
            ANN5244(), # [WARNING] Qualifier 'estimated_length=unknown' cannot be used in transcriptome entries
            ANN5250(), # [WARNING] Inconsistent gap_type and linkage_evidence (telomere)
            ANN5270(), # [WARNING] Overlap between CDS/mRNA and assembly_gap/gap features
            AXS5290(), # [WARNING] Consecutive 'N's must be annotated with a gap or assembly_gap feature

            # 【フェーズ10】フィーチャー間の依存・重複関係
            ANN5310(), # [ERROR] The rRNA feature must not overlap CDS or other rRNA features
            ANN5320(), # [ERROR] The tRNA feature must not fully overlap within CDS exons
            ANN5330(), # [ERROR] For entries with mol_type mRNA, CDS features must not be located on the minus strand
            ANN5340(), # [ERROR] CDS regions must not span multiple joined locations.
            
            # 【フェーズ11】翻訳・イントロン関連（高負荷プロセス）
            AXS6085(), # [WARNING] The length of the complete CDS is not a multiple of 3.
            AXS6087(), # [ERROR] Unnecessary exception: The conceptual translation perfectly matches the annotated translation
            ANN6400(), # [ERROR] The strand of the 'transl_except' location mismatch with the CDS feature.
            ANN6520(), # [WARNING] A transl_table qualifier is required for a CDS feature
            ANN6840(), # [WARNING] CDS/mRNA intron is less than 10 bp
            AXS6810(), # [WARNING] Non-canonical splice sites: GT-AG rule violation
            AXS6820(), # [WARNING] Introns (3, 6 or 9 bp) consist entirely of stop codons
            
            CDS_TRANSLATION_VALIDATOR(), # [ERROR/WARNING] Checks untranslatable codons, start/stop codons, internal stops
            CDS_TRANSL_EXCEPT_VALIDATOR(), # [ERROR/WARNING] Checks transl_except format, boundaries, and necessity
        ]
        
        for rule in available_rules:
            # RDB必須ルールは skip_db が True の時にスキップ
            if ctx.skip_db and getattr(rule, 'requires_rdb', False):
                continue
            # ネットワーク必須ルールは skip_ncbi が True の時にスキップ
            if ctx.skip_ncbi and getattr(rule, 'requires_network', False):
                continue            
            
            # 認証が必要なルールを、skip_auth 指定時にスキップ
            if ctx.skip_auth and getattr(rule, 'requires_auth', False):
                continue

            self.active_rules.append(rule)

        if ctx.ddbj_dict and ctx.ddbj_dict.get("features"):
            self.active_rules.append(ANN_DICT_VALIDATOR())
            
        # クロスチェックは内部DBを使うので skip_db を確認する
        if not ctx.skip_db and ctx.dra_crosscheck_dict and ctx.dra_lib_meta:
            cross_rule = DRA_CROSSCHECK_VALIDATOR()
            # 認証スキップ指定時、ルールが認証必須であれば登録しない
            if not (ctx.skip_auth and (getattr(cross_rule, 'requires_auth', False) or getattr(cross_rule, 'auth_required', False))):
                self.active_rules.append(cross_rule)
                            
    # 引数に ann_lines=None を追加
    def run(self, records, ann_path=None, seq_path=None, ann_lines=None, fasta_content=None):
        all_results = []
        
        # ==============================================================
        # 事前インデックス構築のフォールバック (パーサーをバイパスした場合の安全網)
        # ==============================================================
        for record in records.values():
            if record.id == "COMMON": 
                continue
                
            if not hasattr(record, 'features_by_type'):
                record.features_by_type = defaultdict(list)
                record.features_by_locus_tag = defaultdict(list)
                
                for feature in record.features:
                    record.features_by_type[feature.type].append(feature)
                    for tag in feature.qualifiers.get("locus_tag", []):
                        record.features_by_locus_tag[tag].append(feature)
        
        for rule in self.active_rules:
            if getattr(rule, 'is_submission_level', False): continue
            
            results = []
            
            if getattr(rule, 'is_file_level', False):
                sig = inspect.signature(rule.validate_file)
                kwargs = {}
                if 'context' in sig.parameters:
                    kwargs['context'] = self.context
                if 'ann_path' in sig.parameters:
                    kwargs['ann_path'] = ann_path
                if 'seq_path' in sig.parameters:
                    kwargs['seq_path'] = seq_path
                if 'ann_lines' in sig.parameters:
                    kwargs['ann_lines'] = ann_lines
                if 'fasta_content' in sig.parameters:
                    kwargs['fasta_content'] = fasta_content
                                                        
                try:
                    res = rule.validate_file(records, **kwargs)
                    if res:
                        results.extend(res)
                except NotImplementedError:
                    print(f"[WARN] Rule '{rule.__class__.__name__}' lacks validate_file(). Skipping.")
                    continue
                except Exception as e:
                    print(f"[ERROR] Rule '{rule.__class__.__name__}' failed during validation: {e}")
                    continue
            else:
                # ループ外でシグネチャを判定して高速化
                sig = inspect.signature(rule.validate)
                kwargs = {}
                if 'context' in sig.parameters:
                    kwargs['context'] = self.context

                for entry_id, record in records.items():
                    try:
                        res = rule.validate(record, **kwargs)
                        if res:
                            results.extend(res)
                    except Exception as e:
                        print(f"[ERROR] Rule '{rule.__class__.__name__}' failed on entry '{entry_id}': {e}")

            # 正しくカテゴリー情報とファイル名を付与して all_results に追加する
            if results:
                category = rule.__module__.split('.')[-1]
                for r in results: 
                    r['category'] = category
                    
                    # rule_id が未設定の場合、クラスの rule_id を自動付与する
                    if not r.get('rule'):
                        r['rule'] = getattr(rule, 'rule_id', 'UNKNOWN')

                    if r.get('rule', '').startswith(('SEQ', 'AXS')) and seq_path:
                        r['file'] = Path(seq_path).name
                        r['full_path'] = str(seq_path)
                    elif ann_path:
                        r['file'] = Path(ann_path).name
                        r['full_path'] = str(ann_path)
                all_results.extend(results)

        unique_results = []
        
        seen = set()
        for r in all_results:
            key = (r.get('rule'), r.get('entry'), r.get('feature_type'), r.get('qualifier'), r.get('line_number'), r.get('message'))
            if key not in seen:
                seen.add(key)
                unique_results.append(r)
                
        return unique_results