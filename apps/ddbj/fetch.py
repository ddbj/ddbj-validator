"""フェーズ 1: 外部参照（内部 DB / NCBI API）の一括取得。

`ValidatorPipeline` に mixin として混ぜる。`_fetch_external()` は全 .ann を並列スキャンして
organism / BioProject / BioSample / DRR / journal を集め、ソースごとに 1 回だけ問い合わせて
`ValidationContext` を組む。アカウント権限の事前チェック（gatekeeper）もここ。
状態は self（pairs / jobs / skip_* / account_id / emit_biosample_tsv など）を読み書きする。
2026-09-15 に apps/ddbj/orchestrator.py から移動（中身は不変）。
"""
import logging
from concurrent.futures import ProcessPoolExecutor

from common.db_manager import DatabaseManager
from apps.ddbj.db_metadata import (
    fetch_biosample_data, fetch_biosample_submitters, fetch_biosample_smp_ids,
    fetch_bp_psubs, fetch_dra_refs, fetch_prjdb_by_psub, fetch_samd_by_smp_id,
    fetch_dra_library_metadata, fetch_drr_status, fast_extract_db_keys
)
from common.db_taxonomy import fetch_taxonomy_data
from common.ncbi_api import check_ncbi_public_status
from apps.ddbj.context import ValidationContext

logger = logging.getLogger(__name__)


