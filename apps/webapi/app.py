"""FastAPI アプリ本体。現行 ruby validator と同じ REST 契約（D-way 無改修で差し替え可能）。

- UUID は web server で採番（標準のハイフンあり uuid4）。run dir を作り、validator を子プロセスで呼ぶ。
- status.json / result.json / validation.log は run dir 配下に置く。
"""
import logging
import logging.handlers
import os
import re
import shutil
import tempfile
import time
from contextlib import asynccontextmanager
from pathlib import Path as FsPath

from fastapi import BackgroundTasks, FastAPI, File, Form, Path as FPath, Query, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response

from apps.webapi import config, packages, runner
from common import run_event

logger = logging.getLogger(__name__)

# run dir の shard 名（DATA_DIR/<uuid 先頭2文字>/<uuid>/。run_event.run_dir と対応）
_SHARD_RE = re.compile(r"^[0-9a-f]{2}$")


def _formatter():
    """asctime を JST 固定で出す formatter（run_event.run_logger と同じ方針）。

    コンテナの TZ が UTC でも、status.json / validation.log（JST）と時刻を突き合わせられるようにする。
    """
    f = logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")
    f.converter = lambda secs: time.gmtime((secs if secs is not None else time.time()) + 9 * 3600)
    return f


def _setup_logging():
    """アプリのログを stdout と DATA_DIR/web.log の両方に出す。

    500 の traceback が uvicorn の stdout にしか出ず、log driver が journald だと `podman logs` でも
    journalctl でも回収できなかった（原因調査が再現テスト頼みになった）。
    - root（アプリのログ）: 既定でハンドラが無いので stdout ＋ web.log の両方を付ける。
    - "uvicorn"（uvicorn.error の伝播先）: 既に自前の stdout ハンドラを持つので **web.log だけ**追加する
      （stdout にも付けると uvicorn 自身のログが二重に出る）。
    access ログ（uvicorn.access）は D-way のポーリングで大量になるため web.log には入れない。
    """
    stream = logging.StreamHandler()
    file_handler = None
    try:
        FsPath(config.WEB_LOG).parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            config.WEB_LOG, maxBytes=10 * 1024 * 1024, backupCount=3, encoding="utf-8")
    except OSError as e:
        logging.getLogger(__name__).warning(
            "web ログファイルを開けません（stdout のみで継続）: %s: %s", config.WEB_LOG, e)
    targets = {"": [stream], "uvicorn": []}
    if file_handler is not None:
        targets[""].append(file_handler)
        targets["uvicorn"].append(file_handler)
    for name, handlers in targets.items():
        lg = logging.getLogger(name)
        for h in handlers:
            h.setFormatter(_formatter())
            lg.addHandler(h)
        if lg.level == logging.NOTSET or lg.level > logging.INFO:
            lg.setLevel(logging.INFO)


def _shard_warning(bad):
    """書込不可 shard の件数から、運用者向けの一文を作る（POST の失敗率＝bad/256）。"""
    return (f"{len(bad)}/256 shard が書き込み不可（POST /validation が約 {len(bad) / 256 * 100:.1f}% の"
            f"確率で失敗します）: {', '.join(bad[:10])}")


def _unwritable_shards():
    """既存 shard ディレクトリのうち、このプロセスから書けないものの名前を全件返す。

    POST /validation は run dir を DATA_DIR/<shard>/<uuid>/ に作る。shard の所有権がずれて
    書けなくなると、採番された uuid の当たり方次第で受付だけが失敗する（= ランダムな 500 に見える）。
    起動時ログ・/monitoring・POST の失敗時から呼び、症状として現れる前に検出する。
    件数がそのまま失敗率（件数/256）になるので、途中で打ち切らず全件数える（stat 256 回で十分軽い）。
    """
    try:
        entries = sorted(p for p in FsPath(config.DATA_DIR).iterdir()
                         if _SHARD_RE.match(p.name) and p.is_dir())
    except OSError:
        return []
    return [d.name for d in entries if not os.access(d, os.W_OK | os.X_OK)]


