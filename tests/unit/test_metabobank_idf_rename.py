"""MetaboBank の IDF フィールド名も新旧どちらで書かれていても同じ検証結果になること。

GEA 版（tests/unit/test_gea_idf_rename.py）と同じ狙い。MetaboBank の fixture は
すべて新名で書かれているので、**旧名へ戻した版**を作って突き合わせる。

移行が終わって `RENAMED_IDF_FIELDS` から旧名を消すときは、このテストを消すのが
最後の手順になる（消さずに旧名対応だけ外すと、このテストが落ちて気づける）。
"""
import pathlib
import pytest

from apps.metabobank import reader
from apps.metabobank.reader import RENAMED_IDF_FIELDS
from apps.metabobank.validator import Validator
from apps.metabobank.context import ValidationContext

DATA = pathlib.Path("apps/metabobank/tests/data")

STUDIES = ["MTBKS210", "MTBKS230", "MTBKS240", "MTBKS_msi"]

#: 新名 → 旧名（fixture を旧名へ戻すための逆引き）
_TO_OLD = {new: old for old, new in RENAMED_IDF_FIELDS.items()}


def _fired(idf_path, sdrf_path):
    sub, pre = reader.parse(str(idf_path), str(sdrf_path))
    ctx = ValidationContext(skip_db=True, skip_ncbi=True, skip_auth=True)
    return sorted({r["rule_id"] for r in list(pre) + Validator(ctx).run(sub)})


def _to_old_names(text):
    out = []
    for line in text.splitlines(True):
        name, tab, rest = line.partition("\t")
        out.append(_TO_OLD.get(name, name) + tab + rest if tab else line)
    return "".join(out)


def test_rename_map_is_injective():
    """新名が重複していないこと。重複すると旧名へ戻すときにどちらか一方しか作れない。"""
    assert len(_TO_OLD) == len(RENAMED_IDF_FIELDS)


@pytest.mark.parametrize("study", STUDIES)
def test_old_and_new_field_names_validate_identically(study, tmp_path):
    new_idf = DATA / f"{study}.idf.txt"
    sdrf = DATA / f"{study}.sdrf.txt"
    text = new_idf.read_text(encoding="utf-8")
    old_idf = tmp_path / f"{study}.idf.txt"
    old_idf.write_text(_to_old_names(text), encoding="utf-8")
    assert old_idf.read_text(encoding="utf-8") != text, f"{study} に改名対象が含まれていない（対象として無意味）"
    assert _fired(old_idf, sdrf) == _fired(new_idf, sdrf)


@pytest.mark.parametrize("study", STUDIES)
def test_renamed_fields_are_resolved_at_read_time(study, tmp_path):
    """旧名で書かれた IDF を読んでも、読み込み後は新名だけになること。"""
    text = (DATA / f"{study}.idf.txt").read_text(encoding="utf-8")
    old_idf = tmp_path / f"{study}.idf.txt"
    old_idf.write_text(_to_old_names(text), encoding="utf-8")
    sub, _ = reader.parse(str(old_idf), str(DATA / f"{study}.sdrf.txt"))
    leftover = sorted(set(sub.idf.field_order) & set(RENAMED_IDF_FIELDS))
    assert not leftover, f"{study}: 旧名が残っている {leftover}"
