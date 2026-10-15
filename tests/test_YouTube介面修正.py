"""YouTube 介面修正（2026-10-14 實測日テレNEWS 發現）：
1. 聊天室：從介面開始時 YouTube 聊天室的建立；直播關閉聊天室時說「沒有開放聊天室」（不當成失效、不說 YouTube 改版）；
   失效寫進 logs、聊天室面板也顯示；連上了但還沒有新留言時聊天室面板說「已連上」。
2. 時間藥丸的滑鼠提示：來源單獨一行（YouTube 觀看頁）、依片段時間戳對齊時寫這次實際的延遲；提示框在面板重新置頂後仍在最上層。
全部用假資料，不連網、不呼叫 API（提示框的前後順序要真的 Windows 視窗，另開一個程序測）。"""
import json
import os
import subprocess
import sys
import textwrap
import urllib.request

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
import test_YouTube聊天室 as 聊天
import test_時間顯示介面 as 時間

import first_run
import live_capture as lc
import live_topics as lt
import panel
import platforms
import stream_clock as sc
import stream_info as si
import yt_chat

專案 = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
qapp, 環境 = 時間.qapp, 時間.環境
等 = 時間.等
停止並等完 = 時間.停止並等完

影片 = "AkGgrkdXdcw"
頻道ID = "UCuTAXTexrhetbOe3zgskJBQ"
網址 = f"https://www.youtube.com/watch?v={影片}"
開播 = 1791921551.0           # 2026-10-14 03:59:11（台灣時間）


# ---------- 假的觀看頁（和真的一樣：ytInitialPlayerResponse ＋ ytInitialData 的 conversationBar） ----------
def 觀看頁(聊天列):
    播放 = {"playabilityStatus": {"status": "OK"},
          "videoDetails": {"videoId": 影片, "channelId": 頻道ID, "author": "日テレNEWS", "title": "朝ニュースライブ",
                           "isLive": True, "isLiveContent": True},
          "microformat": {"playerMicroformatRenderer": {
              "category": "News & Politics", "ownerProfileUrl": "http://www.youtube.com/@ntv_news",
              "liveBroadcastDetails": {"isLiveNow": True, "startTimestamp": "2026-10-13T19:59:11+00:00"}}}}
    初始 = {"contents": {"twoColumnWatchNextResults": {"conversationBar": 聊天列}}} if 聊天列 is not None else {}
    return ("<html><body><script>var ytInitialPlayerResponse = " + json.dumps(播放, ensure_ascii=False) + ";</script>"
            "<script>var ytInitialData = " + json.dumps(初始, ensure_ascii=False) + ";</script></body></html>")


開放 = {"liveChatRenderer": {"continuations": [{"reloadContinuationData": {"continuation": "x"}}]}}
關閉 = {"conversationBarRenderer": {"availabilityMessage": {"messageRenderer": {"text": {"runs": [
    {"text": "このライブ ストリームではチャットは無効です。"}]}}}}}


def test_觀看頁_看得出聊天室有沒有開():
    assert si.解析YouTube頁(觀看頁(開放))["聊天室"] == "開放"
    assert si.解析YouTube頁(觀看頁(關閉))["聊天室"] == "關閉"
    assert si.解析YouTube頁(觀看頁(None))["聊天室"] is None          # 看不出來（改版等）：不當成關閉
    資訊 = si.查YouTube直播(網址, lambda *a, **k: 觀看頁(關閉).encode("utf-8"))
    assert 資訊["聊天室"] == "關閉" and 資訊["開播"] == 開播


