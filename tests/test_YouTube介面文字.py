"""YouTube 第 5 步：介面文字兩個平台都適用、連續直播不當成出錯、沒有文字的 Super Chat 不送翻譯。
全部用假資料，不連網、不呼叫 API。"""
import ast
import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
import test_時間顯示介面 as 時間
from PySide6.QtWidgets import QMenu

import chat_translate as ct
import events
import launcher
import onboarding
import platforms
import yt_chat

專案 = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
qapp, 環境, 直播 = 時間.qapp, 時間.環境, 時間.直播
等 = 時間.等

# ---------- 掃描：一般使用者看得到的字串裡，不能只提 Twitch ----------
介面檔們 = ["app.py", "launcher.py", "onboarding.py", "names_page.py", "capsule.py", "settings_page.py", "glossary.py",
         "first_run.py", "panel.py", "ui_state.py", "language_state.py", "platforms.py", "live_capture.py", "live_topics.py"]
# 這些字串只提 Twitch 是對的：只在 Twitch 流程出現（Twitch 才有的資料來源名稱、Twitch 網址的錯誤原因、命令列說明）
只限Twitch = {
    "Twitch 公開資料",                                       # 開播時間來源（GQL）
    "Twitch 頻道網頁",                                       # 開播時間來源（頻道網頁備援）
    "這不是 Twitch 頻道網址（例如 https://www.twitch.tv/頻道名稱）",      # platforms：Twitch 網址不對
    "無法檢查直播，請確認網址正確（例如 https://www.twitch.tv/頻道名稱）。",   # live_capture：Twitch 流程的開播檢查
    "網址看起來不對，請確認是 Twitch 頻道網址。",                          # live_capture：Twitch 流程的開播檢查
    "Twitch 直播網址，例如 https://www.twitch.tv/頻道名稱",              # live_topics 命令列說明（開發者）
    "Twitch／YouTube",                                       # 平台名稱並列
}