@asynccontextmanager
async def lifespan(app):
    _setup_logging()
    bad = _unwritable_shards()
    if bad:
        # ここに出たら受付だけが確率的に落ちる。デプロイ直後に気づけるよう ERROR で出す。
        logger.error("DATA_DIR の所有権を確認してください: %s", _shard_warning(bad))
    else:
        logger.info("DATA_DIR の shard は全て書き込み可（env=%s, dir=%s）", config.DDBJ_ENV, config.DATA_DIR)
    yield


app = FastAPI(title="DDBJ Validator Web API", version="0.1.0", lifespan=lifespan)

_MONITORING_XML = FsPath(__file__).parent / "resources" / "monitoring.xml"

_UUID_RE = r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"   # 標準 uuid（ハイフンあり）



def _err(message, status):
    return JSONResponse({"status": "error", "message": message}, status_code=status)


@app.exception_handler(Exception)
async def _unhandled(request, exc):
    """未捕捉例外を JSON 契約（{status, message}）に揃え、traceback をログへ残す。

    素の FastAPI は本文 `Internal Server Error`（text/plain）を返すだけで、traceback は stdout に
    しか出ない。呼び出し側（D-way）が原因を判別できず、こちらもログを回収できなかったため。
    starlette は応答後に例外を再送出するので uvicorn 側のログにも従来どおり残る。
    """
    logger.exception("未捕捉の例外: %s %s", request.method, request.url.path)
    return JSONResponse({"status": "error", "message": f"Internal Server Error: {exc}"}, status_code=500)


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
    except Exception as e:
        logger.exception("monitoring: data dir not writable")
        return JSONResponse({"status": "NG", "message": f"data dir not writable: {e}", "env": config.DDBJ_ENV},
                            status_code=503)

    # run dir 用 shard の書込可否を先に見る。DATA_DIR 直下（下の mkdtemp）が書けても既存 shard が
    # 書けないことがあり、その場合 /monitoring は OK なのに POST /validation だけが確率的に 500 になる
    # （2026-08 の障害はこの状態を外形監視で検出できなかった）。ここで NG にして気づけるようにする。
    bad = _unwritable_shards()
    if bad:
        logger.error("monitoring: %s", _shard_warning(bad))
        return JSONResponse({"status": "NG", "env": config.DDBJ_ENV,
                             "message": f"Run-dir shards are not writable: {_shard_warning(bad)}"},
                            status_code=503)

    try:
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
        try:
            shutil.rmtree(rdir)
        except OSError as e:
            # ignore_errors=True だと削除失敗が無音で、消せない .monitoring-* が溜まり続けていた
            # （所有者ずれが原因。web を container root にして解消したが、再発は必ずログに出す）。
            logger.warning("monitoring: 一時ディレクトリを削除できません（残骸が残ります）: %s: %s", rdir, e)


# ---- package / attribute 定義提供（現行 ruby validator の packages API 相当）----
# データ源は SPARQL ではなく同梱 JSON（apps/biosample/resources/attributes_packages.json）。

@app.get("/package_list")
def package_list():
    """全 BioSample パッケージ一覧（メタ情報付き）。"""
    return {"status": "success", "version": packages.version(), "packages": packages.package_list()}


@app.get("/attribute_list")
def attribute_list(package: str = Query(None)):
    """指定パッケージの属性一覧（定義順・use・format・CV）。"""
    if not package:
        return _err("'package' parameter is required", 400)
    if not packages.has_package(package):
        return _err(f"Unknown package: '{package}'", 400)
    return {"status": "success", "version": packages.version(), "package": package,
            "attributes": packages.attribute_list(package)}


