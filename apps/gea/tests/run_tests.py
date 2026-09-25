#!/usr/bin/env python3
"""GEA validator E2E。

既定（ローカル）: apps/gea/tests/data/ の実例（-l）で発火 rule_id を検証（DB 非依存・既定ゲート用）。
`--db`（opt-in・要内部 DB＋dradev アカウント）: dordb の dradev テスト submission を DB モードで検証し、
DRA/DB cross（REF）系の発火を検証する。既定集合には含めない（DB のあるマシンで明示実行）。
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT))

from apps.gea.context import ValidationContext
from apps.gea.validator import Validator
from apps.gea import reader

from common.e2e import run_expected_sets
DATA = HERE / "data"

# --- ローカル（既定） ---
EXPECTED = {
    "E-GEAD-1104": set(),                             # microarray, clean
    "E-GEAD-1114": set(),                             # sequencing, clean
    "E-GEAD-1117": set(),                             # microarray, protocol desc 最短 54 文字（閾値 30 では発火しない）
    "E-GEAD-1144": set(),                             # sequencing, Experiment Description 68 文字（20〜4,000 の範囲内）、protocol desc 最短 85 文字
    # crafted fixture: SRA_RUN ≠ Array Data File（TSV のみ・DB 不要）→ REF0007 error
    "REF0007-craft": {"GEA_REF0007"},
    # crafted fixture（E-GEAD-1144 派生）: Experiment Description を 19 文字 / 4,001 文字にして G0009 の下限・上限を担保
    "G0009-short-craft": {"GEA_G0009"},
    "G0009-long-craft": {"GEA_G0009"},
    # crafted fixture（E-GEAD-1117 派生）: Comment[Submission Type] を CV 外（小文字 microarray）にして
    # CV チェック（GEA_COM0002）を担保。専用ルール GEA_G0014 は 2026-09-18 に廃止し COM0002 に統合した
    "COM0002-craft": {"GEA_COM0002"},
    # crafted fixture（E-GEAD-1117 派生）: Comment[Submission Date] を YYYY/MM/DD にして G0015 を担保
    "G0015-craft": {"GEA_G0015"},
    # crafted fixture（E-GEAD-1114 派生）: 列の有無を見る 3 ルール（2026-09-21 追加）。
    # 死んだ定義 sdrf.required_columns_error / _warning を消した代わりに個別ルールで見る形にしたもの。
    "SR0013-craft": {"GEA_SR0013"},     # Comment[BioSample] 列なし（error ＋ ignore）
    "FV0002-craft": {"GEA_FV0002"},     # Factor Value[...] 列が 1 本も無い（warning）
    "LC0002-craft": {"GEA_LC0002"},     # Comment[INSTRUMENT_MODEL] 列なし（error ＋ ignore・sequencing 限定）
    # crafted fixture（E-GEAD-1117 派生）: **初の Xenium fixture**。Submission Type=Xenium、
    # experiment type を spatial transcriptomics by imaging に、protocol を Xenium の必須 5 種にした
    # 移行後の姿。これで Xenium 限定ルール（GEA_G0016 / PR0017 / PR0018 / MAN0014）が E2E に載る。
    "MAN0014-craft": {"GEA_MAN0014"},        # tissue_preservation_method 列なし
    "MAN0014-pass-craft": set(),             # 同列あり → 発火なし（Xenium の clean な形）
    # crafted fixture（E-GEAD-1114 派生）: LIBRARY_STRATEGY を DRA の語彙に無い値にして GEA_LC0003 を担保。
    # 比較は大文字小文字・区切りを無視するので、旧綴り（RNA_SEQ 等）では発火しない。
    "LC0003-craft": {"GEA_LC0003"},
    # crafted fixture（E-GEAD-1104 派生）: Material Type 全必須（2026-09-20）の 2 分岐。
    # ① 列ごと無い（旧 GEA_EX0002 の担当範囲）② 列はあるが 1 行だけ空
    # ②は旧 GEA_MT0001 が「全行空」しか見なかったため**何も出なかった**ケース。ここが MT0002 の主眼。
    "MT0002-craft": {"GEA_MT0002"},
    "MT0002-blank-craft": {"GEA_MT0002"},
    # crafted fixture（E-GEAD-1117 派生）: Comment[tissue_preservation_method] を IDF/SDRF 両方 CV 外にして COM0004 を担保
    "COM0004-craft": {"GEA_COM0004"},
    # crafted fixture（E-GEAD-1104 派生）: Submission Type=Microarray に Sequencing 用の experiment type を
    # 入れて G0016（sub type と exp type の整合）を担保。語自体は CV 内なので COM0002 は出ない
    "G0016-craft": {"GEA_G0016"},
    # crafted fixture（E-GEAD-1114 派生）: Sequencing の IDF から Sequencing protocol を落とす。
    # PR0019（raw があるときだけ必須の protocol）＋ AN0003（SDRF の node に繋がっているか）に加え、
    # SDRF の Protocol REF が IDF に解決しなくなるので REF0001（only in SDRF = error）も出る。
    # → 「値形式（旧 REGEX0002/0010）を外しても名前の解決は REF0001 が担保する」ことの確認を兼ねる
    "PR0019-craft": {"GEA_PR0019", "GEA_AN0003", "GEA_REF0001"},
    # crafted fixture（E-GEAD-1114 派生）: Extraction protocol を Labeling protocol にすり替える。
    # PR0017（その sub type では使わない protocol）と PR0018（必須の Extraction が無い）の 2 本
    "PR0017-craft": {"GEA_PR0017", "GEA_PR0018"},
    # crafted fixture（E-GEAD-1114 派生）: raw を magic word none にし、SRA 参照列と seq 系 protocol を落とす。
    # Skip = raw-less が効いていれば PR0019 / EX0004 / AN0003 / MAN0012 は **出ない**。
    # 残るのは SR0003（raw が none）と PN0001（値が全部空になった Protocol REF 列）だけ
    "rawless-craft": {"GEA_SR0003", "GEA_PN0001"},
    # crafted fixture（E-GEAD-1104 派生）: Raw Data File を magic word none にして SR0003 を担保
    "SR0003-craft": {"GEA_SR0003"},
    # crafted fixture（E-GEAD-1104 派生・2026-09-24 追加）: ヘッダー行の形の 2 ケース。
    # どちらも「書いた値が黙って捨てられる」ため、以前は 0 error 0 warning で素通りしていた。
    "SR0014-craft": {"GEA_SR0014"},   # Raw Data File の右に名前の無い列（値あり）
    "SR0015-craft": {"GEA_SR0015"},   # ヘッダーより 1 列長い行（値あり）
    # crafted fixture（E-GEAD-1104 派生・2026-09-24 追加）: Comment[Experiment Type] を 2 値にする。
    # 2 つ目は Microarray で許可された語にしてあるので G0016 は出ず、COM0005 だけが出る
    "COM0005-craft": {"GEA_COM0005"},
    # crafted fixture（E-GEAD-1104 派生・2026-09-24 追加）: Raw Data File 列を 2 本にし、
    # 2 本目に 1 本目と同じファイル名を入れる。列をまたいだ同名＝どちらかの書き間違い
    "DF0003-craft": {"GEA_DF0003"},
    # crafted fixture（2026-09-26 追加。MetaboBank の MB_IR0024 / MB_SR0030 / MB_SR0036 / MB_SR0050 に相当）
    # E-GEAD-1104 派生: IDF の説明文と SDRF のセルを日本語＋全角数字にし、raw のファイル名も日本語に。
    # 非 ASCII は ASCII 化できたものが warning、できなかったものが error。ファイル名は DF0004。
    "nonascii-craft": {"GEA_G0017", "GEA_SR0016", "GEA_DF0004"},
    # E-GEAD-1114 派生: 2 行目と 3 行目で同じ Assay Name なのに DRX が違う
    "AN0010-craft": {"GEA_AN0010"},
}

# --- DB モード（opt-in / dradev） ---
# DB モードで「DB 依存ルール（requires_rdb/auth）∪ error 級」の発火を検証。
# key が ESUB… は dordb 由来の実 submission、それ以外は DATA/ の crafted fixture（本番登録不可な error 用）。
# ※ 002704/002705/002710 は重複 LIBRARY 列テンプレートで作られており RC0002（重複列）＋
#   LC0001（重複列の空セル）が構造的に発火する（002706 のみ重複なし＝真にクリーン）。
GEA_DB_ACCOUNT = "dradev"
GEA_DB_EXPECTED = {
    "ESUB002709": set(),                              # microarray, external ADF acc ref OK
    "ESUB002708": set(),                              # microarray, ADF file submit OK
    "ESUB002706": set(),                              # sequencing, DRA Run ref ext-permit all OK（重複列なし）
    "ESUB002705": {"GEA_LC0004", "GEA_REF0003", "GEA_REF0004", "GEA_LC0001"},  # partial ＋ 重複列
    "ESUB002704": {"GEA_LC0004", "GEA_LC0001"},       # DRA Run ref OK ＋ 重複列
    # ※ dradev のテスト submission は SDRF の library メタデータが DRA の Experiment と食い違っている
    #    （LIBRARY_SOURCE / SELECTION / STRATEGY / INSTRUMENT_MODEL）。GEA_LC0004（warning）が拾う。
    #    綴り違い（RNA_SEQ ↔ RNA-Seq）は正規化して除いてあるので、残るのは実質的な不一致だけ。
    # 存在しない SAMD00000000（正規表現は通るが DB に無い）→ REF0009、triple 不一致で REF0008、重複列で LC0001
    # ※ sync 属性を ddbj biosample_sync（common）に絞ったため sample_name 不一致では BS0003 は発火しない（→ BS0003-craft で担保）
    "ESUB002710": {"GEA_LC0004", "GEA_REF0009", "GEA_REF0008", "GEA_LC0001"},
    # crafted fixture: bogus A-GEAD-999999（自 account 未登録かつ非公開でない）→ REF0005 error
    "REF0005-craft": {"GEA_REF0005"},
    # crafted fixture（ESUB002710 派生）: sync 対象 collection_date を BS と不一致にして BS0003（warning・requires_rdb）を担保
    "BS0003-craft": {"GEA_LC0004", "GEA_REF0009", "GEA_REF0008", "GEA_BS0003", "GEA_LC0001"},
    # crafted fixture（BS0003-craft 派生）: SAMD00000000 → **実在するが dradev 所有でない** SAMD00000002 に差し替え。
    # REF0009（存在しない）と REF0002（存在するが account 外）の**切り分け**を担保する。
    "REF0002-craft": {"GEA_LC0004", "GEA_REF0002", "GEA_REF0008", "GEA_BS0003", "GEA_LC0001"},
}


def _fired(study):
    sub, pre = reader.parse(str(DATA / f"{study}.idf.txt"), str(DATA / f"{study}.sdrf.txt"))
    ctx = ValidationContext(skip_db=True, skip_ncbi=True, skip_auth=True)
    results = list(pre) + Validator(ctx).run(sub)
    return {r["rule_id"] for r in results}


def _db_rule_ids():
    """DB 依存（requires_rdb / requires_auth）ルールの rule_id 集合。"""
    return {r.rule_id for r in Validator(ValidationContext()).active_rules
            if getattr(r, "requires_rdb", False) or getattr(r, "requires_auth", False)}


def _migrate_sdrf_header(sdrf_text):
    """dordb の SDRF ヘッダを**移行後の列名**に直す（test 専用）。

    新 GEA の SDRF は raw 側を MetaboBank と同じ `Raw Data File`（旧 `Array Data File` と
    `Array Data Matrix File` を統合）、processed 側を `Processed Data File`
    （旧 `Derived Array Data File` と `Derived Array Data Matrix File` を統合）にし、
    旧名は移行で変換する。dordb には変換前のデータしか無いので、ここで列名だけ移行後の姿にしてから検証する
    （変換しないと GEA_DF0001 等が「raw 列が無い」として出てしまい、テストの意味が無くなる）。
    """
    if not sdrf_text:
        return sdrf_text
    head, sep, rest = sdrf_text.partition("\n")
    ren = {"Array Data File": "Raw Data File",
           "Array Data Matrix File": "Raw Data File",
           "Derived Array Data File": "Processed Data File",
           "Derived Array Data Matrix File": "Processed Data File"}
    cells = [ren.get(c.strip(), c) for c in head.split("\t")]
    return "\t".join(cells) + sep + rest


def _db_fired(key, account):
    """key が ESUB… は dordb から取得、それ以外は DATA/<key>.idf.txt/.sdrf.txt（crafted fixture）を DB モード検証。
    「DB 依存ルール ∪ error 級」の発火 rule_id を返す。"""
    import tempfile
    from common.db_manager import DatabaseManager
    from apps.gea import db_meta
    from apps.gea.cli import _fetch_account_refs, _fetch_biosample_attrs, _fetch_db_submission_type
    if key.startswith("ESUB"):
        gc = DatabaseManager().get_gea_conn()
        idf, sdrf = db_meta.fetch_experiment_metadata(gc, key)
        td = Path(tempfile.mkdtemp())
        ip, sp = td / f"{key}.idf.txt", td / f"{key}.sdrf.txt"
        ip.write_text(idf or "", encoding="utf-8")
        sp.write_text(_migrate_sdrf_header(sdrf or ""), encoding="utf-8")
    else:
        ip, sp = DATA / f"{key}.idf.txt", DATA / f"{key}.sdrf.txt"
    sub, pre = reader.parse(str(ip), str(sp), account=account)
    ctx = ValidationContext(account=account, skip_db=False, skip_ncbi=False, skip_auth=False)
    # dordb の既存 submission は IDF に Comment[Submission Type] を持たない（移行で付与する項目）。
    # CLI と同じ経路で DB の数値 submission type から補う（type 限定ルールを走らせるため）。
    _fetch_db_submission_type(ctx, sub, key if key.startswith("ESUB") else None)
    _fetch_biosample_attrs(ctx, sub, account)
    _fetch_account_refs(ctx, sub, account)
    results = list(pre) + Validator(ctx).run(sub)
    db_ids = _db_rule_ids()
    return {r["rule_id"] for r in results if r["rule_id"] in db_ids or r.get("level") == "error"}


def main(argv):
    if "--db" in argv:
        try:
            from dotenv import load_dotenv
            load_dotenv(str(ROOT / ".env"))
        except ImportError:
            pass
        return run_expected_sets("GEA", GEA_DB_EXPECTED, lambda e: _db_fired(e, GEA_DB_ACCOUNT),
                                 header="=== GEA DB-mode E2E (opt-in, dradev) ===")
    return run_expected_sets("GEA", EXPECTED, _fired, header="=== GEA local E2E ===")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
