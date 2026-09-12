"""SDRF ルール（MB_SR。metadata 分。ファイル実体/MAF 検証は別ツール＝非対象）。"""
import re
from apps.metabobank.rules.base import (MbRule, null_values, is_raw_data_file_none,
                                        RAW_DATA_FILE_COLUMN)


def _sdrf_def(context):
    return (context.definitions or {}).get("sdrf", {})


def _empty(v):
    return v is None or str(v).strip() == ""


def _absent(v, nulls):
    """値が「無い」か。空セルと null value（missing 等）を同じ扱いにする。"""
    sv = "" if v is None else str(v).strip()
    return not sv or sv in nulls


def _matches_any(colname, patterns):
    for p in patterns:
        try:
            if re.fullmatch(p, colname) or re.search(p, colname):
                return True
        except re.error:
            if p == colname:
                return True
    return False


def _bracket_kind(colname):
    """`Kind[name]` 形式の列名を (種別, 名前) に分解する。括弧形式でなければ None。"""
    m = re.fullmatch(r"([^\[\]]+)\[(.*)\]", colname or "")
    return (m.group(1).strip(), m.group(2).strip()) if m else None


def _default_columns(sub, context):
    """submission type ごとの既定列集合（literal な列名）。引けなければ None。

    MB_SR0006 が「登録者が足した列」を判定するための基準。素は sdrf.column_order だが、
    `Characteristics[]` / `Factor Value[]` のような種別プレースホルダは名前を持たないので
    既定列には数えない（これらは登録者が名前を決める列＝ユーザ定義扱いにする）。
    """
    sdef = _sdrf_def(context)
    st = sub.idf.submission_type if sub.idf else None
    order = sdef.get("column_order", {}).get(st)
    if not order:
        return None
    cols = set()
    for o in order:
        o = "Protocol REF" if o.startswith("Protocol REF") else o
        b = _bracket_kind(o)
        if b and not b[1]:
            continue
        cols.add(o)
    cols |= set(sdef.get("required_columns_error", []))
    # required_columns_warning は正規表現表記（`Comment\[BioSample\]`）なのでエスケープを外す
    cols |= {re.sub(r"\\(.)", r"\1", p) for p in sdef.get("required_columns_warning", [])}
    # 括弧を持たない既知列（Source Name / Raw Data File 等）も既定
    cols |= {f for f in sdef.get("fields", []) if not _bracket_kind(f)}
    return cols


def _classify_user_defined(sub, context):
    """ヘッダーを (許容種別のユーザ定義列, 不正なユーザ定義列) に分けて返す。

    許容種別は sdrf.user_defined_column_kinds（Characteristics / Parameter Value /
    Comment / Unit / Factor Value）。MAGE-TAB として登録者が名前を決めてよいのはこの 5 種だけ。
    - 定義パターン（sdrf.fields）に当たらない列   → 不正（MB_SR0007）
    - 許容種別だが名前が空（`Kind[]`）            → 不正（MB_SR0007）
    - 許容種別で既定列集合に無い                  → ユーザ定義（MB_SR0006）
    既定列集合が引けない（submission type 不明）ときは比較できないので、ユーザ定義側は空にする。

    ただし sdrf.user_defined_warning_exclude_kinds の種別は ユーザ定義側に入れない。
    - Characteristics — 登録者が自由に足すのが普通で、既定列と比べると全投稿で warning が
      出て煩いうえ、内容の妥当性は BioSample 突合（MB_SR0021 / MB_SR0023）が別途見ている。
    - Factor Value — 実験要因は投稿ごとに名前が変わるのが当然で、既定列に無いのは異常ではない。
      名前と値の妥当性は MB_SR0047（値の欠落）と MB_CR0001（IDF の
      Experimental Factor Name との突合）が見ている。
    名前の無い `Kind[]` は種別に関わらず不正側（MB_SR0007）に残す。
    """
    sdef = _sdrf_def(context)
    kinds = set(sdef.get("user_defined_column_kinds", []))
    warn_exclude = set(sdef.get("user_defined_warning_exclude_kinds", []))
    patterns = sdef.get("fields", [])
    defaults = _default_columns(sub, context)
    user_defined, invalid = [], []
    for h in sub.sdrf.header:
        if _empty(h):
            continue                                  # 無名列は MB_SR0024 の担当
        if not _matches_any(h, patterns):
            invalid.append(h)
            continue
        b = _bracket_kind(h)
        if b is None or b[0] not in kinds:
            continue                                  # 定義済みの literal 列
        if not b[1]:
            invalid.append(h)                         # `Kind[]`（名前が無い）
        elif b[0] in warn_exclude:
            continue                                  # warning の対象外種別
        elif defaults is not None and h not in defaults:
            user_defined.append(h)
    return sorted(set(user_defined)), sorted(set(invalid))


