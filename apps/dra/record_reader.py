"""DDBJ Record（v3 JSON）のパース。xml_reader と同じ契約で DraSubmission を組む。

- DRA_R0001: JSON well-formed（パース失敗で検出）。
- DRA_R0002: 形状・スキーマ違反と、v3 スキーマが縛らないが SRA XSD が縛っていたこと
  （relation の source が解決できない、1 つしか書けない参照が 2 つある、library.layout の値）。
  XML の DRA_R0044〜R0047（役割ごとの XSD）に当たるが、record は 1 ドキュメントなので
  役割で分けず、DRA_R0002（"invalid against the schema"）に寄せる。BP_R0002 / BS_R0098 と同じ。
- DRA_R0032: experiments / runs / analyses があるのに submission が無い。

v3 → DraSubmission の対応（ddbj-record-specifications の tests/fixtures/v3/mapping/sra.yml が正本）:

    submission.accession / alias / center_name -> submission の同名
    submission.sra.lab_name / submission_date  -> lab_name / submission_date
    submission.sra.contacts[]                  -> contacts [{name, inform_on_status, inform_on_error}]
    submission.hold_date                       -> hold_date
    experiments[].accession / alias / center_name / title / description
                                               -> experiment の同名（description は DESIGN_DESCRIPTION）
    experiments[].library.name / strategy / source / selection
                                               -> library_name / _strategy / _source / _selection
    experiments[].library.layout               -> library_layout（"paired" -> "PAIRED"）
    experiments[].library.nominal_length       -> nominal_length（paired のときだけ。XML と同じ）
    experiments[].platform.type / instrument_model
                                               -> platform / instrument_model
    runs[] / analyses[] の accession / alias / center_name / title（analysis は description も）
    runs[] / analyses[].data_blocks[].files[]  -> files [DraFile(filename, filetype, checksum_method, checksum)]

参照（XML の *_REF）は object の中でなく、ルートの `relations` にある。source がその object:

    experiment --part_of--> {db: project}      target.accession -> study_ref      （STUDY_REF）
    experiment --part_of--> {db: sample}       target.accession -> sample_ref     （SAMPLE_DESCRIPTOR）
    run        --part_of--> {db: experiment}   target.accession -> experiment_ref （EXPERIMENT_REF）
                                               target.id        -> experiment_refname（@refname）
    analysis   --part_of--> {db: project}      target.accession -> study_ref      （STUDY_REF）
    analysis   --derived_from--> {db: sample}  target.accession -> sample_refs[]  （TARGET, SAMPLE）
    analysis   --derived_from--> {db: run}     target.accession -> run_refs[]     （TARGET, RUN）

target.db は相手の種類を record の種類の名前で書く（sra.yml の「種類の名前にした値」、
ddbj/ddbj-record-specifications#19）。source は accession で、無ければ alias（同じ alias が
複数あれば、その中での位置を index）で指す（#18）。XML と同じく accession の無い TARGET は読まない。

**source が解決できない relation は DRA_R0002 の error にする。** その参照は読めないので
DRA_R0034 / R0035 なども「参照が無い」と言うが、それだけだと書いたはずの参照がなぜ無いことに
なったのかが分からない。原因（どの relation がどの object も指していないか）を別に言う。
同じく、XML では 1 つしか書けない参照（STUDY_REF、SAMPLE_DESCRIPTOR、EXPERIMENT_REF）が
2 つあれば error にする（XML なら XSD 違反）。1 つ目は読み、検証は続ける。

XML に無く、v3 で読み替えたもの:

    DESIGN（DRA_R0002） -- v3 に入れ物としては無い。DESIGN の下にあったもの（description、
        library、spot_descriptor、pool、legacy.gaps、sample への relation）のどれかがあれば
        「ある」とする。中身の無い <DESIGN/> や <LIBRARY_DESCRIPTOR/>、<DATA_BLOCK/> は v3 に
        書く場所が無く（converter も落とす）、record では「無い」になる。
    submission の役割ファイル（role_files） -- record ではファイルが 1 つなので、その名前を
        載っている役割すべてに置く（レポートの見出し用）。
    submission id / account -- XML と同じく CLI が submission.alias から導く。

**読むのは submission / experiments / runs / analyses（と、それらを source にする relations）だけ。**
DRA の record には SRA の STUDY / SAMPLE から来た projects / samples が同居し得るが、登録は
DB ごとに行う（BioProject / BioSample の reader と同じ方針）。同居していれば読まなかったことを
level=info の結果としてレポートに出し、そちら側のスキーマ違反は warning に落とす。
"""
import json
import re
import sys
import unicodedata
from pathlib import Path

