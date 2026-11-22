# 米国政策調査（一部確認）

2026年11月22日13:08 JST時点。前回11:44 JSTからの差分に24時間の重複を設けた暫定対象は11月21日11:44〜22日13:08 JST。資料ごとの最終完全確認点は不明。

【事実】[EIAの週次在庫表](https://www.eia.gov/dnav/pet/pet_stoc_wstk_dcu_nus_w.htm)で、11月6日週の商業用原油在庫414,417千バレル、13日週417,797千バレルを再確認。対象週は公表日時ではなく、公表時刻は不明。取得11月22日13:08 JST。既存 eia-20261113-commercial-crude-table0 と照合済みで重複保存しない。発表全文やPDFの翻訳・脚注は今回未確認。

## 情報源別の確認・欠損

- [treasury_news](https://home.treasury.gov/news/press-releases)：対象 2026-11-21T11:44:43+09:00/2026-11-22T13:08:57+09:00。入口を確認、個別本文・表の期間全体の確認は未完。再試行。
- [treasury_auctions](https://www.treasurydirect.gov/auctions/results/)：対象 2026-11-21T11:44:43+09:00/2026-11-22T13:08:57+09:00。入口を確認、個別本文・表の期間全体の確認は未完。再試行。
- [treasury_buybacks](https://www.treasurydirect.gov/auctions/announcements-data-results/buy-backs/)：対象 2026-11-21T11:44:43+09:00/2026-11-22T13:08:57+09:00。入口を確認、個別本文・表の期間全体の確認は未完。再試行。
- [fed_fomc](https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm)：対象 2026-11-21T11:44:43+09:00/2026-11-22T13:08:57+09:00。入口を確認、個別本文・表の期間全体の確認は未完。再試行。
- [nyfed_operations](https://www.newyorkfed.org/markets/desk-operations/treasury-securities)：対象 2026-11-21T11:44:43+09:00/2026-11-22T13:08:57+09:00。入口を確認、個別本文・表の期間全体の確認は未完。再試行。
- [white_house](https://www.whitehouse.gov/presidential-actions/)：対象 2026-11-21T11:44:43+09:00/2026-11-22T13:08:57+09:00。入口を確認、個別本文・表の期間全体の確認は未完。再試行。
- [ofac](https://ofac.treasury.gov/recent-actions)：対象 2026-11-21T11:44:43+09:00/2026-11-22T13:08:57+09:00。入口を確認、個別本文・表の期間全体の確認は未完。再試行。
- [eia_petroleum](https://www.eia.gov/petroleum/supply/weekly/)：対象 2026-11-21T11:44:43+09:00/2026-11-22T13:08:57+09:00。入口を確認、個別本文・表の期間全体の確認は未完。再試行。
- [fec_results](https://www.fec.gov/introduction-campaign-finance/election-results-and-voting-information/)：対象 2026-11-21T11:44:43+09:00/2026-11-22T13:08:57+09:00。入口を確認、個別本文・表の期間全体の確認は未完。再試行。
- [cfius](https://www.cfius.gov/)：対象 2026-11-21T11:44:43+09:00/2026-11-22T13:08:57+09:00。入口を確認、個別本文・表の期間全体の確認は未完。再試行。

入口だけでは新着なしとは断定できない。財務省買戻しとFRBの売買は別制度であり、各個別オペの表は未確認。政府発表と独立検証、選挙速報と州認証は区別するが今回の独立検証・州認証は未取得。

【推論】供給増や需要減が持続すれば原油価格、物価や金利見通しに波及し得るが、輸出入・精製稼働・季節性が在庫変化を説明するなら見直す。日・週・月それぞれで持続性は未確認。USD/JPY、EUR/USD、USD/CHF、USD/CAD、AUD/USDと金は、相手側を含む実質金利・政策等が不足し方向を保留。

[1973–74年の事例](https://github.com/samkaz15/invest/blob/main/data/history/us_policy/oil-shock-1973-1974.json)は供給面の比較候補だが、当時と現在のインフレ、実質金利、流動性、エネルギー構造の比較に必要な当時公表値は不足。後年解説を当時の情報として扱わない。3件は検証前の初期要約。

【再試行】10情報源の個別本文・表、PDF・脚注、既存メール経路との網羅照合、期限到来分の事後レビュー。既知の[DB同期失敗](https://github.com/samkaz15/invest/actions/runs/44855507045)があり、今回のPostgreSQL反映状況は未確認。GitHub保存とDB反映、PC実機通知は別であり、通知成功は未確認。