# ---------- 從介面（啟動面板）開始：和使用者同一條路 ----------
class 介面一場:
    """啟動面板貼上 YouTube 網址按開始 → app → 真的 live_topics.執行 → 真的 live_capture.live_session。
    假的只有：觀看頁內容、streamlink 開播檢查、ffmpeg、yt_chat.聊天室（記下有沒有被建立）、引擎（只做「開始擷取」那一步）。"""

    def __init__(self, 台, monkeypatch, 聊天列):
        self.台 = 台
        self.聊天室們 = []
        self.場們 = []
        self.膠囊提示 = []             # 膠囊旁跳過的提示 (文字, 錯誤)：這一場很快就結束，最後會換成「已結束」
        原本 = 台.膠囊.小提示
        monkeypatch.setattr(台.膠囊, "小提示", lambda 字, *a, **k: (self.膠囊提示.append((字, k.get("錯誤"))), 原本(字, *a, **k)))

        def 不准連網(*a, **k):
            raise OSError("測試不連網")
        monkeypatch.setattr(urllib.request, "urlopen", 不准連網)
        # 假觀看頁的開播時間是固定的 2026-10-14：真正的「現在」過了 24 小時就會被當成連續直播，這裡把「現在」固定成開播後 1 小時
        真的判斷 = sc.是連續直播
        monkeypatch.setattr(sc, "是連續直播", lambda 開, 現在=None: 真的判斷(開, 開播 + 3600))

        class 假背景查詢:              # 真的解析觀看頁（查YouTube直播），只是頁面內容是假的
            def __init__(self, 頻道, 取得=None, 查法=None):
                self.結果 = (查法 or si.查詢)(頻道, lambda *a, **k: 觀看頁(聊天列).encode("utf-8"), None)

            def 等(self, *a, **k):
                return self.結果

        外 = self

        class 假聊天室:
            def __init__(self, 聊天網址, 存檔路徑, *a, **k):
                self.網址, self.存檔路徑, self.收到, self.過濾 = 聊天網址, 存檔路徑, 0, 0
                self.開始了 = None
                外.聊天室們.append(self)

            def 開始(self, 起點, 時軸=None):
                self.開始了 = 時軸

            def 關閉(self):
                pass

        def 假引擎(行來源, *a, **k):        # 開始擷取：和 live_session.__iter__ 一樣在這時候開始聊天室
            外.場們.append(行來源)
            軸 = 行來源.時軸
            軸.開始(軸.時鐘())
            行來源.開始聊天室(軸)
            return 0

        monkeypatch.setattr(si, "背景查詢", 假背景查詢)
        monkeypatch.setattr(lc, "檢查直播", lambda 網址, 查詢=None: "worst")
        monkeypatch.setattr(lc, "找ffmpeg", lambda: "ffmpeg")
        monkeypatch.setattr(first_run, "預告", lambda *a: None)
        monkeypatch.setattr(yt_chat, "聊天室", 假聊天室)
        monkeypatch.setattr(lt, "引擎", 假引擎)
        monkeypatch.setattr(lc, "設定分段", lambda 秒: None)     # 分段長度是全域設定：不要留給其他測試
        monkeypatch.setattr(lt, "載入詞庫", lambda *a, **k: None)
        monkeypatch.setattr(lt, "開始查證", lambda *a, **k: None)
        monkeypatch.setattr(sc, "_目前", None)
        monkeypatch.setattr(sc, "_資訊", None)

    def 開始(self):
        啟 = self.台.啟動面板
        啟.網址框.setText(網址)
        啟.語言選.setCurrentIndex(啟.語言選.findData("auto"))
        啟.開始()
        assert 等(lambda: self.場們, 15), "沒有走到開始擷取"
        assert 等(lambda: not self.台.執行中(), 15)


def 聊天頁文字(台):
    return 台.聊天頁.瀏覽.toPlainText()


def 聊天面板紀錄(台):
    return [純 for _, _, 純 in 台.面板.紀錄們["聊天室"].項目們]


def test_介面開始_有聊天室_建立YouTube聊天室並開始(環境, monkeypatch):
    台 = 環境["台"]
    場 = 介面一場(台, monkeypatch, 開放)
    場.開始()
    assert len(場.聊天室們) == 1
    聊 = 場.聊天室們[0]
    assert 聊.網址 == 網址 and 聊.開始了 is 場.場們[0].時軸        # 和直播稿同一個時軸
    assert yt_chat.沒有聊天室訊息 not in 聊天頁文字(台)