from apps.dra.model import (
    DraAnalysis, DraExperiment, DraFile, DraRun, DraSubmission, DraSubmissionMeta,
)
from common.record_keys import carries

_SCHEMA_ERR_CAP = 20
_warned_no_schema = False

# DRA が読まない側。同居していても検証せず、スキーマ違反も validity へ算入しない。
_OUT_OF_SCOPE_KEYS = ('projects', 'samples')

# DRA として読む部分: XML の Submission / Experiment / Run / Analysis 文書に当たるもの。
_OWN_KEYS = ('submission', 'experiments', 'runs', 'analyses')

# relation の source.type（record の種類の名前） -> DraSubmission の list。
_KINDS = {
    'experiment': 'experiments',
    'run':        'runs',
    'analysis':   'analyses',
}

# v3 の library.layout は要素名を小文字にした値（sra.yml）。model は XML の要素名で持つ。
_LAYOUTS = {'single': 'SINGLE', 'paired': 'PAIRED'}


def _format_error(message, field=None, detail=None, rule_id='DRA_R0002', sample=None, level='error',
                  target='#file_format'):
    """入力形式そのものの不備を 1 件組む。

    どこがなぜ悪いかを message に畳み込む。DRA のレポートは `{rule_id}:{OBJECT}:{sample}:{message}`
    の 1 行で、注釈列の channel が無い（BioProject の reader と同じ事情）。
    """
    where = ': '.join(x for x in (field, detail) if x)
    return {
        'rule_id': rule_id, 'level': level, 'target': target, 'sample': sample,
        'message': f'{message} ({where})' if where else message,
    }


def _schema_error(field, detail, sample=None):
    return _format_error('Record is invalid against the DDBJ Record v3 schema.',
                         field=field, detail=detail, sample=sample)


# --- 形の確認 ---------------------------------------------------------------

class _Shape:
    """reader が前提にしている形だけを確かめる。

    スキーマ検証（`ddbj_record`）は任意インストールなので、これが無いと型の違う record で
    reader が AttributeError で落ちる。落ち方が終了コード 1 ＝「検証は終わった」と同じ顔をする。
    """

    def __init__(self):
        self.errors = []

    def bad(self, at, expected, value):
        self.errors.append(_schema_error(at, f'Expected {expected}, got {type(value).__name__}'))

    def obj(self, value, at):
        """None か dict なら True（読み進めてよい）。"""
        if value is not None and not isinstance(value, dict):
            self.bad(at, 'an object', value)
            return False
        return value is not None

    def objects(self, value, at):
        """list[dict] のうち読み進めてよい (位置, dict) を返す。"""
        if value is None:
            return []
        if not isinstance(value, list):
            self.bad(at, 'a list', value)
            return []
        return [(i, item) for i, item in enumerate(value) if self.obj(item, f'{at}.{i}')]

    def strings(self, obj, at, keys):
        for key in keys:
            value = obj.get(key)
            if value is not None and not isinstance(value, str):
                self.bad(f'{at}.{key}', 'a string', value)

    def integer(self, obj, at, key):
        value = obj.get(key)
        if value is not None and _lax_int(value) is None:
            self.bad(f'{at}.{key}', 'an integer', value)


def _lax_int(value):
    """スキーマ（pydantic の lax モード）が int として受ける値を int に。受けないものは None。

    形の確認をスキーマより厳しくすると、スキーマが通す record でルールが 1 つも動かなくなる。
    """
    if isinstance(value, int):   # bool も（pydantic が受ける）
        return int(value)
    if isinstance(value, float):
        return int(value) if value.is_integer() else None
    if isinstance(value, str) and re.fullmatch(r'\s*[+-]?\d+\s*', value):
        return int(value)
    return None


