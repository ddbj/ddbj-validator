"""FastAPI アプリ本体。現行 ruby validator と同じ REST 契約（D-way 無改修で差し替え可能）。

- UUID は web server で採番（標準のハイフンあり uuid4）。run dir を作り、validator を子プロセスで呼ぶ。
- status.json / result.json / validation.log は run dir 配下に置く。
"""
import logging
import shutil
import tempfile
from pathlib import Path as FsPath

from fastapi import BackgroundTasks, FastAPI, File, Form, Path as FPath, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from apps.webapi import config, runner
from common import run_event

logger = logging.getLogger(__name__)

app = FastAPI(title="DDBJ Validator Web API", version="0.1.0")

_MONITORING_XML = FsPath(__file__).parent / "resources" / "monitoring.xml"

_UUID_RE = r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"   # 標準 uuid（ハイフンあり）


def _err(message, status):
    return JSONResponse({"status": "error", "message": message}, status_code=status)


@app.get("/health")
@app.get("/up")
def health():
    """軽量 liveness（プロセス生存）。zabbix 短間隔監視用。"""
    return {"status": "ok", "env": config.DDBJ_ENV}


@app.get("/monitoring")
@app.get("/api/monitoring")
def monitoring():
    """深いヘルスチェック（現行 ruby /api/monitoring 踏襲）。

    同梱の合成テスト BioSample を実際に検証パイプラインへ流し、最後まで走れば 200 {status:OK}、
    異常（validator クラッシュ・DATA_DIR 書込不可等）なら 503 {status:NG}。zabbix 等の外形監視で
    validator 子プロセス／レポート生成まで含む健全性を確認する用途。"""
    try:
        FsPath(config.DATA_DIR).mkdir(parents=True, exist_ok=True)
        rdir = FsPath(tempfile.mkdtemp(prefix=".monitoring-", dir=config.DATA_DIR))
    except Exception as e:
        logger.exception("monitoring: data dir not writable")
        return JSONResponse({"status": "NG", "message": f"data dir not writable: {e}", "env": config.DDBJ_ENV},
                            status_code=503)
    try:
        dest = runner.save_upload(rdir, "biosample", "monitoring.xml", _MONITORING_XML.read_bytes())
        final = runner.run_validation(rdir, {"biosample": dest},
                                      {"start_time": run_event.timestamp()})
        if final == run_event.FINISHED:
            return {"status": "OK", "message": "Validation processing has finished successfully.",
                    "env": config.DDBJ_ENV}
        return JSONResponse({"status": "NG", "message": "Validation finished with error. Check the validation service.",
                             "env": config.DDBJ_ENV}, status_code=503)
    except Exception as e:
        logger.exception("monitoring failed")
        return JSONResponse({"status": "NG", "message": f"Error during monitoring: {e}", "env": config.DDBJ_ENV},
                            status_code=503)
    finally:
        shutil.rmtree(rdir, ignore_errors=True)


@app.post("/validation")
async def create_validation(
    background: BackgroundTasks,
    biosample: UploadFile = File(None),
    bioproject: UploadFile = File(None),
    dra_submission: UploadFile = File(None),
    dra_experiment: UploadFile = File(None),
    dra_run: UploadFile = File(None),
    dra_analysis: UploadFile = File(None),
    gea_idf: UploadFile = File(None),
    gea_sdrf: UploadFile = File(None),
    metabobank_idf: UploadFile = File(None),
    metabobank_sdrf: UploadFile = File(None),
    submitter_id: str = Form(None),
    submission_id: str = Form(None),
    package: str = Form(None),
):
    uploads = {
        "biosample": biosample, "bioproject": bioproject,
        "dra_submission": dra_submission, "dra_experiment": dra_experiment,
        "dra_run": dra_run, "dra_analysis": dra_analysis,
        "gea_idf": gea_idf, "gea_sdrf": gea_sdrf,
        "metabobank_idf": metabobank_idf, "metabobank_sdrf": metabobank_sdrf,
    }
    uploads = {r: f for r, f in uploads.items() if f is not None}
    if not uploads:
        return _err("入力ファイルがありません", 400)

    uuid = run_event.new_uuid()
    rdir = run_event.run_dir(config.DATA_DIR, uuid)
    start = run_event.timestamp()
    run_event.write_status(rdir, uuid=uuid, status=run_event.ACCEPTED, start_time=start)

    saved = {}
    for role, up in uploads.items():
        saved[role] = runner.save_upload(rdir, role, up.filename, await up.read())

    params = {"account": submitter_id, "submission_id": submission_id,
              "package": package, "start_time": start}   # mode は db 固定（引数で受けない）
    background.add_task(runner.run_validation, rdir, saved, params)

    return {"uuid": uuid, "status": run_event.ACCEPTED, "start_time": start}


@app.get("/validation/{uuid}")
def show_validation(uuid: str = FPath(pattern=_UUID_RE)):
    rdir = run_event.run_dir(config.DATA_DIR, uuid)
    status = run_event.read_status(rdir)
    if status is None:
        return _err("Validation not found", 404)
    result = run_event.read_result(rdir)
    if result is None:
        if status.get("status") in (run_event.ACCEPTED, run_event.RUNNING):
            return _err("Validation process has not finished yet", 400)
        return _err("Validation not found", 404)
    return {**status, "result": result}


@app.get("/validation/{uuid}/status")
def show_status(uuid: str = FPath(pattern=_UUID_RE)):
    status = run_event.read_status(run_event.run_dir(config.DATA_DIR, uuid))
    if status is None:
        return _err("Validation not found", 404)
    return status


@app.get("/validation/{uuid}/{filetype}")
def get_file(uuid: str = FPath(pattern=_UUID_RE), filetype: str = FPath(pattern=r"^[a-z][a-z_]*$")):
    """run_dir 直下レイアウト（入力 <SSUB>.xml / fixed/<SSUB>.xml / result.json / status.json）向けの取得。
    filetype: input=入力 XML / fixed=autofix 済み XML / result / status。"""
    rdir = run_event.run_dir(config.DATA_DIR, uuid)
    if not rdir.exists():
        return _err("Validation not found", 404)
    if filetype == "input":
        files = [p for p in sorted(rdir.glob("*.xml"))]        # run_dir 直下の入力 XML
    elif filetype == "fixed":
        files = sorted((rdir / "fixed").glob("*")) if (rdir / "fixed").is_dir() else []
    elif filetype in ("result", "status"):
        p = rdir / f"{filetype}.json"
        files = [p] if p.is_file() else []
    else:
        p = rdir / filetype
        files = sorted(p.glob("*")) if p.is_dir() else ([p] if p.is_file() else [])
    if len(files) != 1:
        return _err("Validation file not found", 404)
    return FileResponse(str(files[0]), filename=files[0].name)

# 注: run dir 削除の DELETE エンドポイントは意図的に廃止（誤削除防止）。UUID は使い捨てで、
# 古い run dir は /data1 のクリーンアップ運用（定期削除）で回収する方針。