def _source_name(sub, row):
    """行の Source Name 値（Assay Name 列が無い SDRF の annotation 用）。"""
    idxs = sub.sdrf.col_indices("Source Name") if sub.sdrf else []
    return row[idxs[0]].strip() if idxs and idxs[0] < len(row) else ""


def _assay(sub, row):
    """行の Assay Name 値（レポートの location 用）。Assay Name 列が無ければ空。"""
    idxs = sub.sdrf.col_indices("Assay Name") if sub.sdrf else []
    return row[idxs[0]].strip() if idxs and idxs[0] < len(row) else ""


class MB_SR0003(MbRule):
    rule_id = "MB_SR0003"; level = "error"; target = "SDRF"
    description = "Column names are duplicated."

    def validate(self, sub, context):
        if not sub.sdrf:
            return []
        # 重複を許さないのは singleton_columns に列挙された列だけ（conf の sdrf_singleton_columns 準拠）。
        # Unit[...] や Comment[...]、Protocol REF 等の修飾列は直前の値列に紐づくため、
        # 同名で複数回現れるのが MAGE-TAB として正しい。
        singleton = _sdrf_def(context).get("singleton_columns", [])
        header = list(sub.sdrf.header)
        dup = {c for c in singleton if header.count(c) > 1}
        if not dup:
            return []
        cols = ", ".join(sorted(dup))
        return [self.result(message=f"{self.description} ({cols})", column=cols)]


class MB_SR0024(MbRule):
    rule_id = "MB_SR0024"; level = "error"; target = "SDRF"
    description = "Column without a name exists."

    def validate(self, sub, context):
        if not sub.sdrf:
            return []
        blank = [i + 1 for i, h in enumerate(sub.sdrf.header) if _empty(h)]
        if not blank:
            return []
        return [self.result(column=", ".join(f"column {i}" for i in blank))]


class MB_SR0004(MbRule):
    # required_columns_error は literal な列名（Characteristics[organism] 等）＝完全一致で判定。
    # submission type によって存在しない列は required_columns_error_exclude で除外する
    # （例: MSI は imaging のため抽出工程が無く、投稿テンプレートに Extract Name 列が無い）。
    rule_id = "MB_SR0004"; level = "error"; target = "SDRF"
    description = "Missing required column(s)."

    def validate(self, sub, context):
        if not sub.sdrf:
            return []
        header = set(sub.sdrf.header)
        st = sub.idf.submission_type if sub.idf else None
        exclude = set(_sdrf_def(context).get("required_columns_error_exclude", {}).get(st, []))
        miss = [req for req in _sdrf_def(context).get("required_columns_error", [])
                if req not in header and req not in exclude]
        if not miss:
            return []
        return [self.result(message=f"{self.description} ({', '.join(miss)})", column=", ".join(miss))]


class MB_SR0005(MbRule):
    r"""**deprecated**（validator に登録しない）。

    推奨列（Comment[BioSample] / Comment[sample_title] / Raw Data File）は MB_SR0004 の
    必須列へ統合する方針になったため廃止した。クラスは既存テストの参照のために残す。
    required_columns_warning は正規表現パターン（Comment\[BioSample\] 等）＝regex で判定。
    """
    deprecated = True
    rule_id = "MB_SR0005"; level = "warning"; target = "SDRF"
    description = "Missing recommended column(s)."

    def validate(self, sub, context):
        if not sub.sdrf:
            return []
        header = sub.sdrf.header
        miss = []
        for pat in _sdrf_def(context).get("required_columns_warning", []):
            if not any(_matches_any(h, [pat]) for h in header):
                miss.append(pat)
        if not miss:
            return []
        return [self.result(message=f"{self.description} ({', '.join(miss)})", column=", ".join(miss))]