class ExternalFetchMixin:
    """`ValidatorPipeline` のフェーズ 1 部分。"""

    def _fetch_external(self):
        """フェーズ1: 外部参照（内部DB / NCBI API）を一括取得し ValidationContext を構築して返す。"""
        all_samds, all_projects, all_drrs, all_organisms, all_journals = set(), set(), set(), set(), set()
        ncbi_check_prjs, ncbi_check_sams, ncbi_check_sras = set(), set() , set()
        
        bp_psubs, dra_refs, tax_data, bs_data = {}, {}, {}, {}
        bs_submitters, bs_smp_ids, psub_to_prjdb, smp_id_to_samd = {}, {}, {}, {}
        dra_lib_meta = {}
        drr_status = {}
        ncbi_private_accs = set() 
        
        # 1. 高速並列スキャン
        if not self.skip_db or not self.skip_ncbi:
            if self.skip_db and not self.skip_ncbi:
                print("\nScanning annotation files for NCBI API queries...")
            else:
                print("\nScanning annotation files for DB/API queries...")
                
            with ProcessPoolExecutor(max_workers=self.jobs) as executor:
                futures = [executor.submit(fast_extract_db_keys, ann, seq) for ann, seq in self.pairs]
                for (ann, seq), future in zip(self.pairs, futures):
                    res = future.result()
                    # -b 用: ann ファイル単位の参照 BioSample 集合（ann↔bs マッピングの曖昧性判定に使う）
                    if self.emit_biosample_tsv:
                        self.ann_to_samds[ann] = set(res["samds"])
                    all_samds.update(res["samds"])
                    all_projects.update(res["projects"])
                    all_drrs.update(res["drrs"])
                    all_organisms.update(res["organisms"])
                    all_journals.update(res["journals"])
                    ncbi_check_prjs.update(res["ncbi_check_prjs"])
                    ncbi_check_sams.update(res["ncbi_check_sams"])
                    ncbi_check_sras.update(res["ncbi_check_sras"])

            # --- 2. データベース情報の取得 (内部DBへのアクセス) ---
            if not self.skip_db:
                db_manager = DatabaseManager()
                try:
                    # =========================================================
                    # ★ ゲートキーパー: アカウント権限の事前チェック
                    # =========================================================
                    auth_prjs = auth_sams = auth_drrs = None
                    if not self.is_curator_mode and self.account_id:
                        print(f"\n[Auth Check] Verifying access rights for account: '{self.account_id}'...")
                        from apps.ddbj.db_auth import fetch_authorized_accessions
                        auth_prjs, auth_sams, auth_drrs = fetch_authorized_accessions(
                            db_manager.get_bp_conn(),
                            db_manager.get_bs_conn(),
                            db_manager.get_dra_conn(),
                            self.account_id
                        )
                        # unauthorized の確定は DB メタ取得の後（下の「アカウント権限の確定」）。
                        # 実在しない accession を権限エラーに混ぜないため、実在集合が要る。

                    if all_organisms or all_samds or all_projects or all_drrs:
                        print("\nChecking Internal DB...")

                    if all_organisms:
                        lbl = "organism" if len(all_organisms) == 1 else "organisms"
                        print(f"[Taxonomy DB] Checking {len(all_organisms)} {lbl}...")
                        tax_data = fetch_taxonomy_data(db_manager.get_tax_conn(), list(all_organisms))
                        
                    if all_projects:
                        lbl = "project" if len(all_projects) == 1 else "projects"
                        print(f"[BioProject DB] Checking {len(all_projects)} {lbl}...")
                        bp_psubs = fetch_bp_psubs(db_manager.get_bp_conn(), list(all_projects))

                    if all_samds:
                        samd_list = list(all_samds)
                        lbl = "sample" if len(samd_list) == 1 else "samples"
                        print(f"[BioSample DB] Checking {len(samd_list)} {lbl}...")
                        bs_data = fetch_biosample_data(db_manager.get_bs_conn(), samd_list)
                        bs_submitters = fetch_biosample_submitters(db_manager.get_bs_conn(), samd_list)
                        bs_smp_ids = fetch_biosample_smp_ids(db_manager.get_bs_conn(), samd_list)

                        # -b/--biosample: SSUB 単位の全サンプル＋属性を取得（更新用 TSV 生成のため）
                        if self.emit_biosample_tsv:
                            from apps.ddbj.db_meta_biosample import fetch_biosample_ssub
                            self.biosample_ssub, found = fetch_biosample_ssub(db_manager.get_bs_conn(), samd_list)
                            self._biosample_found_samds = found
                            self._biosample_input_samds = set(samd_list)

                    if all_drrs:
                        lbl = "DRA Run" if len(all_drrs) == 1 else "DRA Runs"
                        print(f"[DRA DB] Checking {len(all_drrs)} {lbl}...")
                        dra_refs = fetch_dra_refs(db_manager.get_dra_conn(), list(all_drrs))
                        dra_lib_meta = fetch_dra_library_metadata(db_manager.get_dra_conn(), list(all_drrs))
                        drr_status = fetch_drr_status(db_manager.get_dra_conn(), list(all_drrs))
                        
                        if dra_refs:
                            dra_psubs, dra_smps = set(), set()
                            for refs in dra_refs.values():
                                for r in refs:
                                    if r.startswith("PSUB"): dra_psubs.add(r)
                                    elif r.isdigit(): dra_smps.add(int(r))
                            
                            if dra_psubs:
                                psub_to_prjdb = fetch_prjdb_by_psub(db_manager.get_bp_conn(), list(dra_psubs))
                            if dra_smps:
                                smp_id_to_samd = fetch_samd_by_smp_id(db_manager.get_bs_conn(), list(dra_smps))

                    # =========================================================
                    # アカウント権限の確定（実在しない accession は除く）
                    # =========================================================
                    # 単純な集合差にすると、**打ち間違いで存在しない accession も「権限が無い」に落ちる**。
                    # 存在しないことは ANN0420 / ANN0460 / ANN0480 が別に報告しているので、
                    # ここで混ぜると (1) 同じ番号が 2 つのルールから出る
                    # (2) 打ち間違い 1 件で skip_auth が立ち認証必須ルールが全部止まる、の 2 つが起きる。
                    # 除外条件は上記 3 ルールの判定式と同じにしてある（PSUB / SSUB のように
                    # 実在判定できないものは除外せず、従来どおり権限エラーとして扱う）。
                    if auth_prjs is not None:
                        missing_prjs = {p for p in all_projects if p.startswith("PRJDB") and p not in bp_psubs}
                        missing_sams = {s for s in all_samds if s.startswith("SAMD") and s not in bs_smp_ids}
                        missing_drrs = {d for d in all_drrs if d.startswith("DRR") and d not in dra_refs}
                        self.unauthorized_accs["bioproject"] = (all_projects - auth_prjs) - missing_prjs
                        self.unauthorized_accs["biosample"] = (all_samds - auth_sams) - missing_sams
                        self.unauthorized_accs["sra"] = (all_drrs - auth_drrs) - missing_drrs

                        # =================================================
                        # 権限の無い BioSample の中身は取得済みでも捨てる
                        # =================================================
                        # BioSample の取得は権限確定より前に走るので、この時点の bs_data /
                        # bs_submitters にはアカウントがアクセスできないサンプルの属性値も
                        # 入っている。残したままだと ANN1130（BioSample 属性との突合）が
                        # 非公開サンプルの値をメッセージに出し、さらに autofix で登録者の
                        # ann に書き込もうとする。ANN0463 で「権限が無い」と報告する相手の
                        # 中身は一切使わない、を守るためここで落とす。
                        # 認証必須ルール側は skip_auth で止まるが、autofix の提案生成は
                        # ルールではなく worker が直接呼ぶので skip_auth では止まらない。
                        for samd in self.unauthorized_accs["biosample"]:
                            bs_data.pop(samd, None)
                            bs_submitters.pop(samd, None)

                        # 権限がないアクセッションが含まれていれば、以後の認証必須ルールをスキップする
                        if any(self.unauthorized_accs.values()):
                            logger.warning("Unauthorized accession numbers referenced. Disable rules requiring account authorization.")
                            self.skip_auth = True
                except Exception as e:
                    logger.error(f"Database connection failed: {e}", exc_info=True)
                finally:
                    db_manager.close_all()
            else:
                print()
                if not self.skip_ncbi:
                    print("[ NCBI API ] Public NCBI API will be used for taxonomy-dependent rules and NCBI/EBI accessions checks.")
                print("[ SKIP ] Internal DB queries skipped. DB-dependent rules will be skipped.")
                
            # --- 3. NCBI APIへのアクセス ---
            if not self.skip_ncbi:
                if ncbi_check_prjs or ncbi_check_sams or ncbi_check_sras or (self.skip_db and all_organisms):
                    print("\nChecking NCBI API...")

                if ncbi_check_prjs:
                    lbl = "BioProject" if len(ncbi_check_prjs) == 1 else "BioProjects"
                    print(f"[NCBI API] Checking {len(ncbi_check_prjs)} {lbl}...")
                    res = check_ncbi_public_status("bioproject", list(ncbi_check_prjs))
                    ncbi_private_accs.update(res.get("private", []))

                if ncbi_check_sams:
                    lbl = "BioSample" if len(ncbi_check_sams) == 1 else "BioSamples"
                    print(f"[NCBI API] Checking {len(ncbi_check_sams)} {lbl}...")
                    res = check_ncbi_public_status("biosample", list(ncbi_check_sams))
                    ncbi_private_accs.update(res.get("private", []))

                if ncbi_check_sras:
                    lbl = "SRA Run" if len(ncbi_check_sras) == 1 else "SRA Runs"
                    print(f"[NCBI API] Checking {len(ncbi_check_sras)} {lbl}...")
                    res = check_ncbi_public_status("sra", list(ncbi_check_sras))
                    ncbi_private_accs.update(res.get("private", []))
                # DBスキップ時のみ NCBI API から Taxonomy を代替取得
                if self.skip_db and all_organisms:
                    lbl = "organism" if len(all_organisms) == 1 else "organisms"
                    print(f"[NCBI Taxonomy API] Checking {len(all_organisms)} {lbl}...")
                    from common.db_taxonomy import fetch_taxonomy_from_ncbi
                    tax_data = fetch_taxonomy_from_ncbi(list(all_organisms))                    
            else:
                print("\n[ SKIP ] NCBI API queries skipped. API- and taxonomy-dependent rules will be skipped.")
                
        else:
            print("\n[ SKIP ] DB and NCBI API queries skipped. DB-, API- and taxonomy-dependent rules will be skipped.")
            print("Tip: Use '-n' to enable taxonomy-dependent checks via NCBI API.")

        # --- Context の初期化 (共通ルート) ---
        context = ValidationContext(
            is_curator_mode=self.is_curator_mode and not self.skip_db,
            is_web_mode=self.is_web_mode,
            skip_db=self.skip_db,
            skip_ncbi=self.skip_ncbi,
            skip_auth=self.skip_auth,
            bp_psubs=bp_psubs,
            dra_refs=dra_refs,
            drr_status=drr_status,
            tax_data=tax_data,
            bs_data=bs_data,
            bs_submitters=bs_submitters,
            bs_smp_ids=bs_smp_ids,
            psub_to_prjdb=psub_to_prjdb,
            smp_id_to_samd=smp_id_to_samd,
            dra_lib_meta=dra_lib_meta,
            ncbi_private_accs=ncbi_private_accs  
        )
        
        # valid_journals の追加取得
        if not self.skip_db and all_journals:
            db_manager = DatabaseManager()
            try:
                context.load_valid_journals(list(all_journals), db_manager.get_tax_conn())
            except Exception as e:
                logger.debug(f"Failed to load valid journals: {e}", exc_info=True)
            finally:
                db_manager.close_all()

        self.tax_data = tax_data
        self.bs_data = bs_data
        return context
