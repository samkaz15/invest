# 米国政策調査（部分確認）

確認時刻 2026-11-23T00:52:17+09:00。前回以降の差分を対象に、重複期間 2026-11-21T23:24:58+09:00 以降を確認した。10情報源の入口を再取得したが、個別文書・表の網羅は未完で、新着なしとは結論できない。

[OFACの11月20日付イラン指定](https://ofac.treasury.gov/recent-actions/20261120)は[既存メール記録](https://github.com/samkaz15/invest/blob/main/data/knowledge/us/treasury-20261120-iran-oil-outcast-mail-partial.json)と関連。公表時刻は不明で、残余の翻訳・添付と重複の完全照合は未完。封鎖や輸送に関する政府の主張は独立検証されていない。

【推論】制裁が実際の輸出を減らせば、供給・物価・景気を通じ実質金利、金、通貨に波及し得る。数日では在庫・輸送、数週では輸出・代替供給、数か月では物価・景気への波及を確認する。輸出や決済の継続、代替供給増や需要減は仮説を弱める。ドル円、ユーロドル、ドルスイス、ドルカナダ、豪ドル米ドルは両通貨側の資料不足により判断保留。

[1973〜74年の史料付き初期ケース](https://github.com/samkaz15/invest/blob/main/data/history/us_policy/oil-shock-1973-1974.json)と供給制約の可能性は共通するが、当時の実際の禁輸・減産と現在の未検証の供給影響は異なる。当時公表時点のインフレ、実質金利、流動性、エネルギー構造の比較値は未取得。後年の解説を当時の情報としない。

## 情報源別の確認と欠損

各源の対象期間 2026-11-21T23:24:58+09:00〜2026-11-23T00:52:17+09:00。全件再試行対象。

- [treasury_news](https://home.treasury.gov/news/press-releases)：入口を取得、個別本文・表・PDFの全件照合未完。
- [treasury_auctions](https://www.treasurydirect.gov/auctions/results/)：入口を取得、個別本文・表・PDFの全件照合未完。
- [treasury_buybacks](https://www.treasurydirect.gov/auctions/announcements-data-results/buy-backs/)：動的な個別買戻し結果表の行未確認。
- [fed_fomc](https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm)：入口を取得、個別本文・表・PDFの全件照合未完。
- [nyfed_operations](https://www.newyorkfed.org/markets/desk-operations/treasury-securities)：入口を取得、個別本文・表・PDFの全件照合未完。
- [white_house](https://www.whitehouse.gov/presidential-actions/)：入口を取得、個別本文・表・PDFの全件照合未完。
- [ofac](https://ofac.treasury.gov/recent-actions)：11月20日既存指定ページを再取得、詳細・添付・最新期間の完全照合未完。
- [eia_petroleum](https://www.eia.gov/petroleum/supply/weekly/)：入口を取得、個別本文・表・PDFの全件照合未完。
- [fec_results](https://www.fec.gov/introduction-campaign-finance/election-results-and-voting-information/)：入口を取得、個別本文・表・PDFの全件照合未完。
- [cfius](https://www.cfius.gov/)：入口を取得、個別本文・表・PDFの全件照合未完。

新規知識JSONは保存していない。PDF全文、既存記録の全面照合、期限到来分の事後レビューは未完。PostgreSQL反映は未確認で、[過去の同期失敗](https://github.com/samkaz15/invest/actions/runs/44855507045)と区別する。GitHub保存、DB同期、PC実機通知は別であり、実機通知は未確認。
