# REPOSITORY_AUDIT.md
# 既存リポジトリ監査報告 — BIOS → MIOS (Macro Intelligence Operating System)

> 監査日：2026-09-12 ／ 監査対象コミット：`2b9f925` (main = claude/compassionate-keller-a86i62)
> 目的：Bitcoin Intelligence OS (BIOS) を Gold(XAUUSD) / USDJPY 向け
> マクロ経済分析・予測基盤 (MIOS) へ転換するための、全ファイル分類と移行計画。
>
> **本監査の段階ではコード変更を一切行っていない。** 変更は本書の承認後に開始する。

---

## 0. サマリ（先に結論）

| 観点 | 結論 |
|---|---|
| コード総量 | `src/` 5,219行 / 74ファイル、`tests/` 1,440行 / 16ファイル、`docs/` 約2,850行 |
| 品質ゲート | `ruff` / `ruff format` / `mypy --strict` / `pytest` すべてPASS（unit 75件）。**ただし統合テスト16件はPostgreSQL未接続のため既定でskip** |
| 再利用価値 | **高い。** 収集フレームワーク・時刻規律・監査ログ・ID規約・層境界テストは資産クラス非依存に作られており、ほぼそのまま流用できる |
| Bitcoin依存 | **浅い。** Bitcoin固有はYAML設定・3つのanalyzer・seed 2件・ドキュメントに集中。中核フレームワークはBTCを知らない |
| 最大の問題 | **①LLM Agentが1つも実装されていない（全て設定だけの空箱）、②予測値を保存するテーブルが存在しない、③vintage / as-of データの概念が市場データ側に無い** |
| 削除すべき量 | src の約 **25%**（1,300行相当）＝ scenario / portfolio / backtest(P&L) / btc専用analyzer / 空パッケージ |
| 新規に必要な量 | 概算 2,500〜3,500行（calendar / macro data / vintage store / forecast engine / validation / report） |
| 重大な前提条件 | 現在 **CIが存在しない**（`.github/` なし）。日次自動化は `ops/crontab.txt` の個人Mac（`/Users/samukawakazuma/invest`）1台に依存している |

---

## 1. Current Architecture（現在の構造）

### 1.1 物理構成

```
invest/
├── config/          # YAML設定ツリー（挙動をコード変更なしで変える層）
│   ├── agents.yaml          # Agent 8体の実行envelope（※コードから未使用）
│   ├── pipelines.yaml       # cronジョブ定義 10本
│   ├── scoring.yaml         # 次元別ウェイト（7次元 × 6フェーズ）
│   ├── assets/btc.yaml      # 資産定義 1件のみ
│   ├── sources/*.yaml       # データソース 10件
│   └── taxonomy/*.yaml      # events(60型) / entities(23種) / relationships(3クラス)
├── db/migrations/   # 0001-0004、計19テーブル
├── docs/            # 設計書（Constitution が最上位）＋ sprint報告 6件
├── ops/             # crontab / backup.sh
├── prompts/         # README のみ（プロンプト実体ゼロ）
├── seeds/chains/    # Mt.Gox / FTX の歴史イベントseed
├── src/bios/        # 本体 15サブパッケージ
└── tests/           # unit 14 / integration 3
```

### 1.2 論理構成（7層 + 横断層）

import方向は一方向に強制されており、`tests/unit/test_architecture.py` がAST解析で違反を検出する。
これは本リポジトリで**最も価値の高い仕掛けの一つ**であり、MIOSでもそのまま維持する。

```
L0 横断    common（ID・時刻・schema・labels・errors・state）
           config（YAMLロード＋Settings）  audit（append-only 監査）  storage（psycopg薄ラッパ）
   ↓
L1 収集    ingestion（adapter framework / http / rawstore / dlq / health / collector）
           scheduler（jobs / retry / breaker / ratelimit）
   ↓
L2 正規化  extraction（news → curation queue、market → snapshot）
   ↓
L3 知識    knowledge（models / store / graph / timeline / snapshots / curation）
           history（seed loader）
   ↓
L4 分析    analysis（base / models / stats / onchain / derivatives / news_flow / reactions / repo）
           similarity（空）
   ↓
L5 統合    scoring（composite / regime）  scenario（engine）
   ↓
L6 判断    decision（engine / outcomes / portfolio / backtest / alerts）
   ↓
L7 出力    reporting（brief / why）
           agents（空）
```

`src/bios/cli.py`（480行）が唯一の composition root で、全層をimportして配線する。

### 1.3 実行フロー（現行 `ops/crontab.txt`）

```
*/15 run-due   → collect（10ソース）
05:30 extract  → RSS raw → curation_queue（人間承認待ち）
06:00 snapshot → 最新raw → market_snapshots 1行
06:05 react    → イベント後 +1h..+90d のリターンを刻印
06:10 analyze  → 3 analyzer → dimension_reports
06:20 decide   → regime → score_card → scenario → decision → 仮想売買 → alert
06:25 validate → 過去decisionを +1d..+90d で採点
```

---

## 2. Current Agents（現在のAgent）

### 2.1 設計上のAgent（`config/agents.yaml`）

| agent | model | 用途（設計） | **実装状況** |
|---|---|---|---|
| news | claude-sonnet-5 | ニュース14項目分析 | **未実装** |
| knowledge_graph | claude-sonnet-5 | Entity抽出・名寄せ | **未実装** |
| similarity | claude-fable-5 | 類似事例検索 | **未実装** |
| scenario | claude-fable-5 | シナリオ生成 | **未実装** |
| critic | claude-fable-5 | 反対意見生成 | **未実装** |
| risk | claude-fable-5 | リスク評価 | **未実装** |
| report | claude-sonnet-5 | レポート生成 | **未実装** |
| qa | claude-haiku-4-5 | 監査 | **未実装** |

### 2.2 監査結果：**LLM Agentは1体も存在しない**

grep で検証済みの事実：

- `src/bios/agents/__init__.py` は docstring 1行のみ。中身ゼロ。
- `prompts/` に `.md` プロンプトファイルは1つも存在しない（README のみ）。
- `AgentsConfig` / `AgentSpec` は `config/` パッケージ外から**一度も参照されていない**。
  `load_config()` が読んで検証はするが、誰も使わない。
- `AgentRunRecord` にはLLM用フィールド（model / tokens / cost）があるが、
  実際に書いているのは `Collector` だけで、常に `model="-"`, `prompt_version="-"`。

つまり現在稼働している「知能」は**全てルールベース**である。
LLMが数値を捏造する余地は現状ゼロ（これは方針17に照らせば良いこと）だが、
「Agent 8体」という記述はドキュメント上の願望にすぎない。

### 2.3 実際に動いているルールベース処理（＝事実上のAgent）

| 処理 | 実体 | BTC依存 |
|---|---|---|
| Collector | `ingestion/collector.py` | なし |
| News extractor | `extraction/news.py` | なし（RSS汎用） |
| Market normalizer | `extraction/market.py` | **強い**（METRIC_PATHS がBTCソース固定） |
| Derivatives analyzer | `analysis/derivatives.py` | **強い**（funding / OI） |
| Onchain analyzer | `analysis/onchain.py` | **完全にBTC専用** |
| News flow analyzer | `analysis/news_flow.py` | **強い**（Fear&Greed） |
| Regime classifier | `scoring/regime.py` | 弱い（価格SMAのみ。汎用化可能） |
| Scoring engine | `scoring/composite.py` | なし（次元名のみ設定依存） |
| Scenario engine | `scenario/engine.py` | なし（ただし後述のとおり中身が無い） |
| Decision engine | `decision/engine.py` | なし（BUY/WAIT/TAKE_PROFIT語彙に依存） |

