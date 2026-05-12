from pathlib import Path
from collections import defaultdict

def review_and_approve_proposals(all_proposals, force_fix=False, out_dir=None):
    """
    全提案を集約し、target (修正対象項目) ごとにサマリーを表示。
    出力と同じ形式でディレクトリにサマリーファイルを保存し、一括または個別の承認を求める。
    """
    if not all_proposals:
        return []

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
        
        change_key = (str(p.get("old", "")), str(p.get("new", "")), source_db)
        
        target_dict = summary[target][file_set][change_key]
        target_dict["target_level"] = p.get("target_level", "qualifier")
        target_dict["positions"].extend(p.get("positions", []))
        if rule_id:
            target_dict["rules"].add(rule_id)

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
                
                target_lines.append(f"    {count_str}: '{old_val}' -> '{new_val}'{source_str}{rule_str}")
        
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
        return all_proposals

    # 対話モード
    while True:
        ans = input("\nAction: [a] Apply all auto-fixes, [i] Interactive, [q] Quit/Skip all? ").strip().lower()
        if ans in ('a', 'all'):
            return all_proposals
        elif ans in ('q', 'quit'):
            print("  => Skipped auto-fix updates.")
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
        while True:
            sub_ans = input(f"  => Apply auto-fixes for Target [{target}]? (y/n): ").strip().lower()
            if sub_ans in ('y', 'yes'):
                approved_proposals.extend(proposals_by_target[target])
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