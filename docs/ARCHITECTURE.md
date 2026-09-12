# ARCHITECTURE.md
# MIOS システム構造

> 上位文書：`CONSTITUTION.md`
> 現状把握：`REPOSITORY_AUDIT.md`（BIOS からの転換にあたっての全ファイル監査）
>
> 本書は「今どうなっているか」と「なぜそうなっているか」を書く。
> 未実装の層は **未実装と明記する**。設計上の願望を実装済みのように書かない
> （BIOS ではこれが Agent 8体の幻を生んだ。監査 §2.2）。

---

## 1. 層構造

import は一方向にしか流れない。これは規約ではなく、
`tests/unit/test_architecture.py` が AST 解析で機械的に強制するテストである。
層を追加するときは、まずこのテーブルを更新する。

```
L0 横断    common      ID・時刻・schema・共通語彙・エラー・状態ファイル
           config      YAML設定のロードと検証／プロセス設定
           audit       append-only 監査ログ
           storage     PostgreSQL アクセスとマイグレーション
   ↓
L1 収集    ingestion   adapter framework / HTTP / 生データ永久保存 / DLQ / 死活
           scheduler   実行期限判定・リトライ・レート制限・サーキットブレーカ
   ↓
L2 正規化  extraction  生データ → 型付きレコード（ニュース）
           series      生データ → vintage付き観測値（Agent 2 + 3）
   ↓
L3 知識    knowledge   Event Store / Entity / as-of Timeline
   ↓
L4 分析    analysis    次元スコア（Signal の集合 → DimensionReport）
   ↓
L5 統合    scoring     DimensionReport → Score Card（weight・対立・完全性）
```

### 1.1 残りの層（✅ 以外は**現在は未実装**）

| パッケージ | Agent | 内容 | Phase |
|---|---|---|---|
| `calendar/` | 1 | 経済指標発表予定、FOMC / BOJ 日程、次回までの日数 | 5 |
| ~~`data/`~~ | 2 | **`series/` に統合済**（Phase 3 完了） | ✅ |
| ~~`markets/`~~ | 3 | **`series/` に統合済**（Phase 3 完了） | ✅ |
| `forecasts/` | 4 | 機関投資家予測（値そのものより**変化**） | 6 |
| `news/` | 5 | Gold / USDJPY / マクロ予測に影響するニュースのみ分類 | 6 |
| `prediction/` | 6 | **CPI / NFP 予測（最重要）** | 5 |
| `analysis/` | 7 | マクロスコア → クロスアセット → Gold / USDJPY 解釈 | 7 |
| `reports/` | 8 | 日次 Markdown（前日差分を必ず含む） | 8 |
| `validation/` | – | 予測精度検証（MAE / RMSE / 方向 / キャリブレーション） | 9 |

**Agent は8つ。増やさない。** 1サブパッケージ = 1責務。

ただし Agent 2（マクロ指標）と Agent 3（金利・市場データ）は `series/` 1つに統合した。
両者の違いは**どの系列を担当するか**であって、**バイトを数値にする方法**ではない。
同じ payload parser・同じ vintage テーブル・同じ as-of クエリを使う以上、
分けると parser と repository が二重化する。これは指示書 §3 が禁じる
「同じデータを複数Agentが取得する構造」そのものになる。
担当の区別は `config/series.yaml` の `category` が持つ。
「Agent」と呼ぶが、必ずしも LLM ではない。数値を扱う処理は決定論的コードであり、
LLM は分類・要約・抽出・文章生成にのみ使う（憲法第5条）。

---

## 2. データフロー

```
config/sources/*.yaml
      ↓  ingestion（YAML 1枚でプロバイダ追加。コード変更なし）
data/raw/<source_id>/<YYYY-MM>/<raw_item_id>.json     ← 取得したまま永久保存
      ↓  series（実装済） / calendar / forecasts / news
observations（vintage付き）/ releases / institutional_forecasts / news_items
      ↓  prediction
predictions（毎日1行・上書き禁止）
      ↓  analysis
macro_scores → cross asset → USDJPY / Gold バイアス
      ↓
daily_deltas（昨日との差分）
      ↓  reports
reports/daily/YYYY-MM-DD.md
      ↓  validation（実績発表後）
forecast_errors → MAE / RMSE / 方向的中 / キャリブレーション
```

