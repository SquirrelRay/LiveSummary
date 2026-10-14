# YouTube 第 1 步：平台判斷（platforms）、YouTube 觀看頁讀法（stream_info）、名詞清單按鈕的頻道查詢。
# 全部用假網頁、假回應，不連網。
import json
import threading
import time
import urllib.error
from pathlib import Path

import pytest
import test_介面冒煙 as 冒煙
from PySide6.QtWidgets import QApplication, QMenu

import glossary
import names_page
import platforms as pf
import stream_info as si

qapp, 環境 = 冒煙.qapp, 冒煙.環境          # fixture：和冒煙測試共用

頻道ID = "UCSJ4gkVC6NrvII8umztf0Ow"
影片 = "1-LpQekNa9g"


# ---------- 平台判斷 ----------
@pytest.mark.parametrize("網址, 期待", [
    # Twitch（行為不變）
    ("https://www.twitch.tv/abc_123", {"平台": pf.TWITCH, "頻道": "abc_123"}),
    ("twitch.tv/Abc123/", {"平台": pf.TWITCH, "頻道": "Abc123"}),
    ("https://m.twitch.tv/abc123?x=1", {"平台": pf.TWITCH, "頻道": "abc123"}),
    # YouTube 影片網址
    (f"https://www.youtube.com/watch?v={影片}", {"平台": pf.YOUTUBE, "影片": 影片}),
    (f"https://www.youtube.com/watch?v={影片}&t=1s", {"平台": pf.YOUTUBE, "影片": 影片}),
    (f"https://www.youtube.com/watch?feature=share&v={影片}", {"平台": pf.YOUTUBE, "影片": 影片}),
    (f"https://m.youtube.com/watch?v={影片}", {"平台": pf.YOUTUBE, "影片": 影片}),
    (f"youtube.com/watch?v={影片}", {"平台": pf.YOUTUBE, "影片": 影片}),
    (f"https://www.youtube.com/live/{影片}", {"平台": pf.YOUTUBE, "影片": 影片}),
    (f"https://www.youtube.com/live/{影片}?si=abc", {"平台": pf.YOUTUBE, "影片": 影片}),
    (f"https://youtu.be/{影片}", {"平台": pf.YOUTUBE, "影片": 影片}),
    (f"https://youtu.be/{影片}?t=30", {"平台": pf.YOUTUBE, "影片": 影片}),
    (f"https://www.youtube.com/embed/{影片}", {"平台": pf.YOUTUBE, "影片": 影片}),
    # YouTube 頻道網址
    ("https://www.youtube.com/@LofiGirl", {"平台": pf.YOUTUBE, "帳號": "@LofiGirl"}),
    ("https://www.youtube.com/@LofiGirl/live", {"平台": pf.YOUTUBE, "帳號": "@LofiGirl"}),
    ("https://m.youtube.com/@LofiGirl/live/", {"平台": pf.YOUTUBE, "帳號": "@LofiGirl"}),
    ("https://www.youtube.com/@%E3%81%95%E3%81%8F%E3%82%89/live", {"平台": pf.YOUTUBE, "帳號": "@さくら"}),
    (f"https://www.youtube.com/channel/{頻道ID}", {"平台": pf.YOUTUBE, "頻道ID": 頻道ID}),
    (f"https://www.youtube.com/channel/{頻道ID}/live", {"平台": pf.YOUTUBE, "頻道ID": 頻道ID}),
    (f"https://www.youtube.com/embed/live_stream?channel={頻道ID}", {"平台": pf.YOUTUBE, "頻道ID": 頻道ID}),
    ("https://www.youtube.com/c/LofiGirl", {"平台": pf.YOUTUBE, "名稱": "c/LofiGirl"}),
    ("https://www.youtube.com/c/LofiGirl/live", {"平台": pf.YOUTUBE, "名稱": "c/LofiGirl"}),
    ("https://www.youtube.com/user/LofiGirl/live", {"平台": pf.YOUTUBE, "名稱": "user/LofiGirl"}),
])
def test_支援的網址格式(網址, 期待):
    資 = pf.判斷(網址)
    assert 資.支援 and not 資.原因
    for 欄, 值 in 期待.items():
        assert getattr(資, 欄) == 值, 欄