class MB_SR0006(MbRule):
    # 登録者が名前を決めてよいのは sdrf.user_defined_column_kinds の 5 種だけ。
    # そのうち submission type の既定列に無いものを「足された列」として warning で知らせる。
    # Characteristics / Factor Value は名前が自由なのが前提なので対象外
    # （sdrf.user_defined_warning_exclude_kinds）。
    # Name: User-defined column
    rule_id = "MB_SR0006"; level = "warning"; target = "SDRF"
    description = "User-defined columns are added."

    def validate(self, sub, context):
        if not sub.sdrf:
            return []
        user_defined, _ = _classify_user_defined(sub, context)
        if not user_defined:
            return []
        return [self.result(message=f"{self.description} ({', '.join(user_defined)})",
                            column=", ".join(user_defined))]


class MB_SR0007(MbRule):
    # 許容種別（Characteristics / Parameter Value / Comment / Unit / Factor Value）以外の
    # 列名、および名前の無い `Kind[]` は登録者が足してよい形ではないので error。
    # 管理システム側は登録後に列を足し得るため internal ignore にする。
    rule_id = "MB_SR0007"; level = "error"; target = "SDRF"
    description = "Invalid user-defined columns are added."

    def validate(self, sub, context):
        if not sub.sdrf:
            return []
        _, invalid = _classify_user_defined(sub, context)
        if not invalid:
            return []
        return [self.result(message=f"{self.description} ({', '.join(invalid)})",
                            column=", ".join(invalid))]


class MB_SR0009(MbRule):
    rule_id = "MB_SR0009"; level = "error"; target = "SDRF"
    description = "Missing or null value for a required column."

    # Protocol REF は列名が重複する順序付き列で、値の欠落は MB_SR0033 が行単位で見ている。
    # ここで扱うと二重報告になるので除外する。
    _VALUE_CHECK_EXCLUDE = ("Protocol REF",)

    def validate(self, sub, context):
        """必須列の「存在」ではなく「値」を見る。

        対象は 2 つ。
        - `required_columns_error`: MB_SR0004（存在チェック）と同じ集合。submission type
          ごとの `required_columns_error_exclude` も同じように効かせる
          （MSI は抽出工程が無く Extract Name 列そのものが無いので対象外になる）。
        - `required_value_error`: 列の存在は必須でないが、**列があるなら値は必須**の列。
          `Raw Data File` がこれ。無くても警告どまり（required_columns_warning）なので、
          raw が無い投稿は列そのものを書かないのが正規の書き方になる。

        同名の列が複数ある場合は、その行の同名列が全部空/null value のときだけ欠落とみなす。
        ただし `Raw Data File` の magic word `none` は null value ではなく「raw が無い」ことを
        表す正規の値なので、欠落に数えない（MB_SR0048 が warning で拾う）。
        """
        if not sub.sdrf:
            return []
        nulls = null_values(context)
        sdef = _sdrf_def(context)
        st = sub.idf.submission_type if sub.idf else None
        exclude = set(sdef.get("required_columns_error_exclude", {}).get(st, []))
        # 同じ列が両方のリストに載っていても 1 回だけ見る（順序は定義順を保つ）
        targets = list(dict.fromkeys(list(sdef.get("required_columns_error", []))
                                     + list(sdef.get("required_value_error", []))))
        out = []
        for col in targets:
            if col in self._VALUE_CHECK_EXCLUDE or col in exclude:
                continue
            idxs = sub.sdrf.col_indices(col)
            if not idxs:
                continue      # 列そのものが無いのは MB_SR0004 の担当
            for r, row in enumerate(sub.sdrf.rows):
                vals = [(row[i] if i < len(row) else "") for i in idxs]
                # Raw Data File の `none` は値ありとして扱う（null value 扱いしない）
                if any(is_raw_data_file_none(col, v) for v in vals):
                    continue
                if all(_absent(v, nulls) for v in vals):
                    out.append(self.result(message=f"{self.description} ({col}, row {r + 1})",
                                           assay=_assay(sub, row), line=r + 1,
                                           column=col, value=vals[0],
                                           source_name=_source_name(sub, row)))
                    break     # 列ごとに 1 件（最初の該当行）に留める
        return out


