from pathlib import Path
from collections import defaultdict


def _is_bs_sync(p):
    """BioSample 値由来の同期提案か（source_db に SAMD アクセッションが入る）。"""
    return str(p.get("source_db", "")).startswith("SAMD")


def review_and_approve_proposals(all_proposals, force_fix=False, out_dir=None, biosample_mode=False, biosample_clean_samds=None):
    """
    全提案を集約し、target (修正対象項目) ごとにサマリーを表示。
    出力と同じ形式でディレクトリにサマリーファイルを保存し、一括または個別の承認を求める。

    biosample_mode (= -b かつ単一 biosample) の場合、BioSample→ann 同期提案を N としたとき
    「ann 値で BioSample を更新するか」を追加で質問し、各提案に bs_decision を付与する:
      - bs_wins  : BioSample が正（ann を修正、SSUB TSV は BioSample 値）
      - ann_wins : ann が正（ann は変更せず、SSUB TSV は ann 値で上書き）
      - leave    : どちらも変更しない（両方要確認）
    ※ ユーザ向け（-b なし）の挙動は一切変わらない。
    """
    if not all_proposals:
        return []

    # biosample_mode では BioSample 同期提案の決定を leave で初期化（後段で上書き）
    # ann→bs フォローアップは ann↔bs が 1:1 のクリーンな SAMD の提案のみ対象。
    clean_samds = biosample_clean_samds if biosample_clean_samds is not None else None

    def _bs_sync_clean(p):
        return _is_bs_sync(p) and (clean_samds is None or p.get("source_db") in clean_samds)

    if biosample_mode:
        for p in all_proposals:
            if _bs_sync_clean(p):
                p.setdefault("bs_decision", "leave")

    summary = defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: {"target_level": "qualifier", "positions": [], "rules": set()})))

    target_dirs = set()
    for p in all_proposals:
        path_obj = Path(p["ann_path"])
        target_dirs.add(path_obj.parent)
        
        base_group = path_obj.stem
        if base_group.endswith('.ann'):
            base_group = Path(base_group).stem
            
        file_set = base_group
        
        target = p.get("target", "unknown")
        rule_id = p.get("rule", "UNKNOWN_RULE")
        source_db = p.get("source_db", "")
        
        change_key = (str(p.get("old_value", "")), str(p.get("new_value", "")), source_db)
        
        target_dict = summary[target][file_set][change_key]
        target_dict["target_level"] = p.get("target_level", "qualifier")
        target_dict["positions"].extend(p.get("positions", []))
        if rule_id:
            target_dict["rules"].add(rule_id)
        if p.get("bs_addition"):
            target_dict["bs_addition"] = True

    # --- サマリーテキストの構築とTargetごとのブロック保存 ---
    target_text_blocks = {}
    out_lines = ["\n=== Auto-Fix Confirmation ==="]
    
    for target in sorted(summary.keys()):
        target_lines = [f"[ Target: {target} ]"]
        for file_set, changes in sorted(summary[target].items()):
            target_lines.append(f"  {file_set}")
            for (old_val, new_val, source_db), stats in sorted(changes.items()):
                t_level = stats["target_level"]
                positions = stats["positions"]
                rules = stats["rules"]
                
                num_fields = len(positions)
                unique_entries = {pos["entry"] for pos in positions}
                unique_features = {(pos["entry"], pos["feature_id"]) for pos in positions}
                
                e_len, f_len = len(unique_entries), len(unique_features)
                e_label = "entry" if e_len == 1 else "entries"
                f_label = "feature" if f_len == 1 else "features"
                
                # --- target_level に基づく動的フォーマット (スマート化) ---
                if t_level == "field":
                    count_str = f"{num_fields} field{'s' if num_fields != 1 else ''}"
                elif t_level in ("feature", "location"):
                    count_str = f"{e_len} {e_label}, {f_len} {f_label}"
                elif t_level == "qualifier":
                    q_label = "qualifier" if num_fields == 1 else "qualifiers"
                    count_str = f"{e_len} {e_label}, {f_len} {f_label}, {num_fields} {q_label}"
                else:
                    count_str = f"{e_len} {e_label}"

                source_str = f" ({source_db})" if source_db else ""
                rule_str = f" [Rule: {', '.join(sorted(rules))}]" if rules and list(rules) != ["UNKNOWN_RULE"] else ""

                # ann限定追加は new_value が空なので「(add to BioSample)」表記にする
                if stats.get("bs_addition"):
                    change_str = f"'{old_val}' (add to BioSample)"
                else:
                    change_str = f"'{old_val}' -> '{new_val}'"
                target_lines.append(f"    {count_str}: {change_str}{source_str}{rule_str}")
        
        target_text_blocks[target] = "\n".join(target_lines)
        out_lines.append("\n" + target_text_blocks[target])

    summary_text = "\n".join(out_lines)
    print(summary_text)

    # --- 対象のディレクトリに標準出力と同じ形式のログを書き出す ---
    summary_filename = "autofix_confirmation_summary.txt"
    
    if out_dir:
        reports_dir = Path(out_dir) / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        summary_file = reports_dir / summary_filename
        
        with open(summary_file, "w", encoding="utf-8") as f:
            f.write(summary_text.lstrip() + "\n")
        print(f"\n  => Confirmation summary saved: {summary_file}")
    else:
        for d in target_dirs:
            reports_dir = d / "reports"
            reports_dir.mkdir(parents=True, exist_ok=True)
            summary_file = reports_dir / summary_filename
            
            with open(summary_file, "w", encoding="utf-8") as f:
                f.write(summary_text.lstrip() + "\n")
                
        if target_dirs:
            dir_path = str(list(target_dirs)[0] / "reports" / summary_filename)
            print(f"\n  => Confirmation summary saved: {dir_path}")

    if force_fix:
        print("  => Applying all auto-fixes (--force-fix)")
        if biosample_mode:
            for p in all_proposals:
                if _bs_sync_clean(p):
                    p["bs_decision"] = "bs_wins"
        return all_proposals

    # 対話モード（トップメニューは外部ユーザ・-b 共通。ann->BioSample の選択は interactive の対象 target でのみ提示）
    while True:
        ans = input("\nAction: [a] Apply all auto-fixes, [i] Interactive, [q] Quit/Skip all? ").strip().lower()
        if ans in ('a', 'all'):
            # [a] は BioSample 値で ann を修正（bs_wins）。SSUB TSV は BioSample 現行値のまま。
            if biosample_mode:
                for p in all_proposals:
                    if _bs_sync_clean(p):
                        p["bs_decision"] = "bs_wins"
            return all_proposals
        elif ans in ('q', 'quit'):
            print("  => Skipped auto-fix updates.")
            # biosample_mode: 全て leave のまま（ann も BioSample も変更しない）
            return []
        elif ans in ('i', 'interactive'):
            break
            
    # インタラクティブ処理
    print("\n=== Interactive Mode ===")
    approved_proposals = []
    
    proposals_by_target = defaultdict(list)
    for p in all_proposals:
        target = p.get("target", "unknown")
        proposals_by_target[target].append(p)
        
    for target in sorted(proposals_by_target.keys()):
        print(f"\n{target_text_blocks[target]}")
        target_proposals = proposals_by_target[target]
        bs_sync_in_target = [p for p in target_proposals if _bs_sync_clean(p)]

        # -b キュレータ ＆ BioSample 同期(clean)を含む target は、1 プロンプトで方向を選ばせる（2 ステップ廃止）
        if biosample_mode and bs_sync_in_target:
            non_bs = [p for p in target_proposals if not _bs_sync_clean(p)]
            addition_only = all(p.get("bs_addition") for p in bs_sync_in_target)
            if addition_only:
                # ann にしかない値の BioSample への追加。BS→ann 方向は無いので [b]追加/[n]skip の2択。
                while True:
                    sub_ans = input(
                        f"  => [{target}]: [b] add to BioSample (annotation value), [n] skip? "
                    ).strip().lower()
                    if sub_ans in ('b',):
                        approved_proposals.extend(non_bs)
                        for p in bs_sync_in_target:
                            p["bs_decision"] = "ann_wins"        # BioSample に追加
                        break
                    elif sub_ans in ('n', 'no'):
                        for p in bs_sync_in_target:
                            p["bs_decision"] = "leave"
                        break
                continue
            while True:
                sub_ans = input(
                    f"  => [{target}]: [y] BioSample -> annotation, [b] annotation -> BioSample, [n] skip? "
                ).strip().lower()
                if sub_ans in ('y', 'yes'):
                    approved_proposals.extend(target_proposals)  # ann を BioSample 値で修正
                    for p in bs_sync_in_target:
                        p["bs_decision"] = "bs_wins"
                    break
                elif sub_ans in ('b',):
                    approved_proposals.extend(non_bs)            # 非 BioSample の autofix は適用
                    for p in bs_sync_in_target:
                        p["bs_decision"] = "ann_wins"            # ann 値で BioSample(TSV) を更新
                    break
                elif sub_ans in ('n', 'no'):
                    for p in bs_sync_in_target:
                        p["bs_decision"] = "leave"               # どちらも変更しない
                    break
            continue

        # 通常（外部ユーザ／非 BioSample target）は従来どおり y/n
        while True:
            sub_ans = input(f"  => Apply auto-fixes for Target [{target}]? (y/n): ").strip().lower()
            if sub_ans in ('y', 'yes'):
                approved_proposals.extend(target_proposals)
                break
            elif sub_ans in ('n', 'no'):
                break

    if not approved_proposals:
        print("\n  => Skipped all auto-fix updates.")
    else:
        applied_targets_count = len(set(p.get("target", "unknown") for p in approved_proposals))
        print(f"\n  => Applied auto-fixes for {applied_targets_count} targets.")

    return approved_proposals

def apply_proposals(proposals):
    """
    承認された提案から、実際の変更指示データ（updates）を抽出してフラットなリストにする。
    """
    return [update for p in proposals for update in p.get("updates", [])]