@pytest.mark.parametrize("網址, 平台, 原因含", [
    ("", "", "Twitch 或 YouTube"),
    ("abc", "", "只支援"),
    ("https://example.com/live", "", "只支援"),
    ("https://www.twitch.tv/videos/123", pf.TWITCH, "VOD"),
    ("https://www.twitch.tv/abc/videos/123", pf.TWITCH, "VOD"),
    ("https://www.twitch.tv/directory", pf.TWITCH, "Twitch 頻道網址"),
    ("https://www.twitch.tv/abc/clip/x", pf.TWITCH, "Twitch 頻道網址"),
    (f"https://www.youtube.com/shorts/{影片}", pf.YOUTUBE, "Shorts"),
    (f"https://m.youtube.com/shorts/{影片}?feature=share", pf.YOUTUBE, "Shorts"),
    ("https://www.youtube.com/abc", pf.YOUTUBE, "YouTube 直播網址"),
    ("https://www.youtube.com/", pf.YOUTUBE, "YouTube 直播網址"),
    ("https://www.youtube.com/watch?v=短", pf.YOUTUBE, "YouTube 直播網址"),
    ("https://www.youtube.com/watch", pf.YOUTUBE, "YouTube 直播網址"),
    ("https://www.youtube.com/playlist?list=PL1", pf.YOUTUBE, "YouTube 直播網址"),
    ("https://www.youtube.com/@LofiGirl/videos", pf.YOUTUBE, "YouTube 直播網址"),
    ("https://www.youtube.com/channel/不是頻道ID/live", pf.YOUTUBE, "YouTube 直播網址"),
    ("https://youtu.be/", pf.YOUTUBE, "YouTube 直播網址"),
])
def test_不支援的網址有白話原因(網址, 平台, 原因含):
    資 = pf.判斷(網址)
    assert not 資.支援 and 資.平台 == 平台 and 原因含 in 資.原因


def test_同一個來源不同寫法_查詢鍵相同():
    assert pf.判斷("https://www.youtube.com/@LofiGirl").查詢鍵 == pf.判斷("youtube.com/@lofigirl/live").查詢鍵
    assert pf.判斷(f"https://youtu.be/{影片}").查詢鍵 == pf.判斷(f"https://www.youtube.com/watch?v={影片}&t=3").查詢鍵
    assert pf.判斷("https://www.twitch.tv/abc").查詢鍵 == ""


@pytest.mark.parametrize("網址, 頁", [
    (f"https://youtu.be/{影片}", f"https://www.youtube.com/watch?v={影片}"),
    (f"https://www.youtube.com/live/{影片}", f"https://www.youtube.com/watch?v={影片}"),
    ("https://www.youtube.com/@LofiGirl", "https://www.youtube.com/@LofiGirl/live"),
    ("https://www.youtube.com/@%E3%81%95/live", "https://www.youtube.com/@%E3%81%95/live"),
    (f"https://www.youtube.com/channel/{頻道ID}", f"https://www.youtube.com/channel/{頻道ID}/live"),
    ("https://www.youtube.com/user/abc/live", "https://www.youtube.com/user/abc/live"),
    ("https://www.twitch.tv/abc", ""),
    (f"https://www.youtube.com/shorts/{影片}", ""),
])
def test_要讀的觀看頁(網址, 頁):
    assert pf.觀看頁網址(pf.判斷(網址)) == 頁


# ---------- YouTube 觀看頁讀法 ----------
def 播放資料(**改):
    資料 = {
        "videoDetails": {"videoId": 影片, "channelId": 頻道ID, "author": "Lofi Girl", "title": "lofi 直播 🎃", "isLive": True},
        "microformat": {"playerMicroformatRenderer": {
            "category": "Music", "ownerProfileUrl": "http://www.youtube.com/@LofiGirl", "externalChannelId": 頻道ID,
            "liveBroadcastDetails": {"isLiveNow": True, "startTimestamp": "2026-10-01T17:00:26+00:00"}}},
    }
    資料.update(改)
    return 資料


def 頁(播放=None, 初始=None, 額外=""):
    """假的觀看頁：和真的一樣是 var 名稱 = {…}; 後面接別的程式碼。"""
    文 = "<html><head>" + 額外 + "</head><body><script>"
    if 播放 is not None:
        文 += "var ytInitialPlayerResponse = " + json.dumps(播放, ensure_ascii=False) + ";var meta = document.x;"
    文 += "</script><script>"
    if 初始 is not None:
        文 += "var ytInitialData = " + json.dumps(初始, ensure_ascii=False) + ";</script>"
    return 文 + "</body></html>"


