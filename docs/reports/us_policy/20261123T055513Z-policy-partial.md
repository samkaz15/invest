# 米国政策調査（部分・再試行必要）

確認 2026-11-23T14:55:13+09:00。対象 2026-11-21T23:24:58+09:00〜2026-11-23T14:55:13+09:00。最新の保存済み公表時刻を全記録から確定できず、前回の重複期間を暫定利用。入口の確認は個別資料・表の網羅を意味しない。

【取得上の異常】[OFAC一覧](https://ofac.treasury.gov/recent-actions)は今回「No results found」と表示されたが、既知の[11月20日付個別資料](https://ofac.treasury.gov/recent-actions/20261120)は取得できた。矛盾の原因は未確認で、一覧の表示を新着なしと扱わず再試行する。個別資料の公表時刻は不明。関連する[既存メール部分記録](../../../data/knowledge/us/treasury-20261120-iran-oil-outcast-mail-partial.json)を参照し重複保存しない。政府による封鎖・積載の記述は独立検証されていない。

前回確認した[EIA表7と既存日本語記録](../../../data/knowledge/us/eia-20261113-weekly-import-export-table-excerpt.json)は11月18日公表の期間外資料。関連表・PDFの未確認部分は未翻訳として扱う。

【推論】制裁が実際に供給を減らす場合、物価・景気、政策・実質金利、資金需給を経て金や通貨に波及し得る。日単位で輸送・在庫、週単位で輸出・代替供給・需要、月単位で物価と政策を確認。輸出継続、代替供給増、需要減は反証条件。USD/JPY、EUR/USD、USD/CHF、USD/CAD、AUD/USDは両側資料不足で方向判断保留。

[1973〜74年ケース](../../../data/history/us_policy/oil-shock-1973-1974.json)は供給・物価の経路が比較点だが、当時の禁輸と今回の実供給への影響未検証は異なる。両時点のインフレ、実質金利、流動性、エネルギー構造の比較値は未取得。後年の史料を当時の情報とせず、初期3件の予測精度を主張しない。

## 情報源の確認・欠損

各源の対象期間は上記と同じ。未取得資料は再試行対象。

- [treasury_news](https://home.treasury.gov/news/press-releases)：一覧取得。期間内個別資料の網羅照合未完。
- [treasury_auctions](https://www.treasurydirect.gov/auctions/results/)：動的な個別入札結果未取得。
- [treasury_buybacks](https://www.treasurydirect.gov/auctions/announcements-data-results/buy-backs/)：動的な買戻し結果行未取得。
- [fed_fomc](https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm)：入口取得、個別文書・PDF未照合。
- [nyfed_operations](https://www.newyorkfed.org/markets/desk-operations/treasury-securities)：入口取得、個別オペ結果未取得。
- [white_house](https://www.whitehouse.gov/presidential-actions/)：一覧取得、個別文書全件未確認。
- [ofac](https://ofac.treasury.gov/recent-actions)：一覧が「No results found」と表示され既知の11月20日資料と矛盾、一覧は不完全。既知資料は取得。
- [eia_petroleum](https://www.eia.gov/petroleum/supply/weekly/)：入口取得、個別表・PDFの全体未確認。
- [fec_results](https://www.fec.gov/introduction-campaign-finance/election-results-and-voting-information/)：州認証文書未確認。
- [cfius](https://www.cfius.gov/)：入口取得、個別資料未確認。

既存全レコードの重複照合と期限到来レビューは未完。選挙速報と州認証は区別するが州文書未取得。[US knowledge database sync](https://github.com/samkaz15/invest/actions/runs/45102464945)の11:50 JST開始分は失敗。GitHub保存とは別にPostgreSQL個別反映とPC実機通知は未確認。
