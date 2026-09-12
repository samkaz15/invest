# DATA_SOURCE_REGISTRY.md
# データソース台帳と信頼Tier

> 上位文書：`CONSTITUTION.md` 第4条（事実主義）・第8条4項（ソースは必ず死ぬ）
>
> **機械可読な台帳は `config/sources/*.yaml` が正である。** 本書は Tier 制度の定義と、
> 「どのカテゴリをどのソースで埋める計画か」を書く。
> 両者が矛盾したら YAML が正であり、本書を直す。

---

## 1. 信頼Tier制度

`src/mios/common/labels.py::SourceTier`（1〜4）と DB の CHECK 制約に一致する。

| Tier | 定義 | 例 | 扱い |
|---|---|---|---|
| **1** | その数値を**発表している当事者**（統計機関・中央銀行・財務省） | BLS / BEA / Census / DOL / Federal Reserve / US Treasury / 日本銀行 / 総務省統計局 / e-Stat / 財務省 | 単独で `FACT` 認定可 |
| **2** | 公式データ・市場データの**再配信者** | Twelve Data（ADR-011）、その他金融データベンダ | 単独で `FACT` 認定可（配信元の注記つき） |
| **3** | 大手金融報道（一次取材あり） | Reuters / Bloomberg / WSJ / 日経 | `REPORTED`。Tier1-2 で裏取りできたら `FACT` 昇格 |
| **4** | その他メディア・解説・コメンタリ | — | `REPORTED`。**単独で数値の根拠にしない** |

### 規律

1. **Tier 3/4 が伝える数値が、Tier 1 の公式発表を上書きすることは決してない。**
   両者が食い違う場合、Tier 1 を採用し、差異を記録する。
2. AI生成記事・匿名情報を一次データとして扱わない。
3. 台帳（`config/sources/`）にないソースからの取り込みは禁止。出所不明データの混入を防ぐ。
4. 同じ系列を Tier 1 と Tier 2 の双方が持つ場合、Tier 1 を正とし、Tier 2 はフォールバックとする。

---

## 2. ソース台帳スキーマ

ソースは `config/sources/<source_id>.yaml`（`SourceSpec` で検証）、
その payload から取り出す時系列は `config/series.yaml`（`SeriesSpec` で検証）に書く。
FRED は1回の呼び出しで1系列を返すので 1ソース = 1系列だが、
Treasury の日次カーブは1つの CSV に全年限が入るため 1ソース = 複数系列になる。

```yaml
source_id: src_fred_cpi          # ser/src/ent と同じ slug ID 規約
name: FRED CPI (CPIAUCSL)
kind: http_json                  # rss | http_json | http_csv
url: https://.../?api_key=${FRED_API_KEY}
tier: 1
enabled: true
min_interval_seconds: 60         # プロバイダのレート制限を守る下限
notes: 何のために取るのか。フォールバックがあれば書く
```

**秘密は絶対に書かない。** `${ENV_VAR}` を書くと `mios.cli.resolve_sources` が展開し、
**環境変数が未設定のソースは自動的に無効化され、データ欠損として報告される**（黙って飛ばさない）。

---

## 3. カテゴリ別のソース計画

Phase 1 は**無料〜低額ソースのみ**で開始し、見逃し検知（EVALUATION.md §7）が示した穴に応じて
有料ソースを追加する。最初から高額データを買わない。

