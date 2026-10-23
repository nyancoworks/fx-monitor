# 小さな非公開レポートの読取り

大容量の `data/latest.json` はGitHub読取り経路によって本文が空になったり、blob取得で接続エラーになったりすることがあります。原本を縮小・上書きせず、既存snapshot保存と同じprivate commit/pushに `data/strategy-report.json` を追加します。Actions起動・市場API取得・スケジュール・Git pushの回数は増やしません。

`saved_strategy_report_v1` は次を保持します。

- 同じ実行の `source` と元の `snapshot_git_blob_sha`。
- 全32評価の識別子・状態・A/B/C・方向、件数内訳。
- 検証済み保存評価から生成した日本語 `report_text`（各戦略最大3候補と非掲載件数、経済指標の注意・出典を含む）。
- 全32評価と元の行別評価を欠損なく保存した、gzip/base64形式の監査用データ。

原本に対する32評価・行別一致の検証に通った場合だけレポートを作ります。監査用データは関連しない価格足を含まない表示用viewで、元の市場データ原本そのものではありません。圧縮データにはSHA-256、復元サイズ上限16MiB、JSON全体には約900KBの上限を設けます。内容ハッシュと実行IDは保存世代を照合するもので、独立した署名保証ではありません。

レポート生成・検証・サイズ制限で失敗しても元のsnapshot保存は続け、その実行の `status=unavailable` と空の本文を保存します。以前の成功レポートを新しい実行として使いません。private出力パスのsymlinkやルート外への書込みは拒否します。公開repo・公開ログには本文・評価・圧縮原本を出しません。

読取り側はまず `data/source.json` と `data/run-diagnostics.json` を照合し、同じ実行の `strategy-report.json` のsource・snapshot blob SHA・状態を確認します。可能なら同じprivate commitを指定して読みます。状態がsavedで、32件の識別子が16ペア×2戦略と一致し内訳も一致する場合に本文を利用します。市場データ品質の成功は診断の `validation.passed` と区別して確認します。報告タスクは圧縮データを復元できなくても平文の32件一覧と本文を読めますが、その場合は圧縮原本を独立再検証したとは扱いません。

監査用viewの完全復元は `restore_strategy_report_export(bundle, source, snapshot_blob_sha)` で行います。source/hash、展開サイズ、圧縮の末尾・追加メンバー、チェックサム、32評価・元行一致、平文32件一覧・本文との一致を再検証します。利用不能・別世代・破損時は成功や候補なしと取り違えず、既存の原本読取り経路へ戻すか確認できない項目を明示します。取得・生成・配信成功はそれぞれ別の確認です。
