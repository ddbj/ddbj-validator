import re
import json
import logging
from pathlib import Path
from collections import defaultdict

logger = logging.getLogger(__name__)

# --common-only のときヘッダーに足す行（エントリ部・配列を検証していないことを明示する）
_SCOPE_LINES = {
    "common_only": "Scope: COMMON only (entries and sequences were not validated)\n",
    "common_source": "Scope: COMMON and source features (other features and sequences were not validated)\n",
}


def _scope_line(scope):
    return _SCOPE_LINES.get(scope, "") if scope else ""


# NCBI API に届かなかったときにヘッダーに足す行の頭。E2E ハーネスはこの印でその実行の不一致を
# 「NCBI に届かなかった」に分ける（apps/ddbj/tests/run_tests.py）
NCBI_UNREACHABLE_MARK = "NCBI API: unreachable"


def _ncbi_line(ncbi_failed):
    """NCBI API に届かなかったリクエストがあればヘッダーに 1 行出す。検証エラーではない。"""
    if not ncbi_failed:
        return ""
    req = "request" if ncbi_failed == 1 else "requests"
    return (f"{NCBI_UNREACHABLE_MARK} ({ncbi_failed} {req} failed after retries). "
            f"Checks that use NCBI were not fully done; run again later.\n")


def read_submission_types(jsonl_paths):
    """ワーカー JSONL の submission_type レコード（--common-only のとき）をファイル順に返す。"""
    out = []
    for jsonl_path in jsonl_paths:
        try:
            with open(jsonl_path, "r", encoding="utf-8") as f:
                for line in f:
                    rec = json.loads(line)
                    if rec.get("type") == "submission_type":
                        out.append(rec["data"])
        except FileNotFoundError:
            continue
    return out


def overall_submission_type(types):
    """全ファイルで同じ type ならそれを、ばらつく・無いなら None を返す。"""
    vals = {t.get("submission_type") for t in types}
    return vals.pop() if len(vals) == 1 else None


def _submission_type_lines(types):
    """テキストレポートのヘッダーに足す行。複数ファイルならファイルごとに 1 行。"""
    lines = ""
    for t in types:
        st = t.get("submission_type") or "not declared"
        if t.get("candidates"):
            st += f" (keywords suggest: {', '.join(t['candidates'])})"
        suffix = f" [{t.get('file')}]" if len(types) > 1 else ""
        lines += f"Submission Type: {st}{suffix}\n"
    return lines


