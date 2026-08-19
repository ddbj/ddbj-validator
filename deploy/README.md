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
   - validator … `compose.sh pull validator`（版は `pyproject.toml` に自動追従）→ `rm -f $DDBJ_VALIDATOR_NAME` → `up -d validator`。
   - web … `compose.sh build web` → `rm -f ${DDBJ_COMPOSE_PROJECT}_web_1` → `up -d web`。
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
# コンテナ名は <DDBJ_COMPOSE_PROJECT>_web_1（例 ddbj-validator-staging_web_1）
podman rm -f "$(sed -n 's/^DDBJ_COMPOSE_PROJECT=//p' .env | tr -d '"')_web_1"
./compose.sh up -d web
```

## 死活監視プローブ — `monitor-probe.sh`

外部（構築チーム居室の s1）から ssh で呼ばれ、**事実を JSON 1 行で返す読み取り専用**スクリプト。
判定に必要な期待値は同じクローンの `deploy/.env` と `pyproject.toml` から自分で導くので、
呼び出し側に版番号や環境名を持たせない（リリースごとの設定更新が不要）。

```shell
./monitor-probe.sh quick      # /health のみ（数 ms。高頻度用）
./monitor-probe.sh host       # コンテナ・版の3点照合・run 滞留・ログ・容量（HTTP パイプライン検証なし）
./monitor-probe.sh deep       # host + /monitoring（実 XML がパイプライン全体を通る。約 3 秒）
./monitor-probe.sh contract   # deep + 実 POST /validation → status → result 検証 → run dir 削除
```

**常に exit 0 で JSON を返す**。呼び出し側は次のように区別する:

| 判定 | 条件 | 意味 |
|---|---|---|
| OK | JSON の `ok=true` | 正常 |
| NG | JSON の `ok=false`（`failures[]` に理由） | サービス異常（ホストは生存） |
| UNREACHABLE | ssh / 実行そのものが失敗 | ホストまたは経路の障害 |

検査項目と、それが捕まえる障害:

- **版の3点照合**（`pyproject.toml` / 稼働 validator の image tag / コンテナ内 `__version__`）
  … 別クローンで `update.sh` を実行して本番が旧版のままになる事故（2026-08 に発生）
- **迷子コンテナ**（この環境以外の名前で ddbj-validator が動いていないか）… 同上
- `/health` の 200 と `env` が `.env` と一致 … プロセス死・監視先の取り違え
- `/monitoring`（deep 以上）… パイプライン全体＋run dir 用 shard の書込可否（500 の原因クラス）
- run の滞留（`running`/`accepted` が 30 分超）・直近 1h の `error` 件数
- `.monitoring-*` 残骸数（所有権事故の再発カナリア。実行中の一時ディレクトリを誤検知しないよう 10 分より古いものだけ数える）・`web.log` の ERROR・`df`
- `contract` は D-way と同じ API 契約（multipart → uuid → status 遷移 → result）を通し、
  `result.json` の version と BS_R0027 の発火を検証したうえで**自分が作った run dir を削除**する
  （合成データを運用履歴に残さない。入力ファイル名 `SSUB000000.xml` で二重確認してから削除）

しきい値は環境変数で上書き可: `STUCK_MIN`(30) `ERR_MAX`(5) `LEAK_MAX`(0) `LEAK_MIN_AGE`(10) `WEBLOG_ERR_MAX`(0) `DF_MAX`(85) `CONTRACT_TIMEOUT`(120)。

実行ごとに `~/.cache/ddbj-validator-monitor/heartbeat-<env>` を更新する。s1 が死んだ場合に
気づくため、ホスト側の cron でこのファイルの鮮度を見る（s1 はすぱこん側から到達できないので、
heartbeat は s1 が書き込み、ホストが自分で鮮度を判定する）。

### 監視の実行側 — `monitor-s1.sh`（s1 に配置）/ `monitor-heartbeat-check.sh`（a011 の cron）

監視本体はすぱこん外（構築チーム居室の s1）で動かす。停電・クラッシュで監視ごと道連れに
ならないようにするため。s1 → gateway → a011/a012 の ssh で `monitor-probe.sh` を呼ぶ。

**s1 側の準備**（`~/monitor` に置く運用）

```shell
mkdir -p ~/monitor
scp w3const@a012:ddbj-validator-api-staging/deploy/monitor-s1.sh ~/monitor/
chmod +x ~/monitor/monitor-s1.sh
mkdir -p ~/.config/ddbj-validator-monitor
printf '%s\n' '<Slack Incoming Webhook URL>' > ~/.config/ddbj-validator-monitor/webhook
chmod 600 ~/.config/ddbj-validator-monitor/webhook
```

`~/.ssh/config`（gateway 経由。`User` は w3const、鍵は監視専用。`Host a011` の設定は
継承されないので `ProxyCommand` をこのブロックにも書く）:

```
Host a011-monitor
    HostName a011
    User w3const
    ProxyCommand ssh -W %h:%p sc
    IdentityFile ~/.ssh/ddbj_monitor
    IdentitiesOnly yes
    BatchMode yes
    ConnectTimeout 10