class MB_SR0018(MbRule):
    # サンプルを特徴づける属性が少なすぎる投稿を拾う。閾値は 2 → 3 に強化した
    # （organism / taxonomy_id が必須なので 2 では実質「素の必須のみ」を通してしまう）。
    rule_id = "MB_SR0018"; level = "warning"; target = "SDRF"
    description = "Less than 3 characteristic attributes."

    def validate(self, sub, context):
        if not sub.sdrf:
            return []
        chars = [h for h in sub.sdrf.header if re.fullmatch(r"Characteristics\[[-_ /A-Za-z0-9.]+\]", h)]
        if len(chars) >= 3:
            return []
        return [self.result(message=f"{self.description} (Found: {len(chars)})",
                            column=", ".join(chars))]


# Factor Value 列。`[]` の中身が空の `Factor Value[]` も拾う（`.*`）。
# `.+` だと空名の列を素通しし、MB_SR0006 も sdrf.fields の `Factor Value\[.*\]` に
# 当たるため誰も指摘しなくなる。
_FACTOR_VALUE_RE = re.compile(r"Factor Value\[(.*)\]")


def _factor_value_columns(sdrf):
    """SDRF の Factor Value[...] 列を (列名, 全行の値) で返す。空名の列も含む。"""
    for h in sdrf.header:
        if _FACTOR_VALUE_RE.fullmatch(h):
            ix = sdrf.col_indices(h)[0]
            yield h, [(row[ix].strip() if ix < len(row) else "") for row in sdrf.rows]


def _has_no_value(vals, nulls):
    """その列にどの行も値が無い（空 or null value のみ）か。"""
    return all(_absent(v, nulls) for v in vals)


class MB_SR0017(MbRule):
    rule_id = "MB_SR0017"; level = "error"; target = "SDRF"
    description = "Factor value is constant across all rows."

    def validate(self, sub, context):
        if not sub.sdrf or len(sub.sdrf.rows) < 2:
            return []
        nulls = null_values(context)
        out = []
        for h, vals in _factor_value_columns(sub.sdrf):
            if _has_no_value(vals, nulls):
                continue      # 「一定」ではなく「値が無い」。MB_SR0047 が担当する
            if len(set(vals)) == 1:
                out.append(self.result(message=f"{self.description} ({h})",
                                       column=h, rows=len(vals)))
        return out


class MB_SR0047(MbRule):
    rule_id = "MB_SR0047"; level = "error"; target = "SDRF"
    description = "Experimental factor value is missing."

    def validate(self, sub, context):
        """Factor Value[...] 列があるのに factor の値が成立していない場合のエラー。

        Factor Value は任意列になったので、factor が無いなら列そのものを書かなければよい。
        列だけ作って値を入れないと MB_SR0017 が「全行で一定」と報告してしまい、
        実際の問題（値が無い）が伝わらないため、こちらで受ける。
        MB_SR0017 と違って行数の下限は設けない（1 行でも値が無いことは問題）。

        次の 2 つを同じ error で受ける。
        - どの行にも値が無い（空 or null value のみ）
        - **列名が null value**（`Factor Value[missing]`）。値が入っていても factor として
          成立していない。MB_CR0001 を name マッチ限定にした際にこちらへ委譲した。
        """
        if not sub.sdrf:
            return []
        nulls = null_values(context)
        out = []
        for h, vals in _factor_value_columns(sub.sdrf):
            name = (_FACTOR_VALUE_RE.fullmatch(h).group(1) or "").strip()
            if _has_no_value(vals, nulls) or name in nulls:
                out.append(self.result(message=f"{self.description} ({h})",
                                       column=h, rows=len(vals)))
        return out


