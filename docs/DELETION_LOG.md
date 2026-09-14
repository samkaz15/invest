# DELETION_LOG.md

削除・退避の記録。指示書 §4 の要求（何を・なぜ削除したか・復元可能か）に対応する。

**大原則：実測データは削除しない。** 削除対象はコード・設定・ドキュメントに限る。
本リポジトリの git 履歴には実測データ・過去予測・過去価格・レポートが
**一度も含まれていない**（`REPOSITORY_AUDIT.md` 付録B で検証済み）ため、
以下の削除によるデータ消失は発生しない。

すべての削除は git 履歴に残るため、**復元方法は原則として共通**：

```bash
git show 2b9f925:<path>            # 削除前の内容を表示
git checkout 2b9f925 -- <path>     # 作業ツリーへ復元
```

`2b9f925` は BIOS 最終コミット（MIOS 転換前の全ファイルが揃っている唯一の地点）。

---

## Phase 2 — Architecture cleanup（2026-09-12）

### A. コード削除

| 対象 | 種別 | 削除理由 | 復元 |
|---|---|---|---|
| `src/bios/analysis/onchain.py` | code | ハッシュレート・MVRV・SOPR。Gold/USDJPY に対応物が存在しない | git |
| `src/bios/analysis/derivatives.py` | code | 暗号資産perp の funding / open interest 固有 | git |
| `src/bios/analysis/news_flow.py` | code | Fear & Greed（暗号資産専用指数）依存 | git |
| `src/bios/analysis/reactions.py` | code | イベント→BTC価格リターンの刻印。MIOS では「指標サプライズ→資産反応」として Phase 7 で作り直す | git |
| `src/bios/analysis/base.py` | code | `SnapshotRow` が `market_snapshots` の BTC 形状に依存。Phase 3 の新スキーマと合わない | git |
| `src/bios/extraction/market.py` | code | `METRIC_PATHS` が BTC 5ソース固定。**取得時刻を無視して最新rawを「今の値」として書く既知バグを含む**（監査 §14 L4） | git |
| `src/bios/scoring/regime.py` | code | BTC 日次終値の SMA/ボラでフェーズ判定。マクロレジームは Phase 7 で別定義 | git |
| `src/bios/scenario/` | code | 確率が `1/3 ± composite/100 × 0.15` の線形変換にすぎず、docstring 自身が「統計ではない」と明記。検証不能なヒューリスティックは指示書 §26 で禁止 | git |
| `src/bios/decision/engine.py` | code | BUY / WAIT / TAKE_PROFIT は売買助言。MIOS の目的（指標予測）と無関係 | git |
| `src/bios/decision/portfolio.py` | code | 仮想建玉。予測精度の検証に寄与しない | git |
| `src/bios/decision/backtest.py` | code | 売買P&L vs Buy&Hold。CPI/NFP 予測の巧拙を一切測らない | git |
| `src/bios/decision/outcomes.py` | code | ±2% / ±5% バンドの方向採点。Phase 9 で MAE/RMSE/方向的中/キャリブレーションとして作り直す | git |
| `src/bios/decision/alerts.py` | code | `decisions` / `score_cards` に強く依存。Phase 8 でレポート層の一部として再実装 | git |
| `src/bios/reporting/brief.py` | code | 端末向けブリーフィング。Phase 8 で `reports/daily/YYYY-MM-DD.md` 生成として作り直す | git |
| `src/bios/reporting/why.py` | code | decision の証拠チェーン展開。Phase 7 で forecast 版として作り直す | git |
| `src/bios/history/seeds.py` | code | 読み込み対象の BTC seed を archive へ退避したため、参照先のないローダになった | git |
| `src/bios/similarity/__init__.py` | code | **空パッケージ**（docstring 1行のみ、6スプリント放置） | git |
| `src/bios/agents/__init__.py` | code | **空パッケージ**。LLM Agent は Phase 6 で中身を伴って新設する | git |
| `tests/unit/test_analysis.py` | test | 削除した analyzer のテスト | git |
| `tests/unit/test_backtest.py` | test | 削除した backtest のテスト | git |
| `tests/unit/test_intelligence.py` | test | 削除した scoring/scenario/decision 経路のテスト | git |
| `tests/integration/test_analysis_db.py` | test | 同上 | git |
| `tests/integration/test_sprint6_db.py` | test | 同上 | git |

