import re
import os
import json
import datetime
from common.rules.base import BaseRule
from apps.ddbj.rules.division_datatype import get_active_divisions
from collections import defaultdict
from apps.ddbj.utils.location import get_introns_from_join
from common.db_taxonomy import get_expected_transl_table
from datetime import date
from dateutil import parser
from Bio.Seq import Seq
from Bio.SeqFeature import CompoundLocation, BeforePosition, AfterPosition, ExactPosition, FeatureLocation
from apps.ddbj.parser import _parse_location_string, LocationParseError, LocationRangeError
from collections import defaultdict
from common.ncbi_api import check_ncbi_public_status
from intervaltree import IntervalTree
from shapely.geometry import Point

POS_PATTERN = re.compile(r"pos:(.+?),aa:")

def normalize_name(s):
    if not s: return ""
    return re.sub(r'[^a-z]', '', s.lower())

class ANN0160(BaseRule):
    rule_id = "ANN0160"
    alternate_id = "JP0022"
    target = "file"
    description = "Invalid entry name."
    requires_rdb = False
    is_file_level = False

    def validate(self, record, context):
        results = []
        entry_name = record.id

        if entry_name == "COMMON" or not entry_name:
            return results

        invalid_pattern = re.compile(r'[ ="|>\[\]\\]')
        is_valid = True
        
        if len(entry_name) > 32:
            is_valid = False
        elif not re.match(r'^[A-Za-z0-9]', entry_name):
            is_valid = False
        elif invalid_pattern.search(entry_name):
            is_valid = False
        elif not entry_name.isascii():
            is_valid = False

        if not is_valid:
            msg = f"{self.description} (Found: '{entry_name}')"
            res = self.format_result(entry_id=entry_name, message=msg, level="fatal", feature_type="entry")
            res["rule"], res["target"] = self.rule_id, "file"
            results.append(res)

        return results        


class ANN0230(BaseRule):
    rule_id = "ANN0230"
    alternate_id = "JP0035"
    target = "SUBMITTER"
    description = "At least one submitter's 'ab_name' must match the contact person."
    requires_rdb = False
    is_file_level = True

    def _get_valid_names(self, contact_str):
        """
        contact文字列からアルファベットを抽出し、First/Lastの逆転を考慮した
        ab_name (Last + Initials または Initials + Last) の検証用パターンを生成する
        """
        words = re.findall(r'[a-zA-Z]+', str(contact_str).lower())
        valid = set()
        if not words:
            return valid

        # どの単語がLast Nameになるか分からないため、すべての単語をLast Nameとして試行
        for i, last_word in enumerate(words):
            other_words = words[:i] + words[i+1:]
            if not other_words:
                valid.add(last_word)
                continue

            # 他の単語の頭文字（イニシャル）を取得 (例: "george", "robert" -> "gr")
            initials_fw = "".join(w[0] for w in other_words)
            valid.add(last_word + initials_fw)
            valid.add(initials_fw + last_word)

            # イニシャルの順序が逆転しているケースも考慮
            initials_rev = "".join(w[0] for w in reversed(other_words))
            valid.add(last_word + initials_rev)
            valid.add(initials_rev + last_word)
            
            # ab_name がフルネームで記載されているケースのためのフォールバック
            full_others = "".join(other_words)
            valid.add(last_word + full_others)
            valid.add(full_others + last_word)

        return valid

    def validate_file(self, records, context):
        results = []

        for record in records.values():
            for feature in self.get_features(record, "SUBMITTER"):
                # contact が存在する場合のみチェックを実行
                if "contact" in feature.qualifiers:
                    contacts = feature.qualifiers["contact"]
                    # ab_name が存在しない場合は空リストとして扱う
                    ab_names = feature.qualifiers.get("ab_name", [])

                    for contact in contacts:
                        valid_names = self._get_valid_names(contact)
                        match_found = False

                        for ab in ab_names:
                            # 比較対象の ab_name を正規化（アルファベットのみ小文字）
                            # "Fuji,S." -> "fujis", "Robertson,G.R." -> "robertsongr"
                            ab_norm = re.sub(r'[^a-zA-Z]', '', str(ab)).lower()
                            
                            # 部分一致も含めて寛容にチェック
                            if any((ab_norm in vn or vn in ab_norm) for vn in valid_names):
                                match_found = True
                                break

                        if not match_found:
                            msg = f"{self.description} ('{contact}')"                            
                            results.append(self.feature_result(
                                record, 
                                feature, 
                                msg, 
                                level="error", 
                                qualifier="contact"
                            ))

        return results
        

class ANN0250(BaseRule):
    rule_id = "ANN0250"
    alternate_id = "CMC0020"
    target = "SUBMITTER"
    description = "Contact person not included in the associated BioSample."
    requires_rdb = True
    is_file_level = True

    def validate_file(self, records, context):
        results = []
        
        # 1. データベースの情報がセットされていない場合は早期リターン
        if not context.bs_submitters: 
            return results

        file_samds = set()
        for record in records.values():
            for f in self.get_features(record, "DBLINK"):
                if "biosample" in f.qualifiers:
                    for bs in f.qualifiers["biosample"]:
                        file_samds.add(bs)

        valid_names = set()
        for samd in file_samds:
            for sub in context.bs_submitters.get(samd, []):
                # 2. 空対策: None やキーが存在しない場合に備え、空文字でフォールバック
                first_raw = sub.get("first") or ""
                last_raw = sub.get("last") or ""
                
                first = re.sub(r'[\W_]+', '', str(first_raw)).lower()
                last = re.sub(r'[\W_]+', '', str(last_raw)).lower()
                
                # 3. 空対策: データベース側が First も Last も空欄の場合は登録しない
                if not first and not last:
                    continue

                valid_names.add(first + last)
                valid_names.add(last + first)

        for record in records.values():
            for feature in self.get_features(record, "SUBMITTER"):
                if "contact" in feature.qualifiers:
                    for contact in feature.qualifiers["contact"]:
                        c_norm = re.sub(r'[\W_]+', '', str(contact)).lower()
                        
                        # 4. 完全一致で厳密に比較
                        match = any(c_norm == vn for vn in valid_names)
                        
                        if not match:
                            msg = f"{self.description} ('{contact}')"
                            results.append(self.feature_result(record, feature, msg, level="warning", qualifier="contact"))
                            
        return results
        
                
class ANN0260(BaseRule):
    rule_id = "ANN0260"
    alternate_id = "CMC0021"
    target = "SUBMITTER"
    description = "Contact person email not included in the associated BioSample."
    requires_rdb = True
    is_file_level = True

    def validate_file(self, records, context):
        results = []
        if not context.bs_submitters: return results

        file_samds = set()
        for record in records.values():
            for f in self.get_features(record, "DBLINK"):
                if "biosample" in f.qualifiers:
                    file_samds.update(f.qualifiers["biosample"])

        valid_emails = set()
        for samd in file_samds:
            for sub in context.bs_submitters.get(samd, []):
                if sub["email"]:
                    valid_emails.add(sub["email"].lower())

        for record in records.values():
            for feature in self.get_features(record, "SUBMITTER"):
                if "email" in feature.qualifiers:
                    for email in feature.qualifiers["email"]:
                        if email.lower() not in valid_emails:
                            msg = f"{self.description} ('{email}')"
                            results.append(self.feature_result(record, feature, msg, level="warning", qualifier="email"))
        return results


class ANN0270(BaseRule):
    rule_id = "ANN0270"
    alternate_id = "CMC0022"
    target = "SUBMITTER"
    description = "No submitter ab_name shared with the associated BioSample."
    requires_rdb = True
    is_file_level = True

    def validate_file(self, records, context):
        results = []
        if not context.bs_submitters: return results

        file_samds = set()
        for record in records.values():
            for f in self.get_features(record, "DBLINK"):
                if "biosample" in f.qualifiers:
                    file_samds.update(f.qualifiers["biosample"])

        valid_abnames = set()
        for samd in file_samds:
            for sub in context.bs_submitters.get(samd, []):
                first_full = normalize_name(sub["first"])
                last_full = normalize_name(sub["last"])
                f_ini = first_full[0] if first_full else ""
                l_ini = last_full[0] if last_full else ""
                
                valid_abnames.update([
                    last_full + f_ini, f_ini + last_full,
                    first_full + l_ini, l_ini + first_full,
                    first_full + last_full, last_full + first_full
                ])

        for record in records.values():
            for feature in self.get_features(record, "SUBMITTER"):
                if "ab_name" in feature.qualifiers:
                    ann_ab_names = feature.qualifiers["ab_name"]
                    if not ann_ab_names:
                        continue
                        
                    overlap_found = False
                    for ab_name in ann_ab_names:
                        ab_norm = normalize_name(ab_name)
                        for va in valid_abnames:
                            if va and (ab_norm in va or va in ab_norm):
                                overlap_found = True
                                break
                        if overlap_found:
                            break
                    
                    if not overlap_found:
                        results.append(self.feature_result(record, feature, self.description, level="warning", qualifier="ab_name"))
        return results


class ANN0300(BaseRule):
    rule_id = "ANN0300"
    target = "REFERENCE"
    description = "Invalid reference information:"
    requires_rdb = False
    is_file_level = False

    def validate(self, record, context):
        results = []
        
        for feature in self.get_features(record, "REFERENCE"):
            qualifiers = feature.qualifiers
            status = qualifiers.get("status", [""])[0] if qualifiers.get("status") else None
            
            if status != "Unpublished" and "year" not in qualifiers:
                msg = f"{self.description} Missing publication 'year'."
                results.append(self.feature_result(record, feature, msg, level="warning"))

            if status == "In Press":
                if "journal" not in qualifiers:
                    msg = f"{self.description} 'journal' is required when status is 'In Press'."
                    results.append(self.feature_result(record, feature, msg, level="error"))
                    
            elif status == "Published":
                required = ["journal", "volume", "start_page", "end_page"]
                missing = [f for f in required if f not in qualifiers]
                if missing:
                    missing_str = ", ".join(missing)
                    msg = f"{self.description} {missing_str} required when status is 'Published'."
                    results.append(self.feature_result(record, feature, msg, level="error"))
                    
        return results


class ANN0342(BaseRule):
    rule_id = "ANN0342"
    alternate_id = "JP0033"
    target = "REFERENCE"
    description = "The 'Published Only in Database' must be the first REFERENCE."
    requires_rdb = False
    is_file_level = True

    def validate_file(self, records, context, ann_path=None, seq_path=None):
        results = []
        
        # ファイル全体を通した REFERENCE の登場順を管理するカウンター
        global_ref_index = 0
        
        for record in records.values():
            for feature in self.get_features(record, "REFERENCE"):
                # status 修飾子が存在するかチェック
                if "status" in feature.qualifiers:
                    for status in feature.qualifiers["status"]:
                        if status == "Published Only in Database":
                            # 最初の REFERENCE (インデックス0) でない場合にエラーとする
                            if global_ref_index > 0:
                                results.append(self.feature_result(
                                    record, 
                                    feature, 
                                    self.description, 
                                    level="error", 
                                    qualifier="status"
                                ))
                
                # 次の REFERENCE フィーチャーへ進むためカウンターを増やす
                global_ref_index += 1

        return results

class ANN0343(BaseRule):
    rule_id = "ANN0343"
    alternate_id = "JP0034"
    target = "REFERENCE"
    description = "More than one 'Published Only in Database' REFERENCE. Please provide only one."
    requires_rdb = False
    is_file_level = True

    def validate_file(self, records, context, ann_path=None, seq_path=None):
        results = []

        for record in records.values():
            db_only_features = []
            
            for feature in self.get_features(record, "REFERENCE"):
                if "status" in feature.qualifiers:
                    for status in feature.qualifiers["status"]:
                        if status == "Published Only in Database":
                            db_only_features.append(feature)
                            # 同じREFERENCE内に複数statusが記述されていた場合の重複カウントを防ぐ
                            break 
            
            # 複数存在する場合は、2つ目以降のREFERENCEをエラーとして報告
            if len(db_only_features) > 1:
                for feature in db_only_features[1:]:
                    results.append(self.feature_result(
                        record, 
                        feature, 
                        self.description, 
                        level="error", 
                        qualifier="status"
                    ))

        return results
        
        
class ANN0345(BaseRule):
    rule_id = "ANN0345"
    alternate_id = "V200"
    target = "REFERENCE"
    description = "Invalid journal name. Not in the controlled values."
    requires_rdb = True
    is_file_level = True

    def validate_file(self, records, context):
        results = []
        
        # 比較およびAutofix提案用に、「小文字化された名前」と「DB上の正しい名前」のマッピングを作成
        # 例: {"nature": "Nature", "cell": "Cell"}
        valid_lower_map = {j.lower(): j for j in context.valid_journals}
        
        for record in records.values():
            for feature in self.get_features(record, "REFERENCE"):
                journals = feature.qualifiers.get("journal", [])
                
                for journal in journals:
                    if not journal:
                        continue
                        
                    # 1. 完全に一致する場合はOK (そのままの表記でDBに存在)
                    if journal in context.valid_journals:
                        continue
                        
                    # 2. 小文字化して一致するか（大文字小文字の違いだけか）チェック
                    journal_lower = journal.lower()
                    if journal_lower in valid_lower_map:
                        # 大文字小文字の違いで一致する場合 -> Autofix を提案
                        expected_journal = valid_lower_map[journal_lower]
                        msg = f"Journal name formatting differs from the controlled values. (Expected: '{expected_journal}', Found: '{journal}')"
                        res = self.feature_result(record, feature, msg, level="warning", qualifier="journal")
                        
                        res["autofix"] = True
                        res["old_value"] = journal
                        res["new_value"] = expected_journal
                        results.append(res)
                    else:
                        # 3. まったく一致しない場合 -> 単なるWarning
                        msg = f"{self.description} (Found: '{journal}')"
                        results.append(self.feature_result(record, feature, msg, level="warning", qualifier="journal"))
                        
        return results
        
                                
class ANN0350(BaseRule):
    rule_id = "ANN0350"
    target = "qualifier"
    description = "Trailing comma is detected in qualifier value."
    requires_rdb = False
    is_file_level = False

    def validate(self, record, context):
        results = []
        
        for feature in self.get_features(record):
            for q_name, q_values in feature.qualifiers.items():
                values_to_check = q_values if isinstance(q_values, list) else [q_values]

                for val in values_to_check:
                    val_str = str(val)
                    
                    if val_str.endswith(','):
                        fixed_val = val_str.rstrip(',')
                        
                        msg = f"Trailing comma is detected. (Found: '{val_str}')"
                        res = self.feature_result(record, feature, msg, level="warning", qualifier=q_name)
                        
                        res["autofix"] = True
                        res["old_value"] = val_str
                        res["new_value"] = fixed_val
                        
                        results.append(res)
                        
        return results


class ANN0410(BaseRule):
    rule_id = "ANN0410"
    alternate_id = "BLP0001"
    target = "DBLINK"
    description = "Missing BioProject accession."
    requires_rdb = False
    is_file_level = True

    def validate_file(self, records, context):
        has_project = False
        for record in records.values():
            for feature in self.get_features(record, "DBLINK"):
                if "project" in feature.qualifiers:
                    has_project = True
                    break
            if has_project: break
        
        if not has_project:
            return [self.format_result(entry_id="ALL", message=self.description, level="warning")]
        return []


class ANN0420(BaseRule):
    rule_id = "ANN0420"
    alternate_id = "BLP0002"
    target = "DBLINK"
    description = "BioProject accession is not found in the BioProject database."
    requires_rdb = True
    is_file_level = True

    def validate_file(self, records, context):
        results = []
        checked = set()
        
        for record in records.values():
            for feature in self.get_features(record, "DBLINK"):
                if "project" in feature.qualifiers:
                    for prj in feature.qualifiers["project"]:
                        
                        if not prj.startswith("PRJD"):
                            continue
                        
                        if prj not in checked:
                            checked.add(prj)
                            # context.bp_psubs のキーに存在するかどうかで判定
                            if prj.startswith("PRJDB") and prj not in context.bp_psubs:
                                msg = f"{self.description} ('{prj}')"
                                results.append(self.feature_result(record, feature, msg, level="error", qualifier="project"))
        return results


class ANN0425(BaseRule):
    rule_id = "ANN0425"
    alternate_id = "BLP0002_STATUS"
    target = "DBLINK"
    description = "BioProject accession is cancelled/permanently suppressed/withdrawn in the BioProject database."
    requires_rdb = True
    is_file_level = True

    def validate_file(self, records, context):
        results = []
        checked = set()
        
        # ステータスIDとメッセージ用文字列のマッピング
        status_map = {
            5600: "withdrawn",
            5700: "cancelled",
            5800: "permanently suppressed"
        }
        
        for record in records.values():
            for feature in self.get_features(record, "DBLINK"):
                if "project" in feature.qualifiers:
                    for raw_prj in feature.qualifiers["project"]:
                        prj = raw_prj
                        
                        if not prj.startswith("PRJD"):
                            continue
                        
                        if prj not in checked:
                            checked.add(prj)
                            if prj.startswith("PRJDB") and prj in context.bp_psubs:
                                bp_info = context.bp_psubs[prj]
                                status_id = bp_info.get("status_id")
                                
                                if status_id in status_map:
                                    status_str = status_map[status_id]
                                    # 実際のステータスに合わせてメッセージを動的に生成
                                    msg = f"BioProject accession is {status_str} in the BioProject database. ('{prj}')"                                                                        
                                    results.append(self.feature_result(record, feature, msg, level="error", qualifier="project"))
        return results
        
        
class ANN0430(BaseRule):
    rule_id = "ANN0430"
    alternate_id = "BLP0003"
    target = "DBLINK"
    description = "BioProject accession mismatches with the BioProject associated with the linked DRR accessions."
    requires_rdb = True
    is_file_level = True

    def validate_file(self, records, context):
        results = []
        for record in records.values():
            for feature in self.get_features(record, "DBLINK"):
                prjs = [p for p in feature.qualifiers.get("project", []) if p.startswith("PRJDB")]
                drrs = [d for d in feature.qualifiers.get("sequence read archive", []) if d.startswith("DRR")]
                
                if not prjs or not drrs:
                    continue
                    
                prjs_set = set(prjs)
                drr_prjs_set = set()
                
                for drr in drrs:
                    refs = context.dra_refs.get(drr, set())
                    for r in refs:
                        if r.startswith("PSUB") and r in context.psub_to_prjdb:
                            # 辞書から "accession" を取得する
                            prj_data = context.psub_to_prjdb[r]
                            accession = prj_data.get("accession") if isinstance(prj_data, dict) else prj_data
                            if accession:
                                drr_prjs_set.add(accession)
                            
                if prjs_set and drr_prjs_set and prjs_set != drr_prjs_set:
                    msg = f"{self.description} (DBLINK {', '.join(sorted(prjs_set))}, DRRs reference {', '.join(sorted(drr_prjs_set))})"
                    results.append(self.feature_result(record, feature, msg, level="warning", qualifier="project"))
        return results


class ANN0440(BaseRule):
    rule_id = "ANN0440"
    alternate_id = "BLP0004"
    target = "DBLINK"
    description = "BioProject accession mismatches with the BioProject associated with the linked BioSample accessions."
    requires_rdb = True
    is_file_level = True

    def validate_file(self, records, context):
        results = []
        for record in records.values():
            for feature in self.get_features(record, "DBLINK"):
                prjs = [p for p in feature.qualifiers.get("project", []) if p.startswith("PRJDB")]
                samds = [s for s in feature.qualifiers.get("biosample", []) if s.startswith("SAMD")]
                
                if not prjs or not samds:
                    continue
                                            
                for samd in samds:
                    samd_attrs = context.bs_data.get(samd, {})
                    samd_prj = samd_attrs.get("bioproject_id") or samd_attrs.get("project")
                    if samd_prj:
                        for prj in prjs:
                            if prj != samd_prj:
                                msg = f"{self.description} ({prj} vs {samd_prj} in {samd})"
                                results.append(self.feature_result(record, feature, msg, level="warning", qualifier="project"))
        return results


