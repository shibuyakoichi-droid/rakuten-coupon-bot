# -*- coding: utf-8 -*-
"""
coupon.get の動作確認スクリプト。

使い方:
    python test_get.py <クーポンコード>

目的:
  - 認証（serviceSecret / licenseKey）が通るか確認
  - availCount（利用数）が実際の消化枚数と一致するか確認
    （テスト用クーポンを自分で1回使って availCount が 1 になるか等を検証）
"""

import json
import sys
from pathlib import Path

from rakuten_client import RakutenCouponClient, RakutenApiError


def main():
    if len(sys.argv) < 2:
        print("使い方: python test_get.py <クーポンコード>")
        sys.exit(1)

    coupon_code = sys.argv[1]
    raw_mode = len(sys.argv) > 2 and sys.argv[2].lower() == "raw"
    config = json.loads((Path(__file__).parent / "config.json").read_text(encoding="utf-8"))
    auth = config["auth"]

    client = RakutenCouponClient(auth["service_secret"], auth["license_key"])

    # raw モード: 生XML全体を表示して終了（itemType / otherConditions などの設定確認用）
    if raw_mode:
        print("=== coupon.get 生レスポンス（XML全体）===")
        print(client.get_coupon_raw(coupon_code))
        return

    try:
        info = client.get_coupon(coupon_code)
    except RakutenApiError as e:
        print(f"[エラー] {e}")
        if e.status_code:
            print(f"  HTTP status: {e.status_code}")
        if e.body:
            print("  応答本文（先頭500文字）:")
            print("  " + e.body[:500])
        sys.exit(1)

    print("=== coupon.get 結果 ===")
    print(f"クーポンコード : {info['coupon_code']}")
    print(f"クーポン名     : {info['coupon_name']}")
    print(f"発行上限(50)   : {info['issue_count']}   <- issueCount")
    print(f"利用数         : {info['avail_count']}   <- availCount ★これが消化枚数")
    print(f"残枚数         : {info['remaining']}   (= issueCount - availCount)")
    print(f"ステータス     : {info['coupon_status']}   (3:本発行 / 6:終了)")
    print(f"有効期限       : {info['end_date']}")
    print(f"終了済み判定   : {info['is_finished']}")


if __name__ == "__main__":
    main()
