"""軽量ルール基底（dra / metabobank / gea 共有）。

capability flags（requires_rdb/network/auth）＋ result() dict 生成を提供する。
※ ddbj/bs 系の common/rules/base.py:BaseRule（get_features / validate_file 等を持つ重い基底）とは別物。
"""


class SimpleRule:
    rule_id = "RXXXX"
    level = "error"
    target = ""
    description = ""
    requires_rdb = False       # skip_db 時にスキップ
    requires_network = False   # skip_ncbi 時にスキップ
    requires_auth = False      # skip_auth 時にスキップ

    def result(self, message=None, level=None, target=None, **extra):
        r = {
            "rule_id": self.rule_id,
            "level": (level or self.level),
            "target": (target if target is not None else self.target),
            "message": message or self.description,
        }
        r.update(extra)
        return r