| カテゴリ | 系列 | ソース計画 | Tier | 状態 |
|---|---|---|---|---|
| 米 物価 | CPI / Core CPI / PPI / 輸入物価 | FRED（CPIAUCSL / CPILFESL / PPIFIS / IR） | 1 | ✅ 設定済 |
| 米 物価・雇用 **改定履歴** | CPI / Core CPI / NFP / 失業率 / Core PCE の全vintage | **ALFRED**（`realtime_start` 付き） | 1 | ✅ 設定済（週次） |
| 米 物価 | PCE / Core PCE | FRED（PCEPI / PCEPILFE） | 1 | ✅ 設定済 |
| 米 雇用 | NFP / 失業率 / 平均時給 / 週労働時間 / 労働参加率 | FRED（PAYEMS / UNRATE / CES0500000003 / AWHAETP / CIVPART） | 1 | ✅ 設定済 |
| 米 雇用 | JOLTS 求人・離職 / 新規失業保険 / 継続受給 / 人材派遣 | FRED（JTSJOL / JTSQUL / ICSA / CCSA / TEMPHELPS） | 1 | ✅ 設定済 |
| 米 雇用 | ADP / Challenger | 各社公表 | 2-3 | **未着手**（取得可否を要確認） |
| 米 景気 | 小売売上 / 鉱工業生産 / 実質GDP | FRED（RSAFS / INDPRO / GDPC1） | 1 | ✅ 設定済。耐久財・住宅は未着手 |
| 米 景気 | ISM 製造業・非製造業（雇用・価格支払含む） | ISM 公表 | 2 | **未着手**（取得可否を要確認） |
| 米 景気 | 消費者信頼感 / ミシガン大 | Conference Board、UMich | 2 | **未着手** |
| 米 金利 | UST 2Y / 5Y / 10Y / 30Y | US Treasury 日次CSV（全期間）＋ FRED（DGS2 / DGS10） | 1 | ✅ 設定済（二重化＝フォールバック） |
| 米 金利 | 実質金利 5Y / 10Y / 実効FF | FRED（DFII5 / DFII10 / DFF） | 1 | ✅ 設定済 |
| 期待インフレ | BEI 5Y / 10Y | FRED（T5YIE / T10YIE） | 1 | ✅ 設定済 |
| Fed | FOMC 日程 / 声明 / 議事要旨 / SEP | Federal Reserve | 1 | Phase 5（カレンダー層とともに） |
| Fed | 利下げ確率（政策期待） | 要検討 | 2 | **未定**。取得できなければ欠損として明示する |
| 日本 物価 | CPI / コアCPI | 総務省統計局、e-Stat | 1 | **未着手**（API キーと専用 parser が必要） |
| 日本 賃金・雇用 | 毎月勤労統計 / 失業率 | 厚労省、総務省 | 1 | **未着手** |
| BOJ | 政策決定会合 / 声明 / 展望レポート | 日本銀行 | 1 | Phase 5（カレンダー層とともに） |
| JGB | 2Y / 5Y / 10Y / 20Y / 30Y | 財務省 金利情報（CSV） | 1 | ✅ 設定済（**URL・形式は未検証**） |
| 為替 | USDJPY / ドル指数 | Twelve Data（ADR-011）＋ FRED（DEXJPUS / DTWEXBGS） | 2 / 1 | ✅ 設定済。クロス円は未着手 |
| コモディティ | Gold / Silver / Oil / Copper | Twelve Data | 2 | ✅ Gold 設定済。他は未着手 |
| リスク | VIX | FRED（VIXCLS） | 1 | ✅ 設定済。株価指数は未着手 |
| 機関予測 | 各社の**公開**リサーチ・公開記事 | 各社サイト、大手報道 | 2-3 | Phase 6。**有料情報は取得しない** |
| ニュース | Fed / BOJ 公式、大手金融報道 RSS | 各公式、Reuters / Bloomberg / 日経 | 1-3 | Phase 6 |

**「未定」「要確認」「未着手」を空欄にせず明記する。** 取得できないものは欠損として扱い、
推測値で埋めない（憲法第4条3項）。

**✅ は「設定済」であって「データが入っている」ではない。**
実際の蓄積状況は `mios series` が DB を見て表示する。
API キー未設定・URL 誤り・仕様変更はいずれも「収集失敗」として表面化し、
`mios health` が非ゼロで終了する。

---

## 4. 運用ルール

1. **ソース追加の手続き**：見逃し検知レポートまたはオーナー要望 → Tier 査定 →
   `config/sources/` に YAML 追加 →（必要なら）アダプタ実装 → 本書の表を更新。
2. **死活監視**：`mios health` が連続失敗を検出し、**失敗があれば非ゼロで終了する**。
   24時間途絶したソースは日次レポートに欠損として明示される。
3. **四半期棚卸し**：そのソース由来のデータが予測に使われた回数でランキングし、死枝を剪定する。
4. **アーカイブ**：Tier 1 証拠の URL は取得時に生ペイロードごと `data/raw/` に保存される。
   リンク切れで証拠チェーンが壊れることを防ぐ。
5. **ソースは必ず死ぬ**：主要系列には可能な限りフォールバックを用意し、`notes` に書く。
   価格系（Twelve Data）は FRED の DEXJPUS / DTWEXBGS へ退避できるようにしておく。
