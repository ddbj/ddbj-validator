"""アップロードの保存と validator 呼び出し。web server から呼ばれ、validator を子プロセスで実行する。

validator は別コンテナでも良い（config.VALIDATOR_CMD を `podman exec ...` にする）。
各 validator CLI は `-o <run_dir>`（出力先）と `-j`（result.json）に対応済み。
"""
import json
import logging
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
    "ddbj_record",
)

# ロール既定の拡張子（アップロードがファイル名を持たないとき用）。ddbj_record 以外は XML。
_ROLE_SUFFIX = {"ddbj_record": ".json"}

# run_dir 直下に web / validator 自身が書くファイル。アップロードが同じ名前で来ると
# 上書きし合う（入力が result.json ならそれが検証結果として読み出される）。XML しか
# 受けなかった間は起こらなかったが、JSON を受けるロールができたので現実的になった。
RESERVED_NAMES = frozenset({"result.json", "status.json", "validation.log"})


def save_upload(rdir, role, filename, data):
    """アップロードを run_dir 直下に元ファイル名で保存してパスを返す（例 biosample=SSUB000000.xml）。

    D-way は biosample の SSUB XML を SSUB id 名（例 SSUB000000.xml）で送る想定。run_dir 直下に置くことで
    autofix 出力（validator が `<out>/fixed/<同名>` に書く）とレイアウトが揃う。ファイル名が空なら role 名で代替。"""
    dest_dir = Path(rdir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    safe = Path(filename or f"{role}{_ROLE_SUFFIX.get(role, '.xml')}").name
    if safe in RESERVED_NAMES:
        safe = f"{role}_{safe}"
    dest = dest_dir / safe
    dest.write_bytes(data)
    return dest


def plan(saved, params):
    """保存済みファイル（role→Path）から validator サブコマンド＋引数を決める。
    どの validator かはアップロードされたロールの有無で判定する（ruby と同様）。
    決められなければ None を返す（呼び出し側が入力エラーにする）。"""
    if "ddbj_record" in saved:
        return _plan_record(saved["ddbj_record"], params)
    if "biosample" in saved:
        f = saved["biosample"]
        # 拡張子 .xml、または D-way 由来の拡張子なしフォールバック名 "biosample" は XML と決め打ち。
        # （D-way は今後 <SSUB>.xml で送る。TSV はファイル名 SSUBxxxx.<Package>.txt を期待する。）
        flag = "-x" if (f.suffix.lower() == ".xml" or f.name == "biosample") else "-t"
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


# DDBJ Record を「どの validator に渡すか」を呼び出し側が指定するときの値と、
# 指定が無いときに record の top-level から推測するためのキー。
_RECORD_DB = {"bioproject": "project", "biosample": "samples"}


def _plan_record(path, params):
    """DDBJ Record（v3 JSON）の振り分け。

    Record は 1 ファイルに project / samples / experiments … が同居し得るので、他ロールと
    違って「そのファイルがある＝この validator」とは決まらない。`record_db` で指定して
    もらうのが本筋で、無ければ top-level から推測する。

    **同居する record 自体は不正ではない。** 登録は DB ごとに行い、BioProject として登録
    するときに読まれるのは project、BioSample として登録するときは samples だけなので、
    片方だけを検証するのは正しい振る舞いになる。不正なのは「どちらとして検証するのか
    分からないまま片方を選ぶ」ことだけで、それは `record_db` があれば起きない。
    """
    db = (params.get("record_db") or "").strip().lower()
    if db and db not in _RECORD_DB:
        raise ValueError(
            f"record_db に指定できるのは {' / '.join(sorted(_RECORD_DB))} です: {db!r}")

    args = [db or _sniff_record_db(path), "-r", str(path)]
    if params.get("submission_id"):
        # BP_R0004 の自己除外・BS_R0091 の自己重複除外に使う。record は submission id を
        # 持たず、web api の一時ファイル名も PSUB / SSUB を含まない（CLI はファイル名から拾う）。
        args += ["-s", params["submission_id"]]
    return args


def _sniff_record_db(path):
    """`record_db` 指定が無いときだけ、record の top-level から DB を決める。

    top-level を知るためだけに全文をパースしている。10 万 sample の record では数百 MB の
    一時オブジェクトが web プロセスに載るので、呼び出し側は `record_db` を渡すほうがよい。
    """
    try:
        with open(path, encoding="utf-8") as f:
            record = json.load(f)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
        raise ValueError(f"DDBJ Record を読めません: {e}") from e
    if not isinstance(record, dict):
        raise ValueError("DDBJ Record が JSON オブジェクトではありません")

    # 判定は reader と揃える。`bool()` だと `{"project": {}}` が「project 無し」に
    # なり、web api は断るのに CLI は全ルールを回す、という食い違いが出る。
    has_project = isinstance(record.get("project"), dict)
    has_samples = bool(record.get("samples"))

    if has_project and has_samples:
        raise ValueError(
            "project と samples が同居する DDBJ Record は、どちらとして検証するのかを "
            "推測できません。record_db に bioproject / biosample のいずれかを指定してください。")
    if has_project:
        return "bioproject"
    if has_samples:
        return "biosample"
    raise ValueError("DDBJ Record に project も samples もありません")


def _run_failure_message(proc):
    """検証が成立しなかったときに status へ載せる説明。呼び出し側は message しか見られない
    （validation.log を取れるエンドポイントが無い）ので、validator の言い分を持ってくる。"""
    tail = (proc.stderr or proc.stdout or "").strip().splitlines()
    detail = tail[-1] if tail else "no output"
    return f"validator がレポートを出力せずに終了しました (exit={proc.returncode}): {detail}"


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

            args = list(base_args)
            args += [config.MODE_FLAG_DB, "-j", "-o", str(rdir)]   # web api は内部 DB モード固定（-d）
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

            # result.json を run_dir 直下へ（ruby の契約に合わせる）。
            # 公開は原子的に行う（コピー途中を GET /validation/{uuid} に読ませない）。
            report = rdir / "reports" / "validation_report.json"
            if report.exists():
                run_event.publish_result(rdir, report)

            result = run_event.read_result(rdir)
            # CLI 終了コード: 1 = error 級の検証結果あり（プロセス異常ではない）。2 = 入力エラー等。
            # レポートが無ければ検証は成立していない。終了コードで分けない: 未捕捉例外も
            # 終了コード 1 なので、「検証結果あり」と区別が付かず finished に化けていた。
            if result is None:
                raise ValueError(_run_failure_message(proc))
            if result.get("status") == "error":
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
