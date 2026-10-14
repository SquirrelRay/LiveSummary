# YouTube 聊天室（yt_chat）：全部用假的 yt-dlp 回應（假 JSON 行），不連網。
import json
import os
import threading
import time
from types import SimpleNamespace

import pytest

import chat_capture
import chat_translate
import events
import live_capture as lc
import platforms
import stream_clock as sc
import yt_chat

起點 = 2_000_000_000.0      # 開始擷取的時刻（假的 epoch 秒）


@pytest.fixture
def 事件們(monkeypatch):
    收到 = []
    monkeypatch.setattr(events, "接收者們", [lambda 種類, 內容: 收到.append((種類, 內容))])
    events.停止.clear()
    yield 收到
    events.停止.clear()


@pytest.fixture(autouse=True)
def 快一點(monkeypatch):
    monkeypatch.setattr(yt_chat, "重試間隔秒", 0)
    monkeypatch.setattr(yt_chat, "讀取間隔秒", 0.02)
    monkeypatch.setattr(sc, "_目前", None)
    monkeypatch.setattr(sc, "_資訊", None)


# ---------- 假 JSON（yt-dlp 寫進 .live_chat.json.part 的格式：每行一個 replayChatItemAction） ----------
def _包(動作):
    return json.dumps({"replayChatItemAction": {"actions": [動作], "videoOffsetTimeMsec": "0", "isLive": True}},
                      ensure_ascii=False)


def _項目(種類, 發送, 名, **其他):
    r = {"authorName": {"simpleText": 名}, "timestampUsec": str(int(發送 * 1e6)), **其他}
    return _包({"clickTrackingParams": "x", "addChatItemAction": {"item": {種類: r}, "clientId": "c"}})


def 文字(發送, 名, *runs):
    runs = [{"text": r} if isinstance(r, str) else r for r in runs]
    return _項目("liveChatTextMessageRenderer", 發送, 名, message={"runs": runs})


def 表情(字):
    return {"emoji": {"emojiId": 字, "shortcuts": [":x:"], "image": {"thumbnails": []}}}


def 自訂表情():
    return {"emoji": {"emojiId": "UCabcdefghijklmnopqrstuv/AbCdEfGh", "shortcuts": [":_hi:"], "isCustomEmoji": True}}


def SC(發送, 名, *runs):
    其他 = {"purchaseAmountText": {"simpleText": "NT$150.00"}}
    if runs:
        其他["message"] = {"runs": [{"text": r} for r in runs]}
    return _項目("liveChatPaidMessageRenderer", 發送, 名, **其他)


def 貼圖(發送, 名):
    return _項目("liveChatPaidStickerRenderer", 發送, 名, purchaseAmountText={"simpleText": "$2.00"}, sticker={})


def 會員加入(發送, 名):
    return _項目("liveChatMembershipItemRenderer", 發送, 名, headerSubtext={"runs": [{"text": "Welcome to the club!"}]})


def 置頂():
    return _包({"addBannerToLiveChatCommand": {"bannerRenderer": {"liveChatBannerRenderer": {"contents": {}}}}})


def 系統通知(發送):
    return _項目("liveChatViewerEngagementMessageRenderer", 發送, "", message={"runs": [{"text": "Welcome to live chat!"}]})


# ---------- 解析 ----------
def test_一般留言():
    assert yt_chat.解析動作(文字(起點, "@taro", "hello ", "world")) == ("留言", 起點, "@taro", "hello world", False)


def test_表情組文字時拿掉():
    assert yt_chat.解析動作(文字(起點, "@a", "すごい", 表情("😂"), 自訂表情(), "！"))[3] == "すごい！"


def test_只剩表情_當作純表情_照現有規則不翻():
    _, _, _, 內容, 純表情 = yt_chat.解析動作(文字(起點, "@a", 表情("😂"), 自訂表情(), 表情("👍🏻")))
    assert 純表情 and 內容 == "😂□👍🏻"
    assert chat_translate.跳過原因(內容) is not None
    assert not chat_translate.要翻譯(內容, "ja")