class ANN0445(BaseRule):
    rule_id = "ANN0445"
    alternate_id = "BS_R0070"
    target = "DBLINK"
    description = "BioProject is an Umbrella project, not a primary data type of BioProject. Please provide the accession of the correct primary data BioProject or create a new BioProject, if necessary."
    requires_rdb = True
    is_file_level = True

    def validate_file(self, records, context):
        results = []
        checked = set()
        
        for record in records.values():
            for feature in self.get_features(record, "DBLINK"):
                if "project" in feature.qualifiers:
                    for prj in feature.qualifiers["project"]:

                        if not prj.startswith("PRJD"):
                            continue
                                                    
                        if prj not in checked:
                            checked.add(prj)
                            
                            if prj.startswith("PRJDB") and prj in context.bp_psubs:
                                project_info = context.bp_psubs[prj]
                                # 辞書型であることを前提に get を使用
                                project_type = project_info.get("project_type") if isinstance(project_info, dict) else None
                                
                                if project_type and project_type == "umbrella":
                                    msg = f"{self.description} ('{prj}')"
                                    results.append(self.feature_result(record, feature, msg, level="error", qualifier="project"))
        return results
        
class ANN0450(BaseRule):
    rule_id = "ANN0450"
    alternate_id = "BLP0005"
    target = "DBLINK"
    description = "Missing BioSample accession."
    requires_rdb = False
    is_file_level = True

    def validate_file(self, records, context):
        has_biosample = False
        for record in records.values():
            for feature in self.get_features(record, "DBLINK"):
                if "biosample" in feature.qualifiers:
                    has_biosample = True
                    break
            if has_biosample: break
        
        if not has_biosample:
            return [self.format_result(entry_id="ALL", message=self.description, level="warning")]
        return []


class ANN0460(BaseRule):
    rule_id = "ANN0460"
    alternate_id = "BLP0006"
    target = "DBLINK"
    description = "BioSample accession not found in the BioSample database."
    requires_rdb = True
    is_file_level = True

    def validate_file(self, records, context):
        results = []
        checked = set()
        for record in records.values():
            for feature in self.get_features(record, "DBLINK"):
                if "biosample" in feature.qualifiers:
                    for raw_samd in feature.qualifiers["biosample"]:
                        samd = raw_samd

                        if not samd.startswith("SAMD"):
                            continue

                        if samd not in checked:
                            checked.add(samd)
                            # context.bs_smp_ids と照合
                            if samd not in context.bs_smp_ids:
                                msg = f"{self.description} ('{samd}')"
                                results.append(self.feature_result(record, feature, msg, level="error", qualifier="biosample"))
        return results


class ANN0461(BaseRule):
    rule_id = "ANN0461"
    target = "DBLINK"
    description = "Accession is not publicly available in NCBI."
    requires_rdb = False
    is_file_level = True

    def validate_file(self, records, context):
        if not context.ncbi_private_accs:
            return []
            
        results = []
        private_by_group = {}

        for entry_id, record in records.items():
            for feature in self.get_features(record, "DBLINK"):
                for db_type in ["project", "biosample", "sequence read archive"]:
                    for acc in feature.qualifiers.get(db_type, []):
                        acc_clean = acc
                        
                        if acc_clean in context.ncbi_private_accs:
                            key = (id(feature), db_type)
                            if key not in private_by_group:
                                private_by_group[key] = {
                                    "record": record,
                                    "feature": feature,
                                    "type": db_type,
                                    "accs": []
                                }
                            private_by_group[key]["accs"].append(acc_clean)

        for info in private_by_group.values():
            accs_str = ", ".join(info["accs"])
            msg = f"{self.description} ('{accs_str}')"
            results.append(self.feature_result(
                info["record"], 
                info["feature"], 
                msg, 
                level="warning", 
                qualifier=info["type"]
            ))
                
        return results


class ANN0462(BaseRule):
    rule_id = "ANN0462"
    alternate_id = "V200"
    target = "DBLINK"
    description = "Multiple BioSample accessions are permitted only for TSA/TLS entries."
    requires_rdb = False
    is_file_level = False

    def validate(self, record, context):
        results = []
        
        is_tsa_or_tls = context.is_tsa or ("TLS" in context.active_datatypes) or ("TLS" in context.active_divisions)
        
        if is_tsa_or_tls:
            return results

        biosamples = []
        first_dblink_feature = None

        for feature in self.get_features(record, "DBLINK"):
            if "biosample" in feature.qualifiers:
                if not first_dblink_feature:
                    first_dblink_feature = feature
                biosamples.extend(feature.qualifiers["biosample"])

        unique_biosamples = set(bs.strip() for bs in biosamples if bs.strip())

        if len(unique_biosamples) > 1:
            msg = f"{self.description} (Found: {', '.join(sorted(unique_biosamples))})"
            if first_dblink_feature:
                results.append(self.feature_result(record, first_dblink_feature, msg, level="error", qualifier="biosample"))

        return results


class ANN0463(BaseRule):
    rule_id = "ANN0463"
    alternate_id = ""
    target = "DBLINK"
    description = "BioSample accession is cancelled/permanently suppressed/withdrawn in the BioSample database."
    requires_rdb = True
    is_file_level = True

    def validate_file(self, records, context):
        results = []
        checked = set()
        
        status_map = {
            5600: "withdrawn",
            5700: "cancelled",
            5800: "permanently suppressed"
        }

        for record in records.values():
            for feature in self.get_features(record, "DBLINK"):
                if "biosample" in feature.qualifiers:
                    for raw_samd in feature.qualifiers["biosample"]:
                        samd = raw_samd
                        
                        if not samd.startswith("SAMD"):
                            continue
                        
                        if samd not in checked:
                            checked.add(samd)
                            
                            # DBLINKに記載されたSAMD番号を使って直接 bs_data を参照
                            if hasattr(context, "bs_data") and context.bs_data:
                                samd_info = context.bs_data.get(samd, {})
                                status_id = samd_info.get("status_id")
                                
                                if status_id in status_map:
                                    status_str = status_map[status_id]
                                    msg = f"BioSample accession is {status_str} in the BioSample database. ('{samd}')"
                                    results.append(self.feature_result(record, feature, msg, level="error", qualifier="biosample"))
        return results
        
                                
class ANN0470(BaseRule):
    rule_id = "ANN0470"
    alternate_id = "BLP0007"
    target = "DBLINK"
    description = "Missing SRA Run accession."
    requires_rdb = False
    is_file_level = True

    def validate_file(self, records, context):
        has_drr = False
        for record in records.values():
            for feature in self.get_features(record, "DBLINK"):
                if "sequence read archive" in feature.qualifiers:
                    has_drr = True
                    break
            if has_drr: break
        
        if not has_drr:
            return [self.format_result(entry_id="ALL", message=self.description, level="warning")]
        return []

class ANN0480(BaseRule):
    rule_id = "ANN0480"
    alternate_id = "CMC0200"
    target = "DBLINK"
    description = "DRR accession not found in the DRA database."
    requires_rdb = True
    is_file_level = True

    def validate_file(self, records, context):
        results = []
        checked = set()
        for record in records.values():
            for feature in self.get_features(record, "DBLINK"):
                if "sequence read archive" in feature.qualifiers:
                    for drr in feature.qualifiers["sequence read archive"]:

                        if not drr.startswith("DRR"):
                            continue

                        if drr not in checked:
                            checked.add(drr)
                            if drr.startswith("DRR") and drr not in context.dra_refs:
                                msg = f"{self.description} ('{drr}')"
                                results.append(self.feature_result(record, feature, msg, level="error", qualifier="sequence read archive"))
        return results


class ANN0485(BaseRule):
    rule_id = "ANN0485"
    alternate_id = ""
    target = "DBLINK"
    description = "DRR accession is cancelled/permanently suppressed/withdrawn in the DRA database."
    requires_rdb = True
    is_file_level = True

    def validate_file(self, records: dict, context):
        results = []
        checked = set()
        
        # ユーザー指定のステータス定義（数値・文字列の両方に対応）
        invalid_statuses = {1000, 1100, 1200, "1000", "1100", "1200"}
        status_map = {
            1000: "cancelled", "1000": "cancelled",
            1100: "permanently suppressed", "1100": "permanently suppressed",
            1200: "withdrawn", "1200": "withdrawn"
        }

        for record in records.values():
            for feature in self.get_features(record, "DBLINK"):
                if "sequence read archive" in feature.qualifiers:
                    for raw_drr in feature.qualifiers["sequence read archive"]:
                        drr = raw_drr
                        
                        if not drr.startswith("DRR"):
                            continue
                        
                        if drr not in checked:
                            checked.add(drr)
                            
                            # コンテキストからステータスを取得
                            if hasattr(context, "drr_status") and context.drr_status:
                                status = context.drr_status.get(drr)
                                
                                if status in invalid_statuses:
                                    status_str = status_map[status]
                                    msg = f"DRR accession is {status_str} in the DRA database. ('{drr}')"
                                    results.append(self.feature_result(record, feature, msg, level="error", qualifier="sequence read archive"))
        return results
        
                
class ANN0490(BaseRule):
    rule_id = "ANN0490"
    alternate_id = None
    target = "DBLINK"
    description = "BioSample accession mismatches with the BioSample associated with the linked DRR accessions."
    requires_rdb = True
    is_file_level = True

    def validate_file(self, records, context):
        results = []
        for entry_id, record in records.items():
            for feature in self.get_features(record, "DBLINK"):
                samds = [s for s in feature.qualifiers.get("biosample", []) if s.startswith("SAMD")]
                drrs = [d for d in feature.qualifiers.get("sequence read archive", []) if d.startswith("DRR")]                    

                if not samds or not drrs:
                    continue
                    
                samds_set = set(samds)
                drr_samds_set = set()
                
                for drr in drrs:
                    refs = context.dra_refs.get(drr, set())
                    for r in refs:
                        if r.isdigit() and r in context.smp_id_to_samd:
                            samd_info = context.smp_id_to_samd[r]
                            samd_acc = samd_info.get("accession") if isinstance(samd_info, dict) else samd_info
                            if samd_acc:
                                drr_samds_set.add(samd_acc)
                            
                if samds_set and drr_samds_set and samds_set != drr_samds_set:
                    msg = f"{self.description} (DBLINK {', '.join(sorted(samds_set))}, DRRs reference {', '.join(sorted(drr_samds_set))})"
                    results.append(self.feature_result(record, feature, msg, level="warning", qualifier="biosample"))
        return results
        

class ANN0800(BaseRule):
    rule_id = "ANN0800"
    alternate_id = "CMC0050"
    target = "ST_COMMENT"
    description = "Invalid Assembly Method version format."
    requires_rdb = False
    is_file_level = False

    def validate(self, record, context):
        results = []
        for feat in self.get_features(record, "ST_COMMENT"):
            q_name = "Assembly Method"
            if q_name in feat.qualifiers:
                for i, val in enumerate(feat.qualifiers[q_name]):
                    val_str = str(val)
                    
                    if re.search(r'v\.(?=\S)', val_str):
                        fixed_val = re.sub(r'v\.(?=\S)', 'v. ', val_str)
                        
                        msg = "Invalid Assembly Method version format."
                        res = self.feature_result(record, feat, msg, level="warning", qualifier=q_name)
                        
                        res["autofix"] = True
                        res["old_value"] = val_str
                        res["new_value"] = fixed_val
                        results.append(res)
        return results


class ANN0810(BaseRule):
    rule_id = "ANN0810"
    target = "ST_COMMENT"
    description = "Invalid Genome Coverage/Coverage format."
    requires_rdb = False
    is_file_level = False

    def validate(self, record, context):
        results = []
        for feat in self.get_features(record, "ST_COMMENT"):
            for q_name in ["Genome Coverage", "Coverage"]:
                if q_name in feat.qualifiers:
                    for i, val in enumerate(feat.qualifiers[q_name]):
                        val_str = str(val)
                        
                        if re.fullmatch(r'^\d+(\.\d+)?$', val_str):
                            fixed_val = f"{val_str}x"
                            
                            msg = f"Invalid {q_name} format."
                            res = self.feature_result(record, feat, msg, level="warning", qualifier=q_name)
                            
                            res["autofix"] = True
                            res["old_value"] = val_str
                            res["new_value"] = fixed_val
                            results.append(res)
        return results
        
    
class ANN0820(BaseRule):
    rule_id = "ANN0820"
    alternate_id = None
    target = "ST_COMMENT"
    description = "Assembly Name required for eukaryotes."
    requires_rdb = True
    is_file_level = True

    def validate_file(self, records, context, ann_path=None, seq_path=None):
        results = []

        # WGS かつ 真核生物 でなければ即終了
        if not (context.is_wgs and context.is_eukaryote):
            return results

        # 真核生物の名前を取得（エラーメッセージ用）
        eukaryote_org_name = ""
        for record in records.values():
            for feature in self.get_features(record, "source"):
                for org in feature.qualifiers.get("organism", []):
                    org_clean = org.strip()
                    t_data = context.tax_data.get(org_clean, {})
                    if "Eukaryota" in t_data.get("lineage", ""):
                        eukaryote_org_name = org_clean
                        break
                if eukaryote_org_name: break
            if eukaryote_org_name: break

        # ST_COMMENT に Assembly Name が存在するかチェック
        has_assembly_name = False
        for record in records.values():
            for feature in self.get_features(record, "ST_COMMENT"):
                if "Assembly Name" in feature.qualifiers:
                    has_assembly_name = True
                    break
            if has_assembly_name: break

        if not has_assembly_name:
            msg = f"{self.description} (Organism: '{eukaryote_org_name}')"
            results.append(self.format_result(
                entry_id="ALL",
                message=msg,
                level="warning",
                feature_type="ST_COMMENT"
            ))

        return results

class ANN0830(BaseRule):
    rule_id = "ANN0830"
    alternate_id = "JP0154, JP0156, JP0157, JP0158, JP0159, JP0161"
    target = "ST_COMMENT"
    description = "Invalid ST_COMMENT qualifier value."
    requires_rdb = False
    is_file_level = False

    def validate(self, record, context):
        results = []
        
        for feature in self.get_features(record, "ST_COMMENT"):
            qual_keys = list(feature.qualifiers.keys())
            
            if qual_keys and qual_keys[0] != "tagset_id":
                msg = "The tagset_id must be the first qualifier in ST_COMMENT."
                res = self.feature_result(record, feature, msg, level="error", qualifier=qual_keys[0])
                res["rule"] = "ANN0870"
                results.append(res)

            for q_name, q_values in feature.qualifiers.items():
                
                if len(q_values) > 1:
                    if q_name == "tagset_id":
                        msg = "Duplicate tagset_id value."
                        res = self.feature_result(record, feature, msg, level="error", qualifier=q_name)
                        res["rule"] = "ANN0880"
                        results.append(res)
                    else:
                        msg = "Duplicate ST_COMMENT qualifier."
                        res = self.feature_result(record, feature, msg, level="error", qualifier=q_name)
                        res["rule"] = "ANN0900"
                        results.append(res)
                
                if len(q_name) > 64:
                    msg = "Qualifier name length exceeds 64 characters."
                    results.append(self.feature_result(record, feature, msg, level="error", qualifier=q_name))
                    
                for val in q_values:
                    val_str = str(val)
                    
                    if not val_str:
                        msg = "Missing value for ST_COMMENT qualifier."
                        res = self.feature_result(record, feature, msg, level="error", qualifier=q_name)
                        res["rule"] = "ANN0860"
                        results.append(res)
                        continue  
                    
                    max_len = 64 if q_name == "tagset_id" else 255
                    if len(val_str) > max_len:
                        msg = f"{self.description} (Length exceeds {max_len} characters)"
                        results.append(self.feature_result(record, feature, msg, level="error", qualifier=q_name))
                        
                    for forbidden in ["@@", "&&", "::"]:
                        if forbidden in val_str:
                            msg = f"{self.description} (Contains prohibited string '{forbidden}')"
                            results.append(self.feature_result(record, feature, msg, level="error", qualifier=q_name))
                            break  
                            
        return results
                
class ANN0940(BaseRule):
    rule_id = "ANN0940"
    alternate_id = "JP1029, ANN4029"
    target = "REFERENCE"
    description = 'The REFERENCE status "Published Only in Database" is not allowed for TPA.'
    requires_rdb = False
    is_file_level = True

    def validate_file(self, records, context, ann_path=None, seq_path=None):
        results = []
        if not context.is_tpa:
            return results

        for record in records.values():
            for feature in self.get_features(record, "REFERENCE"):
                if "status" in feature.qualifiers:
                    for status in feature.qualifiers["status"]:
                        if status == "Published Only in Database":
                            results.append(self.feature_result(record, feature, self.description, level="error", qualifier="status"))

        return results

class ANN1010(BaseRule):
    rule_id = "ANN1010"
    alternate_id = "BLP0009"
    target = "source"
    description = "Missing organism."
    requires_rdb = False
    is_file_level = True

    def validate_file(self, records, context):
        has_organism = False
        for record in records.values():
            for feature in self.get_features(record, "source"):
                if "organism" in feature.qualifiers:
                    has_organism = True
                    break
            if has_organism: break
                
        if not has_organism:
            return [self.format_result(entry_id="ALL", message=self.description, level="error")]
        return []

class ANN1020(BaseRule):
    rule_id = "ANN1020"
    alternate_id = "CMC0100"
    target = "source"
    description = "The organism name is not found in the Taxonomy database."
    requires_rdb = True
    is_file_level = True

    def validate_file(self, records, context):
        results = []
        checked = set()
        for record in records.values():
            for feature in self.get_features(record, "source"):
                if "organism" in feature.qualifiers:
                    for org in feature.qualifiers["organism"]:
                        org_clean = org.strip()
                        if org_clean not in checked:
                            checked.add(org_clean)
                            t_data = context.tax_data.get(org_clean, {"status": "not_found"})
                            if t_data["status"] == "not_found":
                                msg = f"{self.description} ('{org_clean}')"
                                results.append(self.feature_result(record, feature, msg, level="warning", qualifier="organism"))
        return results

class ANN1040(BaseRule):
    rule_id = "ANN1040"
    alternate_id = None
    target = "source"
    description = "Invalid taxonomic rank: The organism name must be at the species or infraspecific level."
    requires_rdb = True
    is_file_level = True

    def validate_file(self, records, context, ann_path=None, seq_path=None):
        results = []
        checked = set()
        for record in records.values():
            for feature in self.get_features(record, "source"):
                if "organism" in feature.qualifiers:
                    for org in feature.qualifiers["organism"]:
                        org_clean = org.strip()
                        if org_clean not in checked:
                            checked.add(org_clean)
                            t_data = context.tax_data.get(org_clean, {})
                            
                            if t_data.get("status") == "invalid_rank":
                                msg = f"{self.description} (Found: '{org_clean}', Rank: '{t_data.get('rank', 'unknown')}')"
                                results.append(self.feature_result(record, feature, msg, level="error", qualifier="organism"))
        return results        
        
