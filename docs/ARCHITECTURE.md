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
L2 正規化  series      生データ → vintage付き観測値
                       + 発表カレンダー（calendar.py・唯一 upsert する場所）
   ↓
L4 分析    analysis    次元スコア（Signal の集合 → DimensionReport）
   ↓
L6 予測    prediction  先行指標 → CPI / NFP 予測（毎日1行・上書き禁止）
L7 検証    validation  予測 × 初回発表値 → 誤差・対ナイーブ skill・キャリブレーション
L8 出力    reports     保存済み成果物の整形 → reports/daily/YYYY-MM-DD.md
                       + exports/*.csv（スプレッドシート用・ADR-013）
```

`analysis` はマクロ8次元スコアと Gold / USDJPY の2ビューを作る。
`reports` は**保存済みの行を整形するだけ**で、計算を一切行わない
（`tests/integration/test_analysis_report_db.py` が
 report モジュールが scorer/forecaster を import しないことを検査する）。

### 1.1 残りの層（✅ 以外は**現在は未実装**）

| パッケージ | Agent | 内容 | Phase |
|---|---|---|---|
| `calendar/` | 1 | 経済指標発表予定、FOMC / BOJ 日程、次回までの日数 | 5 |
| ~~`data/`~~ | 2 | **`series/` に統合済**（Phase 3 完了） | ✅ |
| ~~`markets/`~~ | 3 | **`series/` に統合済**（Phase 3 完了） | ✅ |
| `forecasts/` | 4 | 機関投資家予測（値そのものより**変化**） | 6 |
| `news/` | 5 | Gold / USDJPY / マクロ予測に影響するニュースのみ分類 | 6 |
| ~~`prediction/`~~ | 6 | **CPI / NFP 予測** — ✅ Phase 5 完了 | ✅ |
| ~~`analysis/`~~ | 7 | マクロスコア → クロスアセット → Gold / USDJPY 解釈 — ✅ Phase 7 完了 | ✅ |
| ~~`reports/`~~ | 8 | 日次 Markdown（前日差分を必ず含む） — ✅ Phase 8 完了 | ✅ |
| ~~`validation/`~~ | – | 予測精度検証 — ✅ Phase 9 完了（順序を前倒し） | ✅ |

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

### 3.6 予測は「ナイーブ + 説明可能な調整」

```
point = baseline + Σ (先行指標の読み × 設定された weight)
```

`baseline`（直近数期の平均＝ナイーブ予測）を**予測と一緒に保存する**。
「調整が仕事をしたのか」を行だけから答えられるようにするため。
調整が常にゼロ近傍なら、先行指標は飾りであり、検証がそう言う。

**weight は「事前分布」であって推定値ではない。** 今フィットしても
数十期しかなく、in-sample だけ良く見えるものができるだけである。
各 weight には `justification` が必須で、誤差が溜まった時点で
再推定する権利を得る（`docs/EVALUATION.md` §3）。

driver は2種類：

| mode | 変換 | 例 |
|---|---|---|
| `elastic` | バスケット構成比で直接換算（ほぼ機械的） | ガソリン価格 → headline CPI |
| `standard` | 自然な換算が無いので σ で表現し、事前分布で換算 | 失業保険申請 → NFP |

確率は「実績が baseline を上回る確率」であり、
**この手法自身の過去の baseline 誤差の広がり**から導く。
履歴が足りなければ `None` を返す（50% は捏造）。
また **5%〜95% に丸める** — 未較正の事前分布に基づく手法が
99% を主張する資格はない（憲法第5条）。

### 3.7 採点は「初回発表値」に対して行う

実績には**最初に発表された値**を使う。最新の改定値ではない。

予測者が当てようとしているのは「発表される数字」である。3ヶ月後に
改定された値で採点するのは、誰も問うていない問いで採点することであり、
さらに悪いことに**採点を走らせるたびに答えが変わる**（的が動く）。
初回 vintage は永久に固定されるので、今日計算した採点と来年計算した
採点が一致する。

そして、あらゆる数値は**ナイーブ予測との相対**で述べる。
「MAE は 0.08pp でした」は単独では反証不能な飾りであり、
「MAE は 0.08pp、何もしなければ 0.11pp だった」が発見である。
この差を `skill` として保存する。

### 3.8 説明可能なスコアだけを保存する

`Signal` は `value` / `points` / `label` / `rationale` / `evidence_refs` を持ち、
`ScoreCard` は各次元の score・weight・contribution・top signals を保存する。
「なぜ +0.8 なのか」が保存された行だけから答えられない計算は作らない。

### 3.9 「見えていないもの」を必ず書く

すべてのマクロ次元・資産ビューは `blind_spots` を**必須**とし、
設定スキーマが空リストを拒否する。

実質金利とドルで金を説明するモデルは、間違ってはいないが**不完全**である。
そして不完全さは出力からは見えない。誰かが書き留めない限り、
読み手はモデルの沈黙を「そういう要因が無かった」と読む。

例（`config/analysis.yaml` より）：

- 中央銀行の金購入は一次的な要因だが、どの利回り系列にも現れない
- MOF の為替介入は金利差ドリフトを1日で反転させるが、観測できない
- 地政学リスクプレミアムは VIX に現れる前に金に現れる

### 3.10 欠損は成果物に出す

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
| `config/forecast.yaml` | 予測対象と先行指標・weight・その根拠（`method_version` が全予測に刻印される） |
| `config/analysis.yaml` | マクロ次元・資産ビューの構成・weight・伝播経路の根拠・**blind_spots（必須）** |

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
mios verify-sources [--source <id>]               # 全ソースを取得・parse（保存はしない）
mios series        # 系列台帳と各系列の実データ蓄積状況
mios calendar [--as-of ISO8601] [--days N]        # 発表予定の取り込みと表示
mios releases      # 発表済みの数字を releases に記録
mios export [--as-of ISO8601]                     # exports/*.csv を書き出す
mios collect       # 有効な全ソースを収集（--source で1件指定）
mios run-due       # 実行期限が来たジョブだけ実行
mios normalize     # 生データ → vintage付き観測値（parse失敗があれば exit 1）
mios observations <series_id> [--as-of ISO8601]   # その時点で知り得た系列
mios revisions <series_id> <YYYY-MM-DD>           # ある参照期間の全vintage
mios forecast [--as-of ISO8601]                   # 予測を実行し、その日の vintage を保存
mios forecasts <series_id> <YYYY-MM-DD>           # ある対象期間への予測の全履歴
mios analyze [--as-of ISO8601]                    # マクロ8次元 + Gold / USDJPY ビュー
mios report [--as-of ISO8601]                     # reports/daily/YYYY-MM-DD.md を生成
mios validate [--as-of ISO8601]                   # 発表済みの対象期間の予測を採点
mios accuracy [--series <id>]                     # MAE / 対ナイーブ skill / 方向 / キャリブレーション
mios health        # ソース別の死活・DLQ 件数（失敗があれば exit 1）
```

**コマンドは、その裏のコードが存在するときにだけ追加する。**
予測・分析・レポートのコマンドは Phase 5〜9 でそれぞれの層とともに現れる。

---

## 5.1 日次自動実行（GitHub Actions）

`.github/workflows/daily.yml` が平日 07:10 UTC に実行する。
**チェーン本体は workflow ではなく `mios daily` にある。**

当初は workflow と Makefile の両方にチェーンを書き下しており、
**実際に食い違った**：workflow は収集失敗を許容してレポートを出すのに、
`make daily-report` は最初のエラーで止まり、何も生成しなかった。
つまり「部分的な失敗でもレポートは出る」という設計が、
片方では真で、もう片方では偽だった。定義は1つにする。

設計は2つの原則で決まっている。

**部分的な失敗でもレポートは必ず生成する。**
プロバイダが1つ死ぬのは日常であり、そのせいでその日のスナップショットを
失うのは日常ではない。収集系のステップは `continue-on-error` とし、
レポート生成だけは常に実行する。**レポートは欠損を明記するので、
何かが壊れた日にこそ最も価値がある。**
`DAILY_CHAIN`（`src/mios/cli.py`）の各ステップに
「失敗を許容するか」が書かれており、`report` と `migrate` だけが不許容。

**失敗を成功に見せない。**
壊れたステップは job summary に出し、ジョブは**最後に**失敗する。
先に失敗させると、失敗を記録した唯一の成果物がコミットされない。

コミットは `data:` と `report:` で分ける（指示書 §23）。
`git log -- data/` と `git log -- reports/` がそれぞれ
1つの事柄の履歴として読めるようにするため。

必要な secrets：`MIOS_DATABASE_URL`（ADR-010）、`FRED_API_KEY`、
`TWELVEDATA_API_KEY`（ADR-011）。

別に `verify-sources.yml` があり、Actions タブから手動実行できる。
全ソースを取得して parse し、**何も保存しない**ので、
本番の認証情報に対していつ実行しても安全。週1回も自動で走る
（プロバイダは予告なく列名を変え、series を廃止する。
思い出した時だけ走る検査は検査ではない）。
`MIOS_DATABASE_URL` が未設定なら**着手前に失敗する** —
無いDBに対しては下流のすべてが「成功」してしまうため。

`tests/unit/test_workflows.py` が workflow の YAML を読み、
(a) 呼び出しているコマンドが実際に CLI に存在すること、
(b) workflow と Makefile が**同じ**チェーンを呼んでいること、
(c) レポートより先に失敗しないこと、を検査する。

---

## 6. 既知の未解決事項

| # | 内容 | 対応予定 |
|---|---|---|
| A-1 | ~~監査ログがファイルにしか出ない~~ | ✅ Phase 10 完了：`PostgresAuditSink` を追加し、ファイルとDBの両方へ書く（`TeeAuditSink`）。DB到達不可時は警告を出してファイルのみに退避する |
| A-2 | ~~`market_snapshots` に vintage がない~~ | ✅ Phase 3 完了：`0005` で `observations`（vintage付き）を追加。旧テーブルは DROP せず参照を止めた |
| A-3 | ~~FRED の series_id・Treasury CSV の列名・Twelve Data のレスポンス形状が未検証~~ | ✅ **2026-09-14 の初回 verify-sources で解決。** 実プロバイダに接続し、FRED 46系列の series_id、ALFRED の vintage 取得、Treasury カーブの全年限の列名、Twelve Data の形状、FRED releases API —— **すべて設定通りで正しかった**。これらは外部到達のない環境で書いたもので、最大の未検証リスクだった。設定を変えたら `verify-sources` を再実行する |
| A-18 | **ニュース・機関予測・日本のデータを収集しない**（ADR-015 で対象外と決定）。したがって (1) 比較対象はナイーブ基準のみで「市場がすでに知っていたことより良かったか」に答えられない、(2) USDJPY は金利差の米国側だけで構成される、(3) 出来事は系列の数字に現れるまで見えない | 意図的な範囲の限定であり、未実装ではない。日次レポートの「このレポートが見ていないもの」節が毎回明示する。再開する場合は ADR-015 の判断を覆す ADR を書く |
| A-4 | ~~統合テストは PostgreSQL がないと skip される~~ | ✅ Phase 2 完了：CI に PostgreSQL サービスを用意し、skip したらビルドを落とす |
| A-13 | **FRED の releases/dates が将来日程を返すか未検証**、および release_name の綴りが未検証 | `mios verify-sources` と初回の `mios calendar` で判明する。照合ゼロ件として表面化し、静かな誤データにはならない。実データの名前一覧は `mios calendar` の出力から拾える |
| A-6 | ~~`vintage_at` が取得時刻でしかない~~ | ✅ Phase 4 完了：主要な改定系列は ALFRED の `realtime_start` から真の vintage を取り込む（`_vintage` 系列）。ALFRED を引かない系列は取得時刻のままで、`mios series` が `published` / `fetched` で区別を表示する |
| A-8 | **driver 系列の多くは ALFRED を引いていない**ため、過去日のバックテストでは driver の読みが当時の値ではなく「取得時点の値」になる。`_vintage` 系列を持つ5指標のみ厳密 | driver 側にも ALFRED を広げるかを、収集コストと精度改善を見て判断する。`mios series` の `published` / `fetched` 列で現状が分かる |
| A-7 | ALFRED の vintage は**日付**であり時刻ではない。発表当日の日中は、実際より早く知り得たことになる | 構造的な限界。UTC 0時として扱い、**遅く知る方向に倒している**（早漏れはしない）。発表時刻が必要になるのは Phase 5 のカレンダー連携時 |
