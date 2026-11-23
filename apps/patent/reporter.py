"""patent の報告。ddbj の reporter にレベル `FLAG`（通して印を返す）を足したもの。"""
from apps.ddbj.reporter import ValidationReporter


class PatentReporter(ValidationReporter):
    LEVELS = ["FATAL", "ERROR", "WARNING", "FLAG", "INFO", "AUTO-CLEANUP"]
    LEVEL_ABBR = {**ValidationReporter.LEVEL_ABBR, "FLAG": "FLAG"}
    EXTRA_STATS = ("flag",)
