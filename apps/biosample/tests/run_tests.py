#!/usr/bin/env python3
"""BioSample validator 専用 E2E ハーネス（ddbj とは完全分離）。

- 対象: apps/biosample/tests/<BS_Rxxxx>/ 配下の fixture（*.xml / *.txt(TSV)）。
- 命名: `BS_Rxxxx_n.pass.xml` / `BS_Rxxxx_n.fail.xml`（.txt も可）。
  ディレクトリ名のルール ID を「対象ルール」とし、
    pass → 対象ルールが発火しないこと、fail → 対象ルールが発火すること、を検証。
- 実行は in-process（パイプライン直呼び）。既定は local モード（DB 非依存ルールの検証）。
ミスマッチが 1 件でもあれば終了コード 1。
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps.biosample.context import ValidationContext
from apps.biosample import xml_reader, tsv_to_xml
from apps.biosample.validator import Validator

GREEN = "\033[92m"; RED = "\033[91m"; END = "\033[0m"

# 決定的テストのための mock taxonomy（DB/NCBI に依存しない）。
# fixture が使う organism を網羅すること。
MOCK_TAX = {
    "Arabidopsis thaliana": {"tax_id": "3702", "rank": "species", "scientific_name": "Arabidopsis thaliana",
                              "is_species_or_below": True, "status": "valid", "lineage": "Eukaryota; Viridiplantae"},
    "Escherichia coli": {"tax_id": "562", "rank": "species", "scientific_name": "Escherichia coli",
                          "is_species_or_below": True, "status": "valid", "lineage": "Bacteria; Proteobacteria"},
    "Homo sapiens": {"tax_id": "9606", "rank": "species", "scientific_name": "Homo sapiens",
                     "is_species_or_below": True, "status": "valid", "lineage": "Eukaryota; Metazoa; Homo"},
    # common name（fetch_taxonomy_data が学名へ解決する。R0015 の human→Homo sapiens autofix 検証用）
    "human": {"tax_id": "9606", "rank": "species", "scientific_name": "Homo sapiens",
              "is_species_or_below": True, "status": "fixable", "lineage": "Eukaryota; Metazoa; Homo"},
    "Homo": {"tax_id": "9605", "rank": "genus", "scientific_name": "Homo",
             "is_species_or_below": False, "status": "invalid_rank", "lineage": "Eukaryota; Metazoa"},
    # package_vs_organism 用
    "Mus musculus": {"tax_id": "10090", "rank": "species", "scientific_name": "Mus musculus",
                     "is_species_or_below": True, "status": "valid", "pl_code": 0,
                     "lineage": "Eukaryota; Metazoa; Chordata; Mammalia; Mus"},
    "Dengue virus": {"tax_id": "12637", "rank": "species", "scientific_name": "Dengue virus",
                     "is_species_or_below": True, "status": "valid", "pl_code": 0,
                     "lineage": "Viruses; Riboviria; Orthornavirae"},
    "Saccharomyces cerevisiae": {"tax_id": "4932", "rank": "species", "scientific_name": "Saccharomyces cerevisiae",
                                 "is_species_or_below": True, "status": "valid", "pl_code": 0,
                                 "lineage": "Eukaryota; Fungi; Ascomycota"},
    "soil metagenome": {"tax_id": "410658", "rank": "species", "scientific_name": "soil metagenome",
                        "is_species_or_below": True, "status": "valid", "pl_code": 0,
                        "lineage": "unclassified sequences; metagenomes; ecological metagenomes"},
    "Euglena gracilis": {"tax_id": "3039", "rank": "species", "scientific_name": "Euglena gracilis",
                         "is_species_or_below": True, "status": "valid", "pl_code": 11,
                         "lineage": "Eukaryota; Discoba; Euglenozoa"},  # 非 Viridiplantae だが plastid 保持
    # R0045/R0105 用: 入力名と学名が異なる（シノニム）ケース
    "Bacillus coli": {"tax_id": "562", "rank": "species", "scientific_name": "Escherichia coli",
                      "is_species_or_below": True, "status": "valid", "pl_code": 0,
                      "lineage": "Bacteria; Proteobacteria"},
}


# 決定的テストのための mock account 状態（DB に依存しない。D 群 R0006/0129/0070/0095 用）。
# fixture はこの mock を前提に pass/fail を設計する。
MOCK_ACCOUNT = "test_account"
MOCK_AUTH_PROJECTS = {"PRJDB00001", "PRJDB00099", "PSUB000001", "PSUB999999"}
MOCK_AUTH_SAMDS = {"SAMD00000001"}
MOCK_BP_META = {
    "PRJDB00001": {"submission_id": "PSUB000001", "project_type": "primary", "status_id": 5500},
    "PRJDB00099": {"submission_id": "PSUB000099", "project_type": "umbrella", "status_id": 5500},
}
MOCK_PSUB_TO_PRJD = {
    "PSUB000001": {"accession": "PRJDB12345", "status_id": 5500},
}
# R0091 用: DB 登録済み locus_tag_prefix -> {submission_id}
MOCK_REGISTERED_PREFIXES = {"TAKENPFX": {"SSUB999999"}}


def _fired_rules(fixture_path):
    """fixture を検証し、発火したルール ID 集合を返す。
    taxonomy ルールも有効化（skip_ncbi=False）し、mock taxonomy を注入して決定的に評価する。
    account 依存ルール（D 群）も skip_auth=False ＋ mock account 状態で決定的に評価する。
    """
    ctx = ValidationContext(
        skip_db=False, skip_ncbi=False, skip_auth=False,
        account=MOCK_ACCOUNT, tax_data=dict(MOCK_TAX),
        authorized_projects=set(MOCK_AUTH_PROJECTS), authorized_samds=set(MOCK_AUTH_SAMDS),
        bp_meta=dict(MOCK_BP_META), psub_to_prjd=dict(MOCK_PSUB_TO_PRJD),
        registered_locus_tag_prefixes=dict(MOCK_REGISTERED_PREFIXES),
    )
    submission, results, _xml_src = _validate(fixture_path, ctx)
    return {r["rule_id"] for r in results}


def _validate(fixture_path, ctx):
    """fixture を検証し (submission, results, xml_source_path) を返す。
    TSV は XML へ変換した一時ファイルのパスを xml_source として返す（autofix 適用に使う）。"""
    path = Path(fixture_path)
    if path.suffix.lower() in (".txt", ".tsv"):
        import tempfile
        xml_text = tsv_to_xml.tsv_to_xml(str(path))
        sub_id, _ = tsv_to_xml.parse_filename(str(path))
        tmp = tempfile.NamedTemporaryFile("w", suffix=".xml", delete=False, encoding="utf-8")
        tmp.write(xml_text or ""); tmp.close()
        xml_src = tmp.name
        submission, pre = xml_reader.parse_xml(xml_src, submission_id=sub_id)
    else:
        xml_src = str(path)
        submission, pre = xml_reader.parse_xml(xml_src)
    results = list(pre)
    if submission is not None:
        results += Validator(ctx).run(submission)
    return submission, results, xml_src


def _check_autofix(fixture_path, golden_path):
    """fixture を検証→autofix 全自動適用し、生成 XML を golden とバイト突合。
    戻り値: (ok, error_message)。"""
    import tempfile
    from apps.biosample import autofix
    ctx = ValidationContext(
        skip_db=False, skip_ncbi=False, skip_auth=False,
        account=MOCK_ACCOUNT, tax_data=dict(MOCK_TAX),
        authorized_projects=set(MOCK_AUTH_PROJECTS), authorized_samds=set(MOCK_AUTH_SAMDS),
        bp_meta=dict(MOCK_BP_META), psub_to_prjd=dict(MOCK_PSUB_TO_PRJD),
        registered_locus_tag_prefixes=dict(MOCK_REGISTERED_PREFIXES),
    )
    submission, results, xml_src = _validate(fixture_path, ctx)
    if submission is None:
        return False, "parse failed"
    with tempfile.TemporaryDirectory() as td:
        name = "out.xml"
        n = autofix.apply_autofix(xml_src, results, td, name)
        if n == 0:
            return False, "no autofix applied (expected fixed output)"
        got = (Path(td) / "fixed" / name).read_bytes()
    want = golden_path.read_bytes()
    if got == want:
        return True, ""
    return False, f"fixed output differs from golden (got {len(got)}B, want {len(want)}B)"


def run_inprocess_mode(target=None):
    """in-process（mock tax/account, 全ルール有効）でルール pass/fail と autofix golden を検証。
    ddbj でいう curator/full 相当。DB/NCBI/auth を mock で決定的に有効化する最も網羅的なモード。"""
    test_dirs = sorted(d for d in HERE.iterdir()
                       if d.is_dir() and d.name.startswith("BS_R")
                       and (target is None or d.name == target))
    passed = mismatched = 0
    errors = []
    print(f"\n=== BioSample Validator E2E ({'all' if not target else target}) ===")
    for d in test_dirs:
        rule_id = d.name
        print(f"Testing: {d.name}")
        for fx in sorted(list(d.glob("*.xml")) + list(d.glob("*.txt"))):
            parts = fx.name.split(".")
            if len(parts) < 3 or parts[-2] not in ("pass", "fail"):
                continue
            expected = parts[-2]
            # 環境依存: XSD(R0098) は lxml 必須。無ければ検証不能なので skip（CLI モードと同じ扱い）。
            if rule_id == "BS_R0098" and not _lxml_available():
                print(f"  [SKIP]     {fx.name} (BS_R0098=XSD は lxml 未導入のため検証不可)")
                continue
            fired = _fired_rules(fx)
            triggered = rule_id in fired
            ok = (triggered if expected == "fail" else not triggered)
            if ok:
                print(f"  [{GREEN}Matched{END}]  {fx.name} ({rule_id} correctly {'triggered' if expected=='fail' else 'not triggered'})")
                passed += 1
            else:
                print(f"  [{RED}MISMATCH{END}] {fx.name}: expected {expected}, fired={sorted(fired)}")
                mismatched += 1
                errors.append(f"{d.name}/{fx.name}")

        # autofix ゴールデン検証: <dir>/expected/<name> があれば、その入力に autofix を適用して突合。
        exp_dir = d / "expected"
        if exp_dir.is_dir():
            for fx in sorted(list(d.glob("*.xml")) + list(d.glob("*.txt"))):
                golden = exp_dir / (Path(fx.name).stem + ".xml" if fx.suffix != ".xml" else fx.name)
                if not golden.exists():
                    continue
                ap, af_err = _check_autofix(fx, golden)
                if ap:
                    print(f"  [{GREEN}Autofix{END}] {fx.name} matches expected/{golden.name}")
                    passed += 1
                else:
                    print(f"  [{RED}MISMATCH{END}] autofix {fx.name}: {af_err}")
                    mismatched += 1
                    errors.append(f"{d.name}/autofix:{fx.name}")

    print("\n" + "=" * 60)
    print(f"  Matched: {passed}   Mismatched: {RED if mismatched else GREEN}{mismatched}{END}")
    for e in errors:
        print(f"    - {e}")
    print("=" * 60)
    rule_ok = mismatched == 0
    if rule_ok:
        print(f"{GREEN}[SUCCESS] All BioSample rule tests passed.{END}")
    else:
        print(f"{RED}[ABORT] BioSample rule tests failed.{END}")

    # TSV→XML 変換テストも同時に実行（"tsv2xml 含めて test"）。全 fixture 実行時のみ。
    tsv_ok = True
    if target is None:
        print("\n--- tsv_to_xml conversion test ---")
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "run_tsv2xml_test", Path(__file__).resolve().parent / "run_tsv2xml_test.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        tsv_ok = (mod.main() == 0)

    return 0 if (rule_ok and tsv_ok) else 1


# ============================================================================
# CLI サブプロセス実行モード
#   ddbj ハーネスと同じ考え方で、実 CLI を local(-l)/ncbi(-n) で回して
#   「一般ユーザが得る挙動」を検証する。docker イメージ / pip CLI / main.py に対応。
#   モード別スキップ（requires_rdb/network/auth）を能力フラグから判定し、
#   skip-only では「そのモードでスキップされるべきルールが確かに発火しない」ことのみ検証する。
# ============================================================================
import argparse
import json
import os
import shutil
import subprocess
import tempfile

# docker コンテナへ NCBI 資格情報を渡すため、ハーネス側で .env を読み込んでおく
# （.env は image に含まれない＝コンテナはキー無しでレート制限に当たるため）。
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass


def _ncbi_env_args():
    """docker コンテナへ渡す NCBI 資格情報の -e 引数。値は付けず環境から引き継ぐ形にして
    キーが argv/ps に出ないようにする。設定済みの変数のみ渡す。"""
    args = []
    for var in ("NCBI_API_KEY", "NCBI_API_EMAIL"):
        if os.environ.get(var):
            args += ["-e", var]
    return args


def _requirement_map():
    """rule_id -> (requires_rdb, requires_network, requires_auth)。全ルール有効の Validator から構築。"""
    ctx = ValidationContext(skip_db=False, skip_ncbi=False, skip_auth=False)
    m = {}
    for r in Validator(ctx).active_rules:
        m[r.rule_id] = (getattr(r, "requires_rdb", False),
                        getattr(r, "requires_network", False),
                        getattr(r, "requires_auth", False))
    return m


def _lxml_available():
    try:
        import lxml  # noqa: F401
        return True
    except Exception:
        return False


def _skipped_in_mode(reqs, mode):
    """mode（local/ncbi）でこの要件のルールがスキップされるか。cli._resolve_modes と同じ規則。"""
    rdb, net, auth = reqs
    if mode == "local":   # -l: DB/NCBI/auth すべてスキップ
        return rdb or net or auth
    if mode == "ncbi":    # -n: DB/auth スキップ、network は有効
        return rdb or auth
    return False


# NCBI API モードで skip する fixture（mock / 内部DB でのみ成立するもの）。
# 実 NCBI taxonomy が該当情報を返さないため、ncbi(-n) モードでは判定不能で正しく評価できない。
# {fixture 名: 理由}。local モードでは該当ルールが元々スキップされるので影響しない。
NCBI_SKIP_FIXTURES = {
    # Euglena gracilis は非 Viridiplantae。Plant パッケージ適合(BS_R0048/_plant)は
    # plastid genetic code (pl_code) に依存するが、NCBI taxonomy は Euglena に
    # PlastidGeneticCode を返さない（pl_code=0 になり BS_R0048 が誤発火）。
    # mock(pl_code=11)/内部DB 前提の pass ケースのため network モードでは検証不能。
    "BS_R0048_12.pass.xml": "Euglena gracilis: NCBI に plastid genetic code が無く Plant 判定不可 (mock/内部DB 限定)",
}


def _build_bs_cmd(mode, fixture, out_dir, use_pip, docker_image, project_root, python_bin, main_py):
    inflag = "-t" if fixture.suffix.lower() in (".txt", ".tsv") else "-x"
    modeflag = "-l" if mode == "local" else "-n"
    if docker_image:
        rel_fx = fixture.relative_to(project_root)
        rel_out = out_dir.relative_to(project_root)
        return ["docker", "run", "--rm", "-u", f"{os.getuid()}:{os.getgid()}",
                "-v", f"{project_root}:/work", *_ncbi_env_args(), docker_image,
                "biosample", modeflag, "-j", inflag, f"/work/{rel_fx}", "-o", f"/work/{rel_out}"]
    if use_pip:
        cli = project_root / ".venv" / "bin" / "ddbj-validator"
        if not cli.exists():
            print(f"{RED}[ERROR]{END} pip CLI が見つかりません: {cli} ('pip install .' 済みか確認)")
            sys.exit(1)
        return [str(cli), "biosample", modeflag, "-j", inflag, str(fixture), "-o", str(out_dir)]
    return [str(python_bin), str(main_py), "biosample", modeflag, "-j", inflag, str(fixture), "-o", str(out_dir)]


def _fired_from_cli(cmd, out_dir):
    """CLI を実行し、JSON レポートから発火 rule_id 集合を返す。レポート未生成なら None。"""
    subprocess.run(cmd, capture_output=True, text=True)
    jp = out_dir / "reports" / "validation_report.json"
    if not jp.exists():
        return None
    try:
        d = json.loads(jp.read_text(encoding="utf-8"))
    except Exception:
        return None
    return {msg["id"] for msg in d.get("messages", [])}


def run_cli_mode(mode, skip_only, target, use_pip, docker_image):
    """実 CLI（local/ncbi）でのテスト。戻り値: 成否(bool)。"""
    reqmap = _requirement_map()
    # docker イメージは lxml 同梱想定（requirements 経由）。source/pip は現行環境依存。
    lxml_ok = _lxml_available() or bool(docker_image)
    project_root = ROOT
    python_bin = sys.executable
    main_py = project_root / "main.py"
    tmp_root = Path(tempfile.mkdtemp(prefix="bs_e2e_", dir=str(project_root)))
    passed = mismatched = skipped = 0
    errors = []
    label = f"{mode.upper()}{' (SKIP ONLY)' if skip_only else ''}"
    runner = f"Docker ({docker_image})" if docker_image else ("pip CLI" if use_pip else "main.py")
    print(f"\n{'=' * 60}")
    print(f" BioSample CLI E2E [{label}] via {runner}")
    print(f"{'=' * 60}")

    test_dirs = sorted(d for d in HERE.iterdir()
                       if d.is_dir() and d.name.startswith("BS_R")
                       and (target is None or d.name == target))
    idx = 0
    try:
        for d in test_dirs:
            rid = d.name
            reqs = reqmap.get(rid, (False, False, False))
            skipmode = _skipped_in_mode(reqs, mode)
            if skip_only and not skipmode:
                continue  # skip-only は「スキップされるべきルール」だけを対象にする
            for fx in sorted(list(d.glob("*.xml")) + list(d.glob("*.txt"))):
                parts = fx.name.split(".")
                if len(parts) < 3 or parts[-2] not in ("pass", "fail"):
                    continue
                expected = parts[-2]
                # 環境依存: XSD(R0098) は lxml 必須。無ければ検証不能なので skip。
                if rid == "BS_R0098" and not lxml_ok:
                    print(f"  [SKIP]     {fx.name} (BS_R0098=XSD は lxml 未導入のため検証不可)")
                    skipped += 1
                    continue
                # mock/内部DB 限定 fixture は network(ncbi) モードでは検証不能なので skip。
                if mode == "ncbi" and fx.name in NCBI_SKIP_FIXTURES:
                    print(f"  [SKIP]     {fx.name} ({NCBI_SKIP_FIXTURES[fx.name]})")
                    skipped += 1
                    continue
                idx += 1
                out_dir = tmp_root / f"{rid}_{idx}"
                out_dir.mkdir(parents=True, exist_ok=True)
                cmd = _build_bs_cmd(mode, fx, out_dir, use_pip, docker_image,
                                    project_root, python_bin, main_py)
                fired = _fired_from_cli(cmd, out_dir)
                if fired is None:
                    print(f"  [{RED}ERROR{END}]   {fx.name}: レポート未生成 (CLI 実行失敗)")
                    mismatched += 1
                    errors.append(f"{rid}/{fx.name}: no report")
                    continue
                triggered = rid in fired
                if skipmode:
                    # このモードでは対象ルールはスキップされるはず → pass/fail 問わず発火しないこと
                    ok = not triggered
                    desc = "correctly skipped" if ok else f"UNEXPECTEDLY fired (should be skipped in {mode})"
                else:
                    ok = (triggered if expected == "fail" else not triggered)
                    desc = (f"correctly {'triggered' if expected == 'fail' else 'not triggered'}"
                            if ok else f"expected {expected}, fired={sorted(fired)}")
                if ok:
                    print(f"  [{GREEN}Matched{END}]  {fx.name} ({rid} {desc})")
                    passed += 1
                else:
                    print(f"  [{RED}MISMATCH{END}] {fx.name} ({rid} {desc})")
                    mismatched += 1
                    errors.append(f"{rid}/{fx.name}")
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)

    print("\n" + "=" * 60)
    print(f"  [{label}] Matched: {passed}   "
          f"Mismatched: {RED if mismatched else GREEN}{mismatched}{END}   Skipped: {skipped}")
    for e in errors:
        print(f"    - {e}")
    print("=" * 60)
    if mismatched == 0:
        print(f"{GREEN}[OK] {label} passed.{END}")
    else:
        print(f"{RED}[ABORT] {label} failed.{END}")
    return mismatched == 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="BioSample Validator E2E harness")
    parser.add_argument("rule_id", nargs="?", default=None, help="対象ルールID (例: BS_R0001)")
    parser.add_argument("--mode", nargs="+",
                        choices=["full", "local", "ncbi", "local-skip", "ncbi-skip", "all"],
                        default=["full"],
                        help="実行モード。full=in-process 全ルール(既定) / local,ncbi=実CLI / *-skip=スキップ検証のみ")
    parser.add_argument("--use-pip", action="store_true",
                        help="pip インストール済み CLI (ddbj-validator) で実行")
    parser.add_argument("-d", "--docker", dest="docker_image", default=None,
                        help="指定した Docker イメージで実行 (例: ghcr.io/ddbj/ddbj-validator:v0.1.5-beta)")
    args = parser.parse_args()

    modes = list(args.mode)
    if "all" in modes:
        modes = ["local", "ncbi"] if (args.docker_image or args.use_pip) else ["full", "local", "ncbi"]
    # docker/pip では in-process(full) は動かせない → 除外して通知
    if (args.docker_image or args.use_pip) and "full" in modes:
        print(f"{RED}[WARN]{END} full(in-process) は docker/pip では実行不可のため除外します。")
        modes = [m for m in modes if m != "full"]

    ok = True
    for m in modes:
        if m == "full":
            ok = (run_inprocess_mode(args.rule_id) == 0) and ok
        elif m == "local":
            ok = run_cli_mode("local", False, args.rule_id, args.use_pip, args.docker_image) and ok
        elif m == "ncbi":
            ok = run_cli_mode("ncbi", False, args.rule_id, args.use_pip, args.docker_image) and ok
        elif m == "local-skip":
            ok = run_cli_mode("local", True, args.rule_id, args.use_pip, args.docker_image) and ok
        elif m == "ncbi-skip":
            ok = run_cli_mode("ncbi", True, args.rule_id, args.use_pip, args.docker_image) and ok

    sys.exit(0 if ok else 1)
