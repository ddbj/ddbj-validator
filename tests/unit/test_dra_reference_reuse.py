"""DRA_R0040 / R0049: reference_fasta / tab を複数 Run で使い回すのは認める。DRA_R0031: 454 seq ＋ qual は組、fastq ＋ qseq の混在は許容（2026-10-06）。

bam の参照配列（reference_fasta）と対応表（tab）は Run 間で共通になりうる。
各 Run に 1 回ずつなら、同じ filename（R0040）でも、別名で同じ md5（R0049）でも出さない。
それ以外の filetype や、同じ Run 内での重複は従来どおり error。
"""
from types import SimpleNamespace

from apps.dra.model import DraAnalysis, DraFile, DraRun
from apps.dra.rules.file import DRA_R0040, DRA_R0049

MD5_REF = "a" * 32
MD5_TAB = "b" * 32


def _run(acc, *files):
    return DraRun(accession=acc, files=[DraFile(filename=n, filetype=t, checksum=c) for n, t, c in files])


def _sub(*runs, analyses=()):
    return SimpleNamespace(runs=list(runs), analyses=list(analyses))


def _bam_run(acc, ref="ref.fa", tab="ref.tab", bam=None):
    return _run(acc, (bam or f"{acc}.bam", "bam", f"{acc:0>32}"[-32:]),
                (ref, "reference_fasta", MD5_REF), (tab, "tab", MD5_TAB))


def test_r0040_same_reference_and_tab_in_each_run_is_allowed():
    sub = _sub(_bam_run("DRR000001"), _bam_run("DRR000002"))
    assert DRA_R0040().validate(sub, None) == []


def test_r0049_renamed_reference_per_run_is_allowed():
    # 過去データの形: 同じ参照を Run ごとに名前を変えて登録
    sub = _sub(_bam_run("DRR000001", ref="r1.fa", tab="r1.tab"),
               _bam_run("DRR000002", ref="r2.fa", tab="r2.tab"))
    assert DRA_R0049().validate(sub, None) == []


def test_r0040_other_filetype_shared_across_runs_is_still_error():
    sub = _sub(_run("DRR000001", ("reads.fq.gz", "fastq", "c" * 32)),
               _run("DRR000002", ("reads.fq.gz", "fastq", "c" * 32)))
    assert len(DRA_R0040().validate(sub, None)) == 1


def test_r0049_other_filetype_same_md5_is_still_error():
    sub = _sub(_run("DRR000001", ("a.fq.gz", "fastq", "c" * 32)),
               _run("DRR000002", ("b.fq.gz", "fastq", "c" * 32)))
    assert len(DRA_R0049().validate(sub, None)) == 1


def test_reference_twice_in_same_run_is_still_error():
    run = _run("DRR000001", ("x.bam", "bam", "d" * 32),
               ("ref.fa", "reference_fasta", MD5_REF), ("ref.fa", "reference_fasta", MD5_REF))
    assert len(DRA_R0040().validate(_sub(run), None)) == 1
    run2 = _run("DRR000001", ("x.bam", "bam", "d" * 32),
                ("r1.fa", "reference_fasta", MD5_REF), ("r2.fa", "reference_fasta", MD5_REF))
    assert len(DRA_R0049().validate(_sub(run2), None)) == 1


def test_reference_shared_with_analysis_is_still_error():
    ana = DraAnalysis(accession="DRZ000001", files=[DraFile(filename="ref.fa", filetype="fasta", checksum=MD5_REF)])
    sub = _sub(_bam_run("DRR000001"), analyses=[ana])
    assert len(DRA_R0040().validate(sub, None)) == 1


# --- DRA_R0031: 454 seq ＋ qual は組として valid（2026-10-06） ---

def test_r0031_454_seq_and_qual_pair_is_not_mixed():
    from apps.dra.rules.file import DRA_R0031
    run = _run("DRR000770", ("1S.fa", "454_native_seq", "e" * 32), ("1Q.qual", "454_native_qual", "f" * 32))
    assert DRA_R0031().validate(_sub(run), None) == []
    # 454 seq と fastq の混在は従来どおり error
    run2 = _run("DRR000771", ("1S.fa", "454_native_seq", "e" * 32), ("r.fq.gz", "fastq", "f" * 32))
    assert len(DRA_R0031().validate(_sub(run2), None)) == 1


def test_r0031_fastq_and_illumina_qseq_mix_is_allowed():
    from apps.dra.rules.file import DRA_R0031
    run = _run("DRR002292", ("s_2_1_sequence.txt.gz", "fastq", "1" * 32), ("s_2_2_sequence.txt.gz", "fastq", "2" * 32),
               ("110424_l3.tgz", "Illumina_native_qseq", "3" * 32))
    assert DRA_R0031().validate(_sub(run), None) == []
    # generic_fastq との混在は従来どおり error
    run2 = _run("DRR517163", ("Y32821.fas", "generic_fastq", "4" * 32), ("R1.fastq.gz", "fastq", "5" * 32))
    assert len(DRA_R0031().validate(_sub(run2), None)) == 1