def test_SuperChat_前面加SC():
    assert yt_chat.解析動作(SC(起點, "@a", "いつも", "ありがとう"))[3] == "【SC】いつもありがとう"
    assert yt_chat.解析動作(SC(起點, "@a"))[3] == "【SC】（沒有留言）"


def test_SuperSticker_沒有文字寫貼圖():
    assert yt_chat.解析動作(貼圖(起點, "@a"))[3] == "【SC】貼圖"


@pytest.mark.parametrize("行", [會員加入(起點, "@a"), 置頂(), 系統通知(起點),
                               _包({"markChatItemAsDeletedAction": {"targetItemId": "x"}})])
def test_系統訊息不是留言(行):
    assert yt_chat.解析動作(行) == ("系統",)


@pytest.mark.parametrize("行", ["", "{不是 JSON", json.dumps({"別的": 1}),
                               文字(起點, "@a", "x").replace(str(int(起點 * 1e6)), "壞")])
def test_看不懂的行不算(行):
    assert yt_chat.解析動作(行) is None


def test_機器人():
    for 名 in ("@Nightbot", "Nightbot", "@StreamElements", "@Streamlabs", "@Fossabot", "@my_helperbot"):
        assert yt_chat.是機器人(名), 名
    assert not yt_chat.是機器人("@taro")


def test_Twitch的機器人名單不變():
    assert chat_capture.機器人 == {"nightbot", "moobot", "streamelements", "streamlabs", "fossabot", "wizebot", "sery_bot",
                                "soundalerts", "commanderroot", "anotherttvviewer", "streamstickers", "pretzelrocks", "lurxx"}
    assert chat_capture.是機器人("Nightbot") and not chat_capture.是機器人("cloudbotfan")


# ---------- 假的 yt-dlp 下載 ----------
class 假下載:
    """像 yt-dlp 一樣把行一批一批寫進 資料夾/chat.live_chat.json.part；批次之間用 yt-dlp 模組裡的 time.sleep 等
    （真的經過 yt_chat 換上的可中斷等待）。批們用完：等到停止（像直播還在進行），或 結束=True 時回來／丟例外。"""

    def __init__(self, 批們=(), 錯誤=None, 結束=False, 等=0.01):
        self.批們, self.錯誤, self.結束, self.等 = [list(b) for b in 批們], 錯誤, 結束, 等
        self.資料夾們 = []
        self.次數 = 0
        self.全寫完 = threading.Event()

    def __call__(self, 網址, 資料夾, 停, 紀錄):
        import yt_dlp.downloader.youtube_live_chat as 模組
        yt_chat._裝上可中斷等待()
        self.次數 += 1
        self.資料夾們.append(資料夾)
        路徑 = os.path.join(資料夾, "chat.live_chat.json.part")
        with open(路徑, "a", encoding="utf-8") as 檔:
            for 批 in self.批們:
                檔.write("".join(x + "\n" for x in 批))
                檔.flush()
                模組.time.sleep(self.等)
            self.全寫完.set()
            if self.錯誤:
                raise self.錯誤
            if self.結束:
                return
            while True:
                模組.time.sleep(10)        # 聊天室很安靜：yt-dlp 每一輪都會等 timeoutMs（真的約 5～10 秒）


def 跑(下載, 時軸=None, 存檔=None, 等到=None):
    聊 = yt_chat.聊天室("https://www.youtube.com/watch?v=abcdefghijk", 存檔, 下載=下載)
    聊.開始(起點, 時軸)
    if 等到 is not None:
        等到()
    return 聊


def 等(條件, 秒=5.0):
    結束 = time.time() + 秒
    while time.time() < 結束:
        if 條件():
            return True
        time.sleep(0.01)
    return False


def 關閉並等(聊):
    聊.關閉()
    聊.執行緒.join(5)
    assert not 聊.執行緒.is_alive()


