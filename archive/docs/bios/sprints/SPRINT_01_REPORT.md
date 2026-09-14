# Sprint 1 Report — Project Foundation

日付：2026-07-14 ／ 対象設計書：MASTER_SYSTEM_DESIGN.md（MSD）§1-2, §15.6, §17-18

## 1. 実装内容

| Sprint 1 スコープ | 実装 |
|---|---|
| Repository整理 | MSD §2.2 のディレクトリ骨格を全作成（src/bios/ 13層パッケージ・config/・prompts/・seeds/・db/migrations/・ops/・tests/{unit,integration,golden}） |
| 開発基盤 | pyproject.toml（Python 3.12+・依存3個のみ）・Makefile（install/lint/fmt/typecheck/test/check）・ruff（DTZ=naive datetime禁止を含む）・mypy strict |
| 設定管理 | `bios.config`：型付きYAMLローダ（未知キー拒否＝タイポで即失敗）＋ `Settings`（.env）。実設定として taxonomy 3ファイル（イベント58種/Entity 23種/関係3クラス）・agents.yaml・scoring.yaml（w_v1）・assets/btc.yaml を設計書から展開 |
| CI | GitHub Actions：ruff check + format --check + mypy + pytest（coverage付き） |
| 共通ライブラリ | `bios.common`：ID規約（IdKind 13種・人間可読evt ID・検証）／時刻規律（UTC強制・naive拒否・TimePrecision）／語彙enum（ClaimLabel・SourceTier・Action等）／スキーマ基底（BiosModel=可変・BiosRecord=不変）／例外階層／構造化ログ（stdlib＋JSONフォーマッタ） |
| 監査ログ | `bios.audit`：AuditRecord（誰が何をしたか）＋AgentRunRecord（MSD §15.6 準拠：prompt_version/model/tokens/cost/status）。AuditSinkプロトコル＋JSONLシンク（追記のみ） |

## 2. 変更ファイル一覧

- 基盤：`pyproject.toml` `Makefile` `.github/workflows/ci.yml` `.gitignore` `.env.example` `README.md`
- 設定：`config/taxonomy/{events,entities,relationships}.yaml` `config/agents.yaml` `config/scoring.yaml` `config/assets/btc.yaml` `config/sources/README.md`
- コード：`src/bios/common/{ids,timeutil,labels,schema,errors,logging}.py` `src/bios/config/{settings,models,loader}.py` `src/bios/audit/{records,logger}.py` ＋13層の `__init__.py`
- テスト：`tests/unit/test_{ids,timeutil,schema,config,audit,logging}.py`（25件）
- 置き場：`prompts/` `seeds/` `db/migrations/` `ops/` の README

## 3. テスト結果

```
ruff check / format --check : PASS（36ファイル）
mypy --strict               : PASS（28ソースファイル・エラー0）
pytest                      : 25 passed
```

テストの要点：実際にコミットされた `config/` ツリーが常にロード可能なことを検証する回帰テストを含む（タクソノミへの「YAML1行追加」が壊れていればCIが落ちる）。監査ログはappend-only・不変・naive時刻拒否を検証。

## 4. 設計との差分と判断理由

| # | 差分 | 判断理由 | 設計変更要否 |
|---|---|---|---|
| D1 | opaque ID を `prefix_<millis-hex><random>`（17hex）に統一。設計書の例（`evd_00123`）は連番風だった | 連番はDB採番依存で分散生成できない。時刻接頭辞により辞書順≈生成順（追記テーブル・ログと相性が良い）。人間可読の `evt_<date>_<slug>` は設計通り | 不要（設計書の例示は非規範と解釈） |
| D2 | 監査ログはJSONLファイルシンクで開始。設計はDBテーブル（MSD §15.6） | DBはSprint 3スコープ。`AuditSink` プロトコル背後に隠したため、Sprint 3でDBシンクに差替えても呼出側は無変更 | 不要（実装順序の問題） |
| D3 | `config/pipelines.yaml` は未作成 | スケジューラ（Sprint 2）実装と同時でないとスキーマが投機的になる。Sprint 2冒頭で作成 | 不要（先送りを明記） |
| D4 | Python 3.12 をbrewで導入（マシンには3.9/3.11しかなかった） | ADR-001（3.12+）遵守 | 不要 |
| D5 | `agents.yaml` のモデルIDは現行Claudeラインナップの仮値 | モデルIDは設定ファイル管理（憲法第8条5項）なので、実運用開始時に無コード変更で差替え可能 | 不要 |

## 5. 注意点・今後の改善点

- `BiosRecord`（frozen）は浅い不変。`detail: dict` の中身までは凍結されない — DBシンク導入時（Sprint 3）に書込後の再利用をしない規約で運用し、必要ならdeep-freezeを検討。
- JSONL監査シンクは単一プロセス前提（現Phaseは単一プロセス設計なので問題なし）。並行書込が必要になったらDBシンクへ。
- ruffの `DTZ` ルールで naive datetime をlint段階でも禁止済みだが、境界（外部データのパース）では必ず `parse_utc`/`ensure_utc` を通す規約とする。

## 6. リスク

| リスク | 影響 | 手当 |
|---|---|---|
| pydantic v2 のメジャー更新 | スキーマ基底に波及 | 依存を `>=2.7` に固定域指定。ゴールデンテスト（Sprint 4〜）で回帰検知 |
| タクソノミ初期版の粒度ミス | 後のイベント分類やり直し | 追加は自由（YAML1行）・削除/改名はADR必須のルールで前方修正可能 |
| CI用GitHub Actionsの無料枠 | 課金 | 現状のジョブは数分以内。問題化したらpushトリガのみに限定 |

## 7. 次Sprintの計画（Sprint 2 : Data Collection Layer — 承認後に着手）

1. `config/pipelines.yaml` スキーマ＋ジョブ定義（D3の解消）
2. `SourceAdapter` インターフェース＋ `RawItem` スキーマ（ハッシュ重複排除・無加工保存）
3. Raw Store（ファイルベースで開始、Sprint 3でDB統合）
4. Scheduler：ジョブ実行・指数バックオフつきリトライ・サーキットブレーカ・デッドレターキュー（MSD §15.4）
5. Rate Limit（ソース毎の呼出間隔制御）
6. 最初の実アダプタ1-2本（低リスクな公開RSS/公開API）で端到端の収集を実証
7. 全ジョブ実行を `agent_runs` 監査ストリームに記録（Sprint 1の監査基盤に接続）
