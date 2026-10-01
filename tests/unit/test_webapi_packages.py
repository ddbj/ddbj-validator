"""web API の /package_list・/attribute_list が返す説明文と either_one の group。

登録システム側の要望（2026-10-01）: 属性の説明は URL ではなく文で欲しい（`description`）、
「どれか 1 つ必須」の群を色分けしたい（`group`）、パッケージの Instructions に
package.txt の Description / Example を出したい。
データ源は同梱 JSON（apps/biosample/resources/attributes_packages.json。g sheet から
build_attributes_packages_json.py で生成）なので、ここでは JSON と API 整形の両方を固定する。

実行: リポジトリルートで `.venv/bin/python -m pytest`
"""
import re

from apps.webapi import packages

# g sheet の説明文に出てくる HTML は <a href> と <span class="attention_text"> だけ。
# specimen_voucher の "[<institution-code>:...]" のような山括弧の書式例（元は &lt; &gt;）は文の一部なので残す。
_TAG_OR_ENTITY = re.compile(r"</?(?:a|span|br|b|i|p)\b[^>]*>|&[a-zA-Z#0-9]+;", re.I)


def _attrs(package):
    return {a["name"]: a for a in packages.attribute_list(package)}


# ---------------- attribute_list ----------------
def test_either_one_attributes_carry_their_group():
    """Microbe: strain/isolate が organism 群、host/isolation_source が source 群。"""
    a = _attrs("Microbe")
    assert a["strain"]["use"] == "either_one_mandatory" and a["strain"]["group"] == "organism"
    assert a["isolate"]["group"] == "organism"
    assert a["host"]["group"] == "source" and a["isolation_source"]["group"] == "source"


def test_non_either_one_attributes_have_an_empty_group():
    a = _attrs("Microbe")
    assert a["sample_name"]["use"] == "mandatory" and a["sample_name"]["group"] == ""   # fixed 属性
    assert a["collection_date"]["use"] == "mandatory" and a["collection_date"]["group"] == ""


def test_every_attribute_has_a_plain_text_description():
    """全属性に説明文があり、HTML タグも実体参照も残っていない（リンクは文だけ残す）。"""
    for a in packages.attribute_list("Microbe"):
        assert a["description"], a["name"]
        assert not _TAG_OR_ENTITY.search(a["description"]), (a["name"], a["description"])
    organism = _attrs("Microbe")["organism"]["description"]
    assert organism.startswith("The most descriptive organism name for this sample")
    assert "NCBI Taxonomy database" in organism and "<a" not in organism


def test_html_entities_are_unescaped_in_descriptions():
    """&deg; → °、&lt;/&gt; → < > のように、実体参照は文字に戻す（タグを外すだけでは残る）。"""
    assert "°" in _attrs("MIGS.ba.soil")["slope_aspect"]["description"]
    assert "[<institution-code>:[<collection-code>:]]<specimen_id>" in _attrs("Plant")["specimen_voucher"]["description"]


# ---------------- package_list ----------------
def _pkgs():
    return {p["package"]: p for p in packages.package_list()}


def test_package_list_carries_description_and_example():
    p = _pkgs()
    assert p["SARS-CoV-2.cl"]["description"].startswith("Use for SARS-CoV-2 samples")
    assert p["Generic"]["description"] == "" and p["Generic"]["example"] == ""   # 無いものは空文字
    assert set(p["Microbe"]) >= {"package", "full_name", "version", "package_group", "env_package",
                                 "description", "example"}


def test_package_description_is_plain_text():
    """Human の Description は g sheet 上で HTML を含む唯一のパッケージ。"""
    desc = _pkgs()["Human"]["description"]
    assert desc.startswith("WARNING: Only use for human samples")
    assert not _TAG_OR_ENTITY.search(desc)
