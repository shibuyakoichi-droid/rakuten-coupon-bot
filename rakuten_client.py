# -*- coding: utf-8 -*-
"""
RMS WEB SERVICE Coupon API クライアント（coupon.get / coupon.issue）

認証: HTTPヘッダ  Authorization: ESA Base64(serviceSecret:licenseKey)
レスポンス: XML（名前空間つきの場合があるためローカル名で照合する）
"""

import base64
import datetime
import xml.etree.ElementTree as ET

import requests

# --- エンドポイント（RMS WEB SERVICE 1.0） ---
# coupon.get / coupon.issue のドキュメント「1. Endpoint」で確認した正確なURL。
BASE = "https://api.rms.rakuten.co.jp/es/1.0/coupon"
ENDPOINT_GET = BASE + "/get"
ENDPOINT_ISSUE = BASE + "/issue"

JST = datetime.timezone(datetime.timedelta(hours=9))


class RakutenApiError(Exception):
    """API呼び出し・パース失敗を表す例外。status_code を保持する。"""

    def __init__(self, message, status_code=None, body=None):
        super().__init__(message)
        self.status_code = status_code
        self.body = body


def _local(tag):
    """名前空間つきタグ '{ns}name' から 'name' を取り出す。"""
    return tag.split("}", 1)[1] if "}" in tag else tag


def _find_text(root, name):
    """ツリー全体から、ローカル名が name の最初の要素のテキストを返す（無ければ None）。"""
    for el in root.iter():
        if _local(el.tag) == name:
            return (el.text or "").strip()
    return None


def _find_all(root, name):
    """ローカル名が name の全要素を返す。"""
    return [el for el in root.iter() if _local(el.tag) == name]


def _child_text(el, name):
    """要素 el の直接の子から、ローカル名が name のテキストを返す。"""
    for ch in el:
        if _local(ch.tag) == name:
            return (ch.text or "").strip()
    return None


class RakutenCouponClient:
    def __init__(self, service_secret, license_key, timeout=30):
        token = base64.b64encode(
            f"{service_secret}:{license_key}".encode("utf-8")
        ).decode("ascii")
        self._headers = {
            "Authorization": f"ESA {token}",
            "Content-Type": "application/xml; charset=UTF-8",
        }
        self.timeout = timeout

    # ------------------------------------------------------------------
    # coupon.get : クーポンコードを指定して現在の状態を取得（動作確認済み）
    # ------------------------------------------------------------------
    def get_coupon(self, coupon_code):
        """
        指定クーポンの状態を dict で返す。
        返り値のキー: coupon_code, coupon_name, issue_count, avail_count,
                     coupon_status, end_date, remaining, is_finished
        """
        resp = requests.get(
            ENDPOINT_GET,
            headers=self._headers,
            params={"couponCode": coupon_code},
            timeout=self.timeout,
        )
        if resp.status_code != 200:
            # AuthError等もここに来る（本文にXMLが入る）
            raise RakutenApiError(
                f"coupon.get 失敗 (HTTP {resp.status_code}): {resp.text[:300]}",
                status_code=resp.status_code,
                body=resp.text,
            )

        try:
            root = ET.fromstring(resp.content)
        except ET.ParseError as e:
            raise RakutenApiError(f"レスポンスXMLの解析に失敗: {e}", body=resp.text)

        if not _find_all(root, "coupon"):
            msg = _find_text(root, "message") or "coupon要素が見つかりません"
            raise RakutenApiError(f"coupon.get: {msg}", body=resp.text)

        def _int(name):
            v = _find_text(root, name)
            try:
                return int(v)
            except (TypeError, ValueError):
                return None

        issue_count = _int("issueCount")
        avail_count = _int("availCount")
        coupon_status = _int("couponStatus")
        end_date = _find_text(root, "couponEndDate")

        remaining = None
        if issue_count is not None and avail_count is not None:
            remaining = issue_count - avail_count

        is_finished = False
        if coupon_status == 6:  # 6:終了
            is_finished = True
        if end_date:
            try:
                dt = datetime.datetime.fromisoformat(end_date)
                if dt < datetime.datetime.now(JST):
                    is_finished = True
            except ValueError:
                pass

        return {
            "coupon_code": _find_text(root, "couponCode") or coupon_code,
            "coupon_name": _find_text(root, "couponName"),
            "issue_count": issue_count,
            "avail_count": avail_count,
            "coupon_status": coupon_status,
            "end_date": end_date,
            "remaining": remaining,
            "is_finished": is_finished,
        }

    def get_coupon_raw(self, coupon_code):
        """coupon.get の生レスポンス（XML文字列）をそのまま返す。設定内容の確認用。"""
        resp = requests.get(
            ENDPOINT_GET,
            headers=self._headers,
            params={"couponCode": coupon_code},
            timeout=self.timeout,
        )
        return resp.text

    # ------------------------------------------------------------------
    # coupon.issue : 新しいクーポンを発行（couponCodeは楽天が自動採番）
    # ------------------------------------------------------------------
    def issue_coupon(self, coupon_conf, coupon_name=None):
        """
        発行に成功したら {"coupon_code": ..., "pc_get_url": ...} を返す。
        couponCode と pcGetUrl は楽天がレスポンスで返す値。
        """
        xml_body = build_issue_xml(coupon_conf, coupon_name)
        resp = requests.post(
            ENDPOINT_ISSUE,
            headers=self._headers,
            data=xml_body.encode("utf-8"),
            timeout=self.timeout,
        )
        if resp.status_code != 200:
            raise RakutenApiError(
                f"coupon.issue 失敗 (HTTP {resp.status_code}): {resp.text[:300]}",
                status_code=resp.status_code,
                body=resp.text,
            )
        try:
            root = ET.fromstring(resp.content)
        except ET.ParseError as e:
            raise RakutenApiError(f"発行レスポンスの解析に失敗: {e}", body=resp.text)

        # systemStatusがOKでも <errors> が入る場合があるので、errorsの有無で判定する
        errors = _find_all(root, "error")
        if errors:
            details = [
                f"{_child_text(e, 'code')}: {_child_text(e, 'message')}" for e in errors
            ]
            raise RakutenApiError(
                "coupon.issue APIエラー: " + "; ".join(details),
                body=resp.text,
            )

        returned_code = _find_text(root, "couponCode")
        if not returned_code:
            raise RakutenApiError("発行応答にcouponCodeがありません", body=resp.text)

        return {"coupon_code": returned_code, "pc_get_url": _find_text(root, "pcGetUrl")}


