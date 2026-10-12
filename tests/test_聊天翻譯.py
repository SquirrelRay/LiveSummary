"""聊天室翻譯（chat_translate.py）：跳過規則、批次、每分鐘上限與抽樣、逾時放棄、429 暫停、開關條件、用量分開記。
全部用假時鐘、假模型與假聊天資料，不呼叫 API、不連網。"""
import json
import re
import threading
import time

import pytest

import chat_translate as ct
import events
import llm
import subtitle


class 假時鐘:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t


class 假模型:
    """記下每次送出的留言；回傳「譯:原文」。例外 = 下次呼叫要丟的例外。"""

    def __init__(self):
        self.批們 = []
        self.例外 = None

    def __call__(self, 提示詞):
        留言們 = re.findall(r"^\d+\. (.*)$", 提示詞.split("留言：", 1)[1], re.MULTILINE)
        self.批們.append(留言們)
        if self.例外:
            raise self.例外
        llm._記用量(len(提示詞), 10 * len(留言們), "聊天翻譯")
        return json.dumps([f"譯:{t}" for t in 留言們], ensure_ascii=False)


@pytest.fixture
def 事件們(monkeypatch):
    收到 = []
    monkeypatch.setattr(events, "接收者們", [lambda 種類, 內容: 收到.append((種類, 內容))])
    return 收到


@pytest.fixture
def 器(monkeypatch, 事件們):
    monkeypatch.setattr(llm, "聊天翻譯用量", {"次數": 0, "輸入": 0, "輸出": 0, "缺token": 0})
    鐘 = 假時鐘()
    模型 = 假模型()
    d = ct.聊天翻譯器(時鐘=鐘)
    d.呼叫 = 模型
    d.開始(True, "ja", "假模型", 1.0, 5.0, 每分上限=30, 執行緒=False)
    d.面板開著 = True
    原 = d.處理一次

    def 處理後放出():                            # 測試沒有放出執行緒：每處理一次就檢查一次能不能顯示
        結果 = 原()
        d.放出一次()
        return 結果
    d.處理一次 = 處理後放出
    return d, 鐘, 模型


_號 = iter(range(1, 100000))


def 留言(d, 內容, 編號=None):
    d.接收("chat_line", {"秒": 0, "時間字": "00:00", "使用者": "u", "內容": 內容, "編號": 編號 or next(_號)})


def 顯示們(事件們):
    """chat_show 事件（照出現順序）：[(編號, 譯文)]，譯文 None = 以原文出現。"""
    return [(c["編號"], c["譯文"]) for 種, c in 事件們 if 種 == "chat_show"]


def 譯文們(事件們):
    return [(號, 譯) for 號, 譯 in 顯示們(事件們) if 譯]


# ---------- 跳過規則 ----------
@pytest.mark.parametrize("內容", [
    "草", "www", "ｗｗｗｗｗｗ", "wwwwwww", "草草草",                   # 草／www
    "888", "8888888", "７７７", "100!?", "1500",                       # 純數字（含 888）
    "え", "あああああ", "え？", "おおおお",                             # 單一字元重複
    "はい", "おつ", "お疲れ様", "かわいい", "ナイス！", "gg", "lol",      # 固定短語
    "hitomi32Hahaha hitomi32Hahaha", "k4senDecoy1", "akariO", "LUL", "KEKW",   # 純表情代碼
    "@someone", "@someone migiYAYA",                                   # 只有 @提及／表情
    "！？", "♡♡", "😂😂",                                               # 純符號、emoji
])
def test_短留言與表情代碼不送翻(內容):
    assert ct.要翻譯(內容, "ja") is False
    assert ct.跳過原因(內容) is not None


@pytest.mark.parametrize("內容", ["まだ言ってない", "パチンコ案件", "理由は強いから", "なっが", "初見です！"])
def test_一般日文留言送翻(內容):
    assert ct.要翻譯(內容, "ja") is True


@pytest.mark.parametrize("內容", ["全然大丈夫", "激熱", "過激派", "無理無理", "審査w"])
def test_全漢字的日文在日文直播中會送翻(內容):
    assert ct.要翻譯(內容, "ja") is True


def test_明顯是中文的留言不送翻():
    assert ct.要翻譯("你們好可愛喔", "ja") is False
    assert ct.要翻譯("這是什麼", "ja") is False


