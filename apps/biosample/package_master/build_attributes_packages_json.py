#!/usr/bin/env python3
"""BioSample マスター（Google Sheets 由来 CSV）から attributes_packages.json を生成する。

現行 ruby validator は 3 表 → RDF(TTL) → Virtuoso → SPARQL でパッケージ定義を配信していたが、
本スクリプトは Virtuoso を介さず、**g sheet のみ**（固定ファイル名の 4 表）から直接 JSON を生成する。

入力（このスクリプトと同じディレクトリ・固定ファイル名。中身は Google Sheets の TSV エクスポート）:
  - package.txt           : パッケージ定義（DisplayName/Version/Group/EnvPackage 等）
  - package-attribute.txt : パッケージ × 属性の use マトリクス（M/O/-/E:<group>/:N）
  - attribute-added.txt   : 属性定義。カラム順 =
                            Name / Harmonized name / Synonym / type / allowed_values / invalid_values /
                            allow_multiple / Description / DescriptionJa（Format 列は廃止）
  - package-tsv.txt       : パッケージ毎の登録 TSV ヘッダー順（full_name + 属性名の並び）。列順の定義。

出力:
  - attributes_packages.json : 同ディレクトリに生成（apps/biosample/resources/ は上書きしない）

use マトリクスのセル値:
  M=mandatory / O=optional / -=非該当 / E:<group>=either_one_mandatory(+group を付与) /
  末尾 ":N"=null 非推奨フラグ（現行 JSON は未使用のため無視）。
列順（登録 TSV）: package-tsv.txt の並びをそのまま用いる（fixed → 準固定 → 必須α → 選択必須α → 任意α）。
必須/任意/択一必須の区別は package-attribute.txt から引く。
"""
import csv
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
# MixS シリーズの package_group（either_one を含むものもある。standard/pathogen は対象外）。
# これらは列順を規則で並べ替える: fixed → locus_tag_prefix → either_one(現行順) →
# core必須(α) → env必須(α) → 任意(core+env 統合, α)。core = group 内 全 variant 共通の属性。
_MIXS_GROUPS = {"MIGS.ba", "MIGS.eu", "MIGS.vi", "MIMS.me", "MIMAG", "MISAG",
                "MIMARKS.specimen", "MIMARKS.survey", "MIUVIG"}
# group 別に「必須グループの先頭へ前寄せする属性」（core 必須のα順より前に置く）。
# source identifier を先頭に見せたいという運用要望による個別調整。
_MIXS_LEAD_MANDATORY = {
    "MIGS.ba": ["strain"],
    "MIMAG": ["isolate"],
    "MISAG": ["isolate"],
    "MIUVIG": ["isolate"],
}
F_PKG = HERE / "package.txt"                 # パッケージ定義
F_MATRIX = HERE / "package-attribute.txt"    # use マトリクス
F_ATTR = HERE / "attribute-added.txt"        # 属性定義（追加列 allowed_values/invalid_values/allow_multiple/type 込み）
F_ORDER = HERE / "package-tsv.txt"           # パッケージ毎の TSV ヘッダー順（列順の定義）
OUT = HERE / "attributes_packages.json"

_FIXED_COUNT = 6           # 先頭 6 属性（sample_name..bioproject_id）は fixed_attributes
_NO_ENV = "No environmental package"   # env_package の「環境パッケージ無し」表記 → 空文字に正規化


def _read_csv(path):
    """入力は TSV（タブ区切り。タブ/改行/引用符を含むセルは CSV 同様に quoting）。"""
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.reader(f, delimiter="\t"))


def _parse_use(cell):
    """use マトリクスのセル → (use, group) / None（非該当）。末尾 ':N' は無視する。"""
    c = (cell or "").strip()
    if not c or c.split(":")[0] == "-":
        return None
    if c.startswith("E:"):
        group = c[2:].split(":")[0].strip().lower()   # 'E:Age/stage' → 'age/stage'
        return ("either_one_mandatory", group)
    base = c.split(":")[0]
    if base == "M":
        return ("mandatory", None)
    if base == "O":
        return ("optional", None)
    return None


def _json_list(cell):
    c = (cell or "").strip()
    return json.loads(c) if c else []


def _reorder_mixs(packages):
    """MixS シリーズの列順を規則で並べ替える（fixed の後ろのみ）。

    順序: [locus_tag_prefix（あれば）] → either_one（現行順を維持） →
          core 必須(α) → env 必須(α) → 任意(core+env 統合, α)
    core = 同一 package_group の全 variant に共通して現れる属性（＝MixS 本体）。
    env  = variant 固有（＝環境パッケージ由来）。standard/pathogen は対象外（並べ替えない）。
    """
    from collections import defaultdict
    by_group = defaultdict(list)
    for key, p in packages.items():
        if p["package_group"] in _MIXS_GROUPS:
            by_group[p["package_group"]].append(key)

    for group, keys in by_group.items():
        core = set.intersection(*(set(packages[k]["attributes"].keys()) for k in keys))
        lead_mand = _MIXS_LEAD_MANDATORY.get(group, [])
        for key in keys:
            attrs = packages[key]["attributes"]
            names = list(attrs.keys())
            lead = ["locus_tag_prefix"] if "locus_tag_prefix" in attrs else []
            eo = [n for n in names if attrs[n]["use"] == "either_one_mandatory"]  # 現行順維持
            skip = set(lead) | set(eo)
            core_mand_all = [n for n in names
                             if n in core and attrs[n]["use"] == "mandatory" and n not in skip]
            # group 別の前寄せ必須（strain/isolate 等）を core 必須の先頭へ、残りはα順
            lead_present = [a for a in lead_mand if a in core_mand_all]
            core_mand = lead_present + sorted(n for n in core_mand_all if n not in lead_present)
            env_mand = sorted(n for n in names
                              if n not in core and attrs[n]["use"] == "mandatory" and n not in skip)
            optional = sorted(n for n in names
                              if attrs[n]["use"] == "optional" and n not in skip)
            new_order = lead + eo + core_mand + env_mand + optional
            assert set(new_order) == set(names), (key, set(names) ^ set(new_order))
            packages[key]["attributes"] = {n: attrs[n] for n in new_order}
    return packages


