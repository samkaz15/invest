# 米国政策調査：差分の部分確認

確認基準：2026年11月23日22:13:05 JST。前回未完分を含む11月21日23:24:58 JSTからの期間を再確認したが、主に入口の確認であり、**網羅的な新着確認は未完**。前回の記録：https://github.com/samkaz15/invest/blob/main/docs/reports/us_policy/20261123T121631Z-recheck.md

## 情報源別の確認と欠損

各行の確認対象期間は上記と同じ。入口からは一覧・案内を取得したが、個別資料・表を取得できなかった部分は再試行対象。

- treasury_news: 一覧表示の最新は11月20日、時刻なし。期間内の個別資料全件・メール照合未完。https://home.treasury.gov/news/press-releases
- treasury_auctions: 入口取得、動的な個別入札結果・表未取得。https://www.treasurydirect.gov/auctions/results/
- treasury_buybacks: 入口取得、個別発表・約定結果表未取得。https://www.treasurydirect.gov/auctions/announcements-data-results/buy-backs/
- fed_fomc: 会合一覧取得、期間内の個別本文の全件照合未完。https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm
- nyfed_operations: 入口取得、個別購入・売却実績の表未取得。https://www.newyorkfed.org/markets/desk-operations/treasury-securities
- white_house: 一覧の最新表示は11月20日、時刻なし。期間内の個別文書の全件照合未完。https://www.whitehouse.gov/presidential-actions/
- ofac: 一覧最新は11月20日、時刻なし。既存の同日資料の全文ハッシュ・メール照合未完。https://ofac.treasury.gov/recent-actions
- eia_petroleum: 一覧の前回号は11月18日。個別表とPDF全頁未照合。https://www.eia.gov/petroleum/supply/weekly/
- fec_results: 入口取得、各州の認証済み結果未取得。https://www.fec.gov/introduction-campaign-finance/election-results-and-voting-information/
- cfius: 入口取得、期間内の個別資料照合未完。https://www.cfius.gov/

11月20日付の[OFAC記録](https://github.com/samkaz15/invest/blob/main/data/knowledge/us/ofac-20261120-iran-cuba-action-public-partial.json)は公表時刻不明のため期間内と断定しない。既存メール経路とのURL・時刻・全文ハッシュの完全照合は未完。今回、新たに完全照合できた個別文書はなく、新着が存在しないことを意味しない。PDF原文、訳文、ページ・図表の照合は未完であり、未取得を翻訳済みと扱わない。

## 条件付き分析

仮に石油供給が減ると、供給制約から物価上昇・実質所得低下を経て、政策金利と資金需給に波及し得る。これは仮説であり、今回の供給減は未検証。日単位は国債入札・買戻しの結果、週単位は供給・在庫、月単位は物価・景気・実質金利を点検する。代替供給や需要減が相殺する場合は仮説が弱まる。金とUSD/JPY、EUR/USD等は必要な双方の資料が不足しており方向の判断を保留する。

[1973〜74年事例](https://github.com/samkaz15/invest/blob/main/data/history/us_policy/oil-shock-1973-1974.json)は後年の公式史料による供給制約の初期要約で、今回の供給減は未検証。当時の公表物価・金利・流動性・エネルギー構造の数値も未取得。[2020年FRB事例](https://github.com/samkaz15/invest/blob/main/data/history/us_policy/fed-response-2020-03-15.json)の当時の声明は流動性支援と政策金利を記録するが、今回のFRB売買実績は未取得。構造の比較は未完。3件は初期要約であり、経済史全体や精度検証済みの予測モデルではない。後年の解説を当時の情報に置き換えない。

## 保存・再試行

各情報源の個別資料、動的表、PDF、既存メールとの照合、期限到来分の事後レビューは再試行する。政府の戦況主張と独立検証、選挙速報と州認証は別に扱う。

GitHubへの記録とPostgreSQL反映・PC通知は別。[US knowledge database sync](https://github.com/samkaz15/invest/actions/runs/45178983790)は11月23日21:56 JST開始の実行が失敗。今回のDB反映とPC通知は未確認。既存の調査、Gmail webhook、朝のまとめを停止・変更しない。
