"""DRA 管理語彙（cv_terms）チェック。

XSD の enumeration を definitions.json の cv_terms に外部化し、分かりやすいメッセージで検査する
（XSD 検証だけだとメッセージが不親切なため）。
- DRA_R0039: Experiment の LIBRARY_STRATEGY / LIBRARY_SOURCE / LIBRARY_SELECTION /
  INSTRUMENT_MODEL が cv_terms に無い → error。
"""
from apps.dra.rules.base import DraRule


class DRA_R0039(DraRule):
    rule_id = "DRA_R0039"
    level = "error"
    target = "EXPERIMENT (LIBRARY_* / INSTRUMENT_MODEL)"
    description = "Value is not defined in controlled vocabulary."

    def validate(self, submission, context):
        cv = context.cv_terms or {}
        strat = set(cv.get("library_strategy", []))
        src = set(cv.get("library_source", []))
        sel = set(cv.get("library_selection", []))
        # instrument_model は platform 別の union
        models = set()
        for lst in (cv.get("instrument_model_by_platform", {}) or {}).values():
            models.update(lst)
        out = []
        for e in submission.experiments:
            for field, val, allowed in (
                ("LIBRARY_STRATEGY", e.library_strategy, strat),
                ("LIBRARY_SOURCE", e.library_source, src),
                ("LIBRARY_SELECTION", e.library_selection, sel),
                ("INSTRUMENT_MODEL", e.instrument_model, models),
            ):
                v = (val or "").strip()
                if v and allowed and v not in allowed:
                    out.append(self.result(sample=e.label, target=field,
                                           message=f"{field} value is not defined in controlled vocabulary. (Found: '{v}')"))
        return out