def test_介面開始_直播關閉聊天室_主控台膠囊聊天室面板都說沒有開放聊天室(環境, monkeypatch):
    台 = 環境["台"]
    場 = 介面一場(台, monkeypatch, 關閉)
    場.開始()
    assert 場.聊天室們 == []                       # 不去抓（不會重試 4 次後誤報「YouTube 改版」）
    句 = "這場直播沒有開放聊天室，摘要和字幕照常。"
    assert 等(lambda: 句 in 聊天頁文字(台))                         # 主控台的聊天室分頁
    assert 句 in 聊天面板紀錄(台)                                   # 浮動的聊天室面板（開著或之後打開都看得到）
    assert 句 in 台.提示層.條們                                     # 主控台提示條
    assert (句, None) in 場.膠囊提示                                # 膠囊旁（黃框提醒，不是紅框錯誤）
    assert not any("改版" in 字 for 字, _ in 場.膠囊提示)


def test_介面開始_時間藥丸提示_來源與對齊方式各一行(環境, monkeypatch):
    台 = 環境["台"]
    場 = 介面一場(台, monkeypatch, 開放)
    場.開始()
    行們 = 台.時間藥丸.toolTip().split("\n")
    assert "來源：YouTube 觀看頁（公開資料）" in 行們
    assert "開播：2026-10-14 03:59:11" in 行們
    assert not any("已扣除約 20" in x for x in 行們)                 # 還沒對齊前不寫估計值
    # 收到第一個串流片段：依片段時間戳對齊 → 寫這次實際的串流延遲
    軸 = 場.場們[0].時軸
    lc.對齊YouTube(軸, 軸.時鐘() - 19.63)
    assert 等(lambda: "這次實際串流延遲約 19.6 秒" in 台.時間藥丸.toolTip())
    提示 = 台.時間藥丸.toolTip()
    assert "依 YouTube 串流片段的時間戳對齊" in 提示 and "已扣除" not in 提示
    assert "來源：YouTube 觀看頁（公開資料）" in 提示.split("\n")


def test_時間藥丸提示_讀不到時間戳才寫已扣除約20秒(環境, monkeypatch):
    台 = 環境["台"]
    場 = 介面一場(台, monkeypatch, 開放)
    場.開始()
    lc.對齊YouTube(場.場們[0].時軸, None)
    assert 等(lambda: "已扣除約 20 秒估計的串流延遲" in 台.時間藥丸.toolTip())
    assert "實際串流延遲" not in 台.時間藥丸.toolTip()


def test_Twitch時間藥丸提示_維持原樣(環境):
    import events
    台 = 環境["台"]
    events.送出("stream_info", 有開播=True, 連續=False, 開播=0.0, 延遲=11.0, 來源="GQL", 平台=platforms.TWITCH,
                直播主="x", 標題="t", 遊戲="g", 印出=None)
    assert 等(lambda: 台.直播資訊 is not None)
    import time
    開播字 = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(0.0))
    assert 台.時間藥丸.toolTip() == f"直播實際進行時間（{開播字} 開播，來源：Twitch 公開資料；已扣除約 11 秒串流延遲）"


def test_失效與已連上_聊天室面板都有一行_不算留言(環境):
    import events
    台 = 環境["台"]
    yt_chat.送狀態("已連上", yt_chat.已連上訊息(46))
    yt_chat.送狀態("失效", yt_chat.失效訊息, 提醒=True)
    assert 等(lambda: yt_chat.失效訊息 in 聊天頁文字(台))
    assert "已連上 YouTube 聊天室，等待新留言（連上前的 46 則舊留言不顯示）。" in 聊天頁文字(台)
    assert yt_chat.失效訊息 in 聊天面板紀錄(台) and 台.膠囊.提示泡.text() == yt_chat.失效訊息
    assert 台.計數["聊天室"] == 0                    # 狀態行不算留言數
    events.送出("chat_line", 秒=1.0, 時間字="0:01", 使用者="@a", 內容="こんにちは", 編號=1)
    assert 等(lambda: 台.計數["聊天室"] == 1)


# ---------- yt_chat：沒有聊天室、失效寫 logs、已連上 ----------
@pytest.fixture
def 事件們(monkeypatch):
    import events
    收到 = []
    monkeypatch.setattr(events, "接收者們", [lambda 種類, 內容: 收到.append((種類, 內容))])
    events.停止.clear()
    monkeypatch.setattr(yt_chat, "重試間隔秒", 0)
    monkeypatch.setattr(yt_chat, "讀取間隔秒", 0.02)
    monkeypatch.setattr(sc, "_目前", None)
    monkeypatch.setattr(sc, "_資訊", None)
    yield 收到
    events.停止.clear()


