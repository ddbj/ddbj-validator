#!/usr/bin/env bash
# run dir（DATA_DIR 配下の検証イベント）を日次で lustre に tar 退避する。
#
# なぜ: /data1 は単体 NVMe（RAID なし）で、飛ぶと run dir は全損する。D-way は結果を
#       自前で保存していないため、失うと result.json / reports/ / fixed/ を再現できない
#       （その時点のルールと DB で出た結果のため）。念のための保険として取る。
#
# 方針:
# - **/data1 側は削除しない**（クリーンアップは別運用。この script は読むだけ）。
# - 前日分（mtime が対象日の 00:00〜翌 00:00）の run dir を 1 本の tar.zst にまとめる。
#   日をまたいで実行中だったものは完了時に mtime が翌日になるので、翌日の分に入る（取りこぼさない）。
# - lustre は小ファイルが苦手（run dir は 1 日 8,000 ファイル超）。ファイルのまま置かず
#   必ず 1 日 1 アーカイブに固める。
# - production 専用。staging は取らない（.env の DDBJ_ENV で弾く）。
#
# 使い方:
#   ./backup-rundir.sh                # 前日分
#   ./backup-rundir.sh 2026-09-08     # 日付指定（再取得は --force）
#   ./backup-rundir.sh 2026-09-08 --force
#
# cron（a011 のみ）:
#   10 3 * * * /home/w3const/ddbj-validator-api-production/deploy/backup-rundir.sh >> /home/w3const/log/ddbj-validator-backup.log 2>&1
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
log() { echo "$(date '+%F %T') $*"; }
die() { log "!! $*"; exit 1; }

env_val() { sed -n "s/^$1=//p" "$here/.env" | tr -d '"' | head -1; }

day=""
force=""
for a in "$@"; do
  case "$a" in
    --force) force=1 ;;
    ????-??-??) day="$a" ;;
    *) die "不明な引数: $a（usage: $0 [YYYY-MM-DD] [--force]）" ;;
  esac
done
day="${day:-$(date -d yesterday +%F)}"
next="$(date -d "$day +1 day" +%F)"

# production 専用。staging クローンから叩かれた場合はここで止める。
env_name="$(env_val DDBJ_ENV)"
[ "$env_name" = "production" ] || die "production 専用です（DDBJ_ENV=${env_name:-未設定}）"

DATA="$(env_val DDBJ_DATA_DIR_HOST)"
[ -n "$DATA" ] || die ".env から DDBJ_DATA_DIR_HOST を取得できません"
[ -d "$DATA" ] || die "DATA_DIR がありません: $DATA（production は a011 で実行してください）"

OUT="${DDBJ_BACKUP_DIR:-$HOME/backup/ddbj-validator/production}"
mkdir -p "$OUT"
archive="$OUT/${day}.tar.zst"
if [ -e "$archive" ] && [ -z "$force" ]; then
  log "既にあるのでスキップ: $archive（再取得は --force）"
  exit 0
fi

# 対象 run dir を列挙（DATA_DIR/<shard 2桁hex>/<uuid>/）。
# monitor-probe の $DATA/.monitoring-XXXX/ は shard 名にマッチしないので自然に除外される。
list="$(mktemp)"
trap 'rm -f "$list"' EXIT
find "$DATA" -mindepth 2 -maxdepth 2 -type d \
  -regextype posix-extended \
  -regex '.*/[0-9a-f]{2}/[0-9a-f-]{36}' \
  -newermt "$day 00:00" ! -newermt "$next 00:00" \
  -printf '%P\n' 2>/dev/null | sort > "$list" || true

n="$(grep -c . "$list" || true)"
if [ "$n" -eq 0 ]; then
  log "$day: 対象なし（run dir 0 件）。アーカイブは作りません"
  exit 0
fi

# web.log（web サーバのログ。RotatingFileHandler で 10MB×3 しか残らないため一緒に退避）。
# 過去日を後追いで取るとき（backfill）は「いまの web.log」が入っても紛らわしいだけなので、
# 通常運用の対象日（＝前日）のときだけ入れる。
if [ "$day" = "$(date -d yesterday +%F)" ] && [ -f "$DATA/web.log" ]; then
  echo "web.log" >> "$list"
fi

log "$day: run dir ${n} 件を退避 → $archive"
tmp="$archive.part"
tar --create --directory "$DATA" --files-from "$list" \
  | zstd -q -9 -T0 -o "$tmp" -f
zstd -q -t "$tmp" || die "アーカイブ検証に失敗: $tmp"
mv -f "$tmp" "$archive"
log "$day: 完了 $(du -h --apparent-size "$archive" | cut -f1)（/data1 側は削除していません）"