class ANN1050(BaseRule):
    rule_id = "ANN1050"
    alternate_id = "ANN0323"
    target = "CDS"
    description = "The transl_table qualifier value (genetic code) mismatches with the Taxonomy database."
    requires_rdb = True

    def validate(self, record, context):
        results = []
        table_id = get_expected_transl_table(record, context.tax_data)

        warned_skip = False
        org_name = ""
        organelle = ""

        if table_id == 0:
            for feature in self.get_features(record, "source"):
                org_name = feature.qualifiers.get("organism", [""])[0]
                organelle = feature.qualifiers.get("organelle", [""])[0]
                break

        for feature in self.get_features(record, "CDS"):
            if table_id == 0:
                if not warned_skip:
                    if organelle:
                        msg = f"transl_table code was not found for the organism '{org_name}' and organelle '{organelle}' combination. Validations and autofix using transl_table were skipped."
                    else:
                        msg = f"transl_table code was not found for the organism '{org_name}'. Validations and autofix using transl_table were skipped."
                    
                    results.append(self.feature_result(record, feature, msg, level="warning", qualifier="transl_table"))
                    warned_skip = True
                continue 

            if "transl_table" in feature.qualifiers:
                try:
                    ann_table = int(feature.qualifiers["transl_table"][0])
                except ValueError:
                    continue
                
                if ann_table != table_id:
                    msg = f"{self.description} (Found: {ann_table}, Expected: {table_id})"
                    results.append(self.feature_result(record, feature, msg, level="error", qualifier="transl_table"))
        return results

class ANN1060(BaseRule):
    rule_id = "ANN1060"
    alternate_id = "JK"
    target = "metagenome_source"
    description = 'The metagenome_source qualifier value must be a valid scientific name ending with "metagenome" in the Taxonomy database.'
    requires_rdb = True
    is_file_level = False

    def validate(self, record, context):
        results = []
        for feature in self.get_features(record, "source"):
            if "metagenome_source" in feature.qualifiers:
                for val in feature.qualifiers["metagenome_source"]:
                    val_clean = val.strip()
                    t_data = context.tax_data.get(val_clean, {})
                    
                    is_scientific_name = t_data.get("status") == "valid" or (t_data.get("status") == "fixable" and t_data.get("type") == "case correction")
                    is_metagenome = t_data.get("scientific_name", "").lower().endswith("metagenome")
                    
                    if not (is_scientific_name and is_metagenome):
                        msg = f"{self.description} (Found: '{val_clean}')"
                        results.append(self.feature_result(record, feature, msg, level="error", qualifier="metagenome_source"))
        return results        

        
class ANN1100(BaseRule):
    rule_id = "ANN1100"
    alternate_id = "JK"
    target = "strain"
    description = "The strain qualifier is not permitted for environmental samples. Use isolate instead."
    requires_rdb = True
    is_file_level = False

    def validate(self, record, context):
        results = []
        for feature in self.get_features(record, "source"):
            if "strain" in feature.qualifiers:
                organisms = feature.qualifiers.get("organism", [])
                
                for org in organisms:
                    org_clean = org.strip()
                    t_data = context.tax_data.get(org_clean, {})
                    lineage = t_data.get("lineage", "").lower()
                    
                    # "uncultured" や "environmental" が名前に含まれているか、系統に含まれているかで判定
                    is_environmental = (
                        "unclassified entries" in lineage or 
                        "environmental samples" in lineage or 
                        "uncultured" in org_clean.lower() or
                        "environmental" in org_clean.lower()
                    )
                    
                    if is_environmental:
                        for strain_val in feature.qualifiers["strain"]:
                            msg = f"{self.description} (Organism: '{org_clean}', Strain: '{strain_val}')"
                            results.append(self.feature_result(record, feature, msg, level="error", qualifier="strain"))
                        # エラーを出したらこのfeatureの判定は終了してOK
                        break
                        
        return results        

        
class ANN1110(BaseRule):
    rule_id = "ANN1110"
    alternate_id = "JK"
    target = "strain"
    description = "The strain matches an institution code. Please add a culture_collection if the sample was obtained from the culture collection."
    requires_rdb = False
    is_file_level = True

    def validate_file(self, records, context):
        results = []
        if not context.institution_codes:
            return results

        # 機関コードを小文字でセット化
        inst_codes_lower = {str(code).lower() for code in context.institution_codes}

        for entry_id, record in records.items():
            for feature in self.get_features(record):
                # culture_collection が既にある場合はスキップ
                if "culture_collection" in feature.qualifiers:
                    continue
                    
                targets = []
                if "strain" in feature.qualifiers:
                    targets.extend([("strain", v) for v in feature.qualifiers["strain"]])

                for q_name, val in targets:
                    val_str = str(val).strip()
                    if not val_str:
                        continue
                        
                    # 数字・スペース・ハイフン・コロン等で分割し、先頭のアルファベット部分だけを抽出する
                    # NBRC100 -> nbrc, JCM 1234 -> jcm
                    match = re.match(r'^([a-zA-Z]+)', val_str)
                    if match:
                        first_word = match.group(1).lower()
                    else:
                        first_word = ""
                    
                    if first_word and first_word in inst_codes_lower:
                        res = self.feature_result(record, feature, self.description, level="warning", qualifier=q_name)
                        res["entry"] = getattr(feature, 'original_entry_id', entry_id)
                        results.append(res)
                        break # 1つのフィーチャーで1回エラーを出せばOK

        return results
        

class ANN1140(BaseRule):
    rule_id = "ANN1140"
    alternate_id = "V200"
    target = "source"
    description = "Source qualifiers (organism, strain, isolation_source, etc.) must be identical across all WGS entries."
    requires_rdb = False
    is_file_level = True

    def validate_file(self, records, context):
        results = []
        if not context.is_wgs:
            return results

        source_def = context.ddbj_dict.get("features", {}).get("source", {})
        target_qualifiers = set(source_def.get("sample_qualifiers", []))

        if not target_qualifiers:
            return results

        source_signatures = {}
        first_mismatch_feature = None

        for entry_id, record in records.items():
            if entry_id == "COMMON":
                continue
            
            for feature in self.get_features(record, "source"):
                extracted_qs = {}
                for q_key, q_vals in feature.qualifiers.items():
                    if q_key in target_qualifiers:
                        extracted_qs[q_key] = tuple(sorted([str(v).strip() for v in q_vals]))
                
                signature = tuple(sorted(extracted_qs.items()))
                
                if signature not in source_signatures:
                    source_signatures[signature] = []
                    if len(source_signatures) == 2:
                        first_mismatch_feature = feature
                        
                source_signatures[signature].append(entry_id)

        if len(source_signatures) > 1:
            sig_dicts = [dict(sig) for sig in source_signatures.keys()]
            differing_quals = []
            
            for q_key in target_qualifiers:
                vals = set(sig_dict.get(q_key, ()) for sig_dict in sig_dicts)
                if len(vals) > 1:
                    differing_quals.append(q_key)
            
            diff_str = ", ".join(sorted(differing_quals))
            msg = f"{self.description} (Found {len(source_signatures)} different qualifier sets. Differing qualifiers: {diff_str})"
            
            results.append(self.format_result(
                entry_id="ALL", message=msg, level="warning",
                feature_type="source", qualifier="ALL",
                line_number=getattr(first_mismatch_feature, 'line_number', None) if first_mismatch_feature else None,
                location=getattr(first_mismatch_feature, 'original_location', "") if first_mismatch_feature else ""
            ))

        return results
        
                                
class ANN1240(BaseRule):
    rule_id = "ANN1240"
    alternate_id = "BS_R0040"
    target = "collection_date"
    description = "Future collection date is not allowed."
    requires_rdb = False
    is_file_level = False

    def validate(self, record, context):
        results = []
        today = date.today()

        # collection_date は source 以外にも付く可能性があるため、全走査(get_features)
        for feature in self.get_features(record):
            if "collection_date" in feature.qualifiers:
                for val in feature.qualifiers["collection_date"]:
                    val_str = str(val)
                    
                    if not val_str or val_str.startswith("missing:") or "/" in val_str:
                        continue
                        
                    try:
                        clean_part = re.sub(r'[\s.,]+', '-', val_str)
                        dt = parser.parse(clean_part)
                        
                        has_time = 'T' in val_str.upper() or ':' in val_str
                        has_month_word = bool(re.search(r'[A-Za-z]{3,}', val_str))
                        digits = re.findall(r'\d+', val_str)
                        
                        comp_count = len(digits) + (1 if has_month_word else 0)
                        if has_time:
                            comp_count = 3 

                        is_future = False
                        
                        if comp_count == 1:
                            if dt.year > today.year:
                                is_future = True
                                
                        elif comp_count == 2:
                            if (dt.year, dt.month) > (today.year, today.month):
                                is_future = True
                                
                        elif comp_count >= 3:
                            if (dt.year, dt.month, dt.day) > (today.year, today.month, today.day):
                                is_future = True

                        if is_future:
                            msg = f"{self.description} (Found: '{val_str}')"
                            results.append(self.feature_result(record, feature, msg, level="error", qualifier="collection_date"))
                            
                    except Exception:
                        pass
                        
        return results


class ANN1250(BaseRule):
    rule_id = "ANN1250"
    alternate_id = "BS_R0008"
    target = "geo_loc_name"
    description = "Invalid country. Not in the country list."
    requires_rdb = False
    is_file_level = False

    def validate(self, record, context):
        results = []
        
        # missing_reporting_terms は厳密一致
        missing_reporting_terms = set(context.cv_terms.get("missing_reporting_terms", []))
        
        # 完全一致用のSetと、小文字から正しいCaseを引くためのマッピング辞書を作成
        exact_countries = context.cv_terms.get("countries", [])
        exact_countries_set = set(exact_countries)
        countries_lower_map = {c.lower(): c for c in exact_countries}

        for feature in self.get_features(record):
            if "geo_loc_name" in feature.qualifiers:
                for val in feature.qualifiers["geo_loc_name"]:
                    val_str = str(val)
                    if not val_str:
                        continue
                        
                    # missing_reporting_terms との照合
                    if val_str in missing_reporting_terms:
                        continue

                    # 国名部分の抽出（コロン以降も保持するために2分割）
                    parts = val_str.split(":", 1)
                    country_part = parts[0].strip()

                    # 1. まず完全一致（Case-sensitive）をチェック。一致すれば何もしない。
                    if country_part in exact_countries_set:
                        continue

                    # 2. 完全一致しなかった場合、Case-insensitiveで照合する
                    country_lower = country_part.lower()
                    if country_lower in countries_lower_map:
                        # マッチした場合は大文字小文字の間違い（Autofix対象）
                        correct_country = countries_lower_map[country_lower]
                        msg = f"{self.description} (Found: '{country_part}', Expected: '{correct_country}')"
                        res = self.feature_result(record, feature, msg, level="error", qualifier="geo_loc_name")
                        
                        # Autofix: 正しい国名に、もしコロン以降があればそれも結合して新しい値を生成
                        if len(parts) > 1:
                            new_val = f"{correct_country}:{parts[1]}"
                        else:
                            new_val = correct_country
                            
                        res["autofix"] = True
                        res["fix_target"] = "qualifier"
                        res["old_value"] = val_str
                        res["new_value"] = new_val
                        results.append(res)
                        
                    # 3. 全くマッチしない不正な国名の場合
                    else:
                        msg = f"{self.description} (Found: '{country_part}')"
                        results.append(self.feature_result(record, feature, msg, level="error", qualifier="geo_loc_name"))

        return results
                
        
class ANN1275(BaseRule):
    rule_id = "ANN1275"
    alternate_id = "BS_R0041"
    target = "source"
    description = "Values provided for 'lat_lon' and 'geo_loc_name' contradict each other."
    requires_rdb = False
    is_file_level = False

    def __init__(self):
        super().__init__()
        self._geo_cache = {}
        self.valid_land_names = None
        self.lat_lon_pattern = None 

    def _init_valid_land_names(self, context):
        names = set()
        for ne_name in context.geo_df['name'].values:
            if ne_name in context.geo_mapping:
                for mapped_name in context.geo_mapping[ne_name]:
                    names.add(mapped_name.lower())
            else:
                names.add(ne_name.lower())
        self.valid_land_names = names

    def validate(self, record, context):
        results = []
        if record.id == "COMMON" or getattr(context, 'geo_df', None) is None or getattr(context, 'geo_mapping', None) is None:
            return results

        if self.lat_lon_pattern is None:
            pattern_str = context.ddbj_dict.get("qualifiers", {}).get("lat_lon", {}).get("format_pattern")
            if pattern_str:
                self.lat_lon_pattern = re.compile(pattern_str)
            else:
                self.lat_lon_pattern = re.compile(r'^\d+(?:\.\d+)?\s+[NS]\s+\d+(?:\.\d+)?\s+[EW]$')

        if self.valid_land_names is None:
            self._init_valid_land_names(context)

        for feat in self.get_features(record, "source"):
            lat_lon_list = feat.qualifiers.get("lat_lon", [])
            geo_loc_list = feat.qualifiers.get("geo_loc_name", [])

            for lat_lon_str, geo_loc_str in zip(lat_lon_list, geo_loc_list):
                country_name = geo_loc_str.split(":")[0].strip()
                country_lower = country_name.lower()

                if country_lower not in self.valid_land_names:
                    continue

                cache_key = (lat_lon_str, country_lower)
                if cache_key in self._geo_cache:
                    is_valid, hit_names, dist_km = self._geo_cache[cache_key]
                    self._report_result(record, feat, lat_lon_str, country_name, is_valid, hit_names, dist_km, results)
                    continue

                parsed_coords = self._parse_lat_lon(lat_lon_str)
                if not parsed_coords:
                    continue

                lat, lon = parsed_coords
                pt = Point(lon, lat)

                # バッファ(約111km)で交差するポリゴンを検索
                matches_df = context.geo_df[context.geo_df.intersects(pt.buffer(1.0))]
                
                # 距離を含めた詳細チェック
                is_valid, hit_names, dist_km = self._check_matches(country_lower, matches_df, pt, context.geo_mapping)

                self._geo_cache[cache_key] = (is_valid, hit_names, dist_km)
                self._report_result(record, feat, lat_lon_str, country_name, is_valid, hit_names, dist_km, results)

        return results

    def _parse_lat_lon(self, lat_lon_str):
        clean_str = lat_lon_str
        if not self.lat_lon_pattern.match(clean_str): return None
        parts = clean_str.split()
        if len(parts) != 4: return None
        lat = float(parts[0]) * (-1 if parts[1] == 'S' else 1)
        lon = float(parts[2]) * (-1 if parts[3] == 'W' else 1)
        return lat, lon

    def _check_matches(self, country_lower, matches_df, pt, geo_mapping):
        hit_names = []
        matched_geometries = [] # 入力された国名に一致したポリゴン

        for idx, row in matches_df.iterrows():
            ne_name = row['name']
            geom = row['geometry']
            
            if ne_name in geo_mapping:
                allowed = [m.lower() for m in geo_mapping[ne_name]]
                hit_names.extend(geo_mapping[ne_name])
            else:
                allowed = [ne_name.lower()]
                hit_names.append(ne_name)
                
            if country_lower in allowed:
                matched_geometries.append(geom)
                
        is_valid = len(matched_geometries) > 0
        dist_km = 0.0

        if is_valid:
            # 一致した国のポリゴンと点との最短距離(度)を求め、kmに変換 (1度 ≒ 約111.13km)
            min_dist_deg = min([geom.distance(pt) for geom in matched_geometries])
            if min_dist_deg > 0:
                dist_km = round(min_dist_deg * 111.13, 1)

        return is_valid, hit_names, dist_km

    def _report_result(self, record, feat, lat_lon_str, country_name, is_valid, hit_names, dist_km, results):
        if not is_valid:
            # エラー時 (他国に落ちた or 完全に外海)
            unique_hits = sorted(list(set(hit_names)))
            actual_loc = ", ".join(unique_hits) if unique_hits else "Ocean/Unmapped area"
            msg = f"Values provided for 'lat_lon' ({lat_lon_str}) and 'geo_loc_name' ({country_name}) contradict each other. Coordinates point to: {actual_loc}"
            results.append(self.feature_result(record, feat, msg, level="warning"))
            
        elif dist_km >= 1.0:
            # 成功時：ただし海岸線から 1km 以上離れている場合 (地図の誤差等を考慮して1km未満は無視)
            msg = f"Coordinates ({lat_lon_str}) match '{country_name}' and located approximately {dist_km} km away from the nearest coastline."            
            results.append(self.feature_result(record, feat, msg, level="info"))
                    

class ANN1280(BaseRule):
    rule_id = "ANN1280"
    alternate_id = "BS_R0059"
    target = "sex"
    description = "Sex qualifier is not valid for prokaryotes."
    requires_rdb = True
    is_file_level = False

    def validate(self, record, context):
        results = []
        for feature in self.get_features(record, "source"):
            if "sex" in feature.qualifiers:
                organisms = feature.qualifiers.get("organism", [])
                
                for org in organisms:
                    org_clean = org.strip()
                    t_data = context.tax_data.get(org_clean, {})
                    lineage = t_data.get("lineage", "")
                    
                    if "Archaea" in lineage or "Bacteria" in lineage:
                        for sex_val in feature.qualifiers["sex"]:
                            msg = f"{self.description} (Organism: '{org_clean}', Sex: '{sex_val}')"
                            results.append(self.feature_result(record, feature, msg, level="warning", qualifier="sex"))
                        break
                        
        return results        
        
class ANN1290(BaseRule):
    rule_id = "ANN1290"
    alternate_id = "BS_R0107"
    target = "culture_collection"
    description = "Invalid institution code. Not in the institution code list."
    requires_rdb = False

    def validate(self, record, context):
        results = []
        for feature in self.get_features(record):
            if "culture_collection" in feature.qualifiers:
                for val in feature.qualifiers["culture_collection"]:
                    inst_code = val.split(':')[0].strip()
                    
                    if inst_code.lower() not in context.institution_codes:
                        msg = f"{self.description} ('{inst_code}' in '{val}')"
                        results.append(self.feature_result(record, feature, msg, level="error", qualifier="culture_collection"))
        return results

class ANN1320(BaseRule):
    rule_id = "ANN1320"
    alternate_id = "BS_R0115"
    target = "specimen_voucher"
    description = "Specimen voucher for prokaryotes and unclassified sequences."
    requires_rdb = True
    is_file_level = False

    def validate(self, record, context):
        results = []
        for feature in self.get_features(record, "source"):
            if "specimen_voucher" in feature.qualifiers:
                organisms = feature.qualifiers.get("organism", [])
                
                for org in organisms:
                    org_clean = org.strip()
                    t_data = context.tax_data.get(org_clean, {})
                    lineage = t_data.get("lineage", "")
                    
                    is_bacteria = "Bacteria" in lineage
                    is_archaea = "Archaea" in lineage
                    is_unclassified = "unclassified" in lineage.lower() or "unclassified" in org_clean.lower()
                    
                    if is_bacteria or is_archaea or is_unclassified:
                        for val in feature.qualifiers["specimen_voucher"]:
                            msg = f"{self.description} (Organism: '{org_clean}', Specimen voucher: '{val}')"
                            results.append(self.feature_result(record, feature, msg, level="error", qualifier="specimen_voucher"))
                        break
                        
        return results        
        
class ANN1330(BaseRule):
    rule_id = "ANN1330"
    alternate_id = "BS_R0116"
    target = "specimen_voucher"
    description = "Invalid specimen_voucher format."
    requires_rdb = False
    is_file_level = False

    def validate(self, record, context):
        results = []
        for feature in self.get_features(record):
            if "specimen_voucher" in feature.qualifiers:
                for val in feature.qualifiers["specimen_voucher"]:
                    val_str = str(val)
                    if not val_str:
                        continue
                        
                    parts = val_str.split(":")
                    is_invalid = False
                    
                    if parts[0].strip() == "personal":
                        if len(parts) != 3 or not parts[1].strip() or not parts[2].strip():
                            is_invalid = True
                    else:
                        if len(parts) > 3:
                            is_invalid = True
                            
                    if is_invalid:
                        msg = f"{self.description} (Found: '{val_str}')"
                        results.append(self.feature_result(record, feature, msg, level="error", qualifier="specimen_voucher"))
        return results        
        
