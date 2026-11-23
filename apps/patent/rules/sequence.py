"""特許の配列を見る規則（PAT0020〜PAT0023、PAT0037〜PAT0042）。

parser は配列を小文字にして持つので、大文字・小文字や AA の文字は parser の record では判定できない。
FASTA の本文を 1 回だけなめて、全部の検査をここで行う。
flag = 通して印を返す（公開はするが INSDC には交換しない、の判断に TSM が使う）。
"""
from common.rules.base import BaseRule
from apps.patent import constants as C


def iter_fasta(fasta_content):
    """FASTA の本文から (entry 名, 配列) を順に返す。配列は改行と末尾の `//` だけを除いたそのままの文字。"""
    if not fasta_content:
        return
    data = fasta_content[1:] if fasta_content.startswith(">") else fasta_content
    for block in data.split("\n>"):
        if not block or block.isspace():
            continue
        header, _, body = block.partition("\n")
        name = header.split(None, 1)[0] if header.strip() else ""
        body = body.rstrip()
        if body.endswith("//"):
            body = body[:-2]
        yield name, body.replace("\n", "").replace("\r", "")


def _shown(chars):
    """報告に出す文字の並び（多いときは先頭 10 個）。"""
    chars = sorted(chars)
    return "".join(chars[:10]) + ("..." if len(chars) > 10 else "")


class PAT_SEQUENCE(BaseRule):
    rule_id = "PAT_SEQUENCE"
    target = "sequence"
    is_file_level = True
    internal_ignore = False

    def validate_file(self, records, context, ann_path=None, seq_path=None, fasta_content=None):
        kind = getattr(context, "pat_kind", None)
        check = {C.KIND_NA: self._check_na, C.KIND_AA: self._check_aa}.get(kind)
        if check is None:
            return []  # ファイル名から NA / AA が決まらないのは PAT0045
        results = []
        for name, seq in iter_fasta(fasta_content):
            if not seq:
                results.append(self._res(name, "PAT0021", "error", "The sequence is empty."))
                continue
            check(name, seq, results)
        return results

    def _res(self, entry, rule, level, message):
        return self.format_result(entry, message, level=level, feature_type="sequence", rule=rule)

    def _check_na(self, name, seq, results):
        chars = set(seq)
        lower = {c.lower() for c in chars}
        invalid = lower - C.NA_CHARS
        if invalid:
            results.append(self._res(name, "PAT0020", C.LEVEL_FLAG,
                                     f"The nucleotide sequence has characters other than IUPAC nucleotide codes. "
                                     f"(Found: '{_shown(invalid)}')"))
            aa_only = invalid & C.NA_AA_ONLY_CHARS
            if aa_only:
                results.append(self._res(name, "PAT0039", C.LEVEL_FLAG,
                                         f"The nucleotide sequence has characters used only for amino acids (NAwithAA). "
                                         f"(Found: '{_shown(aa_only)}')"))
        if lower == {"n"}:
            results.append(self._res(name, "PAT0022", C.LEVEL_FLAG, "The nucleotide sequence consists of only 'n'."))
        if len(seq) < C.MIN_LEN_NA:
            results.append(self._res(name, "PAT0038", "warning",
                                     f"The nucleotide sequence is shorter than {C.MIN_LEN_NA}. (Length: {len(seq)})"))
        if any(c.isupper() for c in chars):
            results.append(self._res(name, "PAT0042", "warning", "The nucleotide sequence has uppercase letters."))

    def _check_aa(self, name, seq, results):
        chars = set(seq)
        upper_chars = {c.upper() for c in chars}
        invalid = upper_chars - C.AA_CHARS
        if invalid:
            results.append(self._res(name, "PAT0037", "error",
                                     f"The amino acid sequence has characters other than amino acid codes. "
                                     f"(Found: '{_shown(invalid)}')"))
        if upper_chars == {"X"}:
            results.append(self._res(name, "PAT0023", C.LEVEL_FLAG, "The amino acid sequence consists of only 'X'."))
        length = len(seq)
        if length < C.MIN_LEN_AA:
            results.append(self._res(name, "PAT0038", "warning",
                                     f"The amino acid sequence is shorter than {C.MIN_LEN_AA}. (Length: {length})"))
        upper = seq.upper()
        if length >= C.AA_NA_LIKE_MIN_LEN and not invalid:
            na_like = sum(upper.count(c) for c in C.AA_NA_LIKE_CHARS)
            if na_like >= length * C.AA_NA_LIKE_RATIO:
                results.append(self._res(name, "PAT0040", C.LEVEL_FLAG,
                                         f"The amino acid sequence looks like a nucleotide sequence (AAwithNA). "
                                         f"(A/C/G/T/U: {na_like} of {length})"))
        if length >= 3:
            three = sum(1 for i in range(0, length - 2, 3) if upper[i:i + 3] in C.AA_THREE_LETTER)
            if three * 3 >= length * C.AA_3L_RATIO:
                results.append(self._res(name, "PAT0041", C.LEVEL_FLAG,
                                         f"The amino acid sequence looks like three-letter codes (AAwith3L). "
                                         f"(Three-letter codes: {three} in {length} characters)"))
        if any(c.islower() for c in chars):
            results.append(self._res(name, "PAT0042", "warning", "The amino acid sequence has lowercase letters."))
