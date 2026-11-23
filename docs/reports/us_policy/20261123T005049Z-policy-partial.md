# 米国政策調査（部分・再試行必要）

確認時刻 2026-11-23T09:50:49+09:00。対象 2026-11-21T23:24:58+09:00〜2026-11-23T09:50:49+09:00。最新保存公表時刻を全記録から確定できず、前回の重複期間を暫定利用。各源の入口確認は期間内の資料の網羅を保証しない。

【事実】今回新たに取得した[EIA週報要約](https://www.eia.gov/petroleum/supply/weekly/archive/2026/2026_11_18/download/summary.txt)は11月13日終了週について、商業原油在庫が前週比340万バレル増の4億1780万バレルとする。アーカイブの公表日は11月18日、実公表時刻は不明で、今回の差分期間より前の未処理資料。取得日時は上記JST。要約の全文訳は[保存記録](../../../data/knowledge/us/eia-wpsr-summary-20261118-20261113.json)に記載。すでにある[別PDFの部分記録](../../../data/knowledge/us/eia-20261113-wpsr-overview-partial-20261118.json)と資料を区別した。[別の1ページ表](https://www.eia.gov/petroleum/supply/weekly/archive/2026/2026_11_18/download/table0.pdf)も本文テキストを取得したが、全表・残余PDF・図表の確認と翻訳は未完。表1 CSV取得は形式非対応で失敗。

【推論】在庫増だけでは市場予想との差、今後の供給や需要を確定できない。供給・需要→物価・景気→政策・実質金利→金・為替という経路を日・週・月で検証する。代替供給増や需要減、実際の輸出継続は供給不足仮説の反証条件。USD/JPY、EUR/USD、USD/CHF、USD/CAD、AUD/USDは両国の資料不足で方向判断を保留。

[1973〜74年の初期ケース](../../../data/history/us_policy/oil-shock-1973-1974.json)は石油供給と物価・景気の関係が共通するが、当時の禁輸・減産と今回の在庫増は異なる。当時と現在のインフレ・実質金利・流動性・エネルギー構造の比較値は未取得。後年の史料は当時の予測情報に使えず、3ケースは精度検証前の初期要約。

## 情報源と欠損

各源の対象期間は上記と同じ。未取得を新着なしとしない。

- [treasury_news](https://home.treasury.gov/news/press-releases)：一覧確認、個別期間の完全照合未完。
- [treasury_auctions](https://www.treasurydirect.gov/auctions/results/)：動的結果表未取得。
- [treasury_buybacks](https://www.treasurydirect.gov/auctions/announcements-data-results/buy-backs/)：結果表の行未取得。
- [fed_fomc](https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm)：入口取得、個別本文PDF未照合。
- [nyfed_operations](https://www.newyorkfed.org/markets/desk-operations/treasury-securities)：入口取得、個別オペ結果未取得。
- [white_house](https://www.whitehouse.gov/presidential-actions/)：一覧取得、全ページと個別資料未確認。
- [ofac](https://ofac.treasury.gov/recent-actions)：11月20日個別資料確認、FAQ・全件照合未完。
- [eia_petroleum](https://www.eia.gov/petroleum/supply/weekly/)：11月18日版要約全文と別の1ページPDFを取得、表1 CSV取得失敗、残余PDF未読。
- [fec_results](https://www.fec.gov/introduction-campaign-finance/election-results-and-voting-information/)：州認証個別資料未確認。
- [cfius](https://www.cfius.gov/)：入口取得、関連資料全件未確認。

[OFACの11月20日付資料](https://ofac.treasury.gov/recent-actions/20261120)と関連メール記録を参照した過去報告は[こちら](20261122T234018Z-policy-partial.md)。政府による封鎖等の記述は政府の主張で、独立検証していない。選挙の速報と州認証は区別し、州文書未取得。

既存記録の全文ハッシュによる完全照合、過去分析の期限到来分と実績によるレビューは未完。資料・PDF・照合・レビューは再試行対象。[直近確認されたUS knowledge database sync](https://github.com/samkaz15/invest/actions/runs/45074322835)は11月23日06:50 JST開始で失敗。新規JSONのGitHub保存はPostgreSQL反映を意味せず、DBへの個別反映とPC実機通知は未確認。