def 假取得(回應們):
    """回應們：{網址: 字串 或 例外}；沒列到的網址丟 OSError。記錄每次呼叫的網址與逾時。"""
    呼叫 = []

    def 取得(網址, 資料=None, 標頭=None, 逾時=None):
        呼叫.append(網址)
        回 = 回應們.get(網址, OSError("沒有設定假回應"))
        if isinstance(回, BaseException):
            raise 回
        return 回.encode("utf-8")

    取得.呼叫 = 呼叫
    return 取得


def test_觀看頁一次拿齊():
    取得 = 假取得({f"https://www.youtube.com/watch?v={影片}": 頁(播放資料())})
    資訊, 原因 = si.查YouTube詳細(f"https://youtu.be/{影片}", 取得)
    assert 原因 == ""
    assert 資訊 == {"頻道ID": 頻道ID, "直播主": "Lofi Girl", "帳號": "@LofiGirl", "標題": "lofi 直播 🎃", "分類": "Music",
                  "開播": 1790874026.0, "直播中": True, "影片ID": 影片, "來源": "YouTube網頁",
                  "狀態": "", "原因": "", "預定開始": None, "即將開始": False, "直播內容": None, "聊天室": None}
    assert 取得.呼叫 == [f"https://www.youtube.com/watch?v={影片}"]      # 影片網址只讀一頁


def test_頻道沒在直播_只有頻道頁_拿得到頻道資訊_其他是不知道():
    初始 = {"metadata": {"channelMetadataRenderer": {"externalId": 頻道ID, "title": "Lofi Girl",
                                                     "vanityChannelUrl": "http://www.youtube.com/@LofiGirl"}}}
    取得 = 假取得({"https://www.youtube.com/@LofiGirl/live": 頁(初始=初始)})
    資訊 = si.查YouTube("https://www.youtube.com/@LofiGirl", 取得)
    assert 資訊["頻道ID"] == 頻道ID and 資訊["直播主"] == "Lofi Girl" and 資訊["帳號"] == "@LofiGirl"
    assert 資訊["開播"] is None and 資訊["直播中"] is None and 資訊["標題"] == "" and 資訊["分類"] == ""


def test_頻道網址的頁面缺開播時間_再讀一次影片觀看頁補齊():
    缺 = 播放資料(microformat={"microformatDataRenderer": {"category": "Music"}})
    取得 = 假取得({f"https://www.youtube.com/channel/{頻道ID}/live": 頁(缺),
                f"https://www.youtube.com/watch?v={影片}": 頁(播放資料())})
    資訊 = si.查YouTube(f"https://www.youtube.com/channel/{頻道ID}/live", 取得)
    assert 資訊["開播"] == 1790874026.0 and 資訊["帳號"] == "@LofiGirl" and 資訊["分類"] == "Music"
    assert len(取得.呼叫) == 2


def test_補讀失敗_保留第一頁讀到的():
    缺 = 播放資料(microformat={"microformatDataRenderer": {"category": "Music"}})
    取得 = 假取得({"https://www.youtube.com/@LofiGirl/live": 頁(缺)})
    資訊 = si.查YouTube("https://www.youtube.com/@LofiGirl/live", 取得)
    assert 資訊["頻道ID"] == 頻道ID and 資訊["開播"] is None and 資訊["分類"] == "Music"
    assert 資訊["帳號"] == "@LofiGirl"          # 頁面沒有 @帳號時用網址上的


def test_只有_canonical_連結也看得出頻道():
    取得 = 假取得({f"https://www.youtube.com/watch?v={影片}":
                頁(額外=f'<link rel="canonical" href="https://www.youtube.com/channel/{頻道ID}">')})
    資訊 = si.查YouTube(f"https://www.youtube.com/watch?v={影片}", 取得)
    assert 資訊["頻道ID"] == 頻道ID and 資訊["直播主"] == "" and 資訊["開播"] is None


@pytest.mark.parametrize("內容", [
    "",                                                          # 空頁
    "<html>同意 Cookie 的頁面</html>",                          # 沒有任何資料
    "var ytInitialPlayerResponse = {壞掉的 JSON;",               # JSON 讀不懂
    頁({"videoDetails": ["不是", "dict"], "microformat": 3}),    # 型別不對
    頁({"videoDetails": {"channelId": "不是頻道ID"}}),          # 頻道 ID 格式不對
])
def test_格式變了_回傳不知道不出錯(內容):
    取得 = 假取得({f"https://www.youtube.com/watch?v={影片}": 內容})
    assert si.查YouTube詳細(f"https://youtu.be/{影片}", 取得) == (None, "格式")


