# ADR-016: 米国公式メールの知見保存と日本語通知
採択: 2026-11-01、オーナーの明示依頼。ADR-015の「ニュース対象外」を米国公式メールに限り変更する。数値予測の入力は変更しない。READMEの数値限定は予測パイプラインに適用する。

## 運用
ChatGPTのGmailイベントで subscriptions@subscriptions.treas.gov の新着本文を取得する。
米国関連の実質的な情報を data/knowledge/us/ に1文書1JSONで保存する。
金・関税・原油・国債（実質金利、入札、発行、関連する制裁を含む）のメールは、対象部分を省略せず日本語訳してChatGPTで通知する。関連性は本文で判定し、件名だけで除外しない。
登録確認・広告・解除案内は市場情報として保存・通知しない。

## レコード契約
ファイル名は公開一次資料から作った安定IDとする。メールアドレス、Gmail ID、個人化URL、解除トークン、配送ヘッダはコミットしない。
必須キー:
id, source_url, title_en, title_ja, published_at, received_at, topics,
original_text, translation_ja, facts_ja, inference_ja。
日時はタイムゾーン付きISO8601。発表時刻不明なら published_at=null とし受信時刻で代用しない。
topics は米国関連分類の配列（gold, tariffs, oil, treasuries, monetary_policy, sanctions, other_us等）。
原文にない数字を追加しない。事実と推論を分離する。公式文書が確認できない場合はその旨を facts_ja に記す。
同一文書の訂正版は新IDで保存し supersedes に旧IDを記す。過去文書を上書きしない。

## DBへの反映
ops/import_us_knowledge.py がJSONを既存PostgreSQLの us_knowledge_documents に取り込む。
新ワークフローは毎時と手動、JSON変更時に実行する。MIOS_DATABASE_URL が必須。
GitHubへの保存成功とDBへの反映成功を区別する。接続不能なら失敗として報告する。
DB反映は保存済みJSONから再実行可能。内容変更による同一IDの上書きは拒否する。
Gmail接続はChatGPT側を利用し、OAuth情報をGitHubへ移さない。
