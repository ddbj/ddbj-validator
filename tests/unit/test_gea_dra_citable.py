"""DRA から引き写した参照が `GEA_REF0002` の対象外になること。

登録 web（Dway）の DRA タブは「その account が登録した／外部参照を許可された DRA submission」だけを
出し、登録者が選ぶと Run / Experiment / BioSample / BioProject を SDRF・IDF に引き写す。
引き写した BioSample / BioProject は **account の所有でも PSUB/SSUB permit でもない**ことがあるため、
所有集合だけを見ていた `GEA_REF0002` が error を出していた（2026-09-21 の GEA からの指摘）。

ここでは「引用してよい DRA から辿れるものは可」が効いていることと、
**DRA を経由しない参照は従来どおり error のまま**であることを固定する。
"""
from apps.gea.context import ValidationContext
from apps.gea.model import GeaSubmission, Idf
from apps.gea.rules.reference_db import GEA_REF0002
from common.magetab.model import Sdrf


def _sub(prjdb="PRJDB18094", samd="SAMD00073782", drr="DRR9999999"):
    idf = Idf()
    idf.fields = {"Comment[BioProject]": [prjdb]}
    idf.field_order = ["Comment[BioProject]"]
    sdrf = Sdrf()
    sdrf.header = ["Comment[BioSample]", "Comment[SRA_RUN]"]
    sdrf.rows = [[samd, drr]]
    sub = GeaSubmission()
    sub.idf, sub.sdrf = idf, sdrf
    return sub


def _ctx(citable):
    """所有は空、実在集合は「全部実在する」にした context。citable だけを動かして違いを見る。"""
    c = ValidationContext(skip_db=False, skip_ncbi=True, skip_auth=False)
    c.account_bioprojects, c.account_biosamples, c.account_runs = set(), set(), set()
    c.existing_bioprojects = {"PRJDB18094"}
    c.existing_biosamples = {"SAMD00073782"}
    c.existing_runs = {"DRR9999999"}
    if citable:
        c.dra_citable_bioprojects = {"PRJDB18094"}
        c.dra_citable_biosamples = {"SAMD00073782"}
        c.dra_citable_runs = {"DRR9999999"}
    return c


def test_ref0002_fires_when_not_owned_and_not_from_dra():
    """DRA 経由でない参照は従来どおり error。ここが消えると検査が骨抜きになる。"""
    ids = [r["message"] for r in GEA_REF0002().validate(_sub(), _ctx(citable=False))]
    assert len(ids) == 3, ids


def test_ref0002_skips_objects_carried_over_from_a_citable_dra_submission():
    """引用してよい DRA submission から辿れるものは所有していなくても通る。"""
    assert GEA_REF0002().validate(_sub(), _ctx(citable=True)) == []


def test_ref0002_still_fires_for_objects_outside_the_dra_submission():
    """同じ submission でも、DRA から辿れないものは error のまま。"""
    ctx = _ctx(citable=True)
    ctx.existing_bioprojects = {"PRJDB18094", "PRJDB99999"}
    msgs = [r["message"] for r in GEA_REF0002().validate(_sub(prjdb="PRJDB99999"), ctx)]
    assert len(msgs) == 1 and "PRJDB99999" in msgs[0], msgs