class ANN1350(BaseRule):
    rule_id = "ANN1350"
    alternate_id = "BS_R0118"
    target = "bio_material"
    description = "Invalid bio_material format."
    requires_rdb = False
    is_file_level = False

    def validate(self, record, context):
        results = []
        for feature in self.get_features(record):
            if "bio_material" in feature.qualifiers:
                for val in feature.qualifiers["bio_material"]:
                    val_str = str(val)
                    if not val_str:
                        continue
                        
                    parts = val_str.split(":")
                    if len(parts) > 3:
                        msg = f"{self.description} (Found: '{val_str}')"
                        results.append(self.feature_result(record, feature, msg, level="error", qualifier="bio_material"))
        return results        
        
class ANN1365(BaseRule):
    rule_id = "ANN1365"
    alternate_id = "BS_R0062"
    target = "source"
    description = "Multiple voucher qualifiers (specimen_voucher, culture_collection or bio_material) detected with the same institution code. Only one value is allowed."
    requires_rdb = False
    is_file_level = False

    def validate(self, record, context):
        results = []
        target_quals = ["specimen_voucher", "culture_collection", "bio_material"]
        
        for feature in self.get_features(record):
            seen_inst_codes = set()
            duplicate_inst_codes = set()
            
            for qual_name in target_quals:
                if qual_name in feature.qualifiers:
                    for val in feature.qualifiers[qual_name]:
                        val_str = str(val)
                        if not val_str:
                            continue
                        
                        inst_code = val_str.split(":")[0].strip()
                        inst_code_lower = inst_code.lower()
                        
                        if inst_code_lower in seen_inst_codes:
                            duplicate_inst_codes.add(inst_code)
                        else:
                            seen_inst_codes.add(inst_code_lower)
            
            if duplicate_inst_codes:
                for dup_code in duplicate_inst_codes:
                    msg = f"{self.description} (Institution code: '{dup_code}')"
                    results.append(self.feature_result(record, feature, msg, level="warning"))
                    
        return results        
        
class ANN1410(BaseRule):
    rule_id = "ANN1410"
    alternate_id = "JK"
    target = "source"
    description = "Inconsistent sample qualifiers: The collection_date, geo_loc_name, and lat_lon values differ among entries with the same organism and strain/isolate."
    requires_rdb = False
    is_file_level = True

    def validate_file(self, records, context, ann_path=None, seq_path=None):
        results = []        
        groups = defaultdict(list)
        
        for entry_id, record in records.items():
            for feature in self.get_features(record, "source"):
                orgs = feature.qualifiers.get("organism", [])
                strains = feature.qualifiers.get("strain", [])
                isolates = feature.qualifiers.get("isolate", [])
                
                cd = tuple(feature.qualifiers.get("collection_date", []))
                gln = tuple(feature.qualifiers.get("geo_loc_name", []))
                ll = tuple(feature.qualifiers.get("lat_lon", []))
                
                for org in orgs:
                    for strain in strains:
                        groups[("strain", org, strain)].append((cd, gln, ll))
                    for isolate in isolates:
                        groups[("isolate", org, isolate)].append((cd, gln, ll))
                            
        for key, items in groups.items():
            type_name, org, val = key
            cds = set(item[0] for item in items)
            glns = set(item[1] for item in items)
            lls = set(item[2] for item in items)
            
            if len(cds) > 1 or len(glns) > 1 or len(lls) > 1:
                msg = f"{self.description} (organism: '{org}', {type_name}: '{val}')"
                results.append(self.format_result(
                    entry_id="ALL", message=msg, level="warning", feature_type="source"
                ))
        return results

class ANN1420(BaseRule):
    rule_id = "ANN1420"
    alternate_id = "JK"
    target = "source"
    description = "Inconsistent sample qualifiers: The collection_date, geo_loc_name, and lat_lon values differ among entries with the same organism and voucher."
    requires_rdb = False
    is_file_level = True

    def validate_file(self, records, context, ann_path=None, seq_path=None):
        results = []        
        groups = defaultdict(list)
        voucher_keys = ["culture_collection", "specimen_voucher", "bio_material"]
        
        for entry_id, record in records.items():
            for feature in self.get_features(record, "source"):
                orgs = feature.qualifiers.get("organism", [])
                
                cd = tuple(feature.qualifiers.get("collection_date", []))
                gln = tuple(feature.qualifiers.get("geo_loc_name", []))
                ll = tuple(feature.qualifiers.get("lat_lon", []))
                
                for org in orgs:
                    for v_key in voucher_keys:
                        for voucher in feature.qualifiers.get(v_key, []):
                            groups[(v_key, org, voucher)].append((cd, gln, ll))
                            
        for key, items in groups.items():
            v_key, org, voucher = key
            cds = set(item[0] for item in items)
            glns = set(item[1] for item in items)
            lls = set(item[2] for item in items)
            
            if len(cds) > 1 or len(glns) > 1 or len(lls) > 1:
                msg = f"{self.description} (organism: '{org}', {v_key}: '{voucher}')"
                results.append(self.format_result(
                    entry_id="ALL", message=msg, level="warning", feature_type="source"
                ))
        return results        
        
class ANN1580(BaseRule):
    rule_id = "ANN1580"
    alternate_id = "JP0041"
    target = "source"
    description = "A main source feature must cover the entire sequence without any partial descriptor."
    requires_rdb = False
    is_file_level = False

    def validate(self, record, context):
        results = []
        if record.id == "COMMON":
            return results

        seq_length = len(record.seq)
        if seq_length == 0:
            return results

        source_features = self.get_features(record, "source")
        
        # location が None になっているフィーチャー（パースエラー等）を事前に除外
        valid_sources = [f for f in source_features if f.location is not None]
        
        # 有効な source が一つも残らなかった場合はスキップ
        if not valid_sources:
            return results

        main_source = max(valid_sources, key=lambda f: len(f.location))
        
        start = int(main_source.location.start)
        end = int(main_source.location.end)
        
        orig_loc = getattr(main_source, 'original_location', "")
        loc_str = str(main_source.location)
        is_partial = "<" in orig_loc or ">" in orig_loc or "<" in loc_str or ">" in loc_str

        if start != 0 or end != seq_length or is_partial:
            msg = f"{self.description} (Sequence length: {seq_length}, Main source location: {start+1}..{end}"
            if is_partial:
                msg += ", contains partial operator"
            msg += ")"
            
            results.append(self.feature_result(record, main_source, msg, level="error"))

        return results


class ANN1620(BaseRule):
    rule_id = "ANN1620"
    alternate_id = "JP0053"
    target = "mol_type"
    description = "All source features must have the same 'mol_type' value."
    requires_rdb = False
    is_file_level = False

    def validate(self, record, context):
        results = []
        
        # エントリ内の全 source フィーチャーを取得
        source_features = self.get_features(record, "source")
        
        # source フィーチャーが2つ未満の場合はチェック不要
        if len(source_features) < 2:
            return results
            
        # 存在する mol_type の値を収集
        mol_types = set()
        for feat in source_features:
            if "mol_type" in feat.qualifiers:
                for val in feat.qualifiers["mol_type"]:
                    mol_types.add(val)
                    
        # 複数種類の mol_type が混在している場合はエラー
        if len(mol_types) > 1:
            found_str = "', '".join(sorted(mol_types))
            msg = f"{self.description} (Found: '{found_str}')"
            
            # 該当するすべての source フィーチャーのエラーとして報告
            for feat in source_features:
                if "mol_type" in feat.qualifiers:
                    results.append(self.feature_result(
                        record,
                        feat,
                        msg,
                        level="error",
                        qualifier="mol_type"
                    ))
                    
        return results
        
                        
class ANN1625(BaseRule):
    rule_id = "ANN1625"
    alternate_id = None
    target = "mol_type"
    description = "The rRNA or tRNA features are not permitted when mol_type is 'mRNA'."
    requires_rdb = False
    is_file_level = False

    def validate(self, record, context):
        results = []
        if record.id == "COMMON":
            return results

        # mol_type が mRNA かどうかを判定
        is_mrna = False
        for feature in self.get_features(record, "source"):
            mol_types = feature.qualifiers.get("mol_type", [])
            if any(m == "mRNA" for m in mol_types):
                is_mrna = True
                break

        if not is_mrna:
            return results

        # mol_type が mRNA の場合、rRNA または tRNA が存在するかチェック
        for f_type in ["rRNA", "tRNA"]:
            for feature in self.get_features(record, f_type):
                loc_str = getattr(feature, 'original_location', str(feature.location))
                msg = f"{self.description} (Found: {feature.type} at {loc_str})"
                
                results.append(self.feature_result(record, feature, msg, level="error"))

        return results
        
        
class ANN1626(BaseRule):
    rule_id = "ANN1626"
    alternate_id = None
    target = "mol_type"
    description = "The tRNA and CDS features are not permitted when the mol_type is 'rRNA'."
    requires_rdb = False
    is_file_level = False

    def validate(self, record, context):
        results = []
        if record.id == "COMMON":
            return results

        # mol_type が rRNA かどうかを判定
        is_rrna = False
        for feature in self.get_features(record, "source"):
            mol_types = feature.qualifiers.get("mol_type", [])
            if any(m == "rRNA" for m in mol_types):
                is_rrna = True
                break

        if not is_rrna:
            return results

        # mol_type が rRNA の場合、tRNA または CDS が存在するかチェック
        for f_type in ["tRNA", "CDS"]:
            for feature in self.get_features(record, f_type):
                msg = f"{self.description} (Found: {feature.type})"
                results.append(self.feature_result(record, feature, msg, level="error"))

        return results
        
class ANN1810(BaseRule):
    rule_id = "ANN1810"
    alternate_id = "JK"
    target = "clone"
    description = "The clone qualifier value is not unique within the ENV division entries."
    requires_rdb = False
    is_file_level = True

    def validate_file(self, records, context, ann_path=None, seq_path=None):
        results = []
        
        if "ENV" not in context.active_divisions:
            return results

        seen_clones = set()
        duplicate_clones = set()

        for entry_id, record in records.items():
            if entry_id == "COMMON": continue
            for feature in self.get_features(record, "source"):
                for clone in feature.qualifiers.get("clone", []):
                    clone_val = str(clone)
                    if not clone_val: continue
                    if clone_val in seen_clones:
                        duplicate_clones.add(clone_val)
                    else:
                        seen_clones.add(clone_val)

        if duplicate_clones:
            msg = f"{self.description} (Duplicates: {', '.join(sorted(duplicate_clones))})"
            results.append(self.format_result(
                entry_id="ALL", message=msg, level="error",
                feature_type="source", qualifier="clone"
            ))
            
        return results

class ANN1820(BaseRule):
    rule_id = "ANN1820"
    alternate_id = "JK"
    target = "submitter_seqid"
    description = "The submitter_seqid qualifier value must be unique within a set of WGS/TSA/TLS assembled sequences or CON records."
    requires_rdb = False
    is_file_level = True

    def validate_file(self, records, context, ann_path=None, seq_path=None):
        results = []
        
        is_target_type = (
            context.is_wgs or 
            context.is_tsa or 
            ("TLS" in context.active_datatypes) or 
            ("CON" in context.active_divisions)
        )

        if not is_target_type:
            return results

        seen_ids = set()
        duplicate_ids = set()

        for entry_id, record in records.items():
            if entry_id == "COMMON": continue
            for feature in self.get_features(record):
                for seqid in feature.qualifiers.get("submitter_seqid", []):
                    val = str(seqid)
                    if not val: continue
                    
                    if "@@[entry]@@" in val:
                        continue
                        
                    if val in seen_ids:
                        duplicate_ids.add(val)
                    else:
                        seen_ids.add(val)

        if duplicate_ids:
            msg = f"{self.description} (Duplicates: {', '.join(sorted(duplicate_ids))})"
            results.append(self.format_result(
                entry_id="ALL", message=msg, level="error",
                feature_type="ALL", qualifier="submitter_seqid"
            ))
            
        return results

class ANN1830(BaseRule):
    rule_id = "ANN1830"
    alternate_id = None
    target = "submitter_seqid"
    description = "Invalid submitter_seqid qualifier value format"
    requires_rdb = False
    is_file_level = False

    def validate(self, record, context):
        results = []
        
        if record.id == "COMMON":
            return results

        invalid_chars = set(' >[]|"')

        for feature in self.get_features(record):
            for seqid in feature.qualifiers.get("submitter_seqid", []):
                val = str(seqid)
                
                if "@@[entry]@@" in val:
                    val = val.replace("@@[entry]@@", record.id)
                
                errors = []
                
                if len(val) >= 51:
                    errors.append(f"length {len(val)} must be < 51 characters")
                    
                found_invalid = [c for c in val if c in invalid_chars]
                if found_invalid:
                    bad_chars_str = "".join(sorted(set(found_invalid)))
                    errors.append(f"contains invalid characters: '{bad_chars_str}'")
                    
                if errors:
                    msg = f"{self.description} - '{val}' ({', '.join(errors)})"
                    results.append(self.feature_result(record, feature, msg, level="error", qualifier="submitter_seqid"))
                    
        return results

        
class ANN2010(BaseRule):
    rule_id = "ANN2010"
    alternate_id = "JP0025"
    target = "file"
    description = "Location is missing."
    requires_rdb = False
    is_file_level = True

    NO_LOCATION_FEATURES = {
        "SUBMITTER", "REFERENCE", "COMMENT", "ST_COMMENT", 
        "DATATYPE", "KEYWORD", "DBLINK", "DIVISION", 
        "DATE", "TOPOLOGY", "PRIMARY_CONTIG", "SUBCONTACT", 
        "CONTIG", "ACCESSION", "ORGANISM", "VERSION", "ENTRY_STATUS"
    }

    # 引数に ann_lines=None を追加
    def validate_file(self, records, context, ann_path=None, seq_path=None, ann_lines=None):
        results = []
        if not ann_path and ann_lines is None:
            return results

        current_entry = None

        try:
            # メモリ上のデータ(ann_lines)があればそれを使い、なければファイルを読む (errors='replace' を指定)
            lines_to_process = ann_lines
            if lines_to_process is None:
                with open(ann_path, "r", encoding="utf-8", errors="replace") as f:
                    lines_to_process = f.readlines()

            for line_num_0, line in enumerate(lines_to_process):
                line_num = line_num_0 + 1
                clean_line = line.rstrip("\r\n")
                
                if not clean_line or clean_line.isspace() or clean_line.startswith("#"):
                    continue

                cols = clean_line.split("\t")
                if len(cols) < 3:
                    continue 

                entry_col = cols[0].strip()
                feature_col = cols[1].strip()
                location_col = cols[2].strip()

                if entry_col:
                    current_entry = entry_col

                if feature_col:
                    if feature_col not in self.NO_LOCATION_FEATURES:
                        if not location_col:
                            msg = f"{self.description} (for feature '{feature_col}')"
                            res = self.format_result(
                                entry_id=current_entry or "UNKNOWN", 
                                message=msg, 
                                level="fatal", 
                                feature_type=feature_col, 
                                line_number=line_num
                            )
                            res["rule"] = self.rule_id
                            res["target"] = "file"
                            results.append(res)
                            
        except Exception as e:
            print(f"[WARN] Failed to read ANN for {self.rule_id} check: {e}")

        return results
        
                
class ANN2030(BaseRule):
    rule_id = "ANN2030"
    alternate_id = "JP0123"
    target = "location"
    description = "Invalid character(s) in the location value."
    requires_rdb = False
    is_file_level = False

    def validate(self, record, context):
        results = []
        if record.id == "COMMON": return results
        
        for feature in self.get_features(record):
            loc_str = getattr(feature, 'original_location', "")
            if not loc_str: continue
            
            if loc_str in ("1..E", "<1..>E", "<1..E", "1..>E"):
                continue
            
            clean_loc = re.sub(r'\b(complement|join|order)\b', '', loc_str)
            clean_loc = re.sub(r'[A-Z0-9_.]+:', '', clean_loc)
            invalid_chars = re.findall(r'[^0-9.,<>^():]', clean_loc)
            
            if invalid_chars:
                bad_chars = "".join(sorted(set(invalid_chars)))
                msg = f"{self.description} (Found: '{bad_chars}' in '{loc_str}')"
                results.append(self.feature_result(record, feature, msg, level="error"))
                
        return results

class ANN2100(BaseRule):
    rule_id = "ANN2100"
    alternate_id = "JP0081"
    target = "location"
    description = "Adjacent locations should be merged."
    requires_rdb = False
    is_file_level = False

    def validate(self, record, context):
        results = []
        if record.id == "COMMON": return results
        
        for feature in self.get_features(record):
            if feature.location and hasattr(feature.location, 'parts') and len(feature.location.parts) > 1:
                parts = feature.location.parts
                found_adjacent = False
                
                for i in range(len(parts)):
                    for j in range(i + 1, len(parts)):
                        p1, p2 = parts[i], parts[j]
                        if p1.strand == p2.strand and getattr(p1, 'ref', None) == getattr(p2, 'ref', None):
                            if int(p1.end) == int(p2.start) or int(p2.end) == int(p1.start):
                                found_adjacent = True
                                break
                    if found_adjacent: break
                    
                if found_adjacent:
                    msg = f"{self.description} (Found in: '{getattr(feature, 'original_location', '')}')"
                    results.append(self.feature_result(record, feature, msg, level="warning"))
        return results

        
class ANN2130(BaseRule):
    rule_id = "ANN2130"
    alternate_id = "JP0179"
    target = "location"
    description = "The unsure feature location exceeds 10 bases."
    requires_rdb = False

    def validate(self, record, context):
        results = []
        for feature in self.get_features(record, "unsure"):
            if feature.location and len(feature.location) > 10:
                length = len(feature.location)
                msg = f"{self.description} (Length: {length} bp)"
                results.append(self.feature_result(record, feature, msg, level="warning"))
        return results

        
class ANN2510(BaseRule):
    rule_id = "ANN2510"
    alternate_id = "SUBC0002, BLP0100"
    target = "feature"
    description = "Multiple locus tag prefixes."
    requires_rdb = False
    is_file_level = True

    def validate_file(self, records, context, ann_path=None, seq_path=None):
        prefixes = set()
        for entry_id, record in records.items():
            if entry_id == "COMMON": continue
            for feature in self.get_features(record):
                for tag in feature.qualifiers.get("locus_tag", []):
                    prefix = tag.split('_')[0] if '_' in tag else tag
                    prefixes.add(prefix)
                    
        if len(prefixes) > 1:
            msg = f"{self.description}: {', '.join(prefixes)}"
            return [self.format_result(entry_id="ALL", message=msg, level="warning")]
        return []

class ANN2520(BaseRule):
    rule_id = "ANN2520"
    alternate_id = "SUBC0003, SVP0150"
    target = "feature"
    description = "Duplicate locus tag."
    requires_rdb = False
    is_file_level = True 

    def validate_file(self, records, context):
        results = []
        
        # locus_tag とそれが現れた feature を紐づける辞書
        # 形式: {"LTP_0001": [(record1, feature1), (record8, feature8), ...]}
        tag_registry = {}

        # ファイル内の全レコードを走査
        for record_id, record in records.items():
            if record_id == "COMMON": 
                continue
                
            # 各レコードの features_by_locus_tag から収集
            index = getattr(record, 'features_by_locus_tag', {})
            for tag, features in index.items():
                if tag not in tag_registry:
                    tag_registry[tag] = []
                
                # そのタグを持つ feature をレコード情報と共に記録
                for f in features:
                    tag_registry[tag].append((record, f))

        # 収集した結果、複数回出現した tag をエラーとする
        for tag, occurrences in tag_registry.items():
            if len(occurrences) > 1:
                # 複数ある場合は、それぞれに対して警告を出す
                for rec, feat in occurrences:
                    msg = f"{self.description} ('{tag}')"
                    results.append(self.feature_result(rec, feat, msg, level="warning", qualifier="locus_tag"))
                    
        return results
        

