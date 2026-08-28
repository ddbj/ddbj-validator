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
                                            （title -> reference、pubmed_id / doi は両方）
    project.target.sample_scope          -> sample_scope
    project.target.material              -> material
    project.target.capture               -> capture
    project.target.method                -> method_type
    project.target.method_description    -> method_text
    project.target.description           -> target_description
    project.target.data_types            -> data_types
    project.target.data_types
      ＋ .data_type_descriptions          -> data_entries [{type, text}]

**読むのは `project` だけ。** DDBJ Record は 1 ドキュメントに project と samples を
同居させられるが、登録は DB ごとに行い、BioProject として登録するときに読まれるのは
project だけ（2026-08-28 の方針決定）。同居していても samples は読まず、読まなかった
ことを **level=info の結果としてレポートに出す**（stderr は validation.log にしか残らず、
取得する API が無い）。

スキーマ検証はドキュメント全体にかけるが、**担当外の違反は warning に落とす**
（`_scoped_schema_errors`）。v3 モデルは `extra='forbid'` なので samples 側の独自キー
1 つで document 全体が invalid になり、それを error にすると BioProject の curator が
直せない瑕疵で BioProject の validity が false になる。なお `ddbj_record` が入っていない
環境ではスキーマ検証そのものが動かず、`_shape_errors` は project しか見ないので、
**壊れた samples は何も報告されない**。

**同一ドキュメント内の相互参照は解決されない。** `BP_R0021` は locus_tag prefix と
BioSample の組を **BioSample DB に問い合わせて**確かめ、`BP_R0022` は accession の
形を見る。同居する samples を `locus_tag_prefix[].biosample_id` から指しても、
accession は登録後にしか存在しないので通らない（`Invalid BioSample accession` になる）。
これは仕様どおりで、黙って通るより良い。同居 record を断っていたときの理由がこれで、
断るのをやめたのは **accession が無い相手を指す書き方がそもそも無い**（参照先は必ず
登録済み）ため。上の info 結果でその旨を呼び出し側に伝えている。

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
        黙って通すと「検証して問題なし」に見えるので、**「評価できなかった」を
        level=info の結果としてレポートに出す**（validity にも error 数にも影響しない）。
        断らないのは、断ると同じ umbrella の BP_R0008 / BP_R0042 まで検証できなくなるため。
