# コードと仕様の参照先

現行の新規判断は[標準テクニカル構成](STANDARD_TECHNICAL_PROFILE.md)を使用する。実装・本番反映・自然実行の状態は[管理Issue #1](https://github.com/nyancoworks/fx-monitor/issues/1)で管理する。

| 役割 | コード・文書 |
| --- | --- |
| 取得・確定足品質・指標準備 | `main.py`、`data_quality.py`、`indicator_inputs.py`、`indicator_history.py`、`indicator_refresh.py` |
| 現行指標・予測・価格計画・32評価 | `standard_technicals.py`、`technical_entry.py`、`scheduled_outlook.py` |
| 同ペアの戦略関係・掲載・本文 | `pair_market_context.py`、`strategy_report.py`、`REPORT_SELECTION.md` |
| 保存・完全復元・履歴・前回条件 | `strategy_report_export.py`、`saved_standard_inputs.py`、`scenario_continuity.py`、`scenario_followthrough.py`、`diagnostics/monitoring_result_history.py`、`PRIVATE_REPORT_READING.md` |
| 保存通貨強弱・経済指標・政策資料 | `strategy_strength.py`、`economic_calendar_context.py`、`ECONOMIC_CALENDAR.md`、`POLICY_REFERENCE.md` |
| NY17確定足・既存保管 | `ny_archive_transport.py`、`ny_archive_status.py`などの保管/復元処理、`ARCHIVE_INVENTORY.md` |

パスは特記がなければコードが`fx_system/`、文書が`docs/`内。既存workflow・保管CLIなどはPython import以外からも呼ばれるため、importがないだけで削除しない。

旧版のDMA・ディナポリMACD・Preferred Stochastic・スパンモデル・PA・レンジ解釈と、その計算器/テストは当時の保存判断・元本文の復元に必要な範囲で保持する。旧版仕様には先頭に区別を表示する。保存データの旧フィールド名を読む処理は、不要になった生成器とは区別する。

参照・復元用途のない旧PA/RCI shadow、旧H4セットアップと近傍目標提案、H1/H4比較、参考ゾーン、観測H1からの旧マクロ参考生成、旧screeningラッパーと入力層診断、未使用のEMA10/20/30等の一括診断は撤去した。履歴原本・非公開証跡は削除しない。
