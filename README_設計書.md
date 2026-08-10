# 楽天クーポン自動発行ボット 設計書

「2個以上購入で10%OFF・50枚限定」クーポンを発行し、**使い切ったら自動で新しい50枚を再発行**する仕組み。
50枚を超えると発行手数料（51枚目から1枚50円）が発生するため、**常に1発行50枚以内**に抑え、消化したら次の50枚を発行してコストをゼロに保つ。

---

## 1. 全体の流れ

```
① coupon.issue で50枚クーポンを発行（世代コード gen0001）
        │
        ▼
② 一定間隔で coupon.get を実行 → availCount（利用数）を確認
        │
        ▼
③ availCount ≧ 50（= issueCount）または couponStatus=6(終了) を検知
        │  = 「使い切り」判定
        ▼
④ coupon.issue で新しい50枚を発行（gen0002）→ ②へ戻る
```

- **残枚数 = `issueCount`(50) − `availCount`(利用数)**
- `availCount` はクーポン自身のカウンタなので、受注集計より速く正確。

---

## 2. 使用する RMS WEB SERVICE API

| API | 用途 |
|---|---|
| `coupon.issue` | 50枚クーポンを新規発行 |
| `coupon.get`   | 現行クーポンの `availCount`（利用数）/ `couponStatus` を取得して消化状況を監視 |
| `coupon.delete`（任意） | 古い世代の後始末（通常は有効期限切れで自然終了させるので必須ではない） |

### coupon.get の主要レスポンス項目（確認済み）
| 項目 | 意味 | 用途 |
|---|---|---|
| `issueCount` | クーポンの全利用回数上限 | 分母（=50） |
| `availCount` | 利用数（消化済み枚数） | 監視対象 ★ |
| `couponStatus` | 3:本発行 / 6:終了 | 終了検知の補助 |
| `couponEndDate` | 有効期間（終了日時） | 期限切れ検知 |

### coupon（発行時）の項目マッピング
| やりたいこと | 項目 | 設定値 |
|---|---|---|
| 10%OFF | `discountType` / `discountFactor` | `2`(定率) / `10` |
| 50枚限定 | `issueCount` | `50` |
| 2個以上で適用 | 個数条件（otherConditions） | 2個以上 |
| 有効期間 | `couponStartDate` / `couponEndDate` | 発行時に設定 |
| 対象商品 | `items` / `itemType` | 全商品 or 指定URL |

> ⚠️ `coupon.issue` の**リクエストXMLの正確な構造**（ラッパー要素名・個数条件の指定方法）は、
> RMS開発者ポータルの「coupon.issue」ページの Request セクションで最終確認が必要。
> `rakuten_client.py` の `build_issue_xml()` にTODOコメントあり。

---

## 3. 認証

RMS WEB SERVICE は HTTPヘッダで認証する。

```
Authorization: ESA <Base64( serviceSecret:licenseKey )>
```

- `serviceSecret` … RMS「WEB API」利用設定で発行されるシークレット
- `licenseKey` … 同ライセンスキー（**90日で失効**。要更新運用）

---

## 4. 再発行の安全装置（歯止め）

無限発行・想定外コストを防ぐため、以下を `config.json` で制御。

| 設定 | 既定 | 意味 |
|---|---|---|
| `enabled` | true | 全体のON/OFF |
| `reissue_threshold` | 0 | 残りこの枚数以下で再発行（0=完全に使い切ってから） |
| `max_reissue_per_day` | 5 | 1日の再発行回数の上限（超えたら発行せずログのみ） |
| `min_reissue_interval_minutes` | 30 | 前回発行からこの分数は再発行しない（連続発行防止） |

---

## 5. 運用フロー（Windowsタスクスケジューラ）

`coupon_bot.py` を **1回実行＝1チェック** の「ワンショット型」で作成。
これをタスクスケジューラで**10〜30分ごと**に起動する（常駐プロセスより再起動に強い）。

1. `state.json` を読む（現在の世代・クーポンコード・本日の再発行回数）
2. アクティブなクーポンが無ければ → 発行して終了
3. あれば `coupon.get` で `availCount` を確認
4. 使い切り（or 終了 or 期限切れ）なら、歯止めを確認して再発行
5. 状態とログを更新して終了

---

## 6. 導入手順

### STEP 0: 事前準備（RMS側・1回だけ）
1. RMS「WEB API」→「利用設定」→「利用機能編集」で **Coupon API を有効化**
2. `serviceSecret` と `licenseKey` を取得

### STEP 1: セットアップ
```bash
cd rakuten-coupon-bot
pip install -r requirements.txt
copy config.example.json config.json   # 中身を自店舗の値に編集
```

### STEP 2: 動作確認（重要）
`availCount` の意味を実データで確定させる。
```bash
python test_get.py <既存のクーポンコード>
```
→ 表示された `availCount` が実際の利用数と一致するか確認。
（テスト用クーポンを自分で1回使い、`availCount` が 1 になるかも見ておくと万全）

### STEP 3: 発行を単発テスト
```bash
python coupon_bot.py --once --force-issue   # 1回だけ強制発行して動作確認
```
※ coupon.issue のリクエスト仕様を確定させてから実行すること。

### STEP 4: 自動化（タスクスケジューラ）
- プログラム: `python`（またはpython.exeのフルパス）
- 引数: `coupon_bot.py --once`
- 開始場所: このフォルダの絶対パス
- トリガー: 10〜30分ごとに繰り返し

---

## 7. 注意点・既知のリスク

- **世代ごとにクーポンは別物**：再発行すると新しいクーポンコード/取得URLになる。
  バナーやページに固定リンクを貼る場合は、`coupon.patch`（表示フラグ）や
  リンク差し替えの自動化も別途検討。
- **キャンセル・返品時の availCount の挙動**は STEP 2 で必ず確認（戻る/戻らない）。
- **couponStartDate の先出し制約**：楽天側で発行〜開始に最小リードタイムがある場合、
  使い切り〜次発行の間に空白が出ることがある。`start_buffer_minutes` と
  `reissue_threshold`（残り数枚で先に発行）で調整可能。
- **ライセンスキー90日失効**：切れると全API停止。`coupon.get` が401等を返したら
  通知が飛ぶようにしてある（`notify_on_error`）。更新運用を必ず組む。

---

## 8. ファイル構成

| ファイル | 役割 |
|---|---|
| `README_設計書.md` | この設計書 |
| `config.example.json` | 設定テンプレート（→ `config.json` にコピーして使用） |
| `rakuten_client.py` | RMS Coupon API クライアント（get / issue） |
| `coupon_bot.py` | 監視〜再発行のメインロジック（ワンショット/常駐） |
| `test_get.py` | `coupon.get` の動作確認用スクリプト |
| `requirements.txt` | 依存ライブラリ |
| `state.json` | 稼働状態（自動生成） |
| `coupon_bot.log` | 実行ログ（自動生成） |