# ---------- 舊留言、時間換算 ----------
def test_舊留言過濾_只留開始擷取之後的(事件們):
    下載 = 假下載([[文字(起點 - 30, "@old1", "前面的"), 文字(起點 - 1, "@old2", "也是前面的"),
                   文字(起點 + 2, "@new", "新的")]])
    聊 = 跑(下載, sc.時軸(開播=起點 - 600))
    assert 等(lambda: len(聊.訊息們) == 1)
    關閉並等(聊)
    assert [m[1] for m in 聊.訊息們] == ["@new"]
    assert (聊.收到, 聊.過濾, 聊.舊留言) == (3, 2, 2)


def test_時間_有開播時間_發送時刻減開播_不扣延遲(事件們, tmp_path):
    軸 = sc.時軸(開播=起點 - 3600, 延遲=sc.YouTube延遲秒)
    聊 = 跑(假下載([[文字(起點 + 5, "@a", "hello")]]), 軸, str(tmp_path / "聊天室.txt"))
    assert 等(lambda: 聊.訊息們)
    關閉並等(聊)
    assert 聊.訊息們[0][0] == pytest.approx(3605)
    行 = next(c for k, c in 事件們 if k == "chat_line")
    assert 行["時間字"] == "1:00:05" and 行["內容"] == "hello"
    assert "[1:00:05] @a: hello" in (tmp_path / "聊天室.txt").read_text(encoding="utf-8")


def test_時間_只有PDT_發送時刻減第一段PDT_和直播稿同一個零點(事件們):
    """抓不到開播時間：音訊第 0 秒 = 第一段 PDT。同一時刻說的話與留言，差的只有觀眾反應時間（這裡 3 秒），不是 20 秒延遲。"""
    鐘 = SimpleNamespace(t=起點 + 2)
    軸 = sc.時軸(開播=None, 時鐘=lambda: 鐘.t, 延遲=sc.YouTube延遲秒)
    軸.開始()                                    # 收到第一個音訊位元組（起點 + 2）
    軸.對齊串流時刻(起點 - 18)                   # 那一段的 PDT：實際延遲 20 秒
    說話時刻 = 起點 + 10                          # 直播端在這一刻說了一句話
    句子秒 = 軸.音訊秒轉直播秒(說話時刻 - (起點 - 18))   # 那句話在音訊裡的位置 = 說話時刻 − PDT
    聊 = 跑(假下載([[文字(說話時刻 + 3, "@a", "草")]]), 軸)
    assert 等(lambda: 聊.訊息們)
    關閉並等(聊)
    留言秒 = 聊.訊息們[0][0]
    assert 留言秒 - 句子秒 == pytest.approx(3)
    assert next(c for k, c in 事件們 if k == "chat_line")["時間字"] == "+00:31"


def test_時間_有開播_同一時刻說的話與留言只差反應時間(事件們):
    鐘 = SimpleNamespace(t=起點 + 2)
    軸 = sc.時軸(開播=起點 - 3600, 時鐘=lambda: 鐘.t, 延遲=sc.YouTube延遲秒)
    軸.開始()
    軸.對齊串流時刻(起點 - 21.5)                 # 這次實際延遲 23.5 秒（和備援的 20 秒不同也一樣對得上）
    說話時刻 = 起點 + 10
    句子秒 = 軸.音訊秒轉直播秒(說話時刻 - (起點 - 21.5))
    聊 = 跑(假下載([[文字(說話時刻 + 2, "@a", "lol")]]), 軸)
    assert 等(lambda: 聊.訊息們)
    關閉並等(聊)
    assert 聊.訊息們[0][0] - 句子秒 == pytest.approx(2)