"""
import json
import sys
from pathlib import Path

from apps.bioproject.model import BioProjectRecord, BioProjectSubmission, Publication

_SCHEMA_ERR_CAP = 20
_warned_no_schema = False

# BioProject が読まない側。同居していても検証対象にせず、スキーマ違反も validity へ
# 算入しない（_scoped_schema_errors）。
_OUT_OF_SCOPE_KEY = 'samples'


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

    **どこがなぜ悪いかを message に畳み込む。** BioProject のレポートには注釈列の
    channel が無く、JSON も text も id / level / message / target / object / external
    しか運ばない（`common.reporter`）。BioSample の reader と同じつもりで anno_cols に
    置くと、フィールドのパスはどこにも出ずに消える。43,021 件の record に対して
    「スキーマ違反です」だけ返ってもどこを直せば良いか分からない。
    括弧で補足を足すのは BP_R0005 の `(Found: 19)` と同じだが、あちらは固定ラベル、
    こちらはフィールドのパスなので中身の形までは揃わない。
    """
    where = ': '.join(x for x in (field, detail) if x)
    return {
        'rule_id': rule_id, 'level': 'error', 'target': '#file_format',
        'sample': None,
        'message': f'{message} ({where})' if where else message,
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
    if organism is not None:
        if not isinstance(organism, dict):
            bad('project.organism', 'an object', organism)
        else:
            if organism.get('name') is not None and not isinstance(organism['name'], str):
                bad('project.organism.name', 'a string', organism['name'])
            tax_id = organism.get('taxonomy_id')
            # str() は何でも受けるので、ここで見ないと "{'oops': 1}" が
            # taxonomy_id として通り、BP_R0038 が「学名と id が不一致」という
            # 誤った診断を出す。
            if tax_id is not None and not isinstance(tax_id, (int, str)):
                bad('project.organism.taxonomy_id', 'an integer', tax_id)

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
            if data_types is not None:
                if not isinstance(data_types, list):
                    bad('project.target.data_types', 'a list', data_types)
                else:
                    # 要素まで見る。dict が来ると _data_entries が descriptions の
                    # キーに使って TypeError で落ちる（unhashable）。落ちると
                    # レポートが出ず、終了コードは「指摘あり」と同じ 1 になる。
                    for i, data_type in enumerate(data_types):
                        if not isinstance(data_type, str):
                            bad(f'project.target.data_types.{i}', 'a string', data_type)
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
        return _scoped_schema_errors(e.errors())
    return []


def _scoped_schema_errors(errors):
    """スキーマ違反を「BioProject が読む側」と「そうでない側」に分ける。

    v3 モデルは `extra='forbid'` なので、**samples 側に producer 独自のキーが 1 つ
    あるだけで document 全体が invalid になる**。それを BP_R0002 の error として出すと、
    BioProject としては何の問題も無い record が、BioProject の curator には直しようの
    無い BioSample 側の瑕疵で `validity: false` になる。登録を DB ごとに行うという
    前提と食い違うので、**担当外は warning に落として validity を動かさない**。
    黙らせはしない — 読まないことと、壊れていて良いことは別。

    上限も別々にかける。pydantic はモデルのフィールド順に返し `project` は `samples`
    より先なので、まとめて 20 件で切ると project 側の瑕疵 20 件で samples 側の違反が
    1 件も出ない、が起きる（逆向きは BioSample 側で同じことになる）。
    切ったときは切ったと言う。
    """
    mine, theirs = [], []
    for err in errors:
        dest = theirs if tuple(err['loc'][:1]) == (_OUT_OF_SCOPE_KEY,) else mine
        dest.append(('.'.join(str(x) for x in err['loc']), err['msg']))

    out = [_schema_error(field, detail) for field, detail in mine[:_SCHEMA_ERR_CAP]]
    if len(mine) > _SCHEMA_ERR_CAP:
        out.append(_format_error(
            'BP_R0002', 'Record is invalid against the DDBJ Record v3 schema.',
            detail=f'{len(mine) - _SCHEMA_ERR_CAP} further violation(s) not listed'))
    if theirs:
        shown = '; '.join(f'{field}: {detail}' for field, detail in theirs[:3])
        more  = f' (+{len(theirs) - 3} more)' if len(theirs) > 3 else ''
        out.append({
            'rule_id': 'BP_R0002', 'level': 'warning', 'target': '#out_of_scope',
            'sample': None,
            'message': 'The DDBJ Record is invalid against the v3 schema outside the '
                       f'BioProject scope, under \'{_OUT_OF_SCOPE_KEY}\'. '
                       f'It is not validated here. ({shown}{more})',
        })
    return out


def _text(value):
    """値を xml_reader の `_text` と同じ形に揃える（strip、空は None）。"""
    if not isinstance(value, str):
        return None
    return value.strip() or None


def _publications(project):
    """v3 publications[] -> [Publication(id, db_type, reference)]。

    v3 は pubmed_id / doi を別のキーに持ち、XML は id ＋ DbType の組で持つ。
    XML の <Reference>（自由記述）は v3 に専用 slot が無く、converter が `title` に
    載せている（載せないと BP_R0015 が誤検知になり、Publication[i].Reference を対象に
    する非 ASCII 検査 BP_R0059/R0060 が record 入力で死ぬ）。
    """
    out = []
    for pub in project.get('publications') or []:
        reference = _text(pub.get('title'))
        # pubmed_id と doi が両方あれば両方を検証対象にする。片方で break すると
        # もう片方が BP_R0014（識別子の形式）をすり抜ける。
        found = [(_text(pub.get(key)), db_type)
                 for key, db_type in _PUBLICATION_DB_TYPE.items() if _text(pub.get(key))]

        if not found:
            out.append(Publication(id=None, db_type=None, reference=reference))
        else:
            out.extend(Publication(id=identifier, db_type=db_type, reference=reference)
                       for identifier, db_type in found)
    return out


def _data_entries(target):
    """data_types と data_type_descriptions を XML の <Data data_type=..>本文</Data> の形へ。

    説明の引き当ては正規化後のキーで行う。生の値で引くと " eOther " と "eOther" が
    別物になり、説明があるのに BP_R0013 が発火する。
    """
    descriptions = {_text(k): v for k, v in (target.get('data_type_descriptions') or {}).items()}

    return [{'type': data_type, 'text': _text(descriptions.get(data_type))}
            for data_type in (_text(t) for t in target.get('data_types') or [])]


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
        # XML の `<Relevance/>`（空）は「要素あり」なので、空 dict も present 扱いにする。
        rec.relevance_present = True
        # キーの大小は producer 次第（我々の converter は要素名を downcase する）。
        other = next((v for k, v in relevance.items() if k.lower() == 'other'), None)
        rec.relevance_other_selected = any(k.lower() == 'other' for k in relevance)
        rec.relevance_other          = _text(other)

    rec.publications = _publications(project)

    # xml_reader は Target/Method/Objectives を ProjectTypeSubmission の下でだけ読む。
    # umbrella に target が付いた record で BP_R0009 等が出ないよう、同じ条件にする。
    target = (project.get('target') or {}) if rec.project_kind == 'submission' else {}
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

    samples = record.get(_OUT_OF_SCOPE_KEY)
    if samples:
        # 読まなかったことを**レポートに**出す。stderr は validation.log にしか残らず、
        # それを取れる API が無い（`get_file` の filetype は `^[a-z][a-z_]*$`）ので、
        # web 経由の呼び出し側から見ると「指摘ゼロの綺麗なレポート」と区別が付かない。
        # BP_R0016 の info と同じ扱い（level=info は validity にも error/warning 数にも
        # 影響しない。common/reporter.py）。
        count = len(samples) if isinstance(samples, list) else None
        shown = f'{count} sample(s)' if count is not None else 'samples'
        errors.append({
            'rule_id': 'BP_R0002', 'level': 'info', 'target': '#not_validated',
            'sample': None,
            'message': f'This DDBJ Record also carries {shown}. They are not '
                       'validated here — send the same record to the BioSample validator '
                       'as well. References from the project into them (locus_tag_prefix'
                       '.biosample_id) are resolved against the registered BioSample '
                       'database, not against this document, so a reference to a sample '
                       'that has no accession yet is reported as invalid (BP_R0021 / '
                       'BP_R0022).',
        })
        print(f'[INFO] この record は samples を{f" {count} 件" if count is not None else ""}'
              '持っていますが、BioProject の検証対象ではないので読みません。', file=sys.stderr)

    if records and records[0].project_kind == 'umbrella':
        # 「評価できなかった」をレポートに出す。level=info は validity にも
        # error/warning 数にも影響せず messages に載る（common/reporter.py）ので、
        # 先方のレポート形式を変えずに「検証していない」を可視化できる。
        # stderr だけだと validation.log にしか残らず、取得する API が無い。
        errors.append({
            'rule_id': 'BP_R0016', 'level': 'info', 'target': '#not_evaluated',
            'sample': records[0].label,
            'message': 'Umbrella membership is not expressed in DDBJ Record v3, '
                       'so this rule could not be evaluated for this input.',
        })
        print('[WARN] umbrella project ですが、v3 には member を表す関係が未確定のため '
              'BP_R0016 (umbrella の妥当性) は評価できません。', file=sys.stderr)

    return BioProjectSubmission(records=records, account=account), errors
