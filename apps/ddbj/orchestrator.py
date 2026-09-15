"""DDBJ validator のパイプライン（3 フェーズを繋ぐ骨）。

1. `fetch.ExternalFetchMixin._fetch_external`      … 外部参照の一括取得 → ValidationContext
2. `_validate_files` ＋ `validate_worker`            … ファイル単位の並列検証（結果は JSONL 経由）→ クロスファイル
3. `run_autofix` ＋ `autofix.writer`                 … 提案のレビュー → fixed/ aa/ の書き出し
   （-b は `biosample.pipeline.BiosampleTsvMixin`）

2026-09-15 にワーカー・書き出し・フェーズ 1・-b を別モジュールへ分けた。旧 import 互換のため
主要シンボルはここから再エクスポートする。
"""
import shutil
import json
import logging
from pathlib import Path
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor

logger = logging.getLogger(__name__)

from apps.ddbj.autofix import review_and_approve_proposals, apply_proposals
from apps.ddbj.rule_modes import get_web_mode_skip_rules
from apps.ddbj.fetch import ExternalFetchMixin
from apps.ddbj.biosample.pipeline import BiosampleTsvMixin
# 旧 import 互換（apps.ddbj.orchestrator から参照していたシンボル）
from apps.ddbj.validate_worker import ValidateTask, _validate_single_file_set  # noqa: F401
from apps.ddbj.autofix.writer import (  # noqa: F401
    AutofixTask, _apply_autofix_worker, write_autofix_to_file, write_clean_ann,
    write_aa_fasta, fast_copy_and_fix_fasta,
)


