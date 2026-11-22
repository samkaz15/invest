# 米国政策調査（部分・再試行必要）

確認時刻 2026-11-23T08:40:18+09:00。確認対象 2026-11-21T23:24:58+09:00〜2026-11-23T08:40:18+09:00。直近の保存済み公表時刻を全記録から確定できず、前回と同じ重複期間を暫定使用した。各入口の確認は網羅的な新着確認を意味しない。

## 確認できたこと

- [OFACの11月20日付指定・FAQ](https://ofac.treasury.gov/recent-actions/20261120) の本文を確認。イラン関連指定とキューバ関連FAQを公表した。公表時刻不明。関連する[財務省メールの部分記録](https://github.com/samkaz15/invest/blob/main/data/knowledge/us/treasury-20261120-iran-oil-outcast-mail-partial.json)を確認したが、同一文書と関連文書の全件ハッシュ照合は未完。個人情報を複製しない。軍事封鎖等は財務省の主張であり独立検証していない。
- [EIA週報の11月18日版](https://www.eia.gov/petroleum/supply/weekly/archive/2026/2026_11_18/wpsr_2026_11_18.php)は11月13日終了週を対象とする。表とPDFの数値・本文は未取得。今回の差分期間より前の資料である。

## 伝達経路と検証条件

推論：制裁が実供給を制約すれば供給減→物価・景気→政策金利・実質金利・資金需要→金や為替に波及し得る。実供給減は未確認。日単位で輸送・在庫、週単位で輸出・代替供給、月単位で物価・景気を確認。輸出・決済の継続や代替供給、需要減は反証条件。ドル円、ユーロドル、ドルスイス、ドルカナダ、豪ドル米ドルは両通貨側の資料不足で方向判断保留。

[1973〜74年の石油ショック初期ケース](https://github.com/samkaz15/invest/blob/main/data/history/us_policy/oil-shock-1973-1974.json)は供給制約が比較点だが、当時の禁輸・減産と今回の供給影響未検証は異なる。元史料は後年の解説で、当時の予測根拠に使えない。当初のインフレ、実質金利、流動性、エネルギー構造の当時値と現在値は未取得。3件のケースは初期要約で精度検証済みではない。

## 情報源ごとの範囲と欠損

各情報源について上記期間を対象として入口を確認。以下は実際に取得した範囲であり、未取得分は再試行対象。

- [treasury_news](https://home.treasury.gov/news/press-releases)：一覧取得。11/20制裁発表が最新表示。個別資料・期間全体未完。
- [treasury_auctions](https://www.treasurydirect.gov/auctions/results/)：入口のみ。動的な入札結果・個別表未取得。
- [treasury_buybacks](https://www.treasurydirect.gov/auctions/announcements-data-results/buy-backs/)：表見出し取得、結果行は取得できず。
- [fed_fomc](https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm)：カレンダー取得、個別本文とPDF未確認。
- [nyfed_operations](https://www.newyorkfed.org/markets/desk-operations/treasury-securities)：入口取得、個別取引結果未取得。
- [white_house](https://www.whitehouse.gov/presidential-actions/)：一覧取得、表示上の最新は11/20。個別本文・全ページ未確認。
- [ofac](https://ofac.treasury.gov/recent-actions)：一覧と11/20個別本文を取得。関連FAQ・添付および網羅照合未完。
- [eia_petroleum](https://www.eia.gov/petroleum/supply/weekly/)：一覧と11/18アーカイブ目次を取得。個別データ表・PDF未取得。
- [fec_results](https://www.fec.gov/introduction-campaign-finance/election-results-and-voting-information/)：入口取得。各州の認証文書未確認。
- [cfius](https://www.cfius.gov/)：入口とプレス一覧取得。最新表示は8/7、全関連資料未確認。

個別PDFの原文・訳文・ページ・図表は未取得であり翻訳済みではない。新しいknowledge文書は保存していない。期限到来レビューとその評価データは未確認。既存記録の完全照合も未完。

## 保存と同期

この報告と対応分析のGitHub保存、PostgreSQL同期、PC通知は別の処理。[直近確認した同期実行](https://github.com/samkaz15/invest/actions/runs/45074322835)は11月23日06:50 JST開始で失敗し、個別DB反映は未確認。PC実機通知は未確認。未取得資料・表・PDF、全件重複照合、過去レビュー、DB同期を再試行する。
