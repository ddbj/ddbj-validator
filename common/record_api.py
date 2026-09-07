"""record-api（DDBJ 内部 RDB の読み取り専用 REST API）のクライアント。

<https://record.ddbj.nig.ac.jp>（OpenAPI は `/docs`）。

**`DDBJ_RECORD_API_URL` が設定されているときだけ使う。** 未設定なら呼び出し側は
従来どおり内部 DB を直接引く。API 側の障害で validator 全体が止まらないよう、
失敗は例外にせず `None`（＝そのルールをスキップ）で返す。

いま使っているのは「account が引用できる ID の一覧」だけ。直 SQL との違いは:

- **`permitted`（他人の登録で外部参照を許可されたもの）を含む**
- **umbrella の BioProject を除く**（umbrella は直接データに紐づけられないので引用できない）
- accession 未発行のものを含まない
"""
import logging
import os

import requests

logger = logging.getLogger(__name__)

BASE_URL_ENV = "DDBJ_RECORD_API_URL"

# 一覧の取得上限。API 側の最大は 100,000。これを超える account では引用可否を
# 判定できないので、部分的な一覧で「引用不可」と言わずにスキップする（§fetch_citable）。
_LIMIT = 100_000
_TIMEOUT = 30


def base_url():
    """設定されていれば末尾スラッシュを落とした base URL、無ければ None。"""
    v = (os.environ.get(BASE_URL_ENV) or "").strip()
    return v.rstrip("/") or None


def enabled():
    return base_url() is not None


def fetch_citable(account, id_type):
    """account が引用できる ID の集合（大文字）を返す。判定できなければ None。

    `id_type` は API の path 名（`bioproject` / `biosample` / `dra_run` / `gea`）。

    **None を返すのは「引用不可と断定できない」場合**で、呼び出し側はルールごとスキップする:
      - API が未設定 / 応答しない / 想定外の形
      - **一覧が上限で切れた（`truncated`）** … 部分的な一覧で「引用不可」と言うと
        誤検知になる。account が巨大なケース（実例: `ngdc` は SAMD 846,545 件）で起きる
    """
    url = base_url()
    if not url or not account:
        return None
    try:
        r = requests.get(f"{url}/api/account/{account}/{id_type}",
                         params={"scope": "citable", "limit": _LIMIT}, timeout=_TIMEOUT)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        logger.warning("record-api %s の取得に失敗しました（このルールはスキップします）: %s", id_type, e)
        return None
    if data.get("truncated"):
        logger.warning("record-api %s の一覧が上限で切れました（account=%s, %s）。"
                       "部分的な一覧で引用不可と判定すると誤検知になるためスキップします。",
                       id_type, account, "; ".join(data.get("warnings") or []))
        return None
    results = data.get("results")
    if not isinstance(results, list):
        logger.warning("record-api %s の応答が想定外の形です（このルールはスキップします）", id_type)
        return None
    return {str(x.get("id")).strip().upper() for x in results if x.get("id")}
