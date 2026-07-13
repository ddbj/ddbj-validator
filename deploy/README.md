# DDBJ Validator Web API — デプロイ（podman / podman compose）

Web server（FastAPI）と validator（検証エンジン）を **別コンテナ**で動かす。スパコンでは docker 不可
（root デーモン・セキュリティ）のため **podman / podman compose 必須**（rootless / daemonless）。
a011＝本番 / a012＝ステージングで、同じ compose ファイル＋ `.env` の差し替えで運用する。

## 構成

- `Containerfile.web` … FastAPI + uvicorn（`pip install .[web]`）。UUID 発行・run dir 作成・status/log 管理・validator 呼び出し。
- `Containerfile.validator` … 検証エンジン（`ddbj-validator` CLI）。UUID/イベントは持たない。
- `podman-compose.yml` … web / validator の 2 サービス＋共有ボリューム `/data`（`DDBJ_DATA_DIR`）。
- `.env.example` … `.env` のテンプレート（実 `.env` は gitignore）。

既定では web が **自コンテナ内の validator を子プロセス起動**する（`DDBJ_VALIDATOR_CMD` 未設定）。
validator を完全に別コンテナで常駐させる場合は、web の `DDBJ_VALIDATOR_CMD` を
`podman exec ddbj-validator ddbj-validator` に設定し、`--profile separate-validator` で validator を起動する。

## 起動

```bash
cd deploy
cp .env.example .env      # a011/a012 に合わせて編集
podman compose --env-file .env up -d --build
curl localhost:8000/health
```

## API（現行 ruby validator と同契約 → D-way 無改修で差し替え可能）

| メソッド/パス | 役割 |
|---|---|
| `POST /validation` | multipart アップロード＋フォーム。UUID 採番・run dir 作成 → `{uuid, status: accepted, start_time}` を返し、バックグラウンドで検証 |
| `GET /validation/{uuid}` | status ＋ result.json |
| `GET /validation/{uuid}/status` | status.json |
| `GET /validation/{uuid}/{filetype}` | アップロード元ファイル |
| `DELETE /validation/{uuid}` | run dir クリーンアップ |
| `GET /health`,`/up` | ヘルスチェック |

- **UUID** はダッシュ無し 32hex（`uuid4().hex`）。route は `^[0-9a-f]{32}$` に制約（現行 ruby の 8-4-4-4-12 と区別）。
- アップロードのロール（フィールド名）: `biosample` / `bioproject` / `dra_submission` / `dra_experiment` / `dra_run` /
  `dra_analysis` / `gea_idf` / `gea_sdrf` / `metabobank_idf` / `metabobank_sdrf`。
- フォーム: `submitter_id`（account）/ `submission_id` / `package` / `mode`（`db`(既定) / `ncbi` / `local`）。

## run ディレクトリの中身（`DATA_DIR/<uuid[:2]>/<uuid>/`）

```
<role>/<file>            アップロード入力
status.json              {uuid, status: accepted|running|finished|error, start_time, end_time}
result.json              検証結果（validator の -j 出力を集約）
validation.log           この UUID の実行ログ
reports/ , fixed/ , aa/  validator の出力
```

## リクエスト例

```bash
curl -F 'gea_idf=@E-GEAD-1104.idf.txt' -F 'gea_sdrf=@E-GEAD-1104.sdrf.txt' -F 'mode=local' \
     localhost:8000/validation
# → {"uuid":"ac69...", "status":"accepted", ...}
curl localhost:8000/validation/ac69.../status
curl localhost:8000/validation/ac69...
```