def test_欄位缺或型別怪_那一項是不知道():
    播放 = 播放資料(videoDetails={"channelId": 頻道ID, "author": 123, "isLive": "yes"})
    播放["microformat"]["playerMicroformatRenderer"]["liveBroadcastDetails"] = {"startTimestamp": "看不懂", "isLiveNow": "?"}
    取得 = 假取得({f"https://www.youtube.com/watch?v={影片}": 頁(播放)})
    資訊 = si.查YouTube(f"https://youtu.be/{影片}", 取得)
    assert 資訊["頻道ID"] == 頻道ID and 資訊["直播主"] == "" and 資訊["開播"] is None and 資訊["直播中"] is None


@pytest.mark.parametrize("種類, 原因", [("OSError", "連線"), ("逾時", "連線"), (404, "找不到"), (500, "連線")])
def test_連線失敗_回傳不知道不出錯(種類, 原因):
    例外 = {"OSError": OSError("連不上"), "逾時": TimeoutError()}.get(種類) or urllib.error.HTTPError("u", 種類, "錯誤", {}, None)
    取得 = 假取得({"https://www.youtube.com/@abc/live": 例外})
    assert si.查YouTube詳細("https://www.youtube.com/@abc", 取得) == (None, 原因)


@pytest.mark.parametrize("網址", ["https://www.twitch.tv/abc", f"https://www.youtube.com/shorts/{影片}", "", "abc"])
def test_不是支援的YouTube網址_不連網(網址):
    取得 = 假取得({})
    assert si.查YouTube詳細(網址, 取得) == (None, "網址")
    assert 取得.呼叫 == []


def test_Twitch_查詢不受影響():
    """Twitch 的 查詢() 仍然只走 GQL → 網頁，不碰 YouTube。"""
    取得 = 假取得({})
    assert si.查詢("abc", 取得) is None
    assert all("youtube" not in u for u in 取得.呼叫)


# ---------- 名詞清單按鈕 ----------
選單們 = []


def _名詞動作(台):
    m = QMenu()
    台.膠囊.填選單(m)
    選單們.append(m)
    return next(a for a in m.actions() if a.text().startswith("名詞清單"))


def 等到(條件, 秒=3):
    結束 = time.time() + 秒
    while time.time() < 結束:
        QApplication.processEvents()
        if 條件():
            return True
        time.sleep(0.01)
    return False


@pytest.fixture
def 暫存詞庫(monkeypatch, tmp_path):
    monkeypatch.setattr(glossary, "資料夾", str(tmp_path / "詞庫"))
    return tmp_path / "詞庫"


def 假查(結果們, 放行=None):
    """結果們：{查詢鍵: (資訊, 原因)}。放行：threading.Event，設定之前查詢一直卡著（模擬查詢中）。"""
    次數 = []

    def 查(資):
        次數.append(資.查詢鍵)
        if 放行 is not None:
            放行.wait(5)
        return 結果們.get(資.查詢鍵, (None, "找不到"))

    查.次數 = 次數
    return 查


Lofi = {"頻道ID": 頻道ID, "直播主": "Lofi Girl", "帳號": "@LofiGirl", "標題": "", "分類": "", "開播": None,
        "直播中": True, "影片ID": 影片, "來源": "YouTube網頁"}


def test_YouTube網址_查詢中_查到_按鈕可用並打開YT頻道ID的詞庫(環境, 暫存詞庫, 不查YouTube, monkeypatch):
    台 = 環境["台"]
    啟 = 台.啟動面板
    放行 = threading.Event()
    查 = 假查({"@lofigirl": (Lofi, ""), "v:" + 影片: (Lofi, "")}, 放行)
    monkeypatch.setattr(不查YouTube, "_查", 查)
    啟.網址框.setText("https://www.youtube.com/@LofiGirl/live")
    assert not 啟.名詞鈕.isEnabled() and 啟.名詞原因.text() == "查詢頻道中…"
    a = _名詞動作(台)
    assert not a.isEnabled() and "查詢頻道中" in a.text()
    放行.set()
    assert 等到(啟.名詞鈕.isEnabled)            # 查完送出訊號，按鈕自己更新
    assert 啟.名詞原因.text() == "直播主：Lofi Girl（@LofiGirl）"
    assert _名詞動作(台).isEnabled()
    台.名詞清單目標()                            # 再判斷一次不會重查
    assert 查.次數.count("@lofigirl") == 1

    啟.名詞鈕.click()
    框 = 台.名詞清單框
    assert 框.詞庫.直播主 == f"YT_{頻道ID}" and 框.詞庫.路徑.endswith(f"YT_{頻道ID}.txt")
    monkeypatch.setattr(names_page, "用記事本打開", lambda 路徑: None)
    框.打開記事本()
    開頭 = Path(框.詞庫.路徑).read_text(encoding="utf-8").splitlines()[0]
    assert "Lofi Girl" in 開頭 and "@LofiGirl" in 開頭 and 頻道ID in 開頭
    框.close()

    啟.網址框.setText(f"https://youtu.be/{影片}")          # 換網址格式：同一個頻道、同一份詞庫
    assert 等到(啟.名詞鈕.isEnabled) and "Lofi Girl" in 啟.名詞原因.text()
    啟.名詞鈕.click()
    assert 台.名詞清單框.詞庫.直播主 == f"YT_{頻道ID}"
    台.名詞清單框.close()


