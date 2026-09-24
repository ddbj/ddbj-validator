"""権限の無い BioSample の属性値が ANN1130 の突合・autofix に使われないこと。

DFAST 組み込みの検証で、アカウントにアクセス権の無い非公開 BioSample（ANN0463 が
「not associated with this account」と報告した相手）の属性値が ANN1130 の
メッセージに出力され、さらに autofix で登録者の ann に書き込まれようとしていた
（2026-09-24 の報告）。

BioSample の取得はアカウント権限の確定より前に走るため、`bs_data` には権限の無い
サンプルの中身も一度は入る。認証必須ルールは skip_auth で止まるが、autofix の提案生成は
ルールではなく worker が直接呼ぶので skip_auth では止まらない。ここでは
`propose_qualifiers_updates` の入口で権限の無い SAMD が外れることを固定する。
"""
from types import SimpleNamespace

from apps.ddbj.autofix.external_db import propose_qualifiers_updates

_SAMD = "SAMD02061638"


def _records():
    """DBLINK に _SAMD を 1 件持ち、collection_date が BioSample と食い違う 1 エントリ。"""
    dblink = SimpleNamespace(type="DBLINK", qualifiers={"biosample": [_SAMD]}, line_number=10)
    source = SimpleNamespace(type="source", qualifiers={"collection_date": ["2024-04-13"]}, line_number=20)
    entry = SimpleNamespace(
        id="CR25-001-01",
        features=[dblink, source],
        features_by_type={"DBLINK": [dblink], "source": [source]},
    )
    return {"CR25-001-01": entry}


_BS_DATA = {_SAMD: {"collection_date": "2021-05-27"}}


def test_authorized_biosample_is_compared():
    """権限があれば従来どおり不一致を報告し、修正提案も作る（回帰の逆側を押さえる）。"""
    props, warns, _ = propose_qualifiers_updates(_records(), _BS_DATA, "icrown_0015.ann")
    assert [w["rule"] for w in warns] == ["ANN1130"]
    assert "2021-05-27" in warns[0]["message"]
    assert len(props) == 1


def test_unauthorized_biosample_is_not_compared():
    """権限が無ければ突合しない。属性値がメッセージにも提案にも出てはいけない。"""
    props, warns, skips = propose_qualifiers_updates(
        _records(), _BS_DATA, "icrown_0015.ann", unauthorized_bs={_SAMD}
    )
    assert warns == []
    assert props == []
    assert skips == []


def test_unauthorized_biosample_is_not_reported_as_missing():
    """bs_data から落ちていても「DB に無い」扱いにはしない（ANN0463 が別に報告している）。"""
    props, warns, _ = propose_qualifiers_updates(
        _records(), {}, "icrown_0015.ann", unauthorized_bs={_SAMD}
    )
    assert props == [] and warns == []