def test_表情代碼會被拿掉_只送文字():
    assert ct.去雜訊("@bob すごすぎ hitomi32Clap LUL") == "すごすぎ"


@pytest.mark.parametrize("語言", ["zh", "auto"])
def test_中文直播或還在偵測_一律不送翻(語言):
    assert ct.要翻譯("まだ言ってない", 語言) is False


def test_迷因對照放在提示詞裡_不認得的保留原文():
    p = ct.提示詞(["草生える"])
    for 原, 譯 in ct.迷因對照:
        assert f"{原}→{譯}" in p
    assert "保留原文" in p and "1. 草生える" in p
    assert ("草", "笑死") in [(a.split("、")[0], b.split("、")[0]) for a, b in ct.迷因對照]
    assert any("888" in a and b == "拍手" for a, b in ct.迷因對照)
    assert any("おつ" in a and b == "辛苦了" for a, b in ct.迷因對照)
    assert any("てぇてぇ" in a and b == "好貼" for a, b in ct.迷因對照)


# ---------- 批次：8 秒或 40 則 ----------
def test_沒滿8秒也沒滿40則就不送(器, 事件們):
    d, 鐘, 模型 = 器
    留言(d, "まだ言ってない", 1)
    留言(d, "保留やめて", 2)
    鐘.t += 7.9
    assert d.處理一次() is False and 模型.批們 == []
    鐘.t += 0.1                                 # 第一則進來滿 8 秒
    assert d.處理一次() is True
    assert 模型.批們 == [["まだ言ってない", "保留やめて"]]
    assert 譯文們(事件們) == [(1, "譯:まだ言ってない"), (2, "譯:保留やめて")]


def test_滿40則馬上送_一次最多40則(器):
    d, 鐘, 模型 = 器
    d.每分上限 = 600                            # 這個測試不受上限影響
    for i in range(45):
        留言(d, f"コメント{i}です")
    assert d.處理一次() is True                 # 0 秒，但已滿 40 則
    assert len(模型.批們[0]) == 40
    assert d.處理一次() is False                # 剩 5 則：沒滿 40 則、也沒滿 8 秒
    鐘.t += 8
    assert d.處理一次() is True and len(模型.批們[1]) == 5


# ---------- 每分鐘上限與抽樣 ----------
def test_抽樣平均分布且保留順序():
    assert ct.抽樣(list(range(40)), 4) == [0, 10, 20, 30]
    assert ct.抽樣([1, 2, 3], 5) == [1, 2, 3]
    assert ct.抽樣([1, 2, 3], 0) == []


def test_熱門台每分鐘不超過上限_沒抽到的不送(器):
    d, 鐘, 模型 = 器
    送出 = []                                    # (時間, 則數)
    for _ in range(0, 180, 2):                   # 三分鐘、每 2 秒 12 則 = 每分鐘 360 則
        for _ in range(12):
            留言(d, "パチンコ案件だ")
        鐘.t += 2
        n = len(模型.批們)
        d.處理一次()
        if len(模型.批們) > n:
            送出.append((鐘.t, len(模型.批們[-1])))
    for t0, _ in 送出:                           # 任何 60 秒視窗內都不超過上限 30
        assert sum(n for t, n in 送出 if t0 <= t < t0 + 60) <= 30
    assert sum(n for _, n in 送出) >= 75          # 三分鐘接近上限
    每分 = [sum(n for t, n in 送出 if 1000 + 60 * k <= t < 1060 + 60 * k) for k in range(3)]
    assert min(每分) >= 20                       # 每一分鐘都有翻到（平均分散，不是一開始送滿就停）
    assert d.統計["抽樣略過"] > 900               # 大部分沒抽到：只顯示原文
    assert all(n <= ct.批次則數 for _, n in 送出)


def test_每批額度依間隔按比例_中等量不會被砍(器):
    d, 鐘, 模型 = 器
    for _ in range(3):                           # 每 8 秒 2 則 = 每分鐘 15 則，低於上限 30
        留言(d, "なんか違う")
        留言(d, "保留やめて")
        鐘.t += 8
        d.處理一次()
    assert [len(b) for b in 模型.批們] == [2, 2, 2]
    assert d.統計["抽樣略過"] == 0