def test_時間_24小時頻道_加號模式_聊天室和直播稿從同一點起算(事件們, monkeypatch):
    現在 = 起點
    monkeypatch.setattr(lc, "time", SimpleNamespace(time=lambda: 現在))
    查詢 = SimpleNamespace(等=lambda: {"開播": 起點 - 3 * 86400, "直播主": "Lofi Girl", "來源": "YouTube網頁"})
    鐘 = SimpleNamespace(t=起點 + 2)
    軸 = lc.取得時軸(查詢, platforms.YOUTUBE)
    軸.時鐘 = lambda: 鐘.t
    assert 軸.開播 is None and 軸.加號 and 軸.連續直播開播 == 起點 - 3 * 86400
    軸.開始()
    軸.對齊串流時刻(起點 - 18)
    說話時刻 = 起點 + 10
    句子秒 = 軸.音訊秒轉直播秒(說話時刻 - (起點 - 18))
    聊 = 跑(假下載([[文字(說話時刻 + 4, "@a", "nice")]]), 軸)
    assert 等(lambda: 聊.訊息們)
    關閉並等(聊)
    assert 聊.訊息們[0][0] - 句子秒 == pytest.approx(4)
    assert 句子秒 == pytest.approx(28) and 軸.標記(句子秒) == "[+00:28]"      # 不會是好幾萬小時


def test_加號模式_還沒收到音訊_留言先等_對齊後才用PDT換算(事件們):
    鐘 = SimpleNamespace(t=起點)
    軸 = sc.時軸(開播=None, 時鐘=lambda: 鐘.t, 延遲=sc.YouTube延遲秒)
    聊 = 跑(假下載([[文字(起點 + 1, "@a", "first")]]), 軸)
    time.sleep(0.2)
    assert 聊.訊息們 == []                       # 還不知道零點：先不放
    鐘.t = 起點 + 3
    軸.開始()
    軸.對齊串流時刻(起點 - 17)
    assert 等(lambda: 聊.訊息們)
    關閉並等(聊)
    assert 聊.訊息們[0][0] == pytest.approx(18)


def test_加號模式_讀不到PDT_用估計延遲換成收到時刻(事件們):
    鐘 = SimpleNamespace(t=起點 + 2)
    軸 = sc.時軸(開播=None, 時鐘=lambda: 鐘.t, 延遲=sc.YouTube延遲秒)
    軸.開始()
    軸.對齊串流時刻(None)
    聊 = 跑(假下載([[文字(起點 + 10, "@a", "x")]]), 軸)
    assert 等(lambda: 聊.訊息們)
    關閉並等(聊)
    assert 聊.訊息們[0][0] == pytest.approx(10 + 20 - 2)      # 發送 + 估計延遲 − 第一個位元組


def test_沒有時軸_從開始擷取起算(事件們):
    聊 = 跑(假下載([[文字(起點 + 7, "@a", "x")]]))
    assert 等(lambda: 聊.訊息們)
    關閉並等(聊)
    assert 聊.訊息們[0][0] == pytest.approx(7)


def test_過濾_機器人_指令_洗版_系統訊息(事件們):
    下載 = 假下載([[文字(起點 + 1, "@Nightbot", "Follow us!"), 文字(起點 + 1, "@a", "!uptime"),
                   文字(起點 + 1, "@b", "lol lol lol"), 會員加入(起點 + 1, "@c"), 置頂(), 系統通知(起點 + 1),
                   SC(起點 + 2, "@d", "がんばって"), 貼圖(起點 + 2, "@e"), 文字(起點 + 3, "@f", 表情("😂"))]])
    聊 = 跑(下載, sc.時軸(開播=起點))
    assert 等(lambda: len(聊.訊息們) == 3)
    關閉並等(聊)
    assert [m[2] for m in 聊.訊息們] == ["【SC】がんばって", "【SC】貼圖", "😂"]
    assert (聊.收到, 聊.過濾, 聊.系統訊息) == (6, 3, 3)


def test_同一個取出介面(事件們):
    聊 = 跑(假下載([[文字(起點 + 5, "@a", "x"), 文字(起點 + 65, "@b", "y")]]), sc.時軸(開播=起點))
    assert 等(lambda: len(聊.訊息們) == 2)
    關閉並等(聊)
    assert [m[1] for m in 聊.取出(0, 60)] == ["@a"] and [m[1] for m in 聊.取出(60, 120)] == ["@b"]


