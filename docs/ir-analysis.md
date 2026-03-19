# Nature Remo IR 解析レポート（首振り・オフタイマー）

本ドキュメントは、クラウド上の登録シグナルのダンプ、ローカルAPIによるIR生データの取得、送信検証、ならびにIRプロトコルの解析結果をまとめたものです。

## 概要
- クラウドに登録済みのシグナル一覧（name/id）の取得を `dump_cloud_signals.py` で実施
- ローカルAPI `GET /messages` を 1秒間隔でポーリングして、物理リモコンから受信したIRデータ（freq, data[us], format）を取得
- 取得したIRを `POST /messages` で送信し、扇風機が期待通りに反応することを確認
- 受信データをAEHA系プロトコル想定で正規化し、ビット列→バイト配列へ復元して比較・解析
- 代表例（首振り・オフタイマー）について、データ部（コマンド/末尾バイト）の規則性を特定

## 環境変数と前提
- `.env` に以下を設定
  - `NATURE_REMO_TOKEN` または `NATURE_REMO_API_TOKEN`: Cloud API 用トークン
  - `NATURE_REMO_LOCAL_IP_ADDRESS`: Remo 本体のローカルIP（例: `192.168.1.23`）
- Remo アプリ側で「ローカルAPI」を有効化してください
- 実行端末と Remo が同一LAN上にいること

## 使用スクリプト一覧（本リポジトリ）
- `dump_cloud_signals.py`
  - クラウドの `/1/appliances` を叩いて、アプライアンスと signals（name/id）をダンプ
  - トークンは `NATURE_REMO_API_TOKEN` または `NATURE_REMO_TOKEN` のいずれでも可
- `dump_local_message.py`
  - ローカルAPI `GET /messages` のポーリング（1秒ごと等）
  - `.env` の `NATURE_REMO_LOCAL_IP_ADDRESS` を自動参照、`--watch` で連続表示、`--raw` で data:[0] でも出力
  - 例: `uv run python dump_local_message.py --interval 1 --watch`
- `send_local_message_from_file.py`
  - テキストファイル（例: `dump-results.txt`）の指定行から JSON を抽出し、`POST /messages` に送信
  - X-Requested-With ヘッダー付与済み
  - 例: `uv run python send_local_message_from_file.py dump-results.txt --line 0`
- `analyze_ir_dump.py`
  - コメント行（`#`, `//`）をスキップし、各行の IR JSON をAEHA系としてデコード
  - ビット列長、推定単位時間、LSB-first バイト配列、ハミング距離を出力
- `checksum_search.py`
  - デコードした8バイト配列を用いて、末尾バイトの規則（チェックサム/ベンダ固有フィールド）を探索

## 実施手順の要点
1) クラウドのシグナル一覧を確認
```
uv run python dump_cloud_signals.py
```
2) ローカルAPIで受信IRを取得（1秒ごと）
```
# ボタンをRemoへ向けて押すと、その直後の受信IRが出力されます
uv run python dump_local_message.py --interval 1 --watch
```
3) 取得したIRを送信検証
```
# dump-results.txt の指定行を /messages へ送信
uv run python send_local_message_from_file.py dump-results.txt --line 0
```

## 取得結果のマッピング（ユーザー提供の注釈に基づく）
- 1行目, 6行目: コメント
- 2〜5行目: 首振り（どれも動作）
- 7〜10行目: オフタイマー（どれも動作）

実測では、同一機能の複数行は小さな時間ブレ（数％〜10％程度）を含みますが、正規化すると同一のビット列に収束します。

## 解析結果（AEHA系のフレーミングを想定）
- ビット列長は概ね 64bit（=8バイト）に復元可能
- LSB-first で詰め直した代表バイト配列:
  - 首振り（例）: `[0x23, 0xCB, 0x16, 0x44, 0x80, 0x89, 0x03, 0xB0]`
  - オフタイマー（例）: `[0x23, 0xCB, 0x16, 0x44, 0x80, 0x89, 0x04, 0xC0]`