class ValidatorPipeline(ExternalFetchMixin, BiosampleTsvMixin):
    def __init__(self, pairs, report_out_dir, is_web_mode, force_fix, jobs=1, skip_db=False, skip_ncbi=False, skip_auth=False, account_id=None, is_curator_mode=True, emit_biosample_tsv=False, nsub=None, biosample_apply="bs2ann"):
        self.pairs = pairs
        self.report_out_dir = report_out_dir
        self.is_web_mode = is_web_mode
        self.force_fix = force_fix
        self.jobs = jobs

        # -b/--biosample: SSUB 単位の BioSample 更新用 TSV 生成フラグと NSUB(対象ディレクトリ名)
        self.emit_biosample_tsv = emit_biosample_tsv
        self.nsub = nsub
        # force 時の biosample 同期方向（内部/テスト用）: "bs2ann"（既定）/ "ann2bs"
        self.biosample_apply = biosample_apply
        self.biosample_ssub = {}  # {submission_id: {"samples": [...]}}（フェーズ1で構築）
        self.ann_to_samds = {}    # {ann_path: set(SAMD)}（-b: ann↔bs 曖昧性判定）
        
        self.skip_db = skip_db
        self.skip_ncbi = skip_ncbi
        
        # DBをスキップする(ローカル利用)場合は、権限必須ルールも強制スキップ
        self.skip_auth = True if self.skip_db else skip_auth
        
        self.account_id = account_id
        self.is_curator_mode = is_curator_mode
        self.unauthorized_accs = {"bioproject": set(), "biosample": set(), "sra": set()}        
        
        self.all_interactive_proposals = []
        self.all_skipped_autofixes = []
        self.auto_updates_by_file = defaultdict(list)
        self.updq_data = defaultdict(list)
        self.tax_data = {}
        self.bs_data = {}
        self.cv_terms = {}

    def run_validation(self):
        """検証パイプライン: 外部参照の一括取得 → 並列ファイル検証を順に実行する。"""
        context = self._fetch_external()
        return self._validate_files(context)

    def _validate_files(self, context):
        """フェーズ2: 各ファイルを並列検証し、クロスファイルチェックを行って JSONL パス一覧を返す。"""
        auto_updates_by_file = defaultdict(list)
        updq_data = defaultdict(list)
                
        # 4. 個別ファイルの検証 (並列処理)
        # 出力先が指定されていればそこに、なければ今まで通り .val_tmp を作成
        base_tmp_dir = Path(self.report_out_dir) if self.report_out_dir else Path(self.pairs[0][0]).parent
        self.tmp_dir = base_tmp_dir / ".val_tmp"
        self.tmp_dir.mkdir(parents=True, exist_ok=True)

        # -b 用: biosample_sync.common を一度だけ読み込みワーカーへ渡す
        biosample_sync_common = []
        biosample_sync_mapping_keys = []
        if self.emit_biosample_tsv:
            try:
                from apps.ddbj.biosample.tsv import load_biosample_sync
                _sync = load_biosample_sync()
                biosample_sync_common = _sync.get("common", [])
                biosample_sync_mapping_keys = [m["ddbj"] for m in _sync.get("mapping", []) if "ddbj" in m]
            except Exception:
                biosample_sync_common = []
                biosample_sync_mapping_keys = []

        tasks = []
        for ann_path, seq_path in self.pairs:
            tasks.append(ValidateTask(
                ann_path=ann_path, seq_path=seq_path, context=context,
                tax_data=self.tax_data, bs_data=self.bs_data, is_web_mode=self.is_web_mode,
                report_out_dir=self.report_out_dir, tmp_dir_str=str(self.tmp_dir),
                unauthorized_accs=self.unauthorized_accs, emit_biosample_tsv=self.emit_biosample_tsv,
                biosample_sync_common=biosample_sync_common,
                biosample_sync_mapping_keys=biosample_sync_mapping_keys))
            
        jsonl_paths = []
        with ProcessPoolExecutor(max_workers=self.jobs) as executor:
            actual_workers = min(executor._max_workers, len(tasks))
            num_sets = len(self.pairs)
            
            p_label = "process" if actual_workers == 1 else "processes"
            f_label = "file set" if num_sets == 1 else "file sets"
            
            print(f"\nRunning validations for {num_sets} {f_label} in {actual_workers} {p_label}...\n")
            
            for output in executor.map(_validate_single_file_set, tasks):
                jsonl_paths.append(output["jsonl_path"])
                self.all_skipped_autofixes.extend(output["skipped_autofixes"])
                
                for out_path, line in output["updq_data"]:
                    updq_data[out_path].append(line)

        # 5. JSONL からメタデータと提案を読み出してクロスチェック
        cross_locus_tags = defaultdict(list)
        all_interactive_proposals = []

        for j_path in jsonl_paths:
            with open(j_path, "r", encoding="utf-8") as f:
                for line in f:
                    rec = json.loads(line)
                    r_type = rec["type"]
                    data = rec["data"]
                    if r_type == "locus_tag":
                        data["file"] = j_path
                        cross_locus_tags[data["tag"]].append(data)
                    elif r_type == "proposal":
                        # ann限定追加候補(bs_addition)も含め対話式レビューに載せる（自動適用しない）
                        all_interactive_proposals.append(data)

        # クロスファイル（Submission全体）のユニークチェック
        cross_file_results = []

        for tag, locs in cross_locus_tags.items():
            # エントリー名とファイル名の組み合わせでユニークにする
            unique_occurrences = set([f"{o['entry']} in {Path(o['file']).name.replace('.jsonl', '')}" for o in locs])
            
            # 異なるエントリー（または異なるファイル）にまたがって存在する場合のみエラーとする
            if len(unique_occurrences) > 1:
                details = ", ".join(sorted(list(unique_occurrences)))
                msg = f"Duplicate locus_tag found across the submission. (Found: '{tag}' in {details})"
                cross_file_results.append({
                    "file": "Submission (across files)", "full_path": "", "rule": "ANN2520",
                    "level": "ERROR", "entry": "ALL_ENTRIES", "feature_type": "locus_tag", "target": "locus_tag", "message": msg
                })
                
        # -w（NSSS）モードでは submission-level も所定ルールを除外
        if self.is_web_mode:
            web_skip = get_web_mode_skip_rules()
            if web_skip:
                cross_file_results = [r for r in cross_file_results if r.get("rule") not in web_skip]

        # クロスファイルのチェック結果も専用の JSONL に書き出して先頭に追加
        if cross_file_results:
            cross_jsonl = self.tmp_dir / "Submission_Cross_File.jsonl"
            with open(cross_jsonl, "w", encoding="utf-8") as f:
                for res in cross_file_results:
                    f.write(json.dumps({"type": "result", "data": res}) + "\n")
            jsonl_paths.insert(0, str(cross_jsonl))

        # 後続フェーズのために状態を保存
        self.all_interactive_proposals = all_interactive_proposals
        self.auto_updates_by_file = auto_updates_by_file
        self.updq_data = updq_data
        self.cv_terms = context.cv_terms
        
        return jsonl_paths

    def cleanup_tmp_dir(self):
        """テンポラリディレクトリのお掃除"""
        if hasattr(self, 'tmp_dir') and self.tmp_dir and self.tmp_dir.exists():
            shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def run_autofix(self):
        """フェーズ2 & 3: Autofix 提案のレビューとファイルへの適用"""
        if self.all_skipped_autofixes:
            print("\n=== Auto-Fix Skipped (Mixed BioSample Values) ===")
            skip_summary = defaultdict(lambda: defaultdict(list))
            
            for skip in self.all_skipped_autofixes:
                val_str = "{" + ", ".join(repr(v) for v in sorted(skip["values"])) + "}"
                skip_summary[skip["ann_path"]][skip["attr"]].append((skip["entry"], val_str))
                
            for path_str, attrs in sorted(skip_summary.items()):
                print(f"\n[ {Path(path_str).name} ]")
                for attr, entries in sorted(attrs.items()):
                    first_val_str = entries[0][1] 
                    e_len = len(entries)
                    e_label = "entry" if e_len == 1 else "entries"
                    print(f"  {e_len} {e_label}: BioSample values differ for '{attr}': {first_val_str}")
            print() 

        for p in self.all_interactive_proposals:
            # proposal は build_proposal 経由で old_value/new_value を必ず持つ（old/new エイリアスは撤廃済み）。
            # ここでは rule / target の欠損のみ防御的に補完する。
            if "rule" not in p or not p["rule"]:
                p["rule"] = "UNKNOWN"

            if "target" not in p:
                p["target"] = p.get("qualifier", "feature")
            
        # -b: ann↔bs が 1:1 の「クリーンな」SAMD のみ autofix 対象。曖昧（1 ann→複数 bs / 複数 ann→1 bs）は skip。
        self._biosample_clean_samds = self._compute_clean_samds() if self.emit_biosample_tsv else set()
        biosample_mode = self.emit_biosample_tsv and bool(self._biosample_clean_samds)
        # out_dir を渡して、提案サマリーを同じ場所に出力させる。
        # フォローアップ（ann→bs 更新）はクリーンな SAMD の提案のみ対象。
        approved_proposals = review_and_approve_proposals(
            self.all_interactive_proposals, self.force_fix, out_dir=self.report_out_dir,
            biosample_mode=biosample_mode, biosample_clean_samds=self._biosample_clean_samds,
            biosample_apply=self.biosample_apply
        )
        
        approved_by_file = defaultdict(list)
        if approved_proposals:
            for p in approved_proposals:  
                approved_by_file[p["ann_path"]].append(p)

        # 並列で Autofix を適用して出力
        if approved_proposals or not self.all_interactive_proposals:
            print("\n=== File Cleanup & Auto-Fix ===")
        else:
            print("\n=== File Cleanup (No auto-fix) ===")

        autofix_tasks = []
        for ann_path, seq_path in self.pairs:
            file_updates = self.auto_updates_by_file[ann_path]
            
            if approved_proposals and approved_by_file[ann_path]:
                interactive_updates = apply_proposals(approved_by_file[ann_path])
                file_updates.extend(interactive_updates)
                
            # report_out_dir を引数に追加
            autofix_tasks.append(AutofixTask(
                ann_path=ann_path, seq_path=seq_path, file_updates=file_updates,
                tax_data=self.tax_data, cv_terms=self.cv_terms, report_out_dir=self.report_out_dir))

        with ProcessPoolExecutor(max_workers=self.jobs) as executor:
            for msg in executor.map(_apply_autofix_worker, autofix_tasks):
                print(msg)
                
        if self.is_web_mode and self.updq_data:
            print("\n[NSSS Mode] Exporting DB update files...")
            for out_path, lines in self.updq_data.items():
                Path(out_path).parent.mkdir(parents=True, exist_ok=True)  # reports/ を確実に作る
                with open(out_path, "w", encoding="utf-8", newline="\n") as f:
                    f.writelines(lines)
                print(f"  => DB update TSV saved to: {out_path}")

        # -b/--biosample: SSUB 単位の BioSample 更新用 TSV を生成
        if self.emit_biosample_tsv:
            self._generate_biosample_tsv()