def test_上限照設定值_一次爆量最多翻上限的一半(器):
    d, 鐘, 模型 = 器
    d.每分上限 = 5
    for _ in range(40):
        留言(d, "まだ言ってない")
    d.處理一次()
    assert len(模型.批們[0]) == 3               # 額度桶最多裝上限的一半（5 → 3），剩下的平均分散在這一分鐘
    鐘.t += 60
    for _ in range(40):
        留言(d, "保留やめて")
    d.處理一次()
    assert len(模型.批們[1]) == 3               # 一分鐘後桶子補滿（不會超過容量）


def test_剛送完一批馬上又滿40則_仍有額度不會整批丟掉(器):
    d, _, 模型 = 器
    for _ in range(40):
        留言(d, "まだ言ってない")
    d.處理一次()
    for _ in range(40):
        留言(d, "保留やめて")
    d.處理一次()                                 # 同一秒：桶裡還剩 15 − 15 = 0 → 這批沒額度
    assert [len(b) for b in 模型.批們] == [15]
    d.每分上限 = 600                             # 換成很高的上限：剛送完也還有額度
    d._額度 = None
    for _ in range(40):
        留言(d, "なっが")
    d.處理一次()
    assert len(模型.批們[-1]) == 40


# ---------- 超過 20 秒的留言放棄翻譯 ----------
def test_排隊超過20秒的留言放棄翻譯(器, 事件們):
    d, 鐘, 模型 = 器
    留言(d, "古いコメント", 1)                   # 例如前一批呼叫很慢，輪到時這則已經等了 21 秒
    鐘.t += 13
    留言(d, "新しいコメント", 2)
    鐘.t += 8                                    # 舊的等了 21 秒、新的等了 8 秒
    d.處理一次()
    assert d.統計["逾時放棄"] == 1
    assert 模型.批們 == [["新しいコメント"]]
    assert [x[0] for x in 譯文們(事件們)] == [2]


def test_剛好20秒還會送(器):
    d, 鐘, 模型 = 器
    留言(d, "古いコメント")
    鐘.t += 20
    d.處理一次()
    assert 模型.批們 == [["古いコメント"]]


# ---------- 429：暫停 60 秒、不重送 ----------
def test_收到429暫停60秒且不重送(器, 事件們):
    d, 鐘, 模型 = 器
    模型.例外 = llm.限速錯誤("429")
    留言(d, "まだ言ってない", 1)
    鐘.t += 8
    assert d.處理一次() is True
    assert len(模型.批們) == 1 and 譯文們(事件們) == []
    assert any(種 == "info" and "速率限制" in c["印出"] for 種, c in 事件們)
    模型.例外 = None
    for _ in range(6):                           # 暫停中：新留言不翻、被 429 的那則也不重送
        留言(d, "保留やめて")
        鐘.t += 9
        d.處理一次()
    assert len(模型.批們) == 1
    assert d.統計["限速放棄"] >= 2
    鐘.t += 10                                   # 已超過 60 秒
    留言(d, "暫停後のコメント", 99)
    鐘.t += 8
    d.處理一次()
    assert 模型.批們[-1] == ["暫停後のコメント"]  # 只有新留言，沒有重送舊的
    assert 譯文們(事件們) == [(99, "譯:暫停後のコメント")]