- 先頭6バイトは両者で完全一致（メーカー/機種識別に相当）
- 7バイト目がコマンド本体
  - 首振り: `0x03`
  - オフタイマー: `0x04`
- 8バイト目は“チェックサム的”フィールド
  - 探索・検証の結果、以下の簡潔な規則に合致
    - `cs = 0x80 + (cmd << 4)` （mod 256）
    - 首振り: `0x80 + (0x03 << 4) = 0xB0`、オフタイマー: `0x80 + (0x04 << 4) = 0xC0`
- つまり、末尾バイトは標準AEHAの単純な和の補数ではなく、ベンダ固有の「固定フラグ + コマンド上位ニブル」構成である可能性が高いと考えられます。

### ハミング距離・単位時間の参考値
- 首振りグループ内: ハミング距離 0（完全一致）
- オフタイマーグループ内: ハミング距離 0（完全一致）
- グループ間（代表同士）: ハミング距離 6（コマンドと末尾フィールドの違いに起因）
- 推定単位時間（unit_us）は 326〜365us 程度で収束

## 実務上の指針
- 各機能につき代表の1サンプルを採用して問題ありません（送信時は許容範囲のブレが吸収されます）
- `signals/oscillate.json`（首振り）, `signals/off_timer.json`（オフタイマー）として保存し、運用に組み込むことを推奨
- Cloud API に新規シグナルとして登録しておけば、以後はID指定で安定運用が可能

## 追加の検証・今後の課題
- 他のボタン（左/右/上下 等）でも `cs = 0x80 + (cmd << 4)` が成り立つか確認
- 先頭6バイトのベンダ識別の確定（顧客コード、サブアドレスの分解）
- 正規化・クラスタリングを自動化し、dumpファイルから代表パターンを抽出して命名保存するツール化

## 参考コマンド
```
# 首振り/オフタイマーの解析（コメント行スキップ対応）
uv run python analyze_ir_dump.py dump-results.txt

# 末尾フィールドの規則（候補）を探索
uv run python checksum_search.py dump-results.txt

# ローカルAPI 連続取得（1秒間隔）
uv run python dump_local_message.py --interval 1 --watch

# ローカルAPI 送信（指定行）
uv run python send_local_message_from_file.py dump-results.txt --line 1
```

## 付録: 既存/追加スクリプトの変更点
- `dump_cloud_signals.py`: `NATURE_REMO_TOKEN` にも対応
- `dump_local_message.py`: `.env` 読み込み、`--watch`/`--raw`/ヘッダー付与、ログ強化
- `send_local_message_from_file.py`: 行からのJSON抽出と `/messages` 送信
- `analyze_ir_dump.py`: AEHA系デコードと比較
- `checksum_search.py`: 末尾バイト規則の探索

### 追記: ブルートフォース検証メモ (2025-11-11)
- `send_bruteforce_cmd.py` にて、ヘッダー `[0x23, 0xCB, 0x16, 0x44, 0x80, 0x89]`、`cmd=0x02` 固定で、末尾バイトを `0xA0`〜`0xAF` にした全てで風量切替が反応。
- 含意: 末尾バイトは上位4ビットのみが検証対象で、`(cs & 0xF0) == 0x80 + (cmd << 4)` を満たせば下位4ビットは不問（ドントケア）と推定。
- 運用推奨: `cs = 0x80 + (cmd << 4)` とし、下位4ビットは `0x0` を固定（例: `cmd=0x02 → cs=0xA0`）。

### 追記: ブルートフォース検証メモ (2026-03-19)
- `cmd=0x01` で電源のオン/オフがトグル動作することを確認。
- `xx=0x90`〜`0x9F` のいずれでも反応し、下位4ビットはドントケア。
- 運用推奨: `cmd=0x01`、`cs = 0x90`（下位4ビットは `0x0` 固定）。
- `cmd=0x0A` / `xx=0x20` でオンタイマーが反応することを確認。