def _shape_errors(record):
    s = _Shape()

    submission = record.get('submission')
    if s.obj(submission, 'submission'):
        s.strings(submission, 'submission', ('accession', 'alias', 'center_name', 'hold_date'))
        sra = submission.get('sra')
        if s.obj(sra, 'submission.sra'):
            s.strings(sra, 'submission.sra', ('lab_name', 'submission_date'))
            for i, contact in s.objects(sra.get('contacts'), 'submission.sra.contacts'):
                s.strings(contact, f'submission.sra.contacts.{i}',
                          ('name', 'inform_on_status', 'inform_on_error'))

    for i, experiment in s.objects(record.get('experiments'), 'experiments'):
        at = f'experiments.{i}'
        s.strings(experiment, at, ('accession', 'alias', 'center_name', 'title', 'description'))
        library = experiment.get('library')
        if s.obj(library, f'{at}.library'):
            s.strings(library, f'{at}.library', ('name', 'strategy', 'source', 'selection', 'layout'))
            s.integer(library, f'{at}.library', 'nominal_length')
        platform = experiment.get('platform')
        if s.obj(platform, f'{at}.platform'):
            s.strings(platform, f'{at}.platform', ('type', 'instrument_model'))
        s.obj(experiment.get('legacy'), f'{at}.legacy')

    for key in ('runs', 'analyses'):
        for i, obj in s.objects(record.get(key), key):
            at = f'{key}.{i}'
            s.strings(obj, at, ('accession', 'alias', 'center_name', 'title', 'description'))
            for j, block in s.objects(obj.get('data_blocks'), f'{at}.data_blocks'):
                for k, f in s.objects(block.get('files'), f'{at}.data_blocks.{j}.files'):
                    s.strings(f, f'{at}.data_blocks.{j}.files.{k}',
                              ('filename', 'filetype', 'checksum_method', 'checksum'))

    for i, relation in s.objects(record.get('relations'), 'relations'):
        at = f'relations.{i}'
        s.strings(relation, at, ('type',))
        source = relation.get('source')
        if s.obj(source, f'{at}.source'):
            s.strings(source, f'{at}.source', ('type', 'accession', 'alias'))
            s.integer(source, f'{at}.source', 'index')
        target = relation.get('target')
        if s.obj(target, f'{at}.target'):
            s.strings(target, f'{at}.target', ('db', 'accession', 'id'))

    return s.errors[:_SCHEMA_ERR_CAP]


# --- スキーマ検証 ------------------------------------------------------------

def _schema_validate(record):
    """DRA_R0002: v3 スキーマ検証。`ddbj_record` が無ければ形状チェックだけに落とす。"""
    global _warned_no_schema
    try:
        from ddbj_record.schema.v3 import DdbjRecord
        from pydantic import ValidationError
    except ImportError:
        if not _warned_no_schema:
            print("[WARN] ddbj-record が入っていないため v3 スキーマ検証 (DRA_R0002) は "
                  "reader が前提とする形の確認のみになります (pip install '.[record]')",
                  file=sys.stderr)
            _warned_no_schema = True
        return []
    try:
        DdbjRecord.model_validate(record)
    except ValidationError as e:
        return _scoped_schema_errors(e.errors(), record)
    return []


def _out_of_scope(loc, record):
    """スキーマ違反の場所が DRA の読まない側か。projects / samples と、それらを source に
    する relation（SRA の STUDY_LINKS などから来る）。"""
    if not loc:
        return False
    if loc[0] in _OUT_OF_SCOPE_KEYS:
        return True
    if loc[0] == 'relations' and len(loc) > 1 and isinstance(loc[1], int):
        relations = record.get('relations')
        relation  = relations[loc[1]] if isinstance(relations, list) and loc[1] < len(relations) else None
        source    = relation.get('source') if isinstance(relation, dict) else None
        kind      = source.get('type') if isinstance(source, dict) else None
        return isinstance(kind, str) and f'{kind}s' in _OUT_OF_SCOPE_KEYS
    return False


def _scoped_schema_errors(errors, record):
    """スキーマ違反を「DRA が読む側」と「そうでない側」に分ける。

    v3 モデルは `extra='forbid'` なので、同居する projects / samples 側の独自キー 1 つで
    document 全体が invalid になる。それを error にすると、DRA の curator には直しようの
    無い瑕疵で validity が false になる。担当外は warning に落とす（黙らせはしない）。
    上限は別々にかける（BioProject の reader と同じ理由）。
    """
    mine, theirs = [], []
    for err in errors:
        dest = theirs if _out_of_scope(err['loc'], record) else mine
        dest.append(('.'.join(str(x) for x in err['loc']), err['msg']))

    out = [_schema_error(field, detail) for field, detail in mine[:_SCHEMA_ERR_CAP]]
    if len(mine) > _SCHEMA_ERR_CAP:
        out.append(_schema_error(None, f'{len(mine) - _SCHEMA_ERR_CAP} further violation(s) not listed'))
    if theirs:
        shown = '; '.join(f'{field}: {detail}' for field, detail in theirs[:3])
        more  = f' (+{len(theirs) - 3} more)' if len(theirs) > 3 else ''
        out.append(_format_error(
            'The DDBJ Record is invalid against the v3 schema outside the DRA scope '
            f'({" / ".join(_OUT_OF_SCOPE_KEYS)}). It is not validated here.',
            detail=f'{shown}{more}', level='warning', target='#out_of_scope'))
    return out


