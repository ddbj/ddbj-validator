"""中間ファイル（ワーカー → メインプロセスの JSONL）用の速い JSON 読み書き。

orjson があれば使い、無ければ標準の json を使う（2026-11-21）。エントリが多い登録では
結果の JSONL の読み書きが全体の 1 割前後を占めていたため。

- 使うのは **中間ファイルだけ**。利用者に見える validation_report.json などは標準の json の
  まま（書式が変わらないようにするため）。
- orjson が無くても動く。`-production` は update_validator.sh が pip install をしないので、
  orjson を入れるまでは標準の json で動く（結果は同じで、遅いだけ）。
- orjson が扱えない値（str 以外のキー、64 bit を超える整数、不正な文字を含む文字列など）は、
  その 1 件だけ標準の json で書く。読む側も同じ。どちらで書いた行も、どちらでも読める。
"""
import json

try:
    import orjson
except ImportError:  # pragma: no cover - orjson の無い環境
    orjson = None


def dumps_line(obj):
    """obj を 1 行の JSON（末尾に改行つき）の bytes にする。"""
    if orjson is not None:
        try:
            return orjson.dumps(obj, option=orjson.OPT_APPEND_NEWLINE)
        except TypeError:
            # orjson.JSONEncodeError は TypeError のサブクラス
            pass
    return (json.dumps(obj) + "\n").encode("utf-8")


def loads(line):
    """1 行の JSON（bytes か str）を読む。"""
    if orjson is not None:
        try:
            return orjson.loads(line)
        except ValueError:
            # orjson.JSONDecodeError は ValueError のサブクラス
            pass
    return json.loads(line)
