# ADR-010: 時系列データの永続化先はマネージドPostgreSQL

- 状態：採択（2026-09-12、オーナー判断）
- 文脈：MIOS転換にあたり `observations`（vintage付き）/ `releases` / `predictions` を
  どこに置くかで Phase 3 以降の設計が分岐する。候補はリポジトリ内ファイル（Parquet/JSONL）、
  マネージドPostgreSQL、リポジトリ内SQLite、およびその併用だった。

## 決定

マネージドPostgreSQL（Supabase / Neon 等、具体的な提供者はオーナーが選定）を単一の
真実の保管庫とする。GitHub Actions は `DATABASE_URL` シークレット経由で接続する。

## 理由

1. 既存の `storage/`（psycopg薄ラッパ）、`db/migrations/` の連番マイグレーション、
   および **append-onlyをDBトリガで物理強制する仕組み** がそのまま活きる。
   ファイル方式に変えると、この強制力をアプリ層で再実装することになり弱くなる。
2. vintage クエリ（`WHERE vintage_at <= :as_of` の DISTINCT ON）はSQLの得意分野であり、
   look-ahead防止の中核をDBの表現力に載せられる。
3. `predictions` の上書き禁止をPK＋トリガで保証できる（指示書 §13）。

## 結果・トレードオフ

- **データが git 履歴の外に出る。** 再現性は git ではなくバックアップで担保する必要があり、
  `ops/backup.sh` 相当の定期ダンプが Phase 10 の必須要件になる。
- 生データ（`data/raw/`）は従来どおりファイルに永久保存し、DB は正規化後の真実とする。
  raw が残る限り DB は再構築可能（憲法第8条3項「データは資産」の運用）。
- 無料枠の容量・接続数制約を Phase 3 で実測し、超える場合は集約方針をADRで追記する。
- 統合テストは CI の PostgreSQL サービスコンテナで実行する（現在skipされている16件を復活させる）。
