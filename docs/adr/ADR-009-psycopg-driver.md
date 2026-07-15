# ADR-009: PostgreSQLドライバとして psycopg3 を採用（ORM不採用）

日付: 2026-07-14 ／ 状態: 採用 ／ 関連: ADR-002（単一PostgreSQL）

## 決定

`psycopg[binary]>=3.2` を実行依存に追加する（Sprint 3）。SQLAlchemy等のORMは採用しない。

## 理由

- スキーマはSQLマイグレーションが正（append-onlyトリガ・CHECK制約をDB側に置く設計のため、ORMのスキーマ管理と二重管理になる）
- クエリ数は少なく型はPydanticが担う。ORMの抽象は一人運用5年での学習・追跡コストに見合わない
- psycopg3は型注釈完備・標準的・保守が活発

## 却下した代替案

- SQLAlchemy: 上記の二重管理。asyncpg: 非同期は本システムの負荷に不要（憲法第8条）
