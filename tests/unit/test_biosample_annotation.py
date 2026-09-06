"""BioSample の annotation 列が D-way 本番 ruby の実測と一致することを固定する。

message はレポート出力時に公式文言で上書きされる（`reporter._error_obj`）ため、
**個別の値は annotation に載っていないと登録者に届かない**。列見出しは D-way の表示に
一致している必要があるので（`docs/biosample/rule_pattern.md`）、
`tests/regression/*/prod.json`（ruby 本番の実測）を正として突き合わせる。

実行: リポジトリルートで `.venv/bin/python -m pytest`
"""
import json
from pathlib import Path

import pytest

from apps.biosample.reporter import _annotation

REG = Path("apps/biosample/tests/regression")


def _ruby_annotations(rule_id):
    """regression の prod.json から、その rule の annotation 実測を集める。"""
    out = []
    for f in sorted(REG.glob("*/prod.json")):
        for m in json.loads(f.read_text(encoding="utf-8")).get("messages") or []:
            if m.get("id") == rule_id and m.get("annotation"):
                out.append((f.parent.name, m["annotation"]))
    return out


def _keys(anno):
    return [a["key"] for a in anno]


# --- BS_R0129（derived_from の未登録 accession）-------------------------

def test_r0129_annotation_matches_ruby():
    """Sample name · Attribute · Invalid Accession IDs の 3 列で、値まで一致すること。"""
    ruby = _ruby_annotations("BS_R0129")
    assert ruby, "regression に BS_R0129 の実測が無い"
    for name, want in ruby:
        sample = want[0]["value"]
        samd = want[2]["value"]
        got = _annotation({
            "rule_id": "BS_R0129", "level": "warning", "sample": sample, "message": "...",
            "anno_cols": [{"key": "Attribute", "value": "derived_from"},
                          {"key": "Invalid Accession IDs", "value": samd}],
        })
        assert got == want, f"{name}: {got} != {want}"


def test_r0129_reports_the_accession():
    """どの accession が問題かが annotation に出ること（公式文言では分からないため）。"""
    got = _annotation({
        "rule_id": "BS_R0129", "level": "warning", "sample": "S1", "message": "...",
        "anno_cols": [{"key": "Attribute", "value": "derived_from"},
                      {"key": "Invalid Accession IDs", "value": "SAMD99999999"}],
    })
    assert _keys(got) == ["Sample name", "Attribute", "Invalid Accession IDs"]
    assert got[-1]["value"] == "SAMD99999999"


# --- 列見出しの綴りは ruby に合わせる（勝手に直さない）-------------------

@pytest.mark.parametrize("rule_id", ["BS_R0132", "BS_R0133"])
def test_multi_pattern_keeps_ruby_spelling(rule_id):
    """`attibutes` は ruby 本番の綴り。D-way の表示に合わせるため直さない。

    こちらの typo ではないので、直すと D-way の表示と食い違う。
    変えるなら D-way 側と合わせて変える（本テストが歯止め）。
    """
    ruby = _ruby_annotations(rule_id)
    assert ruby, f"regression に {rule_id} の実測が無い"
    for name, want in ruby:
        assert _keys(want) == ["Sample name", "package", "attibutes"], name
        got = _annotation({
            "rule_id": rule_id, "level": "warning", "sample": want[0]["value"], "message": "...",
            "anno_cols": [{"key": "package", "value": want[1]["value"]},
                          {"key": "attibutes", "value": want[2]["value"]}],
        })
        assert got == want, f"{name}: {got} != {want}"
