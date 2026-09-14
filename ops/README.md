# ops/

運用スクリプト。

- `backup.sh` — マネージドPostgreSQL のダンプと `data/` の退避（ADR-010）

日次の自動実行は cron ではなく **GitHub Actions** で行う（Phase 10）。
個人マシンの crontab に依存していた BIOS 期の設定は `archive/ops/crontab.txt` に保存されている。

## バックアップの位置づけ

ADR-010 でデータベースを git の外に置いた以上、**再現性は git ではなくバックアップで担保する**。

- `data/raw/` と `reports/` は git にコミットされるため、git 履歴がバックアップになる
- **`observations` / `releases` / `predictions` を含む DB は git の外にある** —
  ここが失われると、過去の予測vintageが永久に失われる
- 四半期に一度、**復元訓練**を行う（ダンプから空のDBを復元し、`mios health` が通ることを確認する）
