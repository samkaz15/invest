# Sprint 3 Report — Data Storage Layer

日付：2026-07-14 ／ 対象設計：MSD §4-§11・§13 ／ Decision語彙はオーナー指定なしのため現行憲法（BUY/WAIT/TAKE_PROFIT）を維持

## 1. 実装内容

| 領域 | 実装 |
|---|---|
| PostgreSQL 16 | brewで導入・起動（ADR-002/005）。`bios`（本番）/`bios_test`（テスト）DB作成。ドライバはpsycopg3（**ADR-009**・ORM不採用） |
| マイグレーション基盤 | `MigrationRunner`：連番SQL、1ファイル=1トランザクション（適用と記録が原子的）、冪等 |
| スキーマ（0001） | events / evidences / event_evidences / entities / event_chains / event_relations / event_participations / curation_queue / market_snapshots / sources / audit_log / agent_runs / extraction_state |
| **DBによる憲法の強制** | ①events・evidences・event_relations・audit_log・agent_runsは**UPDATE/DELETEをトリガで拒否**（第3条 append-only）②`TRIGGERED_BY`/`CAUSED_BY_BG`は**evidence_id+confidenceなしではINSERT不可**（CHECK制約・MSD §6.3）③known_at < occurred_at−1日 を拒否 |
| Event Store | `EventStore.insert_event`：**証拠0件のイベントは書けない**（第4条）・タクソノミ外typeは書けない・event+evidence+participation+relationを単一トランザクションで挿入 |
| Knowledge Graph | `EntityRepo`（upsert・alias検索）/ `ChainRepo`（active一覧・watch_points）/ relationはEventStore経由 |
| Timeline Engine | `TimelineEngine`：known_at順整列・**as-ofクエリ（look-ahead bias排除の実装）**・chain/entity絞込・supersedes連鎖の最新解決・進行中イベント |
| Historical DB | `SeedLoader`（seeds/chains/*.yaml→冪等投入）＋**Mt.Gox・FTXの2チェーン投入済み**（8イベント・5エンティティ・因果エッジ3本） |
| 正規化第1弾 | `MarketNormalizer`：市場系Rawペイロード→market_snapshots（宣言的なdotted-pathマッピング。数値は機械コピーのみ）。`NewsExtractor`：RSS Rawアイテム→curation_queue（リンクハッシュで重複排除） |
| 運用 | `bios migrate / extract / snapshot / seed` CLI追加、`ops/backup.sh`（pg_dump+raw tar・30日保持） |

## 2. ライブ実証（本番DB）

```
migrate  : 0001適用＋ソース10件同期
extract  : ニュース80件をキュレーションキューへ（重複0）
snapshot : price=61,850 USD・9指標・欠損0（funding/OI/F&G/hashrate/difficulty等）
seed     : chains=2, entities=5, events=8, TRIGGERED_BY 3本（全て証拠つき）
検証SQL  : UPDATE events → トリガが拒否 ／ 証拠なしTRIGGERED_BY → CHECKが拒否
```

## 3. テスト結果

```
ruff / format : PASS（69ファイル）
mypy --strict : PASS（55ソースファイル）
pytest        : 55 passed（うちDB統合テスト10件 — マイグレーションから実DBに適用して検証）
```

統合テストの要点：マイグレーション冪等性／**append-onlyトリガが実際にUPDATE/DELETEを拒否**／**証拠なし因果エッジをDBが拒否**（PRECEDESは通る）／**as-ofタイムラインが「後から知った」イベントを隠す**（known_at認識論）／エンティティalias検索／スナップショットのJSONBマージ／キューの重複排除と承認・却下。

## 4. 設計との差分

| # | 差分 | 判断理由 | 要否 |
|---|---|---|---|
| D10 | TimescaleDB・pgvector拡張は未導入（プレーンテーブル） | 現データ量（時間毎スナップショット＝年間1万行未満）にhypertableは不要。pgvectorはSimilarity実装（Sprint 5）で必要になった時点のマイグレーションで追加（追加は非破壊） | 不要（導入トリガを明記） |
| D11 | Raw Storeはファイルのまま（DBのraw_itemsテーブル未使用） | 収集は稼働中で安定。evidences.raw_item_idは文字列参照でファイル側と接続済み。DB化はペイロード肥大とのトレードオフで、移行はRawStoreプロトコル背後で可能 | 不要（Phase 2で再評価） |
| D12 | 「イベント最低1証拠」はDB制約でなくリポジトリ層で強制 | SQLは「子行の存在」を宣言的に強制できない（deferred triggerは複雑度に見合わない）。書込みは全てEventStore経由＋QA夜間監査で二重化 | 不要（多層防御に記録） |
| D13 | Decision語彙はB案（現行憲法）を継続 | オーナー指定なしのためデフォルト適用。A案（6語彙）採用時は憲法改正＋labels.py拡張（1 enum＋スキーマ追記で対応可能な設計） | オーナー判断 |

## 5. リスク・残課題

| 優先度 | 項目 |
|---|---|
| High | キュレーションキューに80件/日ペースで候補が溜まる。**承認UI（CLI最小）が未実装**のため、Sprint 4で`bios curate`（一覧・承認・却下・Event化）を最優先に |
| Medium | シード2チェーンの証拠はTier3報道・confidence=reported。オーナーの一次情報付け直し（Phase 1作業）を推奨 |
| Medium | スナップショットのdotted-pathマッピングがコード内定数（`METRIC_PATHS`）。ソース追加で伸びるためYAML外出しをSprint 4で検討 |
| Low | psql/pg_dumpのPATH（/opt/homebrew/opt/postgresql@16/bin）が非標準。ops/backup.shは環境変数で上書き可能 |

## 6. 次Sprint計画（Sprint 4 : Analysis Layer — 承認待ち）

1. **`bios curate`**：キュー処理CLI（承認→Event化＋Evidence自動添付、却下、一括操作）— 人間ループの開通
2. **Agentランタイム**（`bios.agents`）：Claude API呼出・スキーマ検証・トークン予算・プロンプトバージョン刻印・LLM呼出キャッシュ（**ANTHROPIC_API_KEYが必要**）
3. News Agent（LLM）：候補→Event整形・タクソノミ分類・Entity抽出（人間承認前の下ごしらえ）
4. テーマ別Dimension Analyzer第1弾（ルールベース）：Derivatives（funding極値・OI変化）/ On-chain（z-score基盤）/ Macro（カレンダー）→ DimensionReport（IES §1.3契約）
5. Market Reaction焼付バッチ（+1h/+1d/+7d/+30d/+90d、スナップショット履歴が貯まり次第）
6. ゴールデンテスト基盤（tests/golden/）：FTXシードのRawItem→期待構造の回帰
7. DoD：キュー処理が5分/日で回る・最低2次元のDimensionReportが毎日生成される