def _字串們(檔):
    """檔案裡所有字串常數（不含 docstring 與註解）。"""
    with open(os.path.join(專案, 檔), encoding="utf-8") as f:
        樹 = ast.parse(f.read())
    文件字串 = set()
    for 節點 in ast.walk(樹):
        if isinstance(節點, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            首 = 節點.body[0] if 節點.body else None
            if isinstance(首, ast.Expr) and isinstance(首.value, ast.Constant) and isinstance(首.value.value, str):
                文件字串.add(id(首.value))
    f片段 = {id(v) for 節點 in ast.walk(樹) if isinstance(節點, ast.JoinedStr) for v in 節點.values}
    for 節點 in ast.walk(樹):
        if isinstance(節點, ast.JoinedStr):      # f-string 合成一整句（{…} 先用 {} 代替）
            yield 節點.lineno, "".join(v.value if isinstance(v, ast.Constant) else "{}" for v in 節點.values)
        elif isinstance(節點, ast.Constant) and isinstance(節點.value, str) and id(節點) not in 文件字串 | f片段:
            yield 節點.lineno, 節點.value


def test_介面文字沒有只提Twitch的遺漏():
    漏 = []
    for 檔 in 介面檔們:
        for 行, 字 in _字串們(檔):
            if "twitch" in 字.lower() and "youtube" not in 字.lower() and 字 not in 只限Twitch:
                if not any("一" <= c <= "鿿" for c in 字):
                    continue                      # 網域、參數名這類沒有中文的不是給人看的字
                if 字.startswith("https://") and " " not in 字:
                    continue                      # 單純的網址範例（句子裡會同時列兩個平台，另有測試）
                漏.append(f"{檔}:{行}  {字[:60]}")
    assert not 漏, "介面文字只提 Twitch（要補上 YouTube，或確認只在 Twitch 流程出現再加進 只限Twitch）：\n" + "\n".join(漏)


def test_掃描真的掃得到_只提Twitch的字會被抓出來(tmp_path):
    """保護掃描本身：假檔案裡的文字被判為遺漏，兩平台都提的不算。"""
    假 = tmp_path / "假.py"
    假.write_text('a = "請貼上 Twitch 直播網址"\nb = "請貼上 Twitch 或 YouTube 直播網址"\n', encoding="utf-8")
    樹 = ast.parse(假.read_text(encoding="utf-8"))
    字們 = [n.value for n in ast.walk(樹) if isinstance(n, ast.Constant)]
    漏 = [z for z in 字們 if "twitch" in z.lower() and "youtube" not in z.lower()]
    assert 漏 == ["請貼上 Twitch 直播網址"]


# ---------- 網址欄提示文字 ----------
def test_網址欄提示_兩個平台都提_夠短放得下():
    assert "Twitch" in platforms.網址提示 and "YouTube" in platforms.網址提示
    assert len(platforms.網址提示) <= 30                    # 提示文字要短（150% 縮放也放得下）；範例放滑鼠提示
    for 範例 in (platforms.網址範例, platforms.網址範例YT):
        assert 範例 in platforms.網址欄提示 and 範例 in platforms.請先輸入網址


def test_啟動面板與主控台的網址欄_提示與滑鼠提示(環境):
    台 = 環境["台"]
    for 框 in (台.網址框, 台.啟動面板.網址框):
        assert 框.placeholderText() == platforms.網址提示
        assert "youtube.com/watch?v=" in 框.toolTip() and "twitch.tv/" in 框.toolTip()


def test_網址空白按開始_錯誤訊息列出兩種網址(環境):
    啟 = 環境["台"].啟動面板
    啟.網址框.setText("")
    啟.開始()
    assert 啟.狀態字.text() == platforms.請先輸入網址
    assert "Twitch" in 啟.狀態字.text() and "YouTube" in 啟.狀態字.text()


def test_首次引導第3頁_說明兩個平台():
    說明 = onboarding.頁們[2]["說明"]
    assert "Twitch" in 說明 and "YouTube" in 說明


def test_名詞清單的網址錯誤_範例含YouTube():
    import names_page
    名, 原因 = names_page.頻道("abc")
    assert 名 is None and "YouTube" in 原因 and "twitch.tv" in 原因
    assert launcher.platforms is platforms


# ---------- 時間來源與連續直播 ----------
def _送(內容):
    events.送出("stream_info", **內容)


基本 = {"有開播": True, "連續": False, "開播": 0.0, "延遲": 20.0, "來源": "YouTube網頁", "直播主": "x", "標題": "t",
      "遊戲": "Music", "印出": None}


def test_時間來源_依平台顯示_YouTube不寫成Twitch(直播):
    台, _, _ = 直播
    _送(基本)
    assert 等(lambda: 台.直播資訊 and 台.直播資訊.get("來源") == "YouTube網頁")
    提示 = 台.時間藥丸.toolTip()
    assert "YouTube" in 提示 and "Twitch" not in 提示
    _送({**基本, "來源": "GQL"})
    assert 等(lambda: "Twitch 公開資料" in 台.時間藥丸.toolTip())


連續說明 = "這是連續播出的直播（2020-01-01 00:00 開播，已超過 24 小時），時間改為從開始擷取起算（前面加 +），直播稿和聊天室從同一個時間點算起。"


def test_連續直播_膠囊旁顯示白話說明_不說抓不到(直播):
    台, _, _ = 直播
    _送({**基本, "有開播": False, "連續": True, "開播": None, "印出": 連續說明})
    assert 等(lambda: 台.直播資訊 and 台.直播資訊.get("連續"))
    泡 = 台.膠囊.提示泡.text().replace("\n", "")
    assert "連續播出的直播" in 泡 and "超過 24 小時" in 泡 and "抓不到" not in 泡
    assert "連續直播" in 台.時間藥丸.text() and "抓不到" not in 台.時間藥丸.text()
    assert "24 小時" in 台.時間藥丸.toolTip() and "抓不到" not in 台.時間藥丸.toolTip()
    assert 台._時間藥丸字("+1:00") == "擷取時間 +1:00 · 連續直播"
    assert 台.用幾分鐘前()                       # 時間從開始擷取起算，摘要卡片照樣顯示幾分鐘前
    選單 = QMenu()
    台.膠囊.填選單(選單)
    時 = next(a.menu() for a in 選單.actions() if a.text() == "時間顯示")
    字們 = [a.text() for a in 時.actions()]
    assert any("連續直播" in z for z in 字們) and not any("抓不到" in z for z in 字們)


def test_真的抓不到開播時間_仍然是原本的提示(直播):
    台, _, 送直播資訊 = 直播
    送直播資訊(有開播=False)
    assert "抓不到開播時間" in 台.膠囊.提示泡.text()
    assert "抓不到開播時間" in 台.時間藥丸.text() and "連續" not in 台.時間藥丸.text()


# ---------- Super Chat 沒有文字：不送翻譯，直接顯示原文 ----------
@pytest.mark.parametrize("內容", ["【SC】（沒有留言）", "【SC】貼圖", " 【SC】貼圖 "])
def test_沒有文字的SC不送翻譯(內容):
    assert ct.跳過原因(內容) == "SC 沒有文字"
    for 語言 in ("ja", "en", "ko"):
        assert not ct.要翻譯(內容, 語言)


@pytest.mark.parametrize("內容", ["【SC】ありがとう、楽しいです", "【SC】Thank you for the stream"])
def test_有文字的SC照常翻譯(內容):
    assert ct.跳過原因(內容) is None
    assert ct.要翻譯(內容, "ja" if "あ" in 內容 else "en")


def test_SC固定字樣和yt_chat補的字一致():
    """yt_chat 補的兩個字樣一定在不翻名單裡（改了其中一邊，這裡會失敗）。"""
    def 行(種類, 訊息):
        項目 = {"timestampUsec": "1000000", "authorName": {"simpleText": "u"}}
        if 訊息 is not None:
            項目["message"] = {"runs": [{"text": 訊息}]}
        return json.dumps({"replayChatItemAction": {"actions": [{"addChatItemAction": {"item": {種類: 項目}}}]}})
    for 種類 in ("liveChatPaidMessageRenderer", "liveChatPaidStickerRenderer"):
        結果 = yt_chat.解析動作(行(種類, None))
        assert 結果[0] == "留言" and 結果[3] in ct.SC無文字們
        assert ct.跳過原因(結果[3]) == "SC 沒有文字"
    有字 = yt_chat.解析動作(行("liveChatPaidMessageRenderer", "ありがとう"))
    assert 有字[3] == "【SC】ありがとう" and ct.跳過原因(有字[3]) is None