---

## 3. Current Data Sources（現在のデータソース）

| source_id | kind | Tier | 内容 | MIOSでの扱い |
|---|---|---|---|---|
| src_sec_press_rss | rss | 1 | SEC報道発表 | DELETE（暗号資産規制向け） |
| src_coindesk_rss | rss | 3 | CoinDesk | DELETE |
| src_cointelegraph_rss | rss | 4 | Cointelegraph | DELETE |
| src_coingecko_btc | http_json | 2 | BTC価格・出来高 | DELETE |
| src_bybit_btc_derivs | http_json | 2 | Funding / OI | DELETE |
| src_fng_alternative | http_json | 3 | Fear & Greed | DELETE |
| src_mempool_hashrate | http_json | 1 | ハッシュレート | DELETE |
| src_blockchain_info_stats | http_json | 2 | オンチェーン統計 | DELETE |
| **src_fred_dgs10** | http_json | 1 | 米10年金利 | **KEEP（MIOSの起点）** |
| **src_fred_cpi** | http_json | 1 | CPIAUCSL | **KEEP（MIOSの起点）** |

### 3.1 重大な発見

1. **マクロ系ソースは2本しかなく、しかも一度も収集されていない可能性が高い。**
   両方とも `${FRED_API_KEY}` を要求し、未設定時は `resolve_sources()` により自動で
   `enabled=False` になる。Sprint 6報告の「ALERT[warning] data_gap ×2：FRED未設定ソースを検知」が
   これを裏付けている。→ **MIOSが必要とするマクロ時系列の実データは、リポジトリ内にもDB内にも存在しないと仮定して設計すべき。**

2. **adapter kind は `rss` と `http_json` の2種類のみ**（`SourceSpec.kind` が `Literal`）。
   MIOSで必要になる CSV（BLS / Treasury / 日銀）、XML、HTMLテーブルは
   **新しいkindの追加＝フレームワーク変更**になる。ただし追加は容易（`adapters/` に1ファイル + `_KINDS` に1行）。

3. **本サンドボックス環境からは外部データソースへ到達できない。**
   検証済み：`api.stlouisfed.org`, `www.bls.gov`, `home.treasury.gov`, `query1.finance.yahoo.com`,
   `stooq.com`, `www.federalreserve.gov` — すべてプロキシが CONNECT を 403 で拒否。
   → **実データ収集の検証は GitHub Actions（またはオーナーのローカル）でしか行えない。**
   開発時は「記録済みfixtureに対するテスト」と「本番はActions」の二段構えが必須。

---

## 4. Current Database Schema（現在のDBスキーマ）

19テーブル。append-only制約はDBトリガ `bios_forbid_mutation()` で物理強制されている。

| # | テーブル | append-only | 内容 | MIOS判定 |
|---|---|---|---|---|
| 1 | schema_migrations | – | マイグレーション台帳 | KEEP |
| 2 | sources | – | ソース台帳（YAMLのミラー） | KEEP |
| 3 | entities | – | Entityマスタ | MODIFY（kind群をマクロ向けへ） |
| 4 | event_chains | – | イベント連鎖 | MODIFY（縮小 or DELETE） |
| 5 | **events** | **✓** | 出来事（occurred_at / known_at 分離） | **KEEP（中核）** |
| 6 | **evidences** | **✓** | 証拠（URL / tier / retrieved_at） | **KEEP（中核）** |
| 7 | event_evidences | – | 多対多リンク | KEEP |
| 8 | event_participations | – | Event×Entity 役割 | MODIFY |
| 9 | event_relations | ✓ | Event×Event（因果には証拠必須） | KEEP（縮小） |
| 10 | curation_queue | – | 人間承認待ち | KEEP |
| 11 | **market_snapshots** | – | 資産×時刻のメトリクス | **REPLACE（後述の致命的問題）** |
| 12 | audit_log | ✓ | 監査 | KEEP |
| 13 | agent_runs | ✓ | 実行記録（model/token/cost） | KEEP |
| 14 | extraction_state | – | 抽出済みraw管理 | KEEP |
| 15 | dimension_reports | – | 次元スコア | MODIFY（upsert→append-only化） |
| 16 | market_reactions | – | イベント後リターン | MODIFY（イベント→指標サプライズへ） |
| 17 | regimes | – | 市場体制 | MODIFY |
| 18 | score_cards | ✓ | 総合スコア | KEEP（次元定義を差し替え） |
| 19 | scenario_sets | ✓ | シナリオ確率 | DELETE |
| 20 | decisions | ✓ | BUY/WAIT/TAKE_PROFIT | DELETE |
| 21 | decision_outcomes | ✓ | 判断採点 | REPLACE（→forecast採点） |
| 22 | virtual_positions | – | 仮想建玉 | DELETE |
| 23 | virtual_trades | ✓ | 仮想約定 | DELETE |
| 24 | alerts | ✓ | アラート | KEEP |

### 4.1 スキーマ上の致命的な問題

**問題A：`market_snapshots` に vintage の概念が無い**

```sql
PRIMARY KEY (asset_id, ts)
...
ON CONFLICT (asset_id, ts) DO UPDATE SET
    asset_metrics = market_snapshots.asset_metrics || EXCLUDED.asset_metrics
```

JSONBを `||` でマージ上書きしている。暗号資産の「その時刻の価格」なら成立するが、
**経済指標では成立しない**：

- CPIは発表後に季節調整が改定される。上書きすると「当時市場が見ていた値」が永久に失われる。
- NFPは翌月・翌々月に2回改定される。`previous` と `revised_previous` を区別できない。
- 「参照期間（2026年8月分）」と「発表日（2026年9月11日）」を保持する列が**1つも無い**。
  `ts` しかなく、これは `utc_now()` の時刻である。

→ 指示書 §14 / §15 の要求（actual / forecast / previous / revised_previous / surprise / vintage_timestamp）は
現スキーマでは**表現不可能**。REPLACE 確定。

**問題B：予測値を保存するテーブルが存在しない**

`scenario_sets` はシナリオ確率を持つが、「次回CPIは3.3%と予測した」を保存する場所がない。
指示書 §13（Prediction Vintage：予測値の上書き禁止・日次保存）を満たすテーブルはゼロから作る必要がある。

**問題C：`events` テーブルは経済カレンダーを保持できない**

```sql
CHECK (known_at >= occurred_at - interval '1 day')
```

「次回FOMCは2026-10-28」のような**未来の予定**は `occurred_at` が未来、`known_at` が現在となり、
この制約に違反する。経済カレンダーは別テーブル（`economic_calendar`）が必要。

**問題D：derived テーブルが軒並み upsert で履歴を潰す**

`dimension_reports` (PK: asset,dimension,as_of)、`regimes` (PK: asset,date) はいずれも
`DO UPDATE` で再計算結果を上書きする。「昨日の分析はこうだった」が再現できない。
MIOSでは**予測に関わる derived データは append-only + version列**にしなければならない。

---

