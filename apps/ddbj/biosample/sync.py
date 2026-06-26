"""BioSample 同期（ann↔BioSample）の autofix 提案を生成する関数群。

`-b/--biosample` 時に propose_qualifiers_updates（external_db.py）から呼ばれる。
- _propose_biosample_qualifier_sync: 同名属性（organism/strain 等）の値不一致を同期
- _propose_locus_tag_prefix_sync:    locus_tag -> locus_tag_prefix（BS に無い時のみ ann->bs 追加）
- _propose_bioproject_sync:          DBLINK project -> bioproject_id

各提案には bs_decision（bs_wins/ann_wins/leave）が後段（manager）で付与される。
"""
from pathlib import Path
from apps.ddbj.autofix.proposal import build_proposal, update_qualifier_action
from apps.ddbj.utils.features import get_features


def _propose_biosample_qualifier_sync(record, entry_id, valid_samds, bs_data, ann_path, target_attrs, emit_additions=False):
    """source qualifier 群を BioSample 属性値と突合し、不一致なら修正提案を作る。

    emit_additions=True (-b 時) の場合、ann にのみ値があり BioSample 側が空の qualifier を
    「属性追加候補」として bs_addition 付き proposal で emit する（パッケージ定義ゲートは phase-3）。

    戻り値: (proposals, validation_warnings, skipped_warnings)
    """
    proposals = []
    validation_warnings = []
    skipped_warnings = []

    for feature in record.features:
        for attr in target_attrs:
            if attr in feature.qualifiers:
                ann_val_list = feature.qualifiers[attr]
                ann_val = ann_val_list[0] if ann_val_list else ""

                bs_values = set()
                bs_samd_map = {}
                for s in valid_samds:
                    val = bs_data[s].get(attr)
                    if val is not None and str(val).strip() != "":
                        clean_val = str(val).strip()
                        bs_values.add(clean_val)
                        bs_samd_map[clean_val] = s

                if len(bs_values) == 1:
                    bs_val = bs_values.pop()
                    source_samd = bs_samd_map[bs_val]

                    # 基本は完全一致チェック
                    is_mismatch = (ann_val != bs_val)

                    # geo_loc_name の場合は「:」より前の国名部分のみで一致判定を行う
                    if attr == "geo_loc_name" and is_mismatch:
                        ann_country = ann_val.split(":")[0].strip()
                        bs_country = bs_val.split(":")[0].strip()
                        if ann_country == bs_country:
                            is_mismatch = False

                    if is_mismatch:
                        msg = f"The '{attr}' qualifier value does not match the BioSample attribute value. (ann: '{ann_val}', BioSample: '{bs_val}')"
                        validation_warnings.append({
                            "file": Path(ann_path).name,
                            "full_path": str(ann_path),
                            "entry": entry_id,
                            "rule": "ANN1130",
                            "target": attr,
                            "level": "warning",
                            "message": msg,
                            "feature_type": feature.type,
                            "qualifier": attr,
                            "line_number": getattr(feature, 'line_number', None),
                            "location": getattr(feature, 'original_location', "")
                        })

                        updates = [update_qualifier_action(entry_id, feature.type, attr, ann_val, bs_val, feature_id=getattr(feature, 'line_number', id(feature)))]

                        prop = build_proposal(
                            ann_path=ann_path, entry=entry_id, feature_type=feature.type,
                            qualifier=attr, target=attr, target_level="qualifier",
                            positions=[{"entry": entry_id, "feature_id": getattr(feature, 'line_number', id(feature))}],
                            old_value=ann_val, new_value=bs_val, rule="ANN1130",
                            updates=updates, source_db=source_samd
                        )
                        prop["bs_attr"] = attr  # 上書き対象の BioSample 属性名（common は同名）
                        proposals.append(prop)

                elif len(bs_values) > 1:
                    skipped_warnings.append({
                        "ann_path": ann_path, "entry": entry_id,
                        "attr": attr, "values": bs_values
                    })

                elif emit_additions and ann_val:
                    # ann にのみ値があり BioSample 側が空 → 属性追加候補（bs_addition）。
                    # パッケージ定義に含まれるかの判定は phase-3 で行う。
                    for s in valid_samds:
                        p = build_proposal(
                            ann_path=ann_path, entry=entry_id, feature_type=feature.type,
                            qualifier=attr, target=attr, target_level="qualifier",
                            positions=[{"entry": entry_id, "feature_id": getattr(feature, 'line_number', id(feature))}],
                            old_value=ann_val, new_value="", rule="ANN1130",
                            updates=[], source_db=s,
                        )
                        p["bs_addition"] = True
                        p["bs_attr"] = attr
                        proposals.append(p)

    return proposals, validation_warnings, skipped_warnings


