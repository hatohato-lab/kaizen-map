#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""kaizen-map — システムの地図と改善候補を、人間が判断できる1枚のHTMLにする。

使い方:
    python kaizen_map.py <対象フォルダ> [-o 出力フォルダ]

生成物: <出力フォルダ>/index.html （左メニュー付き・白地黒文字・PlantUML図）
        <出力フォルダ>/judgements.json （あなたの採用/却下の記録。次回実行が必ず読む）

設計の核（人間とAIの乖離を構造で防ぐ）:
- 地図      … AIが読み取った構成・依存を図と表にして、まず認識を合わせる
- レンズ    … 改善候補は観点ごとに独立した検出器で出す（第1層＝中身の理解が不要な形式検査）
- 用語表    … レポートが使う専門語は全て定義する（語彙の乖離対策）
- 推定表    … 確認できていない指摘は「推定」に隔離し、承認されるまで確定扱いしない
- 判断履歴  … 採用/却下と理由を記録し、却下済みを蒸し返さない（学習の差対策）

環境変数 PLANTUML_REMOTE=0 で図をソース表示に切り替え（オフライン・eval用に決定的）。
"""

import argparse
import hashlib
import json
import os
import re
import sys
import urllib.request
import zlib
from datetime import datetime
from pathlib import Path

SRC_EXT = {".py", ".js", ".ts", ".php", ".rb", ".go", ".java", ".ps1"}

GLOSSARY = {
    "地図": "対象システムの構成・依存を、AIが読み取って図と表にしたもの。改善の前にここで認識を合わせる",
    "レンズ": "1観点だけを見る独立した検出器。このレポートは第1層（中身の理解が不要な形式検査）のみ",
    "指摘": "レンズが見つけた改善候補1件。採用するかはすべて人間が決める",
    "推定": "AIが確認できていない指摘。承認されるまで確定扱いにしない",
    "判断履歴": "指摘への採用・却下・保留の記録。次回の実行が必ず読み、却下済みは蒸し返さない",
    "テスト欠落": "対応するテストファイルが見つからないソースファイル",
    "設定の匂い": "CI未設定・.gitignore無し・秘密情報らしき直書き、といった設定まわりの危険信号",
    "死んだコード": "どこからも参照されていない可能性のあるファイル（参照の見落としがありうるため常に推定）",
}

SECRET_RE = re.compile(r"(?i)(password|passwd|api_?key|api_?token|secret)\s*[:=]\s*[\"'][^\"'\n]{4,}[\"']")


# ---------------- 走査 ----------------

def list_files(root: Path):
    skip = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build"}
    out = []
    for p in root.rglob("*"):
        if any(part in skip for part in p.parts):
            continue
        if p.is_file():
            out.append(p)
    return out


def rel(root, p):
    return str(p.relative_to(root)).replace("\\", "/")


def finding(lens, path, text, sure=True):
    fid = hashlib.sha256(f"{lens}|{path}|{text}".encode("utf-8")).hexdigest()[:8]
    return {"id": fid, "lens": lens, "path": path, "text": text, "sure": sure}


def lens_test_gap(root, files):
    """レンズ1: テスト欠落（決定的）。"""
    out = []
    src = [f for f in files if f.suffix in SRC_EXT]
    testnames = {f.stem.lower() for f in src}
    for f in src:
        r = rel(root, f)
        low = f.stem.lower()
        if low.startswith("test_") or low.endswith("_test") or "/tests/" in "/" + r:
            continue
        has = (f"test_{low}" in testnames) or (f"{low}_test" in testnames)
        if not has:
            out.append(finding("テスト欠落", r, "対応するテストファイルが見つからない"))
    return out


def lens_config_smell(root, files):
    """レンズ2: 設定の匂い（決定的）。"""
    out = []
    if not (root / ".gitignore").exists():
        out.append(finding("設定の匂い", ".gitignore", ".gitignore が無い（生成物や秘密の混入防止が効かない）"))
    wf = root / ".github" / "workflows"
    if not (wf.exists() and any(wf.glob("*.yml")) or any(wf.glob("*.yaml")) if wf.exists() else False):
        out.append(finding("設定の匂い", ".github/workflows", "CI が未設定（テストが自動で回らない）"))
    for f in files:
        if f.suffix in SRC_EXT | {".json", ".cfg", ".ini", ".env"}:
            try:
                text = f.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            for m in SECRET_RE.finditer(text):
                line = text[:m.start()].count("\n") + 1
                out.append(finding("設定の匂い", f"{rel(root, f)}:{line}",
                                   "秘密情報らしき直書き（" + m.group(1) + "）"))
    return out


def lens_dead_code(root, files):
    """レンズ3: 死んだコード候補（参照解析は完全ではないため、全件を推定として出す）。"""
    out = []
    texts = {}
    for f in files:
        if f.suffix in SRC_EXT | {".md", ".html"}:
            try:
                texts[f] = f.read_text(encoding="utf-8", errors="replace")
            except Exception:
                texts[f] = ""
    for f in files:
        if f.suffix not in SRC_EXT:
            continue
        r = rel(root, f)
        stem = f.stem
        if stem.lower().startswith("test_") or stem in {"__init__", "index", "main", "app", "setup"}:
            continue
        referenced = any(stem in t for g, t in texts.items() if g != f)
        if not referenced:
            out.append(finding("死んだコード", r, "どこからも参照が見つからない（廃止候補）", sure=False))
    return out


# ---------------- 地図 ----------------

def build_map(root, files):
    """フォルダ構成（PlantUML）とPython依存図（PlantUML）と責務表を作る。"""
    from collections import defaultdict
    top = defaultdict(lambda: {"files": 0, "ext": defaultdict(int)})
    for f in files:
        r = rel(root, f)
        head = r.split("/")[0] if "/" in r else "（直下）"
        top[head]["files"] += 1
        top[head]["ext"][f.suffix or "なし"] += 1

    uml1 = ["@startuml", "skinparam defaultFontName Meiryo"]
    for name, info in sorted(top.items()):
        main = max(info["ext"], key=info["ext"].get)
        uml1.append(f'folder "{name}\\n{info["files"]}ファイル (主に{main})" as {re.sub(r"[^A-Za-z0-9]", "_", name) or "root"}')
    uml1.append("@enduml")

    deps = []
    pyfiles = {f.stem: f for f in files if f.suffix == ".py"}
    for f in files:
        if f.suffix != ".py":
            continue
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        for m in re.finditer(r"^\s*(?:from|import)\s+([A-Za-z_][A-Za-z0-9_.]*)", text, re.M):
            mod = m.group(1).split(".")[0]
            if mod in pyfiles and pyfiles[mod] != f:
                deps.append((f.stem, mod))
    uml2 = ["@startuml", "skinparam defaultFontName Meiryo"]
    seen = set()
    for a, b in deps:
        if (a, b) not in seen:
            seen.add((a, b))
            uml2.append(f"[{a}] --> [{b}]")
    if not deps:
        uml2.append("note as N1\nPython間の依存は検出されなかった\nend note")
    uml2.append("@enduml")

    table = [(name, info["files"], "、".join(f"{k}×{v}" for k, v in sorted(info["ext"].items(), key=lambda x: -x[1])[:3]))
             for name, info in sorted(top.items())]
    return "\n".join(uml1), "\n".join(uml2), table


# ---------------- PlantUML 描画 ----------------

_B64 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz-_"


def plantuml_encode(text):
    data = zlib.compressobj(9, zlib.DEFLATED, -15)
    comp = data.compress(text.encode("utf-8")) + data.flush()
    out = []
    for i in range(0, len(comp), 3):
        b = comp[i:i + 3] + b"\x00" * (3 - len(comp[i:i + 3]))
        n = (b[0] << 16) | (b[1] << 8) | b[2]
        out += [_B64[(n >> 18) & 63], _B64[(n >> 12) & 63], _B64[(n >> 6) & 63], _B64[n & 63]]
    return "".join(out)


def render_uml(src):
    """公式サーバでSVG化。PLANTUML_REMOTE=0 や失敗時はソースを <pre> で表示（黙って壊さない）。"""
    if os.environ.get("PLANTUML_REMOTE", "1") != "0":
        try:
            url = "https://www.plantuml.com/plantuml/svg/" + plantuml_encode(src)
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 kaizen-map"})
            svg = urllib.request.urlopen(req, timeout=20).read().decode("utf-8", "replace")
            if "<svg" in svg:
                return svg[svg.index("<svg"):]
        except Exception:
            pass
    return "<pre class='uml'>" + src.replace("&", "&amp;").replace("<", "&lt;") + "</pre>"


# ---------------- 判断履歴 ----------------

def load_judgements(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return {}


# ---------------- HTML ----------------

CSS = """
* { box-sizing: border-box; } body { margin:0; font-family: Meiryo, "Hiragino Kaku Gothic ProN", "Yu Gothic", sans-serif;
color:#000; background:#fff; font-size:17px; line-height:1.9; }
nav { position:fixed; top:0; left:0; bottom:0; width:250px; background:#f5f5f5; border-right:2px solid #000; padding:16px 12px; overflow-y:auto; }
nav a { display:block; padding:7px 8px; color:#000; text-decoration:none; border-left:4px solid transparent; }
nav a:hover { background:#e6e6e6; } nav b { display:block; margin-bottom:10px; font-size:18px; }
main { margin-left:250px; padding:24px 36px 80px; max-width:1000px; }
h1 { font-size:28px; } h2 { font-size:22px; border-bottom:3px solid #000; padding-bottom:6px; margin-top:44px; scroll-margin-top:12px; }
table { border-collapse:collapse; width:100%; margin:12px 0; } th,td { border:1px solid #999; padding:8px 10px; text-align:left; font-size:16px; }
th { background:#ebebeb; } code { font-size:15px; } .est { color:#000; background:#fff3cd; }
.uml { background:#f8f8f8; border:1px solid #999; padding:10px; overflow-x:auto; font-size:13px; }
svg { max-width:100%; height:auto; } .note { border:2px solid #000; padding:10px 14px; margin:14px 0; }
"""


def esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def build_html(target, findings, uml1, uml2, table, judgements):
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    lenses = ["テスト欠落", "設定の匂い", "死んだコード"]
    sections = [("overview", "概要"), ("map", "地図"), ("l1", "レンズ: テスト欠落"),
                ("l2", "レンズ: 設定の匂い"), ("l3", "レンズ: 死んだコード（推定）"),
                ("terms", "用語表"), ("estimates", "推定表"), ("judgements", "判断履歴")]
    nav = "".join(f'<a href="#{i}">{esc(t)}</a>' for i, t in sections)

    def rows(lens):
        out = []
        for f in findings:
            if f["lens"] != lens:
                continue
            j = judgements.get(f["id"], {})
            state = j.get("判断", "未判断")
            if state == "却下":
                continue  # 却下済みは蒸し返さない（判断履歴の節にだけ出す）
            mark = "" if f["sure"] else "【推定】"
            out.append(f"<tr class='{'est' if not f['sure'] else ''}'><td><code>{f['id']}</code></td>"
                       f"<td><code>{esc(f['path'])}</code></td><td>{mark}{esc(f['text'])}</td><td>{esc(state)}</td></tr>")
        if not out:
            return "<p>指摘なし。</p>"
        return ("<table><tr><th>ID</th><th>場所</th><th>内容</th><th>判断</th></tr>" + "".join(out) + "</table>")

    est_rows = "".join(
        f"<tr><td><code>{f['id']}</code></td><td><code>{esc(f['path'])}</code></td><td>{esc(f['text'])}</td>"
        f"<td>{esc(judgements.get(f['id'], {}).get('判断', '未確認'))}</td></tr>"
        for f in findings if not f["sure"]) or "<tr><td colspan='4'>推定なし</td></tr>"

    jrows = "".join(
        f"<tr><td><code>{fid}</code></td><td>{esc(j.get('判断', ''))}</td><td>{esc(j.get('理由', ''))}</td></tr>"
        for fid, j in judgements.items()) or "<tr><td colspan='3'>まだ判断の記録なし</td></tr>"

    terms = "".join(f"<tr><td>{esc(k)}</td><td>{esc(v)}</td></tr>" for k, v in GLOSSARY.items())
    maprows = "".join(f"<tr><td>{esc(n)}</td><td>{c}</td><td>{esc(e)}</td></tr>" for n, c, e in table)
    counts = {l: sum(1 for f in findings if f["lens"] == l) for l in lenses}

    return f"""<!DOCTYPE html><html lang="ja"><head><meta charset="utf-8">
<title>kaizen-map: {esc(target)}</title><style>{CSS}</style></head><body>
<nav><b>kaizen-map</b>{nav}</nav><main>
<h1 id="overview">改善の地図 — {esc(target)}</h1>
<p>生成: {now}。このレポートはAIの理解の提示であり、確定ではありません。
地図の誤りを直し、指摘を判断し、方向づけをするのはあなたです。</p>
<table><tr><th>レンズ</th><th>指摘数</th></tr>
{''.join(f'<tr><td>{l}</td><td>{counts[l]}</td></tr>' for l in lenses)}</table>
<div class="note">判断のしかた: <code>judgements.json</code> の該当IDに
<code>{{"判断": "採用|却下|保留", "理由": "..."}}</code> を書いて再実行すると、
却下はレンズの表から消え、判断履歴に残ります。</div>
<h2 id="map">地図（まず認識を合わせる）</h2>
<h3>フォルダ構成</h3>{render_uml(uml1)}
<h3>Python依存関係</h3>{render_uml(uml2)}
<h3>責務表</h3><table><tr><th>場所</th><th>ファイル数</th><th>中身</th></tr>{maprows}</table>
<h2 id="l1">レンズ: テスト欠落</h2>{rows('テスト欠落')}
<h2 id="l2">レンズ: 設定の匂い</h2>{rows('設定の匂い')}
<h2 id="l3">レンズ: 死んだコード（推定）</h2>
<p>参照解析は完全ではないため、このレンズの指摘は**すべて推定**です。承認するまで確定扱いされません。</p>
{rows('死んだコード')}
<h2 id="terms">用語表（語彙の乖離対策）</h2><table><tr><th>用語</th><th>この文書での意味</th></tr>{terms}</table>
<h2 id="estimates">推定表（未確認の指摘の隔離場所）</h2>
<table><tr><th>ID</th><th>場所</th><th>内容</th><th>状態</th></tr>{est_rows}</table>
<h2 id="judgements">判断履歴</h2>
<table><tr><th>ID</th><th>判断</th><th>理由</th></tr>{jrows}</table>
</main></body></html>"""


# ---------------- main ----------------

def run(target_dir, out_dir):
    root = Path(target_dir).resolve()
    if not root.is_dir():
        print(f"対象フォルダが見つかりません: {root}")
        return 2
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    files = list_files(root)
    findings = lens_test_gap(root, files) + lens_config_smell(root, files) + lens_dead_code(root, files)
    uml1, uml2, table = build_map(root, files)
    jpath = out / "judgements.json"
    judgements = load_judgements(jpath)
    if not jpath.exists():
        jpath.write_text(json.dumps({f["id"]: {"判断": "", "理由": ""} for f in findings},
                                    ensure_ascii=False, indent=1), encoding="utf-8")
    html = build_html(root.name, findings, uml1, uml2, table, judgements)
    (out / "index.html").write_text(html, encoding="utf-8")
    active = [f for f in findings if judgements.get(f["id"], {}).get("判断") != "却下"]
    print(f"生成: {out / 'index.html'}")
    print(f"指摘 {len(active)} 件（うち推定 {sum(1 for f in active if not f['sure'])} 件・却下済み {len(findings) - len(active)} 件は非表示）")
    return 0


def main():
    ap = argparse.ArgumentParser(description="システムの地図と改善候補をHTML1枚にする")
    ap.add_argument("target", help="対象フォルダ")
    ap.add_argument("-o", "--out", default="kaizen-report", help="出力フォルダ（既定: kaizen-report）")
    a = ap.parse_args()
    return run(a.target, a.out)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    sys.exit(main())