## 5. Bitcoin-specific Components（Bitcoin固有部分）

| 種別 | パス | 行数 | 備考 |
|---|---|---|---|
| 資産定義 | `config/assets/btc.yaml` | 25 | metrics 17件（funding/OI/MVRV/hashrate...） |
| ソース | `config/sources/src_{coindesk,cointelegraph,coingecko,bybit,fng,mempool,blockchain_info,sec_press}*.yaml` | 8ファイル | Tier 1-4 |
| パイプライン | `config/pipelines.yaml` のjob 8本 | – | 上記ソースに対応 |
| タクソノミ(event) | `config/taxonomy/events.yaml` | 60型 | うちマクロ流用可は `macro.*` 8型のみ。残り52型はBTC/暗号資産固有 |
| タクソノミ(entity) | `config/taxonomy/entities.yaml` | 23種 | `token/stablecoin/blockchain/wallet_cluster/miner/protocol` 等がBTC固有 |
| スコアリング | `config/scoring.yaml` | 7次元 | `onchain / derivatives / supply / demand` がBTC固有 |
| Analyzer | `src/bios/analysis/onchain.py` | 86 | ハッシュレート・MVRV・SOPR。**完全にBTC専用** |
| Analyzer | `src/bios/analysis/derivatives.py` | 107 | funding rate / open interest |
| Analyzer | `src/bios/analysis/news_flow.py` | 83 | Fear & Greed（暗号資産専用指数） |
| 正規化 | `src/bios/extraction/market.py` の `METRIC_PATHS` | 40 | 5ソース分のdotted-path表。**全てBTCソース** |
| Seed | `seeds/chains/mtgox.yaml` / `ftx.yaml` | 234 | 歴史データ（削除禁止・ARCHIVE対象） |
| 語彙 | `common/labels.py` の `Dimension` / `Action` | 30 | `Action(BUY/WAIT/TAKE_PROFIT)` は「売買判断」前提 |
| ID | `common/ids.py` の `IdKind.{PATTERN,OVERHANG,ANOMALY}` | 3行 | BTC分析用。**未使用**（定義のみ） |
| 命名 | パッケージ名 `bios`、`ent_asset_btc` 前提の `_asset_slug()` | – | 全ファイルに波及 |
| ドキュメント | Constitution / MSD / IES / DATA_SOURCE_REGISTRY | 約2,170行 | Bitcoin前提で書かれている |

**重要：Bitcoin依存は「広く浅い」。**
`src/` 5,219行のうち、BTC固有ロジックは概算 **約450行（8.6%）**にすぎない。
残りは資産を知らないフレームワークである。これが本リポジトリの最大の資産価値。

---

## 6. Reusable Components（再利用できるもの）＝ KEEP

### 6.1 無修正で使えるもの（★＝MIOSの要求に直接刺さる）

| パス | 行 | 再利用理由 |
|---|---|---|
| ★ `common/timeutil.py` | 41 | **naive datetime を境界で拒否**。vintage / as-of 規律の土台。指示書 §15 の前提 |
| ★ `common/ids.py` | 125 | opaque / slug / dated の3系統。`evt_2026-09-11_us-cpi-aug` がそのまま書ける |
| `common/schema.py` | 27 | `BiosRecord`（frozen）/ `BiosModel`。extra="forbid" でタイポが落ちる |
| `common/errors.py` | 21 | 例外階層 |
| `common/statestore.py` | 34 | 原子的JSON状態保存（tmp+rename） |
| `common/logutil.py` | 53 | JSON行ログ。Actions向けに有用 |
| ★ `ingestion/` 全体 | 458 | adapter / http（条件付きGET）/ rawstore（sha256重複排除・永久保存）/ dlq / health / collector。**provider追加がYAML 1枚で済む設計**。MIOSのFRED/BLS/Treasury/日銀に完全に流用可 |
| ★ `scheduler/` 全体 | 248 | retry（指数バックオフ）/ breaker（連続失敗で遮断）/ ratelimit / jobs。BLS・FRED のレート制限対策にそのまま必要 |
| ★ `audit/` 全体 | 163 | append-only 監査。指示書 §26-3/4（source URL・timestamp保存）と §22（失敗の明示）に対応 |
| `storage/db.py` `migrate.py` `sync.py` | 131 | psycopg薄ラッパ。ORMなし。1ファイル1トランザクションのマイグレーション |
| `config/loader.py` `settings.py` | 131 | YAML→typed。起動時に全検証、1つでも壊れたら起動拒否 |
| ★ `knowledge/timeline.py` | 77 | **`as_of` で `known_at` を切る唯一の正しいクエリ**。指示書 §20（Data Leakage防止）の既存実装 |
| `knowledge/store.py`（EventStore部） | 150 | 「証拠なきEventは書けない」をトランザクション内で強制 |
| `knowledge/models.py`（Event/Evidence） | 145 | occurred_at / known_at / confidence / status(supersedes) |
| `knowledge/curation.py` | 88 | 人間承認ループ |
| ★ `analysis/stats.py` | 34 | **min_n=30 未満は None を返す**（薄い履歴で数字を作らない）。指示書 §26-2 の既存実装 |
| ★ `analysis/models.py` | 77 | `Signal(value, points, label, rationale, evidence_refs)` + `DimensionReport`。**指示書 §18「なぜ+0.8になったか再現できないスコアは禁止」をすでに満たす形** |
| `analysis/base.py` | 45 | analyzer Protocol（I/O禁止＝純関数）。テスト容易 |
| ★ `scoring/composite.py` | 171 | weight × score、**conflict_index（対立を平均で消さない）**、data_completeness。指示書 §18 のScore群にそのまま転用可 |
| `analysis/repo.py` | 80 | derived永続化（要append-only化） |
| `reporting/why.py` | 96 | 判断→スコア→シグナル→証拠→Tier の全展開 |
| ★ `tests/unit/test_architecture.py` | 77 | AST解析による層境界強制。**新設計でも最初に移植すべき** |
| `Makefile` / `pyproject.toml` | 60 | ruff + mypy strict + pytest。`make check` が既に成立 |

### 6.2 設計思想として継承するもの（コードではなく規律）

- **Fact → Evidence → Timeline → ... → Decision の一方向パイプライン**（Constitution 第2条）
  → MIOSの `Raw → Normalized → Historical → ... → Report` はこれと同型。
- **append-onlyをDBトリガで物理強制**（訂正は supersede 行の追加）。
- **Tier制度**（Tier1公式 / Tier2集計 / Tier3大手報道 / Tier4二次）。指示書 §16 とほぼ一致。
  ただし現行は Tier1-4 の `SourceTier` IntEnum と、DATA_SOURCE_REGISTRY.md の Tier1-5 が**食い違っている**（後述 §7）。
- **データ欠損の明示**（`data_gaps` を必ず出力。沈黙禁止）。指示書 §26-10 と一致。
- **設定でふるまいを変え、コードは変えない**（P10）。

---

## 7. Duplicate Components（重複）