class ANN2530(BaseRule):
    rule_id = "ANN2530"
    alternate_id = "BLP0021"
    target = "feature"
    description = "Missing locus_tag."
    requires_rdb = False
    is_file_level = False

    def validate(self, record, context):
        # WGS または GNM に限定
        target_datatypes = {"WGS", "GNM"}
        if not target_datatypes.intersection(context.active_datatypes):
            return []

        if record.id == "COMMON": 
            return []

        results = []
        target_types = ["CDS", "mRNA", "tRNA", "rRNA"]
        
        for f_type in target_types:
            for feature in self.get_features(record, f_type):
                if "locus_tag" not in feature.qualifiers:
                    # locus_tag がないフィーチャーを見つけたら個別にエラーを出す
                    results.append(self.feature_result(
                        record, feature, self.description, level="warning"
                    ))
                    
        return results
                

class ANN2540(BaseRule):
    rule_id = "ANN2540"
    alternate_id = "BS_R0099"
    target = "locus_tag"
    description = "Invalid locus tag prefix format."
    requires_rdb = False
    is_file_level = False

    def validate(self, record, context):
        results = []
        if record.id == "COMMON": return results
        
        acc_pattern = re.compile(r'^[A-Z]{2}\d{6}(?:\.\d+)?$')
        
        for feature in self.get_features(record):
            for tag in feature.qualifiers.get("locus_tag", []):
                tag_str = str(tag)
                
                parts = tag_str.split('_', 1)
                prefix = parts[0]
                suffix = parts[1] if len(parts) > 1 else ""
                
                errors = []
                
                if '.' in tag_str:
                    errors.append(f"Version-like decimal notation is not allowed. (Found: '{tag_str}')")

                if acc_pattern.match(tag_str) or acc_pattern.match(prefix) or (suffix and acc_pattern.match(suffix)):
                    errors.append(f"Accession-like format (<2 letters><6 digits>) is not allowed. (Found: '{tag_str}')")
                
                is_valid_prefix = (
                    3 <= len(prefix) <= 12 and
                    prefix.isalnum() and
                    prefix[0].isalpha()
                )
                if not is_valid_prefix:
                    errors.append(f"Prefix must be 3-12 alphanumeric characters starting with a letter. (Prefix: '{prefix}')")

                for err_reason in errors:
                    msg = f"{self.description} {err_reason}"
                    results.append(self.feature_result(record, feature, msg, level="error", qualifier="locus_tag"))
                    
        return results               


class ANN2542(BaseRule):
    rule_id = "ANN2542"
    alternate_id = "V200"
    target = "locus_tag"
    description = "Duplicate locus_tag across features with different gene qualifiers."
    requires_rdb = False
    is_file_level = True

    TARGET_FEATURES = {
        "CDS", "3'UTR", "5'UTR", "exon", "intron", "mRNA", "ncRNA", 
        "precursor_RNA", "rRNA", "tmRNA", "tRNA", "misc_RNA", "misc_feature"
    }

    def validate_file(self, records, context, ann_path=None, seq_path=None):
        results = []
        locus_tag_map = {}

        for entry_id, record in records.items():
            if entry_id == "COMMON": continue
            
            index = getattr(record, 'features_by_locus_tag', {})
            for tag_str, features in index.items():
                if tag_str not in locus_tag_map:
                    locus_tag_map[tag_str] = []
                    
                for feature in features:
                    if feature.type in self.TARGET_FEATURES:
                        genes = frozenset(feature.qualifiers.get("gene", []))
                        locus_tag_map[tag_str].append({
                            "entry": entry_id,
                            "feature_type": feature.type,
                            "genes": genes
                        })
        
        for tag, occurrences in locus_tag_map.items():
            if len(occurrences) > 1:
                non_empty_gene_sets = {occ["genes"] for occ in occurrences if occ["genes"]}
                
                if len(non_empty_gene_sets) > 1:
                    conflict_genes = [list(g) for g in non_empty_gene_sets]
                    msg = f"{self.description} (locus_tag: '{tag}', Conflicting genes: {conflict_genes})"
                    
                    results.append(self.format_result(
                        entry_id="ALL", 
                        message=msg, 
                        level="error",
                        feature_type="ALL", 
                        qualifier="locus_tag"
                    ))
                    
        return results
        
class ANN2544(BaseRule):
    rule_id = "ANN2544"
    alternate_id = "V200"
    target = "locus_tag"
    description = "Different locus tag digit."
    requires_rdb = False
    is_file_level = True

    def validate_file(self, records, context, ann_path=None, seq_path=None):
        results = []
        prefix_digits = {}

        for entry_id, record in records.items():
            if entry_id == "COMMON": continue
            for feature in self.get_features(record):
                for tag in feature.qualifiers.get("locus_tag", []):
                    tag_str = str(tag)
                    
                    if '_' in tag_str:
                        prefix, suffix = tag_str.split('_', 1)
                        
                        match = re.search(r'(\d+)', suffix)
                        if match:
                            digit_part = match.group(1)
                            digit_len = len(digit_part)
                            
                            if prefix not in prefix_digits:
                                prefix_digits[prefix] = set()
                            
                            prefix_digits[prefix].add(digit_len)
        
        for prefix, lengths in prefix_digits.items():
            if len(lengths) > 1:
                sorted_lengths = sorted(list(lengths))
                msg = f"{self.description} (Prefix: '{prefix}', Found digits: {sorted_lengths})"
                
                results.append(self.format_result(
                    entry_id="ALL", 
                    message=msg, 
                    level="warning",
                    feature_type="ALL", 
                    qualifier="locus_tag"
                ))
                
        return results

class ANN2545(BaseRule):
    rule_id = "ANN2545"
    alternate_id = "V200"
    target = "locus_tag"
    description = "DFAST-generated default 'LOCUS' detected. Please review and correct the tags."
    requires_rdb = False
    is_file_level = False

    def validate(self, record, context):
        results = []
        if record.id == "COMMON": return results
        
        for feature in self.get_features(record):
            for tag in feature.qualifiers.get("locus_tag", []):
                prefix = str(tag).split('_')[0] if '_' in str(tag) else str(tag)
                if prefix == "LOCUS":
                    msg = f"{self.description} (Found: '{tag}')"
                    res = self.feature_result(record, feature, msg, level="warning", qualifier="locus_tag")
                    res["feature_type"] = "feature" 
                    results.append(res)
                    
        return results
                
class ANN2555(BaseRule):
    rule_id = "ANN2555"
    alternate_id = "SVP0200"
    target = "feature"
    description = "Number mismatch between CDS (or misc_feature) and mRNA."
    requires_rdb = False

    def validate(self, record, context):
        results = []
        counts_by_locus = defaultdict(lambda: {"CDS": 0, "mRNA": 0})
        
        for feature in self.get_features(record, "mRNA"):
            for locus_tag in feature.qualifiers.get("locus_tag", []):
                counts_by_locus[locus_tag]["mRNA"] += 1
                
        for feature in self.get_features(record, "CDS"):
            for locus_tag in feature.qualifiers.get("locus_tag", []):
                counts_by_locus[locus_tag]["CDS"] += 1
                
        for feature in self.get_features(record, "misc_feature"):
            for locus_tag in feature.qualifiers.get("locus_tag", []):
                counts_by_locus[locus_tag]["CDS"] += 1
                    
        for locus_tag, counts in counts_by_locus.items():
            if counts["CDS"] > 0 and counts["mRNA"] > 0 and counts["CDS"] != counts["mRNA"]:
                msg = f"{self.description} (locus_tag: '{locus_tag}', CDS/misc_feature count: {counts['CDS']}, mRNA count: {counts['mRNA']})"
                
                results.append(self.format_result(
                    entry_id=record.id, message=msg, level="warning", qualifier="locus_tag"
                ))
        return results
        
class ANN2560(BaseRule):
    rule_id = "ANN2560"
    alternate_id = "BLP0102"
    target = "feature"
    description = "Invalid chromosome name."
    requires_rdb = False
    is_file_level = True
    
    _valid_start_pattern = re.compile(r'^[A-Za-z0-9]')
    _zero_only_pattern = re.compile(r'^0+$')

    def validate_file(self, records, context, ann_path=None, seq_path=None):
        results = []
        ng_tax_strings = set()
        
        for record in records.values():
            for feature in self.get_features(record, "source"):
                for org in feature.qualifiers.get("organism", []):
                    org_clean = org.strip().lower()
                    if not org_clean: continue
                    ng_tax_strings.add(org_clean)
                    parts = org_clean.split()
                    if len(parts) >= 1: ng_tax_strings.add(parts[0])
                    if len(parts) >= 2: ng_tax_strings.add(parts[1])

        ng_contains = ["plasmid", "chromosome", "linkage group", "chr", "chrm", "chrom", "linkage-group", "linkage_group"]
        ng_exacts = {"un", "unk", "unknown", "na"}

        for entry_id, record in records.items():
            for feature in self.get_features(record):
                for val in feature.qualifiers.get("chromosome", []):
                    errors = []
                    v_lower = val.lower()
                    if not val: errors.append("must not be empty")
                    else:
                        if not self._valid_start_pattern.match(val): errors.append("must begin with a letter or number")
                        if len(val) > 32: errors.append("must not be longer than 32 characters")
                        if '\t' in val: errors.append("must not contain <tab>")
                        for ng_c in ng_contains:
                            if ng_c in v_lower:
                                errors.append(f"must not contain '{ng_c}'")
                                break
                        if v_lower in ng_exacts: errors.append(f"'{val}' is not allowed")
                        if self._zero_only_pattern.match(val): errors.append("characters consisting only of 0 are not allowed")
                        for tax_str in ng_tax_strings:
                            if tax_str in v_lower:
                                errors.append(f"must not contain taxname/genus/species '{tax_str}'")
                                break

                    if errors:
                        msg = f"{self.description} '{val}' ({', '.join(errors)})"
                        res = self.feature_result(record, feature, msg, level="warning", qualifier="chromosome")
                        res["entry"] = entry_id
                        results.append(res)
                        
        return results
        
class ANN2570(BaseRule):
    rule_id = "ANN2570"
    alternate_id = "BLP0103"
    target = "feature"
    description = "Invalid plasmid name."
    requires_rdb = False
    is_file_level = True

    def validate_file(self, records, context, ann_path=None, seq_path=None):
        results = []
        for entry_id, record in records.items():
            for feature in self.get_features(record):
                for val in feature.qualifiers.get("plasmid", []):
                    warnings = []
                    v_lower = val.lower()
                    if not val: warnings.append("must not be empty")
                    else:
                        if v_lower == "plasmid": warnings.append("'plasmid' is not allowed")
                        if "/" in val: warnings.append("must not contain a slash ('/')")
                        if not val.startswith("p") and v_lower != "megaplasmid":
                            warnings.append("should start with lowercase 'p'")

                    if warnings:
                        msg = f"{self.description} '{val}' ({', '.join(warnings)})"
                        res = self.feature_result(record, feature, msg, level="warning", qualifier="plasmid")
                        res["entry"] = entry_id 
                        results.append(res)
        return results

class ANN2580(BaseRule):
    rule_id = "ANN2580"
    alternate_id = "SVP0100"
    target = "feature"
    description = "Partial rRNA feature annotated by DFAST."
    requires_rdb = False

    def validate(self, record, context):
        results = []
        for feature in self.get_features(record, "rRNA"):
            aligned_qualifier = None
            for qual_name, values in feature.qualifiers.items():
                for val in values:
                    if "aligned only" in val:
                        aligned_qualifier = qual_name
                        break
                if aligned_qualifier: break
            
            if aligned_qualifier:
                loc_str = str(feature.location)
                if "<" not in loc_str and ">" not in loc_str:
                    results.append(self.feature_result(
                        record, feature, self.description, level="warning", qualifier=aligned_qualifier
                    ))
        return results

class ANN2590(BaseRule):
    rule_id = "ANN2590"
    alternate_id = "CMC0300"
    target = "feature"
    description = "Complement CDS/mRNA/tRNA/rRNA features in TSA."
    requires_rdb = False

    def validate(self, record, context):
        results = []
        
        if not context.is_tsa and "TSA" not in context.active_divisions:
            return results

        target_types = ["CDS", "mRNA", "tRNA", "rRNA"]
        for f_type in target_types:
            for feature in self.get_features(record, f_type):
                loc_str = getattr(feature, "original_location", "")
                if "complement" in loc_str:
                    results.append(self.feature_result(record, feature, self.description, level="warning"))
        return results

class ANN2594(BaseRule):
    rule_id = "ANN2594"
    alternate_id = "V200"
    target = "feature"
    description = "Multiple CDS features are not permitted in TSA entries."
    requires_rdb = False
    is_file_level = True

    def validate_file(self, records, context, ann_path=None, seq_path=None):
        results = []
        
        if not context.is_tsa:
            return results
            
        for entry_id, record in records.items():
            if entry_id == "COMMON":
                continue
                
            cds_features = self.get_features(record, "CDS")
            
            if len(cds_features) > 1:
                results.append(self.format_result(
                    entry_id=entry_id, 
                    message=self.description, 
                    level="error",
                    feature_type="CDS"
                ))
                
        return results
        
        
class ANN2600(BaseRule):
    rule_id = "ANN2600"
    alternate_id = "SEQ0160"
    target = "feature"
    description = "Unexpected rRNA length."
    requires_rdb = False

    def validate(self, record, context):
        results = []
        # JSONから rRNA の長さルールのリストを取得
        rules = context.ddbj_dict.get("features", {}).get("rRNA", {}).get("expected_sequence_lengths", [])
        
        if not rules:
            return results

        for feature in self.get_features(record, "rRNA"):
            loc_str = getattr(feature, 'original_location', str(feature.location))
            # 不完全なLocationは長さチェックをスキップ
            if "<" in loc_str or ">" in loc_str:
                continue

            products = feature.qualifiers.get("product", [])
            product_str = " ".join(products)

            for rule in rules:
                target_product = rule.get("product")
                # product に "16S" などが含まれているか判定
                if target_product and target_product in product_str:
                    bounds = rule.get("bounds", {})
                    min_len = bounds.get("min")
                    max_len = bounds.get("max")
                    length = len(feature.location)

                    if (min_len is not None and length < min_len) or \
                       (max_len is not None and length > max_len):
                        msg = f"{self.description} ({target_product}: {length} bp, expected: {min_len}-{max_len} bp)"
                        results.append(self.feature_result(record, feature, msg, level="warning"))
                    
                    # 一致するサブタイプが見つかったら、他のルールはチェックせずに抜ける
                    break 

        return results


class ANN2610(BaseRule):
    rule_id = "ANN2610"
    alternate_id = "SEQ0161"
    target = "feature"
    description = "Unexpected tRNA length."
    requires_rdb = False

    def validate(self, record, context):
        results = []
        rules = context.ddbj_dict.get("features", {}).get("tRNA", {}).get("expected_sequence_lengths", [])
        if not rules:
            return results
        
        # tRNA は条件なしで全体適用のため、リストの最初の要素を取得
        bounds = rules[0].get("bounds", {})
        min_len = bounds.get("min")
        max_len = bounds.get("max")

        for feature in self.get_features(record, "tRNA"):
            length = len(feature.location)
            if (min_len is not None and length < min_len) or (max_len is not None and length > max_len):
                msg = f"{self.description} ({length} bp, expected: {min_len}-{max_len} bp)"
                results.append(self.feature_result(record, feature, msg, level="warning"))
        
        return results


class ANN2620(BaseRule):
    rule_id = "ANN2620"
    alternate_id = "SEQ0162"
    target = "feature"
    description = "Unexpected tmRNA length."
    requires_rdb = False

    def validate(self, record, context):
        results = []
        rules = context.ddbj_dict.get("features", {}).get("tmRNA", {}).get("expected_sequence_lengths", [])
        if not rules:
            return results
            
        bounds = rules[0].get("bounds", {})
        min_len = bounds.get("min")
        max_len = bounds.get("max")

        for feature in self.get_features(record, "tmRNA"):
            length = len(feature.location)
            if (min_len is not None and length < min_len) or (max_len is not None and length > max_len):
                msg = f"{self.description} ({length} bp, expected: {min_len}-{max_len} bp)"
                results.append(self.feature_result(record, feature, msg, level="warning"))
        
        return results


class ANN2625(BaseRule):
    rule_id = "ANN2625"
    alternate_id = "GENBANK_SHORT_LNCRNA"
    target = "ncRNA"
    description = "Unexpected lncRNA length."
    requires_rdb = False

    def validate(self, record, context):
        results = []
        rules = context.ddbj_dict.get("features", {}).get("ncRNA", {}).get("expected_sequence_lengths", [])
        
        # lncRNA 向けのルールを JSON から特定する
        lncrna_rule = next((r for r in rules if r.get("if_qualifier") == "ncRNA_class" and r.get("has_value") == "lncRNA"), None)
        if not lncrna_rule:
            return results

        bounds = lncrna_rule.get("bounds", {})
        min_len = bounds.get("min")

        for feature in self.get_features(record, "ncRNA"):
            ncrna_classes = feature.qualifiers.get("ncRNA_class", [])
            
            if "lncRNA" in ncrna_classes:
                if not feature.location:
                    continue
                    
                length = len(feature.location)
                
                # min_len を下回る場合に警告
                if min_len is not None and length < min_len:
                    # JSONの min_len から -1 して、メッセージ用の ">200" を動的に生成
                    msg = f"{self.description} ({length} bp, expected: >{min_len - 1} bp)"
                    results.append(self.feature_result(record, feature, msg, level="warning"))
                    
        return results
        
        
class ANN2630(BaseRule):
    rule_id = "ANN2630"
    alternate_id = "FFmaker"
    target = "feature"
    description = "Entry must contain at least one feature in addition to the source feature except EST."
    requires_rdb = False
    is_file_level = True

    def validate_file(self, records, context, ann_path=None, seq_path=None):
        results = []

        if context.is_est:
            return results

        raw_metadata_fields = context.ddbj_dict.get("metadata_fields", [])
        metadata_features = {m for m in raw_metadata_fields}

        for entry_id, record in records.items():
            if entry_id == "COMMON":
                continue

            has_biological_feature = False
            for feature in self.get_features(record):
                f_type = feature.type
                
                if f_type != "source" and f_type not in metadata_features:
                    has_biological_feature = True
                    break
            
            if not has_biological_feature:
                results.append(self.format_result(
                    entry_id=entry_id,
                    message=self.description,
                    level="warning",
                    feature_type="feature"
                ))

        return results

class ANN2660(BaseRule):
    rule_id = "ANN2660"
    alternate_id = "JP0026"
    target = "feature"
    description = "[#FEATURE NAME] feature cannot be used."
    requires_rdb = False
    is_file_level = False

    def validate(self, record, context):
        results = []
        prohibited = set(context.ddbj_dict.get("prohibited_features", []))
        
        for feature in self.get_features(record):
            if feature.type in prohibited:
                msg = f"'{feature.type}' feature cannot be used."
                results.append(self.feature_result(record, feature, msg, level="error"))
        return results

class ANN2661(BaseRule):
    rule_id = "ANN2661"
    alternate_id = "JP0026"
    target = "feature"
    description = "[#FEATURE NAME] feature is not defined."
    requires_rdb = False
    is_file_level = False

    def validate(self, record, context):
        results = []        
        defined_features = set(context.ddbj_dict.get("features", {}).keys())
        
        for feature in self.get_features(record):
            # 未定義のフィーチャー名が使われている場合
            if feature.type not in defined_features:
                msg = f"'{feature.type}' feature is not defined."
                results.append(self.feature_result(record, feature, msg, level="error"))
        return results
        
