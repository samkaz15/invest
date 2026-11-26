# Political & Macro Intelligence

公開情報の現状分析専用。予想・売買指示・日中足は扱わない。米国、日本、スペインを初期対象とする。国別マスターは初期情報であり網羅ではない。`data/political_macro/countries.json` の `missing` は取得待ちである。初期情報の取得時点は暫定で、今後の実行ごとに原典の有効時点と公開時刻を確認する。

`python ops/political_macro.py validate SNAPSHOT.json` で入力検証、`python ops/political_macro.py report SNAPSHOT.json OUTPUT.md --as-of YYYY-MM-DD` で不変報告を作成する。入力は `country`, `event`, `observed_at`, `records` を持つ JSON。各 record は `label` (FACT/REPORTED/INFERENCE), `topic`, `text`, `source_url`, `published_at` を持つ。公開日時不明は null、INFERENCE は根拠を持つ。公的結果・速報・予測・世論調査は `kind` で区別し、投票結果の未認証を認証済みとしない。市場データは日次以上、観測時刻・単位・価格と出典を揃える。計算は公的数値からのみ行い、法定過半数と出席者過半数を分ける。比較は同一対象・単位・時点に限る。選挙制度は国や議院・投票手続によって異なるため一般化しない。

ファイルは追記専用。既存報告を上書きせず、訂正は新ファイルで `supersedes` を指定。検索・取得の失敗、未読 PDF、参照範囲の欠落は明示。各国の政府・中央銀行・議会・選挙機関の URL を入口として、個別の公式本文を保存・時刻付きで確認する。政党・候補者の政策は当人の公開資料に帰属。出典を確認できない場合は空欄のまま残す。報道・見通しを事実と区別し、将来の勝敗・価格の推定は禁止。外部 API キーや個人情報を保存しない。

この初期版は入力済み資料からの検証と報告生成を提供する。収集スケジューラ、APIによる自動取得、投開票結果および時系列市場データの自動集計は未実装。独立した分析であり既存モデル入力や米国・日本の通知経路を変更しない。