| # | 重複 | 実体 | 対処 |
|---|---|---|---|
| D-1 | ID検証ヘルパ | `ingestion/rawitem.py::_pydantic_id` と `knowledge/models.py::_vid` が同一処理。さらに `ingestion/dlq.py` が**private関数 `_pydantic_id` を他モジュールからimport**している | `common/ids.py` に `pydantic_id_validator()` として公開1本化 |
| D-2 | `verdict_for` という同名関数が2つ | `scoring/composite.py`（composite→強気弱気ラベル）と `decision/outcomes.py`（action+return→correct/incorrect）。意味が全く違う | decision側はDELETE対象なので自然消滅 |
| D-3 | ソース台帳が3箇所 | ①`config/sources/*.yaml`（真実）②`sources` テーブル（`sync_sources` でミラー）③`var/state/health.json`（死活） | 構造としては妥当（FK用ミラー）。KEEPするが、DATA_SOURCE_REGISTRY.md（人間向け表）は④番目の手書き台帳になっており**同期が保証されていない** → docs側を「生成物」にするか削除 |
| D-4 | Tier定義の不一致 | `common/labels.py::SourceTier` は **1-4**、DBの CHECK も **1-4**、しかし `docs/DATA_SOURCE_REGISTRY.md` は **Tier 1-5**（Tier5=SNS）を定義 | 指示書 §16 は Tier1-4。**コード側(1-4)に統一し、ドキュメントを修正** |
| D-5 | ドキュメントのスタブ3件 | `docs/SYSTEM_ARCHITECTURE.md` / `DATA_MODEL_AND_KNOWLEDGE_GRAPH.md` / `AI_AGENT_SPECIFICATION.md` はいずれも「MSDに統合されました」の5行リダイレクトのみ | DELETE（リンク維持の価値より、探索ノイズの害が大きい） |
| D-6 | 生データの保存先が2系統 | ファイル (`var/raw/<source>/<YYYY-MM>/*.json`) と、DBの `evidences.raw_item_id`（FKなし・文字列参照） | 指示書 §21 の `data/raw` 構成に合わせ、**ファイルを正とし、DBは参照IDのみ**に規律を明文化 |
| D-7 | 「変化の記録」が2箇所 | `decisions.delta_from_yesterday`（文字列）と `alerts`（イベント） | MIOSでは §12（昨日との差分）を**構造化テーブル**に一本化 |

---

## 8. Unused / Unnecessary Components（未使用・不要）

grep で実際に参照ゼロを確認したもの：

| # | 対象 | 状態 | 根拠 |
|---|---|---|---|
| U-1 | `src/bios/agents/` | **空パッケージ**（docstring 1行） | `bios.agents` への参照は egg-info 以外ゼロ |
| U-2 | `src/bios/similarity/` | **空パッケージ**（docstring 1行） | 参照は `audit/records.py` のコメント文字列のみ |
| U-3 | `config/agents.yaml`（8 agent定義） | **ロードされるが一度も使われない** | `AgentsConfig`/`AgentSpec` の参照は `config/` パッケージ内のみ |
| U-4 | `prompts/` | README のみ。プロンプト実体ゼロ | `.md` ファイルなし |
| U-5 | `IdKind.PATTERN` / `OVERHANG` / `ANOMALY` | 定義とfrozenset登録のみ。生成も検証もされない | grep hit = 定義行のみ |
| U-6 | `Dimension.SUPPLY` / `DEMAND` / `MACRO` | **コード内で一度も使われない**（analyzerが存在しない） | grep hit = 0 |
| U-7 | `config/scoring.yaml` の 6フェーズ × 7次元ウェイト | 実際に選択されるのは `default` と `liquidity_tightening` のみ。`regime.phase_key()` が他4つを返す経路が存在しない | `accumulation/markup/distribution/markdown` は到達不能 |
| U-8 | `config/assets/btc.yaml` の metrics 17件 | 実際に `METRIC_PATHS` で埋まるのは6件。残り11件は永久に欠損 | – |
| U-9 | `analysis/onchain.py::UNAVAILABLE_METRICS`（8件） | **構造的に必ず data_gap を生成するだけのリスト**。毎日8件のノイズを出す | 「有料ソース未契約」の表明にすぎず、分析価値ゼロ |
| U-10 | `reporting/brief.py:42` | `chains = TimelineEngine(self._db)  # noqa: F841 - reserved for chain expansion` | **linterを黙らせて残した死コード**。指示書 §26-20 の典型例 |
| U-11 | `common/labels.py::ChainStatus` / event_chains 一式 | seed 2件でしか使われない。MIOSで「連鎖」が必要かは未検証 | 縮小候補 |
| U-12 | `scenario/engine.py`（137行） | 確率＝`1/3 ± composite/100×0.15`。**これは統計ではなく composite の線形変換**。docstring 自身が「統計ではない」と明記 | 指示書 §26「検証できないheuristic」「根拠が追跡できないscore」に該当 → DELETE |
| U-13 | `.github/` | **存在しない** | CI・スケジュール実行が一切ない |

---

## 9. Components to DELETE（削除するもの）

> **原則**：削除するのは「コード・設定・ドキュメント」のみ。
> 実測データ・過去予測・過去価格・過去ニュース・過去分析結果は**一切削除しない**（指示書 §4）。
> 幸い、これらは `var/`（git管理外）と PostgreSQL にのみ存在し、**リポジトリには1バイトも入っていない**（git履歴全体を検査済み）。
> したがって「コード削除によるデータ消失リスクはゼロ」である。ただし §10 の退避手順は必ず実行する。

### 9.1 コード（概算 1,300行）

| 対象 | 行 | 削除理由 |
|---|---|---|
| `src/bios/analysis/onchain.py` | 86 | Bitcoin専用。Goldにハッシュレートは無い |
| `src/bios/analysis/derivatives.py` | 107 | funding/OIは暗号資産perp固有。※先物CoT/建玉は将来別実装 |
| `src/bios/analysis/news_flow.py` | 83 | Fear&Greed（暗号資産専用指数）依存 |
| `src/bios/scenario/engine.py` | 137 | 検証不能な擬似確率（U-12） |
| `src/bios/decision/engine.py` | 175 | BUY/WAIT/TAKE_PROFIT は売買助言。MIOSの目的（指標予測）と無関係 |
| `src/bios/decision/portfolio.py` | 70 | 仮想建玉。予測精度検証には不要 |
| `src/bios/decision/backtest.py` | 120 | 売買P&L vs Buy&Hold。**CPI予測の巧拙を一切測らない** |
| `src/bios/decision/outcomes.py` | 109 | ±2%/±5%バンドの方向採点。REPLACE（→ forecast誤差採点）として作り直す |
| `src/bios/similarity/__init__.py` | 1 | 空 |
| `src/bios/agents/__init__.py` | 1 | 空（※MIOSでLLM分類Agentを作る際に**中身を持って**復活させる） |
| `src/bios/analysis/reactions.py` | 85 | イベント→価格リターン刻印。MODIFY候補だが、MIOSでは「指標サプライズ→資産反応」に作り替えるためREPLACE扱い |
| `src/bios/extraction/market.py` の `METRIC_PATHS` | 40 | BTCソース固定表 |
| 対応するテスト | ~300 | `test_analysis.py` / `test_backtest.py` / `test_intelligence.py` の該当部 |

### 9.2 設定

- `config/assets/btc.yaml`
- `config/sources/` の8ファイル（FRED 2本を除く全て）
- `config/pipelines.yaml` の該当job 8本
- `config/taxonomy/events.yaml` の52型（`macro.*` 8型を残して全面書き換え）
- `config/taxonomy/entities.yaml` の暗号資産系kind
- `config/scoring.yaml`（次元ごと全面差し替え）
- `config/agents.yaml`（実装を伴って再作成するまで削除）

