"""DDBJ Record（v3 JSON）のパース。xml_reader と同じ契約でモデルを組む。

- BP_R0001: JSON well-formed（パース失敗で検出）。
- BP_R0002: 形状・スキーマ違反。`ddbj_record` があれば v3 スキーマで、無くても
  reader が前提にしている形だけは自前で確かめる（`_shape_errors`）。

v3 → BioProjectRecord の対応:

    project.accession                    -> accession
    project.title / description          -> title / description
    project.project_type                 -> project_kind（primary -> submission）
    project.umbrella_subtype             -> top_admin_subtype
    project.umbrella_subtype_description -> subtype_other_descr
    project.organism.name / taxonomy_id  -> organism_name / tax_id
    project.locus_tag_prefix[]           -> locus_tags [{prefix, biosample_id}]
    project.relevance                    -> relevance_present / _other_selected / _other
    project.publications[]               -> publications [{id, db_type, reference}]
    project.target.sample_scope          -> sample_scope
    project.target.material              -> material
    project.target.capture               -> capture
    project.target.method                -> method_type
    project.target.method_description    -> method_text
    project.target.description           -> target_description
    project.target.data_types            -> data_types
    project.target.data_types
      ＋ .data_type_descriptions          -> data_entries [{type, text}]

語彙は XML と同じ e- 接頭辞付き（`eOther` / `eMonoisolate`）。v3 の仕様書は接頭辞なしの
例を載せているが、実データ（D-way 由来の record 43,021 件）は XML の値をそのまま
持っており、ルール側も e- 付きで比較している。変換表は置かない — 置くと、仕様書どおりの
接頭辞なしを書いた producer だけが黙って別扱いになる。未知の値は BP_R0070（cv_terms）が拾う。

v3 に無いもの / 見ていないもの:

    archive / release_date -- ルールが参照していない。
    Publication の free-text reference -- v3 の Publication は構造化引用で、XML の
        <Reference> にあたる自由記述の slot が無い。実データ 147 件は全て pubmed_id か
        doi を持っていたので BP_R0015 は発火しないが、slot が無いことは変わらない。
    ProjectTypeTopSingleOrganism -- v3 の project_type は primary / umbrella だけなので
        表現できない。BP_R0040 は record 入力では発火し得ない。
    umbrella の member -- XML の ProjectLinks/.../MemberID にあたる関係を v3 の
        `relations` でどう書くかが未確定で、我々の converter も出していない。
        **BP_R0016（umbrella の妥当性）は record 入力では評価できない。**
        黙って通すと「検証して問題なし」に見えるので、umbrella のときは警告する。
"""
import json
import sys
from pathlib import Path

from apps.bioproject.model import BioProjectRecord, BioProjectSubmission, Publication

_SCHEMA_ERR_CAP = 20
_warned_no_schema = False

# v3 project_type -> モデルの project_kind。
# 'single_organism'（XML の ProjectTypeTopSingleOrganism）は v3 で表現できない。
_PROJECT_KIND = {
    'primary':  'submission',
    'umbrella': 'umbrella',
}

# v3 Publication のどのキーが XML の DbType に対応するか。
_PUBLICATION_DB_TYPE = {
    'pubmed_id': 'ePubmed',
    'doi':       'eDOI',
}


def _format_error(rule_id, message, field=None, detail=None):
    """入力形式そのものの不備（BP_R0001/R0002）を 1 件組む。

    どこがなぜ悪いかは message でなく anno_cols に置く。XML 入力では XSD の
    行番号が message に埋め込まれていて、そこから先へ運べていない。
    """
    return {
        'rule_id': rule_id, 'level': 'error', 'target': '#file_format',
        'sample': None, 'message': message, 'input_format': 'record',
        'anno_cols': [c for c in (
            {'key': 'Field', 'value': field} if field else None,
            {'key': 'Message', 'value': detail or message},
        ) if c],
    }


def _schema_error(field, detail):
    return _format_error('BP_R0002', 'Record is invalid against the DDBJ Record v3 schema.',
                         field=field, detail=detail)


