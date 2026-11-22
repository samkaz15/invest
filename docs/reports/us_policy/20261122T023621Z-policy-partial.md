# 米国政策調査（2026年11月22日11:36 JST）

前回09:38 JST以降の差分に、その前24時間を重ねた11月21日09:38〜11月22日11:36 JSTを暫定対象とした。各情報源の最新保存公表時刻、個別文書と表の網羅照合は未完であり、新着なしとは断定しない。

【事実】[EIAの週間輸出入表](https://www.eia.gov/dnav/pet/pet_move_wkly_dc_NUS-Z00_mbblpd_w.htm)を11:36 JSTに再取得。11月13日終了週の米原油輸入は日量557万6000バレル、前週は669万8000バレル。対象週は公表日時ではなく、実際の公表時刻は不明。[既存の週間要約・日本語訳](https://github.com/samkaz15/invest/blob/main/data/knowledge/us/eia-20261113-weekly-petroleum-summary.json)と同じ週の情報として扱い、重複ニュースにしない。上記表の全列・脚注とリンク先は未取得。

[OFAC FAQ 1277](https://ofac.treasury.gov/faqs/1277)も再取得し、分野指定だけで全事業者が自動制裁されないという説明を確認。[既存訳](https://github.com/samkaz15/invest/blob/main/docs/translations/us/ofac-20261120-cuba-faq-1277.ja.md)と同一URLのため再保存しない。公表時刻不明。

【情報源別】各入口を取得。暫定対象期間は上記と同じ。入口の取得は全個別資料の確認ではない。
- [treasury_news](https://home.treasury.gov/news/press-releases)：入口取得、個別本文・表の完全照合未完。
- [treasury_auctions](https://www.treasurydirect.gov/auctions/results/)：入口取得、個別本文・表の完全照合未完。
- [treasury_buybacks](https://www.treasurydirect.gov/auctions/announcements-data-results/buy-backs/)：入口取得、個別本文・表の完全照合未完。
- [fed_fomc](https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm)：入口取得、個別本文・表の完全照合未完。
- [nyfed_operations](https://www.newyorkfed.org/markets/desk-operations/treasury-securities)：入口取得、個別本文・表の完全照合未完。
- [white_house](https://www.whitehouse.gov/presidential-actions/)：入口取得、個別本文・表の完全照合未完。
- [ofac](https://ofac.treasury.gov/recent-actions)：入口取得、個別本文・表の完全照合未完。
- [eia_petroleum](https://www.eia.gov/petroleum/supply/weekly/)：入口取得、個別本文・表の完全照合未完。
- [fec_results](https://www.fec.gov/introduction-campaign-finance/election-results-and-voting-information/)：入口取得、個別本文・表の完全照合未完。
- [cfius](https://www.cfius.gov/)：入口取得、個別本文・表の完全照合未完。

財務省買戻しの別URLは取得失敗。入札・買戻し・NY連銀の個別取引結果、EIA週報の全PDFと脚注、原本PDFの安全確認、州選挙認証、既存メール経路を含むURL・時刻・ハッシュ照合、期限到来分レビューは未完。政府発表の内容と独立検証された戦況、選挙速報と州認証は区別する。

【推論】輸入減が持続的な供給減を意味し他条件が一定なら原油需給を引き締め、エネルギー物価・景気・金利に波及し得る。一方、国内生産や代替供給、在庫の増加、需要減が相殺すれば仮説は弱まる。日次は輸送障害、週次は輸入・在庫・生産、月次は物価と政策反応を確認。日米等の双方の資料不足によりUSD/JPYなど通貨ペアと金の方向は判断保留。

1973年の供給制約事例との比較には当初の物価・金利・流動性・エネルギー構造の照合が必要で、今回未完。3例は初期要約で予測精度未検証。

分析と報告をGitHubに保存。[過去のDB同期](https://github.com/samkaz15/invest/actions/runs/44855507045)は失敗しており、今回のPostgreSQL反映は未確認。PC通知は実機未確認。
