"""直播主專有名詞詞庫（glossary.py 與 live_topics 的串接）。
假模型回覆、詞庫一律放在 tmp_path，不碰真的 詞庫/ 資料夾、不花 API。"""
import json
import os
from pathlib import Path

import pytest

import config
import events
import glossary
import live_topics as lt
import llm
import summarize


@pytest.fixture(autouse=True)
def 暫存詞庫(monkeypatch, tmp_path):
    資料夾 = tmp_path / "詞庫"
    monkeypatch.setattr(glossary, "資料夾", str(資料夾))
    return 資料夾


def 寫(路徑, 文字):
    os.makedirs(os.path.dirname(路徑), exist_ok=True)
    with open(路徑, "w", encoding="utf-8") as f:
        f.write(文字)


def 讀(路徑):
    with open(路徑, encoding="utf-8") as f:
        return f.read()


摘要本體 = (
    "【話題標題】討論新作遊戲\n"
    "【時間範圍】00:00 - 05:00\n"
    "【摘要】實況主聊到艾連（エレン）。\n"
    "【重點】\n"
    "- [01:00] 重點一\n"
    "【支線】無"
)


# ---------- (a) 解析【名詞】並從內文拿掉 ----------
def test_名詞清單被解析並從內文移除():
    內文, 名詞們 = glossary.拆名詞(摘要本體 + "\n【名詞】艾連（エレン）；米卡莎（ミカサ）；台北")
    assert 內文 == 摘要本體
    assert 名詞們 == [("艾連", "エレン"), ("米卡莎", "ミカサ"), ("台北", "")]


def test_名詞清單換行寫成條列也拿得掉():
    內文, 名詞們 = glossary.拆名詞(摘要本體 + "\n【名詞】\n- 艾連（エレン）\n- 米卡莎(ミカサ)")
    assert 內文 == 摘要本體 and "【名詞】" not in 內文
    assert 名詞們 == [("艾連", "エレン"), ("米卡莎", "ミカサ")]


def test_名詞寫成無():
    內文, 名詞們 = glossary.拆名詞(摘要本體 + "\n【名詞】無")
    assert 內文 == 摘要本體 and 名詞們 == []


# ---------- (b) 不確定的不收 ----------
def test_不確定的不進詞庫(tmp_path):
    _, 名詞們 = glossary.拆名詞(摘要本體 + "\n【名詞】艾連（エレン）；ほげ（不確定）；某人（なにか、不確定）；ミカサ（ミカサ）；誰？")
    assert 名詞們 == [("艾連", "エレン")]      # 不確定、寫法還是假名、帶問號的都不收
    庫 = glossary.詞庫("某主")
    庫.自動加入(名詞們)
    assert [e.寫法 for e in 庫.條目們] == ["艾連"]


def test_寫反的對調_日文字形與片段不收():
    # 第一次真模型重跑實際出現過的寫法
    _, 名詞們 = glossary.拆名詞(摘要本體 + "\n【名詞】ルパン（魯邦三世）；弾丸論破（彈丸論破）；桃鉄（桃太郎電鉄）；"
                                   "秋葉原無關；北海道；工藤新一（工藤新一）")
    assert 名詞們 == [("魯邦三世", "ルパン"), ("彈丸論破", "弾丸論破"), ("北海道", ""), ("工藤新一", "")]


# ---------- (c) 手動資料不被動、原文不重複 ----------
def test_自動加入不覆蓋不刪除手動且原文不重複(暫存詞庫):
    路徑 = str(暫存詞庫 / "某主.txt")
    原本 = "# 說明\n艾倫｜エレン｜手動\n阿爾敏｜アルミン\n莉維\n"
    寫(路徑, 原本)
    庫 = glossary.詞庫("某主")
    新的 = 庫.自動加入([("艾連", "エレン"), ("米卡莎", "ミカサ"), ("莉維", ""), ("米卡莎", "ミカサ")])
    assert [e.顯示() for e in 新的] == ["米卡莎（ミカサ）"]
    文字 = 讀(路徑)
    assert 文字.startswith(原本)                      # 手動的行（含格式省略的）原樣保留
    assert 文字.count("ミカサ") == 1 and "艾連" not in 文字
    assert 庫.自動加入([("米卡莎", "ミカサ")]) == []      # 第二次不重複加
    assert 讀(路徑) == 文字


