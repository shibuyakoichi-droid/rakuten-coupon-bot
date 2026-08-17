# -*- coding: utf-8 -*-
"""
商品別クーポンを指定日に発行する（毎日50枚限定・その日限り）
============================================================
product_coupon_config.json の内容で、対象商品のクーポンを1回発行する。
既存の rakuten_client（coupon.issue）をそのまま使う。認証は環境変数から。

安全弁: 本番発行は config の issue_dates に today(JST) が含まれる日だけ実行する
        （GitHub Actionsのcronが別日に誤発火しても、対象日以外は発行しない）。

使い方:
  python product_coupon.py            # 本番発行（config通り・対象日のみ）
  python product_coupon.py --test     # 限定公開・1枚でテスト発行（動作確認用／日付チェックなし）
  python product_coupon.py --force    # 対象日チェックを無視して本番発行（手動発行用）
"""
import argparse
import datetime
import json
import os
import sys
from pathlib import Path

import requests

from rakuten_client import RakutenCouponClient, RakutenApiError

BASE_DIR = Path(__file__).parent
CONFIG_PATH = BASE_DIR / "product_coupon_config.json"
JST = datetime.timezone(datetime.timedelta(hours=9))

# LINE通知（任意）: 環境変数 LINE_CHANNEL_ACCESS_TOKEN があれば発行結果をLINEに送る
LINE_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
LINE_TO = os.environ.get("LINE_TO")


def notify_line(text):
    """LINEに発行結果を通知する（トークン未設定なら何もしない）。失敗しても本処理は止めない。"""
    if not LINE_TOKEN:
        return
    try:
        if LINE_TO:
            url = "https://api.line.me/v2/bot/message/push"
            payload = {"to": LINE_TO, "messages": [{"type": "text", "text": text[:4900]}]}
        else:
            url = "https://api.line.me/v2/bot/message/broadcast"
            payload = {"messages": [{"type": "text", "text": text[:4900]}]}
        requests.post(
            url,
            headers={"Authorization": f"Bearer {LINE_TOKEN}", "Content-Type": "application/json"},
            data=json.dumps(payload).encode("utf-8"),
            timeout=20,
        )
    except Exception:  # noqa: BLE001 通知失敗は無視
        pass


def main():
    ap = argparse.ArgumentParser(description="商品別クーポン発行")
    ap.add_argument("--test", action="store_true", help="限定公開・1枚でテスト発行")
    ap.add_argument("--test-line", action="store_true", help="LINE通知だけをテスト送信（発行しない）")
    ap.add_argument("--force", action="store_true", help="対象日チェックを無視して発行（手動用）")
    ap.add_argument("--config", default=str(CONFIG_PATH), help="使用する設定ファイル（既定=product_coupon_config.json）")
    args = ap.parse_args()

    # LINE通知の疎通テスト（クーポンは発行しない）
    if args.test_line:
        if not LINE_TOKEN:
            print("[!] LINE_CHANNEL_ACCESS_TOKEN が未設定です（Secret登録を確認してください）。")
            sys.exit(1)
        notify_line("✅ クーポン発行通知のテストです。この通知が届けば設定OKです。")
        print("[テスト] LINE通知を送信しました。スマホに届いたか確認してください。")
        return

    cfg = json.loads(Path(args.config).read_text(encoding="utf-8"))
    service_secret = os.environ.get("RAKUTEN_SERVICE_SECRET")
    license_key = os.environ.get("RAKUTEN_LICENSE_KEY")
    if not service_secret or not license_key:
        sys.exit("[!] 認証情報がありません（環境変数 RAKUTEN_SERVICE_SECRET / RAKUTEN_LICENSE_KEY）。")

    today = datetime.datetime.now(JST).date().isoformat()
    allowed = cfg.get("issue_dates", [])

    # 本番は「対象日だけ」発行（テスト・force は除く）
    if not args.test and not args.force:
        if allowed and today not in allowed:
            print(f"[スキップ] 本日 {today} は発行対象日ではありません（対象: {allowed}）。")
            return

    # 単一(coupon) でも複数(coupons: [...]) でもまとめて発行できる
    coupon_defs = cfg.get("coupons") or [cfg["coupon"]]
    # LINE通知: config の notify_line=false なら送らない（テスト時も送らない）
    notify_on = cfg.get("notify_line", True) and not args.test

    client = RakutenCouponClient(service_secret, license_key)
    issued = []
    for cdef in coupon_defs:
        coupon = dict(cdef)
        if args.test:
            coupon["display_flag"] = 0        # 限定公開（お客様には出さない）
            coupon["issue_count"] = 1         # 1枚だけ
            coupon["coupon_name"] = "【テスト】" + coupon.get("coupon_name", "商品クーポン")
        name = coupon.get("coupon_name", "商品クーポン")
        mode = "テスト発行(限定公開1枚)" if args.test else "本番発行"
        print(f"[発行] {mode}: {name} / 対象={coupon.get('target_item_urls')} "
              f"/ {coupon.get('discount_factor')}%OFF / {coupon.get('issue_count')}枚")
        try:
            result = client.issue_coupon(coupon, name)
        except RakutenApiError as e:
            print(f"[発行エラー] {name}: {e}")
            if notify_on:
                notify_line(f"❌ クーポン発行に失敗しました（{today}）\n{name}\n{e}")
            sys.exit(1)
        print(f"[発行完了] {name} couponCode={result['coupon_code']}")
        print(f"[獲得URL] {result.get('pc_get_url')}")
        issued.append((name, result["coupon_code"], result.get("pc_get_url")))

    if notify_on:
        lines = [f"✅ クーポンを発行しました（{today}）"]
        for name, code, url in issued:
            lines.append(f"\n{name}\nコード: {code}\n獲得URL: {url}")
        notify_line("\n".join(lines))


if __name__ == "__main__":
    main()
