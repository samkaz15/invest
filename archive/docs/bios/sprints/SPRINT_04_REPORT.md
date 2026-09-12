# Sprint 4 Report — Analysis Layer (rule-based v1)

日付：2026-07-17 ／ 対象設計：IES §1.3・§5・§6・§8.3(最低標本規律)・§12.1、MSD §3.3・§11

## 1. 実装内容

| 領域 | 実装 |
|---|---|
| DimensionReport契約 | IES §1.3の共通出力契約を実装（`Signal`＝説明可能性の最小単位：signal_id・値・寄与点・ラベル・根拠・証拠参照）。score=寄与点合計のクリップ、**conviction=データ完全性から機械算出**（欠損だらけの日は数値で正直に低くなる） |
| 統計規律 | `stats.py`：zscore/percentile/pct_change、**n<30はNoneを返す**（薄い履歴からの読みは構造的に不可能。IES §8.3） |
| Derivatives Analyzer | funding極値（絶対閾値でなく**履歴percentile**：P95超=crowded_long/P5未満=squeeze燃料）・OI 24h変化（±10%）。IES §6.2/6.3の合流パターン第1弾 |
| On-chain Analyzer | ハッシュレート下落検知（14点窓−10%=降伏パターン）。**MVRV/SOPR等の未契約8指標は明示的data_gaps**として毎日レポートに出る（沈黙の欠損禁止） |
| News/心理 Analyzer | Fear&Greed帯域（正規化済み指数のため絶対帯域が正当：極端恐怖+10〜極端強欲-10の逆張り小寄与・全てINFERENCEラベル）＋キュレーション滞留の可視化 |
| Market Reaction焼付 | `ReactionBatch`：known_at以降の最初のスナップショットを基準価格に+1h/+1d/+7d/+30d/+90dを計算（**基準はknown_at — 市場が知る前の価格で計ればlook-ahead**）。許容窓外・未来分は計算しない（冪等・データが貯まれば埋まる） |
| **キュレーションCLI（人間ループ開通）** | `bios curate list/approve/reject`。approve＝人間が判断（type/magnitude/タイトル）、機械が来歴（RSS配信日時→occurred_at、Tier→confidence、Evidence+raw_item_id自動添付）。憲法の教師データループが稼働 |
| スキーマ | 0002_analysis.sql：dimension_reports / market_reactions（導出データ＝再計算可能・更新可） |
| CLI | `bios analyze / react / curate` 追加 |

## 2. ライブ実証

```
analyze : derivatives score=+0 conviction=0.10 gaps=2（履歴2日 — 正直に「読めない」）
          onchain    score=+0 conviction=0.10 gaps=9（未契約指標を毎日明示）
          news       score=+5 conviction=0.60（F&G28=恐怖圏・滞留80件を警告）
react   : シードイベント8件は当時のスナップショット不在のため0件計算（捏造なし・正しい挙動）
curate  : 実ニュース「Empery Digital BTC売却」を承認
          → evt_2026-07-12_empery-digital-btc-sale（holdings.corporate.sale・
            occurred_atはRSS配信日時から導出・Evidence+raw_item_id連結・confidence=reported）
```

**day-2のBIOSは「ほぼ何も言えない」と正しく言う。** シグナルが火を吹くのは履歴30点（時間足で約1.5日〜、日足系で1ヶ月）蓄積後であり、これは仕様どおりの振る舞い（テストでは合成履歴で発火を検証済み）。

## 3. テスト結果

```
ruff / format : PASS（80ファイル）
mypy --strict : PASS（64ソースファイル）
pytest        : 68 passed（DB統合13件含む）
```

主要テスト：最低標本規律（n=29→None）／funding極値の発火と薄履歴時のgaps化／OIフラッシュの正符号／ハッシュレート降伏検知／F&G帯域パラメトリック／score クリップとconviction算出／DimensionReport永続化の冪等性／**ReactionBatchの+1h=+10%・+1d=-10%検証と未来ホライズン非捏造**／**curate承認フロー端到端**（イベント化・キュー解決・証拠チェーンraw_item_idまで）。

## 4. 設計との差分

| # | 差分 | 判断理由 | 要否 |
|---|---|---|---|
| D14 | **LLM Agentランタイム未実装**（Sprint 4計画に含めていた） | `ANTHROPIC_API_KEY`未設定のため、動作検証できないランタイムの実装は投機的。分析はルールベースv1で先行（IES §13.7-3の「ルール部分とLLM部分の分離」に沿う順序） | **オーナー対応**：`.env`にキー設定→Sprint 5でAgentランタイム+News Agent実装 |
| D15 | Supply/Demand Analyzerは未着手 | 供給圧台帳（Overhang Ledger）の入力になるイベント（政府売却等）がまだキュレーションされていない。データなき分析器は空回り | Sprint 5以降（キュレーション進捗に依存） |
| D16 | ruffのRUF001-003（全角記号警告）を除外 | BIOSの出力は日本語。全角記号は仕様 | 記録のみ |
| D17 | F&Gを`news`次元に配置 | IES P2（Sentiment次元の新設）が未承認のため既存7次元内で暫定配置。P2採用時に移設 | オーナー判断（P2） |

## 5. リスク・残課題

| 優先度 | 項目 |
|---|---|
| **High（オーナー対応依頼）** | ①`ANTHROPIC_API_KEY` — これがないとニュース14項目分析・類似検索・シナリオ生成（Sprint 5-6の中核）が作れない ②`FRED_API_KEY` — マクロ次元が空のまま ③キュレーション滞留80件+（`bios curate list`で5分/日の処理を開始可能） |
| Medium | cron/launchd未設定のため収集は手動実行。`crontab: */15 * * * * cd ~/invest && .venv/bin/python -m bios.cli run-due` の設定を推奨（次Sprintでops/にセットアップスクリプト追加） |
| Medium | OI変化点数の符号（積上がり=脆弱性）はv1の仮置き。60判断蓄積後のシグナル検証（IES §13.6）まで重み変更禁止ルールが適用される |
| Low | blockchain.infoのminers_revenueが0を返す事象 — ソース品質監視（IES P6）の実装動機として記録 |

## 6. 次Sprint計画（Sprint 5 : Intelligence Layer — 承認待ち）

1. **Agentランタイム**（キー設定が前提）：Claude API・Pydanticスキーマ検証・トークン予算・プロンプト刻印・呼出キャッシュ・agent_runs記録
2. News Agent：キュー候補の下ごしらえ（type/Entity/magnitude提案→人間が最終承認。完全自動化はしない）
3. Similarity Engine v1：タクソノミ×レジーム構造検索＋SIMILAR_TO edges（埋め込みはpgvector導入と同時）
4. Scoring Engine：DimensionReport統合→3層Score Card（IES §11.2）・フェーズ別重み（scoring.yaml w_v1）・Conflict Index
5. Scenario/Decision v1：シナリオ3本＋確率（基準率不足時は「統計的に語れない」明示）→BUY/WAIT/TAKE_PROFIT＋無効化条件→Decision Journal
6. Regime判定v1（ルールベース：トレンド/ボラ/流動性）
7. DoD：`bios analyze`→`bios decide`で判断がJournalに記録され、Score Cardから全シグナルまで遡れる
