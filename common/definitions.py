"""ddbj / biosample 共通の定義データ（common/resources/definitions.json）ローダ。

両 app の context が同じ common definitions.json を別々に読み込んでいた重複を解消し、
共有 cv_terms（countries / missing_terms / missing_reporting_terms 等）の単一入口とする。
"""
import json
import importlib.resources


def load_common_definitions():
    """common/resources/definitions.json 全体を dict で返す（読めなければ空 dict）。"""
    try:
        p = importlib.resources.files("common.resources") / "definitions.json"
        with p.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def load_common_cv_terms():
    """common/resources/definitions.json の cv_terms を返す（読めなければ空 dict）。"""
    return load_common_definitions().get("cv_terms", {})
