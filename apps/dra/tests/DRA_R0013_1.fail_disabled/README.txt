DRA_R0013（Experiment description 必須）は現行 D-way が description 入力欄を省略しており通常空のため、
validator.py で呼び出しをコメントアウトして無効化した。本シナリオ（発火期待=.fail）は成立しなくなるため、
ハーネスが読まない名前（末尾が pass/fail 以外）にリネームして無効化している（fixture は将来の再有効化のため保存）。
