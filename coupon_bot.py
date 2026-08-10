# -*- coding: utf-8 -*-
"""
楽天クーポン自動発行ボット（メイン）

動作:
  - 現行クーポンの availCount を確認し、使い切り（残 <= reissue_threshold）
    または終了/期限切れなら、新しい50枚を発行する。
  - 発行手数料を避けるため常に 1発行=issue_count(50) 枚に固定。

実行方法:
  python coupon_bot.py --once            # 1回だけチェック（タスクスケジューラ推奨）
  python coupon_bot.py --loop 900        # 900秒ごとに常駐チェック
  python coupon_bot.py --once --force-issue   # 状態に関わらず1回強制発行（動作確認用）
"""

import argparse
import datetime
import json
import logging
import smtplib
import sys
import time
from email.mime.text import MIMEText
from pathlib import Path

from rakuten_client import RakutenCouponClient, RakutenApiError

BASE_DIR = Path(__file__).parent
CONFIG_PATH = BASE_DIR / "config.json"
STATE_PATH = BASE_DIR / "state.json"
LOG_PATH = BASE_DIR / "coupon_bot.log"
JST = datetime.timezone(datetime.timedelta(hours=9))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_PATH, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("coupon_bot")


# --------------------------------------------------------------------------
# 設定・状態の入出力
# --------------------------------------------------------------------------
def load_config():
    if not CONFIG_PATH.exists():
        log.error("config.json がありません。config.example.json をコピーして作成してください。")
        sys.exit(1)
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def load_state():
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    return {
        "generation": 0,
        "current_coupon_code": None,
        "issued_at": None,
        "reissue_date": None,
        "reissue_count_today": 0,
        "history": [],
    }


def save_state(state):
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def today_str():
    return datetime.datetime.now(JST).strftime("%Y-%m-%d")


# --------------------------------------------------------------------------
# 通知
# --------------------------------------------------------------------------
def notify(config, subject, body):
    n = config.get("notify", {})
    if not n.get("enabled"):
        return
    try:
        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = subject
        msg["From"] = n["smtp_user"]
        msg["To"] = n["to"]
        with smtplib.SMTP(n["smtp_host"], n["smtp_port"], timeout=20) as s:
            s.starttls()
            s.login(n["smtp_user"], n["smtp_password"])
            s.send_message(msg)
        log.info("通知メールを送信しました。")
    except Exception as e:  # noqa: BLE001 通知失敗は本処理を止めない
        log.warning(f"通知メール送信に失敗: {e}")


# --------------------------------------------------------------------------
# 発行
# --------------------------------------------------------------------------
def set_current_coupon(client, state, code):
    """既存クーポンを監視対象として登録する（発行はしない）。
    いま手動で出しているクーポンをボットに引き継がせるのに使う。"""
    info = client.get_coupon(code)  # 実在確認も兼ねる
    now = datetime.datetime.now(JST)
    state["current_coupon_code"] = code
    state["issued_at"] = now.isoformat()
    if not state.get("generation"):
        state["generation"] = 1
    save_state(state)
    log.info(
        f"[登録] 監視対象に設定: code={code} "
        f"利用数={info['avail_count']}/{info['issue_count']} 残={info['remaining']}"
    )
    log.info("次回チェック以降、このクーポンを監視し、使い切ったら自動で新しい50枚を発行します。")


def issue_new_coupon(client, config, state, reason):
    """新しい世代のクーポンを発行し、状態を更新する。couponCodeは楽天が自動採番。"""
    coupon_conf = config["coupon"]
    generation = state["generation"] + 1
    coupon_name = coupon_conf.get("coupon_name")

    log.info(f"[発行] 世代{generation} 理由: {reason}")
    result = client.issue_coupon(coupon_conf, coupon_name)
    issued_code = result["coupon_code"]
    pc_get_url = result.get("pc_get_url")

    now = datetime.datetime.now(JST)
    # 本日の再発行回数を更新
    if state.get("reissue_date") != today_str():
        state["reissue_date"] = today_str()
        state["reissue_count_today"] = 0
    state["reissue_count_today"] += 1

    state["generation"] = generation
    state["current_coupon_code"] = issued_code
    state["current_pc_get_url"] = pc_get_url
    state["issued_at"] = now.isoformat()
    state["history"].append(
        {
            "generation": generation,
            "coupon_code": issued_code,
            "pc_get_url": pc_get_url,
            "issued_at": now.isoformat(),
            "reason": reason,
        }
    )
    save_state(state)
    log.info(f"[発行完了] 世代{generation} code={issued_code}（本日{state['reissue_count_today']}回目）")
    log.info(f"[獲得URL] {pc_get_url}")
    notify(
        config,
        "【楽天クーポン】再発行しました",
        f"世代{generation}\nコード: {issued_code}\n獲得URL: {pc_get_url}\n理由: {reason}",
    )
    return issued_code


