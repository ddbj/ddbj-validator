"""DDBJ Record の taxonomy_id は書かれたままの str（ddbj-record-specifications#11）。

reader も autofix もそれを数として扱わないことを固定する。harness のフィクスチャは
値のある taxonomy_id しか持たないので、空の slot と autofix の書き戻しはここで見る。

実行: リポジトリルートで `.venv/bin/python -m pytest tests/unit`
"""
import json

from apps.biosample import autofix
from apps.biosample import record_reader


def _sample(organism):
    return {
        "alias":      "S1",
        "package":    "Microbe",
        "organism":   organism,
        "attributes": [{"name": "taxonomy_id", "value": "562"}]
    }


def test_blank_slot_falls_back_to_the_attribute(tmp_path):
    """organism.name と同じく、空の slot は「書かれていない」として属性の値を採る。
    採らないと属性はバッグから外されたまま、taxonomy_id が空として検証される。"""
    path = tmp_path / "record.json"
    path.write_text(json.dumps({
        "schema_version": "v3",
        "samples":        [_sample({"name": "Escherichia coli", "taxonomy_id": " "})]
    }), encoding="utf-8")

    submission, _ = record_reader.parse_record(str(path))

    assert submission.records[0].taxonomy_id == "562"


def test_autofix_keeps_the_slot_a_string():
    sample = _sample({"name": "Escherichia coli", "taxonomy_id": "0562"})
    fix    = {"attribute": "taxonomy_id", "old_value": "0562", "new_value": "562"}

    autofix._apply_record_attribute_value(sample, fix)

    assert sample["organism"]["taxonomy_id"] == "562"
