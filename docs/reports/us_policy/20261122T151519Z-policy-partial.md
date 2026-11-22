# 米国政策調査（部分、再試行必要）

確認時刻 2026-11-23T00:15:19+09:00。前回の確認以降の差分を、重複期間 2026-11-21T23:24:58+09:00 から確認した。入口は確認したが、個別資料・表・添付の照合が未完のため、新着なしとは判定しない。

[OFACの11月20日付個別発表](https://ofac.treasury.gov/recent-actions/20261120)はイラン指定とキューバ関連FAQを掲載。公表時刻は不明。[既存メール記録](https://github.com/samkaz15/invest/blob/main/data/knowledge/us/treasury-20261120-iran-oil-outcast-mail-partial.json)は一部訳で残余未翻訳。政府の封鎖や輸送に関する主張は独立検証されていない。個人情報を含む指定詳細は複製していない。

条件付き推論：制裁が実際に石油輸出を減らせば供給・物価・景気・実質金利を経て金や為替に影響し得る。代替供給増、需要減、取引の継続は反証条件。日単位で在庫や輸送、週単位で輸出と代替供給、月単位で物価・景気・金利への波及を確認。ドル円、ユーロドル、ドルスイス、ドルカナダ、豪ドル米ドルは両側の資料不足で判断保留。

[1973〜74年の初期ケース](https://github.com/samkaz15/invest/blob/main/data/history/us_policy/oil-shock-1973-1974.json)は供給制約という類似点があるが、当時の実施された禁輸・減産と現在の未検証の影響を区別する。当時のインフレ・実質金利・流動性・輸入依存に関する当時公表値は未取得。後年の解説を当時の予測情報に使わない。

## 情報源ごとの欠損

対象期間は各源とも 2026-11-21T23:24:58+09:00〜2026-11-23T00:15:19+09:00。全件再試行対象。

- [treasury_news](https://home.treasury.gov/news/press-releases)：入口を確認、対象期間の個別本文・表・添付の網羅確認未完。
- [treasury_auctions](https://www.treasurydirect.gov/auctions/results/)：入口を確認、対象期間の個別本文・表・添付の網羅確認未完。
- [treasury_buybacks](https://www.treasurydirect.gov/auctions/announcements-data-results/buy-backs/)：入口を確認、対象期間の個別本文・表・添付の網羅確認未完。
- [fed_fomc](https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm)：入口を確認、対象期間の個別本文・表・添付の網羅確認未完。
- [nyfed_operations](https://www.newyorkfed.org/markets/desk-operations/treasury-securities)：入口を確認、対象期間の個別本文・表・添付の網羅確認未完。
- [white_house](https://www.whitehouse.gov/presidential-actions/)：入口を確認、対象期間の個別本文・表・添付の網羅確認未完。
- [ofac](https://ofac.treasury.gov/recent-actions)：11月20日個別ページ取得。個人情報を含む指定詳細は保存せず、添付・FAQと全期間照合は未完。
- [eia_petroleum](https://www.eia.gov/petroleum/supply/weekly/)：入口を確認、対象期間の個別本文・表・添付の網羅確認未完。
- [fec_results](https://www.fec.gov/introduction-campaign-finance/election-results-and-voting-information/)：入口を確認、対象期間の個別本文・表・添付の網羅確認未完。
- [cfius](https://www.cfius.gov/)：入口を確認、対象期間の個別本文・表・添付の網羅確認未完。

個別資料の全文訳、PDFページ、重複の全面照合、期限到来分の事後レビューは未完。PostgreSQL同期の現況は未確認。過去に[同期失敗](https://github.com/samkaz15/invest/actions/runs/44855507045)が記録されている。GitHub保存とDB反映、Mac通知は別で、実機通知は未確認。
