"""DDBJ Record 入力のテスト（`@pytest.mark.record`）は、`ddbj-record` が入っていない環境では
skip する。既定では選ばれず（pyproject の addopts）、`pytest -m record` で明示したときだけ走る。"""
import importlib.util

import pytest


def pytest_collection_modifyitems(config, items):
    if importlib.util.find_spec("ddbj_record") is not None:
        return

    skip = pytest.mark.skip(reason="ddbj-record が入っていない（pip install '.[record]'）")

    for item in items:
        if "record" in item.keywords:
            item.add_marker(skip)
