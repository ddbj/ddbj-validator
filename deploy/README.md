# DDBJ Validator Web API — デプロイ（podman / podman compose）

Web server（FastAPI）と validator（検証エンジン）を **別コンテナ**で動かす。スパコンでは docker 不可
（root デーモン・セキュリティ）のため **podman / podman compose 必須**（rootless / daemonless）。
a011＝本番 / a012＝ステージングで、同じ compose ファイル＋ `.env` の差し替えで運用する。

## なぜ validator を別コンテナにするのか（推奨構成）

**validator は頻繁に更新される**（ルール追加・修正のイテレーション）。web と同一コンテナに同居させると、
validator を更新するたびに web も作り直し＝再起動になり、**API のダウンタイム**が発生する。

そこで **validator を独立したコンテナ**にし、web は共有ボリューム `/data` 上の run dir を介して
validator を呼び出す。こうすると **validator だけを再ビルド・入れ替え**でき、web は起動したまま
（＝**無停止**でルール更新を反映）にできる。これを本番の既定運用とする。

```
   ┌──────────────┐  podman exec / run     ┌──────────────────┐
   │  web (FastAPI)│ ─────────────────────▶ │ validator (CLI)  │
   │  :8000        │                        │  ddbj-validator  │
   └──────┬───────┘                         └────────┬─────────┘
          │        共有ボリューム /data（run dir）      │
          └───────────────────┬────────────────────────┘
                              ▼
              /data/<uuid[:2]>/<uuid>/（入力・status.json・result.json・reports/…）
```

- web は UUID 採番・run dir 作成・status/log 管理を担い、実際の検証は validator コンテナに委譲する。
- web → validator の呼び出しは `DDBJ_VALIDATOR_CMD`（既定 `podman exec ddbj-validator ddbj-validator`）。
  web コンテナ内から host の podman を叩くため、**web に podman クライアント＋ rootless podman socket のマウントが必要**（後述）。

## 構成（`deploy/`）

- `Containerfile.web` … FastAPI + uvicorn（`pip install .[web]`）。UUID 発行・run dir 作成・status/log 管理・validator 呼び出し。
- `Containerfile.validator` … 検証エンジン（`ddbj-validator` CLI）。UUID/イベントは持たない。**これを頻繁に入れ替える**。
- `podman-compose.yml` … web / validator の 2 サービス＋共有ボリューム `/data`。両サービスに `restart: unless-stopped`。
- `.env.example` … `.env` のテンプレート（実 `.env` は gitignore）。

## 前提

- `podman`（v4+）と、compose 実装のいずれか:
  - `podman compose`（podman 同梱サブコマンド。以下の例はこれ）
  - もしくは `podman-compose`（Python 実装。`pipx install podman-compose`）。読み替え可。
- 共有データディレクトリ（`.env` の `DDBJ_DATA_DIR_HOST`）が作成済み・書込可であること。
- **別コンテナ運用に必要**（web → validator の `podman exec` のため）:
  1. web イメージに podman クライアントが入っていること（`Containerfile.web` で導入。無ければ下記「単一コンテナ」で運用）。
  2. host の rootless podman socket を web にマウントすること。socket パスは次で確認:
     ```bash
     podman info --format '{{.Host.RemoteSocket.Path}}'   # 例 /run/user/1234/podman/podman.sock
     systemctl --user enable --now podman.socket           # socket を有効化（未起動なら）
     ```
     `podman-compose.yml` の web volumes にある socket 行のコメントを外し、`.env` の `DDBJ_PODMAN_SOCK`
     にこのパスを設定する（＋ web の environment に `CONTAINER_HOST=unix:///run/podman/podman.sock` を追加）。

## セットアップ

```bash
cd deploy
cp .env.example .env      # a011/a012 に合わせて編集（下記「.env の要点」参照）
```

### .env の要点