class ANN2670(BaseRule):
    rule_id = "ANN2670"
    alternate_id = "JP0167"
    target = "feature"
    description = "The [{name}] {type} exists."
    requires_rdb = False

    def validate(self, record, context):
        results = []
        discouraged_features = set(context.ddbj_dict.get("discouraged_features", []))
        discouraged_qualifiers = set(context.ddbj_dict.get("discouraged_qualifiers", []))
        
        for feature in self.get_features(record):
            f_type = feature.type
            
            if f_type in discouraged_features:
                msg = f"The '{f_type}' feature exists."
                res = self.feature_result(record, feature, msg, level="info")
                res["target"] = "feature"
                res["rule"] = self.rule_id
                results.append(res)
                
            for q_name in feature.qualifiers:
                if q_name in discouraged_qualifiers:
                    msg = f"The '{q_name}' qualifier exists."
                    res = self.feature_result(record, feature, msg, level="info", qualifier=q_name)
                    res["target"] = "qualifier"
                    res["rule"] = self.rule_id
                    results.append(res)
                    
        return results
        
        
class ANN2680(BaseRule):
    rule_id = "ANN2680"
    alternate_id = "JP0080"
    target = "feature"
    description = "Identical {f_type} feature and location."
    requires_rdb = False

    def validate(self, record, context):
        results = []
        if record.id == "COMMON": 
            return results
        
        seen_features = set()
        
        for feature in self.get_features(record):
            f_type = feature.type
            loc_str = getattr(feature, 'original_location', "")
            
            if not loc_str:
                continue
            
            feat_key = (f_type, loc_str)
            
            if feat_key in seen_features:
                msg = f"Identical {f_type} feature and location."
                results.append(self.feature_result(record, feature, msg, level="warning"))
            else:
                seen_features.add(feat_key)
                
        return results


class ANTICODON_VALIDATOR(BaseRule):
    rule_id = "ANTICODON_MASTER"
    target = "anticodon"
    description = "Validate anticodon qualifier values (aa, seq, pos, range, translation)."
    requires_rdb = False
    is_file_level = False

    def __init__(self, cv_terms=None, tax_data=None):
        self.extract_pattern = re.compile(
            r'^\(\s*pos:(.+?)\s*,\s*aa:([a-zA-Z]+)(?:\s*,\s*seq:([a-zA-Z]+))?\s*\)$'
        )
        # 下の ANN2720 で使われている seq_pattern もここで定義しておく
        self.seq_pattern = re.compile(r'^[acgt]{3}$')
        
    def validate(self, record, context):
        results = []
        transl_table_id = get_expected_transl_table(record, context.tax_data) or 1
        
        amino_acids = context.cv_terms.get("amino_acids", {}) if context.cv_terms else {}
        aa_lower_map = {k.lower(): k for k in amino_acids.keys()}
        code_to_aa = {v.get("code"): k for k, v in amino_acids.items() if v.get("code")}
        code_to_aa["*"] = "Ter"
        code_to_aa["X"] = "Xaa"

        for feature in self.get_features(record, "tRNA"):
            if "anticodon" in feature.qualifiers:
                trna_seq = feature.extract(record.seq)
                trna_len = len(trna_seq)

                for val in feature.qualifiers["anticodon"]:
                    val_str = str(val)

                    match = self.extract_pattern.match(val_str)
                    if not match:
                        continue

                    # seq_str は None になる可能性がある
                    pos_str, aa_str, seq_str = match.groups()

                    # --- ANN2710: アミノ酸の検証 ---
                    is_aa_valid = True
                    if aa_str not in amino_acids:
                        expected_aa = aa_lower_map.get(aa_str.lower())
                        if expected_aa:
                            msg = f"Invalid 'aa' value in the anticodon qualifier. Check character case (Expected: '{expected_aa}', Found: '{aa_str}')."
                        else:
                            msg = f"Invalid 'aa' value in the anticodon qualifier. It must be a valid amino acid abbreviation. (Found: '{aa_str}')"
                            
                        res = self.feature_result(record, feature, msg, level="error", qualifier="anticodon")
                        res["rule"] = "ANN2710"
                        results.append(res)
                        is_aa_valid = False

                    # --- ANN2730, ANN2740: pos のパースと範囲検証 ---
                    anticodon_loc = None
                    try:
                        # seq_length は元のゲノム長を渡す
                        anticodon_loc = _parse_location_string(pos_str, seq_length=len(record.seq))
                        
                        if anticodon_loc:
                            def get_bounds(loc):
                                if hasattr(loc, 'parts'):
                                    starts = [int(p.start) for p in loc.parts]
                                    ends = [int(p.end) for p in loc.parts]
                                    return min(starts), max(ends)
                                return int(loc.start), int(loc.end)

                            a_min, a_max = get_bounds(anticodon_loc)

                            # 絶対座標同士で比較する (0 や trna_len との比較はNG)
                            parent_start = int(feature.location.start)
                            parent_end = int(feature.location.end)
                            
                            if a_min < parent_start or a_max > parent_end:
                                msg = "The anticodon location is out of the parent tRNA feature range."
                                res = self.feature_result(record, feature, msg, level="error", qualifier="anticodon")
                                res["rule"] = "ANN2740"
                                results.append(res)
                                anticodon_loc = None 
                                
                    except (Exception):
                        msg = "Invalid 'pos' value in the anticodon qualifier. Could not parse as a valid location."
                        res = self.feature_result(record, feature, msg, level="error", qualifier="anticodon")
                        res["rule"] = "ANN2730"
                        results.append(res)

                    # --- posから実際の配列を切り出す ---
                    is_seq_valid = True
                    actual_seq_str = None
                    
                    if anticodon_loc:
                        # 切り出し済みの trna_seq ではなく、大元のゲノム record.seq から切り出す
                        actual_ac_seq = anticodon_loc.extract(record.seq)
                        actual_seq_str = str(actual_ac_seq).lower()
                        
                    # --- ANN2720: seq が明記されている場合のみ検証 ---
                    if seq_str is not None:
                        if not self.seq_pattern.match(seq_str):
                            msg = "Invalid 'seq' value in the anticodon qualifier. It must be exactly 3 lowercase nucleotides (a, c, g, t)."
                            res = self.feature_result(record, feature, msg, level="error", qualifier="anticodon")
                            res["rule"] = "ANN2720"
                            results.append(res)
                            is_seq_valid = False
                            
                        elif actual_seq_str and actual_seq_str != seq_str:
                            msg = f"Invalid 'seq' value in the anticodon qualifier. It must be 3 nucleotides and match the corresponding tRNA bases. (Expected bases at pos: '{actual_seq_str}', Found: '{seq_str}')"
                            res = self.feature_result(record, feature, msg, level="error", qualifier="anticodon")
                            res["rule"] = "ANN2720"
                            results.append(res)
                            is_seq_valid = False

                    # --- ANN2715: アミノ酸翻訳チェック ---
                    if is_seq_valid and is_aa_valid:
                        # seq があればそれを、無ければ pos から切り出した配列を使う
                        target_seq = seq_str if seq_str else actual_seq_str
                        
                        if target_seq and len(target_seq) == 3:
                            try:
                                codon_seq = Seq(target_seq).reverse_complement()
                                translated_aa_code = str(codon_seq.translate(table=transl_table_id))
                                expected_aa_code = amino_acids[aa_str].get('code')
                                
                                if translated_aa_code != expected_aa_code:
                                    translated_aa_3letter = code_to_aa.get(translated_aa_code, translated_aa_code)
                                    
                                    msg = f"The translated amino acid from the anticodon sequence does not match the 'aa' value. (Value: '{aa_str}', Translated: '{translated_aa_3letter}')"
                                    res = self.feature_result(record, feature, msg, level="warning", qualifier="anticodon")
                                    res["rule"] = "ANN2715"
                                    results.append(res)
                            except Exception:
                                pass 

        return results


class ANN2750(BaseRule):
    rule_id = "ANN2750"
    target = "tRNA"
    description = "The strand of the 'anticodon' base position (pos) mismatch with the tRNA feature. Both must be on the same strand."
    requires_rdb = False
    is_file_level = False

    def validate(self, record, context):
        results = []
        if record.id == "COMMON":
            return results

        seq_len = len(record.seq)

        for feature in self.get_features(record, "tRNA"):
            loc = feature.location
            if not loc:
                continue

            anticodons = feature.qualifiers.get("anticodon", [])
            if not anticodons:
                continue

            parent_strand = loc.strand if loc.strand is not None else 1
            loc_str = getattr(feature, 'original_location', str(loc))

            for ac_val in anticodons:
                m = POS_PATTERN.search(ac_val)
                if not m:
                    continue
                
                pos_str = m.group(1).strip()
                try:
                    pos_loc = _parse_location_string(pos_str, seq_length=seq_len)
                    if not pos_loc:
                        continue
                    
                    pos_strand = pos_loc.strand if pos_loc.strand is not None else 1
                    
                    if parent_strand != pos_strand:
                        msg = f"{self.description} (tRNA location: '{loc_str}', anticodon pos: '{pos_str}')"
                        res = self.feature_result(record, feature, msg, level="error", qualifier="anticodon")
                        res["target"] = self.target
                        results.append(res)
                except Exception:
                    pass

        return results


class ANN3020(BaseRule):
    rule_id = "ANN3020"
    alternate_id = "JP0027"
    target = "qualifier"
    description = "[#QUALIFIER NAME] qualifier cannot be used."
    requires_rdb = False
    is_file_level = False

    def validate(self, record, context):
        results = []
        prohibited = set(context.ddbj_dict.get("prohibited_qualifiers", []))
        
        for feature in self.get_features(record):
            for q_name in feature.qualifiers:
                if q_name in prohibited:
                    msg = f"'{q_name}' qualifier cannot be used."
                    res = self.feature_result(record, feature, msg, level="error", qualifier=q_name)
                    res["target"] = feature.type
                    results.append(res)
        return results

class ANN3021(BaseRule):
    rule_id = "ANN3021"
    alternate_id = "JP0167"
    target = "qualifier"
    description = "[#QUALIFIER NAME] qualifier is not defined."
    requires_rdb = False
    is_file_level = False

    def validate(self, record, context):
        results = []        
        defined_qualifiers = set(context.ddbj_dict.get("qualifiers", {}).keys())
        
        for feature in self.get_features(record):
            for q_name in feature.qualifiers:
                # 未定義のQualifier名が使われている場合
                if q_name not in defined_qualifiers:
                    msg = f"'{q_name}' qualifier is not defined."
                    res = self.feature_result(record, feature, msg, level="error", qualifier=q_name)
                    # target を feature.type に上書き
                    res["target"] = feature.type
                    results.append(res)
        return results

class ANN3170(BaseRule):
    rule_id = "ANN3170"
    alternate_id = "JP0085"
    target = "qualifier"
    description = "No qualifier found after the location column."
    requires_rdb = False

    def validate(self, record, context):
        results = []
        if record.id == "COMMON":
            return results

        for feature in self.get_features(record):
            if not getattr(feature, 'has_qualifier_on_first_line', True):
                msg = "No qualifier found after the location column."
                results.append(self.feature_result(record, feature, msg, level="warning"))
        return results

class ANN3240(BaseRule):
    rule_id = "ANN3240"
    alternate_id = "JP0164"
    target = "qualifier"
    description = "The artificial_location qualifier is restricted to genome-scale annotations."
    requires_rdb = False
    is_file_level = True

    def validate_file(self, records, context, ann_path=None, seq_path=None):
        results = []
        
        is_genome_scale = (
            context.is_wgs or 
            context.is_tsa or 
            ("WGS" in context.active_divisions) or 
            ("TSA" in context.active_divisions)
        )

        if is_genome_scale:
            return results

        for entry_id, record in records.items():
            for feature in self.get_features(record):
                if "artificial_location" in feature.qualifiers:
                    res = self.feature_result(record, feature, self.description, level="error", qualifier="artificial_location")
                    res["entry"] = entry_id
                    results.append(res)

        return results
                
class ANN3260(BaseRule):
    rule_id = "ANN3260"
    alternate_id = "JP0169"
    target = "geo_loc_name"
    description = "Historical country name is used."
    requires_rdb = False
    is_file_level = False

    def validate(self, record, context):
        results = []
        historical_countries = {c.lower() for c in context.cv_terms.get("historical_countries", [])}
        
        for feature in self.get_features(record):
            if "geo_loc_name" in feature.qualifiers:
                for val in feature.qualifiers["geo_loc_name"]:
                    val_str = str(val)
                    if not val_str:
                        continue
                        
                    country_part = val_str.split(":")[0].strip()

                    if country_part.lower() in historical_countries:
                        msg = f"{self.description} (Found: '{country_part}')"
                        results.append(self.feature_result(record, feature, msg, level="warning", qualifier="geo_loc_name"))
        return results
                
class ANN3350(BaseRule):
    rule_id = "ANN3350"
    alternate_id = "JP0149"
    target = "qualifier"
    description = "Set hold date at least 10 days from today."
    requires_rdb = False

    def validate(self, record, context):
        results = []
        today = datetime.date.today()

        for feature in self.get_features(record, "DATE"):
            hold_dates = feature.qualifiers.get("hold_date", [])
            
            for val in hold_dates:
                val_str = str(val)
                if not val_str:
                    continue
                
                try:
                    try:
                        if "-" in val_str:
                            parsed_date = datetime.datetime.strptime(val_str, "%Y-%m-%d").date()
                        else:
                            parsed_date = datetime.datetime.strptime(val_str, "%Y%m%d").date()
                    except ValueError:
                        continue
                    
                    diff_days = (parsed_date - today).days
                    
                    if diff_days <= 10:
                        msg = f"{self.description} (Found: {val_str})"
                        results.append(self.feature_result(record, feature, msg, level="warning", qualifier="hold_date"))
                        
                except ValueError:
                    continue

        return results
        
                
class ANN4100(BaseRule):
    rule_id = "ANN4100"
    alternate_id = "JK"
    target = "inference"
    description = "DDBJ, GenBank or ENA detected in the inference qualifier. Use INSD instead."
    requires_rdb = False

    def validate(self, record, context):
        results = []
        if record.id == "COMMON":
            return results

        pattern = re.compile(r'\b(DDBJ|GenBank|ENA)\b', re.IGNORECASE)

        for feature in self.get_features(record):
            inferences = feature.qualifiers.get("inference", [])
            if not inferences:
                continue

            for i, val in enumerate(inferences):
                val_str = str(val)
                if pattern.search(val_str):
                    original_val = val_str
                    fixed_val = pattern.sub("INSD", val_str)
                    
                    msg = f"{self.description} (Found: '{original_val}')"
                    
                    res = self.feature_result(record, feature, msg, level="warning", qualifier="inference")
                    res["target"] = self.target
                    res["autofix"] = True
                    res["old_value"] = original_val
                    res["new_value"] = fixed_val
                    
                    results.append(res)

        return results
        
class ANN4200(BaseRule):
    rule_id = "ANN4200"
    alternate_id = "GENBANK_ALL_SEQS_CIRCULAR"
    target = "topology"
    description = "All WGS entries are annotated as 'circular'. Unless these represent complete circular genomes or plasmids, please update the topology to 'linear' by removing the 'TOPOLOGY' line from the annotation file."
    requires_rdb = False
    is_file_level = True

    def validate_file(self, records, context, ann_path=None, seq_path=None):
        results = []
        
        if not context.is_wgs:
            return results

        def get_topology(record):
            for feat in self.get_features(record, "TOPOLOGY"):
                for k, vals in feat.qualifiers.items():
                    if k == "circular": return "circular", feat
                    if k == "linear": return "linear", feat
                    for v in vals:
                        if str(v) == "circular": return "circular", feat
                        if str(v) == "linear": return "linear", feat
            return None, None

        common_rec = records.get("COMMON")
        common_topo, common_topo_feat = None, None
        if common_rec:
            common_topo, common_topo_feat = get_topology(common_rec)
        
        seq_count = 0
        all_circular = True
        circular_feats_set = set()
        circular_feats_list = []
        
        for entry_id, record in records.items():
            if entry_id == "COMMON": continue
            seq_count += 1
            
            entry_topo, entry_topo_feat = get_topology(record)
            final_topo = entry_topo if entry_topo else (common_topo or "linear")
            
            if final_topo != "circular":
                all_circular = False
                break 
            else:
                f_target = entry_topo_feat if entry_topo_feat else common_topo_feat
                if f_target and id(f_target) not in circular_feats_set:
                    circular_feats_set.add(id(f_target))
                    circular_feats_list.append((entry_id if entry_topo_feat else "COMMON", f_target))

        if seq_count > 0 and all_circular:
            if common_topo == "circular" and len(circular_feats_list) == 1:
                target_entry, target_feat = circular_feats_list[0]
                res = self.feature_result(records[target_entry], target_feat, self.description, level="error")
                res["target"] = "topology"
                results.append(res)
            else:
                res = self.format_result(
                    entry_id="ALL_ENTRIES", 
                    message=self.description, 
                    level="error", 
                    feature_type="TOPOLOGY"
                )
                res["rule"] = self.rule_id
                res["target"] = "topology"
                results.append(res)
                
        return results        


class ANN4210(BaseRule):
    rule_id = "ANN4210"
    alternate_id = "GENBANK_BACTERIAL_JOINED_FEATURES_NO_EXCEPTION"
    target = "location"
    
    description = (
        "Joined locations in bacterial sequences. "
        "Ignore if these cross the sequence origin. Add a 'ribosomal_slippage' qualifier if it is translated by ribosomal slippage. "
    )
    requires_rdb = False
    is_file_level = False

    # バクテリア判定を context.is_prokaryote に近似 (より厳密にしたい場合はtax_dataを参照)
    def validate(self, record, context):
        results = []
        if record.id == "COMMON":
            return results

        # ファイルレベルで原核生物と判定されていない場合はスキップ
        if not context.is_prokaryote:
            return results

        seq_len = len(record.seq) if record.seq else 0

        # このレコードが本当にバクテリアか再確認
        is_bct = False
        for feat in self.get_features(record, "source"):
            orgs = feat.qualifiers.get("organism", [])
            if orgs:
                org_name = orgs[0].strip()
                tax_info = context.tax_data.get(org_name, {})
                if tax_info.get("division") == "BCT" or "Bacteria" in tax_info.get("lineage", ""):
                    is_bct = True
            break

        if not is_bct:
            return results  

        for feature in self.get_features(record):
            if not isinstance(feature.location, CompoundLocation):
                continue

            if "ribosomal_slippage" in feature.qualifiers or "trans_splicing" in feature.qualifiers:
                continue

            crosses_origin = False
            if seq_len > 0:
                parts = feature.location.parts
                for i in range(len(parts) - 1):
                    part_end = int(parts[i].end)
                    next_start = int(parts[i+1].start)
                    
                    if part_end == seq_len and next_start == 0:
                        crosses_origin = True
                        break

            if crosses_origin:
                continue

            results.append(self.feature_result(record, feature, self.description, level="warning"))

        return results

        
