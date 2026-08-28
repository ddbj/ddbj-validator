"""`POST /validation` が受付時に断るべき入力を、受付時に断ることを固定する。

受付時に分かる入力ミスを background task まで持ち越すと、`202 accepted` を返した
あとの `404`（本文にしか理由が無い）になり、素朴な client からは「知らない uuid」と
区別が付かない。ここで見ているのはどれも、ファイルを読まずに分かるものだけ。

実行: リポジトリルートで `.venv/bin/python -m pytest tests/unit`
"""
import json

import pytest

pytest.importorskip("fastapi", reason="web api は [web] extra が要る")

from fastapi.testclient import TestClient        # noqa: E402

from apps.webapi import config, runner           # noqa: E402
from apps.webapi.app import app                  # noqa: E402

_RECORD = json.dumps({"samples": [{"alias": "S1"}]}).encode()
_XML    = b"<BioSampleSet/>"


@pytest.fixture(autouse=True)
def _sandbox(tmp_path, monkeypatch):
    """受付の判断だけを見る。run_dir を tmp へ向け、validator は起動しない。

    既定の DATA_DIR は `/data` で、書けない環境では受付そのものが 503 になる
    （`_unwritable_shards`）。テストがそれに影響されると、断るべきものを断ったのか
    保存先が無かっただけなのかが混ざる。
    """
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(runner, "run_validation", lambda *a, **kw: None)


@pytest.fixture
def client():
    return TestClient(app)


def _post(client, files, **form):
    return client.post("/validation", files=files, data=form)


def test_unknown_record_db_is_rejected_at_accept_time(client):
    r = _post(client, {"ddbj_record": ("r.json", _RECORD)}, record_db="BioProjects")
    assert r.status_code == 400
    assert "record_db に指定できるのは" in r.json()["message"]


def test_record_db_without_a_record_is_rejected(client):
    """黙って捨てると「指定したつもり」で読まれる。"""
    r = _post(client, {"biosample": ("s.xml", _XML)}, record_db="biosample")
    assert r.status_code == 400
    assert "ddbj_record" in r.json()["message"]


def test_package_with_a_record_is_rejected(client):
    """biosample CLI が `-p` と `-r` の併用を拒むのと同じ判断。web だけ黙って無視すると、
    指定した package で検証されたと読まれる。"""
    r = _post(client, {"ddbj_record": ("r.json", _RECORD)}, package="Microbe")
    assert r.status_code == 400
    assert "package" in r.json()["message"]


def test_submission_id_from_the_other_db_is_rejected(client):
    r = _post(client, {"ddbj_record": ("r.json", _RECORD)},
              record_db="bioproject", submission_id="SSUB000001")
    assert r.status_code == 400
    assert "record_db" in r.json()["message"]


@pytest.mark.parametrize("form", [
    {}, {"record_db": "biosample"}, {"record_db": "biosample", "submission_id": "SSUB000001"},
])
def test_valid_combinations_are_accepted(client, form):
    r = _post(client, {"ddbj_record": ("r.json", _RECORD)}, **form)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "accepted"


def test_package_still_allowed_with_the_xml_role(client):
    """既存の XML / TSV 経路は素通し。`package` の拒否は record だけの話。"""
    r = _post(client, {"biosample": ("s.xml", _XML)}, package="Microbe")
    assert r.status_code == 200, r.text