# --- モデルを組む ------------------------------------------------------------

def _text(value):
    """xml_reader の `_text` と同じ形に揃える（strip、空は None）。要素の本文に当たる値に使う。"""
    if not isinstance(value, str):
        return None
    return value.strip() or None


def _attr(value):
    """XML の属性に当たる値。xml_reader は属性を strip しないので、ここでもしない。"""
    return value if isinstance(value, str) else None


def _files(obj):
    return [DraFile(filename=_attr(f.get('filename')), filetype=_attr(f.get('filetype')),
                    checksum_method=_attr(f.get('checksum_method')), checksum=_attr(f.get('checksum')))
            for block in obj.get('data_blocks') or [] for f in block.get('files') or []]


def _build_submission(submission):
    sra = submission.get('sra') or {}
    return DraSubmissionMeta(
        alias=_attr(submission.get('alias')),
        accession=_attr(submission.get('accession')),
        center_name=_attr(submission.get('center_name')),
        lab_name=_attr(sra.get('lab_name')),
        submission_date=_attr(sra.get('submission_date')),
        hold_date=_attr(submission.get('hold_date')),
        contacts=[{'name': _attr(c.get('name')),
                   'inform_on_status': _attr(c.get('inform_on_status')),
                   'inform_on_error': _attr(c.get('inform_on_error'))}
                  for c in sra.get('contacts') or []],
        raw=submission,
    )


def _build_experiment(experiment, at, errors):
    library  = experiment.get('library') or {}
    platform = experiment.get('platform') or {}

    e = DraExperiment(alias=_attr(experiment.get('alias')), accession=_attr(experiment.get('accession')),
                      center_name=_attr(experiment.get('center_name')),
                      title=_text(experiment.get('title')), raw=experiment)
    e.description       = _text(experiment.get('description'))
    e.library_name      = _text(library.get('name'))
    e.library_strategy  = _text(library.get('strategy'))
    e.library_source    = _text(library.get('source'))
    e.library_selection = _text(library.get('selection'))

    layout = _text(library.get('layout'))
    if layout is not None:
        e.library_layout = _LAYOUTS.get(layout)
        if e.library_layout is None:
            # XSD が縛っていた値。v3 のスキーマは str なので、ここで見ないと DRA_R0019 / R0027 が
            # 黙って外れる（'PAIRED' と比べている）。
            errors.append(_schema_error(f'{at}.library.layout',
                                        f"Expected one of {', '.join(repr(v) for v in _LAYOUTS)}, "
                                        f'got {layout!r}', sample=e.label))
    length = library.get('nominal_length')
    if e.library_layout == 'PAIRED' and length is not None:
        e.nominal_length = str(_lax_int(length))

    e.platform         = _text(platform.get('type'))
    e.instrument_model = _text(platform.get('instrument_model'))

    # LIBRARY_DESCRIPTOR/TARGETED_LOCI は library の外（experiments[].targeted_loci）に載る。
    e.library_descriptor_present = bool(experiment.get('library') or experiment.get('targeted_loci'))
    e.platform_present           = bool(experiment.get('platform'))
    # DESIGN は v3 に無い入れ物。その下にあったものが 1 つでもあれば「ある」。
    # sample への relation は _apply_relations が足す。
    e.design_present = e.library_descriptor_present \
        or any(experiment.get(key) for key in ('description', 'spot_descriptor', 'pool')) \
        or bool((experiment.get('legacy') or {}).get('gaps'))
    return e


def _build_run(run):
    r = DraRun(alias=_attr(run.get('alias')), accession=_attr(run.get('accession')),
               center_name=_attr(run.get('center_name')), title=_text(run.get('title')), raw=run)
    r.data_block_present = bool(run.get('data_blocks'))
    r.files = _files(run)
    return r


