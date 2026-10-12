"""時間顯示（offscreen 介面）：直播時間／幾分鐘前切換、每分鐘更新、抓不到開播時間的退回、膠囊選單與設定框、舊 config.json。
共用介面冒煙測試的 fixture（假模型、假引擎、暫存設定檔）；直播時軸用假時鐘，不連網、不花 API。"""
import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
import test_介面冒煙 as 冒煙
from PySide6.QtWidgets import QMenu

import app
import config
import events
import stream_clock as sc

qapp, 環境 = 冒煙.qapp, 冒煙.環境
假引擎, 從啟動面板開始, 停止並等完, 等 = 冒煙.假引擎, 冒煙.從啟動面板開始, 冒煙.停止並等完, 冒煙.等


def 讀設定():
    with open(config.設定檔路徑, encoding="utf-8") as f:
        return json.load(f)


class 假鐘:
    def __init__(self, t=0.0):
        self.t = t

    def __call__(self):
        return self.t


@pytest.fixture
def 直播(環境, monkeypatch):
    """開始一場假直播，時軸用假時鐘：開播時刻 0、延遲 0 → 現在直播秒 = 鐘.t。"""
    台 = 環境["台"]
    鐘 = 假鐘(5025.0)
    monkeypatch.setattr(sc, "_目前", None)
    monkeypatch.setattr(sc, "_資訊", None)
    從啟動面板開始(台, monkeypatch, 假引擎())

    def 送直播資訊(有開播=True):
        軸 = sc.時軸(開播=0.0 if 有開播 else None, 時鐘=鐘, 延遲=0.0)
        if not 有開播:
            軸.開始(0.0)
        資訊 = {"直播主": "たいじ", "標題": "ラーメン屋経営", "遊戲": "Ramen Sim", "來源": "GQL"} if 有開播 else None
        sc.設定目前(軸, 資訊)
        events.送出("stream_info", 有開播=有開播, 開播=軸.開播, 延遲=0.0, 來源=(資訊 or {}).get("來源"),
                    直播主=(資訊 or {}).get("直播主", ""), 標題=(資訊 or {}).get("標題", ""), 遊戲=(資訊 or {}).get("遊戲", ""),
                    印出=None)
        assert 等(lambda: 台.直播資訊 is not None)
    yield 台, 鐘, 送直播資訊
    停止並等完(台)


def 送內容(加號=""):
    events.送出("transcript_line", 秒=5025.5, 時間字=f"{加號}1:23:45", 內容="稿的一句", 行=f"[{加號}1:23:45] 稿的一句")
    events.送出("chat_line", 秒=5025.0, 時間字=f"{加號}1:23:45", 使用者="u", 內容="留言", 編號=events.新留言編號())
    events.送出("minute_summary", 秒=5040, 摘要=f"[{加號}1:23:45] 分鐘摘要內容", 支線=[], 觀眾反應="")
    events.送出("topic_summary", 開始=f"{加號}1:20:00", 結束=f"{加號}1:24:00", 開始秒=4800.0, 結束秒=5040,
                內文="【話題標題】話題\n【摘要】話題摘要內容")


def 卡片字(頁):
    return [卡.字.text() for 卡 in 頁.卡們]


def 面板卡片字(台, 種類):
    return 卡片字(台.面板.面板們[種類].清單頁)


def test_切換時間顯示_摘要卡片當場更新_直播稿聊天室不變(直播):
    台, 鐘, 送直播資訊 = 直播
    for 種類 in ("分鐘摘要", "話題摘要", "直播稿", "聊天室"):
        台.面板.開關(種類, True)
    送直播資訊()
    送內容()
    assert 等(lambda: 面板卡片字(台, "分鐘摘要") and 面板卡片字(台, "話題摘要"))
    assert "1:23:45" in 面板卡片字(台, "分鐘摘要")[0]
    assert "1:20:00 – 1:24:00" in 面板卡片字(台, "話題摘要")[0]
    稿前, 聊前 = list(台.稿頁.條們), list(台.聊天頁.條們)

    鐘.t = 5040 + 180                          # 分鐘摘要（1:23:45）之後 3 分多鐘
    台.設時間顯示("ago")
    assert "3 分鐘前" in 面板卡片字(台, "分鐘摘要")[0] and "1:23:45" not in 面板卡片字(台, "分鐘摘要")[0]
    assert "7 分鐘前 – 3 分鐘前" in 面板卡片字(台, "話題摘要")[0]
    assert 讀設定()["time_display"] == "ago"   # 膠囊／程式切換會寫回
    assert 台.稿頁.條們 == 稿前 and 台.聊天頁.條們 == 聊前           # 直播稿與聊天室一律絕對時間
    assert "1:23:45" in 台.稿頁.條們[0] and "1:23:45" in 台.聊天頁.條們[0]

    台.設時間顯示("stream")
    assert "1:23:45" in 面板卡片字(台, "分鐘摘要")[0]