class ValidationReporter:
    def __init__(self, out_dir):
        self.out_dir = Path(out_dir) / "reports" if out_dir else Path(".") / "reports"
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.show_location = False

    def write_json_report(self, jsonl_paths, version=None, scope=None, ncbi_failed=0):
        """JSON レポート出力（--json）。biosample/bioproject/dra と揃えたスキーマ＋ddbj 固有粒度。

        messages[] に entry/feature_type/qualifier/location/line_number を含める（ddbj は feature/entry 単位）。
        auto-cleanup（is_cleanup）は level="auto-cleanup" として error にカウントしない。
        """
        counts = {"error": 0, "warning": 0, "info": 0, "auto-cleanup": 0}
        messages = []
        for jsonl_path in jsonl_paths:
            try:
                with open(jsonl_path, "r", encoding="utf-8") as f:
                    for line in f:
                        rec = json.loads(line)
                        if rec.get("type") != "result":
                            continue
                        res = rec["data"]
                        level = "auto-cleanup" if res.get("is_cleanup") else str(res.get("level", "warning")).lower()
                        counts[level] = counts.get(level, 0) + 1
                        messages.append({
                            "id": res.get("rule"),
                            "level": level,
                            "message": res.get("message", ""),
                            "target": res.get("target", ""),
                            "file": res.get("file"),
                            "entry": res.get("entry"),
                            "feature_type": res.get("feature_type"),
                            "qualifier": res.get("qualifier"),
                            "location": res.get("location"),
                            "line_number": res.get("line_number"),
                            "external": res.get("internal_ignore", False),
                        })
            except FileNotFoundError:
                continue
        # --common-only のときだけ submission type を返す（COMMON の申告から決まる）
        types = read_submission_types(jsonl_paths)
        payload = {
            "version": version,
            # --common-only のときだけ "common_only"（エントリ部・配列は未検証であることを示す）
            **({"scope": scope} if scope else {}),
            **({"submission_type": overall_submission_type(types), "submission_types": types} if types else {}),
            # NCBI API に届かなかったときだけ。検証エラーではないので validity には影響しない
            **({"ncbi_unreachable": {"failed_requests": ncbi_failed}} if ncbi_failed else {}),
            "validity": counts.get("error", 0) == 0,
            "stats": {"error": counts.get("error", 0), "warning": counts.get("warning", 0),
                      "info": counts.get("info", 0), "auto-cleanup": counts.get("auto-cleanup", 0)},
            "messages": messages,
        }
        out_path = self.out_dir / "validation_report.json"
        out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return out_path

    def generate_report(self, jsonl_paths, print_console=True, start_time=None, end_time=None, version=None, scope=None, ncbi_failed=0,
                        table=False):
        """レポート出力の統括メソッド (JSONLストリーミング対応版)"""
        report_summary_path = self.out_dir / "validation_report_summary.txt"
        report_details_path = self.out_dir / "validation_report_details.txt"

        actual_sets = [p for p in jsonl_paths if "Submission_Cross_File" not in p]
        num_sets = len(actual_sets)

        if not jsonl_paths or num_sets == 0:
            self._write_empty_report(report_summary_path, report_details_path, print_console, start_time=start_time, end_time=end_time, version=version, scope=scope, ncbi_failed=ncbi_failed)
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
        ) + _scope_line(scope) + _ncbi_line(ncbi_failed)
        type_lines = _submission_type_lines(read_submission_types(jsonl_paths))
        header_info += type_lines
        if print_console and type_lines:
            print(type_lines, end="")

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

        # --summary-table: ファイル横断の表（validation_report_table.txt / .tsv）
        if table:
            self.write_table_report(jsonl_paths, header_info=header_info, set_str=set_str)

        return report_summary_path, report_details_path

    # ==============================================================
    # --summary-table: ファイル横断の表（2026-11-10、キュレータの要望）
    # ==============================================================
    _TABLE_LEVELS = ["FATAL", "ERROR", "WARNING", "INFO", "AUTO-CLEANUP"]

    @staticmethod
    def _table_file_label(name, is_cross):
        if is_cross:
            return "(across files)"
        stem = Path(str(name)).name
        return stem[:-4] if stem.endswith(".ann") else stem

    def _collect_table(self, jsonl_paths):
        """表の材料を JSONL から集める。

        戻り値: (files, keys, counts, entries_hit, entry_counts)
          files        : ファイルのラベル（処理順。across files は最後）
          keys         : (level, rule, target) -> 代表メッセージ
          counts       : file -> key -> 件数
          entries_hit  : file -> key -> その key が出た entry の集合
          entry_counts : file -> entry 数（不明なら None）
        """
        files, keys = [], {}
        counts = defaultdict(lambda: defaultdict(int))
        entries_hit = defaultdict(lambda: defaultdict(set))
        entry_counts = {}
        for j_path in jsonl_paths:
            is_cross = "Submission_Cross_File" in str(j_path)
            label = None
            try:
                with open(j_path, "r", encoding="utf-8") as f:
                    for line in f:
                        rec = json.loads(line)
                        r_type, data = rec.get("type"), rec.get("data", {})
                        if r_type == "file_meta":
                            label = label or self._table_file_label(data.get("file", ""), is_cross)
                            entry_counts[label] = data.get("entries")
                            continue
                        if r_type != "result":
                            continue
                        label = label or self._table_file_label(data.get("file", ""), is_cross)
                        level = "AUTO-CLEANUP" if data.get("is_cleanup") else str(data.get("level", "WARNING")).upper()
                        target = data.get("feature_type", "") or data.get("target", "")
                        if data.get("qualifier"):
                            target = f"{target}:{data['qualifier']}" if target else data["qualifier"]
                        key = (level, data.get("rule", "UNKNOWN"), target)
                        if key not in keys:
                            msg = data.get("message", "")
                            if data.get("line_number") is None:
                                msg = re.sub(r"^Line \d+:\s*", "", msg)
                            keys[key] = msg.split("\n")[0]
                        counts[label][key] += 1
                        entry = data.get("entry")
                        if entry and entry not in ("ALL", "COMMON"):
                            entries_hit[label][key].add(entry)
            except FileNotFoundError:
                continue
            if label and label not in files:
                files.append(label)
        # across files は表の最後に置く
        files.sort(key=lambda x: x == "(across files)")
        return files, keys, counts, entries_hit, entry_counts

    def _sorted_table_keys(self, keys, counts, files):
        """Level 順 → 出たファイル数の多い順 → 件数の多い順 → rule id。"""
        def sort_key(k):
            n_files = sum(1 for f in files if counts[f].get(k))
            total = sum(counts[f].get(k, 0) for f in files)
            lvl = self._TABLE_LEVELS.index(k[0]) if k[0] in self._TABLE_LEVELS else len(self._TABLE_LEVELS)
            return (lvl, -n_files, -total, k[1], k[2])
        return sorted(keys, key=sort_key)

    @staticmethod
    def _text_table(header, rows):
        """固定幅の表（列は ' | ' 区切り、最後の列は幅をそろえない）。"""
        widths = [max(len(str(r[i])) for r in [header] + rows) for i in range(len(header) - 1)]
        def fmt(r):
            cells = [str(c).ljust(w) for c, w in zip(r[:-1], widths)] + [str(r[-1])]
            return " | ".join(cells).rstrip()
        sep = "-+-".join("-" * w for w in widths) + "-+-" + "-" * len(str(header[-1]))
        return "\n".join([fmt(header), sep] + [fmt(r) for r in rows]) + "\n"

    def write_table_report(self, jsonl_paths, header_info="", set_str=""):
        """reports/validation_report_table.txt（rule id ごとの集計＋同じ出方のファイルをまとめた一覧）と
        reports/validation_report_table.tsv（ファイル × rule id の件数行列。Excel 用）を書く。"""
        files, keys, counts, entries_hit, entry_counts = self._collect_table(jsonl_paths)
        real_files = [f for f in files if f != "(across files)"]
        n_files = len(real_files)
        ordered = self._sorted_table_keys(keys, counts, files)

        # pattern 表示用の短い名前（同じ rule id が複数の target で出るときだけ target を付ける）
        rule_targets = defaultdict(set)
        for k in ordered:
            rule_targets[k[1]].add((k[0], k[2]))
        short = {k: (k[1] if len(rule_targets[k[1]]) == 1 else f"{k[1]}({k[2]})") for k in ordered}

        # ---------- Summary by rule id ----------
        rows = []
        for k in ordered:
            hit = [f for f in real_files if counts[f].get(k)]
            total = sum(counts[f].get(k, 0) for f in files)
            files_str = f"{len(hit)}/{n_files}" if hit else "-"
            rows.append([k[0], k[1], k[2], files_str, total, keys[k]])
        by_rule = self._text_table(["Level", "Rule ID", "Target", "Files", "Total", "Message"], rows) if rows else "(no messages)\n"

        # ---------- Files by pattern（同じ出方のファイルを 1 つにまとめる） ----------
        # 全 entry に出ている rule は「all entries」とし件数で分けない（entry 数の違うファイルも同じ pattern にする）。
        # それ以外は件数ごと比べる。ファイルごとの件数は TSV にある。
        def mark(f, k):
            ent, n_ent = len(entries_hit[f].get(k, ())), entry_counts.get(f)
            if ent and n_ent and ent == n_ent:
                return "all entries"
            c = counts[f][k]
            return f"{c}" + (f" ({ent}/{n_ent} entries)" if ent and n_ent else "")

        patterns = defaultdict(list)
        for f in real_files:
            sig = tuple((k, mark(f, k)) for k in ordered if counts[f].get(k))
            patterns[sig].append(f)
        pattern_of = {}
        pat_lines = []
        for i, (sig, members) in enumerate(sorted(patterns.items(), key=lambda kv: (-len(kv[1]), kv[1][0])), 1):
            for f in members:
                pattern_of[f] = i
            n_label = "1 file" if len(members) == 1 else f"{len(members)} files"
            ents = sorted(e for e in {entry_counts.get(f) for f in members} if e is not None)
            if ents:
                rng = f"{ents[0]}" if len(ents) == 1 else f"{ents[0]}-{ents[-1]}"
                n_label += f", {rng} entr{'y' if rng == '1' else 'ies'}" + (" each" if len(members) > 1 and len(ents) == 1 else "")
            body = ", ".join(f"{short[k]} {m}" for k, m in sig) if sig else "no messages"
            pat_lines.append(f"Pattern {i} ({n_label}): {body}")
            pat_lines.append("  " + ", ".join(sorted(members)))
        if "(across files)" in files:
            across = ", ".join(f"{short[k]} {counts['(across files)'][k]}" for k in ordered if counts["(across files)"].get(k))
            pat_lines.append(f"Across files: {across}")

        # ---------- ファイル × rule id の行列（TSV と txt の両方に出す） ----------
        level_abbr = {"FATAL": "FAT", "ERROR": "ERR", "WARNING": "WAR", "INFO": "INFO", "AUTO-CLEANUP": "CLEAN"}
        matrix = []
        for i, f in enumerate(files, 1):
            by_level = defaultdict(int)
            for k, c in counts[f].items():
                by_level[k[0]] += c
            ent = entry_counts.get(f)
            matrix.append(([str(i), f, "" if ent is None else str(ent), str(pattern_of.get(f, ""))],
                           [counts[f].get(k, 0) for k in ordered],
                           [by_level.get(lv, 0) for lv in self._TABLE_LEVELS]))
        # txt は rule id（pattern と同じ短い名前）を列名にし、0 は '-' にする（rule の Level / Target は上の表にある）
        txt_head = ["#", "File", "Entries", "Pattern"] + [short[k] for k in ordered] + [level_abbr[lv] for lv in self._TABLE_LEVELS]
        txt_rows = [lead + [str(c) if c else "-" for c in rule_cells + level_cells] for lead, rule_cells, level_cells in matrix]
        by_file = self._text_table(txt_head, txt_rows) if txt_rows else "(no files)\n"

        txt = [f"\n=== Validation Table ({set_str}) ===\n", header_info,
               f"\n## Summary by rule id ({n_files} file{'s' if n_files != 1 else ''})\n", by_rule,
               "\n## Files by pattern\n", "\n".join(pat_lines) + "\n",
               "\n## File x rule id (count)\n", by_file]
        (self.out_dir / "validation_report_table.txt").write_text("".join(txt), encoding="utf-8")

        head = ["#", "File", "Entries", "Pattern"] + [f"{k[1]} ({k[0]}, {k[2]})" for k in ordered] + self._TABLE_LEVELS
        lines = ["\t".join(head)]
        for lead, rule_cells, level_cells in matrix:
            lines.append("\t".join(lead + [str(c) if c else "" for c in rule_cells] + [str(c) for c in level_cells]))
        (self.out_dir / "validation_report_table.tsv").write_text("\n".join(lines) + "\n", encoding="utf-8")


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

    def _write_empty_report(self, sum_path, det_path, print_console, start_time=None, end_time=None, version=None, scope=None, ncbi_failed=0):
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
        ) + _scope_line(scope) + _ncbi_line(ncbi_failed)

        empty_msg_sum = f"\n=== Validation Summary (0 file sets) ===\n{header_info}No errors found.\n"
        empty_msg_det = f"\n=== Validation Details (0 file sets) ===\n{header_info}No errors found.\n"
        
        try:
            with open(det_path, "w", encoding="utf-8") as f:
                f.write(empty_msg_det)
        except Exception as e:
            logger.debug(f"Failed to write empty details report to {det_path}: {e}", exc_info=True)
        try:
            with open(sum_path, "w", encoding="utf-8") as f:
                f.write(empty_msg_sum)
        except Exception as e:
            logger.debug(f"Failed to write empty summary report to {sum_path}: {e}", exc_info=True)
        if print_console:
            print(empty_msg_sum, end="")