def test_429時字幕翻譯照常送出_不被延遲(monkeypatch, 事件們):
    """聊天室翻譯的呼叫卡住、接著收到 429 暫停，字幕翻譯的批次照樣在同一個（假）時間點送出。"""
    鐘 = 假時間()
    monkeypatch.setattr(subtitle, "time", 鐘)
    monkeypatch.setattr(subtitle, "批次秒數", 8)
    monkeypatch.setattr(subtitle, "批次句數", 4)
    monkeypatch.setattr(subtitle, "要翻譯", lambda *a: True)
    monkeypatch.setattr(llm, "聊天翻譯用量", {"次數": 0, "輸入": 0, "輸出": 0, "缺token": 0})
    monkeypatch.setattr(llm, "預先載入", lambda: None)
    字幕批們 = []
    字 = 啟動字幕器(字幕批們)

    卡住 = threading.Event()
    放行 = threading.Event()
    聊天呼叫 = []

    def 聊天模型(提示詞):
        聊天呼叫.append(鐘.t)
        卡住.set()
        放行.wait(5)
        raise llm.限速錯誤("429")

    聊 = ct.聊天翻譯器(時鐘=鐘.time)
    聊.呼叫 = 聊天模型
    聊.開始(True, "ja", "假模型", 1.0, 5.0)
    聊.面板開著 = True
    try:
        for i in range(40):                      # 滿 40 則：聊天翻譯馬上送出，然後卡在 API
            留言(聊, f"コメント{i}です")
        assert 等(卡住.is_set)
        字.接收("transcript_line", {"內容": "字幕一", "時間字": "[00:00]"})
        assert 等(lambda: 字幕批們)      # 聊天翻譯卡著，字幕第一批照樣送出
        assert 字幕批們[0] == (100.0, ["字幕一"])  # 假時鐘沒有前進：零延遲
        放行.set()                               # 聊天翻譯收到 429 → 暫停 60 秒
        assert 等(lambda: 聊._暫停到 > 0)
        for i in range(4):
            字.接收("transcript_line", {"內容": f"字幕{i + 2}", "時間字": "[00:01]"})
            留言(聊, f"暫停中{i}です")
        assert 等(lambda: len(字幕批們) == 2)
        assert 字幕批們[1] == (100.0, ["字幕2", "字幕3", "字幕4", "字幕5"])   # 滿 4 句就送，同樣零延遲
        鐘.t += 30
        time.sleep(0.5)
        assert len(聊天呼叫) == 1                 # 暫停中沒有再呼叫，也沒有重送
    finally:
        放行.set()
        聊.結束()
        字._停.set()
        字._執行緒.join(2)


class 假時間:
    """給 subtitle 模組用的假 time（和 test_first_subtitle_latency 同一種）；呼叫 .time() 拿假時間。"""

    def __init__(self):
        self.t = 100.0

    def time(self):
        return self.t

    def strftime(self, *a):
        return time.strftime(*a)

    def sleep(self, s):
        time.sleep(s)


def 啟動字幕器(送出的批):
    """真的字幕器背景執行緒（字幕翻譯的邏輯完全不動），只把呼叫模型的 _翻 換成記錄送出時間。"""
    d = subtitle.字幕器()
    d.啟用 = True
    d._翻 = lambda 批: (送出的批.append((subtitle.time.time(), [x[2] for x in 批])), [""] * len(批))[1]
    d.模式, d.語言 = "translate", "ja"
    d._停 = threading.Event()
    d._收尾 = threading.Event()
    d._已送過首批 = False
    d._執行緒 = threading.Thread(target=d._跑, daemon=True)
    d._執行緒.start()
    return d


def 等(條件, 秒=3):
    終 = time.time() + 秒
    while time.time() < 終:
        if 條件():
            return True
        time.sleep(0.02)
    return 條件()


# ---------- 開關條件：面板開著且外語直播才翻 ----------
@pytest.mark.parametrize("情境", ["面板關", "中文直播", "設定關", "自動偵測中"])
def test_不符條件時呼叫為0(器, 情境):
    d, 鐘, 模型 = 器
    if 情境 == "面板關":
        d.面板開著 = False
    elif 情境 == "中文直播":
        d.語言 = "zh"
    elif 情境 == "設定關":
        d.開啟 = False
    else:
        d.語言 = "auto"
    for _ in range(50):
        留言(d, "まだ言ってない")
    鐘.t += 10
    d.處理一次()
    assert 模型.批們 == [] and llm.聊天翻譯用量["次數"] == 0


def test_偵測到外語後才開始翻(器):
    d, 鐘, 模型 = 器
    d.語言 = "auto"
    留言(d, "まだ言ってない")
    d.接收("language_detected", {"語言": "ja"})
    留言(d, "保留やめて")
    鐘.t += 8
    d.處理一次()
    assert 模型.批們 == [["保留やめて"]]


def test_中途關掉面板_排隊中的也不翻(器):
    d, 鐘, 模型 = 器
    留言(d, "まだ言ってない")
    d.面板開著 = False
    鐘.t += 8
    d.處理一次()
    assert 模型.批們 == []