def test_幾分鐘前_每分鐘更新一次_分鐘沒變不重畫(直播, monkeypatch):
    台, 鐘, 送直播資訊 = 直播
    台.面板.開關("分鐘摘要", True)
    送直播資訊()
    台.設時間顯示("ago")
    送內容()
    assert 等(lambda: 面板卡片字(台, "分鐘摘要"))
    鐘.t = 89 * 60                              # 直播第 89 分整（1:29:00），距分鐘摘要 5 分多
    重畫次數 = []
    原 = 台.重畫摘要時間
    monkeypatch.setattr(台, "重畫摘要時間", lambda: (重畫次數.append(1), 原())[1])
    台._檢查分鐘()
    assert 重畫次數 == [1] and "5 分鐘前" in 面板卡片字(台, "分鐘摘要")[0]
    鐘.t += 30                                   # 同一分鐘內：不重畫
    台._檢查分鐘()
    assert 重畫次數 == [1]
    鐘.t += 30                                   # 跨到下一分鐘：重畫一次
    台._檢查分鐘()
    assert 重畫次數 == [1, 1] and "6 分鐘前" in 面板卡片字(台, "分鐘摘要")[0]


def test_看不到的頁面等出現時才重畫(qapp):
    頁 = app.卡片清單("提示")
    值 = {"字": "甲"}
    頁.加卡片(lambda: 值["字"])
    值["字"] = "乙"
    頁.重畫時間()                       # 還沒顯示：先記著
    assert 卡片字(頁) == ["甲"] and 頁._待重畫
    頁.show()
    qapp.processEvents()
    assert 卡片字(頁) == ["乙"]
    頁.close()


def test_抓不到開播時間_藥丸標黃_卡片顯示幾分鐘前_膠囊提示(直播):
    台, 鐘, 送直播資訊 = 直播
    台.面板.開關("分鐘摘要", True)
    assert 台.時間顯示 == "stream"
    送直播資訊(有開播=False)
    assert "抓不到開播時間" in 台.時間藥丸.text() and "#" in 台.時間藥丸.styleSheet()
    assert "抓不到開播時間" in 台.膠囊.提示泡.text()
    鐘.t = 5040 + 120
    送內容(加號="+")
    assert 等(lambda: 面板卡片字(台, "分鐘摘要"))
    assert "2 分鐘前" in 面板卡片字(台, "分鐘摘要")[0]           # 設定是 stream，也自動退回幾分鐘前
    assert "擷取時間 +1:23:45 · 抓不到開播時間" == 台.時間藥丸.text()
    assert "+1:23:45" in 台.稿頁.條們[0]
    選單 = QMenu()
    台.膠囊.填選單(選單)
    時 = next(a.menu() for a in 選單.actions() if a.text() == "時間顯示")
    assert any("抓不到開播時間" in a.text() for a in 時.actions())


def test_膠囊選單切換時間顯示_提示顯示直播資訊(直播):
    台, _, 送直播資訊 = 直播
    送直播資訊()
    提示 = 台.膠囊.提示文字()
    assert "直播主：たいじ" in 提示 and "標題：ラーメン屋経営" in 提示 and "分類：Ramen Sim" in 提示
    assert "直播主" not in 台.時間藥丸.text()                        # 不放狀態列
    選單 = QMenu()
    台.膠囊.填選單(選單)
    時 = next(a.menu() for a in 選單.actions() if a.text() == "時間顯示")
    項 = {a.text(): a for a in 時.actions()}
    assert 項["直播時間"].isChecked() and not 項["幾分鐘前"].isChecked()
    項["幾分鐘前"].trigger()
    assert 台.時間顯示 == "ago"
    assert 讀設定()["time_display"] == "ago"


def test_設定框_時間顯示儲存當場生效(環境):
    台 = 環境["台"]
    台.開設定框()
    頁 = 台.設定框.頁
    e = 頁.欄["time_display"]
    assert e.currentData() == "stream"
    e.setCurrentIndex(e.findData("ago"))
    頁.儲存()
    assert 台.時間顯示 == "ago"
    assert 讀設定()["time_display"] == "ago"
    台.設時間顯示("stream")                 # 膠囊切回：表單同步
    assert e.currentData() == "stream"
    台.設定框.close()


def test_舊config沒有time_display_不跳警告_用預設(tmp_path, monkeypatch):
    舊 = {k: v for k, v in config.出廠預設().items() if k != "time_display"}
    路徑 = tmp_path / "config.json"
    路徑.write_text(json.dumps(舊), encoding="utf-8")
    monkeypatch.setattr(config, "設定檔路徑", str(路徑))
    設定, 來源, 警告們 = config.載入設定()
    assert 警告們 == [] and 設定["time_display"] == "stream" and 來源["time_display"] == "內建預設"


def test_time_display_不合法值退回預設(tmp_path, monkeypatch):
    路徑 = tmp_path / "config.json"
    路徑.write_text(json.dumps({"time_display": "abc"}), encoding="utf-8")
    monkeypatch.setattr(config, "設定檔路徑", str(路徑))
    設定, _, 警告們 = config.載入設定()
    assert 設定["time_display"] == "stream" and any("time_display" in w for w in 警告們)
