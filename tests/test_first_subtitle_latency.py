"""開始後第一句字幕的等待時間：auto 語言只看第一段有人聲的音訊、第一批翻譯不等批次秒數。
全部用假模型、假時鐘、假的音訊串流與假的翻譯函式，不連網、不呼叫 API、不需要 ffmpeg／streamlink。
"""
import threading
import time

import numpy as np
import pytest

import events
import live_capture as lc
import startup_timeline as st
import subtitle

小段 = 4            # 測試用的假分段位元組數（只在測試裡縮小，正式程式的 20 秒分段不變）


# ---------------- 語言偵測：只看第一段有人聲的音訊 ----------------
class 假時鐘:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


class 假管線:
    """p1／p2 共用：stdout.read 每次吐出一段，並讓假時鐘前進 20 秒（模擬真的要等 20 秒才收滿一段）。
    讀聲音的執行緒會搶先讀完，所以要等程式處理完上一段（送出 status 事件）才吐下一段，時鐘才對得上。"""

    def __init__(self, 段們, 時鐘):
        self.段們, self.時鐘 = list(段們), 時鐘
        self.stdout = self
        self.可讀 = threading.Semaphore(1)
        events.接收者們.append(lambda 種類, 內容: self.可讀.release() if 種類 == "status" else None)

    def read(self, n):
        self.可讀.acquire(timeout=5)
        self.時鐘.t += 20
        return self.段們.pop(0) if self.段們 else b""

    def close(self):
        pass

    def kill(self):
        pass


def 音(振幅):
    return (np.full(小段, 振幅, dtype=np.int16)).tobytes()


靜音, 人聲, 音樂 = 音(0), 音(8000), 音(3000)      # 音樂：音量夠大，但假的 VAD 認為沒有人聲


@pytest.fixture
def 流程(monkeypatch, tmp_path):
    時鐘 = 假時鐘()
    紀 = st.里程碑紀錄(資料夾=str(tmp_path), 時鐘=時鐘)
    monkeypatch.setattr(st, "紀錄", 紀)
    紀.開始()
    monkeypatch.setattr(lc, "每段位元組", 小段)
    monkeypatch.setattr(lc, "取樣率", 2)                       # 4 位元組 = 2 個取樣 = 1 秒，只影響紀錄裡的「實際秒」
    monkeypatch.setattr(lc, "含人聲", lambda a: bool(np.abs(a).max() >= 0.2))     # 假 VAD：只有 8000 以上算人聲
    偵測到 = []
    monkeypatch.setattr(lc, "載入模型", lambda 語言: object())
    monkeypatch.setattr(lc, "偵測語言", lambda model, 音訊們: (偵測到.append(len(音訊們)), "ja")[1])
    monkeypatch.setattr(lc, "轉錄一段", lambda model, 音訊, 語言: [(0.5, "こんにちは")])
    events.停止.clear()
    events.接收者們.clear()

    def 跑(段們, 語言="auto"):
        管線 = 假管線(段們, 時鐘)
        monkeypatch.setattr(lc.subprocess, "Popen", lambda *a, **k: 管線)
        s = object.__new__(lc.live_session)
        s.網址, s.串流名, s.ffmpeg, s.語言 = "https://x/fake", "audio_only", "ffmpeg", 語言
        s.稿路徑, s.存稿, s.音訊資料夾, s.聊天 = str(tmp_path / "稿.txt"), False, None, None
        s.存了段數 = s.存了位元組 = 0
        s._警告過 = False
        list(s)
        return 紀, 偵測到, s

    return 跑


def 秒數(紀, 名稱):
    with open(紀.路徑, encoding="utf-8") as f:
        for 行 in f:
            if 名稱 in 行:
                return float(行.split("+")[1].split("s")[0])
    return None


def test_auto_第一段有人聲_馬上偵測_不等3段(流程):
    紀, 偵測到, s = 流程([人聲, 人聲, 人聲])
    收滿, 偵測 = 秒數(紀, st.第一段收滿), 秒數(紀, st.語言偵測完成)
    assert 偵測 - 收滿 <= 1
    assert 偵測到 == [1]              # 只用了 1 段來偵測
    assert s.語言 == "ja"


def test_auto_第一段靜音_等下一段有人聲才偵測_不硬判(流程):
    紀, 偵測到, _ = 流程([靜音, 人聲, 人聲])
    assert 偵測到 == [1]              # 靜音那段沒有被拿去偵測
    assert 秒數(紀, st.語言偵測完成) == 40.0      # 第 2 段（40 秒）才偵測