def build():
    matrix = _read_csv(F_MATRIX)
    attr_rows = _read_csv(F_ATTR)
    pkg_rows = _read_csv(F_PKG)
    order_rows = _read_csv(F_ORDER)

    # --- attributes（属性定義 ＋ 追加列）---
    ah = {c: i for i, c in enumerate(attr_rows[0])}
    attributes = {}
    for r in attr_rows[1:]:
        if not r or not r[ah["Name"]].strip():
            continue
        name = r[ah["Name"]].strip()
        syn = r[ah["Synonym"]].strip()
        # キー順は resources/attributes_packages.json に合わせる:
        # name, synonyms, [type], format_pattern, allowed_values, [allow_multiple], [invalid_values]
        entry = {"name": name,
                 "synonyms": [s.strip() for s in syn.split(",")] if syn else []}
        if "type" in ah and r[ah["type"]].strip():
            entry["type"] = r[ah["type"]].strip()
        entry["format_pattern"] = ""   # Format 列は廃止（元々全て空）。互換のためキーは維持
        entry["allowed_values"] = _json_list(r[ah["allowed_values"]]) if "allowed_values" in ah else []
        if "allow_multiple" in ah and r[ah["allow_multiple"]].strip().lower() == "true":
            entry["allow_multiple"] = True
        if "invalid_values" in ah and r[ah["invalid_values"]].strip():
            entry["invalid_values"] = _json_list(r[ah["invalid_values"]])
        attributes[name] = entry

    # --- use マトリクス: {package: {attr: (use, group)}} ---
    m_attrs = matrix[0][2:]                       # Package name, Version の後が属性列
    use_map = {}
    for r in matrix[1:]:
        if not r or not r[0].strip():
            continue
        um = {}
        for i, a in enumerate(m_attrs):
            u = _parse_use(r[2 + i] if 2 + i < len(r) else "")
            if u:
                um[a] = u
        use_map[r[0].strip()] = um

    # --- fixed_attributes（先頭 6 属性。use は全 package 恒常なので代表行から）---
    rep = matrix[1]
    fixed_attributes = {}
    for i, a in enumerate(m_attrs[:_FIXED_COUNT]):
        u = _parse_use(rep[2 + i])
        fixed_attributes[a] = {"use": u[0] if u else "optional"}

    # --- パッケージメタ（Sheet3）＋ full_name→key マップ ---
    ph = {c: i for i, c in enumerate(pkg_rows[0])}
    pkg_meta, fullname_to_key = {}, {}
    for r in pkg_rows[1:]:
        if not r or not r[ph["Package name"]].strip():
            continue
        key = r[ph["Package name"]].strip()
        env = r[ph["EnvPackage"]].strip()
        full = r[ph["DisplayName"]].strip()
        pkg_meta[key] = {
            "full_name": full,
            "version": r[ph["Version"]].strip(),
            "package_group": r[ph["Group"]].strip(),
            "env_package": "" if env == _NO_ENV else env,
        }
        fullname_to_key[full] = key

    # --- 列順（package-tsv.txt: full_name + TSV ヘッダー順の属性名）---
    # 各行: [full_name, sample_name, sample_title, ..., <package attrs...>]。fixed 6 の後がパッケージ属性。
    order_map = {}
    for r in order_rows:
        if not r or not r[0].strip():
            continue
        key = fullname_to_key.get(r[0].strip())
        if key is None:
            continue
        order_map[key] = [a.strip() for a in r[1 + _FIXED_COUNT:] if a.strip()]

    # --- packages ---
    packages = {}
    for key, meta in pkg_meta.items():
        um = use_map.get(key, {})
        attrs = {}
        for a in order_map.get(key, []):
            u = um.get(a)
            if not u:
                continue   # use マトリクスで非該当なら列に出さない
            entry = {"use": u[0]}
            if u[1]:
                entry["group"] = u[1]
            attrs[a] = entry
        packages[key] = {
            "full_name": meta["full_name"],
            "version": meta["version"],
            "package_group": meta["package_group"],
            "env_package": meta["env_package"],
            "not_recommended_for": [],
            "attributes": attrs,
        }

    # MixS シリーズは列順を規則で並べ替える（standard/pathogen は package-tsv 順のまま）
    packages = _reorder_mixs(packages)

    return {
        "metadata": {"version": "1.0",
                     "description": "DDBJ BioSample package and attribute definition"},
        "attributes": attributes,
        "fixed_attributes": fixed_attributes,
        "packages": packages,
    }


def main():
    out = build()
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"generated: {OUT}")
    print(f"  packages={len(out['packages'])}, attributes={len(out['attributes'])}, "
          f"fixed={len(out['fixed_attributes'])}")


if __name__ == "__main__":
    main()
