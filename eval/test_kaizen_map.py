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
