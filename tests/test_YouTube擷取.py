# YouTube 第 2 步：開播檢查的白話訊息、平台分流（Twitch 不變）、PDT 對齊時間、延遲依平台、yt_audio 的 PDT 推算。
# 全部用假的 streamlink 回應、假網頁、假管線；不連網、不需要 streamlink 或 ffmpeg。
import json
import subprocess
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import numpy as np
import pytest

import events
import live_capture as lc
import platforms
import stream_clock as sc
import stream_info as si
import timefmt
import yt_audio

YT網址 = "https://www.youtube.com/@LofiGirl/live"
TW網址 = "https://www.twitch.tv/taiji"
頻道ID = "UCSJ4gkVC6NrvII8umztf0Ow"
影片 = "jfKfPfyJRdk"


@pytest.fixture
def 事件們(monkeypatch):
    收到 = []
    monkeypatch.setattr(events, "接收者們", [lambda 種類, 內容: 收到.append((種類, 內容))])
    events.停止.clear()
    yield 收到
    events.停止.clear()


@pytest.fixture(autouse=True)
def 不留時軸(monkeypatch):
    monkeypatch.setattr(sc, "_目前", None)
    monkeypatch.setattr(sc, "_資訊", None)


# ---------- 假的 streamlink ----------
class 假子程序:
    def __init__(self, stdout="", stderr=""):
        self.輸出 = (stdout, stderr)

    def communicate(self, timeout=None):
        return self.輸出

    def kill(self):
        pass


def 假streamlink(monkeypatch, *回應們):
    """依序回應每次 Popen：(stdout, stderr)；記下每次的參數。"""
    呼叫, 剩 = [], list(回應們)

    def Popen(參數, **_):
        呼叫.append(參數)
        return 假子程序(*剩.pop(0))

    monkeypatch.setattr(lc.subprocess, "Popen", Popen)
    return 呼叫


def JSON錯誤(字):
    return json.dumps({"error": 字})


def JSON串流(**型別們):
    return json.dumps({"plugin": "youtube", "streams": {名: {"type": 型} for 名, 型 in 型別們.items()}})


沒有串流 = JSON錯誤(f"No playable streams found on this URL: {YT網址}")


def 原因紀錄(狀態, 原因):
    return (f"[plugins.youtube][error] Could not get video info - {狀態}: {原因}\n"
            f"error: No playable streams found on this URL: {YT網址}\n")


class 假查詢:
    def __init__(self, 結果):
        self.結果 = 結果

    def 等(self, *a, **k):
        return self.結果


# ---------- 每一種錯誤的白話訊息 ----------
預定 = datetime(2026, 10, 14, 0, 0, tzinfo=UTC).timestamp()
預定字 = datetime.fromtimestamp(預定).strftime("%Y-%m-%d %H:%M")

錯誤情況 = [
    # (名稱, streamlink 一般模式的紀錄, 觀看頁資訊, 訊息應該含的字)
    ("機器人", 原因紀錄("LOGIN_REQUIRED", "Sign in to confirm you’re not a bot"), None,
     ["要求登入驗證", "機器人", "目前無法擷取", "稍後再試", "換一個網路"]),
    ("機器人_中文原因", "", {"狀態": "LOGIN_REQUIRED", "原因": "請登入，確認你不是機器人"},
     ["要求登入驗證", "換一個網路"]),
    ("還沒開始_有預定時間", 原因紀錄("LIVE_STREAM_OFFLINE", "This live event will begin in 6 hours."),
     {"即將開始": True, "預定開始": 預定}, ["還沒開始", f"預定 {預定字} 開始", "本機時間"]),
    ("還沒開始_讀不到預定時間", 原因紀錄("LIVE_STREAM_OFFLINE", "This live event will begin in a few moments."), None,
     ["還沒開始", "請等開播後再按開始"]),
    ("會員限定", 原因紀錄("LOGIN_REQUIRED", "Join this channel to get access to members-only content like this video."),
     None, ["會員限定", "第一版只支援公開直播"]),
    ("年齡限制", 原因紀錄("LOGIN_REQUIRED", "This video may be inappropriate for some users."), None,
     ["年齡限制", "第一版只支援公開直播"]),
    ("年齡限制_確認年齡", 原因紀錄("LOGIN_REQUIRED", "Sign in to confirm your age"), None, ["年齡限制"]),
    ("需要登入", 原因紀錄("LOGIN_REQUIRED", "This video is private."), None, ["需要登入", "第一版只支援公開直播"]),
    ("錄好的影片_看觀看頁", "", {"影片ID": 影片, "直播中": None, "直播內容": False, "狀態": "OK"},
     ["錄好的影片", "目前只支援直播"]),
    ("頻道沒開播", "[plugins.youtube][error] Could not find videoId on channel page\n", None, ["目前沒有在直播"]),
]