def test_稿裡沒出現的名詞不收也不算用到(暫存詞庫, monkeypatch):
    # 第二次真模型重跑看到的情況：模型把詞庫整串抄進【名詞】，但這一題根本沒提到
    庫 = 做詞庫(暫存詞庫, ["栗松｜クリマツ｜自動", "北海道｜｜自動"])
    稿 = "[00:10] エレンが来た\n[00:20] ミカサも"
    新的 = 庫.自動加入([("艾連", "エレン"), ("米卡莎", "ミカサ"), ("栗松", "クリマツ"), ("秋葉原無", "秋葉原無"),
                     ("阿爾敏", "アルミン")], 原稿=稿)
    assert [e.寫法 for e in 新的] == ["艾連", "米卡莎"]
    assert "クリマツ" not in "".join(map(str, 庫._用過)) and "栗松" not in "".join(map(str, 庫._用過))
    monkeypatch.setattr(glossary, "上限", 3)          # 用到的自動名詞優先：艾連、米卡莎排在沒用到的前面
    assert "栗松" not in 庫.提示段() and "艾連" in 庫.提示段()


def test_直播中使用者手動改過檔案也不會被蓋掉(暫存詞庫):
    路徑 = str(暫存詞庫 / "某主.txt")
    庫 = glossary.詞庫("某主")
    庫.自動加入([("艾連", "エレン")])
    with open(路徑, "a", encoding="utf-8") as f:
        f.write("韓吉｜ハンジ｜手動\n")               # 直播中用記事本加的
    庫.自動加入([("米卡莎", "ミカサ")])
    文字 = 讀(路徑)
    assert "韓吉｜ハンジ｜手動" in 文字 and "艾連｜エレン｜自動" in 文字 and "米卡莎｜ミカサ｜自動" in 文字


# ---------- (d) 存讀一致、檔案不存在、格式錯的行 ----------
def test_存檔後重新讀入內容相同(暫存詞庫):
    庫 = glossary.詞庫("某主")
    庫.自動加入([("艾連", "エレン"), ("台北", "")])
    再讀 = glossary.詞庫("某主")
    assert [(e.寫法, e.原文, e.來源) for e in 再讀.條目們] == [("艾連", "エレン", "自動"), ("台北", "", "自動")]
    assert [(e.寫法, e.原文, e.來源) for e in 再讀.條目們] == [(e.寫法, e.原文, e.來源) for e in 庫.條目們]


def test_檔案不存在當作空的而且不會建立(暫存詞庫):
    庫 = glossary.詞庫("沒這個人")
    assert 庫.條目們 == [] and 庫.提示段("任何") == ""
    assert 庫.自動加入([]) == []
    assert not os.path.exists(庫.路徑)


def test_格式錯的行略過但保留在檔案裡(暫存詞庫):
    路徑 = str(暫存詞庫 / "某主.txt")
    原本 = "艾倫｜エレン｜手動\n這行｜欄位｜太多｜了\n怪來源｜ア｜朋友說的\n｜沒寫法\n"
    寫(路徑, 原本)
    庫 = glossary.詞庫("某主")
    assert [e.寫法 for e in 庫.條目們] == ["艾倫"] and 庫.格式錯 == 3
    庫.自動加入([("米卡莎", "ミカサ")])
    assert 讀(路徑) == 原本 + "米卡莎｜ミカサ｜自動\n"


def test_讀不懂的檔案不寫入(暫存詞庫):
    路徑 = str(暫存詞庫 / "某主.txt")
    os.makedirs(暫存詞庫)
    with open(路徑, "wb") as f:
        f.write("艾倫｜エレン｜手動\n".encode("big5", errors="replace") + b"\xff\xfe\xfa")
    原本 = Path(路徑).read_bytes()
    庫 = glossary.詞庫("某主")
    assert 庫.讀錯誤 and 庫.自動加入([("米卡莎", "ミカサ")]) == []
    assert Path(路徑).read_bytes() == 原本