@pytest.mark.parametrize("原因, 字", [("找不到", "查不到這個 YouTube 頻道"), ("連線", "連不上 YouTube"),
                                      ("格式", "看不出是哪個頻道")])
def test_YouTube網址_查不到_按鈕停用並寫白話原因(環境, 不查YouTube, monkeypatch, 原因, 字):
    台 = 環境["台"]
    啟 = 台.啟動面板
    monkeypatch.setattr(不查YouTube, "_查", 假查({"@nobody": (None, 原因)}))
    啟.網址框.setText("https://www.youtube.com/@nobody/live")
    assert 等到(lambda: 啟.名詞原因.text() != "查詢頻道中…")
    assert not 啟.名詞鈕.isEnabled() and 字 in 啟.名詞原因.text()
    a = _名詞動作(台)
    assert not a.isEnabled() and 字 in a.text()
    for 文 in (啟.名詞原因.text(), a.text()):
        assert "config" not in 文 and ".json" not in 文 and "詞庫/" not in 文


def test_查不到過一陣子再改網址會重查(不查YouTube, monkeypatch):
    查 = 假查({})
    monkeypatch.setattr(不查YouTube, "_查", 查)
    assert names_page.頻道("https://www.youtube.com/@nobody") == (None, names_page.查詢中)
    assert 等到(lambda: names_page.頻道("https://www.youtube.com/@nobody")[1] != names_page.查詢中)
    names_page.頻道("https://www.youtube.com/@nobody")
    assert 查.次數.count("@nobody") == 1                     # 剛查不到：不重查（只算這個網址；別的測試留下的面板可能查自己的網址）
    monkeypatch.setattr(names_page, "重查秒", 0)
    names_page.頻道("https://www.youtube.com/@nobody")
    assert 等到(lambda: 查.次數.count("@nobody") >= 2)


def test_查詢本身出錯也只是查不到(不查YouTube, monkeypatch):
    def 壞(資):
        raise RuntimeError("壞了")
    monkeypatch.setattr(不查YouTube, "_查", 壞)
    names_page.頻道("https://www.youtube.com/@x")
    assert 等到(lambda: names_page.頻道("https://www.youtube.com/@x")[0] is None
               and names_page.頻道("https://www.youtube.com/@x")[1] != names_page.查詢中)


def test_Shorts與不支援的YouTube網址_按鈕停用_開始被擋下(環境, 不查YouTube):
    台 = 環境["台"]
    啟 = 台.啟動面板
    啟.網址框.setText(f"https://www.youtube.com/shorts/{影片}")
    assert not 啟.名詞鈕.isEnabled() and "Shorts" in 啟.名詞原因.text()
    啟.開始()
    assert not 台.執行中() and "Shorts" in 啟.狀態字.text()
    啟.網址框.setText("https://www.youtube.com/playlist?list=PL1")
    啟.開始()
    assert not 台.執行中() and "YouTube 直播網址" in 啟.狀態字.text()


def test_Twitch網址不查YouTube(環境, 不查YouTube, monkeypatch):
    查 = 假查({})
    monkeypatch.setattr(不查YouTube, "_查", 查)
    啟 = 環境["台"].啟動面板
    啟.網址框.setText("https://www.twitch.tv/test_names_x")
    assert 啟.名詞鈕.isEnabled() and 啟.名詞原因.text() == "直播主：test_names_x"
    assert "test_names_x" not in str(查.次數)


def test_Twitch詞庫檔開頭照舊(暫存詞庫):
    庫 = glossary.詞庫("某主")
    assert 庫.標示 == "某主"
    庫.新增("艾倫", "エレン")
    assert Path(庫.路徑).read_text(encoding="utf-8").splitlines()[0] == "# 直播主專有名詞詞庫：某主"