@pytest.mark.parametrize("名稱, 紀錄, 頁, 要有", 錯誤情況, ids=[c[0] for c in 錯誤情況])
def test_YouTube_每一種錯誤都是白話訊息(monkeypatch, 事件們, 名稱, 紀錄, 頁, 要有):
    呼叫 = 假streamlink(monkeypatch, (沒有串流, ""), ("", 紀錄))
    with pytest.raises(lc.直播錯誤) as 錯:
        lc.檢查直播(YT網址, 假查詢(頁))
    for 字 in 要有:
        assert 字 in str(錯.value)
    assert "Twitch" not in str(錯.value)
    assert 呼叫[0][-2:] == ["--json", YT網址]
    assert 呼叫[1][-3:] == ["--loglevel", "error", YT網址]       # 失敗才再跑一般模式讀原因


@pytest.mark.parametrize("stdout, 要有", [
    (JSON錯誤("This plugin does not support VOD content, try yt-dlp instead"), "錄好的影片"),
    (JSON錯誤("This plugin does not support protected videos, try yt-dlp instead"), "需要登入"),
    (JSON錯誤(f"No plugin can handle URL: {YT網址}"), "網址看起來不對"),
    ("不是 JSON", "無法檢查直播"),
    (json.dumps({"streams": {}}), "目前沒有在直播"),
    (JSON串流(**{"360p": "http", "720p": "http"}), "錄好的影片"),          # 影片：streamlink 只給一般檔、沒有 HLS
])
def test_YouTube_streamlink直接看得出來的錯誤(monkeypatch, stdout, 要有):
    呼叫 = 假streamlink(monkeypatch, (stdout, ""))
    with pytest.raises(lc.直播錯誤, match=要有):
        lc.檢查直播(YT網址, 假查詢(None))
    assert len(呼叫) == 1


def test_YouTube_有HLS但觀看頁說直播已結束_是錄好的影片(monkeypatch):
    假streamlink(monkeypatch, (JSON串流(**{"144p": "hls", "worst": "hls"}), ""))
    with pytest.raises(lc.直播錯誤, match="錄好的影片"):
        lc.檢查直播(YT網址, 假查詢({"影片ID": 影片, "直播中": False, "直播內容": True}))


def test_YouTube_沒有audio_only_用最低畫質(monkeypatch):
    假streamlink(monkeypatch, (JSON串流(**{"144p": "hls", "720p": "hls", "worst": "hls", "best": "hls"}), ""))
    assert lc.檢查直播(YT網址, 假查詢({"影片ID": 影片, "直播中": True})) == "worst"


def test_YouTube_有audio_only就用(monkeypatch):
    假streamlink(monkeypatch, (JSON串流(audio_only="hls", worst="hls"), ""))
    assert lc.檢查直播(YT網址, 假查詢(None)) == "audio_only"


def test_YouTube_原因種類():
    assert lc.YouTube原因種類("OK", "") is None
    assert lc.YouTube原因種類("ERROR", "Video unavailable") is None
    assert lc.YouTube原因種類("UNPLAYABLE", "這是會員專屬影片") == "會員"
    assert lc.YouTube原因種類("LOGIN_REQUIRED", "") == "登入"
    assert lc.YouTube原因種類("AGE_CHECK_REQUIRED", "") == "年齡"
    assert lc.YouTube原因種類("OK", "This message is about a page") is None      # 「age」不能誤判成年齡限制


