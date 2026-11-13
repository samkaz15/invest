# 財務省メール2件の保存・同期結果

米国2026年11月13日付の制裁発表とSDN更新通知を、実質本文の原文・日本語訳とともにGitHubのmainに保存し、コミットから4ファイルを読み戻して一致を確認した。受信は日本時間11月14日02:03:08と02:04:49。初回公表時刻は不明。制裁は麻薬密売・テロ支援に関する措置で、燃料窃盗は既往の背景説明。金、関税、原油供給、米国債への関連は確認できなかった。

- [財務省発表の日本語訳](https://github.com/samkaz15/invest/blob/f3ea4fab599b9e56586e28b937a810ff554287bb/docs/translations/us/treasury-20261113-guatemala-sanctions-mail-7387f8cc.ja.md)
- [OFAC更新通知の日本語訳](https://github.com/samkaz15/invest/blob/f3ea4fab599b9e56586e28b937a810ff554287bb/docs/translations/us/ofac-20261113-sdn-update-mail-2c0f62cb.ja.md)

公開配信版2件と[OFAC個別告示](https://ofac.treasury.gov/recent-actions/20261113)は取得できなかった。個別告示の本文・表・脚注・付属PDFは未確認。受信メールのMIMEにはPDF添付なし。個別告示取得後、メールとは別文書として照合・保存を再試行する。

[US knowledge database sync](https://github.com/samkaz15/invest/actions/runs/43469783097)はDB接続時に接続先のテナントまたはユーザーが見つからず失敗した。PostgreSQL反映は未確認。接続設定復旧後に保存済みJSONから再試行する。

[日本語成果物の自動処理](https://github.com/samkaz15/invest/actions/runs/43469782870)は既存のBLS翻訳ファイルの不変性チェックで停止した。今回の2件は個別に検証し、保存済み日本語訳を読み戻した。Mac実機での表示は未確認。