class MB_SR0048(MbRule):
    rule_id = "MB_SR0048"; level = "warning"; target = "SDRF"
    description = "Raw data file is missing."

    # raw データが無い投稿を通すための **magic word**（`base.RAW_DATA_FILE_NONE`）。
    # INSDC の null value（missing / not applicable / not collected / not provided /
    # restricted access）は「値が不明・非該当」を表す語彙で役割が違うため流用しない。
    # null value 扱いしないので MB_SR0009（必須列の値の欠落）は発火せず、この warning だけが出る
    # （MB_SR0009 側も同じ `is_raw_data_file_none` で明示的に除外している）。

    def validate(self, sub, context):
        """Raw Data File に magic word `none` が書かれている行を知らせる。

        raw データを伴わない投稿は、列そのものを消すのではなく `none` を書くのが
        正規の書き方（列の存在は MB_SR0004 が必須列として見る）。書き方としては正しいので
        error にはせず、「raw が無い投稿である」ことを登録者とキュレータに気づかせる warning。

        `None` / `NONE` のような大文字混じりを実ファイル名として扱ってしまうと気づけないため、
        判定は大文字小文字を区別しない。
        空セルは対象外（値が無いことは MB_SR0009 の担当）。null value（missing 等）も対象外で、
        そちらは MB_SR0009 が error で受ける＝magic word でない値では通らない。
        同名列が複数あってもセル単位で判定し、該当セルごとに 1 件報告する。
        """
        if not sub.sdrf:
            return []
        out = []
        for i in sub.sdrf.col_indices(RAW_DATA_FILE_COLUMN):
            for r, row in enumerate(sub.sdrf.rows):
                v = (row[i] if i < len(row) else "").strip()
                if is_raw_data_file_none(RAW_DATA_FILE_COLUMN, v):
                    out.append(self.result(
                        message=f"{self.description} (Raw Data File: '{v}', row {r + 1})",
                        assay=_assay(sub, row), line=r + 1,
                        column="Raw Data File", value=v, source_name=_source_name(sub, row)))
        return out


class MB_SR0019(MbRule):
    rule_id = "MB_SR0019"; level = "error"; target = "SDRF"
    description = "Invalid value format."

    def validate(self, sub, context):
        if not sub.sdrf:
            return []
        fmts = (context.definitions or {}).get("value_formats", {})
        out = []
        for col, pat in fmts.items():
            idxs = sub.sdrf.col_indices(col)
            for r, row in enumerate(sub.sdrf.rows):
                for i in idxs:
                    v = row[i] if i < len(row) else ""
                    if v and v.strip() and not re.fullmatch(pat, v.strip()):
                        out.append(self.result(message=f"{self.description} ({col}: '{v}')",
                                               assay=_assay(sub, row), line=r + 1,
                                               column=col, value=v, source_name=_source_name(sub, row)))
        return out


class MB_SR0026(MbRule):
    rule_id = "MB_SR0026"; level = "error"; target = "SDRF"
    description = "Invalid column order."

    def validate(self, sub, context):
        """骨格列（sdrf.column_order_skeleton）の相対順序だけを検査する。

        `sdrf.column_order` の全列突合はしない。Protocol REF / Comment[...] / Unit[...] は
        同名で複数回現れるのが MAGE-TAB として正しく、Unit 列は直前の Parameter Value に
        紐づく相対列（MSI では `Unit[length]` が 6 箇所に出る）なので、列名だけでは
        位置を一意に決められず誤検知が避けられない。

        骨格列は `singleton_columns` 側で重複が禁じられている列なので厳密に判定できる:
        Source Name → Sample Name → Extract Name → Assay Name
        → Raw Data File → Processed Data File → Metabolite Assignment File

        存在しない骨格列は飛ばす（Extract Name は MSI に無い、Processed Data File /
        Metabolite Assignment File は任意）。列の有無は MB_SR0004 の担当。
        同名の骨格列が複数あれば最初の出現位置で評価する。
        """
        if not sub.sdrf:
            return []
        skeleton = _sdrf_def(context).get("column_order_skeleton", [])
        if not skeleton:
            return []
        # 存在する骨格列を (列名, 最初の出現位置) で拾う
        present = []
        for col in skeleton:
            idxs = sub.sdrf.col_indices(col)
            if idxs:
                present.append((col, idxs[0]))
        out = []
        for (prev_col, prev_i), (col, i) in zip(present, present[1:]):
            if i < prev_i:
                out.append(self.result(
                    message=f"{self.description} ('{col}' (column {i + 1}) must come after "
                            f"'{prev_col}' (column {prev_i + 1}))",
                    column=col))
        return out