@pytest.mark.parametrize("stdout, 訊息", [
    (JSON錯誤("No plugin can handle URL: x"), "網址看起來不對，請確認是 Twitch 頻道網址。"),
    (JSON錯誤("auth required"), "這個直播需要訂閱或登入才能看，這個工具只支援公開直播。"),
    (JSON錯誤("No playable streams found"), "頻道目前沒有開播，或網址有誤。"),
    ("壞掉", "無法檢查直播，請確認網址正確（例如 https://www.twitch.tv/頻道名稱）。"),
    (json.dumps({"streams": {}}), "頻道目前沒有開播。"),
])
def test_Twitch_開播檢查訊息不變_只跑一次streamlink(monkeypatch, stdout, 訊息):
    呼叫 = 假streamlink(monkeypatch, (stdout, ""))
    with pytest.raises(lc.直播錯誤) as 錯:
        lc.檢查直播(TW網址)
    assert str(錯.value) == 訊息
    assert len(呼叫) == 1 and 呼叫[0][-2:] == ["--json", TW網址]


def test_Twitch_串流名不變(monkeypatch):
    假streamlink(monkeypatch, (json.dumps({"streams": {"audio_only": {}, "160p": {}}}), ""))
    assert lc.檢查直播(TW網址) == "audio_only"
    假streamlink(monkeypatch, (json.dumps({"streams": {"160p": {}}}), ""))
    assert lc.檢查直播(TW網址) == "worst"


# ---------- 平台分流：live_session.__init__ ----------
@pytest.fixture
def 開始環境(monkeypatch, tmp_path, 事件們):
    紀 = {"查詢": [], "檢查": [], "聊天室": []}

    class 假背景查詢:
        def __init__(self, 頻道, 取得=None, 查法=None):
            紀["查詢"].append((頻道, 查法))

        def 等(self, *a, **k):
            return 紀.get("結果")

    class 假聊天室:
        def __init__(self, *a, **k):
            紀["聊天室"].append(a)

    import chat_capture
    monkeypatch.setattr(si, "背景查詢", 假背景查詢)
    monkeypatch.setattr(lc, "檢查直播", lambda 網址, 查詢=None: (紀["檢查"].append((網址, 查詢)), "worst")[1])
    monkeypatch.setattr(lc, "找ffmpeg", lambda: "ffmpeg")
    monkeypatch.setattr(chat_capture, "聊天室", 假聊天室)

    def 開(網址, 結果=None):
        紀["結果"] = 結果
        return lc.live_session(網址, 稿目錄=str(tmp_path), 存音訊=False)

    紀["開"] = 開
    紀["事件"] = 事件們
    return 紀


def test_YouTube_讀觀看頁_延遲用YouTube的_聊天室用yt_chat(開始環境, monkeypatch):
    import yt_chat
    monkeypatch.setattr(lc, "time", SimpleNamespace(time=lambda: 1000.0 + 3600))     # 開播一小時（不是連續直播）
    s = 開始環境["開"](YT網址, {"開播": 1000.0, "直播主": "Lofi Girl", "標題": "t", "遊戲": "Music", "來源": "YouTube網頁",
                               "影片ID": "abcdefghijk"})
    assert s.平台 == platforms.YOUTUBE
    assert 開始環境["查詢"] == [(YT網址, si.查YouTube直播)]           # 用網址查 YouTube 觀看頁，不查 Twitch
    網址, 查詢 = 開始環境["檢查"][0]
    assert 網址 == YT網址 and 查詢 is not None                       # 開播檢查拿得到觀看頁資訊（寫白話原因用）
    assert s.時軸.延遲 == sc.YouTube延遲秒 and s.時軸.開播 == 1000.0
    assert 開始環境["聊天室"] == []                                    # 不能拿 YouTube 網址去連 Twitch
    assert isinstance(s.聊天, yt_chat.聊天室) and s.聊天.網址 == "https://www.youtube.com/watch?v=abcdefghijk"
    assert s.聊天.存檔路徑.endswith("_聊天室.txt")
    印出 = [c.get("印出") or "" for k, c in 開始環境["事件"] if k == "info"]
    assert not any("尚未支援" in x for x in 印出)
    內容 = next(c for k, c in 開始環境["事件"] if k == "stream_info")
    assert (內容["直播主"], 內容["遊戲"], 內容["來源"]) == ("Lofi Girl", "Music", "YouTube網頁")