# ---------- (e)(f) 提示詞 ----------
def 做詞庫(暫存詞庫, 行們):
    寫(str(暫存詞庫 / "某主.txt"), "\n".join(行們) + "\n")
    return glossary.詞庫("某主")


def test_超過上限時手動優先(暫存詞庫, monkeypatch):
    monkeypatch.setattr(glossary, "上限", 3)
    庫 = 做詞庫(暫存詞庫, ["自一｜ジ1｜自動", "手一｜テ1｜手動", "自二｜ジ2｜自動", "手二｜テ2"])
    段 = 庫.提示段()
    assert "手一（テ1）" in 段 and "手二（テ2）" in 段
    assert "自二（ジ2）" in 段 and "自一" not in 段          # 自動的取較晚加入的
    assert "自一（ジ1）" in 庫.提示段("今日はジ1の話")           # 出現在稿裡的自動名詞優先


class 環境:
    def __init__(self, monkeypatch, 摘要回覆):
        self.事件們, self.提示們, self.摘要提示們 = [], [], []
        monkeypatch.setattr(events, "接收者們", [lambda 種類, 內容: self.事件們.append((種類, 內容))])
        events.停止.clear()
        monkeypatch.setattr(lt, "統計", {"分鐘摘要": 0, "JSON失敗": 0})
        monkeypatch.setattr(lt, "存檔", {"摘要": False})
        monkeypatch.setattr(llm, "摘要_思考", True)

        def 假模型(提示詞):
            self.提示們.append(提示詞)
            return json.dumps({"decision": "same", "topic": "聊遊戲", "topic_brief": "簡述", "side_notes": []})

        def 假摘要(文字, 類型=None, 聊天室紀錄=None, 格式=None):
            self.摘要提示們.append(文字 + "\n" + (格式 or ""))
            return 摘要回覆
        monkeypatch.setattr(summarize, "call_llm", 假模型)
        monkeypatch.setattr(summarize, "summarize_chunk", 假摘要)

    def 跑(self, 詞庫):
        行們 = [(s, f"[{s // 60:02d}:{s % 60:02d}] エレンの話" + "字" * 110) for s in range(0, 301, 60)]
        return lt.引擎(iter(行們), 1, "不會寫的檔案", 詞庫=詞庫)

    def 話題內文(self):
        return [c["內文"] for k, c in self.事件們 if k == "topic_summary"]

    def 資訊(self):
        return [c.get("印出") or "" for k, c in self.事件們 if k == "info"]


def test_詞庫出現在問話題與話題摘要的提示詞(暫存詞庫, monkeypatch):
    e = 環境(monkeypatch, 摘要本體 + "\n【名詞】艾倫（エレン）")
    庫 = 做詞庫(暫存詞庫, ["艾倫｜エレン｜手動"])
    e.跑(庫)
    assert e.提示們 and all("【直播主詞庫】" in p and "艾倫（エレン）" in p for p in e.提示們)
    assert "【直播主詞庫】" in e.摘要提示們[0] and "艾倫（エレン）" in e.摘要提示們[0]
    assert "【名詞】" in e.摘要提示們[0]                      # 有詞庫才請模型列名詞
    assert e.話題內文() == [摘要本體]                         # 顯示的內文沒有名詞清單
    assert not any("詞庫新增" in x for x in e.資訊())         # 已存在的原文不重複加


def test_詞庫是空的時提示詞不出現詞庫段落_但會自動加入(暫存詞庫, monkeypatch):
    e = 環境(monkeypatch, 摘要本體 + "\n【名詞】艾連（エレン）")
    庫 = glossary.詞庫("某主")
    e.跑(庫)
    assert e.提示們 and not any("【直播主詞庫】" in p for p in e.提示們)
    assert "【直播主詞庫】" not in e.摘要提示們[0]
    assert e.話題內文() == [摘要本體]
    assert "詞庫新增：艾連（エレン）" in e.資訊()
    assert "艾連｜エレン｜自動" in 讀(庫.路徑)