def _shape_errors(record):
    """reader が前提にしている形だけを確かめる。

    スキーマ検証（`ddbj_record`）は任意インストールなので、これが無いと型の違う
    レコードで reader が AttributeError で落ちる。JSON では「読めるが型が違う」が
    あり、しかも落ち方が終了コード 1 ＝「検証は終わった」と同じ顔をする。
    """
    out = []

    def bad(field, expected, value):
        out.append(_schema_error(field, f'Expected {expected}, got {type(value).__name__}'))

    project = record.get('project')
    if project is None:
        return out
    if not isinstance(project, dict):
        bad('project', 'an object', project)
        return out

    for key in ('accession', 'title', 'description', 'project_type',
                'umbrella_subtype', 'umbrella_subtype_description'):
        value = project.get(key)
        if value is not None and not isinstance(value, str):
            bad(f'project.{key}', 'a string', value)

    organism = project.get('organism')
    if organism is not None and not isinstance(organism, dict):
        bad('project.organism', 'an object', organism)

    relevance = project.get('relevance')
    if relevance is not None and not isinstance(relevance, dict):
        bad('project.relevance', 'an object', relevance)

    prefixes = project.get('locus_tag_prefix')
    if prefixes is not None:
        if not isinstance(prefixes, list):
            bad('project.locus_tag_prefix', 'a list', prefixes)
        else:
            for i, prefix in enumerate(prefixes):
                if not isinstance(prefix, dict):
                    # v3 の途中まで list[str] だった。古い形は黙って通さない
                    # （通すと prefix だけの record が BP_R0021/R0022 を素通りする）。
                    bad(f'project.locus_tag_prefix.{i}', 'an object with prefix / biosample_id', prefix)

    publications = project.get('publications')
    if publications is not None:
        if not isinstance(publications, list):
            bad('project.publications', 'a list', publications)
        else:
            for i, pub in enumerate(publications):
                if not isinstance(pub, dict):
                    bad(f'project.publications.{i}', 'an object', pub)

    target = project.get('target')
    if target is not None:
        if not isinstance(target, dict):
            bad('project.target', 'an object', target)
        else:
            for key in ('sample_scope', 'material', 'capture', 'method',
                        'method_description', 'description'):
                value = target.get(key)
                if value is not None and not isinstance(value, str):
                    bad(f'project.target.{key}', 'a string', value)
            data_types = target.get('data_types')
            if data_types is not None and not isinstance(data_types, list):
                bad('project.target.data_types', 'a list', data_types)
            descriptions = target.get('data_type_descriptions')
            if descriptions is not None and not isinstance(descriptions, dict):
                bad('project.target.data_type_descriptions', 'an object', descriptions)

    return out[:_SCHEMA_ERR_CAP]


def _schema_validate(record):
    """BP_R0002: v3 スキーマ検証。`ddbj_record` が無ければ形状チェックだけに落とす。

    lxml が無いとき XSD 検証をスキップする xml_reader と同じ方針だが、スキップしたことは言う。
    """
    global _warned_no_schema
    try:
        from ddbj_record.schema.v3 import DdbjRecord
        from pydantic import ValidationError
    except ImportError:
        if not _warned_no_schema:
            print("[WARN] ddbj-record が入っていないため v3 スキーマ検証 (BP_R0002) は "
                  "reader が前提とする形の確認のみになります (pip install '.[record]')",
                  file=sys.stderr)
            _warned_no_schema = True
        return []
    try:
        DdbjRecord.model_validate(record)
    except ValidationError as e:
        return [_schema_error('.'.join(str(x) for x in err['loc']), err['msg'])
                for err in e.errors()[:_SCHEMA_ERR_CAP]]
    return []


def _text(value):
    """値を xml_reader の `_text` と同じ形に揃える（strip、空は None）。"""
    if not isinstance(value, str):
        return None
    return value.strip() or None


def _publications(project):
    """v3 publications[] -> [Publication(id, db_type, reference)]。

    v3 は pubmed_id / doi を別のキーに持ち、XML は id ＋ DbType の組で持つ。
    reference（自由記述）にあたる slot は v3 に無い。
    """
    out = []
    for pub in project.get('publications') or []:
        identifier = db_type = None
        for key, xml_db_type in _PUBLICATION_DB_TYPE.items():
            value = _text(pub.get(key))
            if value:
                identifier, db_type = value, xml_db_type
                break
        out.append(Publication(id=identifier, db_type=db_type, reference=None))
    return out


