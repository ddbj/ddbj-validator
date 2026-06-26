import copy
import re
import logging
from pathlib import Path
from Bio.SeqRecord import SeqRecord
from Bio.Seq import Seq
from apps.ddbj.utils.features import get_features
from apps.ddbj.db_metadata import get_expected_transl_table
from apps.ddbj.autofix.proposal import build_proposal, update_qualifier_action

logger = logging.getLogger(__name__)

_SAMD_PATTERN = re.compile(r'(SAMD\d+)')

def _extract_samd_from_single_record(record):
    samd_list = []
    for feature in get_features(record, "DBLINK"):
        for vals in feature.qualifiers.values():
            for val in vals:
                match = _SAMD_PATTERN.search(val)
                if match: samd_list.append(match.group(1))
    return samd_list


# BioSample 同期提案は apps/ddbj/biosample/sync.py に集約（-b 機能の凝集）
from apps.ddbj.biosample.sync import (
    _propose_biosample_qualifier_sync,
    _propose_locus_tag_prefix_sync,
    _propose_bioproject_sync,
)


def propose_qualifiers_updates(records, bs_data, ann_path, unauthorized_bs=None, sync_attrs=None, emit_additions=False, mapping_keys=None):
    """BioSample 値と source qualifier を突合して修正提案を作る。

    sync_attrs を渡すと突合対象 qualifier をそれに置き換える（-b 時は biosample_sync.common を渡す。
    organism 等も対象になる）。未指定時は従来のハードコード集合（一般挙動は不変）。
    emit_additions=True で ann にしかない qualifier の属性追加候補も emit する。
    mapping_keys は biosample_sync.mapping の ddbj 側キー集合（-b 時）。locus_tag / DBLINK project の
    同期はこの集合に含まれる場合のみ実行する（設定駆動）。
    """
    mapping_keys = set(mapping_keys or [])
    proposals = []
    skipped_warnings = []
    validation_warnings = []

    unauth_set = unauthorized_bs or set()

    target_attrs = sync_attrs if sync_attrs else ["bio_material", "collection_date", "geo_loc_name", "culture_collection",
                    "host", "lat_lon", "sex", "specimen_voucher", "strain", "isolate", "ecotype",
                    "cultivar", "cell_line"]
    common_samds = []
    if "COMMON" in records:
        common_samds = _extract_samd_from_single_record(records["COMMON"])

    all_valid_samds = set()
    for entry_id, record in records.items():
        if entry_id == "COMMON": continue
        entry_samds = _extract_samd_from_single_record(record)
        active_samds = entry_samds if entry_samds else common_samds
        if not active_samds: continue

        valid_samds = [s for s in active_samds if s in bs_data]
        all_valid_samds.update(valid_samds)
        # 権限エラーで除外されたものは missing 扱いしない
        missing_samds = [s for s in active_samds if s not in bs_data and s not in unauth_set]

        if missing_samds:
            logger.warning(f"{entry_id}: BioSample data for {', '.join(missing_samds)} not found in DB.")
        if not valid_samds: continue

        # source qualifier 群を BioSample 値と突合
        p, w, s = _propose_biosample_qualifier_sync(record, entry_id, valid_samds, bs_data, ann_path, target_attrs, emit_additions=emit_additions)
        proposals.extend(p)
        validation_warnings.extend(w)
        skipped_warnings.extend(s)

        # locus_tag prefix を BioSample 値と突合。
        # 一般実行（emit_additions=False）は従来どおり。-b 時は mapping に locus_tag がある場合のみ（addition のみ）。
        if (not emit_additions) or ("locus_tag" in mapping_keys):
            p, w, s = _propose_locus_tag_prefix_sync(record, entry_id, valid_samds, bs_data, ann_path, emit_additions=emit_additions)
            proposals.extend(p)
            validation_warnings.extend(w)
            skipped_warnings.extend(s)

    # DBLINK project(PRJDB) → bioproject_id。-b 時かつ mapping に "DBLINK project" がある場合のみ。
    if sync_attrs and all_valid_samds and "DBLINK project" in mapping_keys:
        p, w, s = _propose_bioproject_sync(records, sorted(all_valid_samds), bs_data, ann_path, emit_additions=emit_additions)
        proposals.extend(p)
        validation_warnings.extend(w)
        skipped_warnings.extend(s)

    return proposals, validation_warnings, skipped_warnings