def test_auto_第一段只有音樂_也不硬判_等有人聲的段(流程):
    紀, 偵測到, _ = 流程([音樂, 靜音, 人聲])
    assert 偵測到 == [1]
    assert 秒數(紀, st.語言偵測完成) == 60.0      # 第 3 段才有人聲


def test_auto_一直沒有人聲_不會偵測也不會誤判(流程):
    紀, 偵測到, s = 流程([靜音, 音樂, 靜音])
    assert 偵測到 == [] and s.語言 == "auto"
    assert 秒數(紀, st.語言偵測完成) is None


def test_語言已指定時不做偵測(流程):
    _, 偵測到, _ = 流程([人聲, 人聲], 語言="ja")
    assert 偵測到 == []


def test_偵測緩存_偵測句數改回3仍可用(monkeypatch):
    monkeypatch.setattr(lc, "偵測句數", 3)
    monkeypatch.setattr(lc, "含人聲", lambda a: True)
    c = lc.偵測緩存()
    a = np.zeros(2, dtype=np.float32)
    assert c.加入(0, a) is None and c.加入(1, a) is None
    assert [n for n, _ in c.加入(2, a)] == [0, 1, 2]


# ---------------- 翻譯：第一批不等批次秒數，之後照 8 秒／4 句 ----------------
class 假時間:
    def __init__(self):
        self.t = 100.0

    def time(self):
        return self.t

    def strftime(self, *a):
        return time.strftime(*a)

    def sleep(self, s):
        time.sleep(s)


@pytest.fixture
def 字幕器(monkeypatch):
    鐘 = 假時間()
    monkeypatch.setattr(subtitle, "time", 鐘)
    monkeypatch.setattr(subtitle, "批次秒數", 8)
    monkeypatch.setattr(subtitle, "批次句數", 4)
    送出的批 = []
    d = subtitle.字幕器()
    d.啟用 = True
    d._翻 = lambda 批: (送出的批.append((鐘.t, [x[2] for x in 批])), [""] * len(批))[1]
    d.模式, d.語言 = "original", "ja"
    d._停 = threading.Event()
    d._收尾 = threading.Event()
    d._已送過首批 = False
    d._執行緒 = threading.Thread(target=d._跑, daemon=True)
    monkeypatch.setattr(subtitle, "要翻譯", lambda *a: True)
    d._執行緒.start()
    yield d, 鐘, 送出的批
    d._停.set()
    d._執行緒.join(2)


def 給句子(d, 句們):
    for i, 文字 in enumerate(句們):
        d.接收("transcript_line", {"內容": 文字, "時間字": f"[00:{i:02d}]"})


def 等(條件, 秒=1.5):
    終 = time.time() + 秒
    while time.time() < 終:
        if 條件():
            return True
        time.sleep(0.02)
    return False


def test_第一批只有2句_馬上送出不等8秒(字幕器):
    d, _, 批們 = 字幕器
    給句子(d, ["一", "二"])
    assert 等(lambda: 批們)                 # 假時鐘完全沒前進（0 秒），仍然送出了
    assert 批們[0] == (100.0, ["一", "二"])


def test_第一批只有1句_也馬上送出(字幕器):
    d, _, 批們 = 字幕器
    給句子(d, ["一"])
    assert 等(lambda: 批們)
    assert 批們[0][1] == ["一"]


def test_第一批之後照批次規則_沒滿4句也沒滿8秒就不送(字幕器):
    d, 鐘, 批們 = 字幕器
    給句子(d, ["一"])
    assert 等(lambda: len(批們) == 1)
    給句子(d, ["二", "三"])
    time.sleep(0.8)
    assert len(批們) == 1                   # 2 句、0 秒：不送
    鐘.t += 7.9
    time.sleep(0.8)
    assert len(批們) == 1                   # 7.9 秒：還不送
    鐘.t += 0.2                             # 8.1 秒
    assert 等(lambda: len(批們) == 2)
    assert 批們[1][1] == ["二", "三"]


def test_第一批之後滿4句就送(字幕器):
    d, _, 批們 = 字幕器
    給句子(d, ["一"])
    assert 等(lambda: len(批們) == 1)
    給句子(d, ["二", "三", "四", "五"])
    assert 等(lambda: len(批們) == 2)
    assert 批們[1][1] == ["二", "三", "四", "五"]
