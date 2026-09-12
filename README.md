# MIOS — Macro Intelligence Operating System

毎日、世界のマクロ経済状態をスナップショットとして保存し、
**次回の CPI / NFP などの重要経済指標が上振れするか下振れするか**を判断し、
その判断が当たっていたのかを**半年後に統計的に検証できる**リサーチ基盤。

対象マーケットは **Gold（XAUUSD）** と **USDJPY**。

価格予想AIではない。ニュース要約AIでもない。

## 成功の定義

> 半年後に「このシステムは CPI / NFP 予測に本当に役立っているのか？」を
> 統計的に検証できる状態にあること。

機能が増えることを成功と呼ばない。優先順位は常に：

```
Data Quality > Reproducibility > Validation > Simplicity > Feature Count
```

## ドキュメント

| 文書 | 役割 |
|---|---|
| [CONSTITUTION.md](docs/CONSTITUTION.md) | 憲法（最上位。全設計・実装はこれに従属） |
| [ARCHITECTURE.md](docs/ARCHITECTURE.md) | 層構造・データフロー・中核規律・未解決事項 |
| [REPOSITORY_AUDIT.md](docs/REPOSITORY_AUDIT.md) | BIOS からの転換にあたっての全ファイル監査と移行計画 |
| [DELETION_LOG.md](docs/DELETION_LOG.md) | 何を・なぜ削除したか・どう復元するか |
| [DATA_SOURCE_REGISTRY.md](docs/DATA_SOURCE_REGISTRY.md) | データソース台帳と信頼Tier |
| [EVALUATION.md](docs/EVALUATION.md) | 予測精度の測り方（MAE / RMSE / 方向 / キャリブレーション） |
| docs/adr/ | 技術判断の記録 |

設計と実装が矛盾した場合は**設計が正**。実装側の都合で設計を変えない（変更は ADR）。

前身の Bitcoin Intelligence OS（BIOS）の設計文書と歴史データは `archive/` に保存されている。

## セットアップ

```bash
make install          # Python 3.12+ 必須（.venv を作成）
cp .env.example .env  # API キーと DATABASE_URL を記入
make check            # lint + typecheck + test（コミット前の必須ゲート）
```

## 実行

```bash
mios migrate       # マイグレーション適用 + ソース台帳・系列台帳の同期
mios sources       # 設定済みソース一覧
mios series        # 系列台帳と各系列の蓄積状況（未取得の系列は欠損として表示）
mios collect       # 有効な全ソースを収集
mios run-due       # 実行期限が来たジョブだけ実行
mios normalize     # 生データ → vintage付き観測値
mios observations ser_us_cpi_index --as-of 2026-09-01T00:00:00Z
mios revisions ser_us_cpi_index 2026-08-01
mios forecast      # 予測を実行し、その日の vintage を保存（上書きしない）
mios forecasts ser_us_core_cpi_index 2026-09-01   # ある期間への予測の全履歴
mios validate      # 発表済みの対象期間について予測を採点
mios analyze       # マクロ8次元スコア + Gold / USDJPY のマクロバイアス
mios accuracy      # MAE / 対ナイーブ skill / 方向的中 / キャリブレーション
mios report        # reports/daily/YYYY-MM-DD.md を生成

mios daily         # 上記を migrate から report まで一気通貫で実行
                   # （プロバイダが1つ落ちてもレポートは出る。終了コードには反映される）

make daily-report  # `mios daily` を呼ぶだけ。workflow と定義を共有する
mios extract       # 未処理ニュースを候補キューへ
mios health        # ソース別の死活（失敗があれば exit 1）
```

**コマンドは、その裏のコードが存在するときにだけ追加する。**
予測・分析・レポートのコマンドは、それぞれの層とともに Phase 5〜9 で現れる。

## 現在地

転換は10フェーズで進む（[REPOSITORY_AUDIT.md §17](docs/REPOSITORY_AUDIT.md)）。

| Phase | 内容 | 状態 |
|---|---|---|
| 1 | Repository audit | ✅ 完了 |
| 2 | Architecture cleanup（Bitcoin固有部分の削除、`bios`→`mios`、CI導入） | ✅ 完了 |
| 3 | Data layer（series / observations / releases / calendar、CSV adapter） | ✅ 完了 |
| 4 | Historical / Vintage（ALFRED 真vintage、as-of 漏れの静的検出、JGB） | ✅ 完了 |
| 5 | Forecast layer（CPI / NFP 予測、予測vintageの保存） | ✅ 完了 |
| 6 | News / Institutional forecasts | 未着手（APIキー・外部到達が必要） |
| 7 | Cross asset（Gold / USDJPY 解釈） | ✅ 完了 |
| 8 | Daily reports（`reports/daily/YYYY-MM-DD.md`） | ✅ 完了 |
| 9 | Validation（予測精度の検証） | ✅ 完了（Phase 6-8 に先行） |
| 10 | GitHub Actions（日次自動化） | ✅ 完了 |

## 自動実行

`.github/workflows/daily.yml` が平日 07:10 UTC に全チェーンを実行し、
`data/` と `reports/` をコミットする。必要な GitHub secrets：

| secret | 用途 |
|---|---|
| `MIOS_DATABASE_URL` | マネージドPostgreSQL（ADR-010）。未設定なら着手前に失敗する |
| `FRED_API_KEY` | FRED / ALFRED（無料） |
| `TWELVEDATA_API_KEY` | 価格データ（ADR-011） |

プロバイダが1つ死んでも**レポートは必ず生成される**。
レポートは欠損を明記するので、何かが壊れた日にこそ価値がある。
壊れたステップはジョブ要約に出て、ジョブは**コミットの後に**失敗する。

## リポジトリ構成

```
config/       全設定（ソース・系列・資産・タクソノミ・ウェイト・ジョブ）
data/raw/     取得した生ペイロード。永久保存・コミット対象
db/migrations 連番SQLマイグレーション（後方互換必須）
docs/         設計書と ADR
reports/      生成された日次レポート（Phase 8〜）
src/mios/     本体（層＝サブパッケージ、import は上流→下流の一方向）
tests/        unit / integration
var/          実行時の使い捨て状態（git管理外）
archive/      BIOS 期の設計文書と歴史データ
```
