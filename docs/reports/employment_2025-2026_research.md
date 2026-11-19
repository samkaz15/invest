# 米雇用統計：直近1年間の初回発表と市場予想

調査時点：2026年11月6日19:45 JST。対象は2025年11月6日〜2026年11月6日19:45 JSTに発表された資料。2026年11月6日22:30 JSTの発表は未反映。

NFPは初回公表値、予想はReuters調査の事後記事に記載された値。単位は千人。記事は発表後に確認したため、事前時点で取得済みだった証拠ではない。報道機関間で予想値が異なる場合がある。

| 発表日（米国） | 対象月 | NFP初回 | Reuters予想 | 差 | 失業率初回 |
|---|---|---:|---:|---:|---:|
| 2025-11-20 | 2025-09 | +119 | +50 | +69 | 4.4% |
| 2025-12-16 | 2025-11 | +64 | +50 | +14 | 4.6% |
| 2026-01-09 | 2025-12 | +50 | +60 | -10 | 4.4% |
| 2026-02-11 | 2026-01 | +130 | +70 | +60 | 4.3% |
| 2026-03-06 | 2026-02 | -92 | +59 | -151 | 4.4% |
| 2026-04-03 | 2026-03 | +178 | +60 | +118 | 4.3% |
| 2026-05-08 | 2026-04 | +115 | +62 | +53 | 4.3% |
| 2026-06-05 | 2026-05 | +172 | +85 | +87 | 4.3% |
| 2026-07-02 | 2026-06 | +57 | +110 | -53 | 4.2% |
| 2026-08-07 | 2026-07 | -23 | +80 | -103 | 4.1% |
| 2026-09-04 | 2026-08 | +162 | +56 | +106 | 4.1% |
| 2026-10-02 | 2026-09 | +29 | +90 | -61 | 4.2% |

発表済み12回中、NFPはReuters予想を7回上回り、5回下回った。ただし相場の方向予測や的中率を示す数字ではない。

2025年10月分は政府機関閉鎖により独立した雇用統計発表がなく、家計調査は実施されなかった。11月分発表で10月の事業所調査データが一部示されたが、10月失業率は未取得でありゼロや前月値で代用しない。[BLSアーカイブ](https://www.bls.gov/bls/news-release/empsit.htm)。

## 市場反応の例：報道による事後観察

- 2025-12-16発表：NFPは6.4万人、予想5万人と上振れた一方、失業率は4.6%。Reutersは発表後の金上昇とドル指数低下を報道。雇用者数だけでは説明が足りない例。[Reuters配信](https://www.kitco.com/news/off-the-wire/2025-12-16/gold-inches-us-unemployment-rate-rises-november)
- 2026-05-08発表：NFPは11.5万人、予想6.2万人と上振れ。Reutersは金の上昇と米金利・ドル指数の低下を報道し、他の市場環境も挙げた。[Reuters配信](https://uk.marketscreener.com/news/gold-on-track-for-weekly-gain-markets-focus-on-us-iran-peace-deal-prospects-ce7f5bdade89f021) [市場概況](https://www.investing.com/news/economy-news/april-jobs-report-shows-continued-strength-4672795)

- 2026-09-04発表：NFPは16.2万人、予想5.6万人。Reutersは発表後の金下落とドル・米金利上昇を報道。ただし発表後5分や30分の騰落率を確認したものではない。[Reuters配信](https://www.kitco.com/news/off-the-wire/2026-09-04/gold-slides-after-robust-us-payrolls-boosts-rate-hike-bets)
- 2026-10-02発表：NFPは2.9万人、予想9万人。Reutersは金が一時上昇後に反落したと報道。[Reuters](https://www.reuters.com/world/india/gold-slips-before-us-payrolls-data-set-second-weekly-loss-2026-10-02/)
- 2026-03-06発表：NFPはマイナス9.2万人、予想プラス5.9万人。Reuters報道では、ドル円は発表直前157.905から早朝取引時157.85だったが、厳密な5分・30分値ではない。[Reuters配信](https://www.lse.co.uk/news/us-dollar-holds-gains-after-unexpected-drop-in-february-payrolls-khc00ykltc1a9q5.html)

## TradingViewの確認

TVC:GOLDの画面で2026-10-02を選択。30分足では当日を表示できたが、5分足ではBasicプランの最大5,000本制限が表示され、同日まで到達できなかった。ドル円を含む12回×2資産の5分・30分・1時間・24時間の厳密な価格観測は未取得。報道による方向とチャート上の正確な時間別変化は区別する。

実行例（DB不要）:

```sh
python ops/employment_research.py --releases data/research/employment/bls_releases_2025-11_2026-10.json --as-of 2026-11-06T20:00:00+09:00 --output /tmp/employment-study.json
```

任意の5分足CSVは `--prices` で指定する。列は `symbol,instrument_id,bar_start,open,close,source_url,retrieved_at`。発表時刻の足の始値から、各時間の足の終値まで比較する。厳密な足がない場合やデータ取得時刻がas_ofより後の場合はnull。発表直前の最終約定価格ではない点にも注意。入力データの利用権は別途確認する。

詳細な発表元・記事URLと時刻は同ディレクトリのJSONを参照。これは調査データであり、将来のイベントの予測やバックテストの実施を意味しない。