### 9.3 ドキュメント

- `docs/SYSTEM_ARCHITECTURE.md` / `DATA_MODEL_AND_KNOWLEDGE_GRAPH.md` / `AI_AGENT_SPECIFICATION.md`（スタブ3件）

### 9.4 DBテーブル（マイグレーションで DROP せず、**新スキーマへ移行後に別マイグレーションで整理**）

`scenario_sets` / `decisions` / `decision_outcomes` / `virtual_positions` / `virtual_trades`

> **注意**：append-onlyトリガが載っているテーブルは DROP も TRUNCATE も通常の権限では拒否される。
> 削除は「新DBへ必要データのみ移送」ではなく「旧テーブルを残したまま参照をやめる」方式を推奨（§16 参照）。

---

## 10. Components to ARCHIVE（アーカイブするもの）

**削除ではなく `archive/` へ退避し、git履歴とファイル双方で残す。**

| 対象 | 理由 |
|---|---|
| `seeds/chains/mtgox.yaml` / `ftx.yaml` | **歴史イベントの実データ**。指示書 §4により削除禁止。MIOSでは使わないが、構造化済み歴史データとして価値がある → `archive/seeds/btc/` |
| `docs/PROJECT_CONSTITUTION.md`（旧版） | 思想の出典。MIOS版Constitutionを新規作成し、旧版は `archive/docs/bios/` へ |
| `docs/MASTER_SYSTEM_DESIGN.md`（1,243行） | 大半がBitcoin前提だが、§2（層設計）§13（物理スキーマ）§15（パイプライン）§18（非機能）は普遍的。**MIOS設計書に抜粋移植した上で**全文を `archive/docs/bios/` へ |
| `docs/INTELLIGENCE_ENGINE_SPECIFICATION.md`（725行） | 同上。§11（Scoring 3層透明性）§13（検証）は移植価値あり |
| `docs/EVALUATION_AND_CALIBRATION.md` | **Brier / キャリブレーション曲線 / 見逃し検知 / プロセスと結果の分離** — これは資産に依存しない。**MIOSの検証設計のベースとして昇格させる**（archiveではなくMODIFY） |
| `docs/DATA_SOURCE_REGISTRY.md` | Tier制度の記述は流用。ソース一覧はマクロ向けに全面差し替え → MODIFY |
| `docs/sprints/*.md`（6件） | BIOS開発の判断記録。`archive/docs/bios/sprints/` へ |
| `docs/reviews/SPRINT_01_ARCHITECTURE_REVIEW.md` | 同上 |
| `docs/adr/ADR-009-psycopg-driver.md` | **現行も有効**（psycopg継続）→ KEEP |
| `ops/crontab.txt` | 個人Mac依存。GitHub Actions へ移行後 `archive/ops/` へ |
| 削除する `analysis/onchain.py` 等 | git履歴に残るため物理アーカイブ不要。ただし §9 の削除一覧を `docs/DELETION_LOG.md` に記録する |

### 10.1 削除記録の義務（指示書 §4）

`docs/DELETION_LOG.md` を新設し、削除ごとに以下を記録する：

```
| 日付 | 対象 | 種別(code/config/doc/data) | 削除理由 | 復元方法 |
```

**データ（`var/` / PostgreSQL）については、作業開始前に必ず以下を実行してオーナーの手元に退避する：**

```bash
pg_dump --format=custom --file=bios-pre-mios-$(date -u +%Y%m%d).dump "$DATABASE_URL"
tar -czf var-pre-mios-$(date -u +%Y%m%d).tar.gz var/
```

---

## 11. Components to MODIFY（修正して使うもの）

| 対象 | 修正内容 |
|---|---|
| `common/labels.py` | `Dimension` をマクロ次元（growth / inflation / labor / fed / boj / rates / fx / risk）へ差し替え。`Action`（BUY/WAIT/TAKE_PROFIT）を削除し、代わりに `Direction`（upside/downside/inline）を導入。`SourceTier` は 1-4 のまま維持 |
| `common/ids.py` | `IdKind` から PATTERN/OVERHANG/ANOMALY/DECISION/SCORE_CARD を外し、`FORECAST`(fc_) / `RELEASE`(rel_) / `SERIES`(ser_) / `CALENDAR`(cal_) を追加 |
| `config/models.py` | `SourceSpec.kind` の Literal に `csv` / `xml` を追加。`AssetConfig` をマクロ資産（XAUUSD/USDJPY）向けに再定義 |
| `ingestion/adapters/` | `csv.py`（BLS/Treasury/日銀のCSV配信用）を追加。既存2kindはそのまま |
| `extraction/market.py` | `METRIC_PATHS` をマクロ系列マッピングへ全面差し替え。**同時に重大バグを修正**：現在 `store.latest(source_id)` を無条件で「今の時刻のスナップショット」として書き込むため、3日前に取得した古いrawが今日の値として記録される（§14-L4参照） |
| `knowledge/snapshots.py` | vintage対応スキーマへ書き換え（`observation_date` / `release_date` / `vintage_at` / `revision_n`） |
| `analysis/repo.py` | upsert → append-only + `computed_at` へ |
| `scoring/composite.py` | 次元名の差し替えのみ。ロジック（weight/conflict/completeness）は維持 |
| `scoring/regime.py` | BTC価格ベース → マクロレジーム（inflation regime / policy regime / risk regime）へ |
| `reporting/brief.py` | 端末出力の整形 → `reports/daily/YYYY-MM-DD.md` のMarkdown生成へ |
| `reporting/why.py` | decision参照 → forecast参照へ |
| `decision/alerts.py` | signal/breaker/data_gap の枠組みは維持。参照先をforecastへ |
| `docs/EVALUATION_AND_CALIBRATION.md` | **昇格**。Brier / calibration / 見逃し検知をCPI・NFP予測向けに書き直し、MIOSの検証設計書とする |
| `tests/unit/test_architecture.py` | `ALLOWED` テーブルを新パッケージ構成へ更新 |
| `pyproject.toml` / `Makefile` | パッケージ名 `bios` → `mios`。`make daily-report` ターゲット追加 |
| `README.md` | 全面書き換え |

---

## 12. New Components Required（新規に必要なもの）

### 12.1 パッケージ構成（指示書 §21 に準拠しつつ既存層設計を維持）

```
src/mios/
├── common/        [KEEP] ids / timeutil / schema / labels / errors / statestore / logutil
├── config/        [KEEP] loader / settings / models
├── audit/         [KEEP]
├── storage/       [KEEP] db / migrate / sync
├── scheduler/     [KEEP] jobs / retry / breaker / ratelimit
├── ingestion/     [KEEP+] adapter / http / rawstore / dlq / health / collector / adapters{rss,http_json,csv}
│
├── calendar/      [NEW] Agent 1: 経済指標カレンダー
├── data/          [NEW] Agent 2: マクロ指標の正規化・vintage保存
├── markets/       [NEW] Agent 3: 金利・為替・コモディティ
├── forecasts/     [NEW] Agent 4: 機関投資家予測
├── news/          [NEW] Agent 5: ニュース分類（taxonomy 20分類）
├── prediction/    [NEW] Agent 6: CPI/NFP予測（最重要）
├── analysis/      [MOD] Agent 7: スコア＋クロスアセット
├── reports/       [MOD] Agent 8: 日次Markdown
└── validation/    [NEW] 予測精度検証（MAE/RMSE/方向/キャリブレーション）
```

