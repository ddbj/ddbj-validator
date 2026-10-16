"""非 ASCII 正規化の位置表示（2026-10-16）。

MB_IR0024 などは summary と details が同じ文面で、どの値のどこに非 ASCII があったか
分からなかった。details にだけ「どの値か（#k / Protocol Name）」と前後の抜粋を足す。
"""
from apps.metabobank.model import MbSubmission
from common.magetab.model import Idf, Sdrf
from common.magetab.charnorm import apply_to_submission, snippets, location_text
from common.magetab import reporter as mr


def _sub(idf_fields=None, header=None, rows=None):
    s = MbSubmission()
    if idf_fields is not None:
        idf = Idf()
        idf.fields = {k: list(v) for k, v in idf_fields.items()}
        idf.field_order = list(idf_fields)
        s.idf = idf
    if header is not None:
        sd = Sdrf()
        sd.header, sd.rows = header, rows or []
        s.sdrf = sd
    return s


def _ctx():
    return type("C", (), {"definitions": {}})()


def test_snippets_marks_each_occurrence_with_context():
    s = snippets("incubated at 37°C for 30 min, mean ± SD", {"°", "±"}, ctx=5)
    assert s == '"...at 37[°]C for...", "...mean [±] SD"'


def test_snippets_limit_and_newline():
    s = snippets("a°\nb°c°", {"°"}, ctx=2, limit=2)
    assert s == '"a[°]\\nb...", "...\\nb[°]c°", +1 more'


def test_idf_label_has_index_and_protocol_name():
    sub = _sub(idf_fields={"Protocol Name": ["Sample collection", "Extraction"],
                           "Protocol Description": ["none", "at 4°C"]})
    apply_to_submission(sub)
    fx = [f for f in sub.char_fixes if f["mapped"]][0]
    assert location_text(fx, fx["mapped"]) == \
        'Protocol Description #2 (Protocol Name: Extraction): "at 4[°]C"'


def test_mb_ir0024_location_only_in_details():
    from apps.metabobank.rules.idf import MB_IR0024
    sub = _sub(idf_fields={"Protocol Name": ["Extraction"],
                           "Protocol Description": ["kept at 4°C"]})
    apply_to_submission(sub)
    res = MB_IR0024().validate(sub, _ctx())
    r = [x for x in res if x["level"] == "warning"][0]
    assert r["location"] == 'Protocol Description (Protocol Name: Extraction): "kept at 4[°]C"'
    line = mr.fmt_detail(r, lambda _: False, None)
    assert line.endswith(' at Protocol Description (Protocol Name: Extraction): "kept at 4[°]C"')
    assert "[°]" not in r["message"]            # summary が使う message には入れない


def test_mb_sr0030_location_is_cell_snippet():
    from apps.metabobank.rules.sdrf import MB_SR0030
    sub = _sub(header=["Comment[sample_title]"], rows=[["5 µL 肝"]])
    apply_to_submission(sub)
    res = MB_SR0030().validate(sub, _ctx())
    by_level = {r["level"]: r for r in res}
    assert by_level["warning"]["location"] == '"5 [µ]L 肝"'
    assert by_level["error"]["location"] == '"5 µL [肝]"'


def test_arrows_are_normalized():
    sub = _sub(idf_fields={"Study Description": ["A ↑ B ↓ C ↔ D ≓ E"]})
    apply_to_submission(sub)
    assert sub.idf.fields["Study Description"] == ["A up B down C <--> D ~ E"]
    assert not any(f["residual"] for f in sub.char_fixes)
