"""SDRF ルール（MB_SR。metadata 分。ファイル実体/MAF 検証は別ツール＝非対象）。"""
import re
from apps.metabobank.rules.base import MbRule, null_values


def _sdrf_def(context):
    return (context.definitions or {}).get("sdrf", {})


def _empty(v):
    return v is None or str(v).strip() == ""


def _matches_any(colname, patterns):
    for p in patterns:
        try:
            if re.fullmatch(p, colname) or re.search(p, colname):
                return True
        except re.error:
            if p == colname:
                return True
    return False


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
        return [self.result(message=f"{self.description} ({', '.join(sorted(dup))})")] if dup else []


class MB_SR0024(MbRule):
    rule_id = "MB_SR0024"; level = "error"; target = "SDRF"
    description = "Column without a name exists."

    def validate(self, sub, context):
        if not sub.sdrf:
            return []
        return [self.result()] if any(_empty(h) for h in sub.sdrf.header) else []


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
        return [self.result(message=f"{self.description} ({', '.join(miss)})")] if miss else []


class MB_SR0005(MbRule):
    # required_columns_warning は正規表現パターン（Comment\[BioSample\] 等）＝regex で判定。
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
        return [self.result(message=f"{self.description} ({', '.join(miss)})")] if miss else []


class MB_SR0006(MbRule):
    rule_id = "MB_SR0006"; level = "error"; target = "SDRF"
    description = "Undefined column exists."

    def validate(self, sub, context):
        if not sub.sdrf:
            return []
        patterns = _sdrf_def(context).get("fields", [])
        bad = [h for h in sub.sdrf.header if h and not _matches_any(h, patterns)]
        return [self.result(message=f"{self.description} ({', '.join(sorted(set(bad)))})")] if bad else []


class MB_SR0009(MbRule):
    rule_id = "MB_SR0009"; level = "error"; target = "SDRF"
    description = "Missing or null value for a required column."

    def validate(self, sub, context):
        if not sub.sdrf:
            return []
        nulls = null_values(context)
        out = []
        for col in ("Characteristics[organism]", "Characteristics[taxonomy_id]", "Source Name"):
            idxs = sub.sdrf.col_indices(col)
            if not idxs:
                continue
            for r, row in enumerate(sub.sdrf.rows):
                v = row[idxs[0]] if idxs[0] < len(row) else ""
                if _empty(v) or v.strip() in nulls:
                    out.append(self.result(message=f"{self.description} ({col}, row {r + 1})", assay=_assay(sub, row), line=r + 1))
                    break
        return out


class MB_SR0018(MbRule):
    rule_id = "MB_SR0018"; level = "warning"; target = "SDRF"
    description = "Less than 2 characteristic attributes."

    def validate(self, sub, context):
        if not sub.sdrf:
            return []
        chars = [h for h in sub.sdrf.header if re.fullmatch(r"Characteristics\[[-_ /A-Za-z0-9.]+\]", h)]
        return [self.result(message=f"{self.description} (Found: {len(chars)})")] if len(chars) < 2 else []


class MB_SR0017(MbRule):
    rule_id = "MB_SR0017"; level = "error"; target = "SDRF"
    description = "Factor value is constant across all rows."

    def validate(self, sub, context):
        if not sub.sdrf or len(sub.sdrf.rows) < 2:
            return []
        out = []
        for h in sub.sdrf.header:
            if re.fullmatch(r"Factor Value\[.+\]", h):
                idxs = sub.sdrf.col_indices(h)
                vals = {(row[idxs[0]].strip() if idxs[0] < len(row) else "") for row in sub.sdrf.rows}
                if len(vals) == 1:
                    out.append(self.result(message=f"{self.description} ({h})"))
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
                        out.append(self.result(message=f"{self.description} ({col}: '{v}')", assay=_assay(sub, row), line=r + 1))
        return out


class MB_SR0026(MbRule):
    rule_id = "MB_SR0026"; level = "error"; target = "SDRF"
    description = "Invalid column order."

    def validate(self, sub, context):
        if not sub.sdrf:
            return []
        st = sub.idf.submission_type if sub.idf else None
        order = _sdrf_def(context).get("column_order", {}).get(st)
        if not order:
            return []
        # order の「素の列種別」列（Characteristics[] や Protocol REF:x を種別に正規化）に対する相対順序をチェック
        def kind(h):
            m = re.match(r"^(Characteristics|Comment|Parameter Value|Factor Value|Unit)\[", h)
            return (m.group(1) + "[]") if m else h
        seq = [kind(h) for h in sub.sdrf.header]
        # order 中の Protocol REF:xxx は Protocol REF に丸め、種別列も丸める
        norm_order = []
        for o in order:
            norm_order.append("Protocol REF" if o.startswith("Protocol REF") else o)
        # header 側の Protocol REF は複数だが順序上は出現順で評価。ここでは「必須種別が定義順に現れるか」を緩く検査。
        pos = 0
        for o in norm_order:
            found = False
            while pos < len(seq):
                if seq[pos] == o or (o == "Characteristics[]" and seq[pos] == "Characteristics[]"):
                    found = True
                    pos += 1
                    break
                pos += 1
            # 見つからなくても次へ（任意列があるため厳密チェックはしない）
        # 厳密な順序違反判定は複雑なため、ここでは Source Name が先頭かの最低限のみ error 化
        if seq and seq[0] != "Source Name":
            return [self.result(message=f"{self.description} (first column: '{sub.sdrf.header[0]}', expected 'Source Name')")]
        return []


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
                out.append(self.result(message=f"{self.description} (row {r + 1})", assay=_assay(sub, row), line=r + 1))
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
                                       level="warning", assay=_assay(sub, row), line=line))
            if fx["residual"]:
                out.append(self.result(message=residual_error_message(where, fx["residual"]),
                                       level="error", assay=_assay(sub, row), line=line))
        # (2) 制御文字（ord<32・タブ除く）は残存非 ASCII と同様に error
        for r, row in enumerate(rows):
            ctrl = {ch for cell in row for ch in cell if ord(ch) < 32 and ch != "\t"}
            if ctrl:
                out.append(self.result(message=residual_error_message(f"row {r + 1}", ctrl),
                                       level="error", assay=_assay(sub, row), line=r + 1))
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
                        out.append(self.result(message=f"{self.description} ({col}: '{v}')", assay=_assay(sub, row), line=r + 1))
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
                    message=f"{self.description} (Protocol REF at column {i + 1}: {', '.join(types)})"))
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
        return [self.result(message=f"{self.description} ({', '.join(dup)})")]


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
                                       assay=_assay(sub, row), line=line))
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
                                       assay=_assay(sub, row), line=line))
        return out