**Agentは8つ。指示書の指定どおりで、増やさない。** 各Agentは1サブパッケージ＝1責務。

### 12.2 新規DBテーブル（最小構成）

| テーブル | 目的 | append-only |
|---|---|---|
| `economic_calendar` | 発表予定（指標・予定日時・重要度・国） | 予定はUPDATE可、確定行は追加 |
| `series` | 系列マスタ（series_id / 指標名 / 単位 / 国 / 頻度 / source_id） | – |
| **`observations`** | **vintage対応の観測値。PK = (series_id, observation_date, vintage_at)** | **✓** |
| **`releases`** | 発表イベント：actual / forecast(consensus) / previous / revised_previous / surprise / standardized_surprise / release_at / source_url | **✓** |
| **`predictions`** | **自システムの予測。PK = (target_series, target_period, predicted_at)。上書き禁止（指示書 §13）** | **✓** |
| `institutional_forecasts` | 機関予測：institution / target / value / previous_value / change / reason / source_url / published_at | ✓ |
| `news_items` | source / published_at / title / summary / entities / category / affected_asset / direction / importance / source_tier / url | ✓ |
| `macro_scores` | growth/inflation/labor/fed/boj/usdjpy_bias/gold_bias + 入力・weight・計算式・timestamp | ✓ |
| `daily_deltas` | 前日比（項目 / 昨日値 / 今日値 / 変化量 / 単位） | ✓ |
| `forecast_errors` | predictions × releases の突合結果（error / abs_error / direction_hit） | ✓ |

`observations` が vintage の要。**同じ (series, observation_date) に複数の vintage 行が並び、
「2026-09-01時点で見えていた値」は `WHERE vintage_at <= '2026-09-01'` の最新行で再現できる。**
これが指示書 §15 / §20（look-ahead 防止）の構造的な解になる。

### 12.3 新規データソース（公開・無料を優先）

| カテゴリ | ソース | Tier | 備考 |
|---|---|---|---|
| 米指標（横断） | **FRED API**（ALFREDのvintage含む） | 1 | 要 API key（無料）。**ALFREDは vintage 取得の本命** |
| 雇用 | BLS Public Data API | 1 | 無料枠あり |
| 物価 | BLS（CPI/PPI）、BEA（PCE） | 1 | |
| 金利 | US Treasury `daily_treasury_yield_curve` | 1 | key不要 |
| 実質金利/BEI | FRED（DFII5/DFII10/T5YIE/T10YIE） | 1 | |
| 日本 | e-Stat / 総務省統計局（CPI）、日銀時系列統計 | 1 | |
| JGB | 財務省 金利情報（CSV） | 1 | key不要 |
| Fed | FOMC カレンダー・声明・SEP | 1 | |
| 政策期待 | CME FedWatch 相当（取得可否を要確認） | 2 | **取れなければ「欠損」と明示。推測で埋めない** |
| 為替/商品/株 | 検討中（要 §13 の判断） | 2 | |
| ニュース | Reuters / Bloomberg / 日経 RSS、Fed/BOJ 公式RSS | 1-3 | |
| 機関予測 | 各社の**公開**リサーチ・公開記事のみ | 2-3 | 有料情報は取得しない（指示書 §7） |

---

## 13. Recommended Simplified Architecture（推奨する簡素化構成）

### 13.1 方針

既存の7層構造は**過剰ではなく、むしろ適切**だった。問題は層の数ではなく、
**中身が空の層（agents/similarity）と、検証できない層（scenario/decision）が混ざっていたこと**。
よってMIOSでは層数を減らし、**8 Agent = 8 サブパッケージ**に単純化する。

### 13.2 データフロー

```
 [config/sources/*.yaml]
        ↓
   ingestion（変更なし）───→ data/raw/<source>/<YYYY-MM>/*.json   ← 生データは永久保存
        ↓
   data / markets / calendar / forecasts / news        ← 正規化（Agent 1-5）
        ↓
   observations（vintage付き）/ releases / institutional_forecasts / news_items
        ↓
   prediction（Agent 6: CPI / NFP）→ predictions（毎日1行・上書き禁止）
        ↓
   analysis（Agent 7: macro_scores → cross asset → USDJPY / Gold）
        ↓
   daily_deltas（昨日との差分）
        ↓
   reports（Agent 8）→ reports/daily/YYYY-MM-DD.md
        ↓
   validation（releases 到着後に predictions と突合）→ forecast_errors
```

### 13.3 維持する規律（BIOSからの継承）

1. **import は一方向**（`test_architecture.py` を移植）
2. **naive datetime は境界で拒否**
3. **証拠なき事実は保存できない**（`releases.source_url` を NOT NULL に）
4. **append-only をDBトリガで物理強制**
5. **欠損は必ず明示**（`data_gaps` を全出力に）
6. **min sample 未満は None を返す**（数字を作らない）
7. **設定でふるまいを変え、コードは変えない**

### 13.4 捨てる規律

- **BUY / WAIT / TAKE_PROFIT の語彙**（売買助言はMIOSの目的外）
- **仮想ポートフォリオ / Buy&Hold比較**（予測精度と無関係）
- **基準率なきシナリオ確率**（検証不能）

---

## 14. Data Leakage Risks（データリーク危険箇所）

**深刻度順。L1-L4は新設計で構造的に潰す。**

| # | 深刻度 | 箇所 | 内容 |
|---|---|---|---|
| **L1** | **致命的** | `market_snapshots` 全体 | vintageが無い。改定値が原値を上書きし、「当時知り得た値」が消える。CPI/NFP/PCEは改定される指標であり、**この設計のままバックテストすると必ず未来情報が混入する** |
| **L2** | **致命的** | `observation_date` / `release_date` の不在 | 「2026年8月分CPI」と「2026年9月11日に発表」が区別できない。8月分のデータを8月中の分析で使ってしまう構造的リーク |
| **L3** | **重大** | `AnalysisRepo.save_report` / `save_regime` の upsert | 再計算が過去の分析を上書きする。「10日前に何を予測していたか」が再現不能（指示書 §13 に真っ向から反する） |
| **L4** | **重大** | `extraction/market.py::build_snapshot` | `store.latest(source_id)` の結果を**取得時刻を無視して** `utc_now()` の行に書く。ソースが3日前から死んでいても、古い値が「今日の値」として記録される。**これは現時点で実在するバグ** |
| L5 | 中 | `AnalysisRepo.latest_reports()` | `DISTINCT ON (dimension) ORDER BY as_of DESC` に as-of 引数がない。バックテストから「X日時点の最新レポート」を引けない |
| L6 | 中 | `ScoreCardRepo` / `ScenarioRepo` / `DecisionJournal` | append-onlyだが、読み出しに as-of フィルタが無い |
| L7 | 中 | `sources` テーブルの `enabled` 上書き | ソースがいつ無効化されたかの履歴が残らない。「当時このソースは生きていたか」が検証できない |
| L8 | 低 | `events.recorded_at` を使った検索 | `TimelineEngine` は正しく `known_at` を使っている（コメントで理由も明記）。**ここは既に正しい** |
| L9 | 低 | 埋め込み検索（未実装） | 将来LLM埋め込みを使う場合、モデルの学習データに未来知識が含まれる。EVALUATION §5 が既に警告済み |

