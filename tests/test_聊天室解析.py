"""安全網測試：chat_capture 的 IRC 解析、機器人與洗版過濾。用假的 IRC 文字與假 socket，不連網。"""
import io
import re
import time

import pytest

import chat_capture as cc
import events


@pytest.fixture
def 事件們(monkeypatch):
    收到 = []
    monkeypatch.setattr(events, "接收者們", [lambda 種類, 內容: 收到.append((種類, 內容))])
    return 收到


# ---------- 私訊解析 ----------
def test_私訊格式解析出使用者與內容():
    m = cc.私訊.match(":alice!alice@alice.tmi.twitch.tv PRIVMSG #chan :你好 world")
    assert m.groups() == ("alice", "你好 world")


def test_內容裡有冒號也完整保留():
    m = cc.私訊.match(":bob!bob@bob.tmi.twitch.tv PRIVMSG #chan :時間 12:30 到了")
    assert m.group(2) == "時間 12:30 到了"


@pytest.mark.parametrize("行", [
    "PING :tmi.twitch.tv",
    ":tmi.twitch.tv 001 justinfan1 :Welcome, GLHF!",
    ":alice!alice@alice.tmi.twitch.tv JOIN #chan",
])
def test_不是私訊的行不吻合(行):
    assert cc.私訊.match(行) is None


# ---------- 機器人與洗版 ----------
@pytest.mark.parametrize("名稱,預期", [
    ("Nightbot", True), ("StreamElements", True), ("my_bot", True), ("Fossabot", True),
    ("alice", False), ("robert", False),
])
def test_是機器人(名稱, 預期):
    assert cc.是機器人(名稱) is 預期


@pytest.mark.parametrize("內容,預期", [
    ("LUL LUL LUL", True),        # 同一個字重複 3 次以上
    ("LUL LUL", False),           # 只有 2 次不算
    ("LUL KEKW LUL", False),
    ("！！！", True),             # 只有符號
    ("😂😂", True),
    ("哈哈", False),
    ("w", False),
    ("", True),
])
def test_是洗版(內容, 預期):
    assert cc.是洗版(內容) is 預期


# ---------- _處理：過濾與記錄 ----------
def 建立(起點=None):
    c = cc.聊天室("TestChan", None)
    c._起點 = 起點 if 起點 is not None else time.time() - 65
    return c


def test_正常留言被記錄並送出事件(事件們):
    c, 檔 = 建立(), io.StringIO()
    c._處理("alice", "你好", 檔)
    assert (c.收到, c.過濾) == (1, 0)
    秒, 人, 內容 = c.訊息們[0]
    assert (人, 內容) == ("alice", "你好") and 65 <= 秒 < 67
    assert re.fullmatch(r"\[01:0[56]\] alice: 你好\n", 檔.getvalue())
    assert 事件們[0][0] == "chat_line" and 事件們[0][1]["使用者"] == "alice"


def test_機器人指令洗版都被過濾(事件們):
    c, 檔 = 建立(), io.StringIO()
    c._處理("Nightbot", "歡迎光臨", 檔)
    c._處理("alice", "!discord", 檔)
    c._處理("bob", "LUL LUL LUL", 檔)
    c._處理("carol", "😂", 檔)
    assert (c.收到, c.過濾) == (4, 4)
    assert c.訊息們 == [] and 檔.getvalue() == "" and 事件們 == []


def test_取出只回傳開始秒之後到結束秒為止(事件們):
    c = cc.聊天室("c", None)
    c.訊息們 = [(10, "a", "x"), (20, "b", "y"), (30, "c", "z")]
    assert c.取出(10, 30) == [(20, "b", "y"), (30, "c", "z")]


def test_頻道名轉小寫():
    assert cc.聊天室("MyChan", None).頻道 == "mychan"


# ---------- _連線並讀取：用假 socket 餵 IRC 原始文字 ----------
class 假Socket:
    def __init__(self, 資料們, 聊天):
        self.資料們, self.聊天, self.送出的, self.關了 = list(資料們), 聊天, b"", False

    def settimeout(self, t):
        pass

    def sendall(self, b):
        self.送出的 += b

    def recv(self, n):
        if self.資料們:
            return self.資料們.pop(0)
        return b""

    def close(self):
        self.關了 = True


@pytest.fixture
def 假連線(monkeypatch):
    def 裝(資料們, 聊天):
        s = 假Socket(資料們, 聊天)
        monkeypatch.setattr(cc.socket, "create_connection", lambda *a, **k: object())
        monkeypatch.setattr(cc.ssl, "create_default_context",
                            lambda: type("C", (), {"wrap_socket": lambda self, raw, server_hostname=None: s})())
        return s
    return 裝


def test_讀取流程_PING回PONG_留言被處理_機器人被擋(事件們, 假連線):
    c = cc.聊天室("Chan", None)
    c._起點 = time.time()
    s = 假連線([
        b"PING :tmi.twitch.tv\r\n:alice!alice@alice.tmi.twitch.tv PRIVMSG #chan :hello world\r\n",
        b":nightbot!nightbot@nightbot.tmi.twitch.tv PRIVMSG #chan :bot talk\r\n",
    ], c)
    c._連線並讀取(io.StringIO())
    assert b"PONG :tmi.twitch.tv\r\n" in s.送出的
    assert b"JOIN #chan\r\n" in s.送出的 and b"NICK justinfan" in s.送出的
    assert [m[1:] for m in c.訊息們] == [("alice", "hello world")]
    assert (c.收到, c.過濾) == (2, 1)
    assert c.連線中 is True and s.關了


def test_一則訊息被切成兩次收到也能組回來(事件們, 假連線):
    c = cc.聊天室("chan", None)
    c._起點 = time.time()
    假連線([b":alice!alice@alice.tmi.twitch.tv PRIVMSG #chan :ab", b"cd\r\n"], c)
    c._連線並讀取(io.StringIO())
    assert [m[1:] for m in c.訊息們] == [("alice", "abcd")]


def test_中文留言被正確解碼(事件們, 假連線):
    c = cc.聊天室("chan", None)
    c._起點 = time.time()
    假連線([":alice!alice@alice.tmi.twitch.tv PRIVMSG #chan :笑死\r\n".encode()], c)
    c._連線並讀取(io.StringIO())
    assert c.訊息們[0][2] == "笑死"


@pytest.mark.parametrize("名稱", sorted(cc.機器人))
def test_名單中的機器人都會被擋(名稱):
    assert cc.是機器人(名稱) is True
    assert cc.是機器人(名稱.upper()) is True          # 不分大小寫


@pytest.mark.parametrize("名稱", ["SomeBot", "cool_BOT", "mychannelbot", "Bot"])
def test_以bot結尾的會被擋(名稱):
    assert cc.是機器人(名稱) is True


@pytest.mark.parametrize("名稱", ["Abbott", "Botan", "botanist", "robotfan", "bottle_man", "bot_lover99"])
def test_名稱含bot但不是以bot結尾的真人不該被當成機器人(名稱):
    assert cc.是機器人(名稱) is False