# ---------- 暫存檔、只讀新增的部分 ----------
def test_只讀新增的部分_沒寫完的行留到下次(tmp_path):
    路徑 = tmp_path / "chat.live_chat.json.part"
    讀 = yt_chat.增量讀取(str(tmp_path))
    assert 讀.新行() == []
    路徑.write_bytes(b'{"a": 1}\n{"b"')
    assert 讀.新行() == ['{"a": 1}'] and 讀.位置 == 路徑.stat().st_size
    with open(路徑, "ab") as f:
        f.write(b': 2}\n{"c": 3}\n')
    assert 讀.新行() == ['{"b": 2}', '{"c": 3}']
    assert 讀.新行() == []
    os.rename(路徑, tmp_path / "chat.live_chat.json")          # yt-dlp 結束時改名：接著讀，不重讀
    with open(tmp_path / "chat.live_chat.json", "ab") as f:
        f.write(b'{"d": 4}\n')
    assert 讀.新行() == ['{"d": 4}']


def test_暫存在系統暫存資料夾_按停止後刪掉(事件們):
    下載 = 假下載([[文字(起點 + 1, "@a", "x")]])
    聊 = 跑(下載, sc.時軸(開播=起點))
    assert 等(lambda: 聊.訊息們)
    資料夾 = 下載.資料夾們[0]
    assert os.path.dirname(資料夾) == os.path.dirname(os.path.join(__import__("tempfile").gettempdir(), "x"))
    assert os.path.basename(資料夾).startswith(yt_chat.暫存前綴) and os.path.exists(資料夾)
    關閉並等(聊)
    assert not os.path.exists(資料夾)


def test_出錯後暫存也刪掉(事件們):
    下載 = 假下載([[文字(起點 + 1, "@a", "x")]], 錯誤=RuntimeError("壞了"))
    聊 = 跑(下載, sc.時軸(開播=起點))
    assert 等(lambda: 下載.次數 >= 2)
    關閉並等(聊)
    assert 下載.資料夾們 and not any(os.path.exists(d) for d in 下載.資料夾們)


# ---------- 停止：5 秒內收尾 ----------
def test_聊天室完全沒有新留言時按停止_5秒內收尾(事件們, tmp_path):
    下載 = 假下載([], 結束=False)                 # 一則都沒有，yt-dlp 正在等下一輪（sleep 10 秒）
    聊 = 跑(下載, sc.時軸(開播=起點), str(tmp_path / "聊天室.txt"))
    assert 等(下載.全寫完.is_set)
    time.sleep(0.2)
    開始 = time.time()
    聊.關閉()
    聊.執行緒.join(5)
    花了 = time.time() - 開始
    assert not 聊.執行緒.is_alive() and 花了 < 5
    assert 花了 < 1.5                            # 可中斷等待：實際上幾乎馬上停
    assert not os.path.exists(下載.資料夾們[0])


def test_yt_dlp卡住不理停止_讀取端照樣5秒內收尾_暫存等它結束再刪(事件們, monkeypatch):
    monkeypatch.setattr(yt_chat, "停止等待秒", 0.5)
    放開 = threading.Event()
    資料夾們 = []

    def 卡住(網址, 資料夾, 停, 紀錄):          # 例如網路卡住：不呼叫 sleep 也不回報進度
        資料夾們.append(資料夾)
        放開.wait(10)

    聊 = 跑(卡住, sc.時軸(開播=起點))
    assert 等(lambda: 資料夾們)
    開始 = time.time()
    聊.關閉()
    聊.執行緒.join(5)
    assert not 聊.執行緒.is_alive() and time.time() - 開始 < 5
    assert os.path.exists(資料夾們[0])           # yt-dlp 還沒結束：交給它結束時刪
    數 = len([k for k, _ in 事件們 if k == "chat_line"])
    放開.set()
    assert 等(lambda: not os.path.exists(資料夾們[0]))
    assert len([k for k, _ in 事件們 if k == "chat_line"]) == 數      # 收尾後不再送留言