### B. 設定削除

| 対象 | 削除理由 |
|---|---|
| `config/assets/btc.yaml` | 対象資産が XAUUSD / USDJPY に変わった。17 metrics のうち実際に埋まっていたのは6件 |
| `config/agents.yaml` | Agent 8体を宣言していたが、`AgentsConfig` は `config/` パッケージ外から**一度も参照されていなかった**。実装を伴って Phase 6 で再作成する |
| `config/sources/src_{coindesk,cointelegraph,sec_press}_rss.yaml` | 暗号資産・SEC 報道。マクロ予測に寄与しない |
| `config/sources/src_{coingecko_btc,bybit_btc_derivs,fng_alternative,mempool_hashrate,blockchain_info_stats}.yaml` | BTC 価格・デリバティブ・センチメント・オンチェーン |
| `prompts/` | README のみでプロンプト実体ゼロ。Phase 6 で中身を伴って再作成する |

### C. ドキュメント削除

| 対象 | 削除理由 |
|---|---|
| `docs/SYSTEM_ARCHITECTURE.md` | 「MSDに統合されました」の5行リダイレクトスタブ |
| `docs/DATA_MODEL_AND_KNOWLEDGE_GRAPH.md` | 同上 |
| `docs/AI_AGENT_SPECIFICATION.md` | 同上 |

### D. アーカイブ（削除ではなく退避）

| 元 | 先 | 理由 |
|---|---|---|
| `seeds/chains/mtgox.yaml` | `archive/seeds/btc/mtgox.yaml` | **歴史イベントの実データ。指示書 §4 により削除禁止** |
| `seeds/chains/ftx.yaml` | `archive/seeds/btc/ftx.yaml` | 同上 |
| `docs/PROJECT_CONSTITUTION.md` | `archive/docs/bios/` | 思想の出典。MIOS 版を `docs/CONSTITUTION.md` として新設 |
| `docs/MASTER_SYSTEM_DESIGN.md` | `archive/docs/bios/` | 1,243行。§2/§13/§15/§18 は `docs/ARCHITECTURE.md` へ抜粋移植済み |
| `docs/INTELLIGENCE_ENGINE_SPECIFICATION.md` | `archive/docs/bios/` | 725行。§11（スコア3層透明性）は scoring に実装済みのため設計意図のみ継承 |
| `docs/RISK_AND_GOVERNANCE.md` | `archive/docs/bios/` | 自動売買前提のガバナンス。MIOS は発注機能を持たない |
| `docs/sprints/*.md`（6件） | `archive/docs/bios/sprints/` | BIOS 開発の判断記録 |
| `docs/reviews/*.md` | `archive/docs/bios/reviews/` | 同上 |
| `ops/crontab.txt` | `archive/ops/` | 個人Mac（`/Users/samukawakazuma/invest`）依存。GitHub Actions へ移行 |

### E. 削除しなかったもの（記録）

| 対象 | 残す理由 |
|---|---|
| `db/migrations/0001`〜`0004`（BIOS 期のスキーマ） | **適用済みマイグレーションの編集・削除は禁止**（後方互換原則）。SQL 内の `bios_forbid_mutation()` という関数名もそのまま残る。MIOS のテーブルは `0005` 以降で追加し、旧テーブルは参照をやめるだけにする |
| `market_snapshots` / `decisions` 等の旧テーブル | append-only トリガが載っており、DROP も UPDATE も DB が拒否する。**参照停止のみ**とし、過去データを物理削除しない |
| `src/mios/knowledge/` 一式 | Event / Evidence / as-of Timeline はマクロイベントにそのまま使える |
| `src/mios/extraction/news.py` | RSS → curation queue は資産非依存。Phase 6 の News Agent の土台になる |
| `src/mios/analysis/{models,stats,repo}.py` | `Signal`/`DimensionReport` の説明可能性と min-sample 規律は MIOS の中核要件 |
| `src/mios/scoring/composite.py` | weight × score・対立指数・データ完全性の算術は資産非依存 |
