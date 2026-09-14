"""IDF↔SDRF 横断ルール（MB_CR）。"""
import re
from apps.metabobank.rules.base import MbRule, null_values, mtbks_accession


def _unmatch_results(rule, sdrf_only, idf_only):
    """IDF↔SDRF の片側にしか無い名前を、向きを添えた result のリストにする。

    MB_CR0001 / MB_CR0002 / MB_CR0003 で共用。両方向にズレがあれば 2 件に分ける
    （どちらを直せばよいかが 1 件では分からないため）。annotation は idf_sdrf パターンで、
    向きに応じて `sdrf_only` / `idf_only` のどちらかだけを載せる。
    """
    out = []
    for label, bad, key in (("only in SDRF", sdrf_only, "sdrf_only"),
                            ("only in IDF", idf_only, "idf_only")):
        if bad:
            joined = ", ".join(sorted(bad))
            out.append(rule.result(message=f"{rule.description} ({label}: {joined})",
                                   **{key: joined}))
    return out


class MB_CR0001(MbRule):
    rule_id = "MB_CR0001"; level = "error"; target = "IDF,SDRF"
    description = "Experimental factor in SDRF does not match IDF Experimental Factor Name."

    def validate(self, sub, context):
        r"""IDF Experimental Factor Name と SDRF Factor Value[...] の **名前** を双方向に突き合わせる。

        factor 自体は任意項目なので「どちらにも無い」は無指摘。片側にしか無ければ向きを
        添えて指摘する（両方向あれば 2 件に分ける）。

        このルールは **名前の一致だけ** を見る。名前として不正な形は両側とも集合から除き、
        それぞれの担当ルールに委譲する（二重報告を避けるため）。
        - IDF 側の null value（missing 等） → MB_IR0007（required_not_null）
        - SDRF 側の null value を名前にした列（`Factor Value[missing]`） → MB_SR0047（値の欠落）
        - 名前の無い `Factor Value[]` → MB_SR0007（無名のユーザ定義列）
        """
        if not sub.idf or not sub.sdrf:
            return []
        nulls = null_values(context)
        idf_factors = {n.strip() for n in sub.idf.get("Experimental Factor Name")
                       if n.strip() and n.strip() not in nulls}
        sdrf_factors = set()
        for h in sub.sdrf.header:
            m = re.fullmatch(r"Factor Value\[(.*)\]", h)
            if m:
                name = m.group(1).strip()
                if name and name not in nulls:      # 無名・null 名は他ルールへ委譲
                    sdrf_factors.add(name)
        return _unmatch_results(self, sdrf_factors - idf_factors, idf_factors - sdrf_factors)


class MB_CR0002(MbRule):
    # ルール表の名前: Protocol unmatch
    rule_id = "MB_CR0002"; level = "error"; target = "IDF,SDRF"
    description = "IDF Protocol and SDRF Protocol REF do not match."

    def validate(self, sub, context):
        """IDF Protocol Name と SDRF Protocol REF の値を **双方向** に突き合わせる。

        ルール表の「IDF の Protocol、及び、SDRF で参照されている Protocol が一致していない」
        ＝過不足なしの意味なので、片側にしか無いものを向きを添えて指摘する
        （両方向あれば 2 件に分ける）。MB_CR0001 と同じ形。

        - only in SDRF — SDRF が参照しているのに IDF の Protocol Name に定義が無い。
        - only in IDF  — IDF で定義したのに SDRF がどの行からも参照していない
          （工程に対応する Protocol REF 列が消えている／値が別の protocol に化けている）。

        null value（missing 等）は SDRF 側の集合から除かない（従来どおり）。
        `Protocol REF` に null value を書くと IDF に無い値でもあるため、値の欠落を見る
        MB_SR0033 / MB_SR0049 と併発する。観点が違うので二重報告のままにしている。
        """
        if not sub.idf or not sub.sdrf:
            return []
        idf_protocols = {n.strip() for n in sub.idf.get("Protocol Name") if n.strip()}
        idxs = sub.sdrf.col_indices("Protocol REF")
        refs = set()
        for row in sub.sdrf.rows:
            for i in idxs:
                v = (row[i] if i < len(row) else "").strip()
                if v:
                    refs.add(v)
        return _unmatch_results(self, refs - idf_protocols, idf_protocols - refs)


class MB_CR0003(MbRule):
    # ルール表の名前: Protocol parameter unmatch
    rule_id = "MB_CR0003"; level = "error"; target = "IDF,SDRF"
    description = "IDF and SDRF Protocol Parameters do not match."

    def validate(self, sub, context):
        """IDF Protocol Parameters と SDRF `Parameter Value[...]` 列名を **双方向** に突き合わせる。

        ルール表の「IDF の Protocol Parameter、及び、SDRF の Protocol Parameter が
        一致していない」＝過不足なしの意味。MB_CR0002 / MB_CR0001 と同じ形。

        - only in SDRF — 列はあるが IDF で宣言されていない。
        - only in IDF  — IDF で宣言したのに対応する列が SDRF に無い（列が削られている）。

        IDF 側は protocol 横断でフラットな名前集合にして比較する。**どの protocol に
        属するか** までは見ない（Extraction のパラメータが Mass spectrometry の位置に
        置かれている、といった取り違えは対象外）。
        """
        if not sub.idf or not sub.sdrf:
            return []
        idf_params = set()
        for p in sub.idf.protocols():
            for x in (p["Protocol Parameters"] or "").split(";"):
                if x.strip():
                    idf_params.add(x.strip())
        sdrf_params = set()
        for h in sub.sdrf.header:
            m = re.fullmatch(r"Parameter Value\[(.+)\]", h)
            if m:
                sdrf_params.add(m.group(1).strip())
        return _unmatch_results(self, sdrf_params - idf_params, idf_params - sdrf_params)


class MB_CR0004(MbRule):
    rule_id = "MB_CR0004"; level = "warning"; target = "IDF,SDRF"
    description = "Re-analysis accession differs between IDF and SDRF."

    def validate(self, sub, context):
        if not sub.idf or not sub.sdrf:
            return []
        # IDF 側は `MetaboBank:MTBKS123` とも書けるので accession に正規化して突き合わせる
        # （MB_IR0038 の仕様。prefix の有無で不一致扱いになるのを避ける）。
        idf_re = {mtbks_accession(v) or v.strip()
                  for v in sub.idf.get("Comment[Related study]") if v.strip()}
        sdrf_re = set()
        for i in sub.sdrf.col_indices("Comment[Reanalysis of]"):
            for row in sub.sdrf.rows:
                v = (row[i] if i < len(row) else "").strip()
                m = re.match(r"^(MTBKS\d+):", v)
                if m:
                    sdrf_re.add(m.group(1))
        bad = sdrf_re - idf_re if idf_re else set()
        if not bad:
            return []
        return [self.result(message=f"{self.description} ({', '.join(sorted(bad))})",
                            sdrf_only=", ".join(sorted(bad)),
                            idf_only=", ".join(sorted(idf_re)))]
