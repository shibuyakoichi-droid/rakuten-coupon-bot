# -*- coding: utf-8 -*-
"""
オフライン・デモ（楽天につながずロジックだけ確認）

使い方:
    python demo.py

やること:
  - モッククライアントで「50枚発行 → 消化 → 使い切り → 再発行」を高速に再現。
  - 実際のAPIも認証も不要。state_demo.json に状態を書く（本番の state.json は汚さない）。
"""

from pathlib import Path

import coupon_bot
from mock_client import MockCouponClient

BASE_DIR = Path(__file__).parent

# 本番の状態ファイルを汚さないよう、デモ用に差し替え
coupon_bot.STATE_PATH = BASE_DIR / "state_demo.json"
if coupon_bot.STATE_PATH.exists():
    coupon_bot.STATE_PATH.unlink()  # 毎回まっさらから開始

# デモ用の設定（少枚数・間隔ゼロで一気に回す）
demo_config = {
    "coupon": {
        "coupon_name": "3000円以上で100円OFF(デモ)",
        "coupon_code_prefix": "DEMO",
        "discount_type": 1,
        "discount_factor": 100,
        "condition_type": "amount",
        "min_purchase_amount": 3000,
        "min_purchase_count": 2,
        "issue_count": 50,
        "item_type": 4,
        "validity_days": 7,
        "start_buffer_minutes": 0,
        "member_avail_max_count": 1,
        "combine_flag": 0,
        "target_item_urls": [],
    },
    "automation": {
        "enabled": True,
        "reissue_threshold": 0,
        "max_reissue_per_day": 100,          # デモなので上限緩め
        "min_reissue_interval_minutes": 0,   # デモなので即再発行OK
    },
    "notify": {"enabled": False},
}

client = MockCouponClient(consume_per_check=9)  # 1チェックで9枚消化される想定

print("=== オフラインデモ開始（50枚 → 使い切り → 自動再発行）===\n")
for i in range(1, 21):
    print(f"[チェック {i:>2}]")
    state = coupon_bot.load_state()
    coupon_bot.run_once(client, demo_config, state, force_issue=False)
    print()

print("=== デモ終了 ===")
print("state_demo.json に世代履歴が残っています。")
