# 米国政策調査（一部確認）2026年11月22日16:52 JST

前回15:45から24時間重複を設けた暫定対象は11月21日15:45〜22日16:52 JST。各情報源の最終完全確認時刻は不明。

【事実】[EIA週次表](https://www.eia.gov/dnav/pet/pet_stoc_wstk_dcu_nus_w.htm)を確認。商業用原油在庫（リース在庫除く）は11月6日週414,417千バレル、13日週417,797千バレル。対象週は公表時刻ではなく、公表時刻は不明。取得11月22日16:52 JST。[既存記録](../../../data/knowledge/us/eia-20261113-commercial-crude-table0.json)と照合済みで重複保存せず。PDFや表以外の原文・全文訳は未確認。

財務省の[イラン石油関連制裁発表](https://home.treasury.gov/news/press-releases/sb0697/)は11月20日米国日付、公表時刻不明、取得11月22日16:52 JST。政府の封鎖・積載に関する記述は主張であり、独立検証していない。[既存の部分メール記録](../../../data/knowledge/us/treasury-20261120-iran-oil-outcast-mail-partial.json)と題名・冒頭が重複。全文訳と全文ハッシュ照合は未完、補完は新IDとsupersedesを用いる。

## 情報源別の確認と欠損

- [treasury_news](https://home.treasury.gov/news/press-releases)：2026-11-21T15:45:27+09:00/2026-11-22T16:52:09+09:00を対象。入口確認、個別文書と表の網羅確認未完。再試行。
- [treasury_auctions](https://www.treasurydirect.gov/auctions/results/)：2026-11-21T15:45:27+09:00/2026-11-22T16:52:09+09:00を対象。入口確認、個別文書と表の網羅確認未完。再試行。
- [treasury_buybacks](https://www.treasurydirect.gov/auctions/announcements-data-results/buy-backs/)：2026-11-21T15:45:27+09:00/2026-11-22T16:52:09+09:00を対象。入口確認、個別文書と表の網羅確認未完。再試行。
- [fed_fomc](https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm)：2026-11-21T15:45:27+09:00/2026-11-22T16:52:09+09:00を対象。入口確認、個別文書と表の網羅確認未完。再試行。
- [nyfed_operations](https://www.newyorkfed.org/markets/desk-operations/treasury-securities)：2026-11-21T15:45:27+09:00/2026-11-22T16:52:09+09:00を対象。入口確認、個別文書と表の網羅確認未完。再試行。
- [white_house](https://www.whitehouse.gov/presidential-actions/)：2026-11-21T15:45:27+09:00/2026-11-22T16:52:09+09:00を対象。入口確認、個別文書と表の網羅確認未完。再試行。
- [ofac](https://ofac.treasury.gov/recent-actions)：2026-11-21T15:45:27+09:00/2026-11-22T16:52:09+09:00を対象。入口確認、個別文書と表の網羅確認未完。再試行。
- [eia_petroleum](https://www.eia.gov/petroleum/supply/weekly/)：2026-11-21T15:45:27+09:00/2026-11-22T16:52:09+09:00を対象。入口確認、個別文書と表の網羅確認未完。再試行。
- [fec_results](https://www.fec.gov/introduction-campaign-finance/election-results-and-voting-information/)：2026-11-21T15:45:27+09:00/2026-11-22T16:52:09+09:00を対象。入口確認、個別文書と表の網羅確認未完。再試行。
- [cfius](https://www.cfius.gov/)：2026-11-21T15:45:27+09:00/2026-11-22T16:52:09+09:00を対象。入口確認、個別文書と表の網羅確認未完。再試行。

【推論】輸送・決済の制約が実際に世界供給を減らせば、原油価格から物価・景気、政策金利や資金需給に波及し得る。輸出減を確認できない場合や代替供給が十分な場合は見直す。日・週・月ごとに輸送、輸出と代替供給、物価と政策反応を確認。USD/JPY、EUR/USD、USD/CHF、USD/CAD、AUD/USDと金は双方の実質金利・景気資料が不足し方向を保留。

[1973〜74年の石油ショック](https://github.com/samkaz15/invest/blob/main/data/history/us_policy/oil-shock-1973-1974.json)は供給制約の比較候補。今回の実供給減は未検証、当時と現在のインフレ・実質金利・流動性・エネルギー構造は未照合。後年の解説を当時の情報として使わない。3事例は検証前の初期要約。

【再試行】入札・財務省買戻し・FRBオペの個別表、州選挙認証、戦況独立検証、PDF・全文訳、既存メールの全文ハッシュ照合、期限到来分の事後レビュー。過去の[DB同期失敗](https://github.com/samkaz15/invest/actions/runs/44855507045)を把握しているが、今回のPostgreSQL反映は未確認。GitHub保存とDB反映、PC実機通知は別で、通知は未確認。
