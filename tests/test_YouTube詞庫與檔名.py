# YouTube 第 4 步：詞庫鍵（YT_頻道ID，各種網址格式同一份；查不到頻道 ID 不讀不寫）、輸出檔名（@帳號 → 頻道 ID → 影片 ID）、
# 名詞清單打開這一場正在用的同一份、上網查證的脈絡含標題；Twitch 全部照舊。全部用假資料，不連網。
import os
from types import SimpleNamespace

import pytest

import app
import config
import events
import glossary
import live_capture as lc
import live_topics as lt
import llm
import platforms
import stream_clock as sc
import stream_info as si
import web_verify as wv

頻道ID = "UCSJ4gkVC6NrvII8umztf0Ow"
影片 = "jfKfPfyJRdk"
Lofi = {"頻道ID": 頻道ID, "直播主": "Lofi Girl", "帳號": "@LofiGirl", "標題": "lofi hip hop radio 📚 beats to relax/study to",
        "分類": "Music", "遊戲": "Music", "開播": 1000.0, "直播中": True, "影片ID": 影片, "來源": "YouTube網頁"}

各種網址 = [
    f"https://www.youtube.com/watch?v={影片}",
    f"https://youtu.be/{影片}",
    f"https://www.youtube.com/live/{影片}",
    "https://www.youtube.com/@LofiGirl/live",
    "https://www.youtube.com/@LofiGirl",
    f"https://www.youtube.com/channel/{頻道ID}/live",
    f"https://m.youtube.com/watch?v={影片}",
    f"https://www.youtube.com/embed/live_stream?channel={頻道ID}",
    "https://www.youtube.com/c/LofiGirl/live",
]


@pytest.fixture(autouse=True)
def 乾淨(monkeypatch, tmp_path):
    monkeypatch.setattr(sc, "_目前", None)
    monkeypatch.setattr(sc, "_資訊", None)
    monkeypatch.setattr(glossary, "資料夾", str(tmp_path / "詞庫"))
    monkeypatch.setattr(glossary, "本場詞庫", None)
    monkeypatch.setattr(glossary, "本場沒詞庫原因", "")
    monkeypatch.setattr(lc, "time", SimpleNamespace(time=lambda: 1000.0 + 3600))     # 開播一小時（不是連續直播）
    收到 = []
    monkeypatch.setattr(events, "接收者們", [lambda 種類, 內容: 收到.append((種類, 內容))])
    events.停止.clear()
    yield 收到
    events.停止.clear()


def 印出(事件們):
    return [c.get("印出") or "" for k, c in 事件們 if k == "info"]


# ---------- live_session：詞庫名與輸出檔名 ----------
@pytest.fixture
def 開(monkeypatch, tmp_path):
    結果 = {}

    class 假背景查詢:
        def __init__(self, 頻道, 取得=None, 查法=None):
            pass

        def 等(self, *a, **k):
            return dict(結果["值"]) if 結果["值"] else None

    import chat_capture
    monkeypatch.setattr(si, "背景查詢", 假背景查詢)
    monkeypatch.setattr(lc, "檢查直播", lambda 網址, 查詢=None: "worst")
    monkeypatch.setattr(lc, "找ffmpeg", lambda: "ffmpeg")
    monkeypatch.setattr(chat_capture, "聊天室", lambda *a, **k: SimpleNamespace(存檔路徑=a[1]))

    def 跑(網址, 資訊=Lofi):
        結果["值"] = 資訊
        return lc.live_session(網址, 稿目錄=str(tmp_path), 存音訊=True)

    return 跑


def 檔名們(s):
    return [os.path.basename(p) for p in (s.稿路徑, s.音訊資料夾, s.聊天.存檔路徑)]


@pytest.mark.parametrize("網址", 各種網址)
def test_各種網址格式_都對到同一份詞庫_檔名用帳號(開, 網址):
    s = 開(網址)
    assert s.詞庫名 == f"YT_{頻道ID}"
    稿, 音訊, 聊天 = 檔名們(s)
    assert 稿.startswith("@LofiGirl_") and 稿.endswith("_直播稿.txt")
    assert 音訊.startswith("@LofiGirl_") and 音訊.endswith("_音訊")
    assert 聊天.startswith("@LofiGirl_") and 聊天.endswith("_聊天室.txt")
    for 名 in 檔名們(s):
        assert not 名.startswith(("live_", "watchv", "LofiGirl_", "c_"))


def test_沒有帳號_用頻道ID(開):
    s = 開(f"https://youtu.be/{影片}", dict(Lofi, 帳號=""))
    assert os.path.basename(s.稿路徑).startswith(f"{頻道ID}_") and s.詞庫名 == f"YT_{頻道ID}"


def test_查不到頻道ID_詞庫名是None_檔名用影片ID(開):
    s = 開(f"https://www.youtube.com/watch?v={影片}", None)
    assert s.詞庫名 is None
    assert os.path.basename(s.稿路徑).startswith(f"{影片}_")
    assert not os.path.basename(s.稿路徑).startswith("watchv")


