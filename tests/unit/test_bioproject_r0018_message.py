"""BP_R0018 の文に、いつ効く規則か（Monoisolate / Multiisolate のときだけ）と直し方を入れる（2026-10-22）。"""
from types import SimpleNamespace

from apps.bioproject.model import BioProjectRecord
from apps.bioproject.rules.taxonomy import BP_R0018


def _run(scope, taxid="3701", rank="genus", organism="Arabidopsis"):
    rec = BioProjectRecord(sample_scope=scope, organism_name=organism, tax_id=taxid)
    ctx = SimpleNamespace(taxid_info={taxid: {"rank": rank, "is_species_or_below": False}} if taxid else {},
                          tax_data={organism: {"status": "invalid_rank", "rank": rank}})
    return BP_R0018().validate(SimpleNamespace(records=[rec]), ctx)


def test_message_by_taxid_has_condition_and_fix():
    [r] = _run("eMonoisolate")
    assert r["message"] == ("For a Monoisolate or Multiisolate project, taxonomy should be at the species or "
                            "infraspecific level (taxonomy_id: '3701', rank: 'genus'). "
                            "Use the species name or change the sample scope.")


def test_message_by_organism_name():
    res = _run("eMultiisolate", taxid=None)
    assert [r["message"] for r in res] == [
        "For a Monoisolate or Multiisolate project, taxonomy should be at the species or infraspecific level "
        "(organism: 'Arabidopsis', rank: 'genus'). Use the species name or change the sample scope."]


def test_other_scopes_are_not_checked():
    assert _run("eMultispecies") == [] and _run("eOther") == []
