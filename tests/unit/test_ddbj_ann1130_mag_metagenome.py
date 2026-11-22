"""ANN1130: MAG の DBLINK が元のメタゲノム試料の BioSample のとき、organism を
`... metagenome` に自動修正しないこと（ddbj/ddbj-validator#17）。

MAG には MAG 用の BioSample（MIMAG、derived_from で元の試料を参照）が要る。DBLINK がメタゲノム試料の
BioSample だと、organism の突合で BioSample の `soil metagenome` などに書き換える提案が出ていた。
このときは提案を出さず、警告だけにする。
"""
from types import SimpleNamespace

from apps.ddbj.autofix.external_db import propose_qualifiers_updates

_SAMD = "SAMD00000001"


def _run(ann_organism, bs_organism):
    dblink = SimpleNamespace(type="DBLINK", qualifiers={"biosample": [_SAMD]}, line_number=1)
    source = SimpleNamespace(type="source", line_number=5, qualifiers={"organism": [ann_organism]})
    rec = SimpleNamespace(id="seq1", features=[dblink, source],
                          features_by_type={"DBLINK": [dblink], "source": [source]})
    props, warns, _skips = propose_qualifiers_updates({"seq1": rec}, {_SAMD: {"organism": bs_organism}}, "t.ann")
    org_props = [p for p in props if p["qualifier"] == "organism"]
    org_warns = [w["message"] for w in warns if w["qualifier"] == "organism"]
    return org_props, org_warns


def test_mag_organism_is_not_replaced_by_metagenome_name():
    props, warns = _run("Candidatus Examplea bacterium", "soil metagenome")
    assert props == []
    assert len(warns) == 1 and "metagenome" in warns[0] and "MAG" in warns[0]


def test_metagenome_on_both_sides_still_autofixed():
    props, _ = _run("marine metagenome", "marine sediment metagenome")
    assert [p["new_value"] for p in props] == ["marine sediment metagenome"]


def test_ordinary_organism_mismatch_still_autofixed():
    props, _ = _run("Examplea sp.", "Examplea sp. ABC1")
    assert [p["new_value"] for p in props] == ["Examplea sp. ABC1"]