def test_查不到資訊_網址看得出帳號就用帳號(開):
    s = 開("https://www.youtube.com/@LofiGirl/live", None)
    assert s.詞庫名 is None and os.path.basename(s.稿路徑).startswith("@LofiGirl_")


def test_頻道ID看起來不對_不當詞庫鍵(開):
    s = 開(f"https://youtu.be/{影片}", dict(Lofi, 頻道ID="watchv" + 影片))
    assert s.詞庫名 is None


def test_Twitch_詞庫名與檔名照舊(開):
    s = 開("https://www.twitch.tv/Taiji_99", {"開播": 1000.0, "直播主": "taiji", "標題": "t", "遊戲": "g", "來源": "GQL"})
    assert s.詞庫名 == "Taiji_99" == lc.頻道名稱("https://www.twitch.tv/Taiji_99")
    assert [n.split("_2")[0] for n in 檔名們(s)] == ["Taiji_99"] * 3


@pytest.mark.parametrize("網址, 資訊, 開頭", [
    ("https://www.youtube.com/@a", {"帳號": "@Lo:fi*Gi?rl"}, "@Lo_fi_Gi_rl"),
    ("https://www.youtube.com/@a", {"帳號": '@a<b>c|d"e/f\\g'}, "@a_b_c_d_e_f_g"),
    ("https://www.youtube.com/@a", {"帳號": "@名前 テスト\t"}, "@名前_テスト"),
    ("https://www.youtube.com/@a", {"帳號": "@x" + "y" * 100}, "@x" + "y" * 58),
    ("https://www.youtube.com/@a", {"帳號": "@"}, "@a"),
    ("https://www.youtube.com/@a", {"帳號": "@trailing."}, "@trailing"),
    (f"https://youtu.be/{影片}", {}, 影片),
    (f"https://www.youtube.com/channel/{頻道ID}", {}, 頻道ID),
    ("https://www.youtube.com/c/Name/live", {}, "YouTube"),
    ("https://www.youtube.com/c/Name/live", None, "YouTube"),
])
def test_檔名規則與Windows不合法字元(網址, 資訊, 開頭):
    結果 = lc.YouTube檔名開頭(網址, 資訊)
    assert 結果 == 開頭
    assert not any(c in 結果 for c in '\\/:*?"<>|\t\n ') and not 結果.endswith((".", " "))


def test_詞庫前綴和名詞清單按鈕同一個規則():
    import names_page
    assert lc.YouTube詞庫名({"頻道ID": 頻道ID}) == names_page.YouTube詞庫名(頻道ID)
    assert lc.YouTube詞庫名({}) is None and lc.YouTube詞庫名(None) is None


# ---------- live_topics.執行：用哪一份詞庫、查不到不讀不寫 ----------
class 一場:
    """假的 live_session（只給 執行() 需要的欄位）＋ 假引擎（記下拿到的詞庫，不跑模型）。"""

    def __init__(self, monkeypatch, tmp_path, 事件們):
        self.事件們, self.引擎拿到, self.目標們 = 事件們, [], []
        self.tmp = tmp_path
        monkeypatch.setattr(llm, "檢查金鑰", lambda *a: None)
        monkeypatch.setattr(lt, "存檔", {"摘要": False})
        monkeypatch.setattr(lc, "設定分段", lambda 秒: None)

        def 假引擎(行來源, *a, 詞庫=None, **k):
            self.引擎拿到.append(詞庫)
            self.目標們.append(app.主控台.名詞清單目標(self.假主控台()))    # 直播中從膠囊選單看名詞清單
            return 0
        monkeypatch.setattr(lt, "引擎", 假引擎)
        self.查證們 = []
        monkeypatch.setattr(wv, "背景查證", lambda 詞庫, 脈絡, 模型: self.查證們.append(脈絡) or None)
        monkeypatch.setattr(llm, "支援上網查證", lambda: True)
        self.mp = monkeypatch

    def 假主控台(self):
        def 不該查(網址):
            raise AssertionError("直播中不應該另外查頻道、打開別份詞庫")
        self.mp.setattr(app.names_page, "頻道", 不該查)
        網址框 = SimpleNamespace(text=lambda: self.網址)
        return SimpleNamespace(執行中=lambda: True, 直播鈕=SimpleNamespace(isChecked=lambda: True), 網址框=網址框)

    def 跑(self, 網址, 平台, 詞庫名, 資訊=Lofi, **設定改):
        self.網址 = 網址
        稿 = str(self.tmp / "out" / "x_直播稿.txt")
        sc.設定目前(sc.時軸(開播=1000.0), 資訊)
        self.mp.setattr(sc, "清除", lambda: None)         # 執行() 一開始會清時軸；這裡要保留假資訊
        假 = SimpleNamespace(稿路徑=稿, 聊天=None, 平台=平台, 詞庫名=詞庫名)
        self.mp.setattr(lc, "live_session", lambda *a, **k: 假)
        設定 = config.出廠預設() | {"save_summary": False} | 設定改
        return lt.執行(設定, 網址=網址)


@pytest.fixture
def 場(monkeypatch, tmp_path, 乾淨):
    return 一場(monkeypatch, tmp_path, 乾淨)