# ---------- 用量依類別分開 ----------
def test_用量記在聊天翻譯_不混進摘要與逐句翻譯(器, monkeypatch, 事件們):
    monkeypatch.setattr(llm, "用量", {"次數": 0, "輸入": 0, "輸出": 0, "缺token": 0})
    monkeypatch.setattr(llm, "翻譯用量", {"次數": 0, "輸入": 0, "輸出": 0, "缺token": 0})
    d, 鐘, _ = 器
    留言(d, "まだ言ってない")
    鐘.t += 8
    d.處理一次()
    assert llm.聊天翻譯用量["次數"] == 1
    assert llm.用量["次數"] == 0 and llm.翻譯用量["次數"] == 0
    狀態 = [c for 種, c in 事件們 if 種 == "status"]
    assert 狀態[-1]["聊天翻譯次數"] == 1 and 狀態[-1]["聊天翻譯費用"] > 0
    assert "聊天室翻譯（另計）：呼叫 1 次" in d.統計文字()


def test_模型回答讀不出來_只顯示原文不重送(器, 事件們):
    d, 鐘, 模型 = 器
    d.呼叫 = lambda p: (模型.批們.append(p), "抱歉")[1]
    留言(d, "まだ言ってない")
    鐘.t += 8
    d.處理一次()
    鐘.t += 30
    d.處理一次()
    assert len(模型.批們) == 1 and 譯文們(事件們) == [] and d.統計["失敗"] == 1


# ---------- 顯示排隊：原文與譯文一起出現、照原本順序、最多等 20 秒 ----------
def test_留言先暫留_譯文回來才和原文一起出現(器, 事件們):
    d, 鐘, _ = 器
    內容 = {"秒": 0, "時間字": "00:00", "使用者": "u", "內容": "まだ言ってない", "編號": 1}
    d.接收("chat_line", 內容)
    assert 內容["暫留"] is True                 # 介面看到 暫留 就不立刻顯示
    d.放出一次()
    assert 顯示們(事件們) == []                 # 譯文還沒回來：不顯示
    鐘.t += 8
    d.處理一次()
    assert 顯示們(事件們) == [(1, "譯:まだ言ってない")]
    事件 = next(c for 種, c in 事件們 if 種 == "chat_show")
    assert (事件["使用者"], 事件["內容"], 事件["時間字"]) == ("u", "まだ言ってない", "00:00")


def test_跳過與翻譯的留言照原本順序一起出現(器, 事件們):
    d, 鐘, _ = 器
    留言(d, "まだ言ってない", 1)
    留言(d, "草", 2)                            # 跳過：不翻，但不能比第 1 則先出現
    留言(d, "hitomi32Hahaha", 3)
    留言(d, "保留やめて", 4)
    留言(d, "www", 5)
    d.放出一次()
    assert 顯示們(事件們) == []
    鐘.t += 8
    d.處理一次()
    assert 顯示們(事件們) == [(1, "譯:まだ言ってない"), (2, None), (3, None), (4, "譯:保留やめて"), (5, None)]


def test_前面沒有等譯文的_跳過的留言馬上出現(器, 事件們):
    d, _, _ = 器
    留言(d, "草", 1)
    d.放出一次()
    assert 顯示們(事件們) == [(1, None)]


def test_抽樣略過的留言以原文和同一批一起出現(器, 事件們):
    d, _, _ = 器
    d.每分上限 = 4                              # 桶子 2 則
    for i in range(1, 41):
        留言(d, f"コメント{i}です", i)
    d.處理一次()
    出現 = 顯示們(事件們)
    assert [號 for 號, _ in 出現] == list(range(1, 41))      # 40 則全部照順序出現
    assert sum(1 for _, 譯 in 出現 if 譯) == 2 and d.統計["抽樣略過"] == 38


@pytest.mark.parametrize("情境", ["失敗", "429", "讀不出來"])
def test_翻譯失敗或429_以原文出現不卡住(器, 事件們, 情境):
    d, 鐘, 模型 = 器
    if 情境 == "失敗":
        模型.例外 = RuntimeError("伺服器錯誤")
    elif 情境 == "429":
        模型.例外 = llm.限速錯誤("429")
    else:
        d.呼叫 = lambda p: "抱歉"
    留言(d, "まだ言ってない", 1)
    留言(d, "草", 2)
    鐘.t += 8
    d.處理一次()
    assert 顯示們(事件們) == [(1, None), (2, None)]


def test_排隊超過20秒放棄的留言以原文出現(器, 事件們):
    d, 鐘, _ = 器
    留言(d, "古いコメント", 1)
    鐘.t += 13
    留言(d, "新しいコメント", 2)
    鐘.t += 8
    d.處理一次()
    assert 顯示們(事件們) == [(1, None), (2, "譯:新しいコメント")]