class ANN4220(BaseRule):
    rule_id = "ANN4220"
    alternate_id = "GENBANK_DUP_GENES_OPPOSITE_STRANDS"
    target = "CDS, mRNA"
    description = "Two genes match other genes in the same location on the opposite strand. If this is an annotation error, remove one of the genes."
    requires_rdb = False
    is_file_level = False

    def validate(self, record, context):
        results = []
        if record.id == "COMMON":
            return results

        span_groups = {}
        target_types = ["CDS", "mRNA", "rRNA"]
        
        for f_type in target_types:
            for feature in self.get_features(record, f_type):
                if not feature.location:
                    continue
                
                loc = feature.location
                
                # 位置情報の文字列（元の記載文字列、またはBiopythonの文字列表現）を取得
                location_str = getattr(feature, 'original_location', str(loc))
                
                # 文字列の中に '<' や '>' が含まれている場合は Partial とみなしてチェックから除外
                if "<" in location_str or ">" in location_str:
                    continue
                    
                start = int(loc.start)
                end = int(loc.end)
                
                key = (feature.type, start, end)
                if key not in span_groups:
                    span_groups[key] = []
                span_groups[key].append(feature)

        for key, feats in span_groups.items():
            if len(feats) < 2:
                continue
                
            strands = set(f.location.strand for f in feats if f.location.strand is not None)
            
            if 1 in strands and -1 in strands:
                for f in feats:
                    results.append(self.feature_result(record, f, self.description, level="warning"))

        return results


class ANN4240(BaseRule):
    rule_id = "ANN4240"
    alternate_id = ""
    target = "CDS"
    description = "For prokaryote genomes, CDS features can be partial if the feature abut a gap or the end of the sequence (within 2 bases to allow for non-complete codons; however, it is preferred to extend the feature and include the non-complete codon)."
    requires_rdb = True
    is_file_level = False

    def validate(self, record, context):
        results = []
        if record.id == "COMMON":
            return results

        # =========================================================
        # 1. Autofix と完全に同じロジックで原核生物判定を行う
        # =========================================================
        is_prokaryote = False
        # context が tax_data (辞書) を持っていると仮定して取得
        tax_data = getattr(context, "tax_data", {}) 

        for feature in self.get_features(record, "source"):
            for org in feature.qualifiers.get("organism", []):
                lineage = tax_data.get(org.strip(), {}).get("lineage", "")
                if "Archaea" in lineage or "Bacteria" in lineage:
                    is_prokaryote = True
                    break
            if is_prokaryote:
                break
                
        if not is_prokaryote:
            return results

        # =========================================================
        # 2. gap および assembly_gap のゲノム座標を収集
        # =========================================================
        gaps = []
        for gap_type in ("gap", "assembly_gap"):
            for feature in self.get_features(record, gap_type):
                if feature.location:
                    gaps.append((int(feature.location.start), int(feature.location.end)))

        seq_len = len(record.seq)

        # =========================================================
        # 3. CDSフィーチャーの partial 状態と検証
        # =========================================================
        for feature in self.get_features(record, "CDS"):
            if not feature.location:
                continue

            # CompoundLocation対応
            first_part = feature.location.parts[0]
            last_part = feature.location.parts[-1]

            is_left_partial = type(first_part.start).__name__ == "BeforePosition"
            is_right_partial = type(last_part.end).__name__ == "AfterPosition"

            if not (is_left_partial or is_right_partial):
                continue

            start_val = int(first_part.start)
            end_val = int(last_part.end)
            
            reasons = []

            if is_left_partial:
                if 0 < start_val <= 2:
                    reasons.append("sequence end")
                else:
                    for g_start, g_end in gaps:
                        if 0 < (start_val - g_end) <= 2:
                            reasons.append("gap")
                            break

            if is_right_partial:
                if 0 < (seq_len - end_val) <= 2:
                    reasons.append("sequence end")
                else:
                    for g_start, g_end in gaps:
                        if 0 < (g_start - end_val) <= 2:
                            reasons.append("gap")
                            break

            if reasons:
                loc_str = getattr(feature, 'original_location', str(feature.location))
                reason_str = " and ".join(sorted(set(reasons)))
                msg = f"{self.description} (Found partial location close to {reason_str}: {loc_str})"
                results.append(self.feature_result(record, feature, msg, level="error"))

        return results        
                                                
class ANN4300(BaseRule):
    rule_id = "ANN4300"
    alternate_id = "V200"
    target = "CDS"
    description = "Complete CDS must be at least 90 bases (30 aa) long unless supported by experiment or inference."
    requires_rdb = False
    is_file_level = False

    def validate(self, record, context):
        results = []
        if record.id == "COMMON":
            return results

        for feature in self.get_features(record, "CDS"):
            if "experiment" in feature.qualifiers or "inference" in feature.qualifiers:
                continue

            loc_str = getattr(feature, 'original_location', "")
            
            if "<" in loc_str or ">" in loc_str:
                continue

            if feature.location is not None:
                try:
                    seq_len = len(feature.location)
                    if seq_len < 90:
                        msg = f"{self.description} (Length: {seq_len} bases)"
                        results.append(self.feature_result(record, feature, msg, level="warning"))
                except Exception:
                    pass

        return results

class ANN4400(BaseRule):
    rule_id = "ANN4400"
    target = "allele"
    description = "The 'allele' qualifier value must be different from the 'gene' qualifier value."
    requires_rdb = False
    is_file_level = False

    def validate(self, record, context):
        results = []
        if record.id == "COMMON":
            pass 

        for feature in self.get_features(record):
            if "allele" in feature.qualifiers and "gene" in feature.qualifiers:
                alleles = feature.qualifiers["allele"]
                genes = feature.qualifiers["gene"]
                
                for allele_val in alleles:
                    if allele_val in genes:
                        msg = f"{self.description} (Found identical value: '{allele_val}')"
                        results.append(self.feature_result(record, feature, msg, level="warning", qualifier="allele"))
                        
        return results

class ANN4410(BaseRule):
    rule_id = "ANN4410"
    target = "altitude"
    description = "The 'altitude' qualifier value should end with ' m' to indicate metres."
    requires_rdb = False
    is_file_level = False

    def validate(self, record, context):
        results = []
        
        for feature in self.get_features(record):
            if "altitude" in feature.qualifiers:
                altitudes = feature.qualifiers["altitude"]
                
                for val in altitudes:
                    val_str = str(val)
                    
                    if not val_str.endswith(" m"):
                        msg = f"{self.description} (Found: '{val_str}')"
                        results.append(self.feature_result(record, feature, msg, level="error", qualifier="altitude"))
                        
        return results
                        
        
class ANN5045(BaseRule):
    rule_id = "ANN5045"
    alternate_id = "-"
    target = "source"
    description = "Minimal size for sequences in a eukaryote or prokaryotic genome (WGS) is 1,000 nucleotides."
    requires_rdb = True  
    is_file_level = True 

    def validate_file(self, records, context, ann_path=None, seq_path=None):
        results = []

        if not context.is_wgs:
            return results

        if not (context.is_eukaryote or context.is_prokaryote):
            return results

        for entry_id, record in records.items():
            if entry_id == "COMMON":
                continue
            
            for feature in self.get_features(record, "source"):
                if not feature.location:
                    continue

                seq_len = len(feature.location)
                
                if seq_len < 1000:
                    msg = f"{self.description} (Length: {seq_len} bp)"
                    res = self.feature_result(record, feature, msg, level="error")
                    res["entry"] = entry_id
                    results.append(res)
                
                break # source は1つチェックすれば十分
        
        return results


class ANN5220(BaseRule):
    rule_id = "ANN5220"
    alternate_id = "SVP0040, ANN0401"
    target = "gap"
    description = "Unknown gap length exceeds 1,000 bases."
    requires_rdb = False

    def validate(self, record, context):
        results = []
        for feature in self.get_features(record, "assembly_gap"):
            
            est_len = feature.qualifiers.get("estimated_length", [])
            
            # リストが空でなく、値が "unknown" であるかチェック
            if est_len and est_len[0] == "unknown":
                length = len(feature.location)
                if length > 1000:
                    start, end = feature.location.start + 1, feature.location.end
                    msg = f"{self.description}: {length}-bp at {start}..{end}"
                    # qualifierの指定も実態に合わせて "estimated_length" に修正
                    results.append(self.feature_result(record, feature, msg, level="warning", qualifier="estimated_length"))
        return results


class ANN5230(BaseRule):
    rule_id = "ANN5230"
    alternate_id = "SVP0050, ANN0402"
    target = "gap"
    description = "All unknown assembly_gap features must have a uniform length."
    requires_rdb = False

    def validate(self, record, context):
        results = []
        unknown_gap_lengths = set()
        
        for feature in self.get_features(record, "assembly_gap"):
            est_len = feature.qualifiers.get("estimated_length", [])
            if est_len and est_len[0] == "unknown":
                unknown_gap_lengths.add(len(feature.location))
        
        if len(unknown_gap_lengths) > 1:
            # どんな長さが混在しているかメッセージに出す
            lengths_str = ", ".join(f"{l}-bp" for l in sorted(unknown_gap_lengths))
            msg = f"{self.description} (Found lengths: {lengths_str})"
            results.append(self.format_result(
                entry_id=record.id, message=msg, level="warning",
                feature_type="assembly_gap", qualifier="estimated_length"
            ))
        return results

        
class ANN5240(BaseRule):
    rule_id = "ANN5240"
    alternate_id = "SVP0060, ANN0403"
    target = "gap"
    description = "All known assembly_gap features have a uniform length."
    requires_rdb = False

    def validate(self, record, context):
        results = []
        known_gap_lengths = set()
        known_gap_count = 0
        
        for feature in self.get_features(record, "assembly_gap"):
            est_len = feature.qualifiers.get("estimated_length", [])
            if est_len and est_len[0] != "unknown":
                known_gap_lengths.add(len(feature.location))
                known_gap_count += 1
                    
        if known_gap_count > 1 and len(known_gap_lengths) == 1:
            msg = f"{self.description} ({known_gap_lengths.pop()}-bp)"
            results.append(self.format_result(
                entry_id=record.id, message=msg, level="warning",
                feature_type="assembly_gap", qualifier="estimated_length"
            ))
        return results
        
class ANN5242(BaseRule):
    rule_id = "ANN5242"
    alternate_id = ""
    target = "gap, assembly_gap"
    description = "Location operators 'join', 'order', and 'complement' cannot be used in 'gap' or 'assembly_gap'."
    requires_rdb = False
    is_file_level = False

    def validate(self, record, context):
        results = []
        if record.id == "COMMON":
            return results

        for f_type in ("gap", "assembly_gap"):
            for feature in self.get_features(record, f_type):
                if not feature.location:
                    continue
                
                orig_loc = getattr(feature, 'original_location', str(feature.location))
                
                if any(op in orig_loc for op in ["join", "order", "complement"]):
                    msg = f"Location operators 'join', 'order', and 'complement' cannot be used in '{feature.type}'."
                    res = self.feature_result(record, feature, msg, level="warning")
                    res["target"] = "location"
                    results.append(res)
                    
        return results
        
        
class ANN5244(BaseRule):
    rule_id = "ANN5244"
    alternate_id = ""
    target = "gap, assembly_gap"
    description = "Qualifier 'estimated_length=unknown' cannot be used in transcriptome entries."
    requires_rdb = False
    is_file_level = True 

    def validate_file(self, records, context, ann_path=None, seq_path=None):
        results = []

        is_transcriptome = (
            context.is_tsa or context.is_est or 
            ("HTC" in context.active_datatypes) or
            ("TSA" in context.active_divisions) or
            ("EST" in context.active_divisions) or
            ("HTC" in context.active_divisions)
        )
        
        if not is_transcriptome:
            return results

        for entry_id, record in records.items():
            if entry_id == "COMMON":
                continue

            for f_type in ("gap", "assembly_gap"):
                for feature in self.get_features(record, f_type):
                    if "estimated_length" in feature.qualifiers:
                        est_length = feature.qualifiers["estimated_length"][0]
                        
                        if est_length == "unknown":
                            msg = "Qualifier 'estimated_length=unknown' cannot be used in transcriptome entries (TSA, EST, or HTC divisions)."
                            res = self.feature_result(record, feature, msg, level="warning", qualifier="estimated_length")
                            results.append(res)
                            
        return results


class ANN5250(BaseRule):
    rule_id = "ANN5250"
    alternate_id = "SVP0080, SVP0081, ANN0404"
    target = "gap"
    description = "Inconsistent gap_type and linkage_evidence"
    requires_rdb = False

    def validate(self, record, context):
        results = []
        
        # パターン1: linkage_evidence を書いてはいけないリスト
        no_evidence_types = [
            "between scaffolds", "telomere", "centromere", 
            "short arm", "heterochromatin", "repeat between scaffolds", 
            "unknown"
        ]
        
        for feature in self.get_features(record, "assembly_gap"):
            gap_types = feature.qualifiers.get("gap_type", [])
            linkage_evidences = feature.qualifiers.get("linkage_evidence", [])
            
            if not gap_types:
                continue
                
            gap_type = gap_types[0]
            
            # --- パターン1: linkage_evidence を書いてはいけない gap_type ---
            if gap_type in no_evidence_types:
                if linkage_evidences:
                    ev_str = ", ".join(linkage_evidences)
                    msg = f"[{record.id}] Inconsistent gap_type and linkage_evidence. The '{gap_type}' gap_type does not require linkage_evidence ({ev_str})."
                    results.append(self.feature_result(record, feature, msg, level="warning", qualifier="gap_type"))
                    
            # --- パターン2: contamination (必須かつ "unspecified" 固定) ---
            elif gap_type == "contamination":
                if not linkage_evidences:
                    # 記載がない場合
                    msg = f"[{record.id}] Inconsistent gap_type and linkage_evidence (contamination). - actual value is: missing"
                    results.append(self.feature_result(record, feature, msg, level="warning", qualifier="gap_type"))
                
                elif linkage_evidences[0] != "unspecified":
                    # "unspecified" 以外の値が書かれている場合
                    ev_str = linkage_evidences[0]
                    msg = f"[{record.id}] Inconsistent gap_type and linkage_evidence (contamination). - actual value is: {ev_str}"
                    # 値が間違っている場合は qualifier="linkage_evidence" をターゲットにする
                    results.append(self.feature_result(record, feature, msg, level="warning", qualifier="linkage_evidence"))
                    
        return results

                        
class ANN5270(BaseRule):
    rule_id = "ANN5270"
    alternate_id = "BLP0026, ANN0406, SVP0300, ANN0407"
    target = "CDS, mRNA, assembly_gap, gap"
    description = "Overlap between CDS/mRNA and gap/assembly_gap features."
    requires_rdb = False
    is_file_level = False

    def validate(self, record, context):
        results = []
        if record.id == "COMMON":
            return results

        gaps = self.get_features(record, "gap") + self.get_features(record, "assembly_gap")
        if not gaps:
            return results

        targets = self.get_features(record, "CDS") + self.get_features(record, "mRNA")
        if not targets:
            return results
        
        # 1. ギャップ(gap, assembly_gap) の空間インデックス（区間木）を構築
        gap_tree = IntervalTree()
        for gap in gaps:
            if gap.location:
                g_parts = getattr(gap.location, "parts", [gap.location])
                for g_part in g_parts:
                    gap_tree.addi(int(g_part.start), int(g_part.end), {"gap": gap, "part": g_part})

        # 2. ターゲットをループし、ギャップと重なっているか高速検索
        for target in targets:
            if not target.location:
                continue
            
            orig_loc = getattr(target, 'original_location', "")
            t_parts = getattr(target.location, "parts", [target.location])
            
            for t_part in t_parts:
                t_start_0 = int(t_part.start)
                t_end_0 = int(t_part.end)
                
                overlapping_gaps = gap_tree.overlap(t_start_0, t_end_0)
                
                if not overlapping_gaps:
                    continue
                    
                # =======================================================
                # 1. 重なる全ギャップを評価し、最終的な両端の座標を決定する
                # =======================================================
                new_start_0 = t_start_0
                new_end_0 = t_end_0
                new_start_lt = ""
                new_end_gt = ""
                
                for interval in overlapping_gaps:
                    g_part = interval.data["part"]
                    g_start_0 = int(g_part.start)
                    g_end_0 = int(g_part.end)

                    # Targetの Start側 のみがギャップ内に落ちている場合
                    if g_start_0 <= new_start_0 < g_end_0 and new_end_0 > g_end_0:
                        new_start_0 = g_end_0
                        new_start_lt = "<"
                        
                    # Targetの End側 のみがギャップ内に落ちている場合
                    if new_start_0 < g_start_0 and g_start_0 < new_end_0 <= g_end_0:
                        new_end_0 = g_start_0
                        new_end_gt = ">"

                autofix_possible = (new_start_0 != t_start_0) or (new_end_0 != t_end_0)

                # =======================================================
                # 2. 新しいロケーション文字列の構築（autofix可能な場合のみ）
                # =======================================================
                old_loc_str = getattr(target, 'original_location', "")
                if autofix_possible:
                    if not old_loc_str:
                        old_loc_str = f"{t_start_0+1}..{t_end_0}"
                        if getattr(target.location, 'strand', 1) == -1:
                            old_loc_str = f"complement({old_loc_str})"
                            
                    is_complement = "complement" in old_loc_str

                    n_start_1 = new_start_0 + 1
                    n_end_1 = new_end_0
                    prefix = "complement(" if is_complement else ""
                    suffix = ")" if is_complement else ""
                    new_loc_str = f"{prefix}{new_start_lt}{n_start_1}..{new_end_gt}{n_end_1}{suffix}"

                # =======================================================
                # 3. 警告と Auto-fix の登録
                # =======================================================
                for i, interval in enumerate(overlapping_gaps):
                    gap_data = interval.data
                    gap = gap_data["gap"]
                    g_part = gap_data["part"]
                    g_start_0 = int(g_part.start)
                    g_end_0 = int(g_part.end)
                    
                    # 完全に内包されているか判定 (CDSがGapをすっぽり覆っている、またはその逆)
                    is_complete_overlap = (t_start_0 <= g_start_0 and g_end_0 <= t_end_0) or \
                                          (g_start_0 <= t_start_0 and t_end_0 <= g_end_0)
                    
                    overlap_prefix = "Complete overlap" if is_complete_overlap else "Overlap"
                    
                    msg = f"{overlap_prefix} between {target.type} and {gap.type} features. (at {t_start_0+1}..{t_end_0})"
                    res = self.feature_result(record, target, msg, level="warning")
                    res["target"] = "location"
                    
                    # autofixの指示は重複適用を防ぐため最初の警告(i == 0)にのみ紐付ける
                    if autofix_possible and i == 0:
                        res["autofix"] = True
                        res["fix_target"] = "location"
                        res["old_value"] = old_loc_str
                        res["new_value"] = new_loc_str
                        res["qualifier"] = f"{target.type} location"
                        
                        res["updates"] = [{
                            "action": "update_location",
                            "entry": record.id,
                            "feature_type": target.type,
                            "feature_id": getattr(target, 'line_number', id(target)),
                            "old_value": old_loc_str,
                            "new_value": new_loc_str
                        }]
                    
                    results.append(res)
                                                                    
        return results        
        