### 14.1 新設計での対策

```sql
-- 全ての時系列読み出しに as_of を必須化する
SELECT DISTINCT ON (series_id, observation_date) *
FROM observations
WHERE series_id = %(s)s AND vintage_at <= %(as_of)s
ORDER BY series_id, observation_date, vintage_at DESC;
```

- バックテストAPIは `as_of: datetime` を**必須引数**にする（デフォルト値を与えない）。
- `predictions` は `predicted_at` を PK に含め、UPDATE をトリガで拒否。
- CI で「as_of なしで observations を読むコード」を静的検出するテストを追加する。

---

## 15. Validation Weaknesses（検証面の弱点）

| # | 弱点 | 詳細 |
|---|---|---|
| V-1 | **予測を保存していない** | `predictions` 相当のテーブルが存在しない。したがって「予測精度」を測る対象自体が無い |
| V-2 | **測っているものが目的とずれている** | `decision/outcomes.py` は BUY/WAIT の方向を ±2% / ±5% バンドで採点。`backtest.py` は売買P&L。**どちらもCPI/NFP予測の巧拙を一切測らない** |
| V-3 | **MAE / RMSE / Brier / キャリブレーションが未実装** | `EVALUATION_AND_CALIBRATION.md` は Brier とキャリブレーション曲線を要求しているが、コードに存在しない。**設計と実装の乖離** |
| V-4 | 確率が検証に耐えない | `scenario/engine.py` の確率は composite の線形変換。キャリブレーションを測っても「式の傾き」しか分からない |
| V-5 | **統合テストが既定でskip** | 16/91件がPostgreSQL未接続でskip。**DB不変条件（append-onlyトリガ・FK・CHECK）がCIで一度も検証されていない** |
| V-6 | **CIが存在しない** | `.github/` なし。`make check` はローカル実行のみ。マージ時の品質保証がゼロ |
| V-7 | ゴールデンテストなし | `prompts/README.md` が `tests/golden/` を参照しているが、ディレクトリごと存在しない |
| V-8 | 見逃し（recall）検知が未実装 | EVALUATION §6 が要求する「大きく動いた日の原因イベントが存在するか」の照合が無い |
| V-9 | 最小サンプル規律が一部のみ | `analysis/stats.py` は `min_n=30` を守るが、`regime.py` は `TREND_WINDOW=20` / `VOL_WINDOW=30` をハードコードし、閾値（±3%, 0.015, 0.035）の根拠が無い |
| V-10 | サンドボックスから外部到達不可 | 本環境ではFRED/BLS/Treasury等が全てプロキシで403。**開発中の「実データでの検証」ができない**→ fixture ベースのテスト＋Actionsでの実行、の二段構えが必須 |

### 15.1 MIOSでの検証設計（最低要件）

```
predictions(CPI, 2026-10分, predicted_at=2026-09-12) = 3.3%
        ↓ releases 到着（2026-10-15, actual=3.4%）
forecast_errors: error=+0.1pp, direction_hit=true, days_ahead=33
        ↓ 集計
MAE / RMSE / Directional Accuracy / Upside-Downside Accuracy / Calibration
        ↓ 比較対象（必須）
  ① コンセンサス予測（releases.forecast）  ← 最強のライバル
  ② ナイーブ予測（前月と同じ）
  ③ 直近12ヶ月平均
```

**成功条件は「当たること」ではなく「コンセンサスとナイーブに対する相対誤差を、統計的に有意な期間で測れること」**（指示書 §28）。

---

## 16. Migration Plan（移行計画）

### 16.1 基本方針

1. **既存DBは破壊しない。** 新スキーマは `0005_mios_core.sql` 以降として**追加**する。
   旧テーブル（decisions等）は DROP せず、参照をやめるだけ。append-onlyトリガのため
   誤操作でのデータ消失はDBが拒否する。
2. **パッケージは `bios` → `mios` へリネームし、同一コミット内で移行する。**
   `git mv` を使い、履歴を保つ。
3. **各フェーズの終わりで `make check` が必ずPASSすること。** 赤いまま次へ進まない。
4. **削除のたびに `docs/DELETION_LOG.md` へ記録する。**

### 16.2 リネーム表（主要なもの）

| 旧 | 新 |
|---|---|
| `src/bios/` | `src/mios/` |
| `bios.common.*` | `mios.common.*`（内容ほぼ不変） |
| `BiosModel` / `BiosRecord` / `BiosError` | `MiosModel` / `MiosRecord` / `MiosError` |
| `BIOS_*` 環境変数 | `MIOS_*`（`.env.example` 更新） |
| `bios_forbid_mutation()` | `mios_forbid_mutation()`（新規作成。旧関数は残す） |
| `bios` CLI | `mios` CLI |

### 16.3 データ移行

| 対象 | 移行方法 |
|---|---|
| `var/raw/` の生データ | **そのまま保持**。MIOSは `data/raw/` を使うが、旧パスも読めるようにする（消さない） |
| `events` / `evidences` | **そのまま保持**。MIOSのマクロイベントは同じテーブルに追記できる（type taxonomyのみ差し替え） |
| `market_snapshots` の BTC 行 | **そのまま保持**。MIOSは新 `observations` を使う。旧データは参照しないが削除もしない |
| `decisions` / `virtual_trades` 等 | 保持（参照停止のみ） |
| `seeds/chains/*.yaml` | `archive/seeds/btc/` へ `git mv` |

### 16.4 破壊的変更のリスクと対策

| リスク | 対策 |
|---|---|
| `common/labels.py` の enum 改名でDBの CHECK 制約と不整合 | 新 enum は新テーブルにのみ適用。旧テーブルの CHECK は触らない |
| `test_architecture.py` の ALLOWED 更新漏れ | フェーズ2の最初に更新し、以降は毎回実行 |
| Bitcoin用cronが動き続けて壊れたコードを叩く | フェーズ2開始前に `ops/crontab.txt` の該当ジョブ停止をオーナーへ依頼（**オーナー作業**） |
| 外部到達不可の環境で「動いた」と誤認 | 全てのcollectorテストは録画fixtureで行い、**実接続の成否はActionsのログでのみ判定**する |

---

## 17. Estimated Implementation Order（実装順序と見積り）

> 見積りは「1フェーズ = 1 PR相当」。各フェーズ末で `make check` が緑であることを完了条件とする。

