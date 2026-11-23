"""patent の実行: set（ann 1 つ + FASTA 1 つ）ごとに検証し、結果を JSONL に書く。

ddbj のパイプライン（外部 DB の一括取得・自動修正の提案・fixed/ の書き出し）は使わない。
特許は値に手を入れず、fixed/ も出さないので、前処理（掃除なし）→ parser → 規則 → JSONL だけを行う。
JSONL の形は ddbj のワーカーと同じにして、報告は ddbj の reporter をそのまま使う。
"""
import logging
import shutil
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from common.jsonl import dumps_line
from apps.patent import constants as C

logger = logging.getLogger(__name__)

# 組の検出で出た error（ANN0010 / ANN0020）を載せる JSONL の名前
FILE_ERRORS_JSONL = "_file_pairs.jsonl"


@dataclass(frozen=True)
class PatentTask:
    """ワーカーへ渡す入力（ProcessPoolExecutor に渡すので pickle できる形）。"""
    ann_path: str
    seq_path: str
    tmp_dir: str
    # taxonomy にある organism 名の集合。None は引いていない（-l、または DB に届かない）
    known_organisms: Any = None
    today: Any = None


_CONTEXT = None


def _context():
    """ワーカーのプロセスごとに 1 回だけ作る（定義ファイルの読み込みを set ごとに繰り返さない）。"""
    global _CONTEXT
    if _CONTEXT is None:
        from apps.ddbj.context import ValidationContext
        _CONTEXT = ValidationContext(skip_db=True, skip_ncbi=True, skip_auth=True)
    return _CONTEXT


def filter_results(results):
    """使う検査（借りる rule id の表 + PAT）の結果だけを残す。

    特許の重さは error / warning / flag / info。借りた検査の FATAL は error にそろえる
    （error が 1 つでもある set は load しない、という判定を 1 つの重さで行えるように）。
    """
    kept = []
    for r in results:
        rule = str(r.get("rule", ""))
        if not (rule.startswith("PAT") or rule in C.BORROWED_RULE_IDS):
            continue
        if str(r.get("level", "")).lower() == "fatal":
            r["level"] = "error"
        kept.append(r)
    return kept


def validate_set(task):
    """1 set を検証して JSONL のパスを返す。"""
    ann_path, seq_path = task.ann_path, task.seq_path
    ann_name = Path(ann_path).name
    try:
        results, entry_count = _validate(task)
    except Exception as e:  # 1 set の失敗で送付全体を止めない
        logger.error(f"Failed to validate '{ann_name}': {e}", exc_info=True)
        results, entry_count = [{
            "level": "error", "rule": "PAT9999", "target": "file", "entry": "ALL", "feature_type": "file",
            "message": f"Internal error; the set could not be validated. ({type(e).__name__}: {e})",
        }], None
    # file は set の名前としてそろえる（ddbj は SEQ / AXS の結果に FASTA の名前を入れるが、
    # 特許の報告は {file, entry} で set と entry を引くので ann の名前に統一する）
    for r in results:
        r["file"] = ann_name
        r["full_path"] = str(ann_path)
    jsonl_path = Path(task.tmp_dir) / f"{ann_name}.jsonl"
    with open(jsonl_path, "wb") as f:
        for r in results:
            f.write(dumps_line({"type": "result", "data": r}))
        f.write(dumps_line({"type": "file_meta", "data": {"file": ann_name, "entries": entry_count}}))
    return str(jsonl_path)


def _validate(task):
    from apps.ddbj.preprocessor import preprocess_files
    from apps.ddbj.parser import parse_ddbj_submission
    from apps.patent.validator import PatentValidator

    context = _context()
    context.pat_kind = C.set_kind(task.ann_path)
    context.pat_known_organisms = task.known_organisms
    context.pat_today = task.today

    # cleanup=False: 値に手を入れない（COMMENT の line は桁を空白で揃えてある）
    ann_lines, fasta_content, pre_warnings = preprocess_files(task.ann_path, task.seq_path, cleanup=False)
    records, parse_errors, fasta_only_records = parse_ddbj_submission(
        fasta_content=fasta_content, ann_path=task.ann_path, ann_lines=ann_lines, ddbj_dict=context.ddbj_dict)
    # 列の数の誤りは前処理が全行を見て報告する。parser の分は重ねない（ddbj のワーカーと同じ）
    if any(w.get("rule") == "ANN0140" for w in pre_warnings):
        parse_errors = [e for e in parse_errors if e.get("rule") != "ANN0140"]

    context.analyze_records(records)
    results = pre_warnings + parse_errors
    results += PatentValidator(context).run(records, task.ann_path, task.seq_path, ann_lines=ann_lines,
                                            fasta_content=fasta_content, fasta_only_records=fasta_only_records)
    entry_count = sum(1 for e in records if e != "COMMON")
    return filter_results(results), entry_count


def collect_organisms(pairs):
    """全 set の /organism の値（一意）。taxonomy を 1 回だけ引くために先に集める。"""
    names = set()
    for ann_path, _ in pairs:
        with open(ann_path, encoding="utf-8", errors="replace") as f:
            for line in f:
                if "\torganism\t" in line:
                    names.add(line.rstrip("\r\n").split("\t")[-1].strip())
    names.discard("")
    return names


def fetch_known_organisms(pairs):
    """taxonomy にある organism 名の集合を返す。DB に届かないときは None（PAT0043 を動かさない）。"""
    names = collect_organisms(pairs) - C.ORGANISM_ALWAYS_OK
    if not names:
        return set()
    try:
        from common.db_manager import DatabaseManager
        from common.db_taxonomy import fetch_taxonomy_data, lookup_failed_organisms
        conn = DatabaseManager().get_tax_conn()
        if conn is None:
            return None
        tax_data = fetch_taxonomy_data(conn, sorted(names))
        failed = set(lookup_failed_organisms(tax_data))
        # 引けなかった名前は「無い」と言えないので、あるものとして扱う
        return {n for n in names if n in failed or tax_data.get(n, {}).get("status") != "not_found"}
    except Exception as e:
        logger.warning(f"Taxonomy lookup failed; PAT0043 is skipped. ({e})")
        return None


def run(pairs, file_errors, out_dir, jobs, known_organisms=None, today=None):
    """全 set を検証し、(JSONL のパスの一覧, 一時ディレクトリ) を返す。一時ディレクトリは呼び出し側が消す。"""
    tmp_dir = Path(out_dir) / ".val_tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    tasks = [PatentTask(str(a), str(s), str(tmp_dir), known_organisms, today) for a, s in pairs]
    jsonl_paths = []
    if file_errors:
        path = tmp_dir / FILE_ERRORS_JSONL
        with open(path, "wb") as f:
            for r in filter_results([dict(e) for e in file_errors]):
                f.write(dumps_line({"type": "result", "data": r}))
        jsonl_paths.append(str(path))
    if tasks:
        workers = max(1, min(jobs, len(tasks)))
        if workers == 1:
            jsonl_paths.extend(validate_set(t) for t in tasks)
        else:
            # 小さい set が多い（1 回の送付で最大 13,500 set）ので、まとめて渡して受け渡しを減らす
            chunk = max(1, min(32, len(tasks) // (workers * 4)))
            with ProcessPoolExecutor(max_workers=workers) as executor:
                jsonl_paths.extend(executor.map(validate_set, tasks, chunksize=chunk))
    return jsonl_paths, tmp_dir


def cleanup(tmp_dir):
    shutil.rmtree(tmp_dir, ignore_errors=True)
