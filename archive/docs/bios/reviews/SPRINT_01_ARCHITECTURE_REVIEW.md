# Sprint 1 最終アーキテクチャレビュー

日付：2026-07-14 ／ レビュー観点：Software Architect / Data Platform Engineer / Quant Infrastructure Engineer
対象：コミット `3bda359`（Sprint 1: Project Foundation）

## 判定：**Go with Minor Changes**（変更は本レビューで即時適用済み）

理由：憲法・MSD・IESとの構造的整合は取れており、レイヤ骨格・追記のみ規律・設定駆動はすべて設計どおり。ただし**ID体系の設計不整合（F1）**が発見され、これはSprint 2（Source Registry）が最初の利用者になるため、着手前の修正が必須。その他は軽微。全指摘の修正を適用した上でSprint 2へ進む。

---

## 1. Architecture Review

| 観点 | 評価 | 所見 |
|---|---|---|
| 憲法との整合 | ✅ | 追記のみ（BiosRecord凍結）・証拠ラベル語彙・依存最小（実行依存3個）・モデルIDの設定外出し、すべて遵守 |
| MSDとの整合 | ⚠→✅ | ディレクトリ＝§2.2に一致。監査レコード＝§15.6に一致。**F1（ID体系）のみ不整合**→修正済み |
| IESとの整合 | ✅ | Dimension語彙・スコア設定（w_v1・anomaly cap）はIES §11に一致 |
| 将来拡張性 | ✅ | タクソノミYAML追記・アセット追加=ファイル追加。Asset非依存（P9）維持 |
| Market Intelligence Platformへの発展性 | ✅ | 語彙・スキーマにBTC固有の前提なし。asset_class次元あり |
| Event Driven Architectureとして | ✅（設計意図どおり） | **データはイベントソーシング**（append-only Event Store が真実源）だが、**実行系は意図的にバッチDAG**（ADR-004：一人運用にイベントバスは過剰）。「EDAでない」のではなく「EDAのデータ面のみ採用」が設計判断。矛盾なし |

## 2. Repository Review

- 責務分離：層=パッケージ、import方向は一方向 — ただし**規約のみで機械的強制がなかった**（F5）→ アーキテクチャテストを追加済み。
- 命名：`bios.common.logging` が標準ライブラリ`logging`と同名で読み手を混乱させる（F2）→ `logutil.py` へ改名済み。
- その他の構成・命名は良好。5年保守の観点で問題なし。

## 3. Foundation Review

| 項目 | 評価 | 所見 |
|---|---|---|
| Configuration | ✅ | 型付き・未知キー拒否・実configの回帰テストつき。Settings（環境）とYAML（知識）の分離が明確 |
| Logging | ✅ | stdlib+JSON。運用ログと監査ログの分離が明示されている |
| Error Handling | ✅ | 例外階層あり。監査書込失敗は握り潰し禁止（AuditWriteError）が明文化 |
| Dependency Injection | ✅ | コンストラクタ注入＋Protocol（AuditSink）。DIフレームワーク不使用は正しい判断。**composition rootが未出現**だが、初のエントリポイントはSprint 2（CLI）で導入予定 — 妥当 |
| Common Library | ⚠→✅ | F1（ID）修正済み。UTC規律はlint（DTZ）とランタイム二重防御で優秀 |
| Security | ✅ | .env外出し・yaml.safe_load・秘密のログ出力なし。現段階の攻撃面は最小 |
| Monitoring | ➖ | 未実装（Sprint 2スコープ。設計どおり） |

## 4. Code Quality

- SOLID/Clean Architecture：単一責務・依存逆転（Protocol）・境界明確。指摘なし。
- 型安全：mypy strict 全通過。`log_action(**detail)` は将来の名前衝突リスク（F3）→ 明示的 `detail: dict` 引数へ変更済み。
- 重複・負債：現時点でゼロに近い。`BiosRecord`の浅い凍結（detail dictの中身は可変）は既知の限界として記録（Sprint 3のDBシンクで実質解消）。

## 5. Risk Assessment

| 優先度 | リスク | 対応 |
|---|---|---|
| **Critical** | なし | — |
| **High** | F1: ID体系の設計不整合。設計はEntity/Source/Chain/Pattern等に**人間可読ID**（`ent_mtgox`, `src_sec_press`, `chain_mtgox`）、Scenario/Decision/ScoreCardに**日付ID**（`scn_2026-07-14_btc`）を規定するが、実装は全種別opaque hexを強制。放置するとSprint 2のSource Registry・Sprint 3のEntityマスタが設計と乖離したIDで永続化され、後から直せない | **修正済み**：IdKindを3家系に分類（opaque=raw/evd/run、slug=src/ent/chain/pat/ovh/anm、dated=evt/scn/dcs/sc）。生成・検証を家系別に実装、テスト更新 |
| Medium | F2: `common/logging.py` のstdlib同名モジュール | 修正済み：`logutil.py`へ改名 |
| Medium | F3: `log_action(**detail)` のキーワード衝突（`actor`等を詳細に入れられない） | 修正済み：`detail: dict \| None` 引数化 |
| Medium | F5: import方向が規約頼み | 修正済み：ASTベースの層依存テスト（`test_architecture.py`）を追加。違反はCIで落ちる |
| Low | F4: `make_event_id` が実在しない日付（2024-13-45）を通す | 修正済み：`date.fromisoformat`検証 |
| Low | F6: scoring.yamlの次元名タイポが実行時まで発覚しない | 修正済み：`Dimension` enum（IES §1.3の7次元）を語彙に追加し、weight_setsのキーを検証 |
| Low | JSONL監査シンクがflushのみ（fsyncなし）でクラッシュ時に直近数行を失い得る | 許容（Phase 1）。Sprint 3のDBシンクで解消。runbookに記載予定 |
| Low | opaque ID正規表現（17hex固定）が形式変更に対する互換契約になる | 意図的に固定（永続IDの検証は永久互換が必要）。変更時はADR |

## 6. Refactoring Proposal → 全件適用済み

上表F1-F6。いずれも影響範囲は`bios.common`/`bios.audit`とテストのみで、外部利用者ゼロの今が最後の安価な修正機会だった。

## 7. Sprint Readiness

**Go with Minor Changes** — F1-F6を本コミットで適用済み。ゲート（ruff/mypy strict/pytest）全通過を確認の上、Sprint 2へ進む。
