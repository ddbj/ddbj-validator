#!/usr/bin/env python3
"""mss form のアップロード（NSUBxxxxxx/YYYYMMDD-HHMMSS/）に ddbj-validator を自動でかける（2026-10-23）。

cron（a012、10 分ごと）から `-production` の venv で呼ぶ:
    */10 * * * * /home/w3const/ddbj-validator-production/.venv/bin/python \
        /home/w3const/ddbj-validator-production/deploy/auto_validate_uploads.py --since 20261023 \
        >> /home/w3const/log/validator-auto.log 2>&1

**アップロード先（submissions/production 以下）には何も書かない。** 日時ディレクトリの中に結果を出すと
mss form で登録者から見えてしまうため（2026-10-23）。結果も印もすべて --out-root
（既定 /home/w3const/nsub-validation）の NSUBxxxxxx/YYYYMMDD-HHMMSS/ に出す。

対象（すべて満たすもの）:
  1. NSUB 直下に disable-upload が無い（登録完了済みは対象外）。
  2. その NSUB の**最新**の日時ディレクトリだけ（古いアップロードは未実行でも流さない）。
  3. 日時ディレクトリ名の日付が --since 以降（運用開始前の分は流さない）。
  4. ディレクトリ内の最終更新から --quiet-min 分以上たっている（アップロード途中を読まない）。
  5. 出力側に済み・実行中の印（.validator.done / .validator.running）が無い。

二回かけない仕組み:
  - 実行前に出力ディレクトリへ .validator.running を置き、終わったら .validator.done（JSON）に置き換える。
    どちらかがあれば実行しない。validator の版が上がっても再実行しない。
  - .running が残ったまま（kill・OOM 等）のものは自動では再実行しない（ログに出すだけ）。
    やり直すときは印を消せば次の回で実行される。
  - スクリプト自体を flock で 1 つに限る（前の回が長引いても重ならない）。

実行内容: `<repo>/.venv/bin/python <repo>/main.py ddbj -f -j 2 -o <出力dir> <日時dir>`（内部 DB モード）。
-o なので reports/ fixed/ aa/ と作業用の .val_tmp はすべて出力 dir にできる。
validator の標準出力・エラーは <出力dir>/validator.log に残す。
出力は umask 027（dir 750 / file 640）で作る。
"""
import argparse
import fcntl
import json
import os
import re
import socket
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
from apps.ddbj.preprocessor import ANN_EXTENSIONS, FASTA_EXTENSIONS  # noqa: E402

DEFAULT_ROOT = "/home/w3const/submissions/production"
DEFAULT_OUT_ROOT = "/home/w3const/nsub-validation"
DEFAULT_LOCK = "/home/w3const/log/validator-auto.lock"
UPLOAD_DIR_RE = re.compile(r"^\d{8}-\d{6}$")
NSUB_RE = re.compile(r"^NSUB\d+$")
DISABLE_MARK = "disable-upload"
RUNNING_MARK = ".validator.running"
DONE_MARK = ".validator.done"
RUN_LOG = "validator.log"


def log(msg):
    print(f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}", flush=True)


def validator_version():
    m = re.search(r'^version\s*=\s*"([^"]+)"', (REPO / "pyproject.toml").read_text(), re.M)
    return m.group(1) if m else ""


def input_files(upload_dir):
    """日時ディレクトリ直下の ann / fasta（validator が拾うもの）を [(name, size, mtime)] で返す。"""
    out = []
    for e in os.scandir(upload_dir):
        if not e.is_file() or e.name.startswith("."):
            continue
        if e.name.endswith(ANN_EXTENSIONS) or e.name.endswith(FASTA_EXTENSIONS):
            st = e.stat()
            out.append((e.name, st.st_size, int(st.st_mtime)))
    return sorted(out)


def has_pair(files):
    names = [f[0] for f in files]
    return any(n.endswith(ANN_EXTENSIONS) for n in names) and \
        any(n.endswith(FASTA_EXTENSIONS) and not n.endswith(ANN_EXTENSIONS) for n in names)


def last_modified(upload_dir):
    """日時ディレクトリ自身と直下ファイルの mtime の最大値。"""
    t = upload_dir.stat().st_mtime
    for e in os.scandir(upload_dir):
        try:
            t = max(t, e.stat().st_mtime)
        except FileNotFoundError:
            pass
    return t


def out_dir_for(out_root, upload_dir):
    """アップロード dir（.../NSUBxxxxxx/YYYYMMDD-HHMMSS）に対応する出力 dir。"""
    return Path(out_root) / upload_dir.parent.name / upload_dir.name


