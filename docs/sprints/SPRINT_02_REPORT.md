# Sprint 2 Report — Data Collection Layer

日付：2026-07-14 ／ 対象設計：MSD §3.3(L0-L1)・§15、IES該当なし ／ 前提：Sprint 1レビュー指摘F1-F6適用済み（`7950b1d`）

## 1. 実装内容（要求対象と対応）

| 要求 | 実装 |
|---|---|
| Source Adapter Framework | `SourceAdapter` ABC＋`FetchResult`契約。**adapterは「種類」（rss / http_json）にのみ対応し、プロバイダは100% YAML**（SourceSpec）。新プロバイダ追加＝YAML 1ファイル、コード変更ゼロ（アセット非依存P9をL1でも貫徹） |
| Collector Interface | `Collector.collect(source_id)`：rate limit→条件付きGET（ETag/Last-Modified）→ハッシュ重複排除→Raw保存→DLQ→health→metrics→audit の一本道 |
| Source Registry | `config/sources/*.yaml`（機械可読レジストリ）。`${ENV_VAR}`展開つき。**秘密欠落ソースは自動無効化＋警告**（他ソースを道連れにしない） |
| RawItem Schema | `raw_item_id`（時刻順opaque ID）・`source_id`・`retrieved_at`（後段`known_at`の基盤）・`content_hash`・無加工payload |
| Raw Storage | `FileRawStore`：追記のみ・上書き拒否・`<source>/<YYYY-MM>/`レイアウト・ハッシュ台帳（再起動後も重複排除有効）。`RawStore`プロトコル背後なのでDB移行時も呼出側無変更 |
| Scheduler | `JobRunner`＋`config/pipelines.yaml`（interval駆動・cron/launchdから`bios run-due`。ADR-004どおりデーモンなし） |
| Retry / Exponential Backoff | `RetryPolicy`：設定駆動の遅延列（60s→300s→1800s）＋ジッター。**プログラミングエラーはリトライしない**（BiosError系のみ） |
| Circuit Breaker | `CircuitBreaker`：連続N失敗→open→クールダウン→half-open試行。**状態を永続化**（短命ジョブプロセス前提のため） |
| Dead Letter Queue | 解析不能データを理由つきで隔離（フィード全体はAdapterError、エントリ単位はParseFailure→DEGRADED完了） |
| Rate Limiter | ソース毎の最小呼出間隔 |
| Hash Deduplication | sha256（正準化JSONペイロード）。RSSはエントリ単位で正準化→**記事単位の重複排除**が機能 |
| Source Health Check | 成功/失敗/連続失敗/最終エラーを永続追跡。`bios health`で表示。`degraded()`はBriefingの欠損明示（沈黙の欠損禁止）に接続予定 |
| Metrics / Monitoring | 全実行の`CollectReport`をmetricsストリームへ追記＋`bios health`コマンド |
| Audit Log | 全収集実行を`agent_runs`ストリームに記録（Sprint 1基盤に接続、agent=`collector.<source>`） |

## 2. 稼働データソース（Phase 3要求との対応・ライブ検証済み）

| ソース | Tier | 頻度 | カバーする要求項目 | 状態 |
|---|---|---|---|---|
| CoinGecko BTC | 2 | 1h | BTC価格・出来高・時価総額 | ✅ 稼働 |
| Bybit BTCUSDT perp | 2 | 1h | Funding Rate・Open Interest・mark価格 | ✅ 稼働 |
| alternative.me | 3 | 12h | Fear & Greed Index | ✅ 稼働 |
| mempool.space | 1 | 12h | Hash Rate・Difficulty | ✅ 稼働 |
| blockchain.info stats | 2 | 12h | ネットワーク統計・マイナー収益 | ✅ 稼働 |
| CoinDesk RSS | 3 | 15m | ニュース | ✅ 稼働 |
| Cointelegraph RSS | 4 | 15m | ニュース | ✅ 稼働 |
| SEC Press RSS | 1 | 1h | SEC・政府発表・規制 | ✅ 稼働 |
| FRED DGS10 / CPI | 1 | 12h/24h | US10Y・CPI | ⏸ **FRED_API_KEY待ち**（無料キー。設定すれば自動有効化） |

ライブ実証：8/8ソース収集成功・87 RawItem保存・即時再収集で全件重複判定（ハッシュ重複排除の実証）・FRED2件は警告つき自動無効化。

