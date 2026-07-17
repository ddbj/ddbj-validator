"""アップロードの保存と validator 呼び出し。web server から呼ばれ、validator を子プロセスで実行する。

validator は別コンテナでも良い（config.VALIDATOR_CMD を `podman exec ...` にする）。
各 validator CLI は `-o <run_dir>`（出力先）と `-j`（result.json）に対応済み。
"""
import logging
import shutil
import subprocess
from pathlib import Path

from apps.webapi import config
from common import run_event

logger = logging.getLogger(__name__)

# 受け付けるアップロードのロール（フィールド名）。ruby validator のカテゴリに対応。
UPLOAD_ROLES = (
    "biosample", "bioproject",
    "dra_submission", "dra_experiment", "dra_run", "dra_analysis",
    "gea_idf", "gea_sdrf",
    "metabobank_idf", "metabobank_sdrf",
)


def save_upload(rdir, role, filename, data):
    """アップロードを run_dir 直下に元ファイル名で保存してパスを返す（例 biosample=SSUB000000.xml）。

    D-way は biosample の SSUB XML を SSUB id 名（例 SSUB000000.xml）で送る想定。run_dir 直下に置くことで
    autofix 出力（validator が `<out>/fixed/<同名>` に書く）とレイアウトが揃う。ファイル名が空なら role 名で代替。"""
    dest_dir = Path(rdir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    safe = Path(filename or f"{role}.xml").name
    dest = dest_dir / safe
    dest.write_bytes(data)
    return dest


def plan(saved, params):
    """保存済みファイル（role→Path）から validator サブコマンド＋引数を決める。
    どの validator かはアップロードされたロールの有無で判定する（ruby と同様）。"""
    if "biosample" in saved:
        f = saved["biosample"]
        flag = "-x" if f.suffix.lower() == ".xml" else "-t"
        args = ["biosample", flag, str(f)]
        if params.get("submission_id"):
            args += ["-s", params["submission_id"]]
        if params.get("package"):
            args += ["-p", params["package"]]
        return args
    if "bioproject" in saved:
        return ["bioproject", "-x", str(saved["bioproject"])]
    dra_map = {"dra_submission": "--sub", "dra_experiment": "--exp",
               "dra_run": "--run", "dra_analysis": "--ana"}
    if any(r in saved for r in dra_map):
        args = ["dra"]
        for role, flag in dra_map.items():
            if role in saved:
                args += [flag, str(saved[role])]
        return args
    if "gea_idf" in saved or "gea_sdrf" in saved:
        args = ["gea"]
        if "gea_idf" in saved:
            args += ["--idf", str(saved["gea_idf"])]
        if "gea_sdrf" in saved:
            args += ["--sdrf", str(saved["gea_sdrf"])]
        return args
    if "metabobank_idf" in saved or "metabobank_sdrf" in saved:
        args = ["metabobank"]
        if "metabobank_idf" in saved:
            args += ["--idf", str(saved["metabobank_idf"])]
        if "metabobank_sdrf" in saved:
            args += ["--sdrf", str(saved["metabobank_sdrf"])]
        return args
    return None


def run_validation(rdir, saved, params):
    """validator を子プロセス実行し、result.json を run_dir 直下へ集約する。

    status.json（running→finished/error）を更新し、実行ログは run_dir/validation.log へ集約する。
    """
    rdir = Path(rdir)
    start = params.get("start_time") or run_event.timestamp()
    with run_event.run_logger(rdir):
        try:
            base_args = plan(saved, params)
            if base_args is None:
                raise ValueError("有効な入力がありません（対応ロールのファイルが無い）")

            mode = params.get("mode") or config.DEFAULT_MODE
            args = list(base_args)
            args += [config.MODE_FLAG.get(mode, "-d"), "-j", "-o", str(rdir)]
            if params.get("account"):
                args += ["--account", params["account"]]

            cmd = config.VALIDATOR_CMD + args
            logger.info("run validation: %s", " ".join(cmd))
            run_event.write_status(rdir, uuid=rdir.name, status=run_event.RUNNING,
                                   start_time=start)
            proc = subprocess.run(cmd, capture_output=True, text=True,
                                  timeout=config.RUN_TIMEOUT)
            if proc.stdout:
                logger.info("validator stdout:\n%s", proc.stdout)
            if proc.stderr:
                logger.info("validator stderr:\n%s", proc.stderr)

            # result.json を run_dir 直下へ（ruby の契約に合わせる）
            report = rdir / "reports" / "validation_report.json"
            if report.exists():
                shutil.copyfile(report, run_event.result_path(rdir))

            result = run_event.read_result(rdir)
            # CLI 終了コード: 1 = error 級の検証結果あり（プロセス異常ではない）。2 = 入力エラー等。
            if result is None and proc.returncode not in (0, 1):
                final = run_event.ERROR
            elif result is not None and result.get("status") == "error":
                final = run_event.ERROR
            else:
                final = run_event.FINISHED
        except Exception as e:   # noqa: BLE001 - 失敗は status に残して握る
            logger.exception("validation failed")
            final = run_event.ERROR
            run_event.write_status(rdir, uuid=rdir.name, status=final,
                                   start_time=start, end_time=run_event.timestamp(),
                                   message=str(e))
            return final
        run_event.write_status(rdir, uuid=rdir.name, status=final,
                               start_time=start, end_time=run_event.timestamp())
        return final