```

**cron（s1）** — crontab では `~` を使わず絶対パスで書く。重いモードは分をずらす
（mode ごとにロックを取るので重複起動は自動スキップされる）。

```cron
MAILTO=""
*/1              * * * * TARGETS="a011-monitor:production" /home/ykodama/monitor/monitor-s1.sh quick    >> /home/ykodama/monitor/monitor.log 2>&1
*/5              * * * * TARGETS="a011-monitor:production" /home/ykodama/monitor/monitor-s1.sh deep     >> /home/ykodama/monitor/monitor.log 2>&1
3,13,23,33,43,53 * * * * TARGETS="a011-monitor:production" /home/ykodama/monitor/monitor-s1.sh host     >> /home/ykodama/monitor/monitor.log 2>&1
17 */6           * * *   TARGETS="a011-monitor:production" /home/ykodama/monitor/monitor-s1.sh contract >> /home/ykodama/monitor/monitor.log 2>&1
*/10             * * * * TARGETS="a012-monitor:staging"    /home/ykodama/monitor/monitor-s1.sh quick    >> /home/ykodama/monitor/monitor.log 2>&1
*/30             * * * * TARGETS="a012-monitor:staging"    /home/ykodama/monitor/monitor-s1.sh deep     >> /home/ykodama/monitor/monitor.log 2>&1
23 3             * * *   TARGETS="a012-monitor:staging"    /home/ykodama/monitor/monitor-s1.sh contract >> /home/ykodama/monitor/monitor.log 2>&1
30 7             * * *   TARGETS="a011-monitor:production a012-monitor:staging" /home/ykodama/monitor/monitor-s1.sh summary >> /home/ykodama/monitor/monitor.log 2>&1
5 0 1            * *     : > /home/ykodama/monitor/monitor.log
```

**異常時のみメンションする**（復旧通知と日次サマリには付けない）。既定は `NG` が `<!here>`、
`UNREACHABLE`・同時不通・heartbeat 途切れが `<!channel>`。s1 の
`~/.config/ddbj-validator-monitor/config` で変更でき、空文字にすればメンションしない。
Webhook では `@name` は効かず、`<!here>` / `<!channel>` / `<@U012ABCDEF>`（member ID）/
`<!subteam^S012ABCDEF>` のエスケープ記法を使う。

判定は 4 状態（`OK` / `NG`＝サービス異常・ホストは生存 / `UNREACHABLE`＝ホストか経路の障害 /
`CONFIG`＝監視設定の誤り）。**通知は状態が変わったときだけ**で、同じ異常が連続 N 回
（quick は 3 回、他は 2 回）続いて初めて発報し、復旧時にも 1 通出す。全対象が同時に
`UNREACHABLE` のときは 1 通に集約する（サイト障害を N 件に分裂させない）。

**a011 側（s1 が落ちたときに気づくための dead-man）**

```cron
*/10 * * * * /home/w3const/ddbj-validator-api-production/deploy/monitor-heartbeat-check.sh >> ~/log/ddbj-heartbeat.log 2>&1
```

probe は実行ごとに `~/.cache/ddbj-validator-monitor/heartbeat-<env>` を更新する。この鮮度が
30 分を超えたら「外部監視が止まっている可能性」として **すぱこん側から** Slack へ通知する
（a011 から `hooks.slack.com` へ到達できることは実測済み）。`/home/w3const` は a011/a012 で
共有なので、**この cron は a011 だけに置く**（1 本で両環境分を見る。両方に置くと二重通知）。

Slack webhook はすぱこん側にも必要: `~/.config/ddbj-validator-monitor/webhook`（chmod 600、共有 home なので 1 つ置けば両ホストで使える）。