def test_YouTube_用YT頻道ID的詞庫_名詞清單打開同一個物件(場, tmp_path):
    詞庫檔 = tmp_path / "詞庫" / f"YT_{頻道ID}.txt"
    詞庫檔.parent.mkdir()
    詞庫檔.write_text("# 說明\n咖啡廳｜カフェ｜手動\n", encoding="utf-8")
    assert 場.跑("https://www.youtube.com/watch?v=" + 影片, platforms.YOUTUBE, f"YT_{頻道ID}") is True
    詞庫 = 場.引擎拿到[0]
    assert 詞庫 is not None and 詞庫.路徑 == str(詞庫檔) and 詞庫.條目們[0].寫法 == "咖啡廳"
    名, 本場, 原因 = 場.目標們[0]
    assert 本場 is 詞庫 and 名 == f"YT_{頻道ID}" and 原因 == ""          # 名詞清單打開的就是引擎正在用的那一個
    assert 詞庫.標示 == f"Lofi Girl（@LofiGirl），YouTube 頻道 {頻道ID}"   # 新建詞庫檔時開頭的寫法和名詞清單按鈕一樣
    assert any(x.startswith(f"已載入詞庫：YT_{頻道ID}") for x in 印出(場.事件們))


def test_YouTube_兩種網址_同一份詞庫檔(場):
    場.跑("https://www.youtube.com/watch?v=" + 影片, platforms.YOUTUBE, f"YT_{頻道ID}")
    場.跑("https://www.youtube.com/@LofiGirl/live", platforms.YOUTUBE, f"YT_{頻道ID}")
    assert 場.引擎拿到[0].路徑 == 場.引擎拿到[1].路徑


def test_YouTube_查不到頻道ID_不讀不寫詞庫_印一行_名詞清單停用(場, tmp_path):
    資料夾 = tmp_path / "詞庫"
    assert 場.跑("https://www.youtube.com/watch?v=" + 影片, platforms.YOUTUBE, None, web_verify=True) is True
    assert 場.引擎拿到 == [None]
    assert not 資料夾.exists() or os.listdir(資料夾) == []                  # 沒有多出任何詞庫檔
    assert lt.YouTube沒頻道ID in 印出(場.事件們)
    assert not any(x.startswith("已載入詞庫") for x in 印出(場.事件們))
    assert glossary.本場詞庫 is None
    名, 本場, 原因 = 場.目標們[0]
    assert (名, 本場) == (None, None) and 原因 == lt.本場沒詞庫                # 膠囊選單停用並寫原因，不另外打開別份
    assert 場.查證們 == []
    assert "上網查證：這一場沒有使用詞庫（查不到 YouTube 頻道 ID），不查證。" in 印出(場.事件們)


def test_下一場重新登記_停用原因清掉(場):
    場.跑("https://www.youtube.com/watch?v=" + 影片, platforms.YOUTUBE, None)
    assert glossary.本場沒詞庫原因
    場.跑("https://www.twitch.tv/taiji", platforms.TWITCH, "taiji")
    assert glossary.本場沒詞庫原因 == "" and 場.目標們[1][1] is 場.引擎拿到[1]


def test_Twitch_詞庫照舊用頻道名稱_檔頭照舊(場, tmp_path):
    場.跑("https://www.twitch.tv/taiji", platforms.TWITCH, "taiji", 資訊={"直播主": "Taiji", "遊戲": "Minecraft", "標題": "t"})
    詞庫 = 場.引擎拿到[0]
    assert 詞庫.路徑 == str(tmp_path / "詞庫" / "taiji.txt") and 詞庫.標示 == "taiji"
    assert lt.YouTube沒頻道ID not in 印出(場.事件們)


# ---------- 上網查證的脈絡 ----------
def test_YouTube查證脈絡含標題_提示詞註明分類很粗(場):
    場.跑("https://www.youtube.com/@LofiGirl/live", platforms.YOUTUBE, f"YT_{頻道ID}", web_verify=True)
    脈絡 = 場.查證們[0]
    assert 脈絡["標題"] == Lofi["標題"] and 脈絡["分類"] == "Music" and 脈絡["直播主"] == "Lofi Girl"
    提示 = wv.提示詞(glossary.條目("X", "エックス", "候選"), 脈絡, [])
    assert f"直播標題：{Lofi['標題']}" in 提示
    assert "直播分類／遊戲：Music" + wv.YouTube分類說明 in 提示


def test_Twitch查證脈絡與提示詞照舊(場):
    場.跑("https://www.twitch.tv/taiji", platforms.TWITCH, "taiji", 資訊={"直播主": "Taiji", "遊戲": "Minecraft", "標題": "挖礦"},
         web_verify=True)
    脈絡 = 場.查證們[0]
    assert 脈絡 == {"直播主": "Taiji", "分類": "Minecraft", "標題": "挖礦"}
    e = glossary.條目("X", "エックス", "候選")
    舊 = wv.查證提示.format(原文="エックス", 寫法="X", 直播主="Taiji", 分類="Minecraft", 標題="挖礦", 句子="（沒有找到）")
    assert wv.提示詞(e, 脈絡, []) == 舊 and wv.YouTube分類說明 not in 舊