def test_有詞庫時話題摘要存檔也沒有名詞清單(暫存詞庫, monkeypatch, tmp_path):
    e = 環境(monkeypatch, 摘要本體 + "\n【名詞】艾連（エレン）")
    monkeypatch.setattr(lt, "存檔", {"摘要": True})
    輸出 = str(tmp_path / "話題.md")
    行們 = [(s, f"[{s // 60:02d}:{s % 60:02d}] エレンの話" + "字" * 110) for s in range(0, 301, 60)]
    lt.引擎(iter(行們), 1, 輸出, 詞庫=glossary.詞庫("某主"))
    存的 = 讀(輸出)
    assert "【名詞】" not in 存的 and "【支線】無" in 存的
    assert e.話題內文() == [摘要本體]


# ---------- (h) 清單格式錯誤時摘要照常 ----------
@pytest.mark.parametrize("回覆", [
    摘要本體,                                   # 模型沒給清單
    摘要本體 + "\n【名詞】",                      # 空的
    摘要本體 + "\n【名詞】（）；｜｜；" + "長" * 50,   # 看不懂
])
def test_清單格式錯誤時摘要照常輸出(暫存詞庫, monkeypatch, 回覆):
    e = 環境(monkeypatch, 回覆)
    庫 = glossary.詞庫("某主")
    assert e.跑(庫) == 1
    assert e.話題內文() == [摘要本體]
    assert 庫.條目們 == [] and not os.path.exists(庫.路徑)


def test_詞庫存檔失敗時摘要照常(暫存詞庫, monkeypatch):
    e = 環境(monkeypatch, 摘要本體 + "\n【名詞】艾連（エレン）")

    def 壞掉(*a, **k):
        raise OSError("磁碟滿了")
    monkeypatch.setattr(glossary, "安全寫入", 壞掉)
    e.跑(glossary.詞庫("某主"))
    assert e.話題內文() == [摘要本體]
    assert any("詞庫存檔失敗" in x for x in e.資訊())


# ---------- (g) 文字稿模式沒指定直播主 ----------
def 跑執行(monkeypatch, tmp_path, 直播主=None):
    稿 = tmp_path / "稿.txt"
    稿.write_text("\n".join(f"[{s // 60:02d}:{s % 60:02d}] エレンの話" + "字" * 110 for s in range(0, 301, 60)),
                 encoding="utf-8")
    monkeypatch.setattr(llm, "檢查金鑰", lambda: None)
    e = 環境(monkeypatch, 摘要本體 + "\n【名詞】艾連（エレン）")
    設定 = config.出廠預設() | {"save_summary": False, "language": "ja"}
    assert lt.執行(設定, 檔案=str(稿), 直播主=直播主) is True
    return e


def test_文字稿模式沒指定直播主就不讀不寫詞庫(暫存詞庫, monkeypatch, tmp_path):
    寫(str(暫存詞庫 / "某主.txt"), "艾倫｜エレン｜手動\n")
    e = 跑執行(monkeypatch, tmp_path)
    assert not any("【直播主詞庫】" in p for p in e.提示們 + e.摘要提示們)
    assert not any("【名詞】" in p for p in e.摘要提示們)        # 提示詞和原本一樣
    assert e.話題內文() == [摘要本體]
    assert not any("詞庫" in x for x in e.資訊())
    assert os.listdir(暫存詞庫) == ["某主.txt"] and 讀(str(暫存詞庫 / "某主.txt")) == "艾倫｜エレン｜手動\n"


def test_文字稿模式指定直播主就讀入並自動加入(暫存詞庫, monkeypatch, tmp_path):
    寫(str(暫存詞庫 / "某主.txt"), "米卡莎｜ミカサ｜手動\n")
    e = 跑執行(monkeypatch, tmp_path, 直播主="某主")
    assert "已載入詞庫：某主，1 個名詞" in e.資訊()
    assert all("米卡莎（ミカサ）" in p for p in e.提示們)
    assert "詞庫新增：艾連（エレン）" in e.資訊()
    assert 讀(str(暫存詞庫 / "某主.txt")) == "米卡莎｜ミカサ｜手動\n艾連｜エレン｜自動\n"


def test_直播主名字轉成安全檔名():
    assert glossary.檔名安全('a/b:c*?"<>| d') == "a_b_c_d"
    assert glossary.檔名安全(None) == "" and glossary.檔名安全("  ") == ""