def build_issue_xml(coupon_conf, coupon_name=None):
    """
    coupon.issue のリクエストXMLを組み立てる。

    構造: request > couponIssueRequest > coupon（ドキュメントで確認済み）
    ※couponCodeは送らない（楽天が自動採番）。
    ※couponStartDateは「現在の最短60分後〜最長30日後」。
    ※必須の各条件は「条件なし」で埋める（要素順はドキュメントの並び順に合わせる）。
    ※条件コード: RS003=利用金額 / RS004=利用個数。
    """
    now = datetime.datetime.now(JST)
    # 開始日時は「最短60分後〜最長30日後」の制約あり。
    # 設定値が小さくても over_term にならないよう、最低90分後を強制する。
    buffer_min = coupon_conf.get("start_buffer_minutes", 90) or 0
    buffer_min = max(90, int(buffer_min))
    start = now + datetime.timedelta(minutes=buffer_min)
    end = start + datetime.timedelta(days=coupon_conf.get("validity_days", 7))
    fmt = "%Y-%m-%dT%H:%M:%S+09:00"
    name = coupon_name or coupon_conf.get("coupon_name", "クーポン")

    # 対象商品（指定があれば）
    items_xml = ""
    urls = coupon_conf.get("target_item_urls") or []
    if urls:
        rows = "".join(f"<item><itemUrl>{u}</itemUrl></item>" for u in urls)
        items_xml = f"<items>{rows}</items>"

    # 利用条件（otherConditions）
    #   動作中クーポンの構成に合わせ、基本条件も明示的に入れる:
    #     RS001=0(PC) / RS001=1(モバイル) / RS002=99(通常&定期購入)
    #   その上で、金額(RS003) または 個数(RS004) の条件を追加する。
    #   RS003=利用金額(startValueに金額) / RS004=利用個数(startValueに個数)
    conditions = [
        ("RS001", "0"),   # デバイス: PC
        ("RS001", "1"),   # デバイス: モバイル
        ("RS002", "99"),  # 販売方法: 通常&定期購入
    ]
    condition_type = coupon_conf.get("condition_type", "quantity")
    if condition_type == "amount":
        conditions.append(("RS003", str(coupon_conf.get("min_purchase_amount", 3000))))
    else:
        conditions.append(("RS004", str(coupon_conf.get("min_purchase_count", 2))))

    other_conditions_xml = (
        "<otherConditions>"
        + "".join(
            f"<otherCondition><conditionTypeCode>{code}</conditionTypeCode>"
            f"<startValue>{value}</startValue></otherCondition>"
            for code, value in conditions
        )
        + "</otherConditions>"
    )

    # 必須の各条件（条件なしを指定）
    #   年齢: lowerBound/upperBound = 0（指定なし）
    #   居住地: prefectureCond = NONE（指定なし）
    age_range_xml = "<ageRangeCond><lowerBound>0</lowerBound><upperBound>0</upperBound></ageRangeCond>"
    multi_prefecture_xml = "<multiPrefectureCond><prefectureCond>NONE</prefectureCond></multiPrefectureCond>"

    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<request>
  <couponIssueRequest>
    <coupon>
      <couponName>{name}</couponName>
      <couponStartDate>{start.strftime(fmt)}</couponStartDate>
      <couponEndDate>{end.strftime(fmt)}</couponEndDate>
      <issueCount>{coupon_conf.get('issue_count', 50)}</issueCount>
      <itemType>{coupon_conf.get('item_type', 4)}</itemType>
      <discountType>{coupon_conf.get('discount_type', 1)}</discountType>
      <discountFactor>{coupon_conf.get('discount_factor', 100)}</discountFactor>
      <memberAvailMaxCount>{coupon_conf.get('member_avail_max_count', 1)}</memberAvailMaxCount>
      <purchaseHistoryCond><type>0</type></purchaseHistoryCond>
      <multiRankCond><rankCond>0</rankCond></multiRankCond>
      <genderCond>NONE</genderCond>
      {age_range_xml}
      <birthmonthCond>0</birthmonthCond>
      {multi_prefecture_xml}
      <combineFlag>{coupon_conf.get('combine_flag', 0)}</combineFlag>
      <displayFlag>{coupon_conf.get('display_flag', 0)}</displayFlag>
      {items_xml}
      {other_conditions_xml}
    </coupon>
  </couponIssueRequest>
</request>"""
    return xml