def within_reissue_guards(config, state):
    """歯止めチェック。発行してよければ (True, "") を返す。"""
    auto = config["automation"]
    if not auto.get("enabled", True):
        return False, "automation.enabled=false のため停止中"

    # 1日の上限
    if state.get("reissue_date") == today_str():
        if state.get("reissue_count_today", 0) >= auto.get("max_reissue_per_day", 5):
            return False, f"本日の再発行上限({auto.get('max_reissue_per_day')}回)に到達"

    # 連続発行防止
    interval = auto.get("min_reissue_interval_minutes", 30)
    if state.get("issued_at"):
        last = datetime.datetime.fromisoformat(state["issued_at"])
        elapsed_min = (datetime.datetime.now(JST) - last).total_seconds() / 60
        if elapsed_min < interval:
            return False, f"前回発行から{elapsed_min:.0f}分（最小間隔{interval}分）未満"

    return True, ""


# --------------------------------------------------------------------------
# 1回分のチェック
# --------------------------------------------------------------------------
def run_once(client, config, state, force_issue=False):
    auto = config["automation"]

    # 強制発行（動作確認用）
    if force_issue:
        issue_new_coupon(client, config, state, "手動強制発行(--force-issue)")
        return

    # まだ一度も発行していない → 初回発行
    if not state.get("current_coupon_code"):
        ok, why = within_reissue_guards(config, state)
        if ok:
            issue_new_coupon(client, config, state, "初回発行")
        else:
            log.info(f"[スキップ] 初回発行を見送り: {why}")
        return

    # 現行クーポンの状態を取得
    code = state["current_coupon_code"]
    try:
        info = client.get_coupon(code)
    except RakutenApiError as e:
        log.error(f"[取得エラー] coupon.get 失敗: {e}")
        if e.status_code in (401, 403):
            notify(config, "【楽天クーポン】認証エラー",
                   "coupon.get が認証エラーを返しました。ライセンスキーの失効(90日)を確認してください。")
        return

    log.info(
        f"[監視] code={code} 利用数={info['avail_count']}/{info['issue_count']} "
        f"残={info['remaining']} status={info['coupon_status']}"
    )

    used_up = False
    reason = ""
    threshold = auto.get("reissue_threshold", 0)
    if info["remaining"] is not None and info["remaining"] <= threshold:
        used_up, reason = True, f"残{info['remaining']}枚（閾値{threshold}）で使い切り"
    elif info["is_finished"]:
        used_up, reason = True, "クーポンが終了/期限切れ"

    if not used_up:
        return

    # 再発行の歯止め
    ok, why = within_reissue_guards(config, state)
    if not ok:
        log.info(f"[スキップ] 使い切りだが再発行を見送り: {why}")
        return

    issue_new_coupon(client, config, state, reason)


# --------------------------------------------------------------------------
# エントリポイント
# --------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="楽天クーポン自動発行ボット")
    parser.add_argument("--once", action="store_true", help="1回だけチェックして終了")
    parser.add_argument("--loop", type=int, metavar="SEC", help="指定秒ごとに常駐チェック")
    parser.add_argument("--force-issue", action="store_true", help="状態に関わらず1回強制発行（テスト用）")
    parser.add_argument("--set-current", metavar="CODE", help="既存クーポンを監視対象として登録（発行しない）")
    args = parser.parse_args()

    config = load_config()
    auth = config["auth"]
    client = RakutenCouponClient(auth["service_secret"], auth["license_key"])

    if args.set_current:
        state = load_state()
        set_current_coupon(client, state, args.set_current)
        return

    if args.loop:
        log.info(f"常駐モード開始（{args.loop}秒間隔）")
        while True:
            try:
                state = load_state()
                run_once(client, config, state, force_issue=False)
            except Exception as e:  # noqa: BLE001 常駐は落とさない
                log.exception(f"予期せぬエラー: {e}")
            time.sleep(args.loop)
    else:
        state = load_state()
        run_once(client, config, state, force_issue=args.force_issue)


if __name__ == "__main__":
    main()
