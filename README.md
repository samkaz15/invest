# BIOS — Bitcoin Intelligence Operating System

事実を構造化し、因果と統計で確率を推定する**分析OS**。価格予想AIではない。

## ドキュメント（Single Source of Truth）

| 文書 | 役割 |
|---|---|
| [PROJECT_CONSTITUTION.md](docs/PROJECT_CONSTITUTION.md) | 憲法（最上位。全設計・実装はこれに従属） |
| [MASTER_SYSTEM_DESIGN.md](docs/MASTER_SYSTEM_DESIGN.md) | システム構造・データモデル・Agent仕様 |
| [INTELLIGENCE_ENGINE_SPECIFICATION.md](docs/INTELLIGENCE_ENGINE_SPECIFICATION.md) | 分析・スコアリング・レポート・検証 |
| [DATA_SOURCE_REGISTRY.md](docs/DATA_SOURCE_REGISTRY.md) | データソース台帳・信頼Tier |
| docs/sprints/ | Sprint毎の実装報告（設計との差分・判断理由） |

設計と実装が矛盾した場合は**設計が正**。実装側の都合で設計を変えない（変更はADR＋オーナー承認）。

## セットアップ

```bash
make install   # Python 3.12+ 必須（.venv を作成）
cp .env.example .env
make check     # lint + typecheck + test（コミット前の必須ゲート）
```

## リポジトリ構成

MASTER_SYSTEM_DESIGN.md §2 を参照。要点：

- `src/bios/` — アプリ本体（層＝サブパッケージ、import は上流→下流の一方向）
- `config/` — 全設定（タクソノミ・Agent・重み。コード変更なしで挙動を変える層）
- `prompts/` — Agentプロンプト（Git履歴＝バージョン管理）
- `seeds/` — 歴史イベント初期データ
- `db/migrations/` — スキーママイグレーション（後方互換必須）
- `var/` — 実行時状態（git管理外。監査ログ等）