@app.get("/attribute_template_file")
def attribute_template_file(package: str = Query(None)):
    """登録システムと同一のヘッダ 1 行 TSV テンプレートをダウンロード（必須は '*' 接頭辞）。"""
    if not package:
        return _err("'package' parameter is required", 400)
    if not packages.has_package(package):
        return _err(f"Unknown package: '{package}'", 400)
    return Response(
        content=packages.template_tsv(package),
        media_type="text/tab-separated-values",
        headers={"Content-Disposition": 'attachment; filename="template.tsv"'},
    )


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
    ddbj_record: UploadFile = File(None),
    submitter_id: str = Form(None),
    submission_id: str = Form(None),
    package: str = Form(None),
    # ddbj_record 専用。1 ファイルに複数 DB が同居し得るので、どの DB として検証するかを
    # 呼び出し側が指定する（省略時は top-level から推測。runner._plan_record）。
    # 名前が record_db なのは、この file 内の「db モード」（MODE_FLAG_DB）と別物だから。
    record_db: str = Form(None),
):
    uploads = {
        "biosample": biosample, "bioproject": bioproject,
        "dra_submission": dra_submission, "dra_experiment": dra_experiment,
        "dra_run": dra_run, "dra_analysis": dra_analysis,
        "gea_idf": gea_idf, "gea_sdrf": gea_sdrf,
        "metabobank_idf": metabobank_idf, "metabobank_sdrf": metabobank_sdrf,
        # DDBJ Record（v3 JSON）は DB 別でなく形式で 1 ロール。record_db フォームか、
        # 無ければ中身を見て振り分ける（runner._plan_record）。
        "ddbj_record": ddbj_record,
    }
    uploads = {r: f for r, f in uploads.items() if f is not None}
    if not uploads:
        return _err("入力ファイルがありません", 400)

    uuid = run_event.new_uuid()
    rdir = run_event.run_dir(config.DATA_DIR, uuid)
    start = run_event.timestamp()
    try:
        run_event.write_status(rdir, uuid=uuid, status=run_event.ACCEPTED, start_time=start)

        saved = {}
        for role, up in uploads.items():
            saved[role] = runner.save_upload(rdir, role, up.filename, await up.read())
    except OSError as e:
        # run dir を作れない／書けないのはサーバ側の事故（shard の所有権ずれ・ディスク不足等）で、
        # 呼び出し側の入力は正しい。素の 500 `Internal Server Error` では原因が判別できないため、
        # 503（一時的に受付不能。再送で回復し得る）＋原因メッセージ＋traceback をログに残す。
        logger.exception("run dir を作成できません: %s", rdir)
        bad = _unwritable_shards()
        hint = (f" {_shard_warning(bad)}" if bad else "")
        return _err(f"検証を受け付けられません（保存先エラー）: {e}.{hint}", 503)

    params = {"account": submitter_id, "submission_id": submission_id,
              "package": package, "record_db": record_db, "start_time": start}   # mode は db 固定（引数で受けない）
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
        # 検証が成立しなかった run。status の message には理由が入っているので、
        # "Validation not found"（＝知らない UUID）と同じ本文を返さない。
        return _err(status.get("message") or "Validation not found", 404)
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
    filetype: input=入力ファイル / fixed=autofix 済みファイル / result / status。
    入力・autofix 出力は形式が XML とは限らない（DDBJ Record 入力なら JSON）。"""
    rdir = run_event.run_dir(config.DATA_DIR, uuid)
    if not rdir.exists():
        return _err("Validation not found", 404)
    if filetype == "input":
        # run_dir 直下の入力ファイル（<SSUB>.xml / <SSUB>.json 等）。run 自身の出力
        # （result.json / status.json / validation.log）は同じ場所にあるので除く。
        # 同名でアップロードされたものは save_upload がロール名を前置してある。
        files = sorted(rdir.glob("*.xml"))
        files += [p for p in sorted(rdir.glob("*.json"))
                  if p.name not in runner.RESERVED_NAMES]
        if not files:
            # D-way が拡張子なしのフォールバック名 "biosample" で送った入力も拾う（fixed を fixed/* で
            # 緩めているのと同様）。今後 D-way は <SSUB>.xml で送る想定だが、拡張子なし時の後方互換。
            cand = rdir / "biosample"
            if cand.is_file():
                files = [cand]
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