def _propose_locus_tag_prefix_sync(record, entry_id, valid_samds, bs_data, ann_path, emit_additions=False):
    """locus_tag prefix を BioSample の locus_tag_prefix と突合し、一括修正提案を作る。

    emit_additions=True (-b 時) かつ BioSample に locus_tag_prefix が無い場合、ann の locus_tag の
    先頭（最初の '_' より前）を prefix として「属性追加候補」を emit する。

    戻り値: (proposals, validation_warnings, skipped_warnings)
    """
    proposals = []
    validation_warnings = []
    skipped_warnings = []

    bs_prefixes = set()
    bs_prefix_samd_map = {}
    for s in valid_samds:
        val = bs_data[s].get("locus_tag_prefix")
        if val is not None and str(val).strip() != "":
            clean_val = str(val).strip()
            bs_prefixes.add(clean_val)
            bs_prefix_samd_map[clean_val] = s

    # -b（emit_additions=True）では locus_tag prefix の不一致 autofix は行わない（addition のみ）。
    # 一般実行（emit_additions=False）は従来どおり ann←bs prefix 修正を提案する。
    if not emit_additions and len(bs_prefixes) == 1:
        bs_prefix = bs_prefixes.pop()
        source_samd = bs_prefix_samd_map[bs_prefix]
        wrong_prefixes = set()

        if hasattr(record, 'features_by_locus_tag') and record.features_by_locus_tag:
            for tag_str, features in record.features_by_locus_tag.items():
                ann_prefix = tag_str.split("_", 1)[0] if "_" in tag_str else tag_str
                if ann_prefix and ann_prefix != bs_prefix:
                    wrong_prefixes.add(ann_prefix)

                    for feature in features:
                        msg = f"The 'locus_tag' prefix does not match the BioSample locus_tag_prefix. (ann: '{ann_prefix}', BioSample: '{bs_prefix}')"
                        validation_warnings.append({
                            "file": ann_path,
                            "entry_id": entry_id,
                            "rule": "ANN1130",
                            "target": "locus_tag_prefix",
                            "level": "warning",
                            "message": msg,
                            "feature_type": feature.type,
                            "qualifier": "locus_tag",
                            "line_number": getattr(feature, 'line_number', None),
                            "location": getattr(feature, 'original_location', "")
                        })
        else:
            for feature in record.features:
                if "locus_tag" in feature.qualifiers:
                    ann_locus_tag = feature.qualifiers["locus_tag"][0]
                    ann_prefix = ann_locus_tag.split("_", 1)[0] if "_" in ann_locus_tag else ann_locus_tag
                    if ann_prefix and ann_prefix != bs_prefix:
                        wrong_prefixes.add(ann_prefix)
                        msg = f"The 'locus_tag' prefix does not match the BioSample locus_tag_prefix. (ann: '{ann_prefix}', BioSample: '{bs_prefix}')"
                        validation_warnings.append({
                            "file": ann_path, "entry_id": entry_id, "rule": "ANN1130",
                            "target": "locus_tag_prefix", "level": "warning", "message": msg,
                            "feature_type": feature.type, "qualifier": "locus_tag",
                            "line_number": getattr(feature, 'line_number', None),
                            "location": getattr(feature, 'original_location', "")
                        })

        for wp in wrong_prefixes:
            positions = []
            updates = []

            if hasattr(record, 'features_by_locus_tag'):
                for tag_str, features in record.features_by_locus_tag.items():
                    curr_prefix = tag_str.split("_", 1)[0] if "_" in tag_str else tag_str
                    if curr_prefix == wp:
                        for f in features:
                            positions.append({"entry": entry_id, "feature_id": getattr(f, 'line_number', id(f))})

                            if "_" in tag_str:
                                _, suffix = tag_str.split("_", 1)
                                new_tag = f"{bs_prefix}_{suffix}"
                            else:
                                new_tag = bs_prefix

                            updates.append(update_qualifier_action(entry_id, f.type, "locus_tag", tag_str, new_tag, feature_id=getattr(f, 'line_number', id(f))))
            else:
                for f in record.features:
                    if "locus_tag" in f.qualifiers:
                        tags = f.qualifiers["locus_tag"]
                        old_tag = tags[0] if tags else ""
                        curr_prefix = old_tag.split("_", 1)[0] if "_" in old_tag else old_tag

                        if curr_prefix == wp:
                            positions.append({"entry": entry_id, "feature_id": getattr(f, 'line_number', id(f))})

                            if "_" in old_tag:
                                _, suffix = old_tag.split("_", 1)
                                new_tag = f"{bs_prefix}_{suffix}"
                            else:
                                new_tag = bs_prefix

                            updates.append(update_qualifier_action(entry_id, f.type, "locus_tag", old_tag, new_tag, feature_id=getattr(f, 'line_number', id(f))))

            prop = build_proposal(
                ann_path=ann_path, entry=entry_id, feature_type="",
                qualifier="locus_tag", target="locus_tag_prefix", target_level="qualifier",
                positions=positions,
                old_value=wp, new_value=bs_prefix, rule="ANN1130",
                updates=updates, source_db=source_samd
            )
            prop["bs_attr"] = "locus_tag_prefix"
            proposals.append(prop)

    elif not emit_additions and len(bs_prefixes) > 1:
        skipped_warnings.append({
            "ann_path": ann_path, "entry": entry_id,
            "attr": "locus_tag_prefix", "values": bs_prefixes
        })

    elif emit_additions and not bs_prefixes:
        # BioSample に locus_tag_prefix が無く ann に locus_tag がある → prefix を追加候補に
        ann_prefix = None
        if hasattr(record, 'features_by_locus_tag') and record.features_by_locus_tag:
            for tag_str in record.features_by_locus_tag:
                ann_prefix = tag_str.split("_", 1)[0] if "_" in tag_str else tag_str
                if ann_prefix:
                    break
        else:
            for feature in record.features:
                if "locus_tag" in feature.qualifiers and feature.qualifiers["locus_tag"]:
                    t = feature.qualifiers["locus_tag"][0]
                    ann_prefix = t.split("_", 1)[0] if "_" in t else t
                    if ann_prefix:
                        break
        if ann_prefix:
            for s in valid_samds:
                p = build_proposal(
                    ann_path=ann_path, entry=entry_id, feature_type="",
                    qualifier="locus_tag", target="locus_tag_prefix", target_level="qualifier",
                    positions=[], old_value=ann_prefix, new_value="", rule="ANN1130",
                    updates=[], source_db=s,
                )
                p["bs_addition"] = True
                p["bs_attr"] = "locus_tag_prefix"
                proposals.append(p)

    return proposals, validation_warnings, skipped_warnings