class MB_SR0033(MbRule):
    rule_id = "MB_SR0033"; level = "error"; target = "SDRF"
    description = "Missing protocol reference (Protocol REF value)."

    def validate(self, sub, context):
        if not sub.sdrf:
            return []
        idxs = sub.sdrf.col_indices("Protocol REF")
        if not idxs:
            return []
        out = []
        for r, row in enumerate(sub.sdrf.rows):
            if all(_empty(row[i]) if i < len(row) else True for i in idxs):
                out.append(self.result(message=f"{self.description} (row {r + 1})",
                                       assay=_assay(sub, row), line=r + 1,
                                       column="Protocol REF", source_name=_source_name(sub, row)))
        return out


class MB_SR0049(MbRule):
    # ルール表の名前: Absent Protocol REF
    rule_id = "MB_SR0049"; level = "error"; target = "SDRF"
    description = "Protocol REF is missing from all SDRF rows."

    def validate(self, sub, context):
        """`Protocol REF` 列を **列単位** で見て、どの行にも値が無い列を error にする。

        MB_SR0033（行単位＝その行の Protocol REF が全部空）との役割分担:
        - 行の欠落 → MB_SR0033
        - **列の欠落** → このルール。工程が 1 つ丸ごと書かれていない状態を拾う。
        Protocol REF は同名列が工程の数だけ並ぶ順序付き列なので、1 列だけ全行空でも
        行単位では他の列に値があり MB_SR0033 が発火せず、これまで無指摘だった。

        値が「無い」は **空セルと null value（missing 等）を同じ扱い** にする
        （工程が無いなら列そのものを書かないのが正規の書き方で、null value を書いても
        工程を書いたことにはならないため）。
        同名列が並ぶため、どの列かは `Protocol REF #n of m`（左から何本目）と
        SDRF 上の列位置で示す。データ行が 1 行も無い SDRF では何も出さない。
        """
        if not sub.sdrf or not sub.sdrf.rows:
            return []
        idxs = sub.sdrf.col_indices("Protocol REF")
        if not idxs:
            return []      # 列そのものが無いのは MB_SR0004 の担当
        nulls = null_values(context)
        out = []
        for n, i in enumerate(idxs, start=1):
            vals = [(row[i] if i < len(row) else "") for row in sub.sdrf.rows]
            if _has_no_value(vals, nulls):
                out.append(self.result(
                    message=f"{self.description} (Protocol REF #{n} of {len(idxs)}, column {i + 1})",
                    column=f"Protocol REF #{n} of {len(idxs)} (column {i + 1})", rows=len(vals)))
        return out


class MB_SR0050(MbRule):
    # ルール表の名前: Duplicated Assay Name
    rule_id = "MB_SR0050"; level = "error"; target = "SDRF"
    description = "Assay Name is not unique."

    def validate(self, sub, context):
        """`Assay Name` の値が 2 行以上に現れていないか。

        Assay Name は行（＝測定）を一意に指す名前で、レポートの location にも使っている
        （重複すると指摘がどの行か特定できない）。

        値が「無い」行（空セル・null value）は **対象外**。値が無いことは MB_SR0009 の
        担当で、空同士・null 同士を重複と数えると二重報告になるため。
        比較は前後の空白を落とした完全一致（大文字小文字は区別する。別表記は別の名前）。
        報告は **重複値ごとに 1 件**（行数が多くても件数が膨らまないようにする）。
        Assay Name は singleton 列なので列自体の重複は MB_SR0003 の担当。ここは 1 列目を見る。
        """
        if not sub.sdrf:
            return []
        idxs = sub.sdrf.col_indices("Assay Name")
        if not idxs:
            return []      # 列そのものが無いのは MB_SR0004 の担当
        nulls = null_values(context)
        i = idxs[0]
        seen = {}
        for r, row in enumerate(sub.sdrf.rows):
            v = (row[i] if i < len(row) else "").strip()
            if _absent(v, nulls):
                continue
            seen.setdefault(v, []).append(r + 1)
        out = []
        for v, rows in seen.items():
            if len(rows) > 1:
                out.append(self.result(
                    message=f"{self.description} ('{v}', rows {', '.join(str(x) for x in rows)})",
                    column="Assay Name", value=v, rows=len(rows)))
        return out


