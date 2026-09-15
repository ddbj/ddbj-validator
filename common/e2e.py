"""E2E ハーネスの共通ランナー（bioproject / dra / gea / metabobank）。

4 app の `apps/<app>/tests/run_tests.py` に同型で書かれていた
「fixture を回す → 発火 rule_id 集合を取る → 期待と比べる → Matched/Mismatched を色つきで出す →
終了コードを返す」を 1 箇所にした。各 app 側に残るのは **mock と fixture の読み方** だけ。

判定は 2 種類:
- `check_rule(name, rule_id, expected, fired)`  … `.pass` / `.fail` 方式（bp / dra）。
  そのディレクトリ名のルールが .fail なら発火・.pass なら非発火であること。
- `check_set(name, fired, expected)`           … 期待集合方式（gea / mb）。
  発火 rule_id 集合が EXPECTED と完全一致すること。

biosample（CLI サブプロセス＋autofix ゴールデン）と ddbj（note 埋め込み方式）は方式が別なので対象外。
"""

GREEN, RED, END = "\033[92m", "\033[91m", "\033[0m"


class E2ERunner:
    def __init__(self, app_name):
        self.app_name = app_name
        self.matched = 0
        self.mismatched = 0

    def check_rule(self, name, rule_id, expected, fired):
        """expected は "pass" / "fail"。fired は発火した rule_id の集合。"""
        triggered = rule_id in fired
        ok = (triggered if expected == "fail" else not triggered)
        if ok:
            self.matched += 1
            print(f"  [{GREEN}Matched{END}]  {name} ({rule_id} correctly "
                  f"{'triggered' if expected == 'fail' else 'not triggered'})")
        else:
            self.mismatched += 1
            print(f"  [{RED}MISMATCH{END}] {name}: expected {expected}, fired={triggered}")
        return ok

    def check_set(self, name, fired, expected):
        """発火 rule_id 集合が期待集合と一致するか。差分を +/− で出す。"""
        ok = fired == expected
        if ok:
            self.matched += 1
            print(f"  [{GREEN}Matched{END}]  {name}: {sorted(fired)}")
        else:
            self.mismatched += 1
            print(f"  [{RED}MISMATCH{END}] {name}: fired={sorted(fired)} expected={sorted(expected)}"
                  f" (+{sorted(fired - expected)} / -{sorted(expected - fired)})")
        return ok

    def finish(self):
        """集計を出して終了コード（0 / 1）を返す。"""
        print(f"\n  Matched: {self.matched}   Mismatched: {self.mismatched}")
        if self.mismatched:
            print(f"{RED}[FAIL]{END}")
            return 1
        print(f"{GREEN}[SUCCESS] All {self.app_name} tests passed.{END}")
        return 0


def run_expected_sets(app_name, expected, fired_fn, header=None):
    """期待集合方式を一括で回す（gea / mb）。fired_fn(key) -> set。終了コードを返す。"""
    if header:
        print(header)
    r = E2ERunner(app_name)
    for key, exp in expected.items():
        r.check_set(key, fired_fn(key), exp)
    return r.finish()
