# kaizen-map — システムの地図と改善候補を、人間が判断できる1枚のHTMLに

**kaizen-map** は、対象システム（任意のフォルダ／リポジトリ）を走査して、
**地図（構成・依存のPlantUML図）＋改善候補（レンズ別の指摘）＋乖離対策の3表**を
左メニュー付きの1枚のHTMLレポートにする道具です。

Scan any codebase and render a single left-nav HTML report: a PlantUML map of the
system, findings from independent improvement lenses, and three tables that keep
the human and the AI aligned (glossary, unconfirmed estimates, judgement history).
Standard library only. The rest of this README is in Japanese.

## なぜ作ったか — 改善は「理解の乖離」で失敗する

システムを知らないまま出された改善提案は的外れになり、
知っているつもりの提案は誤解を含みます。改善の前に必要なのは**共有の地図**です。

改善は必要な理解の深さで3層に分かれます。

| 層 | 種類 | このツールの扱い |
|---|---|---|
| 1 形式の層 | 一般規則に照らすだけで見つかる（テスト欠落・設定の欠落・秘密の直書き…） | **レンズで自動検出**（中身の理解が不要） |
| 2 意味の層 | 中身を読んで初めて見つかる | まず**地図**で認識を合わせてから（将来のレンズ） |
| 3 価値の層 | 人間の判断そのもの | 自動化しない。**判断欄**として人間に返す |

## 人間とAIの乖離を構造で防ぐ3つの表

| 乖離 | 対策（レポートに常設） |
|---|---|
| 語彙の違い | **用語表**：レポートが使う専門語は全て定義。未定義語は eval で赤 |
| 理解の乖離 | **推定表**：AIが確認できていない指摘（例：死んだコード候補）は本文と分離し、承認されるまで確定扱いしない |
| 学習の差 | **判断履歴**：採用・却下と理由を `judgements.json` に記録。次回の実行が必ず読み、**却下済みは蒸し返さない** |

## 使い方

```
python kaizen_map.py <対象フォルダ> [-o 出力フォルダ]
```

- 出力：`kaizen-report/index.html`（左メニュー・白地黒文字・PlantUML図をSVG描画）と `judgements.json`
- 判断のしかた：`judgements.json` の該当IDに `{"判断": "採用|却下|保留", "理由": "..."}` を書いて再実行
- 図はマークダウン＋Mermaidではなく **HTML＋PlantUML**（公式サーバでSVG化。`PLANTUML_REMOTE=0` でソース表示に切替＝オフライン可）

## いまのレンズ（第1層・すべて決定的判定）

| レンズ | 見つけるもの |
|---|---|
| テスト欠落 | 対応するテストファイルが無いソースファイル |
| 設定の匂い | CI未設定／.gitignore無し／秘密情報らしき直書き |
| 死んだコード | どこからも参照されないファイル（**常に推定扱い**。参照解析は完全ではないため） |

## eval（機械判定11項目）

```
python eval/test_kaizen_map.py
```

同梱の架空見本（問題を仕込んだ `samples/demo_system` と正常な `samples/clean_system`）で、
仕込んだ問題の全検出／正常系に赤を付けない／8章とメニューの対応／未定義語0／
確実な指摘に推定マークを付けない／**却下済みを蒸し返さない**、まで検証します。
ネットワーク不使用・実環境に触れません。

## 関連（同じ思想のリポジトリ）

| リポジトリ | 関係 |
|---|---|
| [fractal-spec-agent](https://github.com/hatohato-lab/fractal-spec-agent) | 「構造は機械検査できる」の先行実証。用語の定義義務・推定の隔離はここから輸入 |
| [harness-lens-reviewer](https://github.com/hatohato-lab/harness-lens-reviewer) | レンズ方式の査読と、その検出力のメタ評価 |
| [rule-retirement-eval](https://github.com/hatohato-lab/rule-retirement-eval) | 「採用されない提案は退役させる」という判断履歴の思想の源流 |

## 制限

- レンズは第1層（形式検査）のみ。意味の層（命名と実態のズレ等）は地図で認識を合わせた後の将来課題
- 死んだコード検出は文字列参照の単純な突き合わせで、動的参照は見えない（だから推定扱いにしている）
- テスト対応は `test_<名前>` / `<名前>_test` の命名規約前提

## ライセンス

MIT