| Phase | 内容 | 主要成果物 | 概算LOC | 完了判定 |
|---|---|---|---|---|
| **1** | **監査（本書）** | `docs/REPOSITORY_AUDIT.md` | – | ✅ **完了** |
| **2** | Architecture cleanup | `bios`→`mios` リネーム、§9の削除実行、`DELETION_LOG.md`、`archive/` 退避、`test_architecture.py` 更新、README/Constitution 書き換え、**CI導入** | −1,300 / +200 | ✅ **完了**（src 5,219→3,384行 / 74→52ファイル。`make check` PASS、統合テストも実PostgreSQLで56件PASS） |
| **3** | Data layer（骨格） | `0005_series_vintage.sql`（series / observations / releases / economic_calendar / normalize_state）、`http_csv` adapter、FRED 29系列＋Treasury CSV＋Twelve Data、**`mios.series`（`data`/`markets` を統合）** | +1,100 | ✅ **完了**（unit 72 / integration 20 とも実PostgreSQLで緑。CLIで raw→observations→as-of 参照まで疎通確認） |
| **4** | Historical / Vintage | ALFRED vintage 取り込み、`as_of` 必須のクエリAPI、as-of リーク検出テスト | +400 | 「2026-09-01時点の値」を再現するテストが緑 |
| **5** | Forecast layer | `mios.prediction`（CPI / NFP）、`predictions` テーブル、先行指標マッピング、上書き禁止トリガ | +700 | 同日2回実行しても2行目が拒否され、日次で行が増える |
| **6** | News / Institutional | `mios.news`（20分類 taxonomy）、`mios.forecasts`（機関予測の**変化**を保存）、LLMは分類・要約のみ（数値生成禁止） | +600 | LLM出力に数値フィールドが存在しないことをテストで保証 |
| **7** | Cross Asset | `mios.analysis`（macro_scores → USDJPY / Gold バイアス）、各スコアに入力・weight・式・timestamp を保存 | +500 | `why` コマンドでスコアの再現計算が全て表示される |
| **8** | Daily Reports | `mios.reports` → `reports/daily/YYYY-MM-DD.md`（17ブロック）、`daily_deltas`（昨日差分） | +500 | `make daily-report` が実行でき、欠損が明示される |
| **9** | Validation | `mios.validation`（MAE/RMSE/方向/キャリブレーション）、コンセンサス・ナイーブとの比較、`forecast_errors` | +500 | 合成データで既知の誤差指標を再現するテストが緑 |
| **10** | GitHub Actions | `.github/workflows/{ci,daily}.yml`、PostgreSQLサービスコンテナで**統合テストをCIで実行**、失敗ソース・欠損・レポート生成可否をログに明示、意味のあるcommit message | +200(yaml) | CIが緑、日次ワークフローが手動実行で通る |

### 17.1 重要な順序上の注意

- **Phase 4（vintage）は Phase 5（予測）より必ず先。** 逆にすると、予測が非vintageデータで学習され、
  後から全て作り直しになる。
- **Phase 10（Actions）は最後だが、Phase 3 の時点で最小のCI（`make check` のみ）を先行導入すべき。**
  現在CIが無いため、Phase 2〜9 の間ずっと品質保証がローカル依存になる。
  → **推奨：Phase 2 の PR に `.github/workflows/ci.yml`（lint/typecheck/unit test）だけ含める。**
- **Phase 6 は外部到達性に依存する。** 本サンドボックスでは検証できないため、
  Actionsで初回実行するまで「実装済み・未検証」として扱う。

---

## 18. 監査時点の未決事項（オーナー判断が必要）

| # | 論点 | 選択肢 |
|---|---|---|
| Q-1 | ~~FX / Gold / 株価の価格ソース~~ | **決定済（2026-09-12）：Twelve Data を Tier2 として採用。ADR-011 参照。** 金利・経済指標は引き続き Tier1（FRED/BLS/BEA/Treasury/日銀）を正とする |
| Q-2 | **Fed政策期待（利下げ確率）の取得元** | CME FedWatch はスクレイピング前提になりがち。取得できない場合は「欠損」を明示するか、FF先物から自前計算するか |
| Q-3 | **機関投資家予測の取得範囲** | 有料レポートは対象外（指示書 §7）。公開記事のみだと網羅性が落ちる。「取れた分だけ・出典URL付き」で妥協するのが妥当か |
| Q-4 | ~~PostgreSQL の稼働場所~~ | **決定済（2026-09-12）：マネージドPostgreSQL。ADR-010 参照。** 既存の psycopg 層・マイグレーション・append-onlyトリガをそのまま継承する |
| Q-5 | **旧BIOSの停止タイミング** | `ops/crontab.txt` の8ジョブは現在も動いている可能性がある。Phase 2 開始前に停止するか、並走させるか |
| Q-6 | LLM利用 | `ANTHROPIC_API_KEY` は未設定。Phase 6 まではLLM不要で進められる |

---

## 19. 結論

**このリポジトリは捨てるべきではない。**

Bitcoin固有のコードは全体の1割弱にすぎず、残りの9割——収集フレームワーク、時刻規律、
append-only監査、ID規約、層境界の機械的強制、欠損の明示、最小サンプル規律——は
**マクロ経済データ基盤にそのまま必要なものばかり**である。むしろゼロから書けば、
これらの規律を再発明するのに数週間かかる。

一方で、**BUY/WAIT/TAKE_PROFIT を出力する判断層・仮想ポートフォリオ・売買バックテスト・
基準率なきシナリオ確率は、MIOSの目的に対して有害**である。それらは「予測精度」ではなく
「売買成績」を測る装置であり、残せば検証の焦点がぼやける。約1,300行を削除する。

そして最大の欠落は**「予測を保存する場所」と「vintageの概念」**である。これが無い限り、
半年後に「このシステムはCPI/NFP予測に本当に役立っているのか？」には**原理的に答えられない**。
Phase 4 と Phase 5 が本プロジェクトの成否を決める。

---

## 付録A：ファイル分類一覧（全145ファイル）

| 分類 | 件数 | 主な対象 |
|---|---|---|
| **KEEP** | 46 | common(8) / config(4) / audit(3) / storage(3) / scheduler(4) / ingestion(10) / knowledge一部(5) / analysis一部(4) / scoring(2) / tests一部(8) / Makefile / pyproject / ADR-009 |
| **MODIFY** | 21 | labels / ids / config models / extraction(2) / snapshots / repo / regime / brief / why / alerts / taxonomy(3) / scoring.yaml / pipelines.yaml / test_architecture / README / .env.example / EVALUATION / DATA_SOURCE_REGISTRY |
| **REPLACE** | 6 | market_snapshots スキーマ / reactions.py / outcomes.py / decision採点 / assets定義 / crontab→Actions |
| **DELETE** | 42 | analyzer(3) / scenario(1) / decision(4) / 空パッケージ(2) / BTCソースYAML(8) / btc.yaml / agents.yaml / docスタブ(3) / 対応テスト(3) / その他設定・死コード |
| **ARCHIVE** | 13 | seeds(2) / Constitution / MSD / IES / sprints(6) / review(1) / crontab |
| 変更なし（生成物・空） | 17 | `__init__.py` の一部、README類 |

## 付録B：検証に使ったコマンドと結果

```
$ python3.12 -m venv .venv && pip install -e ".[dev]"
$ ruff check src tests          → All checks passed!
$ ruff format --check src tests → 93 files already formatted
$ mypy                          → Success: no issues found in 74 source files
$ pytest                        → 75 passed, 16 skipped   （skip = PostgreSQL未接続）

$ git log --all --name-only --pretty=format: | sort -u
  → 実測データ・レポート・予測値のファイルは git 履歴上に一度も存在しない
    （すべて var/ = git管理外 と PostgreSQL にのみ存在）

$ for h in api.stlouisfed.org www.bls.gov home.treasury.gov \
           query1.finance.yahoo.com stooq.com www.federalreserve.gov; do
      curl -sS -o /dev/null -w "%{http_code}" "https://$h/"; done
  → すべて 000（プロキシが CONNECT を 403 で拒否）
```
