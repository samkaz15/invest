# Sprint 5 Report — Intelligence Layer (rule-based v1) + Morning Briefing

日付：2026-07-17 ／ 対象設計：IES §10-§13・§12.2、MSD G12-G14・§15.2 ／ ANTHROPIC_API_KEY未設定のためLLMなしの決定論パスを完成（D14継続）

## 1. 実装内容

| 領域 | 実装 |
|---|---|
| Regime判定 v1 | ルールベース（SMA乖離→trend、実現ボラ帯→vol、liquidityはFRED待ちでunknown）。**履歴不足の軸は正直にunknown**を返し、重みセットはdefaultへフォールバック |
| **Scoring Engine（3層Score Card）** | DimensionReport→重み付き合成（フェーズ別weight set・anomalyハードキャップ）→ composite・verdict（IES §11.5マッピング）。**Conflict Index**＝重み考慮の符号対立度（対立は平均化せず第一級で表示）。**data_completeness**＝次元confidenceの平均。Score Cardは**append-only**（1資産1日1枚）で全シグナルまで分解可能 |
| Scenario Engine v1 | 続伸/レンジ/調整の3本・Σp=1.0をコードで保証。**確率は無情報事前分布(1/3)±composite傾き（最大±0.15・式公開）**。基準率が算出不能である旨をレコード自体に永久記載（憲法第5条: 統計の捏造禁止をスキーマで担保） |
| **Decision Engine v1 + Journal** | WAITバイアス設計：データ完全性<0.6→強制WAIT／composite≥+40＋充足→BUY／TAKE_PROFITはポジション追跡実装まで発火せず。Conflict>0.6で確信度キャップ0.55。**無効化条件なしの判断はDB制約でも不可**。Critic-lite（最強の反対シグナルを自動併記）。decisions/decision_outcomesはappend-onlyトリガ付き |
| Learning Engine v1 | `bios validate`：+1d/+7d/+30d/+90dで自動採点。BUY=±2%帯、**WAITは+5%超の機会損失を明示的に減点**（「常にWAIT」への退化を防ぐIES §13.3の規律）。採点基準の変更はADR必須 |
| **Morning Briefing v1（「おはよう」）** | `bios brief`（`bios おはよう`エイリアス）。**新規分析ゼロ・全数値DB由来**（Report Agent原則G14）。判断/フェーズ/Score Card内訳/市況FACT/シナリオ+注記/承認イベント/チェーン監視点/キュレーション滞留/**無効化中ソースの欠損明示**/免責定型文 |
| スキーマ | 0003：regimes（導出）＋score_cards/scenario_sets/decisions/decision_outcomes（append-only） |

## 2. ライブ実証（本日の実データ）

```
decide : WAIT conviction=0.41 composite=+2 (NEUTRAL_BULLISH) conflict=0.00 → dcs_2026-07-17_btc
おはよう: ブリーフィング全文生成（価格$63,039・F&G27・シナリオ34/33/33%・
         無効化条件・Critic反論・FRED2ソースの欠損明示つき）
validate: 採点対象なしを正しく報告（+1d経過後から自動採点開始）
```

判断根拠が「データ完全性0.27<0.6」であること自体が正しい動作 — **day-4のBIOSは「まだ判断材料が足りない」とWAITし、その理由と解除条件を明示する**。履歴蓄積とともにcomposite・確信度が自然に立ち上がる。

## 3. テスト結果

```
ruff / format : PASS（87ファイル）
mypy --strict : PASS（70ソースファイル）
pytest        : 84 passed
```

主要テスト：合成の加重平均とverdictマッピング／**Conflict Index（全会一致=0.0・真っ二つ=1.0）**／Regimeのunknownフォールバックと強気トレンド判定／シナリオΣp=1.0と傾きの方向・INFERENCEラベル・「統計ではない」注記／**薄データ強制WAIT**／強composite+充足でBUY＋Critic併記＋前日比変化文／**対立時の確信度キャップ**／採点規則8ケース（WAITの機会損失減点を含む）。

## 4. 設計との差分

| # | 差分 | 判断理由 | 要否 |
|---|---|---|---|
| D18 | tactical/strategic 2本立てスコア（IES §11.4-3）は未実装（composite1本） | 時間軸タグをシグナルに付与する設計が先（v1シグナル数が少なく分離の意味が薄い）。シグナル増加時に追加 | 不要（拡張ポイント記録） |
| D19 | シナリオ確率が基準率起点でない（IES §9.5の本則に対する暫定則） | 類似事例n<5で基準率が定義不能。無情報事前分布＋公開式＋レコード上の明記はIES P4（ベイズ縮小）の趣旨に整合。Historical DB拡充とともに自動的に本則へ移行する構造 | 不要（暫定則を明記済み） |
| D20 | TAKE_PROFITが発火しない（ポジション追跡未実装） | 仮想ポートフォリオ（IES §13.3）の実装がSprint 6。現状は常にフラット前提 | Sprint 6で解消 |
| D21 | ソース同期を解決後レジストリに変更（キー欠落ソースをDB上もdisabled記録） | ブリーフィングの欠損明示（沈黙の欠損禁止）が機能するために必要と実装中に発見 | 不要（改善） |

## 5. リスク・残課題

| 優先度 | 項目 |
|---|---|
| High | 引き続き：ANTHROPIC_API_KEY（ニュース14項目分析・類似検索の質）／FRED_API_KEY（マクロ次元・liquidity軸）／キュレーション滞留79件／cron未設定 |
| Medium | Regime v1のボラ帯（1.5%/3.5%）は絶対値の仮置き。履歴90日蓄積後にpercentile化（変更はADR） |
| Medium | Scenario先行指標がv1固定文。イベント駆動の動的化はLLM Sprint |
| Low | 判断は1日1回（append-only）。日中の再判断は翌日ID待ち — 憲法の時間軸（日〜週）に整合するため仕様とする |

## 6. 次Sprint計画（Sprint 6 : Reporting & Ops 完成 — 承認待ち）

1. 仮想ポートフォリオ（IES §13.3）：BUY/WAIT/TAKE_PROFIT→ポジション状態機械・B&H比較（D20解消、TAKE_PROFIT有効化）
2. Backtest指標：勝率/期待値/PF/Sharpe/MDD/**対B&H超過**を`bios validate`に統合
3. Alert Engine v1：|points|≥15のシグナル発火・ブレーカopen・invalidation発動をalertsストリーム＋brief冒頭に表示
4. cron/launchdセットアップ（ops/）：15分run-due＋早朝の analyze→decide→brief 事前生成
5. 深掘りコマンド：`bios why <decision_id>`（Score Card→シグナル→Evidence→RawItemの証拠チェーン全展開）
6. （キー設定され次第）Agentランタイム＋News Agent＋類似検索LLM経路