class MB_SR0030(MbRule):
    rule_id = "MB_SR0030"; level = "error"; target = "SDRF"
    # SDRF 側の非 ASCII 検査（IDF の MB_IR0024 と同仕様）。reader で正規化済み。
    # mapped は warning（autofix 報告）、残存非 ASCII と制御文字は error。
    description = "Non-ASCII or control characters in an SDRF cell."

    def validate(self, sub, context):
        from apps.metabobank.charnorm import fix_warning_message, residual_error_message
        if not sub.sdrf:
            return []
        out = []
        rows = sub.sdrf.rows
        # (1) 非 ASCII 正規化の報告（reader で適用済み。char_fixes 参照）
        for fx in getattr(sub, "char_fixes", []):
            if fx["target"] != "SDRF":
                continue
            line = fx["line"]
            row = rows[line - 1] if line and line - 1 < len(rows) else []
            where = f"{fx['where']}, row {line}"
            if fx["mapped"]:
                out.append(self.result(message=fix_warning_message(where, fx["mapped"]),
                                       level="warning", assay=_assay(sub, row), line=line,
                                       column=fx["where"], value="".join(sorted(fx["mapped"])),
                                       source_name=_source_name(sub, row)))
            if fx["residual"]:
                out.append(self.result(message=residual_error_message(where, fx["residual"]),
                                       level="error", assay=_assay(sub, row), line=line,
                                       column=fx["where"], value="".join(sorted(fx["residual"])),
                                       source_name=_source_name(sub, row)))
        # (2) 制御文字（ord<32・タブ除く）は残存非 ASCII と同様に error
        for r, row in enumerate(rows):
            ctrl = {ch for cell in row for ch in cell if ord(ch) < 32 and ch != "\t"}
            if ctrl:
                out.append(self.result(message=residual_error_message(f"row {r + 1}", ctrl),
                                       level="error", assay=_assay(sub, row), line=r + 1,
                                       value="".join(sorted(ctrl)), source_name=_source_name(sub, row)))
        return out


class _SdrfCvBase(MbRule):
    _level_key = None
    def validate(self, sub, context):
        if not sub.sdrf:
            return []
        cv = ((context.definitions or {}).get("controlled_terms", {}).get("sdrf", {}).get(self._level_key, {}))
        out = []
        for col, allowed in cv.items():
            idxs = sub.sdrf.col_indices(col)
            for r, row in enumerate(sub.sdrf.rows):
                for i in idxs:
                    v = row[i] if i < len(row) else ""
                    if v and v.strip() and v.strip() not in allowed:
                        out.append(self.result(message=f"{self.description} ({col}: '{v}')",
                                               assay=_assay(sub, row), line=r + 1,
                                               column=col, value=v, source_name=_source_name(sub, row)))
        return out


class MB_SR0045(_SdrfCvBase):
    rule_id = "MB_SR0045"; level = "error"; target = "SDRF"; _level_key = "error"
    description = "Value is not in controlled terms."


class MB_SR0046(_SdrfCvBase):
    rule_id = "MB_SR0046"; level = "warning"; target = "SDRF"; _level_key = "warning"
    description = "Value is not in controlled terms."


# --- Protocol REF の type 参照チェック（MB_SR0034 / MB_SR0035）------------------

_DATA_FILE_COLUMNS = ("Raw Data File", "Processed Data File", "Metabolite Assignment File")


def _protocol_name_to_type(sub):
    """IDF の Protocol Name -> Protocol Type の対応表。"""
    if not sub.idf:
        return {}
    return {p["Protocol Name"].strip(): (p["Protocol Type"] or "").strip()
            for p in sub.idf.protocols() if p["Protocol Name"].strip()}


def _protocol_types_per_ref_column(sub):
    """Protocol REF 列ごとに、その列が参照している protocol type の集合を返す。

    戻り値: [(列インデックス, [type, ...]), ...]。IDF で type を引けない値は無視する。
    """
    name2type = _protocol_name_to_type(sub)
    out = []
    for i in sub.sdrf.col_indices("Protocol REF"):
        types = set()
        for row in sub.sdrf.rows:
            v = (row[i] if i < len(row) else "").strip()
            t = name2type.get(v)
            if t:
                types.add(t)
        out.append((i, sorted(types)))
    return out


