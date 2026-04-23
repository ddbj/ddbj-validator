import re
from pathlib import Path
from collections import defaultdict

class ValidationReporter:
    def __init__(self, out_dir):
        self.out_dir = Path(out_dir) if out_dir else Path(".")
        self.show_location = False  

    def generate_report(self, all_results, print_console=True):
        """レポート出力の統括メソッド"""
        report_summary_path = self.out_dir / "validation_report_summary.txt"
        report_details_path = self.out_dir / "validation_report_details.txt"

        if not all_results:
            self._write_empty_report(report_summary_path, report_details_path, print_console)
            return report_summary_path, report_details_path

        data = self._process_results(all_results)
        self._write_details(report_details_path, data)
        self._write_summary(report_summary_path, data, print_console)

        return report_summary_path, report_details_path

    # ==========================================
    # 内部処理メソッド
    # ==========================================
    def _process_results(self, all_results):
        """全件の検証結果をパースし、出力用にグループ化する"""
        nsub_set = set()
        base_set = set()
        
        for res in all_results:
            full_path = str(res.get('full_path', ''))
            filename = str(res.get('file', ''))
            
            # full_pathが空の場合、filename(fileキー)の文字列からNSUB番号を探す
            search_target = full_path if full_path else filename
            match = re.search(r'(NSUB\d+)', search_target)
            
            res['nsub_id'] = match.group(1) if match else "Unknown_NSUB"
            if res['nsub_id'] != "Unknown_NSUB":
                nsub_set.add(res['nsub_id'])

            if filename in ["ALL", "ALL_SETS", "Submission (Cross-File)"]:
                res['base_group'] = "Submission (Cross-File)"
            else:
                base_name = Path(filename).stem
                if base_name.endswith('.ann'):
                    base_name = Path(base_name).stem
                res['base_group'] = base_name
                base_set.add(base_name)

        show_nsub = len(nsub_set) > 1

        detailed_lines = defaultdict(lambda: defaultdict(list))
        # 件数(int)ではなく、結果の辞書をそのまま保持する
        summary_results = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
        summary_messages = defaultdict(lambda: defaultdict(dict))

        for res in all_results:
            nsub_id = res['nsub_id']
            group_name = res['base_group']
            
            # details出力用にエラーレベルとフォーマット済み文字列をセットで保持する
            detailed_line = self._format_detail_line(res, show_nsub)
            if res.get('is_cleanup'):
                level = "AUTO-CLEANUP"
            else:
                level = res.get('level', 'WARNING').upper()
            detailed_lines[nsub_id][group_name].append((level, detailed_line))

            summary_key = self._format_summary_key(res)
            # keyごとに発生したエラー(res)をリストに蓄積
            summary_results[nsub_id][group_name][summary_key].append(res)
            
            if summary_key not in summary_messages[nsub_id][group_name]:
                msg = res.get('message', '')
                if res.get('line_number') is None and msg.startswith("Line "):
                    msg = re.sub(r"^Line \d+:\s*", "", msg)
                summary_messages[nsub_id][group_name][summary_key] = msg.split('\n')[0]

        return {
            'num_nsubs': len(nsub_set),
            'num_sets': len(base_set),
            'show_nsub': show_nsub,
            'detailed_lines': detailed_lines,
            'summary_results': summary_results,
            'summary_messages': summary_messages
        }

    def _format_detail_line(self, res, show_nsub):
        line_val = res.get('line_number')
        msg = res.get('message', '')
        
        if line_val is None:
            line_match = re.search(r"^Line (\d+):\s*(.*)", msg)
            if line_match:
                line_val = line_match.group(1)
                msg = line_match.group(2)
        
        # 行番号がない場合の表記を [FILE] または [ENTRY] に変更
        if line_val:
            line_str = f"Line[{line_val}]"
        else:
            e_val = res.get('entry', '')
            t_val = res.get('target', '')
            f_type = res.get('feature_type', '')
            
            # ALL指定、ターゲットがfile/sequence系なら [FILE]、それ以外は [ENTRY]
            if e_val == "ALL" or t_val in ("file", "file/format", "sequence") or f_type == "sequence":
                line_str = "[FILE]"
            else:
                line_str = "[ENTRY]"
        
        rule_id = res.get('rule', 'UNKNOWN')
        level_map = {"WARNING": "WAR", "ERROR": "ERR", "FATAL": "FAT", "INFO": "INFO"}            
        level_upper = res.get('level', 'WARNING').upper()
        short_level = level_map.get(level_upper, "WAR")
                    
        parts = [rule_id, short_level]

        if show_nsub and res.get('nsub_id') != "Unknown_NSUB":
            parts.append(res.get('nsub_id', ''))
        
        parts.extend([res.get('entry', ''), res.get('feature_type', "") or res.get('target', "")])
        if self.show_location and res.get('location'): parts.append(res.get('location'))
        parts.extend([res.get('qualifier', ''), line_str, msg])

        return ":".join(p for p in parts if p != "")

    def _format_summary_key(self, res):
        rule_id = res.get('rule', 'UNKNOWN')
        level_map = {"WARNING": "WAR", "ERROR": "ERR", "FATAL": "FAT", "INFO": "INFO"}
        level_upper = res.get('level', 'WARNING').upper()
        short_level = level_map.get(level_upper, "WAR")
        
        parts = [rule_id, short_level]
            
        feat = res.get('feature_type', "") or res.get('target', "")
        if feat: parts.append(feat)
        qual = res.get('qualifier', '')
        if qual: parts.append(qual)
        return ":".join(parts)

    def _write_details(self, path, data):
        num_nsubs = max(data['num_nsubs'], 1)
        num_sets = data['num_sets']
        detailed_lines = data['detailed_lines']
        
        try:
            with open(path, "w", encoding="utf-8") as f:
                # 見出しの単複判定
                sub_str = "1 submission" if num_nsubs == 1 else f"{num_nsubs} submissions"
                set_str = "1 file set" if num_sets == 1 else f"{num_sets} file sets"
                f.write(f"\n=== Validation Details ({sub_str}, {set_str}) ===\n")
                
                nsub_idx = 1
                for nid in sorted(detailed_lines.keys()):
                    if nid != "Unknown_NSUB":
                        f.write(f"\n{nsub_idx}. {nid}\n")
                    
                    set_idx = 1
                    for gname in sorted(detailed_lines[nid].keys()):
                        if gname == "Submission (Cross-File)":
                            f.write(f"\n{gname}\n")
                        else:
                            header = f"\n{nsub_idx}-{set_idx}. {gname}\n" if nid != "Unknown_NSUB" else f"\n{set_idx}. {gname}\n"
                            f.write(header)
                            set_idx += 1
                            
                        level_groups = {"FATAL": [], "ERROR": [], "WARNING": [], "INFO": [], "AUTO-CLEANUP": []}
                        for lvl, line in detailed_lines[nid][gname]:
                            if lvl not in level_groups:
                                level_groups[lvl] = []
                            level_groups[lvl].append(line)

                        # 深刻度が高い順にセクションを作成し、左寄せ＆グループ間に空行を入れる
                        is_first_group = True
                        for level_name in ["FATAL", "ERROR", "WARNING", "INFO", "AUTO-CLEANUP"]:
                            if level_groups.get(level_name):
                                if not is_first_group:
                                    f.write("\n")  # グループ間の空行
                                f.write(f"[ {level_name} ]\n")
                                for line in sorted(level_groups[level_name]):
                                    f.write(f"{line}\n")
                                is_first_group = False
                                    
                    if nid != "Unknown_NSUB":
                        nsub_idx += 1
                        
        except PermissionError:
            import sys
            print(f"[WARN] Permission denied: Cannot write to '{path}'.", file=sys.stderr)
        except Exception as e:
            import sys
            print(f"[WARN] Cannot write to '{path}': {e}", file=sys.stderr)

    def _write_summary(self, path, data, print_console):
        num_nsubs = max(data['num_nsubs'], 1)
        num_sets = data['num_sets']
        summary_results = data['summary_results']
        summary_messages = data['summary_messages']
        
        file_obj = None
        try:
            file_obj = open(path, "w", encoding="utf-8")
        except PermissionError:
            import sys
            print(f"[WARN] Permission denied: Cannot write to '{path}'. Outputting to console only.", file=sys.stderr)
        except Exception as e:
            import sys
            print(f"[WARN] Cannot write to '{path}': {e}", file=sys.stderr)
            
        def write_out(text):
            if print_console: print(text, end="")
            if file_obj: file_obj.write(text)

        try:
            # 見出しの単複判定
            sub_str = "1 submission" if num_nsubs == 1 else f"{num_nsubs} submissions"
            set_str = "1 file set" if num_sets == 1 else f"{num_sets} file sets"
            write_out(f"\n=== Validation Summary ({sub_str}, {set_str}) ===\n")
            
            nsub_idx = 1
            for nid in sorted(summary_results.keys()):
                if nid != "Unknown_NSUB":
                    write_out(f"\n{nsub_idx}. {nid}\n")
                
                set_idx = 1
                for gname in sorted(summary_results[nid].keys()):
                    if gname == "Submission (Cross-File)":
                        write_out(f"\n{gname}\n")
                    else:
                        header = f"\n{nsub_idx}-{set_idx}. {gname}\n" if nid != "Unknown_NSUB" else f"\n{set_idx}. {gname}\n"
                        write_out(header)
                        set_idx += 1
                        
                    # 重大度 (Severity level) でグループ化
                    level_groups = {"FATAL": [], "ERROR": [], "WARNING": [], "INFO": [], "AUTO-CLEANUP": []}
                    for key, results_list in summary_results[nid][gname].items():
                        first_res = results_list[0]
                        if first_res.get('is_cleanup'):
                            level = "AUTO-CLEANUP"
                        else:
                            level = first_res.get('level', 'WARNING').upper()
                                
                        if level not in level_groups:
                            level_groups[level] = []
                        level_groups[level].append((key, results_list))

                    # 深刻度が高い順にセクションを作成
                    for level_name in ["FATAL", "ERROR", "WARNING", "INFO", "AUTO-CLEANUP"]:
                        if level_name in level_groups and level_groups[level_name]:
                            write_out(f"[ {level_name} ]\n")
                            
                            for key, results_list in sorted(level_groups[level_name]):
                                num_items = len(results_list)
                                first_res = results_list[0]                               
                                e_val = first_res.get('entry', '')
                                f_type = first_res.get('feature_type', '')
                                t_val = first_res.get('target', '')
                                q_val = first_res.get('qualifier', '')
                                
                                # 1. 複数ファイル横断チェック (Submission レベル)
                                if gname == "Submission (Cross-File)":
                                    label = "submission" if num_items == 1 else "submissions"
                                    count_str = f"{num_items} {label}"
                                
                                # 2. ファイル単位チェックの判定 (File レベル)
                                elif e_val == "ALL" or t_val == "file":
                                    label = "file" if num_items == 1 else "files"
                                    count_str = f"{num_items} {label}"
                                
                                # 3. 配列(Sequence)自体のエラー (SEQルールなど)
                                elif t_val == "sequence" or f_type == "sequence":
                                    label = "sequence" if num_items == 1 else "sequences"
                                    count_str = f"{num_items} {label}"

                                # 4. file/format エラーの場合は純粋な「発生件数 (items)」を出す
                                elif t_val == "file/format":
                                    parts = []
                                    parts.append(f"{num_items} line" if num_items == 1 else f"{num_items} lines")
                                    count_str = ", ".join(parts)
                                
                                # 5. 通常のエントリー / Feature / Qualifier の判定
                                else:
                                    unique_entries = len(set(r.get('entry') for r in results_list if r.get('entry') and r.get('entry') != "ALL"))
                                    unique_features = len(set((r.get('entry'), r.get('line_number')) for r in results_list if r.get('line_number') is not None))
                                    
                                    parts = []
                                    if unique_entries > 0:
                                        parts.append(f"{unique_entries} entry" if unique_entries == 1 else f"{unique_entries} entries")
                                     
                                    feat_count = unique_features if unique_features > 0 else num_items
                                    parts.append(f"{feat_count} feature" if feat_count == 1 else f"{feat_count} features")
                                    
                                    if q_val:
                                        parts.append(f"{num_items} qualifier" if num_items == 1 else f"{num_items} qualifiers")
                                    elif num_items > feat_count:
                                        rule_id = first_res.get('rule', '')
                                        if rule_id in ("AXS6030", "AXS6060"):
                                            parts.append(f"{num_items} codons")
                                        else:
                                            parts.append(f"{num_items} occurrences")
                                        
                                    count_str = ", ".join(parts)

                                msg = summary_messages[nid][gname][key]
                                if num_items > 1:
                                    msg = re.sub(r"\(Found:\s*(.*?)\)", r"(Example: \1)", msg)

                                write_out(f"{key}: {count_str}: {msg}\n")
                            write_out("\n")
                            
                if nid != "Unknown_NSUB":
                    nsub_idx += 1
        finally:
            if file_obj:
                file_obj.close()
                                        
    def _write_empty_report(self, sum_path, det_path, print_console):
        empty_msg = "\n=== Validation Summary (0 file sets) ===\nNo errors found.\n"
        
        try:
            with open(det_path, "w", encoding="utf-8") as f:
                f.write("=== Validation Details (0 file sets) ===\nNo errors found.\n")
        except Exception:
            pass

        try:
            with open(sum_path, "w", encoding="utf-8") as f:
                f.write(empty_msg)
        except Exception:
            pass

        if print_console:
            print(empty_msg, end="")