class ANN5310(BaseRule):
    rule_id = "ANN5310"
    target = "feature"
    description = "The rRNA feature must not overlap CDS or other rRNA features."
    requires_rdb = False

    def validate(self, record, context):
        results = []
        rrnas = self.get_features(record, "rRNA")
        if not rrnas:
            return results
            
        cdss = self.get_features(record, "CDS")

        # rRNA の空間インデックス構築
        rrna_tree = IntervalTree()
        for i, rrna in enumerate(rrnas):
            if rrna.location:
                parts = getattr(rrna.location, "parts", [rrna.location])
                for part in parts:
                    rrna_tree.addi(int(part.start), int(part.end), {"feat": rrna, "index": i})

        # CDS の空間インデックス構築
        cds_tree = IntervalTree()
        for cds in cdss:
            if cds.location:
                parts = getattr(cds.location, "parts", [cds.location])
                for part in parts:
                    cds_tree.addi(int(part.start), int(part.end), cds)

        for i, rrna in enumerate(rrnas):
            if not rrna.location:
                continue
            
            rrna_loc = getattr(rrna, 'original_location', str(rrna.location))
            parts = getattr(rrna.location, "parts", [rrna.location])
            
            # 1. rRNA 同士の重複チェック
            overlap_found = False
            for part in parts:
                overlaps = rrna_tree.overlap(int(part.start), int(part.end))
                for interval in overlaps:
                    other_data = interval.data
                    if other_data["index"] > i: # j > i の条件を再現
                        other_rrna = other_data["feat"]
                        if rrna.location.strand == other_rrna.location.strand:
                            other_loc = getattr(other_rrna, 'original_location', str(other_rrna.location))
                            msg = f"The rRNA feature must not overlap other rRNA features. (Found: rRNA at {rrna_loc} overlaps with rRNA at {other_loc})"
                            results.append(self.feature_result(record, rrna, msg, level="error"))
                            overlap_found = True
                            break
                if overlap_found: break

            # 2. CDS との重複チェック
            overlap_found = False
            for part in parts:
                overlaps = cds_tree.overlap(int(part.start), int(part.end))
                for interval in overlaps:
                    cds = interval.data
                    if rrna.location.strand == cds.location.strand:
                        cds_loc = getattr(cds, 'original_location', str(cds.location))
                        msg = f"The rRNA feature must not overlap CDS features. (Found: rRNA at {rrna_loc} overlaps with CDS at {cds_loc})"
                        results.append(self.feature_result(record, rrna, msg, level="error"))
                        overlap_found = True
                        break
                if overlap_found: break

        return results

class ANN5320(BaseRule):
    rule_id = "ANN5320"
    target = "feature"
    description = "The tRNA feature must not be completely contained within CDS exons."
    requires_rdb = False

    def validate(self, record, context):
        results = []
        trnas = self.get_features(record, "tRNA")
        if not trnas: return results
        
        cdss = self.get_features(record, "CDS")
        if not cdss: return results

        # CDSの空間インデックスを構築
        cds_tree = IntervalTree()
        for cds in cdss:
            if cds.location:
                parts = getattr(cds.location, "parts", [cds.location])
                for part in parts:
                    cds_tree.addi(int(part.start), int(part.end), cds)

        for trna in trnas:
            if not trna.location:
                continue

            t_parts = getattr(trna.location, "parts", [trna.location])
            
            for t_part in t_parts:
                t_start = int(t_part.start)
                t_end = int(t_part.end)
                
                # tRNAのパーツを完全に包含しているか？(overlapで候補を出し、厳密に包含かチェック)
                overlaps = cds_tree.overlap(t_start, t_end)
                for interval in overlaps:
                    cds = interval.data
                    if trna.location.strand == cds.location.strand:
                        c_start = interval.begin
                        c_end = interval.end
                        
                        # 完全に包含されている場合 (t_start >= c_start AND t_end <= c_end)
                        if t_start >= c_start and t_end <= c_end:
                            trna_loc = getattr(trna, 'original_location', str(trna.location))
                            cds_loc = getattr(cds, 'original_location', str(cds.location))
                            
                            msg = f"{self.description} (Found: tRNA {trna_loc} in CDS {cds_loc})"
                            results.append(self.feature_result(record, trna, msg, level="error"))
                            break # tRNAの1つのパーツが見つかれば十分

        return results

class ANN5330(BaseRule):
    rule_id = "ANN5330"
    target = "CDS"
    description = "For entries with mol_type mRNA, CDS features must not be located on the minus strand."
    requires_rdb = False

    def validate(self, record, context):
        results = []
        
        is_mrna = False
        for feature in self.get_features(record, "source"):
            mol_types = feature.qualifiers.get("mol_type", [])
            if any(m == "mRNA" for m in mol_types):
                is_mrna = True
            break 
        
        if not is_mrna:
            return results

        for feature in self.get_features(record, "CDS"):
            if feature.location:
                parts = getattr(feature.location, "parts", [feature.location])
                
                if any(part.strand == -1 for part in parts):
                    loc_str = getattr(feature, 'original_location', str(feature.location))
                    msg = f"{self.description} (Found: CDS on minus strand at {loc_str})"
                    results.append(self.feature_result(record, feature, msg, level="error"))

        return results
                        
class ANN5340(BaseRule):
    rule_id = "ANN5340"
    alternate_id = ""
    target = "CDS"
    description = "For entries with mol_type mRNA or transcribed RNA, CDS regions must not span multiple joined locations."
    requires_rdb = False
    is_file_level = False

    def validate(self, record, context):
        results = []
        if record.id == "COMMON":
            return results

        is_target_mol_type = False
        for feature in self.get_features(record, "source"):
            for mt in feature.qualifiers.get("mol_type", []):
                if mt in ("mRNA", "transcribed RNA"):
                    is_target_mol_type = True
                    break
            if is_target_mol_type:
                break
        
        if not is_target_mol_type:
            return results

        for feature in self.get_features(record, "CDS"):
            if feature.location:
                parts = getattr(feature.location, "parts", [feature.location])
                
                if len(parts) > 1:
                    if "artificial_location" not in feature.qualifiers:
                        loc_str = getattr(feature, 'original_location', str(feature.location))
                        msg = f"{self.description} (Found: joined CDS at {loc_str})"
                        results.append(self.feature_result(record, feature, msg, level="error"))

        return results

class ANN6520(BaseRule):
    rule_id = "ANN6520"
    alternate_id = "ANN0324"
    target = "CDS"
    description = "A transl_table qualifier is required for a CDS feature."
    requires_rdb = True


    def validate(self, record, context):
        results = []
        table_id = get_expected_transl_table(record, context.tax_data)

        if table_id in (0, 1):
            return results

        for feature in self.get_features(record, "CDS"):
            if "transl_table" not in feature.qualifiers:
                msg = f"{self.description} (Expected: {table_id})"
                results.append(self.feature_result(record, feature, msg, level="error", qualifier="transl_table"))
                
        return results
                        
class ANN6840(BaseRule):
    rule_id = "ANN6840"
    alternate_id = "SVP0140, ANN0321"
    target = "CDS, mRNA, intron"
    description = "CDS/mRNA intron or intron feature is less than 10 bp and artificial_location or ribosomal_slippage qualifier is missing."
    requires_rdb = False

    def validate(self, record, context):
        results = []
        
        targets = self.get_features(record, "CDS") + self.get_features(record, "mRNA") + self.get_features(record, "intron")
        
        for feature in targets:
            has_artificial = "artificial_location" in feature.qualifiers
            has_slippage = "ribosomal_slippage" in feature.qualifiers
            
            if has_artificial or has_slippage:
                continue

            if feature.type in ("CDS", "mRNA"):
                # get_introns_from_join はそのままインポート元から利用                
                for intron in get_introns_from_join(feature):
                    if intron["length"] < 10:
                        msg = f"{self.description} (length = {intron['length']} bases)"
                        results.append(self.feature_result(record, feature, msg, level="warning"))
                        
            elif feature.type == "intron":
                if feature.location:
                    intron_length = len(feature.location)
                    if intron_length < 10:
                        msg = f"{self.description} (length = {intron_length} bases)"
                        results.append(self.feature_result(record, feature, msg, level="warning"))

        return results

class FF_DEFINITION_VALIDATOR(BaseRule):
    rule_id = "FF_DEFINITION_MASTER"
    target = "ff_definition"
    description = "Validate ff_definition meta-descriptions"
    requires_rdb = False

    def __init__(self, ddbj_dict=None):
        pass

    def validate(self, record, context):
        results = []
        allowed_quals = set()
        source_def = context.ddbj_dict.get("features", {}).get("source", {})
        allowed_quals.update(source_def.get("mandatory_qualifiers", {}).keys())
        allowed_quals.update(source_def.get("optional_qualifiers", []))
        allowed_quals.add("entry")

        sources = self.get_features(record, "source")
        main_source_ids = set()
        
        has_explicit_main = False
        for s in sources:
            if "focus" in s.qualifiers or "transgenic" in s.qualifiers:
                main_source_ids.add(id(s))
                has_explicit_main = True
                
        if not has_explicit_main and sources:
            max_len = -1
            for s in sources:
                try:
                    slen = len(s.location) if s.location else 0
                except Exception:
                    slen = 0
                if slen > max_len:
                    max_len = slen
            
            for s in sources:
                try:
                    slen = len(s.location) if s.location else 0
                except Exception:
                    slen = 0
                if slen == max_len:
                    main_source_ids.add(id(s))

        for feature in self.get_features(record, "source"):
            if "ff_definition" in feature.qualifiers:
                is_main_source = id(feature) in main_source_ids
                ff_vals = feature.qualifiers["ff_definition"]
                
                if not is_main_source:
                    msg = "Non-main source feature has the ff_definition qualifier."
                    res = self.feature_result(record, feature, msg, level="error", qualifier="ff_definition")
                    res["rule"], res["target"] = "ANN4730", "ff_definition"
                    results.append(res)

                for val in ff_vals:
                    val_str = str(val)

                    cleaned_val = re.sub(r'@@\[[a-zA-Z0-9_]+\]@@', '', val_str)
                    if '@' in cleaned_val:
                        msg = "Qualifier includes '@' not used as meta-description."
                        res = self.feature_result(record, feature, msg, level="warning", qualifier="ff_definition")
                        res["rule"], res["target"] = "ANN4620", "ff_definition"
                        results.append(res)

                    if "@@[organism]@@" in val_str and not val_str.startswith("@@[organism]@@"):
                        msg = "@@[organism]@@ must be at the start of the ff_definition value."
                        res = self.feature_result(record, feature, msg, level="error", qualifier="ff_definition")
                        res["rule"], res["target"] = "ANN4690", "ff_definition"
                        results.append(res)

                    seen_tags = set()
                    
                    for match in re.finditer(r'@@\[(.*?)\]@@', val_str):
                        ref_qual = match.group(1)
                        start_idx = match.start()
                        end_idx = match.end()

                        prev_valid = (start_idx == 0) or (val_str[start_idx - 1] in (' ', '('))
                        
                        next_valid = False
                        if end_idx == len(val_str):
                            next_valid = True
                        elif val_str[end_idx] in (' ', ')'):
                            next_valid = True
                        elif val_str[end_idx] == ',':
                            if end_idx + 1 == len(val_str) or val_str[end_idx + 1] == ' ':
                                next_valid = True

                        if not (prev_valid and next_valid):
                            msg = "Meta-description must be delimited by space, comma-space, or ()."
                            res = self.feature_result(record, feature, msg, level="warning", qualifier="ff_definition")
                            res["rule"], res["target"] = "ANN4710", "ff_definition"
                            results.append(res)

                        if ref_qual in seen_tags:
                            msg = f"Duplicate meta-description @@[{ref_qual}]@@."
                            res = self.feature_result(record, feature, msg, level="error", qualifier="ff_definition")
                            res["rule"], res["target"] = "ANN4660", "ff_definition"
                            results.append(res)
                        else:
                            seen_tags.add(ref_qual)

                            if not re.match(r'^[a-zA-Z0-9_]+$', ref_qual) or ref_qual not in allowed_quals:
                                msg = "Invalid meta-description format."
                                res = self.feature_result(record, feature, msg, level="error", qualifier="ff_definition")
                                res["rule"], res["target"] = "ANN4630", "ff_definition"
                                results.append(res)
                                
                            elif ref_qual != "entry": 
                                if ref_qual not in feature.qualifiers:
                                    msg = "The qualifier referenced by the ff_definition does not exist."
                                    res = self.feature_result(record, feature, msg, level="error", qualifier="ff_definition")
                                    res["rule"], res["target"] = "ANN4640", "ff_definition"
                                    results.append(res)
                                    
                                elif len(feature.qualifiers[ref_qual]) > 1:
                                    msg = f"The qualifier '{ref_qual}' referenced by ff_definition appears multiple times."
                                    res = self.feature_result(record, feature, msg, level="error", qualifier="ff_definition")
                                    res["rule"], res["target"] = "ANN4650", "ff_definition"
                                    results.append(res)

        return results


class OPERON_MASTER_VALIDATOR(BaseRule):
    """
    operon フィーチャーおよび /operon qualifier に関する統合バリデーター
    対象ルール: ANN4010, ANN4020, ANN4030, ANN4040, ANN4050, ANN4060
    """
    rule_id = "ANN40X0"
    alternate_id = "OPERON_MASTER"
    target = "operon"
    description = "Master validation for operon features and qualifiers."
    requires_rdb = False
    is_file_level = True 

    def validate_file(self, records, context, ann_path=None, seq_path=None):
        results = []
        
        # 1. COMMONエントリからベースとなる mol_type を取得
        common_mol_type = None
        if "COMMON" in records:
            for feat in self.get_features(records["COMMON"], "source"):
                mts = feat.qualifiers.get("mol_type", [])
                if mts:
                    common_mol_type = mts[0]

        # 2. 各エントリを検証
        for entry_id, record in records.items():
            if entry_id == "COMMON": 
                continue
            
            entry_mol_type = common_mol_type
            
            for feat in self.get_features(record, "source"):
                mts = feat.qualifiers.get("mol_type", [])
                if mts:
                    entry_mol_type = mts[0]
                    
            operon_feats = self.get_features(record, "operon")
            
            # =========================================================
            # ANN4010 (JP0064): operon が外部エントリを参照しているかチェック
            # =========================================================
            for op_feat in operon_feats:
                if op_feat.location:
                    for part in op_feat.location.parts:
                        if getattr(part, 'ref', None) is not None:
                            msg = "The operon feature cannot refer to another entry."
                            res = self.feature_result(record, op_feat, msg, level="error")
                            res["entry"] = getattr(op_feat, 'original_entry_id', entry_id)
                            res["rule"] = "ANN4010"
                            res["target"] = "operon"
                            results.append(res)
                            break  # 1つのフィーチャーにつきエラーは1回で十分なため抜ける
            
            # sourceとoperon以外の全てのフィーチャーを「子フィーチャー候補」とする
            other_feats = [f for f in record.features if f.type not in ("source", "operon")]
                        
            # =========================================================
            # ANN4060 (JP0165): operon があるのに genomic DNA ではない場合
            # =========================================================
            if operon_feats and entry_mol_type != "genomic DNA":
                for op_feat in operon_feats:
                    msg = "The operon features require a mol_type of 'genomic DNA'."
                    res = self.feature_result(record, op_feat, msg, level="warning")
                    res["entry"] = getattr(op_feat, 'original_entry_id', entry_id)
                    res["rule"], res["target"] = "ANN4060", "mol_type"
                    results.append(res)
                    
            op_children_count = {id(op): 0 for op in operon_feats}
            
            # =========================================================
            # 子フィーチャー候補との整合性チェック
            # =========================================================
            for other_feat in other_feats:
                o_loc = other_feat.location
                if not o_loc: continue
                
                other_operon_quals = other_feat.qualifiers.get("operon", [])
                
                # パターンA: 子フィーチャー候補が /operon qualifier を持っている場合
                if other_operon_quals:
                    for op_val in other_operon_quals:
                        
                        # 1. 同名の /operon を持つ親 operon フィーチャーを探す
                        matching_parent = None
                        for op_feat in operon_feats:
                            if op_val in op_feat.qualifiers.get("operon", []):
                                matching_parent = op_feat
                                break
                                
                        if matching_parent:
                            p_loc = matching_parent.location
                            # 子供が親の location の範囲内に完全に包含されているかチェック
                            if p_loc and o_loc.start >= p_loc.start and o_loc.end <= p_loc.end:
                                op_children_count[id(matching_parent)] += 1 
                            else:
                                # 同名の親はいるが、locationがはみ出している (ANN4050)
                                msg = f"Feature with operon qualifier does not overlap with the associated operon '{op_val}'."
                                res = self.feature_result(record, other_feat, msg, level="error", qualifier="operon")
                                res["entry"] = getattr(other_feat, 'original_entry_id', entry_id)
                                res["rule"] = "ANN4050"
                                results.append(res)
                        else:
                            # 2. 同名の親 operon が存在しない場合
                            overlapping_parent = None
                            for op_feat in operon_feats:
                                p_loc = op_feat.location
                                if p_loc and max(o_loc.start, p_loc.start) < min(o_loc.end, p_loc.end):
                                    overlapping_parent = op_feat
                                    break
                                    
                            if overlapping_parent:
                                # 重なる親はいるが、/operon の名前が一致していない (ANN4030)
                                msg = "Feature must have the same operon qualifier as the associated operon."
                                res = self.feature_result(record, other_feat, msg, level="error", qualifier="operon")
                                res["entry"] = getattr(other_feat, 'original_entry_id', entry_id)
                                res["rule"] = "ANN4030"
                                results.append(res)
                            else:
                                # 重なる親も、同名の親も存在しない (ANN4050)
                                msg = "Feature with operon qualifier does not overlap with any associated operon."
                                res = self.feature_result(record, other_feat, msg, level="error", qualifier="operon")
                                res["entry"] = getattr(other_feat, 'original_entry_id', entry_id)
                                res["rule"] = "ANN4050"
                                results.append(res)
                                
                # パターンB: 子フィーチャー候補が /operon を持っていない場合
                else:
                    # /operon を持たないのに、任意の operon_feature と重なっていたら警告 (ANN4020)
                    for op_feat in operon_feats:
                        p_loc = op_feat.location
                        if p_loc and max(o_loc.start, p_loc.start) < min(o_loc.end, p_loc.end):
                            msg = "Overlapped with the operon feature."
                            res = self.feature_result(record, other_feat, msg, level="warning")
                            res["entry"] = getattr(other_feat, 'original_entry_id', entry_id)
                            res["rule"] = "ANN4020"
                            results.append(res)
                            break 
                            
            # =========================================================
            # ANN4040 (JP0067): 関連する子フィーチャーを1つも持たない operon
            # =========================================================
            for op_feat in operon_feats:
                if op_children_count[id(op_feat)] == 0:
                    op_vals = op_feat.qualifiers.get("operon", [])
                    op_name = op_vals[0] if op_vals else "UNKNOWN"
                    
                    msg = f"An operon feature '{op_name}' must be associated with at least one related feature."
                    res = self.feature_result(record, op_feat, msg, level="error")
                    res["entry"] = getattr(op_feat, 'original_entry_id', entry_id)
                    res["rule"] = "ANN4040"
                    results.append(res)
                                        
        return results

class ANN6400(BaseRule):
    rule_id = "ANN6400"
    target = "CDS"
    description = "The strand of the 'transl_except' location mismatch with the CDS feature. Both must be on the same strand."
    requires_rdb = False
    is_file_level = False

    def validate(self, record, context):
        results = []
        if record.id == "COMMON":
            return results

        seq_len = len(record.seq)

        # ターゲットである CDS だけを取得
        for feature in self.get_features(record, "CDS"):
            loc = feature.location
            if not loc:
                continue

            transl_excepts = feature.qualifiers.get("transl_except", [])
            if not transl_excepts:
                continue

            # 親フィーチャーのストランドを取得
            parent_strand = loc.strand if loc.strand is not None else 1
            loc_str = getattr(feature, 'original_location', str(loc))

            for te_val in transl_excepts:
                m = POS_PATTERN.search(te_val)
                if not m:
                    continue
                
                pos_str = m.group(1).strip()
                try:
                    pos_loc = _parse_location_string(pos_str, seq_length=seq_len)
                    if not pos_loc:
                        continue
                    
                    pos_strand = pos_loc.strand if pos_loc.strand is not None else 1
                    
                    # ストランドが一致しない場合はエラー
                    if parent_strand != pos_strand:
                        msg = f"{self.description} (CDS location: '{loc_str}', transl_except pos: '{pos_str}')"
                        
                        # feature_result で簡潔にエラーを生成
                        res = self.feature_result(record, feature, msg, level="error", qualifier="transl_except")
                        res["target"] = self.target
                        results.append(res)
                        
                except Exception:
                    pass

        return results