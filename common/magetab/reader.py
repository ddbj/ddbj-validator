"""MAGE-TAB（IDF/SDRF TSV）の汎用パーサ。MetaboBank / GEA で共有。

app 固有の model クラス（Idf/Sdrf/Submission のサブクラス）と、整形不正時の rule_id を渡す。
戻り値は (submission, pre_errors)。読込失敗は pre_errors に積む。
"""
import csv
import re

from common.magetab.model import Idf, Sdrf, Submission


def _field_like(col0):
    """IDF フィールド名らしい短いトークンか（未定義フィールドの typo 検出／複数行セル判定用）。
    長い散文（複数行セルの継続行）は False。"""
    if not col0 or len(col0) > 50 or col0.rstrip().endswith("."):
        return False
    return bool(re.match(r"^[A-Z][A-Za-z0-9 \[\]/_-]{0,49}$", col0))


def _err(rule_id, message, level="error", target="#file_format"):
    return {"rule_id": rule_id, "level": level, "target": target, "sample": None, "message": message}


def parse_idf(path, idf_cls=Idf, known_fields=frozenset()):
    """IDF（key-value TSV）→ idf_cls。空行は直後の項目の blank_before として記録。
    引用符付きの複数行セル（Protocol Description 等）に対応するため csv.reader を使う。"""
    idf = idf_cls(raw_path=str(path))
    known = set(known_fields)
    prev_blank = False
    last_field = None
    with open(path, encoding="utf-8", newline="") as f:
        for row in csv.reader(f, delimiter="\t"):
            if not row or not any(c.strip() for c in row):
                prev_blank = True
                continue
            name = row[0].strip()
            # 既知フィールドでも field-like でもない col0 は、直前フィールドの複数行セル継続とみなし連結。
            if name != "" and name not in known and not _field_like(name) and last_field \
                    and idf.fields.get(last_field):
                idf.fields[last_field][-1] += "\n" + "\t".join(row)
                prev_blank = False
                continue
            if name == "":
                prev_blank = True
                continue
            values = [c for c in row[1:]]
            while values and values[-1].strip() == "":
                values.pop()
            if name in idf.field_order:
                idf.duplicate_fields.append(name)
            idf.fields.setdefault(name, [])
            idf.fields[name].extend(values)
            if name not in idf.field_order:
                idf.field_order.append(name)
            if prev_blank:
                idf.blank_before.add(name)
            prev_blank = False
            last_field = name
    return idf


def parse_sdrf(path, sdrf_cls=Sdrf):
    """SDRF（表形式 TSV）→ sdrf_cls。"""
    sdrf = sdrf_cls(raw_path=str(path))
    with open(path, encoding="utf-8", newline="") as f:
        rows = list(csv.reader(f, delimiter="\t"))
    rows = [r for r in rows if any(c.strip() for c in r)]  # 空行除去
    if rows:
        sdrf.header = [h.strip() for h in rows[0]]
        sdrf.rows = rows[1:]
    return sdrf


def parse(idf_path=None, sdrf_path=None, submission_cls=Submission, idf_cls=Idf, sdrf_cls=Sdrf,
          known_fields=frozenset(), idf_err_id="IR0001", sdrf_err_id="SR0001", account=None):
    sub = submission_cls(account=account)
    pre = []
    if idf_path:
        try:
            sub.idf = parse_idf(idf_path, idf_cls=idf_cls, known_fields=known_fields)
        except Exception as e:
            pre.append(_err(idf_err_id, f"IDF is not readable. ({e})"))
    if sdrf_path:
        try:
            sub.sdrf = parse_sdrf(sdrf_path, sdrf_cls=sdrf_cls)
        except Exception as e:
            pre.append(_err(sdrf_err_id, f"SDRF is not readable. ({e})"))
    return sub, pre