def _build_analysis(analysis):
    a = DraAnalysis(alias=_attr(analysis.get('alias')), accession=_attr(analysis.get('accession')),
                    center_name=_attr(analysis.get('center_name')), title=_text(analysis.get('title')),
                    description=_text(analysis.get('description')), raw=analysis)
    a.data_block_present = bool(analysis.get('data_blocks'))
    a.files = _files(analysis)
    return a


# --- relations ---------------------------------------------------------------

# 正準形（ddbj-canon）の single-line の文字列が 1 つの空白に畳む文字: Unicode の White_Space と
# U+200B / U+200C / U+200D / U+FEFF（ddbj-repository の doc/canonical-json.md §2.2）。
# Python の \s は White_Space と一致しない（U+001C〜U+001F を含み、U+200B などを含まない）。
_WHITESPACE = re.compile('[\t\n\v\f\r \x85\xa0\u1680\u2000-\u200d\u2028\u2029\u202f\u205f\u3000\ufeff]+')


def _alias_key(alias):
    """alias の比べ方（ddbj/ddbj-record-specifications#18）。record が書かれるときの正準形に揃えて
    比べる: NFC にし、空白の並びを 1 つにし、前後を除く。alias の無いものは空の alias と同じに
    数える（正準形では空の文字列は落ちるので区別できない）。converter（ddbj-repository の
    DRA::Converter）も同じ正準形で数えて index を書く。"""
    text = unicodedata.normalize('NFC', alias) if isinstance(alias, str) else ''
    return _WHITESPACE.sub(' ', text).strip(' ')


class _Sources:
    """relation の source（種類 + accession か alias[+index]）を object へ解決する。"""

    def __init__(self, submission):
        self._by_kind = {kind: getattr(submission, attr) for kind, attr in _KINDS.items()}

    def resolve(self, source):
        """(object, 解決できなかった理由)。DRA の種類でなければ (None, None)。"""
        kind = source.get('type')
        objects = self._by_kind.get(kind)
        if objects is None:
            return None, None

        accession = source.get('accession')
        if accession:
            found = [o for o in objects if o.accession and o.accession.strip() == accession.strip()]
            return (found[0], None) if found else (None, f'no {kind} has accession {accession!r}')

        key       = _alias_key(source.get('alias'))
        namesakes = [o for o in objects if _alias_key(o.alias) == key]
        index     = _lax_int(source['index']) if source.get('index') is not None else None
        shown     = f'alias {source.get("alias")!r}' if key else 'no alias'
        if index is not None:
            if 0 <= index < len(namesakes):
                return namesakes[index], None
            return None, f'there are {len(namesakes)} {kind}(s) with {shown}, so index {index} names none'
        if len(namesakes) == 1:
            return namesakes[0], None
        if not namesakes:
            return None, f'no {kind} has {shown}'
        return None, f'{len(namesakes)} {kind}s have {shown}; an index is needed to tell them apart'


# (source の種類, relation の type, target.db) -> 読み方。
# single: XML では 1 つしか書けない参照（2 つ目は DRA_R0002）。
_REFERENCES = {
    ('experiment', 'part_of', 'project'):    ('study_ref',  'STUDY_REF'),
    ('experiment', 'part_of', 'sample'):     ('sample_ref', 'SAMPLE_DESCRIPTOR'),
    ('run',        'part_of', 'experiment'): ('experiment_ref', 'EXPERIMENT_REF'),
    ('analysis',   'part_of', 'project'):    ('study_ref',  'STUDY_REF'),
}
_TARGETS = {
    ('analysis', 'derived_from', 'sample'): 'sample_refs',
    ('analysis', 'derived_from', 'run'):    'run_refs',
}