def test_YouTube_沒開聊天室就不建(開始環境, tmp_path):
    開始環境["結果"] = None
    s = lc.live_session(YT網址, 稿目錄=str(tmp_path), 用聊天室=False, 存音訊=False)
    assert s.聊天 is None


def test_YouTube_讀不到影片ID_聊天室用原網址(開始環境):
    s = 開始環境["開"](YT網址, None)
    assert s.聊天.網址 == YT網址


def test_Twitch_流程不變(開始環境):
    s = 開始環境["開"](TW網址, {"開播": 1000.0, "直播主": "taiji", "標題": "t", "遊戲": "g", "來源": "GQL"})
    assert s.平台 == platforms.TWITCH
    assert 開始環境["查詢"] == [("taiji", None)]                      # 照舊用頻道名稱查 Twitch
    assert 開始環境["檢查"] == [(TW網址, None)]
    assert s.時軸.延遲 == sc.延遲秒 == 11.0 and s.時軸.說明 is None
    assert len(開始環境["聊天室"]) == 1 and 開始環境["聊天室"][0][0] == "taiji"


# ---------- 擷取：YouTube 用 yt_audio、PDT 對齊；Twitch 指令不變 ----------
class 假鐘:
    def __init__(self, t=0.0):
        self.t = t

    def __call__(self):
        return self.t


class 假管線:
    """一次吐一段音訊；stderr 是 yt_audio 印的行。"""

    def __init__(self, 段們, stderr行們=()):
        self.段們 = list(段們)
        self.stdout = self
        self.stderr = iter(stderr行們)

    def peek(self, n=1):
        return b"x"

    def read(self, n):
        return self.段們.pop(0) if self.段們 else b""

    def close(self):
        pass

    def kill(self):
        pass


@pytest.fixture
def 擷取(monkeypatch, tmp_path, 事件們):
    monkeypatch.setattr(lc, "每段位元組", 4)
    monkeypatch.setattr(lc, "載入模型", lambda 語言: object())
    monkeypatch.setattr(lc, "轉錄一段", lambda model, 音訊, 語言: [(0.5, "hello")])

    def 跑(平台, 時軸, stderr行們=()):
        指令們 = []
        人聲 = np.full(2, 8000, dtype=np.int16).tobytes()

        def Popen(參數, **k):
            指令們.append((參數, k))
            return 假管線([], stderr行們) if len(指令們) == 1 else 假管線([人聲, 人聲])     # p1：streamlink（stderr）；p2：ffmpeg（音訊）

        monkeypatch.setattr(lc.subprocess, "Popen", Popen)
        s = object.__new__(lc.live_session)
        s.網址 = YT網址 if 平台 == platforms.YOUTUBE else TW網址
        s.平台, s.串流名, s.ffmpeg, s.語言 = 平台, "worst", "ffmpeg", "en"
        s.稿路徑, s.存稿, s.音訊資料夾, s.聊天 = str(tmp_path / "稿.txt"), False, None, None
        s.存了段數 = s.存了位元組 = 0
        s._警告過 = False
        s.時軸 = 時軸
        s.吐出 = list(s)
        return s, 指令們

    return 跑


def test_YouTube_第一段音訊的直播時間_用PDT減開播(擷取, 事件們):
    """一小時前開播（−3600），第一個位元組在時刻 0，第一個片段的 PDT 是 −19.6（實際延遲 19.6 秒）。"""
    軸 = sc.時軸(開播=-3600.0, 時鐘=假鐘(0.0), 延遲=sc.YouTube延遲秒)
    s, 指令們 = 擷取(platforms.YOUTUBE, 軸, [b"PDT 807 -19.600\n"])
    參數, 選項 = 指令們[0]
    assert 參數[1] == yt_audio.__file__ and 參數[2:] == [YT網址, "worst"]
    assert 選項["stderr"] == subprocess.PIPE
    assert 軸.串流時刻對齊 and 軸.偏移 == pytest.approx(3580.4)      # PDT − 開播
    assert 軸.延遲 == pytest.approx(19.6)                             # 換成實測值，聊天室也用這個
    assert s.吐出[0][0] == pytest.approx(3580.9)
    assert s.吐出[0][1] == f"{timefmt.標記(3580.9)} hello" and s.吐出[0][1].startswith("[59:40]")
    assert any("依串流片段的時間戳對齊" in (c.get("印出") or "") for k, c in 事件們 if k == "info")


