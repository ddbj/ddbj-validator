import re
import json
from pathlib import Path
from collections import defaultdict

class ValidationReporter:
    def __init__(self, out_dir):
        self.out_dir = Path(out_dir) / "reports" if out_dir else Path(".") / "reports"
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.show_location = False

    def generate_report(self, jsonl_paths, print_console=True, start_time=None, end_time=None, version=None):
        """レポート出力の統括メソッド (JSONLストリーミング対応版)"""
        report_summary_path = self.out_dir / "validation_report_summary.txt"
        report_details_path = self.out_dir / "validation_report_details.txt"

        actual_sets = [p for p in jsonl_paths if "Submission_Cross_File" not in p]
        num_sets = len(actual_sets)

        if not jsonl_paths or num_sets == 0:
            self._write_empty_report(report_summary_path, report_details_path, print_console, start_time=start_time, end_time=end_time, version=version)
            return report_summary_path, report_details_path

        # ヘッダー情報の生成
        import datetime
        import time
        exec_date = datetime.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
        process_time_str = ""
        if start_time and end_time:
            diff = end_time - start_time
            if diff < 1:
                process_time_str = f"{diff:.2f} seconds"
            else:
                # timedelta は 秒未満も処理してくれる
                delta = datetime.timedelta(seconds=diff)
                # ミリ秒以下を切り捨てて見やすくする
                delta = delta - datetime.timedelta(microseconds=delta.microseconds)
                process_time_str = str(delta)
                if diff < 60:
                    process_time_str += " seconds"
        version_str = version if version else "unknown"
            
        header_info = (
            f"Validation Date: {exec_date}\n"
            f"Process Time: {process_time_str}\n"
            f"Version: {version_str}\n"
        )

        # レポートファイルを初期化 (上書き)
        set_str = "1 file set" if num_sets == 1 else f"{num_sets} file sets"
        with open(report_summary_path, "w", encoding="utf-8") as fs, open(report_details_path, "w", encoding="utf-8") as fd:
            fs.write(f"\n=== Validation Summary ({set_str}) ===\n")
            fs.write(header_info)
            fd.write(f"\n=== Validation Details ({set_str}) ===\n")
            fd.write(header_info)

        set_idx = 1
        for j_path in jsonl_paths:
            is_cross = "Submission_Cross_File" in str(j_path)
            self._process_and_append_report(j_path, set_idx, report_summary_path, report_details_path, print_console, is_cross)
            if not is_cross:
                set_idx += 1

        return report_summary_path, report_details_path

    def _process_and_append_report(self, jsonl_path, set_idx, sum_path, det_path, print_console, is_cross):
        detailed_lines = {"FATAL": [], "ERROR": [], "WARNING": [], "INFO": [], "AUTO-CLEANUP": []}
        summary_stats = {} # key -> {"res": res, "items": []}
        summary_messages = {} # key -> msg

        base_group = ""

        try:
            with open(jsonl_path, "r", encoding="utf-8") as f:
                for line in f:
                    rec = json.loads(line)
                    if rec["type"] == "result":
                        res = rec["data"]
                        
                        if not base_group:
                            filename = str(res.get('file', ''))
                            if is_cross or filename in ["ALL", "ALL_SETS", "Submission (Cross-File)"]:
                                base_group = "Submission (across files)"
                            else:
                                base_group = Path(filename).stem
                                if base_group.endswith('.ann'):
                                    base_group = base_group[:-4]

                        # 1. Summaryキーの構築 (カウントの単位として使用)
                        summary_key = self._format_summary_key(res)
                        if summary_key not in summary_stats:
                            summary_stats[summary_key] = {"res": res, "items": []}
                            
                            msg = res.get('message', '')
                            if res.get('line_number') is None and msg.startswith("Line "):
                                msg = re.sub(r"^Line \d+:\s*", "", msg)
                            summary_messages[summary_key] = msg.split('\n')[0]
                            
                        summary_stats[summary_key]["items"].append(res)

                        # 2. Details の構築
                        level = "AUTO-CLEANUP" if res.get('is_cleanup') else res.get('level', 'WARNING').upper()
                        if level not in detailed_lines:
                            detailed_lines[level] = []

                        detailed_line = self._format_detail_line(res)
                        detailed_lines[level].append(detailed_line)

        except FileNotFoundError:
            return

        if not base_group:
            return

        # ==========================================
        # Details の書き出し (逐次 Append)
        # ==========================================
        with open(det_path, "a", encoding="utf-8") as fd:
            header = f"\n0. {base_group}\n" if is_cross else f"\n{set_idx}. {base_group}\n"
            fd.write(header)
            
            is_first_group = True
            for level_name in ["FATAL", "ERROR", "WARNING", "INFO", "AUTO-CLEANUP"]:
                if detailed_lines.get(level_name):
                    if not is_first_group:
                        fd.write("\n")
                    fd.write(f"[ {level_name} ]\n")
                    for line in sorted(detailed_lines[level_name]):
                        fd.write(f"{line}\n")
                    is_first_group = False

        # ==========================================
        # Summary の書き出し (逐次 Append)
        # ==========================================
        sum_text = ""
        header = f"\n0. {base_group}\n" if is_cross else f"\n{set_idx}. {base_group}\n"
        sum_text += header
        
        level_groups = {"FATAL": [], "ERROR": [], "WARNING": [], "INFO": [], "AUTO-CLEANUP": []}
        for key, stats in summary_stats.items():
            first_res = stats["res"]
            level = "AUTO-CLEANUP" if first_res.get('is_cleanup') else first_res.get('level', 'WARNING').upper()
            if level not in level_groups:
                level_groups[level] = []
            level_groups[level].append((key, stats["items"]))

        is_first_sum_group = True
        for level_name in ["FATAL", "ERROR", "WARNING", "INFO", "AUTO-CLEANUP"]:
            if level_groups.get(level_name):
                # エラーレベルが変わる時（WARNING -> ERRORなど）だけ空行を入れる
                if not is_first_sum_group:
                    sum_text += "\n"
                sum_text += f"[ {level_name} ]\n"
                
                for key, results_list in sorted(level_groups[level_name]):
                    num_items = len(results_list)
                    first_res = results_list[0]                               
            
                    e_val = first_res.get('entry', '')
                    f_type = first_res.get('feature_type', '')
                    t_val = first_res.get('target', '')
                    q_val = first_res.get('qualifier', '')
                    
                    if is_cross:
                        label = "submission" if num_items == 1 else "submissions"
                        count_str = f"{num_items} {label}"
                    elif e_val == "ALL" or t_val == "file":
                        label = "file" if num_items == 1 else "files"
                        count_str = f"{num_items} {label}"
                    elif t_val == "sequence" or f_type == "sequence":
                        label = "sequence" if num_items == 1 else "sequences"
                        count_str = f"{num_items} {label}"
                    elif t_val == "file/format":
                        parts = []
                        parts.append(f"{num_items} line" if num_items == 1 else f"{num_items} lines")
                        count_str = ", ".join(parts)
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

                    msg = summary_messages[key]
                    if num_items > 1:
                        msg = re.sub(r"\(Found:\s*(.*?)\)", r"(Example: \1)", msg)

                    sum_text += f"{key}: {count_str}: {msg}\n"
                
                is_first_sum_group = False

        with open(sum_path, "a", encoding="utf-8") as fs:
            fs.write(sum_text)
            
        if print_console:
            print(sum_text)
            
    def _format_detail_line(self, res):
        line_val = res.get('line_number')
        msg = res.get('message', '')
        
        if line_val is None:
            line_match = re.search(r"^Line (\d+):\s*(.*)", msg)
            if line_match:
                line_val = line_match.group(1)
                msg = line_match.group(2)
        
        if line_val:
            line_str = f"Line[{line_val}]"
        else:
            e_val = res.get('entry', '')
            t_val = res.get('target', '')
            f_type = res.get('feature_type', '')
            
            if e_val == "ALL" or t_val in ("file", "file/format", "sequence") or f_type == "sequence":
                line_str = "[FILE]"
            else:
                line_str = "[ENTRY]"
        
        rule_id = res.get('rule', 'UNKNOWN')
        level_map = {"WARNING": "WAR", "ERROR": "ERR", "FATAL": "FAT", "INFO": "INFO"}            
        level_upper = res.get('level', 'WARNING').upper()
        short_level = level_map.get(level_upper, "WAR")
                    
        parts = [rule_id, short_level]

        parts.extend([res.get('entry', ''), res.get('feature_type', "") or res.get('target', "")])
        if self.show_location and res.get('location'): parts.append(res.get('location'))
        parts.extend([res.get('qualifier', ''), line_str, msg])

        return ":".join(str(p) for p in parts if p != "")

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
        return ":".join(str(p) for p in parts)

    def _write_empty_report(self, sum_path, det_path, print_console, start_time=None, end_time=None, version=None):
        import datetime
        import time
        exec_date = datetime.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
        process_time_str = ""
        if start_time and end_time:
            diff = end_time - start_time
            if diff < 1:
                process_time_str = f"{diff:.2f} seconds"
            else:
                delta = datetime.timedelta(seconds=diff)
                delta = delta - datetime.timedelta(microseconds=delta.microseconds)
                process_time_str = str(delta)
                if diff < 60:
                    process_time_str += " seconds"
        version_str = version if version else "unknown"
            
        header_info = (
            f"Validation Date: {exec_date}\n"
            f"Process Time: {process_time_str}\n"
            f"Version: {version_str}\n"
        )

        empty_msg_sum = f"\n=== Validation Summary (0 file sets) ===\n{header_info}No errors found.\n"
        empty_msg_det = f"\n=== Validation Details (0 file sets) ===\n{header_info}No errors found.\n"
        
        try:
            with open(det_path, "w", encoding="utf-8") as f:
                f.write(empty_msg_det)
        except Exception:
            pass
        try:
            with open(sum_path, "w", encoding="utf-8") as f:
                f.write(empty_msg_sum)
        except Exception:
            pass
        if print_console:
            print(empty_msg_sum, end="")
