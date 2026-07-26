# Sprint 6 Report — Reporting & Ops 完成（仮想ポートフォリオ・Backtest・Alert・自動化）

日付：2026-07-26 ／ 対象設計：IES §13.3-13.4、MSD §15.1-15.4、G14（Report Agent原則）

## 1. 実装内容

| 領域 | 実装 |
|---|---|
| **仮想ポートフォリオ** | `VirtualPortfolio`：Decisionを機械的にBUY=1単位追加／TAKE_PROFIT=全決済へ変換（IES §13.3）。`virtual_positions`（現在値）＋`virtual_trades`（append-only履歴）。**サイジング・レバレッジは実装しない**（憲法第7条：意思決定支援システムであり自動売買ではない） |
| **TAKE_PROFIT有効化** | Decision Engineにポジション状態を接続：`composite ≤ -20 かつ保有あり`でTAKE_PROFIT発火。D20（Sprint5残課題）を解消。フラット時の弱気シグナルはWAITのまま（売る物がない） |
| **Backtest Engine** | `BacktestEngine`：決済済みトレードから勝率・期待値・Profit Factor・Sharpe・最大ドローダウンを算出。**`strategy_return`と`buy_hold_return`を同一ウィンドウで並記し`excess_vs_buy_hold`を明示**（IES §14.4「B&Hに勝てないなら判断機能に価値がない」の直接実装） |
| **Alert Engine** | ルールベース：`\|points\|≥15`のシグナル発火／Conflict Index≥0.8／アクティブな無効化条件／無効化中ソース(欠損)を`alerts`テーブル(append-only)へ記録。ブリーフィングの「pull」に対する「push」経路 |
| **`bios why <decision_id>`** | Decision→Score Card→次元→シグナル→根拠→(Evidence参照)まで完全展開。MSD §18「任意のDecisionから証拠まで遡及可能」の実行手段 |
| **cron自動化** | `ops/crontab.txt`をユーザー承認の上インストール（**既存の別プロジェクト5ジョブは保持**）。15分毎`run-due`＋毎朝5:30-6:25台に extract→snapshot→react→analyze→decide→validate の自動パイプライン＋週次バックアップ |
| スキーマ | 0004：virtual_positions/virtual_trades/alerts（後2者はappend-only） |

## 2. ライブ実証

```
decide  : WAIT conviction=0.41 composite=+2 → dcs_2026-07-26_btc
          （+ ALERT[warning] data_gap ×2：FRED未設定ソースを検知・記録）
backtest: 決済済みトレードなし、と正しく報告（BUYが一度も発火していないため。捏造なし）
alerts  : 直近アラート一覧を正常表示
why     : dcs_2026-07-26_btc → score_card sc_2026-07-26_btc → signal
          news.fear_greed_band(+5) → rationale_refs まで完全遡及を確認
cron    : 8ジョブをインストール（既存5ジョブと共存）。var/logs/へ出力
```

## 3. テスト結果

```
ruff / format : PASS（93ファイル）
mypy --strict : PASS（74ソースファイル）
pytest        : 91 passed（DB統合5件追加）
```

主要テスト：BUY→TAKE_PROFITペアリングの時系列整合と未決済除外／最大ドローダウン計算／**「保有なしなら弱気でもWAIT、保有ありならTAKE_PROFIT」の分岐**／仮想ポートフォリオの建玉更新とBacktestの一致（100→200で戦略リターン・B&Hリターンとも+100%、超過0%を検証）／Alert発火（極端シグナル・無効化ソース）／`why`の証拠チェーン展開と存在しないIDへの安全な応答。

## 4. 設計との差分

| # | 差分 | 判断理由 | 要否 |
|---|---|---|---|
| D22 | 仮想ポートフォリオは1資産1ポジション（ナンピン・部分利確なし） | v1は「判断が正しい方向か」の検証が目的で、資金管理最適化は憲法のスコープ外（第7条：発注機能は最終段階まで実装しない） | 不要（意図的な単純化） |
| D23 | Sharpe算出は日次リターンでなくトレード単位（IES §13.4は日次リターン想定） | トレード数がまだ非常に少なく（0件）日次系列化は時期尚早。トレード数が十分蓄積した時点で日次リターン方式に切替可能な設計 | 軽微・将来ADR候補 |
| D24 | crontabは既存の別プロジェクトジョブと共存させ、コメント区切りで追記（上書きせず） | 既存ジョブ（gold_predictor等）の破壊はデータ喪失級のリスク。オーナー確認の上で追記のみ実施 | 不要（安全策として記録） |

## 5. リスク・残課題

| 優先度 | 項目 |
|---|---|
| High（継続） | ANTHROPIC_API_KEY / FRED_API_KEY 未設定。キュレーション滞留（`bios curate list`で確認・処理を推奨） |
| Medium | cronの初回実行を明日の朝に確認すること（var/logs/pipeline.log, run-due.log） |
| Medium | Backtestはトレード0件のため指標が全てNone。BUYが発火するまで（composite≥+40達成まで）性能検証は開始されない — これは仕様どおり（捏造回避） |
| Low | AlertEngineの`scan()`は毎回DBへ書き込む（`bios decide`の度に重複気味に記録され得る）。運用開始後に重複除去ロジックの要否を判断 |

## 6. 累積到達点（Sprint 1-6振り返り）

全7層(L0-L6)が最小実装で貫通：収集→Raw保存→正規化→Knowledge Graph/Timeline→分析→Scoring→Scenario/Decision→仮想ポートフォリオ→Backtest→Alert→Briefing。**「おはよう」から仮想トレード検証まで、決定論的パスが実データで動作**しています。未実装はLLM Agent系（キー待ち）とHistorical DB/Similarity Engineの本格拡充のみ。

## 7. 次フェーズ計画（Sprint 7 : Validation — 承認待ち）

これはMVP指示の最終フェーズ相当。ANTHROPIC_API_KEYの有無で経路が分岐する：

**キー設定済みの場合**：
1. Agentランタイム（LLM呼出・スキーマ検証・予算・キャッシュ）
2. News Agent（14項目分析・タクソノミ提案。人間承認は維持）
3. Similarity Engine LLM経路（構造検索＋埋め込み。pgvector導入）
4. ゴールデンテスト（tests/golden/）：既知イベント→期待構造の回帰

**未設定でも進められる項目**：
5. Historical DB拡充（LUNA・SVB・半減期等の追加シード）
6. Backtestのウォークフォワード検証基盤（IES §13.8ガバナンス：60判断蓄積まで重み変更禁止の実装チェック）
7. QA Agent相当のルールベース監査（証拠なきFACT・ラベル欠落の機械検出）

MVP完成率としては、収集〜判断〜検証の骨格は100%到達。残るのはLLMによる分析の質向上と、統計的検証に必要な時間経過（判断蓄積）のみです。