**未対応（今後のYAML追加または要契約）**：OHLCV時系列（CoinGecko候補あり）／Liquidation（取引所API要調査）／ETF Flows（無料の安定APIなし—Farside等のスクレイプかT3 Index系有料）／PPI・NFP・FOMC・DXY・M2（FREDキーで全て解決）／オンチェーン詳細（MVRV・SOPR・Exchange Reserve等は**Glassnode/CryptoQuant有料**。無料代替は精度劣後）／ウォレット監視（Tier 4。mempool.spaceアドレスAPIで実装可能、監視対象リストのYAML化を次Sprint以降で設計）／企業IR・裁判資料（EDGAR RSS・CourtListener APIをYAML追加可能）。

## 3. テスト結果

```
ruff / format : PASS（56ファイル）
mypy --strict : PASS（44ソースファイル）
pytest        : 45 passed（+ライブ収集の手動端到端検証）
```

主要テスト：リトライ台形とジッター境界／ブレーカのopen→half-open→再open・再起動耐性／レート制限の待機計算／RSS・Atom解析と正準ペイロードのハッシュ安定性／エントリ単位DLQ隔離／Collector端到端（保存・重複・監査・メトリクス・health）／JobRunnerのdue計算・ブレーカ連携／実configの整合（pipelines→sources相互参照）。

## 4. 設計との差分

| # | 差分 | 判断理由 | 設計変更要否 |
|---|---|---|---|
| D6 | Raw StoreがファイルベースでPostgreSQL（ADR-002）未着手 | Sprint 3スコープ。`RawStore`プロトコルで差替え可能 | 不要（実装順序） |
| D7 | ingestion→schedulerの依存エッジ追加（RateLimiter利用） | schedulerは横断層。逆方向importはなし（タスクは注入）。arch testに明記 | 不要（テーブルに記録済み） |
| D8 | HTTPクライアントをstdlib urllibで自作（httpx等不採用） | 憲法第8条（依存最小）。GET+ヘッダ+タイムアウトに外部依存は不要 | 不要 |
| D9 | 「リアルタイム」は15分ポーリング粒度 | 憲法第9条Non-Goal（秒単位速報はやらない）の確認 | 不要 |

## 5. リスク・残課題

| 優先度 | 項目 |
|---|---|
| High | **オンチェーン中核指標（MVRV/SOPR/Reserve）の無料ソース不在**。IES §5の11指標のうち4指標が有料データ前提。→ オーナー判断事項：Glassnode等の契約 or 無料近似（blockchain.info系）で開始 |
| High | ETF Flowsの安定取得経路が未確定（Farsideスクレイプは脆い） |
| Medium | RSSは直近N件しか含まない：収集停止が長引くと記事を取りこぼす（アーカイブAPIなし）。cron常時稼働が前提 |
| Medium | CoinGecko等の利用規約上のレート制限。min_interval・スケジュール間隔は保守的に設定済み |
| Low | JSONペイロード内の揮発フィールド（タイムスタンプ等）により市場データ系は毎回「新規」判定になる（意図どおり：市場データは毎回が新しい観測） |

## 6. 次Sprint計画（Sprint 3 : Data Storage Layer — 承認待ち）

1. **PostgreSQL 16導入**（brew・ローカルMac、ADR-002/005どおり）＋マイグレーション基盤（db/migrations 連番SQL）
2. スキーマ実装：`raw_items`（ファイル→DB移行 or 併用）／`events`（UPDATE/DELETE拒否トリガ）／`evidences`／`entities`／`event_chains`／`event_relations`（TRIGGERED_BY証拠必須制約）／`event_participations`／`curation_queue`／`audit_log`・`agent_runs`（DBシンク）
3. Event Store・Knowledge Graph・Timeline Engineのリポジトリ層（Python API）
4. 正規化第1弾：市場系RawItem→`market_snapshots`（価格・funding・OI・F&G・hashrate）
5. ニュースRawItem→Event候補→curation_queue（ルールベース。LLM抽出はAgent実装Sprintで）
6. シード投入基盤（seeds/chains → Historical DB）＋Mt.Gox・FTXなど2-3チェーンの試験投入
7. DoD：`おはよう`前提データが照会可能／全テーブルにテスト／pg_dumpバックアップスクリプト（ops/）

**Sprint 3の判断事項（オーナー確認推奨）**：pgvector/TimescaleDB拡張を初回から入れるか（推奨：入れる。後からの拡張追加はマイグレーション増）。