def _data_entries(target):
    """data_types と data_type_descriptions を XML の <Data data_type=..>本文</Data> の形へ。"""
    descriptions = target.get('data_type_descriptions') or {}

    return [{'type': _text(data_type), 'text': _text(descriptions.get(data_type))}
            for data_type in target.get('data_types') or []]


def _build_record(project):
    rec = BioProjectRecord(raw=project)

    rec.accession   = _text(project.get('accession'))
    rec.title       = _text(project.get('title'))
    rec.description = _text(project.get('description'))

    project_type    = _text(project.get('project_type'))
    rec.project_kind = _PROJECT_KIND.get(project_type, 'other' if project_type else None)

    rec.top_admin_subtype   = _text(project.get('umbrella_subtype'))
    rec.subtype_other_descr = _text(project.get('umbrella_subtype_description'))

    organism = project.get('organism') or {}
    rec.organism_name = _text(organism.get('name'))
    tax_id = organism.get('taxonomy_id')
    # ルールは str を前提にしている（値を strip するので int だと AttributeError）。
    rec.tax_id = str(tax_id).strip() if tax_id is not None else None

    rec.locus_tags = [
        {'prefix': _text(prefix.get('prefix')), 'biosample_id': _text(prefix.get('biosample_id'))}
        for prefix in project.get('locus_tag_prefix') or []
    ]

    # Relevance は v3 のほうが素直。XML では「要素があるか」を見るしかなかったが、
    # v3 では dict のキーが選択、値が説明。
    relevance = project.get('relevance')
    if isinstance(relevance, dict):
        rec.relevance_present       = bool(relevance)
        rec.relevance_other_selected = 'other' in relevance
        rec.relevance_other          = _text(relevance.get('other'))

    rec.publications = _publications(project)

    target = project.get('target') or {}
    rec.sample_scope       = _text(target.get('sample_scope'))
    rec.material           = _text(target.get('material'))
    rec.capture            = _text(target.get('capture'))
    rec.method_type        = _text(target.get('method'))
    rec.method_text        = _text(target.get('method_description'))
    rec.target_description = _text(target.get('description'))
    rec.data_types         = [_text(t) for t in target.get('data_types') or [] if _text(t)]
    rec.data_entries       = _data_entries(target)

    return rec


def parse_record(record_path, account=None):
    """DDBJ Record ファイルを BioProjectSubmission へ。戻り値: (submission, errors)。

    submission=None は「モデルを組めなかった」を意味する。JSON として読めなかった場合と、
    形が違う場合の両方。**形が違うレコードでモデルを組もうとしない**のが XML との違いで、
    XML なら中身は全て文字列なので不正でもモデルは組めるが、JSON のスキーマ違反は
    そのまま型違反であり、読み進めれば落ちる。

    `project` を持たないレコードは records=[] の submission を返す。「検証対象がゼロ」を
    「指摘ゼロ」と混同させないため、どう扱うかは呼び出し側の責任にしてある。
    """
    try:
        record = json.loads(Path(record_path).read_text(encoding='utf-8'))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, RecursionError) as e:
        return None, [_format_error('BP_R0001', 'JSON document is not well-formed.', detail=str(e))]
    if not isinstance(record, dict):
        return None, [_format_error('BP_R0001', 'JSON document is not a DDBJ Record object.')]

    shape_errors = _shape_errors(record)
    if shape_errors:
        return None, shape_errors

    errors  = _schema_validate(record)
    project = record.get('project')
    records = [_build_record(project)] if isinstance(project, dict) else []

    if records and records[0].project_kind == 'umbrella':
        # umbrella の member を v3 の relations でどう書くかが未確定で、我々の
        # converter も出していない。黙って通すと「検証して問題なし」に見える。
        print('[WARN] umbrella project ですが、v3 には member を表す関係が未確定のため '
              'BP_R0016 (umbrella の妥当性) は評価できません。', file=sys.stderr)

    return BioProjectSubmission(records=records, account=account), errors