def _apply_relations(record, submission, errors):
    """ルートの relations から、DRA の object が source のものを読んで *_ref に置く。"""
    sources = _Sources(submission)
    seen    = {}   # (id(object), 参照の名前) -> 何件目か

    for i, relation in enumerate(record.get('relations') or []):
        at     = f'relations.{i}'
        source = relation.get('source')
        if not source:
            # source を省くと record 全体が起点（v3 の Relation）。どの object の参照でもない。
            continue

        obj, why = sources.resolve(source)
        if why:
            errors.append(_schema_error(f'{at}.source', f'The relation names no object in this record: {why}'))
            continue
        if obj is None:
            continue

        target = relation.get('target') or {}
        key    = (source.get('type'), relation.get('type'), target.get('db'))

        if key in _REFERENCES:
            attr, element = _REFERENCES[key]
            n = seen[(id(obj), attr)] = seen.get((id(obj), attr), 0) + 1
            if n > 1:
                errors.append(_schema_error(
                    at, f'{obj.label} already has a {key[1]} relation to a {key[2]}; SRA allows one '
                        f'{element} per {key[0]}. Only the first one is read.', sample=obj.label))
                continue
            setattr(obj, attr, _attr(target.get('accession')))
            if attr == 'experiment_ref':
                obj.experiment_refname = _attr(target.get('id'))
            if attr == 'sample_ref':
                obj.design_present = True    # SAMPLE_DESCRIPTOR は DESIGN の下
        elif key in _TARGETS:
            # XML と同じく accession の無い TARGET は読まない（refname だけでは DB で引けない）。
            if _attr(target.get('accession')):
                getattr(obj, _TARGETS[key]).append(target['accession'])


# --- 入口 --------------------------------------------------------------------

def parse_record(record_path, account=None):
    """DDBJ Record ファイルを DraSubmission へ。戻り値: (submission, errors)。

    submission=None は「モデルを組めなかった」を意味する（JSON として読めない / 形が違う）。
    experiments / runs / analyses が 1 つも無い record もそのまま返す。「検証対象がゼロ」を
    「指摘ゼロ」と混同させないため、どう扱うかは呼び出し側（CLI）の責任にしてある。
    """
    try:
        text   = Path(record_path).read_text(encoding='utf-8')
        record = json.loads(text)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, RecursionError) as e:
        return None, [_format_error('JSON document is not well-formed.', detail=str(e), rule_id='DRA_R0001')]
    if not isinstance(record, dict):
        return None, [_format_error('JSON document is not a DDBJ Record object.', rule_id='DRA_R0001')]

    shape_errors = _shape_errors(record)
    if shape_errors:
        return None, shape_errors

    errors = _schema_validate(record)
    sub    = DraSubmission(account=account)

    if record.get('submission'):
        sub.submission = _build_submission(record['submission'])
    sub.experiments = [_build_experiment(e, f'experiments.{i}', errors)
                       for i, e in enumerate(record.get('experiments') or [])]
    sub.runs        = [_build_run(r) for r in record.get('runs') or []]
    sub.analyses    = [_build_analysis(a) for a in record.get('analyses') or []]
    _apply_relations(record, sub, errors)

    name = Path(record_path).name
    for role, present in (('submission', sub.submission is not None), ('experiment', sub.experiments),
                          ('run', sub.runs), ('analysis', sub.analyses)):
        if present:
            sub.role_files[role] = [name]

    if sub.submission is None and (sub.experiments or sub.runs or sub.analyses):
        errors.append(_format_error('A DDBJ Record carrying experiments, runs or analyses must also '
                                    'carry the submission.', rule_id='DRA_R0032'))

    carried = [key for key in _OUT_OF_SCOPE_KEYS if carries(record, key)]
    if carried:
        # 読まなかったことを**レポートに**出す（stderr は validation.log にしか残らず、取る API が無い）。
        # level=info は validity にも error/warning 数にも影響しない。
        errors.append(_format_error(
            f'This DDBJ Record also carries {" and ".join(carried)}. They are not validated here — '
            'send the same record to the BioProject / BioSample validator for them. References to '
            'them (relations to a project or sample) are checked by accession against the '
            'registered databases, not against this document.',
            level='info', target='#not_validated'))
        print(f'[INFO] この record は {" / ".join(carried)} を持っていますが、DRA の検証対象ではないので読みません。',
              file=sys.stderr)

    # DRA_R0050 が非 ASCII を探す範囲: DRA として読む部分の全体を、XML の 4 つの文書に当たる
    # 1 つとして。ソースに素の文字として書かれた非 ASCII だけを見るのは XML と同じで、JSON の
    # `\u201c` は XML の `&#x201c;` に当たる。
    sub.xml_docs = [{
        'file':    name,
        'root':    {key: record[key] for key in _OWN_KEYS if key in record},
        'literal': {ch for ch in text if ord(ch) > 0x7F},
    }]

    return sub, errors
