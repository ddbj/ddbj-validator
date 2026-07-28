# Web API デプロイ（podman / podman-compose）

DDBJ Validator Web API を podman で運用するための compose 定義とラッパスクリプト。スパコンでは docker 不可（root デーモン）のため rootless / daemonless の podman-compose を使う。web（FastAPI）と validator（検証エンジン）を別コンテナで動かし、web から `podman exec` で validator を呼ぶ。

- `compose.sh` … podman-compose ラッパ。`--env-file .env` を自動付与し、validator の ghcr タグを `pyproject.toml` の version に自動追従させる（`DDBJ_VALIDATOR_TAG`）。起動・停止・個別操作に使う。
- `update.sh` … コンテナ差し替え（更新）ラッパ。git pull → pull/build → running 確認 → `rm -f` → `up` を 1 コマンドにまとめる（下記）。

> 起動系は必ず `./compose.sh` を使う。`podman compose`（スペース）はこの環境では docker-compose に委譲され `podman-compose.yml` を認識できず失敗する。

## 起動

```shell
cd deploy
cp .env.example .env      # 環境（a011=本番 / a012=ステージング）に合わせて編集
./compose.sh up -d        # web + validator を起動
./compose.sh ps           # 稼働確認
./compose.sh logs -f web  # ログ追尾
./compose.sh down         # 停止・削除
```

秘密情報は git 管理外。運用パラメータは `deploy/.env`、内部 DB 接続情報・NCBI キーはリポジトリ直下 `.env`（どちらも gitignore 済み）。

## 更新（コンテナ差し替え）— `update.sh`（推奨）

新しい版へ入れ替える。git pull → pull/build → running 確認 → `rm -f` → `up` を 1 コマンドにまとめ、順番間違いや走行中 `rm` の事故を防ぐ。ダウンタイムは差し替えの数秒だけ（pull / build 中は旧コンテナがそのまま動く）。

```shell
cd deploy
./update.sh both        # validator と web の両方
./update.sh validator   # validator だけ（ghcr から最新版を pull）
./update.sh web         # web だけ（このリポジトリのコードで rebuild）
./update.sh both --skip-pull   # git pull を省略（既に pull 済みのとき）
```

やること:

1. `git pull --ff-only` で最新コード＋version を取得（対象 version を表示）。
2. 対象を差し替え。
   - validator … `compose.sh pull validator`（版は `pyproject.toml` に自動追従）→ `rm -f ddbj-validator` → `up -d validator`。
   - web … `compose.sh build web` → `rm -f deploy_web_1` → `up -d web`。
3. `podman ps`・各コンテナの image・`/health` で稼働確認。

内蔵の安全策:

- `rm -f` の直前に検証が走っていないか確認し（`podman top ddbj-validator` に `sleep infinity` 以外のプロセスがあれば）走行中なら中止し、処理中の uuid を表示する（走行中に落とすとそのジョブが死ぬため）。web 差し替え時も確認する（web を止めると `podman exec` の親が死に、処理中の検証が巻き添えになる）。
- `git pull` は `--ff-only`。ローカルにコミットが溜まっている等の異常時はクリーンに中止する。
- `pyproject.toml` から version を取得できなければ中止する。

差し替え後、動作確認が済んでから不要なら `podman image prune -f` で dangling を掃除する（差し替え直後には実行しない）。

## 手動で差し替える場合

`update.sh` を使わず個別に確認しながら行うときの手順。

validator（ghcr の released イメージ。版は git pull に自動追従）:

```shell
cd deploy
git -C .. pull
./compose.sh pull validator
# running 確認（IDLE なら差し替え可）
podman top ddbj-validator | tail -n +2 | grep -vq 'sleep infinity' && echo RUNNING || echo IDLE
podman rm -f ddbj-validator
./compose.sh up -d validator
```

web（このリポジトリからビルド）:

```shell
cd deploy
git -C .. pull
./compose.sh build web
# running 確認（web を止めると受付も止まる）
podman rm -f deploy_web_1
./compose.sh up -d web
```
