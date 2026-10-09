"""BioSample の検証プロファイル（`profile=next`、2026-10-03）。

web API `/validation` に任意のフォーム項目 `profile` を足した。値は `next`（次期 BioSample）だけ。
- `profile=next`: 属性定義（attributes_packages.json）で `allow_multiple: true` の属性は、
  同名多値でも BS_R0061 を出さない。それ以外の属性の多値は従来どおり error。
- `profile` 無し（現行 D-way / BioSample）: 従来どおり全部 error。
- 結果 JSON・status には profile を載せない（現行 D-way が受け取る形を変えないため）。
"""
import json
from types import SimpleNamespace

import pytest

from apps.biosample.context import ValidationContext
from apps.biosample.rules.structure import BS_R0061
from apps.webapi import runner

ALLOW_MULTIPLE = {"locus_tag_prefix", "component_organism", "culture_collection",
                  "metagenome_source", "specimen_voucher", "virus_enrich_appr"}


def _sub(attrs):
    rec = SimpleNamespace(sample_id="S1", attributes=attrs)
    return SimpleNamespace(records=[rec])


def _fired(profile, attrs):
    ctx = ValidationContext(skip_db=True, skip_ncbi=True, skip_auth=True, profile=profile)
    return {r["attribute"] for r in BS_R0061().validate(_sub(attrs), ctx)}


def test_allow_multiple_set_matches_the_attribute_master():
    ctx = ValidationContext(skip_db=True, skip_ncbi=True, skip_auth=True)
    assert {n for n, a in ctx.attributes.items() if a.get("allow_multiple")} == ALLOW_MULTIPLE


@pytest.mark.parametrize("name", sorted(ALLOW_MULTIPLE))
def test_next_allows_multiple_values_for_allow_multiple_attributes(name):
    attrs = {name: ["A", "B"]}
    assert _fired("next", attrs) == set()
    assert _fired(None, attrs) == {name}          # profile 無しは従来どおり error


def test_next_still_rejects_other_attributes():
    attrs = {"cultivar": ["Cv", "Cv2"], "culture_collection": ["JCM:1", "NBRC:2"]}
    assert _fired("next", attrs) == {"cultivar"}
    assert _fired(None, attrs) == {"cultivar", "culture_collection"}


# --- web API ---

def test_runner_passes_profile_only_to_biosample(tmp_path):
    bs = {"biosample": tmp_path / "SSUB000001.xml"}
    assert runner.plan(bs, {"profile": "next"})[-2:] == ["--profile", "next"]
    assert "--profile" not in runner.plan(bs, {})
    bp = {"bioproject": tmp_path / "PSUB000001.xml"}
    assert "--profile" not in runner.plan(bp, {"profile": "next"})


@pytest.fixture
def client(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    from apps.webapi import app as webapp
    monkeypatch.setattr(webapp.config, "DATA_DIR", str(tmp_path))
    calls = []
    monkeypatch.setattr(webapp.runner, "run_validation", lambda rdir, saved, params: calls.append(params))
    c = TestClient(webapp.app)
    c.calls = calls
    return c


def _post(client, **data):
    files = {"biosample": ("SSUB000001.xml", b"<BioSampleSet/>", "application/xml")}
    return client.post("/validation", files=files, data=data)


def test_api_accepts_profile_next_and_keeps_it_out_of_the_response(client):
    r = _post(client, profile="next")
    assert r.status_code == 200
    assert "profile" not in r.json()
    assert client.calls[-1]["profile"] == "next"


def test_api_without_profile_is_unchanged(client):
    r = _post(client)
    assert r.status_code == 200
    assert client.calls[-1]["profile"] is None


def test_api_rejects_unknown_profile(client):
    r = _post(client, profile="future")
    assert r.status_code == 400
    assert "Unknown profile" in r.json()["message"]
    assert client.calls == []


def test_cli_profile_does_not_leak_into_the_json_report(tmp_path):
    """結果 JSON（result.json の元）に profile を出さない。"""
    from apps.biosample import cli
    src = "apps/biosample/tests/BS_R0061/BS_R0061_1.fail.xml"
    xml = tmp_path / "SSUB000001.xml"
    xml.write_text(open(src, encoding="utf-8").read().replace(
        '<Attribute attribute_name="cultivar">Cv2</Attribute>',
        '<Attribute attribute_name="cultivar">Cv2</Attribute>'
        '<Attribute attribute_name="culture_collection">JCM:1</Attribute>'
        '<Attribute attribute_name="culture_collection">NBRC:2</Attribute>'), encoding="utf-8")
    out = tmp_path / "out"
    args = cli._build_parser().parse_args(["-x", str(xml), "-l", "-j", "--profile", "next", "-o", str(out)])
    cli.run(args)
    text = (out / "reports" / "validation_report.json").read_text(encoding="utf-8")
    assert "profile" not in text
    r0061 = [m for m in json.loads(text)["messages"] if m["id"] == "BS_R0061"]
    assert [a["value"] for m in r0061 for a in m["annotation"] if a["key"] == "Attribute"] == ["cultivar"]