### 2.1 生データとデータベースの役割分担（ADR-010）

| | 置き場所 | git | 役割 |
|---|---|---|---|
| 生ペイロード | `data/raw/` | **コミットする** | 取得したまま。DB を失っても再構築できる最後の砦 |
| 正規化済みの真実 | マネージドPostgreSQL | 管理外 | vintage 付き時系列・予測・検証結果 |
| 運用状態 | `var/` | 管理外 | スケジューラ最終実行・ブレーカ・etag・DLQ・死活 |
| レポート | `reports/daily/` | **コミットする** | 人間が読む成果物 |

`var/` は失っても構わない。`data/` と DB は失ってはならない。

---

## 3. 中核となる規律

### 3.1 時刻はすべて tz-aware UTC

naive datetime は境界で拒否される（`common/timeutil.ensure_utc`）。
`observation_date` / `release_date` / `vintage_at` の区別は、
時刻が曖昧なら意味をなさない。

### 3.2 as-of クエリ

時系列の読み出しは **必ず** as-of を伴う。これは規約ではなく
`tests/unit/test_no_lookahead.py` が機械的に検査する：

- `observations` への生SQLは repository 以外に書けない
- `as_of` 引数にデフォルト値を与えられない
- repository は時計（`utc_now`）を参照できない

as-of 規律は**静かに壊れる**（テストは通り、半年後にバックテストが
不自然に良く見えて初めて気づく）ため、人間の注意力に任せない。

```sql
SELECT DISTINCT ON (series_id, observation_date) *
FROM observations
WHERE series_id = %(s)s AND vintage_at <= %(as_of)s
ORDER BY series_id, observation_date, vintage_at DESC;
```

バックテストAPIの `as_of` は**必須引数**であり、デフォルト値を持たない。
デフォルトを与えた瞬間、うっかり未来を見る経路ができる。

### 3.3 append-only は DB トリガで物理強制

訂正は行の更新ではなく、後続行の追加で行う。
アプリのバグでも、手動の psql でも、過去は書き換えられない。

### 3.4 証拠なき事実は保存できない

Event は evidence なしには書き込めない（`knowledge/store.py` がトランザクション内で拒否）。
observation は `source_id` と取得元 URL を持つ。

### 3.5 最小サンプル規律

統計量は標本数が足りなければ `None` を返す（`analysis/stats.py`, 既定 n≥30）。
呼び出し側は欠損として記録する。薄い履歴から数字をひねり出さない。

### 3.6 説明可能なスコアだけを保存する

`Signal` は `value` / `points` / `label` / `rationale` / `evidence_refs` を持ち、
`ScoreCard` は各次元の score・weight・contribution・top signals を保存する。
「なぜ +0.8 なのか」が保存された行だけから答えられない計算は作らない。

### 3.7 欠損は成果物に出す

`DimensionReport.data_gaps` と、無効化されたソースの一覧は必ずレポートに載る。
`mios health` は失敗中のソースがあれば非ゼロで終了する。

---

## 4. 設定でふるまいを変える

コードを変えずに変えられるもの：

| ファイル | 内容 |
|---|---|
| `config/sources/*.yaml` | データソース（URL・Tier・呼び出し間隔・必要な環境変数） |
| `config/series.yaml` | 追跡する時系列（担当カテゴリ・単位・頻度・改定の有無・parser） |
| `config/assets/*.yaml` | 分析対象資産とその driver 系列 |
| `config/taxonomy/*.yaml` | イベント種別・エンティティ種別・関係種別 |
| `config/scoring.yaml` | 次元ウェイト（`weights_version` が全 score card に刻印される） |
| `config/pipelines.yaml` | ジョブとその実行間隔、リトライ・ブレーカのパラメータ |

