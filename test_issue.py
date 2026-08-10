# -*- coding: utf-8 -*-
"""
coupon.issue の安全なお試し発行スクリプト。

安全対策:
  - 5枚だけ発行（50枚以下なので手数料なし）
  - 限定公開（displayFlag=0）＝獲得URLを知る人しか使えない＝お客に見えない
  - 有効期間1日
  - 引数なしで実行 → 送信XMLの「プレビューのみ」（発行しない）
  - 引数に yes を付けて実行 → 実際に発行

使い方:
    python test_issue.py           # プレビューのみ（安全確認）
    python test_issue.py yes       # 実際に5枚・限定公開で発行
"""

import json
import sys
from pathlib import Path

from rakuten_client import RakutenCouponClient, RakutenApiError, build_issue_xml


def main():
    do_issue = len(sys.argv) > 1 and sys.argv[1].lower() == "yes"

    config = json.loads((Path(__file__).parent / "config.json").read_text(encoding="utf-8"))
    auth = config["auth"]

    # テスト用に安全な設定へ上書き
    coupon = dict(config["coupon"])
    coupon["issue_count"] = 5        # 5枚だけ
    coupon["validity_days"] = 1      # 1日だけ
    coupon["display_flag"] = 0       # 限定公開（お客に見えない）
    coupon["start_buffer_minutes"] = max(90, coupon.get("start_buffer_minutes", 90))

    print("=== 送信するリクエストXML（プレビュー）===")
    print(build_issue_xml(coupon))
    print()

    if not do_issue:
        print("※これはプレビューのみです。実際に発行していません。")
        print("※発行するには:  python test_issue.py yes")
        return

    print("=== 実際に発行します（5枚・限定公開・1日）===")
    client = RakutenCouponClient(auth["service_secret"], auth["license_key"])
    try:
        result = client.issue_coupon(coupon)
    except RakutenApiError as e:
        print(f"[エラー] {e}")
        if e.body:
            print("  応答本文（先頭500文字）:")
            print("  " + e.body[:500])
        sys.exit(1)

    print(f"発行成功！")
    print(f"  クーポンコード : {result['coupon_code']}")
    print(f"  獲得URL        : {result['pc_get_url']}")
    print()

    # 発行直後の状態を取得して確認
    try:
        info = client.get_coupon(result["coupon_code"])
        print("=== 発行直後の状態（coupon.get で確認）===")
        print(f"  発行上限 : {info['issue_count']}（5になっていれば成功）")
        print(f"  利用数   : {info['avail_count']}")
        print(f"  残枚数   : {info['remaining']}")
    except RakutenApiError as e:
        print(f"(確認取得でエラー: {e})")

    print()
    print("※このテストクーポンは限定公開なのでお客様には見えません。")
    print("※不要になったらRMSのクーポン管理画面から削除してください。")


if __name__ == "__main__":
    main()
