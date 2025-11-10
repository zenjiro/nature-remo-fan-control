# 扇風機（R30J-HRV想定）「電源ON」信号送信の実行計画

本計画は、docs/chatgpt-report.md と docs/gemini-report.md の内容に基づき、最短で「電源ON」信号を送るための具体的な方針と手順をまとめたものです。基本戦略は Nature Remo（Cloud API/Local API）をハブにして、学習済みまたは既知のRAWパルス列を送信して動作検証することです。

---

## 1. 目的
- Nature Remo を用いて三菱電機製扇風機（R30J-HRV想定）に「電源ON」IR信号を送信し、起動を確認する。

## 2. 前提・制約
- 対象扇風機が赤外線（IR）方式であること（RF/Bluetoothでは不可）。
- Remo が同一LAN（Local API使用時）またはインターネット疎通（Cloud API使用時）にあること。
- キャリア周波数は概ね38kHz。メーカー独自プロトコルの可能性が高く、RAW（μs）配列を扱う前提。
- 物理リモコンが無い場合は、
  - 既存の学習済みシグナルがRemoに残っていればそれを再利用、
  - それが無ければ、公開例（参考ブログ等）や自前計測のRAW配列を用意して登録・送信で検証する。

## 3. 方針（優先度順）
1) Cloud APIで既存の学習シグナルを確認 → あればその「電源」シグナルを送信（最短）
2) 学習シグナルが無い場合は、信号を新規登録して送信
   - RAW形式: { "format": "us", "freq": 38, "data": [ON/OFF時間(μs)配列] }
   - data配列は、
     - Remoアプリで学習して取得（推奨）
     - または docs/chatgpt-report.md の参考リンク等の既知データを元に仮登録し、動作を検証
3) 反応が無い場合は Local API で試行回数を増やし、パルス列の微調整（リードイン/マーク/スペース幅）を行う。

## 4. 実行手順（Cloud API）

### 4.1 準備
- Nature Remo Cloud API のパーソナルアクセストークン（PAT）を用意。
- Python の requests を利用。トークンは環境変数に格納。

### 4.2 アプライアンスIDと既存シグナルの確認
- GET /1/appliances で扇風機アプライアンスのIDを取得。
- GET /1/appliances/{applianceId}/signals で既存シグナル（電源）があるか確認。

### 4.3 既存シグナルの送信（あれば最短）
- POST /1/signals/{signalId}/send で送信し、扇風機の起動を確認。

### 4.4 新規シグナル登録（無い場合）
- POST /1/appliances/{applianceId}/signals に以下のようなペイロードで登録。
  - name: "power_on"（任意）
  - message: JSON文字列（RAW）：{"format":"us","freq":38,"data":[…]}
- 戻りの signalId を取得。

### 4.5 送信と検証
- POST /1/signals/{signalId}/send で送信。
- 扇風機が起動するか確認。
- 反応しない場合は、data配列のタイミング（特にリードイン、ビット長、リピート構造）を見直し。

#### Python スニペット（Cloud API）

```python
import os
import json
import requests

BASE = "https://api.nature.global/1"
TOKEN = os.environ["NATURE_REMO_TOKEN"]
HEADERS = {"Authorization": f"Bearer {TOKEN}"}

# 1) アプライアンス取得
aps = requests.get(f"{BASE}/appliances", headers=HEADERS).json()
# "扇風機" など名称から対象を選ぶ（例）
appliance = next(a for a in aps if "扇風機" in a.get("nickname", "") or a.get("type") == "IR")
app_id = appliance["id"]

# 2) 既存シグナル確認
sigs = requests.get(f"{BASE}/appliances/{app_id}/signals", headers=HEADERS).json()
power = next((s for s in sigs if "電源" in s["name"] or "power" in s["name"].lower()), None)

if power is None:
    # 3) 無ければ新規登録（RAW例: 仮のデータ。実機に合わせて差し替え）
    raw = {
        "format": "us",
        "freq": 38,
        "data": [
            # 例: リードイン/データ/リードアウト（μs）。実測または信頼できる資料で置換。
            9000, 4500, 560, 560, 560, 560, 560, 1690, 560, 560,
            # ... 省略 ...
        ]
    }
    payload = {
        "name": "power_on",
        "message": json.dumps(raw, separators=(",", ":"))
    }
    created = requests.post(f"{BASE}/appliances/{app_id}/signals", headers=HEADERS, json=payload).json()
    power = created

# 4) 送信
requests.post(f"{BASE}/signals/{power['id']}/send", headers=HEADERS)
print("sent:", power["name"]) 
```

> 注意: data は実機のRAW配列に差し替えてください。docs/chatgpt-report.md の参考リンク（例: ak1211.com）で公開例を参照し、μs配列に展開するか、Remoアプリで一度学習してCloud APIから取得したRAWを流用するのが確実です。

## 5. Local API による高速検証（代替手順）
- RemoのローカルIPが分かれば、`/messages`（Local API）に対し X-Requested-With ヘッダー付きで POST。
- 低遅延なので、微修正を繰り返す検証に向く。

```python
import requests
import json

REMO_IP = "http://<remo-local-ip>"
HEADERS = {"X-Requested-With": "local"}
raw = {"format": "us", "freq": 38, "data": [/* 実データ */]}
requests.post(f"{REMO_IP}/messages", headers=HEADERS, data=json.dumps(raw))
```

## 6. データ取得の現実解
- 物理リモコンが無い場合のRAWデータ入手は次のいずれか：
  - Remoアプリで「手動学習」で一度だけでも電源ボタンを学習 → Cloud APIでJSON取得 → 再利用
  - 参考ブログ等の公開RAW/HEXをμs配列に変換して試す（成功報告がある例を優先）
  - Raspberry Pi + 受光モジュールでキャプチャ（pigpio等）。

## 7. 失敗時の切り分け
- 反応しない場合：
  - Remoの向き・距離・電池残量（Remo本体）
  - 周波数（38kHz付近）とデューティ
  - リードイン長、ビット長、フレームのリピート有無
  - 電源ボタンがトグル式（同一コードでON/OFF）か、別コード（ON/OFf分離）かの確認

## 8. 次の拡張
- 「風量（弱/中/強）」「首振りON/OFF」等の各コマンドを、電源ONのRAWを基に微調整・派生して登録。
- 検証済みコードをNature Remoアプリにボタン化、さらにシーン化し、Alexa/Google Homeのルーティンに連携。

## 9. チェックリスト（実行順）
- [ ] Cloud APIトークンを準備
- [ ] /1/appliances で対象アプライアンスID取得
- [ ] 既存の「電源」シグナル有無を確認
- [ ] あれば即送信して起動確認
- [ ] 無ければRAWで新規登録 → 送信
- [ ] 反応が無ければLocal APIで微調整→再送
- [ ] 成功後、アプリにボタン配置→シーン作成→音声連携

---

補足: 実装が進み、安定したRAW配列が確定したら docs/ に信号カタログ（power_on.md 等）を作成して再現性を確保することを推奨します。