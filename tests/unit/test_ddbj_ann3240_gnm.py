"""ANN3240: GNM（完全長ゲノム、DATATYPE で申告）では artificial_location を許可する（ddbj/ddbj-validator#13）。"""
from types import SimpleNamespace

from apps.ddbj.rules.annotation import ANN3240


def _run(datatypes):
    cds = SimpleNamespace(type="CDS", line_number=7, location=None,
                          qualifiers={"artificial_location": ["low-quality sequence region"]})
    rec = SimpleNamespace(id="chr1", features=[cds], features_by_type={"CDS": [cds]})
    context = SimpleNamespace(is_wgs=False, is_tsa=False, active_divisions=set(),
                              active_datatypes=set(datatypes))
    return ANN3240().validate_file({"chr1": rec}, context)


def test_gnm_allows_artificial_location():
    assert _run({"GNM"}) == []


def test_without_genome_scale_datatype_is_error():
    res = _run(set())
    assert len(res) == 1 and res[0]["level"].lower() == "error"