def _propose_bioproject_sync(records, valid_samds, bs_data, ann_path, emit_additions=False):
    """DBLINK の project(PRJDB) を BioSample の bioproject_id と突合する（mapping エントリ）。

    競合(ann≠BS) は通常 proposal、ann のみ(BS 空) は bs_addition として emit。bs_attr="bioproject_id"。
    """
    from apps.ddbj.utils.features import get_features
    proposals = []

    ann_projects = []
    for entry_id, record in records.items():
        for feature in get_features(record, "DBLINK"):
            for v in feature.qualifiers.get("project", []):
                if v and str(v).strip():
                    ann_projects.append(str(v).strip())
    if not ann_projects:
        return proposals, [], []
    # 単一前提（複数 project は対象外）
    if len(set(ann_projects)) != 1:
        return proposals, [], []
    ann_proj = ann_projects[0]

    for samd in valid_samds:
        bs_bp = str(bs_data[samd].get("bioproject_id", "") or "").strip()
        if bs_bp and bs_bp != ann_proj:
            prop = build_proposal(
                ann_path=ann_path, entry="COMMON", feature_type="DBLINK",
                qualifier="project", target="bioproject_id", target_level="qualifier",
                positions=[], old_value=ann_proj, new_value=bs_bp, rule="ANN1130",
                updates=[], source_db=samd,
            )
            prop["bs_attr"] = "bioproject_id"
            proposals.append(prop)
        elif emit_additions and not bs_bp:
            p = build_proposal(
                ann_path=ann_path, entry="COMMON", feature_type="DBLINK",
                qualifier="project", target="bioproject_id", target_level="qualifier",
                positions=[], old_value=ann_proj, new_value="", rule="ANN1130",
                updates=[], source_db=samd,
            )
            p["bs_addition"] = True
            p["bs_attr"] = "bioproject_id"
            proposals.append(p)

    return proposals, [], []


