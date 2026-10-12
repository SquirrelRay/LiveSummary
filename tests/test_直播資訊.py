# 開播時間取得（stream_info）：全部用假的 GQL／網頁回應，不連網
import json
import threading
import time

import pytest

import events
import stream_info as si

開播字 = "2026-10-12T09:38:28Z"
開播秒 = 1791797908.0

GQL成功 = {"data": {"user": {"login": "taiji", "displayName": "たいじ", "stream": {
    "createdAt": 開播字, "title": "ラーメン屋経営", "game": {"displayName": "Japanese Ramen Simulator"}}}}}

網頁 = ('<html><head><meta property="og:description" content="ラーメン屋経営 | Streaming japanese ramen simulator for 8,490 viewers.">'
      '<script type="application/ld+json">{"@context":"http://schema.org","@graph":[{"@type":"ProfilePage",'
      '"mainEntity":{"@type":"Person","name":"たいじ"}},{"@type":"VideoObject","publication":'
      '{"@type":"BroadcastEvent","isLiveBroadcast":true,"startDate":"' + 開播字 + '"}}]}</script></head></html>')


def 假取得(gql=None, 頁=None):
    """gql／頁：回應內容（dict 或字串），或一個例外（呼叫時丟出）。記錄每次呼叫的網址。"""
    呼叫 = []

    def 取得(網址, 資料=None, 標頭=None, 逾時=si.逾時秒):
        呼叫.append(網址)
        回應 = gql if 網址 == si.GQL網址 else 頁
        if isinstance(回應, BaseException):
            raise 回應
        if 回應 is None:
            raise OSError("沒有設定假回應")
        return (json.dumps(回應) if isinstance(回應, dict) else 回應).encode()

    取得.呼叫 = 呼叫
    return 取得


def test_GQL成功_一次拿齊():
    取得 = 假取得(gql=GQL成功)
    結果 = si.查詢("taiji", 取得)
    assert 結果 == {"開播": 開播秒, "標題": "ラーメン屋経営", "遊戲": "Japanese Ramen Simulator", "直播主": "たいじ", "來源": "GQL"}
    assert 取得.呼叫 == [si.GQL網址]          # 成功就不抓網頁


def test_GQL請求內容():
    收到 = {}

    def 取得(網址, 資料=None, 標頭=None, 逾時=si.逾時秒):
        收到.update(網址=網址, 資料=json.loads(資料), 標頭=標頭, 逾時=逾時)
        return json.dumps(GQL成功).encode()

    si.查詢('a"b', 取得)
    assert 收到["標頭"]["Client-ID"] == si.網頁ClientID
    assert 'login:"a\\"b"' in 收到["資料"]["query"]          # 頻道名稱有跳脫，不會拼壞查詢
    assert 收到["逾時"] == 3


@pytest.mark.parametrize("壞", [
    {"data": {"user": {"displayName": "x", "stream": None}}},                       # 沒開播／欄位缺失
    {"data": {"user": {"displayName": "x", "stream": {"title": "t"}}}},             # 沒有 createdAt
    {"data": {"user": {"displayName": "x", "stream": {"createdAt": "不是時間"}}}},
    {"data": {"user": None}},
    {"errors": [{"message": "bad"}]},
])
def test_GQL欄位缺失_改走網頁備援(壞):
    取得 = 假取得(gql=壞, 頁=網頁)
    結果 = si.查詢("taiji", 取得)
    assert 結果["開播"] == 開播秒 and 結果["來源"] == "網頁"
    assert 結果["直播主"] == "たいじ" and 結果["標題"] == "ラーメン屋経営" and 結果["遊戲"] == "japanese ramen simulator"
    assert len(取得.呼叫) == 2


@pytest.mark.parametrize("例外", [TimeoutError("timed out"), TimeoutError(), OSError("連不上"), ValueError("壞 JSON")])
def test_GQL逾時或失敗_改走網頁備援(例外):
    結果 = si.查詢("taiji", 假取得(gql=例外, 頁=網頁))
    assert 結果["來源"] == "網頁" and 結果["開播"] == 開播秒


def test_網頁沒有標題也能用():
    頁 = 網頁.replace('<meta property="og:description" content="ラーメン屋経営 | Streaming japanese ramen simulator for 8,490 viewers.">', "")
    結果 = si.查詢("taiji", 假取得(gql=OSError(), 頁=頁))
    assert 結果["開播"] == 開播秒 and 結果["標題"] == "" and 結果["遊戲"] == ""


@pytest.mark.parametrize("頁", ["<html>沒有 ld+json</html>", TimeoutError("讀取逾時"), OSError("連不上")])
def test_兩者都失敗_回傳None(頁):
    assert si.查詢("taiji", 假取得(gql=OSError("GQL 掛了"), 頁=頁)) is None


def test_解析時間():
    assert si.解析時間("2026-10-12T09:38:28Z") == 開播秒
    assert si.解析時間("2026-10-12T09:38:28.500Z") == 開播秒 + 0.5
    assert si.解析時間(None) is None and si.解析時間("abc") is None


@pytest.fixture
def 乾淨停止():
    events.停止.clear()
    yield
    events.停止.clear()


def test_背景查詢_成功(乾淨停止):
    q = si.背景查詢("taiji", 假取得(gql=GQL成功))
    assert q.等()["來源"] == "GQL"


def test_背景查詢_按結束可中斷(乾淨停止):
    放行 = threading.Event()

    def 卡住(網址, 資料=None, 標頭=None, 逾時=si.逾時秒):
        放行.wait(5)              # 模擬網路卡住
        raise OSError("逾時")

    q = si.背景查詢("taiji", 卡住)
    threading.Timer(0.2, events.停止.set).start()
    開始 = time.monotonic()
    assert q.等(最久=5) is None
    assert time.monotonic() - 開始 < 1.5        # 按結束後馬上不等了
    放行.set()


def test_背景查詢_超過最久就放棄(乾淨停止):
    放行 = threading.Event()

    def 卡住(網址, 資料=None, 標頭=None, 逾時=si.逾時秒):
        放行.wait(5)
        raise OSError("逾時")

    開始 = time.monotonic()
    assert si.背景查詢("taiji", 卡住).等(最久=0.3) is None
    assert time.monotonic() - 開始 < 1.5
    放行.set()


def test_停止後不再試備援(乾淨停止):
    events.停止.set()
    取得 = 假取得(gql=GQL成功, 頁=網頁)
    assert si.查詢("taiji", 取得, events.停止) is None and 取得.呼叫 == []