def test_可中斷等待_不是我們的執行緒照原本sleep():
    yt_chat._裝上可中斷等待()
    import yt_dlp.downloader.youtube_live_chat as 模組
    開始 = time.time()
    模組.time.sleep(0.05)
    assert time.time() - 開始 >= 0.04
    assert 模組.time.time() == pytest.approx(time.time(), abs=1)


# ---------- 重試與失效訊息 ----------
def test_重試3次後_主控台與膠囊顯示失效訊息(事件們):
    下載 = 假下載([], 錯誤=RuntimeError("Unable to extract"))
    聊 = 跑(下載, sc.時軸(開播=起點))
    聊.執行緒.join(5)
    assert not 聊.執行緒.is_alive()
    assert 下載.次數 == 1 + yt_chat.重試次數 and 聊.失效
    訊息 = [c for k, c in 事件們 if k == "chat_status"]       # 主控台（印出）、膠囊、聊天室面板（說明）同一則
    assert len(訊息) == 1 and 訊息[0]["狀態"] == "失效"
    assert 訊息[0]["印出"].strip() == 訊息[0]["膠囊"] == 訊息[0]["說明"] == (
        "YouTube 聊天室暫時抓不到（可能是 YouTube 改版），摘要和字幕照常；更新程式後可能會恢復。")


def test_有收到過就重新計算重試次數(事件們):
    下載 = 假下載([[文字(起點 + 1, "@a", "x")]], 錯誤=RuntimeError("斷線"))
    聊 = 跑(下載, sc.時軸(開播=起點))
    assert 等(lambda: 下載.次數 >= 6)              # 每輪都有資料：一直重連，不會說失效
    關閉並等(聊)
    assert not 聊.失效 and not [c for k, c in 事件們 if k == "info"]


def test_直播結束_正常回來也不會一直卡住(事件們):
    下載 = 假下載([[]], 結束=True)
    聊 = 跑(下載, sc.時軸(開播=起點))
    聊.執行緒.join(5)
    assert not 聊.執行緒.is_alive() and 聊.失效


# ---------- 24 小時判斷 ----------
def test_是連續直播():
    assert not sc.是連續直播(None, 起點)
    assert not sc.是連續直播(起點 - 23.9 * 3600, 起點)
    assert sc.是連續直播(起點 - 24.1 * 3600, 起點)


def test_取得時軸_24小時頻道_改從開始擷取起算並說一行(事件們, monkeypatch):
    monkeypatch.setattr(lc, "time", SimpleNamespace(time=lambda: 起點))
    查詢 = SimpleNamespace(等=lambda: {"開播": 起點 - 400 * 86400, "直播主": "Lofi Girl", "來源": "YouTube網頁"})
    軸 = lc.取得時軸(查詢, platforms.YOUTUBE)
    assert 軸.開播 is None and 軸.加號
    內容 = next(c for k, c in 事件們 if k == "stream_info")
    assert not 內容["有開播"]
    assert "連續播出的直播" in 內容["印出"] and "已超過 24 小時" in 內容["印出"] and "前面加 +" in 內容["印出"]
    assert "連續直播超過 24 小時" in sc.檔頭()


def test_取得時軸_YouTube_開播不到24小時照舊(事件們, monkeypatch):
    monkeypatch.setattr(lc, "time", SimpleNamespace(time=lambda: 起點))
    軸 = lc.取得時軸(SimpleNamespace(等=lambda: {"開播": 起點 - 3600}), platforms.YOUTUBE)
    assert 軸.開播 == 起點 - 3600
    assert next(c for k, c in 事件們 if k == "stream_info")["印出"] is None


