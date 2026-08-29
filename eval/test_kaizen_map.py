#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""kaizen-map の機械判定 eval（11項目）。

同梱の架空見本（samples/）を一時フォルダへコピーして実行する。ネットワーク不使用
（PLANTUML_REMOTE=0 で決定的）。実環境・実リポジトリには触れない。
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOOL = ROOT / "kaizen_map.py"
RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(ok)
    print(("PASS" if ok else "FAIL"), "-", name, ("| " + str(detail)[:140] if detail and not ok else ""))


def run(target, out):
    env = dict(os.environ)
    env["PLANTUML_REMOTE"] = "0"
    env["PYTHONIOENCODING"] = "utf-8"
    p = subprocess.run([sys.executable, "-X", "utf8", str(TOOL), str(target), "-o", str(out)],
                       capture_output=True, text=True, encoding="utf-8", env=env, timeout=60)
    return p.returncode, p.stdout


def main():
    tmp = Path(tempfile.mkdtemp(prefix="kaizen_eval_"))
    try:
        demo = tmp / "demo"
        clean = tmp / "clean"
        shutil.copytree(ROOT / "samples" / "demo_system", demo)
        shutil.copytree(ROOT / "samples" / "clean_system", clean)
        out1 = tmp / "r1"

        # 1. 実行してHTMLが生成される
        rc, _ = run(demo, out1)
        html = (out1 / "index.html").read_text(encoding="utf-8") if (out1 / "index.html").exists() else ""
        check("1 HTML生成", rc == 0 and "<html" in html)

        # 2. テスト欠落を検出（pricing.py）
        check("2 テスト欠落検出", "pricing.py" in html and "対応するテストファイルが見つからない" in html)

        # 3. 秘密情報らしき直書きを検出（settings.py）
        check("3 秘密直書き検出", re.search(r"settings\.py:\d+", html) and "秘密情報らしき直書き" in html, html.count("秘密"))

        # 4. CI未設定と .gitignore 無しを検出
        check("4 設定の欠落検出", "CI が未設定" in html and ".gitignore が無い" in html)

        # 5. 死んだコード候補（legacy_report）が【推定】として出て、推定表にも載る
        est_sec = html.split('id="estimates"')[1].split("<h2")[0] if 'id="estimates"' in html else ""
        check("5 死んだコードは推定扱い", "legacy_report" in html and "【推定】" in html and "legacy_report" in est_sec)

        # 6. 正常な見本には指摘を出さない（過剰検出なし）
        rc, out_text = run(clean, tmp / "r2")
        check("6 正常系に赤なし", rc == 0 and "指摘 0 件" in out_text, out_text)

        # 7. 左メニューの全リンク先セクションが存在する
        hrefs = set(re.findall(r'href="#([a-z0-9]+)"', html))
        ids = set(re.findall(r'id="([a-z0-9]+)"', html))
        check("7 メニューと本文の対応", hrefs and hrefs.issubset(ids), hrefs - ids)

        # 8. 8つの章（概要・地図・レンズ3・用語表・推定表・判断履歴）が全部ある
        need = {"overview", "map", "l1", "l2", "l3", "terms", "estimates", "judgements"}
        check("8 8章そろっている", need.issubset(ids), need - ids)

        # 9. 用語表: 語彙の乖離対策 — 本文で使う用語が全て定義されている
        terms_sec = html.split('id="terms"')[1].split("<h2")[0]
        need_terms = ["レンズ", "推定", "判断履歴", "地図", "テスト欠落", "設定の匂い", "死んだコード"]
        missing = [t for t in need_terms if f"<td>{t}</td>" not in terms_sec]
        check("9 未定義語なし", not missing, missing)

        # 10. 確実な指摘の行に【推定】が付かない（推定の隔離）
        l1_sec = html.split('id="l1"')[1].split("<h2")[0]
        l2_sec = html.split('id="l2"')[1].split("<h2")[0]
        check("10 確実な指摘に推定マーク無し", "【推定】" not in l1_sec and "【推定】" not in l2_sec)

        # 11. 判断履歴: 却下を書いて再実行すると、レンズ表から消え履歴に残る（蒸し返さない）
        jpath = out1 / "judgements.json"
        j = json.loads(jpath.read_text(encoding="utf-8"))
        target_id = None
        for fid in j:
            j[fid] = {"判断": "", "理由": ""}
        m = re.search(r"<tr[^>]*><td><code>([0-9a-f]{8})</code></td><td><code>[^<]*pricing\.py", html)
        target_id = m.group(1)
        j[target_id] = {"判断": "却下", "理由": "テストは別リポジトリにある（架空の理由）"}
        jpath.write_text(json.dumps(j, ensure_ascii=False), encoding="utf-8")
        rc, _ = run(demo, out1)
        html2 = (out1 / "index.html").read_text(encoding="utf-8")
        l1_2 = html2.split('id="l1"')[1].split("<h2")[0]
        jd_2 = html2.split('id="judgements"')[1]
        check("11 却下は蒸し返さない", target_id not in l1_2 and target_id in jd_2 and "却下" in jd_2)
        # ---- v2: 俯瞰（survey）モード ----
        ws = tmp / "ws"
        shutil.copytree(ROOT / "samples" / "demo_workspace", ws)
        old = (ws / "90_dormant" / "archive.md")
        import time
        t100 = time.time() - 100 * 86400
        os.utime(old, (t100, t100))
        sout = tmp / "s1"

        def run_survey(target, out):
            env = dict(os.environ)
            env["PLANTUML_REMOTE"] = "0"
            env["PYTHONIOENCODING"] = "utf-8"
            p = subprocess.run([sys.executable, "-X", "utf8", str(TOOL), str(target), "-o", str(out), "--survey"],
                               capture_output=True, text=True, encoding="utf-8", env=env, timeout=60)
            return p.returncode, p.stdout

        rc, _ = run_survey(ws, sout)
        shtml = (sout / "index.html").read_text(encoding="utf-8") if (sout / "index.html").exists() else ""

        # 12. 俯瞰HTMLが生成され、7章（工程1〜3＋3表）がそろう
        sids = set(re.findall(r'id="([a-z0-9]+)"', shtml))
        need = {"overview", "map", "areas", "deep", "terms", "estimates", "judgements"}
        check("12 俯瞰HTML生成と章構成", rc == 0 and need.issubset(sids), need - sids)

        # 13. 兆候: 休眠・入口不明・ごみ名・重複名を検出
        ok13 = ("休眠（" in shtml and "入口不明" in shtml and "ごみ名" in shtml
                and "重複名の疑い" in shtml and "レシピ帳" in shtml)
        check("13 4種の兆候を検出", ok13)

        # 14. 正常区画（01_active）には★が付かない
        row = re.search(r"<tr[^>]*><td>(★?)</td><td>01_active</td>", shtml)
        check("14 正常区画に★なし", row is not None and row.group(1) == "", row.group(0) if row else "行なし")

        # 15. 深掘りの合流: findings-*.json を置いて再実行すると推定として表に出る
        (sout / "findings-02_no_entry.json").write_text(json.dumps([
            {"path": "02_no_entry/data2.md", "text": "data1.md と内容が同一の重複（片方に統合できる）"},
            {"path": "02_no_entry/料金表.md", "text": "名前と実態のズレ（中身は料金ではなく週次予定）"},
        ], ensure_ascii=False), encoding="utf-8")
        rc, _ = run_survey(ws, sout)
        shtml2 = (sout / "index.html").read_text(encoding="utf-8")
        deep_sec = shtml2.split('id="deep"')[1].split("<h2")[0]
        ok15 = ("data2.md" in deep_sec and "料金表.md" in deep_sec and "【推定】" in deep_sec)
        check("15 深掘り指摘の合流（推定扱い）", rc == 0 and ok15)

        # 16. 深掘り指摘にも判断履歴が効く（却下→蒸し返さない）
        j = json.loads((sout / "judgements.json").read_text(encoding="utf-8"))
        m = re.search(r"<td><code>([0-9a-f]{8})</code></td><td><code>02_no_entry/data2\.md", shtml2)
        j[m.group(1)] = {"判断": "却下", "理由": "意図的な複製（架空の理由）"}
        (sout / "judgements.json").write_text(json.dumps(j, ensure_ascii=False), encoding="utf-8")
        rc, _ = run_survey(ws, sout)
        shtml3 = (sout / "index.html").read_text(encoding="utf-8")
        deep3 = shtml3.split('id="deep"')[1].split("<h2")[0]
        check("16 深掘りの却下も蒸し返さない", "data2.md" not in deep3 and "料金表.md" in deep3)

        # 17. 発見レンズの検出力オラクル: 見本の正解（重複・名前ズレ）を、
        #     良い findings は両方当て、盲目版・過剰版は落とす
        EXPECTED = {"02_no_entry/data2.md", "02_no_entry/料金表.md"}
        CLEAN = {"01_active"}

        def grade(findings):
            paths = {f.get("path", "") for f in findings}
            recall = EXPECTED.issubset(paths)
            precision = not any(p.split("/")[0] in CLEAN for p in paths)
            return recall and precision

        reference = [{"path": p, "text": "指摘"} for p in EXPECTED]
        broken_blind = []
        broken_over = reference + [{"path": "01_active/README.md", "text": "無理やりの指摘"}]
        check("17 発見レンズのオラクル", grade(reference) and not grade(broken_blind) and not grade(broken_over))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"\n{sum(RESULTS)} / {len(RESULTS)} PASS")
    return 0 if all(RESULTS) else 1


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    sys.exit(main())
