"""-b/--biosample: SSUB 単位の BioSample 更新用 TSV 生成（フェーズ 3 の一部）。

`ValidatorPipeline` に mixin として混ぜる。ann↔bs 1:1 の「クリーンな」SAMD の判定と、
承認済み提案（bs_decision）を反映した SSUB TSV の書き出し。純粋ロジックは同ディレクトリの
emit.py / tsv.py にあり、ここは pipeline の状態（biosample_ssub / all_interactive_proposals 等）との橋渡し。
2026-09-15 に apps/ddbj/orchestrator.py から移動（中身は不変）。
"""
from collections import defaultdict
from pathlib import Path


class BiosampleTsvMixin:
    """`ValidatorPipeline` の -b 部分。"""

    def _compute_clean_samds(self):
        """ann↔bs が 1:1 でマッピングできる（autofix 可能な）SAMD 集合を返す。

        SAMD が「クリーン」= その SAMD を参照する ann がちょうど 1 つ、かつ その ann が参照する SAMD も
        その 1 つだけ。これ以外（1 ann→複数 bs / 複数 ann→1 bs）は曖昧なので autofix を skip する。
        """
        a2s = getattr(self, "ann_to_samds", {})
        if not a2s:
            return set()
        samd_to_anns = defaultdict(set)
        for ann, samds in a2s.items():
            for s in samds:
                samd_to_anns[s].add(ann)
        clean = set()
        for samd, anns in samd_to_anns.items():
            if len(anns) == 1:
                only_ann = next(iter(anns))
                if len(a2s.get(only_ann, set())) == 1:
                    clean.add(samd)
        return clean

    def _generate_biosample_tsv(self):
        """SSUB 単位の BioSample 更新用 TSV を `<out>/biosample/` に出力する。

        - クリーンな SAMD（ann↔bs が 1:1）: autofix の判定（bs_decision）/ann限定追加を反映。
        - 曖昧な SAMD（1 ann→複数 bs / 複数 ann→1 bs）: autofix を skip し、BioSample 現行値のまま。
        ファイル名の `_unmodified` は **その SSUB TSV が実際に無修正か**で決まる（skip 有無に依らない）:
        - override（ann→bs 上書き・属性追加）が1つも適用されなかった SSUB → `<SSUB>_<NSUB>_unmodified.txt`
        - 何らか適用された SSUB → `<SSUB>_<NSUB>.txt`
        列順・必須 '*' 表記は登録システムと同一（attributes_packages.json に焼き込み済み）。
        """
        from apps.ddbj.biosample.tsv import load_biosample_definitions, build_ssub_tsv

        print("\n=== BioSample Submission TSV ===")

        # 出力先（実行時に既存の SSUB TSV を削除して旧命名の残留を防ぐ。aa/reports/fixed と同様の運用）
        out_dir = Path(self.report_out_dir) / "biosample" if self.report_out_dir else Path("biosample")
        out_dir.mkdir(parents=True, exist_ok=True)
        for f in out_dir.glob("*.txt"):
            f.unlink()

        # --account 付きで権限外サンプルがあった場合、その SSUB は fetch 側で落としてある。
        # 黙って減ると「DBLINK に記載が無い」と誤読されるので、input_samds の判定より先に出す。
        # （-b 単体＝--account 無しでは権限判定が走らないのでここは通らない）
        unauth_samds = getattr(self, "_biosample_unauth_samds", [])
        if unauth_samds:
            print(f"  [WARN] BioSample accession(s) not associated with this account: {', '.join(unauth_samds)}")
            unauth_ssubs = getattr(self, "_biosample_unauth_ssubs", [])
            if unauth_ssubs:
                print(f"  Submission TSV not generated for SSUB {', '.join(unauth_ssubs)}.")

        # 要件: DBLINK に biosample アクセッション番号が無い → メッセージ表示し生成しない
        input_samds = getattr(self, "_biosample_input_samds", set())
        if not input_samds:
            if unauth_samds:
                print("  No accessible BioSample accession left. Submission TSV not generated.")
            else:
                print("  No BioSample accession found in DBLINK. Submission TSV not generated.")
            return

        # 要件: biosample アクセッションが BioSample DB で見つからない → 同様
        found = getattr(self, "_biosample_found_samds", set())
        not_found = sorted(input_samds - found)
        if not_found:
            print(f"  [WARN] BioSample accession(s) not found in DB: {', '.join(not_found)}")
        if not self.biosample_ssub:
            print("  No corresponding SSUB found in BioSample DB. Submission TSV not generated.")
            return

        # ann↔bs が 1:1 のクリーンな SAMD のみ autofix 対象。曖昧（1 ann→複数 bs / 複数 ann→1 bs）は skip。
        clean_samds = getattr(self, "_biosample_clean_samds", None)
        if clean_samds is None:
            clean_samds = self._compute_clean_samds()
        ambiguous = sorted(input_samds - clean_samds)
        if ambiguous:
            n_amb = len(ambiguous)
            print(f"  Non-unique BioSample and annotation file relationship for {n_amb}/{len(input_samds)} BioSamples.")
            print(f"  BioSample autofix skipped for these {n_amb} sample{'' if n_amb == 1 else 's'}.")

        fixed_attributes, packages = load_biosample_definitions()
        from apps.ddbj.biosample.tsv import resolve_package_key, ordered_attributes

        # SAMD → (パッケージ定義の属性集合, 現行 BioSample 属性) を構築
        samd_pkg_attrs = {}
        samd_sample = {}
        for info in self.biosample_ssub.values():
            for s in info.get("samples", []):
                acc = s.get("accession_id")
                if not acc:
                    continue
                samd_sample[acc] = s
                pk = resolve_package_key(s.get("package"), s.get("env_package"), s.get("package_group"), packages)
                samd_pkg_attrs[acc] = {n for n, _ in ordered_attributes(pk, fixed_attributes, packages)} if pk else set()

        # ann_wins と判定された提案を SSUB TSV の上書き・追加値に変換（純粋ロジックは biosample.emit へ）。
        from apps.ddbj.biosample.emit import compute_overrides
        overrides, override_summary, added_summary, taxid_cleared = compute_overrides(
            self.all_interactive_proposals, clean_samds, samd_pkg_attrs, samd_sample)

        # ann→bs 上書き（競合で ann を採用）のサマリー。TSV に ann 値が反映されたことを明示。
        for samd, items in override_summary.items():
            detail = ", ".join(f"{a}: {v}" for a, v in sorted(items.items()))
            print(f"  annotation value applied to BioSample for {samd}: {detail}")
        for samd, items in added_summary.items():
            detail = ", ".join(f"{a}: {v}" for a, v in sorted(items.items()))
            print(f"  annotation-only values added to {samd}: {detail}")
        for samd in sorted(taxid_cleared):
            print(f"  {samd} taxonomy_id deleted to avoid organism autofix by taxonomy_id")

        nsub = self.nsub or "submission"
        for ssub_id, info in sorted(self.biosample_ssub.items()):
            samples = info.get("samples", [])
            tsv_text, package_key = build_ssub_tsv(samples, fixed_attributes, packages, overrides=overrides)
            if tsv_text is None:
                print(f"  [WARN] Package definition not resolved for SSUB {ssub_id}. Skipped.")
                continue
            # この SSUB のサンプルに override（ann→bs 上書き・属性追加）が1つでも適用されたか。
            # 適用ゼロ（skip／完全一致／追加なし）なら _unmodified を付ける。
            modified = any(overrides.get(s.get("accession_id")) for s in samples)
            suffix = "" if modified else "_unmodified"
            out_path = out_dir / f"{ssub_id}_{nsub}{suffix}.txt"
            out_path.write_text(tsv_text, encoding="utf-8", newline="\n")
            n = len(samples)
            print(f"  => {out_path}  (package={package_key}, {n} sample{'' if n == 1 else 's'})")