| 変数 | 意味 | 例 |
|---|---|---|
| `DDBJ_ENV` | production / staging | `staging` |
| `DDBJ_WEB_PORT` | ホスト公開ポート | `8000` |
| `DDBJ_DATA_DIR_HOST` | 共有データの**ホスト側**パス（コンテナ内 `/data`） | `/lustre9/.../data` |
| `DDBJ_DEFAULT_MODE` | 既定検証モード `db`/`ncbi`/`local` | `db` |
| `DDBJ_VALIDATOR_CMD` | web→validator 呼び出し。別コンテナ運用の既定 | `podman exec ddbj-validator ddbj-validator` |
| `DDBJ_PODMAN_SOCK` | host の rootless podman socket パス（web にマウント） | `/run/user/1234/podman/podman.sock` |
| `PGHOST`/`PGPORT`/`PGDATABASE` | 内部 DB 接続（`db` モード時。規約: user=password=unixユーザ名） | |
| `NCBI_API_KEY` | NCBI API（`ncbi` モード時） | |

## 起動

```bash
cd deploy
podman compose --env-file .env up -d --build   # web と validator の両コンテナを起動
curl localhost:8000/health                      # {"status":"ok"} 等が返れば成功
```

- `-d`（detached）で**バックグラウンド起動**。コマンドはすぐ戻り、**ターミナルを閉じてもコンテナは動き続ける**
  （常駐させるには下記「常駐運用」も参照。rootless では linger 設定が要る）。

## validator の更新（web 無停止）

ルール更新をデプロイするときは **validator コンテナだけ**を作り直す。web は再起動しない＝ダウンタイム無し。

```bash
cd deploy
git pull                                                  # 最新コードを取得
podman compose --env-file .env build validator            # validator イメージだけ再ビルド
podman compose --env-file .env up -d validator            # validator だけ入れ替え（web はそのまま）
```

- 実行中ジョブへの影響を避けたい場合は、検証が走っていない時間帯に入れ替える（新規ジョブから新 validator を使う）。
- web 自体（API 仕様・アップロード処理）を変えたときのみ `up -d --build web` で web を更新する。

## 常駐運用（ターミナルを閉じてよいか / サービス化）

`podman compose ... up -d` はバックグラウンド起動なので、**その場のターミナルは閉じてよい**。ただし本格運用では
次の 2 点に注意し、**systemd で管理**するのが定石。

1. **rootless の linger**: rootless podman のコンテナはユーザーセッションに紐づく。ログアウトで止まらないよう、
   一度だけ有効化する:
   ```bash
   loginctl enable-linger $USER
   ```
2. **OS 再起動後の自動起動＋異常時の自動再起動**: compose の `restart: unless-stopped` に加え、
   起動そのものを systemd の user service にする。最も簡単なのは compose を叩く unit を 1 つ作る方法:

   `~/.config/systemd/user/ddbj-validator.service`
   ```ini
   [Unit]
   Description=DDBJ Validator (web + validator, podman compose)
   After=network-online.target
   Wants=network-online.target

   [Service]
   Type=simple
   WorkingDirectory=%h/ddbj-validator/deploy
   ExecStart=/usr/bin/podman compose --env-file .env up
   ExecStop=/usr/bin/podman compose --env-file .env down
   Restart=always
   RestartSec=5

   [Install]
   WantedBy=default.target
   ```
   ```bash
   systemctl --user daemon-reload
   systemctl --user enable --now ddbj-validator.service   # 起動＋OS再起動後も自動起動
   systemctl --user status ddbj-validator.service         # 稼働確認
   journalctl --user -u ddbj-validator.service -f         # ログ
   ```
   - この unit は `up`（`-d` なし＝フォアグラウンド）を systemd に管理させる形。プロセス監視・自動再起動・
     起動時自動立ち上げを systemd が担うので、手動で `up -d` するより堅い。
   - （発展）`podman generate systemd` や Quadlet でコンテナ単位の unit を作る方法もあるが、まずは上記で十分。

## よく使う操作

```bash
cd deploy
podman compose --env-file .env ps               # 稼働確認
podman compose --env-file .env logs -f web       # web ログ追尾
podman compose --env-file .env logs -f validator # validator ログ追尾
podman compose --env-file .env down              # 停止・削除
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

## 代替: 単一コンテナ運用（開発・簡易）

podman socket のマウントが難しい環境や開発用途では、web が**自コンテナ内で validator を子プロセス起動**する
単一コンテナ運用も可能。この場合は `.env` で `DDBJ_VALIDATOR_CMD` を空にし、validator サービスは起動しない
（`podman compose --env-file .env up -d --build web`）。ただし validator 更新のたびに web の再ビルド＝
**再起動が必要**（ダウンタイムが出る）ため、本番は上記の別コンテナ運用を推奨する。
