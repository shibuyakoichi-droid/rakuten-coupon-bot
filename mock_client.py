# -*- coding: utf-8 -*-
"""
オフライン実験用のニセ(モック)クライアント。

楽天APIには一切つながず、RakutenCouponClient と同じメソッド
(get_coupon / issue_coupon) を持つ。
get_coupon を呼ぶたびに「利用数(avail_count)」が増える＝お客が使っている
状況をシミュレートし、使い切り→再発行のループを目で確認できる。
"""

import datetime

JST = datetime.timezone(datetime.timedelta(hours=9))


class MockCouponClient:
    def __init__(self, consume_per_check=7):
        # 1回チェックするたびに何枚消化されたことにするか
        self.consume_per_check = consume_per_check
        # coupon_code -> {issue_count, avail_count}
        self._coupons = {}
        self._seq = 0

    def issue_coupon(self, coupon_conf, coupon_name=None):
        # 楽天は自動採番。モックでも連番でコードを生成する。
        self._seq += 1
        coupon_code = f"MOCK-{self._seq:04d}"
        self._coupons[coupon_code] = {
            "issue_count": coupon_conf.get("issue_count", 50),
            "avail_count": 0,
        }
        print(f"    (mock) 発行: {coupon_code} / 上限{self._coupons[coupon_code]['issue_count']}枚")
        return {"coupon_code": coupon_code, "pc_get_url": f"https://coupon.example/{coupon_code}"}

    def get_coupon(self, coupon_code):
        c = self._coupons.get(coupon_code)
        if c is None:
            # 未知のコードは終了扱い
            return {
                "coupon_code": coupon_code, "coupon_name": None,
                "issue_count": None, "avail_count": None, "coupon_status": 6,
                "end_date": None, "remaining": None, "is_finished": True,
            }
        # チェックのたびに消化が進む（上限で頭打ち）
        c["avail_count"] = min(c["issue_count"], c["avail_count"] + self.consume_per_check)
        remaining = c["issue_count"] - c["avail_count"]
        return {
            "coupon_code": coupon_code,
            "coupon_name": "デモクーポン",
            "issue_count": c["issue_count"],
            "avail_count": c["avail_count"],
            "coupon_status": 3,
            "end_date": None,
            "remaining": remaining,
            "is_finished": False,
        }