def test_API很慢_最多20秒一定以原文出現_晚到的譯文不再補(器, 事件們):
    d, 鐘, _ = 器
    留言(d, "まだ言ってない", 1)
    留言(d, "草", 2)
    鐘.t += 19.9
    d.放出一次()                                # 翻譯呼叫還在進行中（處理一次沒有回來）
    assert 顯示們(事件們) == []
    鐘.t += 0.1
    d.放出一次()
    assert 顯示們(事件們) == [(1, None), (2, None)]
    d.排隊.定案(1, "太晚的譯文")                # 之後才回來：不再補上（避免閃動）
    d.放出一次()
    assert 顯示們(事件們) == [(1, None), (2, None)]


def test_中途關掉翻譯_排隊中的留言立刻以原文出現(器, 事件們):
    d, _, _ = 器
    留言(d, "まだ言ってない", 1)
    留言(d, "草", 2)
    d.開啟 = False
    d.放出一次()
    assert 顯示們(事件們) == [(1, None), (2, None)]


def test_結束時排隊中的留言全部出現(器, 事件們):
    d, _, _ = 器
    留言(d, "まだ言ってない", 1)
    d.結束()
    assert 顯示們(事件們) == [(1, None)]


def test_翻譯關著時不暫留_介面立刻顯示(器, 事件們):
    d, _, _ = 器
    d.開啟 = False
    內容 = {"秒": 0, "時間字": "00:00", "使用者": "u", "內容": "まだ言ってない", "編號": 1}
    d.接收("chat_line", 內容)
    assert "暫留" not in 內容 and len(d.排隊) == 0


# ---------- 第一批延遲：不超過批次秒數加 API 時間 ----------
def test_第一批譯文延遲不超過批次秒數加API時間(器, 事件們):
    d, 鐘, _ = 器
    API秒 = 3.0
    原呼叫 = d.呼叫

    def 慢的模型(p):
        鐘.t += API秒
        return 原呼叫(p)
    d.呼叫 = 慢的模型
    進來 = 鐘.t
    留言(d, "まだ言ってない", 1)
    while not 顯示們(事件們):
        鐘.t += 0.3                              # 和翻譯執行緒一樣每 0.3 秒看一次
        d.處理一次()
    assert 鐘.t - 進來 <= ct.批次秒數 + 0.3 + API秒
    assert 顯示們(事件們) == [(1, "譯:まだ言ってない")]


def test_開始時額度桶是滿的_第一批不會被砍(器):
    d, 鐘, 模型 = 器
    for i in range(10):
        留言(d, f"コメント{i}です")
    鐘.t += 8
    d.處理一次()
    assert len(模型.批們[0]) == 10


def test_翻譯執行緒一開始就先載入模型套件(monkeypatch):
    載入 = []
    monkeypatch.setattr(llm, "預先載入", lambda: 載入.append(1))
    d = ct.聊天翻譯器()
    d.開始(True, "ja", "m", 1, 5)
    try:
        for _ in range(100):
            if 載入:
                break
            time.sleep(0.01)
        assert 載入 == [1]
    finally:
        d.結束()


def test_里程碑記下第一批等了幾秒與API花幾秒(器, monkeypatch, tmp_path):
    import startup_timeline as st
    d, 鐘, _ = 器
    紀 = st.里程碑紀錄(資料夾=str(tmp_path), 時鐘=鐘)
    monkeypatch.setattr(st, "紀錄", 紀)
    紀.開始()
    原呼叫 = d.呼叫

    def 慢的模型(p):
        鐘.t += 3.0
        return 原呼叫(p)
    d.呼叫 = 慢的模型
    留言(d, "まだ言ってない")
    鐘.t += 8
    d.處理一次()
    留言(d, "保留やめて")
    鐘.t += 8
    d.處理一次()
    with open(紀.路徑, encoding="utf-8") as f:
        內容 = f.read()
    assert "[+   0.00s] " + st.聊天第一則 in 內容
    assert "[+   8.00s] " + st.聊天第一批送出 + "  | 則數=1，等了秒=8.0" in 內容
    assert "[+  11.00s] " + st.聊天第一批回來 + "  | API秒=3.0" in 內容
    assert "[+  11.00s] " + st.聊天第一則顯示 + "  | 有譯文=True" in 內容
    assert 內容.count(st.聊天第一批送出) == 1                 # 第二批不再記
