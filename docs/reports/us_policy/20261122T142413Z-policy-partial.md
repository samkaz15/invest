# 米国政策調査（部分・再試行必要）

取得 2026-11-22T23:24:58+09:00。前回の22:30 JSTからの差分を対象に、2026-11-21 22:30 JST以降を重複期間として確認した。10情報源の入口確認はできたが、個別資料の網羅は未完了であり、新着なしとは判断できない。

## 確認できた資料と制約

- [OFAC：11月20日のイラン指定](https://ofac.treasury.gov/recent-actions/20261120)。公表時刻不明。既存の[財務省メール部分記録](https://github.com/samkaz15/invest/blob/main/data/knowledge/us/treasury-20261120-iran-oil-outcast-mail-partial.json)と関連するため、新規知識JSONは作成していない。財務省による封鎖・積載に関する記述は政府の主張であり、独立検証は未実施。人物別の根拠や本文の完全翻訳も未完。
- [EIA原油在庫表](https://www.eia.gov/dnav/pet/pet_stoc_wstk_dcu_nus_w.htm)：11月13日終了週の商業原油在庫は4億1779万7000バレル、前週は4億1441万7000バレル。11月18日版であり、今回の新規発表ではない。全表・関連PDF未確認。

## 条件付き分析

制裁が実際に輸出や決済を妨げれば、原油供給の制約から物価や景気、金利に波及し、金や為替にも影響し得る。一方、代替供給の増加、需要減、輸送や決済の継続が確認されればこの仮説は弱まる。数日では輸送と在庫、数週では輸出と代替供給、数か月では物価や期待への波及を確認する。ドル円、ユーロドル、ドルスイス、ドルカナダ、豪ドル米ドルは通貨の両側の資料が不足し判断保留。

1973〜74年の事例との共通点は供給制約の可能性だが、当時は禁輸と減産が実施され、現在の実際の供給影響は未検証。エネルギー依存度、為替制度、政策環境も異なる。当時公表時点のインフレ・金利・流動性の資料は未取得。後年の解説を当時の情報として扱わない。[史料付き初期事例](https://github.com/samkaz15/invest/blob/main/data/history/us_policy/oil-shock-1973-1974.json)は検証済み予測モデルではない。

## 情報源別の未完項目

対象期間はいずれも2026-11-21 22:30〜2026-11-22 23:24 JST、入口確認 2026-11-22T23:24:58+09:00。下記は新着なしを意味せず、すべて再試行対象。

- [treasury_news](https://home.treasury.gov/news/press-releases)：一覧・入口のみ、対象期間の個別文書と表の網羅確認未完。
- [treasury_auctions](https://www.treasurydirect.gov/auctions/results/)：一覧・入口のみ、対象期間の個別文書と表の網羅確認未完。
- [treasury_buybacks](https://www.treasurydirect.gov/auctions/announcements-data-results/buy-backs/)：結果表は動的で行が取得できず、個別実績未確認。
- [fed_fomc](https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm)：一覧・入口のみ、対象期間の個別文書と表の網羅確認未完。
- [nyfed_operations](https://www.newyorkfed.org/markets/desk-operations/treasury-securities)：一覧・入口のみ、対象期間の個別文書と表の網羅確認未完。
- [white_house](https://www.whitehouse.gov/presidential-actions/)：一覧・入口のみ、対象期間の個別文書と表の網羅確認未完。
- [ofac](https://ofac.treasury.gov/recent-actions)：11月20日の指定ページを取得。詳細指定・添付全文の照合は未完。
- [eia_petroleum](https://www.eia.gov/petroleum/supply/weekly/)：11月18日公開の表を一部取得。期間内の個別資料・PDF全文の網羅は未確認。
- [fec_results](https://www.fec.gov/introduction-campaign-finance/election-results-and-voting-information/)：州の速報及び認証の個別資料未確認。
- [cfius](https://www.cfius.gov/)：一覧・入口のみ、対象期間の個別文書と表の網羅確認未完。

期限到来分の事後レビュー、全既存記録との本文・ハッシュ照合、個別資料の全文訳とPDFページ確認は未完。過去に[DB同期失敗](https://github.com/samkaz15/invest/actions/runs/44855507045)が記録されており、今回のPostgreSQL反映は未確認。GitHubへの保存とDB反映、Mac実機通知は別である。実機通知は未確認。