def test_Twitch_開播超過24小時也不變(事件們, monkeypatch):
    monkeypatch.setattr(lc, "time", SimpleNamespace(time=lambda: 起點))
    軸 = lc.取得時軸(SimpleNamespace(等=lambda: {"開播": 起點 - 30 * 3600}), platforms.TWITCH)
    assert 軸.開播 == 起點 - 30 * 3600 and 軸.延遲 == sc.延遲秒


def test_Twitch聊天室_仍然用chat_capture(monkeypatch, tmp_path, 事件們):
    建了 = []
    monkeypatch.setattr(chat_capture, "聊天室", lambda *a: 建了.append(a))
    monkeypatch.setattr(lc, "檢查直播", lambda 網址, 查詢=None: "audio_only")
    monkeypatch.setattr(lc, "找ffmpeg", lambda: "ffmpeg")
    monkeypatch.setattr(lc.stream_info, "背景查詢", lambda *a, **k: SimpleNamespace(等=lambda: None))
    lc.live_session("https://www.twitch.tv/taiji", 稿目錄=str(tmp_path), 存音訊=False)
    assert 建了 and 建了[0][0] == "taiji"


def test_yt_dlp被中斷時檔案還開著_也刪得掉(事件們):
    """像真的 yt-dlp：.part 由下載端開著不關（內部循環參照），停止時從 sleep 丟例外出來。
    例外物件不能留著（它的 traceback 抓著檔案），不然 Windows 上刪不掉。"""
    資料夾們 = []

    def 下載(網址, 資料夾, 停, 紀錄):
        import yt_dlp.downloader.youtube_live_chat as 模組
        yt_chat._裝上可中斷等待()
        資料夾們.append(資料夾)
        ctx = {"dest_stream": open(os.path.join(資料夾, "chat.live_chat.json.part"), "ab")}    # noqa: SIM115
        ctx["自己"] = ctx                                  # 循環參照：只靠引用計數不會關檔
        ctx["dest_stream"].write((文字(起點 + 1, "@a", "x") + "\n").encode())
        ctx["dest_stream"].flush()
        while True:
            模組.time.sleep(10)

    聊 = 跑(下載, sc.時軸(開播=起點))
    assert 等(lambda: 聊.訊息們)
    關閉並等(聊)
    assert not os.path.exists(資料夾們[0])


def test_清掉上次留下的舊暫存_正在用的不動(monkeypatch, tmp_path):
    monkeypatch.setattr(yt_chat.tempfile, "gettempdir", lambda: str(tmp_path))
    舊 = tmp_path / (yt_chat.暫存前綴 + "old")
    新 = tmp_path / (yt_chat.暫存前綴 + "new")
    別的 = tmp_path / "別的程式_old"
    for d in (舊, 新, 別的):
        d.mkdir()
        (d / "chat.live_chat.json.part").write_text("x")
    os.utime(舊, (起點 - 3600, 起點 - 3600))
    os.utime(別的, (起點 - 3600, 起點 - 3600))
    os.utime(新, (起點 - 5, 起點 - 5))
    yt_chat.清舊暫存(起點)
    assert not 舊.exists() and 新.exists() and 別的.exists()


# ---------- 保護測試：yt-dlp 更新後，被替換的等待還在不在 ----------
# yt_chat 替換了 yt_dlp.downloader.youtube_live_chat 的 time（兩批之間的 time.sleep），按停止才能立刻生效。
# yt-dlp 改版把那個位置拿掉或改寫時，這裡要直接失敗，不能默默退回「按停止停不下來」。
改版訊息 = "yt-dlp 版本變了，聊天室的停止機制要重新檢查（yt_chat._可中斷時間 替換的位置）"


def test_保護_yt_dlp被替換的等待位置還在():
    模組, 原因 = yt_chat.檢查可中斷等待(要原始碼=True)
    assert 模組 is not None, f"{改版訊息}：{原因}"


