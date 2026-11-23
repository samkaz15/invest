# 米国政策調査（部分・再試行必要）

確認 2026-11-23T14:10:25+09:00。対象 2026-11-21T23:24:58+09:00〜2026-11-23T14:10:25+09:00。最新の保存済み公表時刻を全記録から確定できず、前回の重複期間を暫定利用。入口確認は個別資料・表の網羅を意味しない。

【事実】[EIAの11月18日公表の表7](https://www.eia.gov/petroleum/supply/weekly/archive/2026/2026_11_18/download/table7.pdf)は、11月13日終了週の原油輸入を日量557.6万バレル、輸出を448.8万バレル、純輸入を108.8万バレルと示す。公表時刻不明。取得時刻 2026-11-23T14:10:25+09:00。1ページの表テキストと脚注を取得した。対象期間前の資料であり、[既存の同週輸出入記録](../../../data/knowledge/us/eia-20261113-weekly-import-export-table-excerpt.json)と主要数値が一致するため、重複を避け新規JSONは作成しない。全品目・脚注の翻訳は未完。

[OFACの11月20日付資料](https://ofac.treasury.gov/recent-actions/20261120)はイラン関連指定とキューバ関連FAQ発出を掲載、時刻不明。関連する[既存メール記録](../../../data/knowledge/us/treasury-20261120-iran-oil-outcast-mail-partial.json)の封鎖・積載に関する米政府の主張は独立検証されていない。

【推論】供給や需要の変化は物価・景気、政策・実質金利、資金需給を介して金や為替に影響し得る。単週の輸出入だけから価格方向や恒常的な供給変化は判断できない。日単位で輸送・在庫、週単位で輸出入・代替供給・需要、月単位で物価・政策反応を確認。輸出継続や代替供給増、需要減は供給不足仮説への反証。USD/JPY、EUR/USD、USD/CHF、USD/CAD、AUD/USDは双方の資料不足で方向保留。

[1973〜74年の初期ケース](../../../data/history/us_policy/oil-shock-1973-1974.json)とは供給と物価・景気の経路が比較点だが、当時の禁輸と今回の単週輸出入は異なる。当時と現在のインフレ・実質金利・流動性・エネルギー構造の比較値は未取得。後年の解説を当時の情報として扱わず、3件の初期要約に精度検証済みと主張しない。

## 情報源と欠損

各源の対象期間は上記。取得できなかったものは新着なしとせず再試行する。

- [treasury_news](https://home.treasury.gov/news/press-releases)：入口取得、期間内の個別資料全件未照合。
- [treasury_auctions](https://www.treasurydirect.gov/auctions/results/)：動的入札結果未取得。
- [treasury_buybacks](https://www.treasurydirect.gov/auctions/announcements-data-results/buy-backs/)：動的結果行未取得。
- [fed_fomc](https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm)：入口取得、個別本文・PDF未確認。
- [nyfed_operations](https://www.newyorkfed.org/markets/desk-operations/treasury-securities)：入口取得、個別オペ結果未取得。
- [white_house](https://www.whitehouse.gov/presidential-actions/)：一覧取得、個別文書全件未確認。
- [ofac](https://ofac.treasury.gov/recent-actions)：11月20日の個別本文を確認、FAQ等未照合。
- [eia_petroleum](https://www.eia.gov/petroleum/supply/weekly/)：11月18日版表7の1ページを取得、他表・PDF全体未確認。
- [fec_results](https://www.fec.gov/introduction-campaign-finance/election-results-and-voting-information/)：州認証文書未確認。
- [cfius](https://www.cfius.gov/)：入口取得、個別資料未確認。

全記録のURL・時刻・本文ハッシュ照合と期限到来レビューは未完。選挙速報と州認証を区別するが州文書は未取得。[US knowledge database sync](https://github.com/samkaz15/invest/actions/runs/45102464945)の11:50 JST開始分は失敗。GitHub保存とは別にPostgreSQL個別反映とPC実機通知は未確認。
