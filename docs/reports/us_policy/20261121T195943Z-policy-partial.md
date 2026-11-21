# 米国政策調査：部分実行記録

- 実行基準：2026年11月22日 04:59:43 JST
- 照合対象：前回の03:43 JST報告以降から今回基準時点まで。各一覧の公開時刻や網羅性を確認できておらず、以下は新着なしの判定ではない。
- 分析記録：data/analysis/us_policy/20261121T195943Z-policy-partial.json（コミット df2efb87458e5b5f9ed0f12c7328b65744e19021）

## 確認した資料

- **事実**：OFACの[11月20日付資料](https://ofac.treasury.gov/recent-actions/20261120)は、イラン関連指定とキューバ関連FAQ 1277・1278の発出を掲載。公表時刻は不明。既存の部分記録 `ofac-20261120-iran-cuba-action-public-partial` との完全な照合は未了。対象FAQの独立した原文・訳文も未確認。
- **事実**：[EIAの週間輸出入表](https://www.eia.gov/dnav/pet/pet_move_wkly_dc_NUS-Z00_mbblpd_w.htm)では11月13日終了週の米国の原油輸入は日量557.6万バレル。表の公表時刻は不明。これは週次値で、当日の約定や取引量ではない。
- 上記資料の取得基準は2026年11月22日04:59 JST。全文翻訳・表全体の確認は完了していない。新しいknowledgeレコードは作成しておらず、原文と訳文を保存済みとは扱わない。

## 情報源別の範囲と欠損

全情報源について確認対象期間は11月22日03:43〜04:59 JST。取得した一覧や案内だけでは、その期間内の個別資料の網羅確認にはならない。

- [米財務省報道発表](https://home.treasury.gov/news/press-releases)：一覧取得、対象時間帯の全個別本文は未照合。
- [TreasuryDirect入札結果](https://www.treasurydirect.gov/auctions/results/)：一覧取得、個別入札結果・表の網羅確認未了。
- [TreasuryDirect買戻し](https://www.treasurydirect.gov/auctions/announcements-data-results/buy-backs/)：一覧取得、個別発表と実際の買戻し結果の照合未了。
- [FRB FOMC](https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm)：会合一覧取得、対象時間帯の個別本文未照合。
- [NY連銀国債オペ](https://www.newyorkfed.org/markets/desk-operations/treasury-securities)：案内取得、個別オペと約定結果未取得。
- [ホワイトハウス大統領措置](https://www.whitehouse.gov/presidential-actions/)：一覧取得、対象期間の全本文未確認。
- [OFAC制裁](https://ofac.treasury.gov/recent-actions)：一覧と11月20日付個別ページ取得、リンクFAQの独立記録未確認。
- [EIA石油週報](https://www.eia.gov/petroleum/supply/weekly/)：一覧と輸出入表を取得、週報PDFの全ページ未読。
- [FEC選挙](https://www.fec.gov/introduction-campaign-finance/election-results-and-voting-information/)：案内取得、州別認証の確認未了。
- [CFIUS](https://www.cfius.gov/)：案内取得、全個別措置未確認。

## 条件付きの経済経路

**推論**：制裁が実際に石油の供給・輸送を制約する場合、供給減はエネルギー価格と物価を押し上げ、景気と金融政策を通じて金利や資金需給に影響し得る。代替供給の増加や需要減で影響が相殺される場合は、この経路が弱まる。今回の資料だけでは実際の供給への影響を確認できない。

日・週・月の具体的シナリオ、金への影響、通貨ペア別の方向は相手国を含む資料が不足するため判断保留。市場の名目金利と実質金利を同一視しない。政府の主張は独立検証された戦況ではない。選挙速報は州の認証ではない。

## 比較・レビューと再試行

史料付きの過去事例について、当時のインフレ・金利・流動性・エネルギー構造の照合と、期限到来分の事後レビューは未了。全経済史を学習済み、または予測精度を検証済みとは扱わない。再検討目安：2026年11月23日04:59 JST。

再試行対象：各情報源の個別本文と表、国債入札・財務省買戻し・NY連銀オペの実績、EIA週報PDF全ページ、OFAC FAQ、州別選挙認証、既存メール経路とのURL・公表時刻・内容ハッシュ照合、履歴比較、ADR-016/017形式での原文と日本語訳の保存。未取得は翻訳済みにしない。

GitHub保存とDB反映は別工程。以前の[US knowledge database sync実行](https://github.com/samkaz15/invest/actions/runs/44855507045)は失敗しており、今回のPostgreSQL反映状況は未確認。PC通知は実機未確認。個別のChatGPT通知やメール送信は行っていない。
