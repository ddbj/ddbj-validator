"""DRA XML 群のパース。

役割は **root 要素**で判定する（ファイル名や submission の ACTIONS/ADD@source は使わない）:
  SUBMISSION / EXPERIMENT_SET / RUN_SET / ANALYSIS_SET。
1 セッションに渡された XML 群を 1 つの DraSubmission に束ねる。

- DRA_R0001: XML well-formed（パース失敗で検出）。
- DRA_R0032: submission XML が無い（Experiment/Run/Analysis 提出には submission 必須）。
- DRA_R0002（XSD）は well-formed＋構造の粗いゲートに縮小（別途 structure.py 側で構造チェック）。
戻り値: (DraSubmission, pre_errors[])。
"""
import defusedxml.ElementTree as ET
from apps.dra.model import (
    DraSubmission, DraSubmissionMeta, DraExperiment, DraRun, DraAnalysis, DraFile,
)


def _text(el):
    return el.text.strip() if el is not None and el.text and el.text.strip() else None


def _err(rule_id, message, target="#file_format", sample=None, level="error"):
    return {"rule_id": rule_id, "level": level, "target": target, "sample": sample, "message": message}


def _files(node):
    out = []
    for f in node.findall(".//DATA_BLOCK/FILES/FILE"):
        out.append(DraFile(filename=f.get("filename"), filetype=f.get("filetype"),
                           checksum_method=f.get("checksum_method"), checksum=f.get("checksum")))
    return out


def _build_submission(root):
    m = DraSubmissionMeta(alias=root.get("alias"), accession=root.get("accession"),
                          center_name=root.get("center_name"), lab_name=root.get("lab_name"),
                          submission_date=root.get("submission_date"), raw=root)
    hold = root.find(".//ACTIONS/ACTION/HOLD")
    if hold is not None:
        m.hold_date = hold.get("HoldUntilDate")
    for c in root.findall(".//CONTACTS/CONTACT"):
        m.contacts.append({"name": c.get("name"), "inform_on_status": c.get("inform_on_status"),
                           "inform_on_error": c.get("inform_on_error")})
    return m


def _build_experiment(exp):
    e = DraExperiment(alias=exp.get("alias"), accession=exp.get("accession"),
                      center_name=exp.get("center_name"), title=_text(exp.find("./TITLE")), raw=exp)
    e.description = _text(exp.find("./DESIGN/DESIGN_DESCRIPTION"))
    sref = exp.find("./STUDY_REF")
    if sref is not None:
        e.study_ref = sref.get("accession")
    samp = exp.find("./DESIGN/SAMPLE_DESCRIPTOR")
    if samp is not None:
        e.sample_ref = samp.get("accession")
    lib = exp.find("./DESIGN/LIBRARY_DESCRIPTOR")
    if lib is not None:
        e.library_name = _text(lib.find("./LIBRARY_NAME"))
        e.library_strategy = _text(lib.find("./LIBRARY_STRATEGY"))
        e.library_source = _text(lib.find("./LIBRARY_SOURCE"))
        e.library_selection = _text(lib.find("./LIBRARY_SELECTION"))
        layout = lib.find("./LIBRARY_LAYOUT")
        if layout is not None:
            for child in list(layout):
                e.library_layout = child.tag       # SINGLE / PAIRED
                if child.tag == "PAIRED":
                    e.nominal_length = child.get("NOMINAL_LENGTH")
                break
    plat = exp.find("./PLATFORM")
    if plat is not None and len(list(plat)):
        pchild = list(plat)[0]
        e.platform = pchild.tag                    # ILLUMINA / PACBIO_SMRT 等
        e.instrument_model = _text(pchild.find("./INSTRUMENT_MODEL"))
    return e


def _build_run(run):
    r = DraRun(alias=run.get("alias"), accession=run.get("accession"),
               center_name=run.get("center_name"), title=_text(run.find("./TITLE")), raw=run)
    ref = run.find("./EXPERIMENT_REF")
    if ref is not None:
        r.experiment_ref = ref.get("accession")
        r.experiment_refname = ref.get("refname")
    r.files = _files(run)
    return r


def _build_analysis(an):
    a = DraAnalysis(alias=an.get("alias"), accession=an.get("accession"),
                    center_name=an.get("center_name"), title=_text(an.find("./TITLE")),
                    description=_text(an.find("./DESCRIPTION")), raw=an)
    sref = an.find("./STUDY_REF")
    if sref is not None:
        a.study_ref = sref.get("accession")
    for t in an.findall("./TARGETS/TARGET"):
        typ = (t.get("sra_object_type") or "").upper()
        acc = t.get("accession")
        if not acc:
            continue
        if typ == "SAMPLE":
            a.sample_refs.append(acc)
        elif typ == "RUN":
            a.run_refs.append(acc)
    a.files = _files(an)
    return a


# root タグ -> 役割
_ROOTS = {"SUBMISSION": "submission", "EXPERIMENT_SET": "experiment",
          "RUN_SET": "run", "ANALYSIS_SET": "analysis"}


def parse_files(paths, account=None):
    """XML パス群（役割混在可）をパースして (DraSubmission, pre_errors)。役割は root で判定。"""
    sub = DraSubmission(account=account)
    pre = []
    for p in paths:
        try:
            root = ET.parse(str(p)).getroot()
        except Exception as e:
            pre.append(_err("DRA_R0001", f"XML document is not well-formed. ({e})", sample=str(p)))
            continue
        role = _ROOTS.get(root.tag)
        if role == "submission":
            if sub.submission is None:
                sub.submission = _build_submission(root)
        elif role == "experiment":
            sub.experiments.extend(_build_experiment(x) for x in root.findall("./EXPERIMENT"))
        elif role == "run":
            sub.runs.extend(_build_run(x) for x in root.findall("./RUN"))
        elif role == "analysis":
            sub.analyses.extend(_build_analysis(x) for x in root.findall("./ANALYSIS"))
        # 不明な root は無視（DRA_R0002 構造チェックで扱う余地）

    # DRA_R0032: Experiment/Run/Analysis を出すなら submission が必須
    if sub.submission is None and (sub.experiments or sub.runs or sub.analyses):
        pre.append(_err("DRA_R0032", "Submission XML is required for submitting Experiment, Run and Analysis."))
    return sub, pre
