"""FastAPI アプリ本体。現行 ruby validator と同じ REST 契約（D-way 無改修で差し替え可能）。

- UUID は web server で採番（ダッシュ無し 32hex）。run dir を作り、validator を子プロセスで呼ぶ。
- status.json / result.json / validation.log は run dir 配下に置く。
"""
import logging

from fastapi import BackgroundTasks, FastAPI, File, Form, Path as FPath, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from apps.webapi import config, runner
from common import run_event

logger = logging.getLogger(__name__)

app = FastAPI(title="DDBJ Validator Web API", version="0.1.0")

_UUID_RE = r"^[0-9a-f]{32}$"   # 本ツール発行の UUID（ダッシュ無し 32hex）のみ受け付ける


def _err(message, status):
    return JSONResponse({"status": "error", "message": message}, status_code=status)


@app.get("/health")
@app.get("/up")
def health():
    return {"status": "ok", "env": config.DDBJ_ENV}


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
    mode: str = Form(None),
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
              "package": package, "mode": mode, "start_time": start}
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
    rdir = run_event.run_dir(config.DATA_DIR, uuid)
    files = sorted((rdir / filetype).glob("*")) if (rdir / filetype).is_dir() else []
    if len(files) != 1:
        return _err("Validation file not found", 404)
    return FileResponse(str(files[0]), filename=files[0].name)


@app.delete("/validation/{uuid}")
def delete_validation(uuid: str = FPath(pattern=_UUID_RE)):
    import shutil
    rdir = run_event.run_dir(config.DATA_DIR, uuid)
    if not rdir.exists():
        return _err("Validation not found", 404)
    shutil.rmtree(rdir, ignore_errors=True)
    return {"uuid": uuid, "status": "deleted"}
