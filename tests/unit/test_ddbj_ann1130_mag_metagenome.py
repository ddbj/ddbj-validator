"""ANN1130: MAG の DBLINK が元のメタゲノム試料の BioSample のとき、organism を
試料の名前（`... metagenome` / `uncultured ...`）に自動修正しないこと（ddbj/ddbj-validator#17）。

MAG には MAG 用の BioSample（organism は MAG の生物名）が要る。DBLINK がメタゲノム試料の
BioSample だと、organism の突合で BioSample の `soil metagenome` などに書き換える提案が出ていた。
MAG（KEYWORD に MAG / Metagenome Assembled Genome）のときは提案を出さず、警告だけにする。
MAG 以外は従来どおり突合する。
"""
from types import SimpleNamespace

from apps.ddbj.autofix.external_db import propose_qualifiers_updates

_SAMD = "SAMD00000001"


def _run(ann_organism, bs_organism, keywords=("ENV", "MAG"), keyword_on_entry=False):
    dblink = SimpleNamespace(type="DBLINK", qualifiers={"biosample": [_SAMD]}, line_number=1)
    source = SimpleNamespace(type="source", line_number=5, qualifiers={"organism": [ann_organism]})
    keyword = SimpleNamespace(type="KEYWORD", qualifiers={"keyword": list(keywords)}, line_number=2)
    entry_feats = {"DBLINK": [dblink], "source": [source]}
    common_feats = {}
    (entry_feats if keyword_on_entry else common_feats)["KEYWORD"] = [keyword]
    rec = SimpleNamespace(id="seq1", features=[f for fs in entry_feats.values() for f in fs],
                          features_by_type=entry_feats)
    common = SimpleNamespace(id="COMMON", features=[f for fs in common_feats.values() for f in fs],
                             features_by_type=common_feats)
    props, warns, _skips = propose_qualifiers_updates(
        {"COMMON": common, "seq1": rec}, {_SAMD: {"organism": bs_organism}}, "t.ann")
    org_props = [p for p in props if p["qualifier"] == "organism"]
    org_warns = [w["message"] for w in warns if w["qualifier"] == "organism"]
    return org_props, org_warns


def test_mag_organism_is_not_replaced_by_metagenome_name():
    props, warns = _run("Candidatus Examplea bacterium", "soil metagenome")
    assert props == []
    assert len(warns) == 1 and "The MAG entry requires its own BioSample" in warns[0]
    assert "(ann: 'Candidatus Examplea bacterium', BioSample: 'soil metagenome')" in warns[0]


def test_mag_organism_is_not_replaced_by_uncultured_name():
    props, warns = _run("Examplea sp.", "uncultured bacterium")
    assert props == []
    assert len(warns) == 1 and "The MAG entry requires its own BioSample" in warns[0]


def test_mag_keyword_long_form_and_on_entry():
    props, warns = _run("Examplea sp.", "Soil Metagenome", keywords=("Metagenome Assembled Genome",),
                        keyword_on_entry=True)
    assert props == []
    assert len(warns) == 1


def test_non_mag_is_still_autofixed():
    # MAG の申告が無ければ従来どおり BioSample の値に合わせる
    props, warns = _run("uncultured bacterium", "soil metagenome", keywords=("ENV",))
    assert [p["new_value"] for p in props] == ["soil metagenome"]
    assert all("MAG entry" not in w for w in warns)


def test_mag_with_metagenome_name_on_both_sides_still_autofixed():
    props, _ = _run("marine metagenome", "marine sediment metagenome")
    assert [p["new_value"] for p in props] == ["marine sediment metagenome"]


def test_mag_ordinary_organism_mismatch_still_autofixed():
    props, _ = _run("Examplea sp.", "Examplea sp. ABC1")
    assert [p["new_value"] for p in props] == ["Examplea sp. ABC1"]