def test_YouTube_讀不到PDT_退回估計的延遲並說明(擷取, 事件們):
    軸 = sc.時軸(開播=-3600.0, 時鐘=假鐘(0.0), 延遲=sc.YouTube延遲秒)
    s, _ = 擷取(platforms.YOUTUBE, 軸, [b"some streamlink error\n"])
    assert not 軸.串流時刻對齊 and 軸.偏移 == 3600 - sc.YouTube延遲秒
    assert s.吐出[0][0] == pytest.approx(3580.5)
    assert any("改用估計的串流延遲" in (c.get("印出") or "") for k, c in 事件們 if k == "info")


def test_YouTube_抓不到開播時間_PDT不用_照舊加號(擷取):
    軸 = sc.時軸(開播=None, 時鐘=假鐘(0.0), 延遲=sc.YouTube延遲秒)
    s, _ = 擷取(platforms.YOUTUBE, 軸, [b"PDT 1 -19.6\n"])
    assert not 軸.串流時刻對齊 and s.吐出[0][1].startswith("[+00:00]")
    assert 軸.第一段PDT == -19.6          # 第 3 步聊天室用發送時刻換算時要用


def test_Twitch_擷取指令不變_不讀PDT(擷取):
    軸 = sc.時軸(開播=-3600.0, 時鐘=假鐘(0.0), 延遲=sc.延遲秒)
    _, 指令們 = 擷取(platforms.TWITCH, 軸, [b"PDT 1 -5\n"])
    參數, 選項 = 指令們[0]
    assert 參數[1:] == ["-m", "streamlink_cli", "--loglevel", "error", "--stdout", TW網址, "worst"]
    assert 選項["stderr"] == subprocess.DEVNULL
    assert not 軸.串流時刻對齊 and 軸.偏移 == 3600 - 11.0


# ---------- stream_clock ----------
def test_延遲依平台():
    assert sc.平台延遲(platforms.TWITCH) == 11.0
    assert sc.平台延遲(platforms.YOUTUBE) == sc.YouTube延遲秒
    assert sc.平台延遲("") == 11.0


def test_對齊串流時刻_聊天室與漂移校正用同一個基準():
    鐘 = 假鐘(10_000.0)
    軸 = sc.時軸(開播=1000.0, 時鐘=鐘, 延遲=20.0)
    assert not 軸.對齊串流時刻(9_980.0)              # 還沒收到第一個位元組：不動
    軸.開始()
    assert 軸.對齊串流時刻(9_975.5)
    assert (軸.偏移, 軸.延遲) == (8975.5, 24.5)
    assert 軸.時刻轉直播秒(10_000.0) == 8975.5         # 同一時刻的聊天留言 = 第一段音訊的直播秒
    鐘.t = 10_010.0
    assert 軸.段收滿(10, 10_010.0) == 0.0               # 剛好跟上：不補


def test_檔頭_YouTube寫明怎麼對齊_Twitch不變():
    sc.設定目前(sc.時軸(開播=0.0, 延遲=11.0), {"直播主": "n"})
    assert "已扣除約 11 秒串流延遲）" in sc.檔頭()
    sc.設定目前(sc.時軸(開播=0.0, 延遲=20.0, 說明="依 YouTube 串流片段的時間戳對齊"), {"直播主": "n"})
    assert "依 YouTube 串流片段的時間戳對齊）" in sc.檔頭()


# ---------- yt_audio：PDT 推算 ----------
def 片段(num, 秒=None, 長=5.0):
    基 = datetime(2026, 10, 13, 17, 39, 1, 262000, tzinfo=UTC)
    return SimpleNamespace(num=num, duration=長, date=None if 秒 is None else 基 + timedelta(seconds=秒))