class 安靜下載:
    """直播關閉聊天室時的 yt-dlp：不報錯、不寫檔就結束（2026-10-14 實測 Sky News）。"""

    def __init__(self):
        self.次數 = 0

    def __call__(self, 網址, 資料夾, 停, 紀錄):
        self.次數 += 1


def 紀錄行們():
    if not os.path.exists(yt_chat.紀錄檔):
        return []
    with open(yt_chat.紀錄檔, encoding="utf-8") as f:
        return f.read().splitlines()


def test_ytdlp安靜結束_觀看頁說關閉_說沒有開放聊天室_不說改版(事件們):
    查過 = []
    下載 = 安靜下載()
    聊 = yt_chat.聊天室(網址, None, 下載=下載, 查頁=lambda u: 查過.append(u) or "關閉")
    聊.開始(聊天.起點, sc.時軸(開播=聊天.起點))
    聊.執行緒.join(5)
    assert not 聊.執行緒.is_alive()
    assert 下載.次數 == 1 and 查過 == [網址] and 聊.沒有聊天室 and not 聊.失效
    狀態 = [c for k, c in 事件們 if k == "chat_status"]
    assert [c["狀態"] for c in 狀態] == ["沒有聊天室"]
    assert 狀態[0]["說明"] == 狀態[0]["膠囊"] == 狀態[0]["印出"].strip() == "這場直播沒有開放聊天室，摘要和字幕照常。"
    assert not any("改版" in str(c) for _, c in 事件們)
    assert any("沒有開放聊天室" in x for x in 紀錄行們())


def test_ytdlp安靜結束_觀看頁看不出來_照失效流程_每次原因寫進logs(事件們):
    下載 = 安靜下載()
    聊 = yt_chat.聊天室(網址, None, 下載=下載, 查頁=lambda u: None)
    聊.開始(聊天.起點, sc.時軸(開播=聊天.起點))
    聊.執行緒.join(5)
    assert 下載.次數 == 1 + yt_chat.重試次數 and 聊.失效 and not 聊.沒有聊天室
    assert [c["狀態"] for k, c in 事件們 if k == "chat_status"] == ["失效"]
    行們 = 紀錄行們()
    每次 = [x for x in 行們 if "聊天室第" in x and "次沒有收到資料" in x]
    assert len(每次) == 1 + yt_chat.重試次數 and all("yt-dlp 沒有錯誤也沒有寫出聊天室資料" in x for x in 每次)
    assert yt_chat.失效訊息 in 行們[-1]


def test_ytdlp出錯_失效時錯誤原因寫進logs(事件們):
    下載 = 聊天.假下載([], 錯誤=RuntimeError("Unable to extract initial data"))
    聊 = yt_chat.聊天室(網址, None, 下載=下載)
    聊.開始(聊天.起點, sc.時軸(開播=聊天.起點))
    聊.執行緒.join(5)
    assert 聊.失效
    行們 = 紀錄行們()
    assert any("RuntimeError: Unable to extract initial data" in x for x in 行們)
    assert yt_chat.失效訊息 in 行們[-1]


def test_連上了_舊留言都過濾_聊天室面板說已連上與舊留言數(事件們):
    起點 = 聊天.起點
    下載 = 聊天.假下載([[聊天.文字(起點 - 300, "@a", "おはよう"), 聊天.文字(起點 - 60, "@b", "ニュース")]])
    聊 = yt_chat.聊天室(網址, None, 下載=下載)
    聊.開始(起點, sc.時軸(開播=起點))
    assert 等(lambda: any(k == "chat_status" for k, _ in 事件們))
    聊.關閉()
    聊.執行緒.join(5)
    狀態 = [c for k, c in 事件們 if k == "chat_status"]
    assert len(狀態) == 1 and 狀態[0]["狀態"] == "已連上" and "膠囊" not in 狀態[0]
    assert 狀態[0]["說明"] == "已連上 YouTube 聊天室，等待新留言（連上前的 2 則舊留言不顯示）。"
    assert not any(k == "chat_line" for k, _ in 事件們)