def find_candidates(root, out_root, since, quiet_sec, now=None):
    """実行すべき日時ディレクトリを返す。印・待ちの判定もここで行い、理由をログに出す。

    since は "YYYYMMDD"。NSUB ディレクトリの mtime が since の 0 時より前なら、
    その後に新しい日時ディレクトリは作られていないので中を見ない（約 4,000 NSUB を毎回なめないため）。
    """
    now = now or time.time()
    since_ts = datetime.strptime(since, "%Y%m%d").timestamp()
    found = []
    for e in os.scandir(root):
        if not (e.is_dir() and NSUB_RE.match(e.name)):
            continue
        if e.stat().st_mtime < since_ts:
            continue
        nsub = Path(e.path)
        if (nsub / DISABLE_MARK).exists():
            continue
        uploads = sorted(d.name for d in os.scandir(nsub) if d.is_dir() and UPLOAD_DIR_RE.match(d.name))
        if not uploads:
            continue
        latest = nsub / uploads[-1]          # 最新だけ（古い未実行分は流さない）
        if latest.name[:8] < since:
            continue
        out = out_dir_for(out_root, latest)
        if (out / DONE_MARK).exists():
            continue
        if (out / RUNNING_MARK).exists():
            log(f"[STALE] {out}: {RUNNING_MARK} が残っています（再実行しない。やり直すなら印を消す）")
            continue
        if now - last_modified(latest) < quiet_sec:
            log(f"[WAIT] {latest}: アップロード直後のため次の回に回す")
            continue
        found.append(latest)
    return found


def write_json(path, data):
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n")
    tmp.rename(path)


def run_one(upload_dir, out_root, jobs, timeout_sec, dry_run=False):
    """1 アップロード分を実行する。アップロード dir は読むだけで、書くのは出力 dir だけ。"""
    files = input_files(upload_dir)
    out = out_dir_for(out_root, upload_dir)
    rec = {"upload_dir": str(upload_dir), "out_dir": str(out), "validator_version": validator_version(),
           "host": socket.gethostname(), "start": datetime.now().isoformat(timespec="seconds"),
           "files": [{"name": n, "size": s, "mtime": m} for n, s, m in files]}
    if not has_pair(files):
        # ann / fasta が揃っていない。毎回ログに出さないよう済みにする
        rec.update(status="skipped_no_pair", end=rec["start"], exit_code=None)
        log(f"[SKIP] {upload_dir}: ann と fasta の組がありません")
        if not dry_run:
            out.mkdir(parents=True, exist_ok=True)
            write_json(out / DONE_MARK, rec)
        return rec
    cmd = ["nice", "-n", "10", str(REPO / ".venv/bin/python"), str(REPO / "main.py"),
           "ddbj", "-f", "-j", str(jobs), "-o", str(out), str(upload_dir)]
    if dry_run:
        log(f"[DRY] {' '.join(cmd)}")
        return rec
    out.mkdir(parents=True, exist_ok=True)
    write_json(out / RUNNING_MARK, {**rec, "pid": os.getpid()})
    log(f"[RUN] {upload_dir} ({len(files)} files, v{rec['validator_version']})")
    t0 = time.time()
    with open(out / RUN_LOG, "w") as fh:
        try:
            p = subprocess.run(cmd, cwd=str(REPO), stdin=subprocess.DEVNULL, stdout=fh,
                               stderr=subprocess.STDOUT, timeout=timeout_sec)
            rec.update(status="done", exit_code=p.returncode)
        except subprocess.TimeoutExpired:
            rec.update(status="timeout", exit_code=None)
    rec.update(end=datetime.now().isoformat(timespec="seconds"), elapsed_sec=round(time.time() - t0))
    write_json(out / DONE_MARK, rec)
    (out / RUNNING_MARK).unlink(missing_ok=True)
    log(f"[{rec['status'].upper()}] {upload_dir} exit={rec['exit_code']} {rec['elapsed_sec']}s")
    return rec


def main(argv=None):
    ap = argparse.ArgumentParser(description="mss form アップロードへの ddbj-validator 自動実行")
    ap.add_argument("--since", required=True, help="この日付（YYYYMMDD）以降の日時ディレクトリだけ対象")
    ap.add_argument("--root", default=DEFAULT_ROOT, help="アップロード先（読むだけ）")
    ap.add_argument("--out-root", default=DEFAULT_OUT_ROOT, help="結果と印の出力先（submissions の外）")
    ap.add_argument("--quiet-min", type=int, default=10, help="最終更新からこの分数たったものだけ実行")
    ap.add_argument("-j", "--jobs", type=int, default=2)
    ap.add_argument("--timeout-hour", type=float, default=6)
    ap.add_argument("--lock", default=DEFAULT_LOCK)
    ap.add_argument("--dry-run", action="store_true", help="対象を表示するだけ（印も置かない）")
    args = ap.parse_args(argv)
    if not re.fullmatch(r"\d{8}", args.since):
        ap.error("--since は YYYYMMDD")

    os.umask(0o027)   # 出力は dir 750 / file 640
    Path(args.lock).parent.mkdir(parents=True, exist_ok=True)
    lock = open(args.lock, "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return 0   # 前の回がまだ動いている
    for d in find_candidates(Path(args.root), Path(args.out_root), args.since, args.quiet_min * 60):
        run_one(d, Path(args.out_root), args.jobs, int(args.timeout_hour * 3600), dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