新しいプロバイダの追加は YAML 1枚。
新しい *kind*（`rss` / `http_json` / `http_csv` 以外）の追加だけがコード変更になる。

### 4.1 vintage の二種類

| parser | `vintage_at` の意味 | 用途 |
|---|---|---|
| `alfred_json` | **公表された日**（`realtime_start`） | 改定される指標。MIOS が稼働していなかった期間のバックテストに耐える |
| その他 | **取得した時刻** | 改定されない日次系列、および ALFRED を引かない系列 |

同じ指標の「現在値」と「vintage付き履歴」は**別系列**として登録する
（`ser_us_cpi_index` と `ser_us_cpi_index_vintage`）。
フラグではなく別系列にしているのは、両者が世界に対する別の観測だから：
前者は「今いくつか」、後者は「いくつだと言われ、それはいつだったか」に答える。

---

## 5. 現在の実行コマンド

```bash
mios migrate       # マイグレーション適用 + ソース台帳・系列台帳の同期
mios sources       # 設定済みソース一覧（解決後の状態）
mios series        # 系列台帳と各系列の実データ蓄積状況
mios collect       # 有効な全ソースを収集（--source で1件指定）
mios run-due       # 実行期限が来たジョブだけ実行
mios normalize     # 生データ → vintage付き観測値（parse失敗があれば exit 1）
mios observations <series_id> [--as-of ISO8601]   # その時点で知り得た系列
mios revisions <series_id> <YYYY-MM-DD>           # ある参照期間の全vintage
mios extract       # 未処理のニュース raw を候補キューへ
mios health        # ソース別の死活・DLQ 件数（失敗があれば exit 1）
```

**コマンドは、その裏のコードが存在するときにだけ追加する。**
予測・分析・レポートのコマンドは Phase 5〜9 でそれぞれの層とともに現れる。

---

## 6. 既知の未解決事項

| # | 内容 | 対応予定 |
|---|---|---|
| A-1 | 監査ログが JSONL ファイル（`var/audit/`）に出る。GitHub Actions のランナーは使い捨てなので、このままでは実行記録が残らない | Phase 10：`audit_log` / `agent_runs` テーブルへのシンクに切り替える（テーブルは 0001 で作成済み） |
| A-2 | ~~`market_snapshots` に vintage がない~~ | ✅ Phase 3 完了：`0005` で `observations`（vintage付き）を追加。旧テーブルは DROP せず参照を止めた |
| A-3 | **FRED の series_id・Treasury CSV の列名・Twelve Data のレート制限とレスポンス形状がいずれも未検証**（本作業環境から外部へ到達できない）。parser は記録済み fixture に対してのみ検証済み | 最初の実接続（Actions またはローカル）で確認する。**誤りは「収集失敗」として表面化する設計**（parser は想定外の形を黙って空扱いせず ParseError を投げる）であり、静かな誤データにはならない |
| A-4 | ~~統合テストは PostgreSQL がないと skip される~~ | ✅ Phase 2 完了：CI に PostgreSQL サービスを用意し、skip したらビルドを落とす |
| A-5 | 日本の **CPI・賃金**が未登録（JGB は Phase 4 で追加済）。e-Stat は API キーと専用 parser を要する | 未定。**データのない系列を先に登録しない**（placeholder は作らない） |
| A-6 | ~~`vintage_at` が取得時刻でしかない~~ | ✅ Phase 4 完了：主要な改定系列は ALFRED の `realtime_start` から真の vintage を取り込む（`_vintage` 系列）。ALFRED を引かない系列は取得時刻のままで、`mios series` が `published` / `fetched` で区別を表示する |
| A-7 | ALFRED の vintage は**日付**であり時刻ではない。発表当日の日中は、実際より早く知り得たことになる | 構造的な限界。UTC 0時として扱い、**遅く知る方向に倒している**（早漏れはしない）。発表時刻が必要になるのは Phase 5 のカレンダー連携時 |