# ---------- 提示框在面板重新置頂後仍在最上層（真的 Windows 視窗，另開程序：測試程序用的是 offscreen） ----------
def test_主控台裝了提示置頂(環境):
    assert isinstance(環境["台"].提示置頂, panel.提示置頂)


前後順序腳本 = textwrap.dedent(r'''
    # 和使用者遇到的一樣：提示開著 → 面板重新置頂（開面板、切換置頂、膠囊移到面板上面…）→ 提示換內容
    # （滑到另一個藥丸、膠囊每秒更新）。Qt 重複使用開著的提示框、只換文字，不會重新排到最上面。
    import sys, time
    sys.path.insert(0, sys.argv[1])
    import overlay, panel
    from PySide6.QtWidgets import QApplication, QWidget, QToolTip
    from PySide6.QtCore import Qt, QPoint

    u = overlay.user32
    app = QApplication([])
    if sys.argv[2] == "1":
        過濾 = panel.提示置頂()
        app.installEventFilter(過濾)
    主 = QWidget(); 主.setAttribute(Qt.WA_AlwaysShowToolTips); 主.setGeometry(100, 100, 400, 300); 主.show()
    面 = QWidget(None, Qt.FramelessWindowHint | Qt.Tool); 面.setGeometry(150, 100, 300, 300); 面.show()
    面h = int(面.winId())
    u.SetWindowPos(面h, overlay.HWND_TOPMOST, 0, 0, 0, 0, overlay.SWP_旗標)

    def 等(秒=0.3):
        到 = time.time() + 秒
        while time.time() < 到:
            app.processEvents(); time.sleep(0.01)

    def 提示框():
        for _ in range(200):
            框們 = [w for w in QApplication.topLevelWidgets() if w.inherits("QTipLabel") and w.isVisible()]
            if 框們:
                return 框們[0]
            等(0.01)
        raise SystemExit("提示框沒有出現")

    def 在上面(a, b):
        h = overlay.上方視窗(b)
        for _ in range(5000):
            if not h:
                return False
            if h == a:
                return True
            h = overlay.上方視窗(h)
        return False

    等()
    主.activateWindow()
    QToolTip.showText(主.mapToGlobal(QPoint(20, 20)), "直播時間 1:00:00 的提示", 主)
    第一次 = 提示框(); 等()
    結果 = [在上面(int(第一次.winId()), 面h)]
    u.SetWindowPos(面h, overlay.HWND_TOPMOST, 0, 0, 0, 0, overlay.SWP_旗標)      # 面板重新置頂
    等()
    QToolTip.showText(主.mapToGlobal(QPoint(40, 40)), "膠囊每秒更新：直播時間 1:00:01", 主)
    第二次 = 提示框(); 等()
    結果.append(在上面(int(第二次.winId()), 面h))
    print("RESULT", *結果, "同一個提示框" if 第一次 is 第二次 else "新的提示框")
''')


def _前後順序(裝過濾, tmp_path):
    腳本 = tmp_path / "前後順序.py"
    腳本.write_text(前後順序腳本, encoding="utf-8")
    環 = dict(os.environ, QT_QPA_PLATFORM="windows", PYTHONIOENCODING="utf-8")
    出 = subprocess.run([sys.executable, str(腳本), 專案, "1" if 裝過濾 else "0"], capture_output=True, text=True,  # noqa: S603  自己寫的腳本
                       encoding="utf-8", timeout=30, env=環, check=False)
    行 = next((x for x in 出.stdout.splitlines() if x.startswith("RESULT")), None)
    assert 行, 出.stdout + 出.stderr
    return 行.split()[1:]


@pytest.mark.slow          # 真的 Windows 視窗＋兩個子程序：git hook 預設不跑，python scripts/check.py --all 才跑
@pytest.mark.skipif(sys.platform != "win32", reason="提示框的前後順序是 Windows 原生行為")
def test_提示框_面板重新置頂後_再顯示仍在面板上面(tmp_path):
    assert _前後順序(False, tmp_path) == ["True", "False", "同一個提示框"]     # 沒裝：換內容後被面板蓋住（重現問題）
    assert _前後順序(True, tmp_path) == ["True", "True", "同一個提示框"]       # 裝了：仍在最上層