def test_保護_裝上後_yt_dlp聊天室下載真的用我們的等待():
    assert yt_chat._裝上可中斷等待(), 改版訊息
    import yt_dlp.downloader.youtube_live_chat as 模組
    類 = getattr(模組, "YoutubeLiveChatFD", None)
    assert 類 is not None and hasattr(類, "real_download"), f"{改版訊息}：找不到 YoutubeLiveChatFD.real_download"
    assert isinstance(類.real_download.__globals__.get("time"), yt_chat._可中斷時間), \
        f"{改版訊息}：real_download 用的 time 不是替換後的版本"


def test_保護_安裝的yt_dlp和requirements固定的版本一樣():
    import re

    import yt_dlp.version
    根 = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(根, "requirements.txt"), encoding="utf-8") as f:
        m = re.search(r"^yt-dlp==(\S+)", f.read(), re.MULTILINE)
    assert m, "requirements.txt 沒有固定 yt-dlp 的版本（yt-dlp==版本）"

    def 正規(v):
        return tuple(int(x) for x in v.split("."))
    assert 正規(yt_dlp.version.__version__) == 正規(m.group(1)), (
        f"{改版訊息}：安裝的是 {yt_dlp.version.__version__}，requirements.txt 固定 {m.group(1)}。"
        "確認保護測試都通過、真的按停止會立刻結束後，再更新 requirements.txt 的版本")


@pytest.mark.parametrize("改法", ["沒有time", "找不到sleep", "讀不到原始碼", "模組不見"])
def test_保護_位置不見時檢查會失敗並寫出白話原因(monkeypatch, 改法):
    import importlib
    import inspect

    import yt_dlp.downloader.youtube_live_chat as 模組
    if 改法 == "沒有time":
        monkeypatch.setattr(模組, "time", object())
    elif 改法 == "找不到sleep":
        monkeypatch.setattr(inspect, "getsource", lambda m: "import time\nwait(timeout_ms)\n")
    elif 改法 == "讀不到原始碼":
        def 讀不到(m):
            raise OSError("frozen")
        monkeypatch.setattr(inspect, "getsource", 讀不到)
    else:
        def 不見(名):
            raise ImportError("No module named " + 名)
        monkeypatch.setattr(importlib, "import_module", 不見)
    結果, 原因 = yt_chat.檢查可中斷等待(要原始碼=True)
    assert 結果 is None and "youtube_live_chat" in 原因


def test_執行時讀不到原始碼_只看模組結構照樣裝上(monkeypatch):
    import inspect

    def 讀不到(m):
        raise OSError("打包成 .exe")
    monkeypatch.setattr(inspect, "getsource", 讀不到)
    assert yt_chat.檢查可中斷等待()[0] is not None


def test_執行時位置不見_主控台說一次_寫進log_聊天室照常(monkeypatch, tmp_path, 事件們):
    紀錄檔 = tmp_path / "logs" / "YouTube聊天室_紀錄.txt"
    monkeypatch.setattr(yt_chat, "紀錄檔", str(紀錄檔))
    monkeypatch.setattr(yt_chat, "_說過", False)
    monkeypatch.setattr(yt_chat, "檢查可中斷等待", lambda 要原始碼=False: (None, "找不到 time.sleep("))
    assert yt_chat._裝上可中斷等待() is False
    assert yt_chat._裝上可中斷等待() is False
    說 = [c["印出"] for k, c in 事件們 if k == "info"]
    assert 說 == [yt_chat.無法快速停止] and "按停止後可能要多等幾秒" in 說[0]
    行們 = 紀錄檔.read_text(encoding="utf-8").splitlines()
    assert len(行們) == 2 and all(yt_chat.無法快速停止 in x and "找不到 time.sleep(" in x for x in 行們)

    下載 = 假下載([[文字(起點 + 1, "@a", "還是收得到")]], 結束=True)     # 聊天室照常運作
    聊 = 跑(下載, sc.時軸(開播=起點))
    assert 等(lambda: any(k == "chat_line" for k, _ in 事件們))
    聊.關閉()
