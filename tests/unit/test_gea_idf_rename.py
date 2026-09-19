"""IDF フィールド名の新旧どちらでも同じ検証結果になることを確かめる。

GEA / MetaboBank で IDF のフィールド名を揃える改名を続けている（2026-09-18 / 2026-09-20）。
登録済みの IDF は旧名のままなので、読み込み時に `RENAMED_IDF_FIELDS` で新名へ読み替えている。

このテストは **旧名の IDF と新名の IDF が同じルール結果になること** を保証する。
移行が終わって `RENAMED_IDF_FIELDS` と `idf.legacy_fields` から旧名を消すとき、
「消したら旧名の IDF が通らなくなる」ことがこのテストの失敗として出るので、
消してよい時期かどうかを実際の挙動で判断できる。
"""
import pytest

from apps.gea import reader
from apps.gea.reader import RENAMED_IDF_FIELDS
from apps.gea.validator import Validator
from apps.gea.context import ValidationContext
from apps.gea.defs import load_definitions

DATA = __import__("pathlib").Path("apps/gea/tests/data")

#: 旧名を実際に含む fixture（新名へ書き換えた版と結果を突き合わせる）
STUDIES = ["E-GEAD-1104", "E-GEAD-1117", "COM0002-craft", "G0016-craft"]


def _fired(idf_path, sdrf_path):
    sub, pre = reader.parse(str(idf_path), str(sdrf_path))
    ctx = ValidationContext(skip_db=True, skip_ncbi=True, skip_auth=True)
    return sorted({r["rule_id"] for r in list(pre) + Validator(ctx).run(sub)})


def _to_new_names(text):
    """IDF 本文の行頭フィールド名を旧名 → 新名に書き換える。"""
    out = []
    for line in text.splitlines(True):
        name, tab, rest = line.partition("\t")
        out.append(RENAMED_IDF_FIELDS.get(name, name) + tab + rest if tab else line)
    return "".join(out)


@pytest.mark.parametrize("study", STUDIES)
def test_old_and_new_field_names_validate_identically(study, tmp_path):
    old_idf = DATA / f"{study}.idf.txt"
    sdrf = DATA / f"{study}.sdrf.txt"
    text = old_idf.read_text(encoding="utf-8")
    new_idf = tmp_path / f"{study}.idf.txt"
    new_idf.write_text(_to_new_names(text), encoding="utf-8")
    assert new_idf.read_text(encoding="utf-8") != text, f"{study} に旧名が含まれていない（対象として無意味）"
    assert _fired(old_idf, sdrf) == _fired(new_idf, sdrf)


def test_renamed_fields_are_resolved_at_read_time():
    """読み込み後の IDF に旧名が 1 つも残らないこと。"""
    for study in STUDIES:
        sub, _ = reader.parse(str(DATA / f"{study}.idf.txt"), str(DATA / f"{study}.sdrf.txt"))
        leftover = sorted(set(sub.idf.field_order) & set(RENAMED_IDF_FIELDS))
        assert not leftover, f"{study}: 旧名が残っている {leftover}"


def test_legacy_fields_are_either_renamed_or_deliberately_dropped():
    """`idf.legacy_fields` の各名は、読み替え先があるか、意図して捨てた名であること。

    どちらでもない名は「旧名として許すだけで誰も読まない」死んだ定義になる。
    """
    #: 読み替え先を持たない旧名（項目ごと廃止したもの）
    DROPPED = {"Comment[Array Design REF]"}
    legacy = set(load_definitions()["idf"]["legacy_fields"])
    orphan = sorted(legacy - set(RENAMED_IDF_FIELDS) - DROPPED)
    assert not orphan, f"読み替え先も廃止理由も無い legacy_fields: {orphan}"
