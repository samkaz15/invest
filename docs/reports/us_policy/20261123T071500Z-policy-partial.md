# 米国政策調査：部分確認・再試行待ち

取得基準時刻: 2026-11-23T16:15:00+09:00。確認対象: 2026-11-21 23:24:58 JST〜2026-11-23 16:15 JST（前回の未完範囲を維持）。各情報源の入口を確認したが、期間全体の個別本文・表は網羅できていない。取得不全は新着なしを意味しない。

- treasury_news: 一覧取得。対象期間の個別本文・公表時刻の網羅照合未完（https://home.treasury.gov/news/press-releases）
- treasury_auctions: 一覧取得。個別入札結果表の対象期間網羅確認未完（https://www.treasurydirect.gov/auctions/results/）
- treasury_buybacks: 一覧取得。個別買戻し表の対象期間網羅確認未完（https://www.treasurydirect.gov/auctions/announcements-data-results/buy-backs/）
- fed_fomc: 会合一覧取得。対象期間の声明等の個別本文確認未完（https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm）
- nyfed_operations: 入口取得。個別の実施結果と予定表の確認未完（https://www.newyorkfed.org/markets/desk-operations/treasury-securities）
- white_house: 入口取得。対象期間の各文書と時刻の照合未完（https://www.whitehouse.gov/presidential-actions/）
- ofac: 一覧が No results found を返却。既存既知文書と整合せず取得不全として再試行（https://ofac.treasury.gov/recent-actions）
- eia_petroleum: 入口取得、11月18日号が表示。各表・PDF全頁の対象期間照合未完（https://www.eia.gov/petroleum/supply/weekly/）
- fec_results: 入口取得。州の認証・公表時刻は未確認（https://www.fec.gov/introduction-campaign-finance/election-results-and-voting-information/）
- cfius: 入口取得。個別発表確認未完（https://www.cfius.gov/）

## 資料・重複
今回、新たに本文・翻訳を完備した一次資料は保存していない。前回記録と財務省メール経路に対する公開URL・公表時刻・内容ハッシュの完全照合は未完。未取得のPDF、表と翻訳は未取得のまま。情報源ごとの個別文書の公表時刻・未読箇所の特定も未完。選挙速報と州認証、政府の戦況主張と独立検証は区別し、未確認情報を確定扱いしない。

## 条件付き経路と限界
仮に原油供給制約が持続すれば、エネルギー価格から物価・実質所得を通じて金利と資金需給へ影響し得る。需要の減少や代替供給拡大は反証条件。日・週・月の具体的な条件分岐は資料不足で保留。USD/JPY、EUR/USD、USD/CHF、USD/CAD、AUD/USD は相手通貨側資料が不足するため方向判断保留。金への影響も実質金利等の資料不足で保留。これは一般的な因果仮説であり、今回の供給途絶を確認したものではない。

既存の歴史3事例は初期要約であり、当時のインフレ・金利・流動性・エネルギー構造と現在値の一次資料が揃っていないため厳密な比較は保留。review_after 到来分の完了確認も未完。

## 保存と再試行
GitHubへの本報告の保存とPostgreSQL反映は別。直近50件の実行履歴で確認できた最新の [US knowledge database sync](https://github.com/samkaz15/invest/actions/runs/45102464945) は2026-11-23 11:50:23 JST開始、失敗。今回のDB反映は未確認。PC通知も未確認。10情報源の各本文・表、OFAC一覧、PDF、メール重複、履歴レビュー、DB反映を次回再試行する。既存の定期タスク・Gmail webhookは変更しない。