def propose_taxonomy_updates(records, tax_data, ann_path):
    proposals = []
    fixable_orgs = {org: data for org, data in tax_data.items() if data["status"] == "fixable"}
    if not fixable_orgs:
        return proposals

    for org, data in fixable_orgs.items():
        sci_name = data["scientific_name"]
        tax_id = data.get("tax_id", "unknown")
        match_type = data.get("type", "unknown")
        source_str = f"taxid: {tax_id}, {match_type}"

        positions = []
        updates = []
        used_in_records = False

        for entry_id, record in records.items():
            for feature in get_features(record, "source"):
                if "organism" in feature.qualifiers:
                    if org in feature.qualifiers["organism"]:
                        used_in_records = True
                        positions.append({"entry": entry_id, "feature_id": getattr(feature, 'line_number', id(feature))})

                        updates.append(update_qualifier_action(entry_id, feature.type, "organism", org, sci_name, feature_id=getattr(feature, 'line_number', id(feature))))

        if used_in_records:
            proposals.append(build_proposal(
                ann_path=ann_path, entry="ALL_ENTRIES", feature_type="source",
                qualifier="organism", target="organism", target_level="qualifier",
                positions=positions,
                old_value=org, new_value=sci_name, rule="ANN1025",
                updates=updates, source_db=source_str
            ))

    return proposals


def propose_transl_table_fixes(records, tax_data, ann_path):
    proposals = []
    common_rec = records.get("COMMON")
    common_sources = get_features(common_rec, "source") if common_rec else []

    for entry_id, record in records.items():
        if entry_id == "COMMON": continue

        eval_record = SeqRecord(Seq(""), id="dummy")
        record_sources = get_features(record, "source")
        eval_record.features_by_type = {"source": common_sources + record_sources}

        table_id = get_expected_transl_table(eval_record, tax_data)

        # 0 (不明/組み合わせ不適) の場合は Autofix を提案しない
        if table_id == 0:
            continue

        org_name = ""
        organelle = ""
        for feature in eval_record.features_by_type["source"]:
            org_name = feature.qualifiers.get("organism", [""])[0]
            organelle = feature.qualifiers.get("organelle", [""])[0]
            break

        sci_name = org_name
        tax_id = "unknown"
        if org_name in tax_data and tax_data[org_name].get("status") in ["valid", "fixable"]:
            sci_name = tax_data[org_name].get("scientific_name", org_name)
            tax_id = tax_data[org_name].get("tax_id", "unknown")

        source_parts = []
        if sci_name:
            source_parts.append(sci_name)
        if tax_id != "unknown":
            source_parts.append(f"taxid: {tax_id}")
        if organelle:
            source_parts.append(organelle)

        source_db_str = ", ".join(source_parts) if source_parts else "Taxonomy DB"

        for feature in get_features(record, "CDS"):
            if "transl_table" not in feature.qualifiers:

                # 期待値が 1 (標準表) の場合は、システムのデフォルトで処理されるため Autofix の提案をスキップする
                if table_id == 1:
                    continue

                updates = [{
                    "action": "add_qualifier",
                    "entry": entry_id,
                    "feature_type": feature.type,
                    "feature_id": getattr(feature, 'line_number', id(feature)),
                    "feature_line": getattr(feature, 'line_number', -1),
                    "qualifier": "transl_table",
                    "new_value": str(table_id)
                }]

                proposals.append(build_proposal(
                    ann_path=ann_path, entry=entry_id, feature_type=feature.type,
                    qualifier="transl_table", target="transl_table", target_level="qualifier",
                    positions=[{"entry": entry_id, "feature_id": getattr(feature, 'line_number', id(feature))}],
                    old_value="none", new_value=str(table_id), rule="ANN1050",
                    updates=updates, source_db=source_db_str
                ))
            else:
                ann_table = feature.qualifiers["transl_table"][0]
                if str(ann_table) != str(table_id):
                    updates = [update_qualifier_action(entry_id, feature.type, "transl_table", str(ann_table), str(table_id), feature_id=getattr(feature, 'line_number', id(feature)))]

                    proposals.append(build_proposal(
                        ann_path=ann_path, entry=entry_id, feature_type=feature.type,
                        qualifier="transl_table", target="transl_table", target_level="qualifier",
                        positions=[{"entry": entry_id, "feature_id": getattr(feature, 'line_number', id(feature))}],
                        old_value=str(ann_table), new_value=str(table_id), rule="ANN1050",
                        updates=updates, source_db=source_db_str
                    ))
    return proposals
