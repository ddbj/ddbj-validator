# -*- coding: utf-8 -*-
"""common/xmltext.py（XML 全要素の走査と非 ASCII 抽出）の挙動固定。

BP_R0060 / BS_R0058 / DRA_R0050 が共有する純関数なので、ここで壊れないようにしておく。
"""
import xml.etree.ElementTree as ET

from common.xmltext import iter_values, literal_non_ascii, non_ascii_values

SAMPLE = """<?xml version="1.0" encoding="UTF-8"?>
<Root id="R1">
  <Owner><Name>NIG</Name></Owner>
  <Pub id="1"><Title>First</Title></Pub>
  <Pub id="2"><Title>Second</Title></Pub>
</Root>
"""


def _paths(xml):
    return [p for _el, p, _v in iter_values(ET.fromstring(xml))]


def test_walks_text_and_attributes():
    paths = _paths(SAMPLE)
    assert "Root@id" in paths          # 属性値
    assert "Root/Owner/Name" in paths   # 要素テキスト


def test_repeated_siblings_get_index():
    paths = _paths(SAMPLE)
    # 同名の兄弟が複数あるときだけ添字が付く（Owner には付かない）
    assert "Root/Pub[1]/Title" in paths and "Root/Pub[2]/Title" in paths
    assert "Root/Owner/Name" in paths


def test_blank_text_is_skipped():
    vals = [v for _el, _p, v in iter_values(ET.fromstring("<a><b>  </b><c>x</c></a>"))]
    assert vals == ["x"]


def test_mixed_content_tail_is_collected():
    vals = [v for _el, _p, v in iter_values(ET.fromstring("<a>head<b>in</b>tail</a>"))]
    assert set(vals) == {"head", "in", "tail"}


def test_literal_non_ascii_ignores_character_references(tmp_path):
    ref = tmp_path / "ref.xml"
    ref.write_text('<?xml version="1.0" encoding="UTF-8"?><a>25 &#x2103;</a>', encoding="utf-8")
    assert literal_non_ascii(ref) == set()

    raw = tmp_path / "raw.xml"
    raw.write_text('<?xml version="1.0" encoding="UTF-8"?><a>25 ℃</a>', encoding="utf-8")
    assert literal_non_ascii(raw) == {"℃"}


def test_non_ascii_values_filtered_by_literal_set():
    root = ET.fromstring("<a><b>25 ℃</b><c>plain</c></a>")
    # literal が空集合 = ソースはすべて文字参照 → 報告しない
    assert list(non_ascii_values(root, literal=set())) == []
    # literal に素の文字がある → 報告する
    hits = [(p, v) for _el, p, v in non_ascii_values(root, literal={"℃"})]
    assert hits == [("a/b", "25 ℃")]