class MB_SR0034(MbRule):
    rule_id = "MB_SR0034"; level = "error"; target = "SDRF"
    description = ("More than one protocol type are referenced in Protocol REF. "
                   "Specify protocol name(s) of single type.")

    def validate(self, sub, context):
        if not sub.sdrf or not sub.idf:
            return []
        out = []
        for i, types in _protocol_types_per_ref_column(sub):
            if len(types) > 1:
                out.append(self.result(
                    message=f"{self.description} (Protocol REF at column {i + 1}: {', '.join(types)})",
                    column=f"Protocol REF (column {i + 1})", value=", ".join(types)))
        return out


class MB_SR0035(MbRule):
    rule_id = "MB_SR0035"; level = "warning"; target = "SDRF"
    description = "A protocol type is referenced from different Protocol REF columns."

    def validate(self, sub, context):
        if not sub.sdrf or not sub.idf:
            return []
        # 列ごとの代表 type（ruby と同じく sort uniq の先頭）が複数列で重複していれば warning
        rep = [types[0] for _, types in _protocol_types_per_ref_column(sub) if types]
        dup = sorted({t for t in rep if rep.count(t) > 1})
        if not dup:
            return []
        return [self.result(message=f"{self.description} ({', '.join(dup)})", column=", ".join(dup))]


# --- データファイル名・ディレクトリ名の禁則文字（MB_SR0036 / MB_SR0037）--------

_VALID_FILENAME = re.compile(r"^[-_A-Za-z0-9. ]+$")
_VALID_DIRNAME = re.compile(r"^[-_A-Za-z0-9./ ]+$")


def _data_file_entries(sub):
    """データファイル列に現れるパスを (パス, 最初の行番号, その行) で返す（重複除去）。"""
    seen = {}
    for col in _DATA_FILE_COLUMNS:
        for i in sub.sdrf.col_indices(col):
            for r, row in enumerate(sub.sdrf.rows):
                v = (row[i] if i < len(row) else "").strip()
                if v and v not in seen:
                    seen[v] = (r + 1, row)
    return [(path, line, row) for path, (line, row) in seen.items()]


def _split_path(path):
    """SDRF のデータファイルパスを (ディレクトリ名, ファイル名) に分ける。

    先頭が '/' や './' の絶対・相対指定はファイル名として不正扱い（ruby と同じ）。
    末尾が '/' のものはディレクトリ指定とみなす。
    """
    if re.match(r"^\.?/+", path):
        return "", path          # 不正な先頭 → ファイル名側で弾く
    if path.endswith("/"):
        return path.rstrip("/"), ""
    if "/" in path:
        return path.rsplit("/", 1)[0], path.rsplit("/", 1)[1]
    return "", path


class MB_SR0036(MbRule):
    rule_id = "MB_SR0036"; level = "error"; target = "SDRF"
    description = ("Invalid character in file name. Use only alphanumerals [A-Z,a-z,0-9], "
                   "underscores [_], hyphens [-], spaces and dots [.] for file name.")

    def validate(self, sub, context):
        if not sub.sdrf:
            return []
        out = []
        for path, line, row in _data_file_entries(sub):
            _, filename = _split_path(path)
            if filename and not _VALID_FILENAME.fullmatch(filename):
                out.append(self.result(message=f"{self.description} ('{filename}')",
                                       assay=_assay(sub, row), line=line,
                                       value=filename, source_name=_source_name(sub, row)))
        return out


class MB_SR0037(MbRule):
    rule_id = "MB_SR0037"; level = "error"; target = "SDRF"
    description = ("Invalid character in directory name. Use only alphanumerals [A-Z,a-z,0-9], "
                   "underscores [_], hyphens [-] and dots [.] for directory name.")

    def validate(self, sub, context):
        if not sub.sdrf:
            return []
        out, seen = [], set()
        for path, line, row in _data_file_entries(sub):
            dirname, _ = _split_path(path)
            if dirname and dirname not in seen and not _VALID_DIRNAME.fullmatch(dirname):
                seen.add(dirname)
                out.append(self.result(message=f"{self.description} ('{dirname}')",
                                       assay=_assay(sub, row), line=line,
                                       value=dirname, source_name=_source_name(sub, row)))
        return out