def test_只有第一段有PDT_後面用片段長度往下推():
    基 = 片段(0, 0).date.timestamp()
    結果 = yt_audio.推算片段時刻([片段(790, 0), 片段(791), 片段(792, 長=2.0), 片段(793)])
    assert 結果 == {790: 基, 791: 基 + 5, 792: 基 + 10, 793: 基 + 12}


def test_沒有PDT_推不出來():
    assert yt_audio.推算片段時刻([片段(1), 片段(2)]) == {}


def test_中途又出現PDT_用新的():
    結果 = yt_audio.推算片段時刻([片段(1, 0), 片段(2, 7.0)])
    assert 結果[2] == 片段(0, 7.0).date.timestamp()


@pytest.mark.parametrize("行, 值", [("PDT 807 1791913166.262", 1791913166.262), ("PDT 807", None),
                                   ("PDT x y", None), ("error: xxx", None), ("", None)])
def test_解析PDT行(行, 值):
    assert yt_audio.解析PDT行(行) == 值


# ---------- stream_info：觀看頁的播放狀態、開始擷取用的查法 ----------
def 頁(播放):
    return "<script>var ytInitialPlayerResponse = " + json.dumps(播放, ensure_ascii=False) + ";</script>"


def 假取得(文):
    return lambda 網址, 資料=None, 標頭=None, 逾時=None: 文.encode("utf-8")


還沒開始頁 = 頁({
    "playabilityStatus": {"status": "LIVE_STREAM_OFFLINE", "reason": "這個現場直播將於 6 小時 後開始。",
                          "liveStreamability": {"liveStreamabilityRenderer": {"offlineSlate": {
                              "liveStreamOfflineSlateRenderer": {"scheduledStartTime": "1791936000"}}}}},
    "videoDetails": {"videoId": 影片, "channelId": 頻道ID, "author": "x", "isUpcoming": True, "isLiveContent": True},
    "microformat": {"playerMicroformatRenderer": {"category": "Gaming",
                                                  "liveBroadcastDetails": {"isLiveNow": False,
                                                                           "startTimestamp": "2026-10-14T00:00:00+00:00"}}},
})


def test_觀看頁_還沒開始的直播():
    資訊 = si.解析YouTube頁(還沒開始頁)
    assert (資訊["狀態"], 資訊["即將開始"], 資訊["預定開始"], 資訊["直播內容"]) == ("LIVE_STREAM_OFFLINE", True, 1791936000.0, True)
    assert "後開始" in 資訊["原因"]


def test_查YouTube直播_預定時間不能當開播時間():
    資訊 = si.查YouTube直播(f"https://www.youtube.com/watch?v={影片}", 假取得(還沒開始頁))
    assert 資訊["開播"] is None and 資訊["預定開始"] == 1791936000.0 and 資訊["遊戲"] == "Gaming"


def test_查YouTube直播_直播中_開播時間與分類():
    文 = 頁({"playabilityStatus": {"status": "OK"},
             "videoDetails": {"videoId": 影片, "channelId": 頻道ID, "author": "Sky News", "title": "t", "isLive": True},
             "microformat": {"playerMicroformatRenderer": {"category": "News & Politics", "liveBroadcastDetails": {
                 "isLiveNow": True, "startTimestamp": "2026-10-13T17:45:54+00:00"}}}})
    資訊 = si.查YouTube直播(f"https://youtu.be/{影片}", 假取得(文))
    assert 資訊["開播"] == datetime(2026, 10, 13, 17, 45, 54, tzinfo=UTC).timestamp()
    assert (資訊["直播主"], 資訊["遊戲"], 資訊["頻道ID"], 資訊["狀態"]) == ("Sky News", "News & Politics", 頻道ID, "OK")


def test_查YouTube直播_查不到或按了結束_回傳None():
    assert si.查YouTube直播(YT網址, 假取得("<html></html>")) is None
    停 = SimpleNamespace(is_set=lambda: True)
    assert si.查YouTube直播(YT網址, 假取得(還沒開始頁), 停) is None


def test_背景查詢_可以換查法(事件們):
    q = si.背景查詢(YT網址, 取得="假", 查法=lambda 網址, 取得, 停止: {"網址": 網址, "取得": 取得})
    assert q.等(最久=2) == {"網址": YT網址, "取得": "假"}
