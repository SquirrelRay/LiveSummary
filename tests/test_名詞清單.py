"""名詞清單：在介面上訂正詞庫的名字寫法（glossary 的清單操作、names_page 視窗、膠囊選單與啟動面板入口）。
詞庫一律放在 tmp_path，假模型、不連網，不碰真的 詞庫/ 資料夾。"""
import json
import os
import threading
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
import test_介面冒煙 as 冒煙
from PySide6.QtWidgets import QAbstractItemDelegate, QLineEdit, QMenu

import events
import glossary
import live_topics as lt
import llm
import names_page
import summarize
import web_verify as wv

qapp, 環境 = 冒煙.qapp, 冒煙.環境          # fixture：和冒煙測試共用


@pytest.fixture(autouse=True)
def 暫存詞庫(monkeypatch, tmp_path):
    資料夾 = tmp_path / "詞庫"
    monkeypatch.setattr(glossary, "資料夾", str(資料夾))
    monkeypatch.setattr(glossary, "本場詞庫", None)
    return 資料夾


def 寫(路徑, 文字):
    os.makedirs(os.path.dirname(路徑), exist_ok=True)
    with open(路徑, "w", encoding="utf-8") as f:
        f.write(文字)


def 讀(路徑):
    with open(路徑, encoding="utf-8") as f:
        return f.read()


def 做詞庫(資料夾, 行們, 名="某主"):
    寫(str(資料夾 / f"{名}.txt"), "\n".join(行們) + "\n")
    return glossary.詞庫(名)


def 找(庫, 原文):
    return next(e for e in 庫.清單() if e.原文 == 原文)


# ---------- glossary：改寫法、確認、刪除（忽略）、新增 ----------
def test_改寫法變成手動_存檔後重新讀入相同(暫存詞庫):
    庫 = 做詞庫(暫存詞庫, ["# 說明行", "曼太郎｜マン太郎｜候選", "艾倫｜エレン｜手動", "壞掉的行｜a｜b｜c｜d"])
    庫.改寫法(找(庫, "マン太郎"), " Mantarou ")
    行們 = 讀(庫.路徑).splitlines()
    assert 行們 == ["# 說明行", "Mantarou｜マン太郎｜手動", "艾倫｜エレン｜手動", "壞掉的行｜a｜b｜c｜d"]   # 其他行原樣
    新庫 = glossary.詞庫("某主")
    e = 找(新庫, "マン太郎")
    assert (e.寫法, e.來源) == ("Mantarou", "手動")
    assert [(x.寫法, x.原文, x.來源) for x in 新庫.條目們] == [(x.寫法, x.原文, x.來源) for x in 庫.條目們]   # 記憶體＝檔案
    assert "Mantarou（マン太郎）" in 庫.提示段()


def test_改寫法保留上網網址_拿掉已查(暫存詞庫):
    庫 = 做詞庫(暫存詞庫, ["閃電十一人｜稻妻イレブン｜上網｜https://zh.wikipedia.org/x", "稻妻｜イナズマ｜候選｜已查"])
    庫.改寫法(找(庫, "稻妻イレブン"), "閃電11人")
    庫.改寫法(找(庫, "イナズマ"), "Inazuma")
    assert 讀(庫.路徑).splitlines() == ["閃電11人｜稻妻イレブン｜手動｜https://zh.wikipedia.org/x", "Inazuma｜イナズマ｜手動"]


@pytest.mark.parametrize("寫法", ["", "   ", "a｜b", "a|b", "#開頭", "字" * 31])
def test_顯示寫法不合格不存(暫存詞庫, 寫法):
    庫 = 做詞庫(暫存詞庫, ["曼太郎｜マン太郎｜候選"])
    原本 = 讀(庫.路徑)
    with pytest.raises(glossary.詞庫錯誤):
        庫.改寫法(找(庫, "マン太郎"), 寫法)
    assert 讀(庫.路徑) == 原本


def test_確認把候選與上網升級成手動(暫存詞庫):
    庫 = 做詞庫(暫存詞庫, ["米卡莎｜ミカサ｜候選", "呼拉圈｜フラフープ｜上網｜https://a.example/x"])
    庫.確認(找(庫, "ミカサ"))
    庫.確認(找(庫, "フラフープ"))
    assert 讀(庫.路徑).splitlines() == ["米卡莎｜ミカサ｜手動", "呼拉圈｜フラフープ｜手動｜https://a.example/x"]
    assert "米卡莎（ミカサ）" in glossary.詞庫("某主").提示段()       # 下一場起也會用


def test_刪除變成忽略_清單與提示詞都不出現_行還在檔案裡(暫存詞庫):
    庫 = 做詞庫(暫存詞庫, ["蛋白粉｜プロテイン｜候選", "艾倫｜エレン｜手動"])
    庫._本場.add("プロテイン")                    # 這一場剛加入的候選：本來提示詞會用
    庫.忽略(找(庫, "プロテイン"))
    assert "蛋白粉｜プロテイン｜忽略" in 讀(庫.路徑).splitlines()
    assert [e.原文 for e in 庫.清單()] == ["エレン"]
    assert "蛋白粉" not in 庫.提示段() and "蛋白粉" not in glossary.詞庫("某主").提示段()
    assert glossary.詞庫("某主").數量() == (1, 0)


def test_刪除後同一原文再出現_不會被自動加回來_也不會被上網查證(暫存詞庫, monkeypatch):
    庫 = 做詞庫(暫存詞庫, ["蛋白粉｜プロテイン｜候選"])
    庫.忽略(找(庫, "プロテイン"))
    原本 = 讀(庫.路徑)
    assert 庫.自動加入([("高蛋白", "プロテイン")], 原稿="今日はプロテインを飲む") == []
    assert 讀(庫.路徑) == 原本
    assert 庫.待查證們() == [] and not 庫.還要查("プロテイン")
    assert 庫.套用查證("プロテイン", "高蛋白", "https://a.example/x") == 0
    assert 讀(庫.路徑) == 原本
    # 背景查證排隊中才被刪掉：輪到它時略過，不呼叫搜尋
    問過 = []
    monkeypatch.setattr(llm, "上網搜尋", lambda *a, **k: 問過.append(a) or {})
    monkeypatch.setattr(events, "接收者們", [])
    查 = wv.背景查證(庫, {}, "假模型")
    查.加入([glossary.條目("蛋白粉", "プロテイン", "候選")], ["[00:01] プロテイン"])
    查.收尾(5)
    assert 問過 == [] and 讀(庫.路徑) == 原本


def test_話題摘要再列出被刪的名詞_引擎不加回來(暫存詞庫, monkeypatch):
    庫 = 做詞庫(暫存詞庫, ["艾連｜エレン｜候選"])
    庫.忽略(找(庫, "エレン"))
    原本 = 讀(庫.路徑)
    引 = 假引擎環境(monkeypatch, 摘要 + "\n【名詞】艾連（エレン）")
    引.跑(庫)
    assert 讀(庫.路徑) == 原本
    assert not any("詞庫新增" in x for x in 引.資訊())


def test_新增_必填寫法_原文選填_同一個名詞不重複(暫存詞庫):
    庫 = glossary.詞庫("新主")
    庫.新增("曼太郎")                                   # 只有顯示寫法：建立檔案（附說明檔頭）
    庫.新增("Mantarou", "マン太郎")
    行們 = 讀(庫.路徑).splitlines()
    assert 行們[0].startswith("# 直播主專有名詞詞庫：新主")
    assert 行們[-2:] == ["曼太郎｜｜手動", "Mantarou｜マン太郎｜手動"]
    with pytest.raises(glossary.詞庫錯誤, match="已經有"):
        庫.新增("曼太郎2", "マン太郎")
    with pytest.raises(glossary.詞庫錯誤):
        庫.新增("  ", "マン")
    assert "Mantarou（マン太郎）" in 庫.提示段() and "曼太郎" in 庫.提示段()


def test_新增被忽略過的原文_以新增的手動為準(暫存詞庫):
    庫 = 做詞庫(暫存詞庫, ["蛋白粉｜プロテイン｜候選", "艾倫｜エレン｜手動"])
    庫.忽略(找(庫, "プロテイン"))
    庫.新增("Protein", "プロテイン")
    assert 讀(庫.路徑).splitlines() == ["艾倫｜エレン｜手動", "Protein｜プロテイン｜手動"]
    assert "Protein（プロテイン）" in 庫.提示段()


# ---------- 同時寫檔不互蓋 ----------
def test_與話題摘要自動加入_上網查證同時寫檔不互蓋(暫存詞庫, monkeypatch):
    待查 = [f"候選{i}｜コウホ{i}｜候選" for i in range(10)]
    改的 = [f"舊寫{i}｜カエル{i}｜候選" for i in range(10)]
    庫路徑 = str(暫存詞庫 / "某主.txt")
    寫(庫路徑, "\n".join(["艾倫｜エレン｜手動"] + 待查 + 改的) + "\n")
    原寫入 = glossary.安全寫入

    def 慢寫入(p, 文字):          # 拉長「重讀→寫檔」之間的空檔，沒有鎖的話一定會互蓋
        time.sleep(0.005)
        原寫入(p, 文字)
    monkeypatch.setattr(glossary, "安全寫入", 慢寫入)
    引擎庫, 查證庫, 視窗庫 = glossary.詞庫("某主"), glossary.詞庫("某主"), glossary.詞庫("某主")
    視窗條目 = {e.原文: e for e in 視窗庫.清單()}
    錯誤們 = []

    def 引擎():
        for i in range(10):
            引擎庫.自動加入([(f"新詞{i}", f"シンゴ{i}")])

    def 查證():
        for i in range(10):
            查證庫.套用查證(f"コウホ{i}".casefold(), f"確認{i}", f"https://x.example/{i}")

    def 視窗():
        try:
            for i in range(10):
                視窗庫.改寫法(視窗條目[f"カエル{i}"], f"Kaeru{i}")
                視窗庫.新增(f"手填{i}", f"テガキ{i}")
        except Exception as e:      # noqa: BLE001
            錯誤們.append(e)
    執行緒們 = [threading.Thread(target=f) for f in (引擎, 查證, 視窗)]
    for t in 執行緒們:
        t.start()
    for t in 執行緒們:
        t.join()
    assert 錯誤們 == []
    行們 = 讀(庫路徑).splitlines()
    assert "艾倫｜エレン｜手動" in 行們
    assert all(f"新詞{i}｜シンゴ{i}｜候選" in 行們 for i in range(10))
    assert all(f"確認{i}｜コウホ{i}｜上網｜https://x.example/{i}" in 行們 for i in range(10))
    assert all(f"Kaeru{i}｜カエル{i}｜手動" in 行們 for i in range(10))
    assert all(f"手填{i}｜テガキ{i}｜手動" in 行們 for i in range(10))
    assert len(行們) == 1 + 10 + 10 + 10 + 10


def test_記事本同時改檔不被蓋掉(暫存詞庫):
    庫 = 做詞庫(暫存詞庫, ["曼太郎｜マン太郎｜候選", "米卡莎｜ミカサ｜候選", "艾倫｜エレン｜手動"])
    清單 = {e.原文: e for e in 庫.清單()}           # 打開視窗時看到的樣子
    # 使用者同時用記事本：改了米卡莎那一行、新增一行、刪掉艾倫
    寫(庫.路徑, "曼太郎｜マン太郎｜候選\nMikasa｜ミカサ｜手動\n阿爾敏｜アルミン｜手動\n")
    庫.改寫法(清單["マン太郎"], "Mantarou")          # 沒被記事本動到的行：照改，記事本的修改都保留
    assert 讀(庫.路徑).splitlines() == ["Mantarou｜マン太郎｜手動", "Mikasa｜ミカサ｜手動", "阿爾敏｜アルミン｜手動"]
    with pytest.raises(glossary.已被改過):          # 記事本剛改過的那一行：不蓋掉
        庫.改寫法(清單["ミカサ"], "米卡莎2")
    with pytest.raises(glossary.已被改過):          # 記事本刪掉的行：不會被寫回來
        庫.忽略(清單["エレン"])
    assert 讀(庫.路徑).splitlines() == ["Mantarou｜マン太郎｜手動", "Mikasa｜ミカサ｜手動", "阿爾敏｜アルミン｜手動"]
    assert [e.寫法 for e in 庫.清單()] == ["Mantarou", "Mikasa", "阿爾敏"]


# ---------- 直播中改完，下一輪提示詞立刻用新寫法 ----------
摘要 = "【話題標題】聊天\n【時間範圍】00:00 - 05:00\n【摘要】實況主聊天。\n【重點】\n- [01:00] 重點\n【支線】無"


class 假引擎環境:
    def __init__(self, monkeypatch, 摘要回覆=摘要):
        self.事件們, self.提示們, self.摘要提示們 = [], [], []
        monkeypatch.setattr(events, "接收者們", [lambda 種類, 內容: self.事件們.append((種類, 內容))])
        events.停止.clear()
        monkeypatch.setattr(lt, "統計", {"分鐘摘要": 0, "JSON失敗": 0})
        monkeypatch.setattr(lt, "存檔", {"摘要": False})
        monkeypatch.setattr(llm, "摘要_思考", True)

        def 假模型(提示詞):
            self.提示們.append(提示詞)
            return json.dumps({"decision": "same", "topic": "聊遊戲", "topic_brief": "簡述", "side_notes": [],
                               "minute_summary": {"summary": "[01:00] 摘要", "audience": ""}})

        def 假摘要(文字, 類型=None, 聊天室紀錄=None, 格式=None):
            self.摘要提示們.append(文字 + "\n" + (格式 or ""))
            return 摘要回覆
        monkeypatch.setattr(summarize, "call_llm", 假模型)
        monkeypatch.setattr(summarize, "summarize_chunk", 假摘要)

    def 行們(self, 每輪前=None):
        for s in range(0, 301, 60):
            if 每輪前:
                每輪前(s)
            yield s, f"[{s // 60:02d}:{s % 60:02d}] マン太郎の話" + "字" * 110

    def 跑(self, 詞庫, 每輪前=None, 分鐘檔=None):
        return lt.引擎(self.行們(每輪前), 1, "不會寫的檔案", 分鐘檔=分鐘檔, 詞庫=詞庫)

    def 資訊(self):
        return [c.get("印出") or "" for k, c in self.事件們 if k == "info"]


def test_直播中改完寫法_下一輪換話題判斷分鐘摘要與話題摘要都用新寫法(暫存詞庫, monkeypatch):
    庫 = 做詞庫(暫存詞庫, ["曼太郎｜マン太郎｜手動"])
    monkeypatch.setattr(glossary, "本場詞庫", 庫)
    引 = 假引擎環境(monkeypatch)
    改了第幾輪 = []

    def 每輪前(秒):
        if len(引.提示們) == 1 and not 改了第幾輪:      # 第一輪判斷之後，使用者在名詞清單改了寫法
            視窗庫 = glossary.本場詞庫                    # 名詞清單視窗直播中改的就是引擎的那一個物件
            視窗庫.改寫法(找(視窗庫, "マン太郎"), "Mantarou")
            改了第幾輪.append(len(引.提示們))
    引.跑(庫, 每輪前, 分鐘檔="不會寫的分鐘檔")
    assert 改了第幾輪 == [1]
    assert "曼太郎（マン太郎）" in 引.提示們[0] and "Mantarou" not in 引.提示們[0]
    assert all("Mantarou（マン太郎）" in p and "曼太郎" not in p for p in 引.提示們[1:])
    assert len(引.提示們) >= 2 and all("minute_summary" in p for p in 引.提示們)       # 分鐘摘要也在同一次呼叫
    assert "Mantarou（マン太郎）" in 引.摘要提示們[-1] and "曼太郎" not in 引.摘要提示們[-1]
    assert 庫.出現過(找(庫, "マン太郎"))                 # 「這一場」欄：稿裡出現過


# ---------- 提示詞：羅馬拼音寫法與例外 ----------
def test_羅馬拼音寫法出現在提示詞的詞庫段_附上例外說明(暫存詞庫, monkeypatch):
    庫 = 做詞庫(暫存詞庫, ["Mantarou｜マン太郎｜手動", "艾倫｜エレン｜手動"])
    段 = 庫.提示段()
    assert "Mantarou（マン太郎）" in 段 and "艾倫（エレン）" in 段
    assert "羅馬拼音或英文時也照原樣寫" in 段 and "只限詞庫裡的名字" in 段
    引 = 假引擎環境(monkeypatch)
    引.跑(庫, 分鐘檔="不會寫的分鐘檔")
    for p in 引.提示們 + 引.摘要提示們:
        assert "Mantarou（マン太郎）" in p
        assert lt.夾雜規則 + lt.詞庫例外 in p                 # 「正文不可夾雜英文」那一句補上詞庫的例外


def test_沒有詞庫時夾雜英文的規則不變(暫存詞庫, monkeypatch):
    引 = 假引擎環境(monkeypatch)
    引.跑(None, 分鐘檔="不會寫的分鐘檔")
    for p in 引.提示們 + 引.摘要提示們:
        assert lt.夾雜規則 in p and lt.詞庫例外 not in p and "【直播主詞庫】" not in p


def test_執行時登記這一場的詞庫(暫存詞庫, monkeypatch):
    做詞庫(暫存詞庫, ["艾倫｜エレン｜手動"])
    登記 = []
    monkeypatch.setattr(lt, "引擎", lambda *a, **k: 登記.append(glossary.本場詞庫) or 0)
    monkeypatch.setattr(llm, "檢查金鑰", lambda *a: None)
    monkeypatch.setattr(events, "接收者們", [])
    稿 = 暫存詞庫.parent / "稿.txt"
    稿.write_text("[00:00] こんにちは\n", encoding="utf-8")
    import config
    設定 = dict(config.出廠預設(), save_summary=False, language="ja")
    lt.執行(設定, 檔案=str(稿), 直播主="某主")
    assert 登記[0] is not None and 登記[0].直播主 == "某主"
    lt.執行(設定, 檔案=str(稿))
    assert 登記[1] is None


# ---------- 網址 → 頻道 ----------
@pytest.mark.parametrize("網址, 頻道", [
    ("https://www.twitch.tv/abc_123", "abc_123"), ("twitch.tv/Abc123/", "Abc123"),
    ("https://m.twitch.tv/abc123?x=1", "abc123"),
])
def test_有效的頻道網址(網址, 頻道):
    assert names_page.頻道(網址) == (頻道, "")


@pytest.mark.parametrize("網址", ["", "abc", "https://www.youtube.com/abc", "https://www.twitch.tv/videos/123",
                                "https://www.twitch.tv/directory", "https://www.twitch.tv/abc/clip/x"])
def test_無效的網址有白話原因(網址):
    名, 原因 = names_page.頻道(網址)
    assert 名 is None and 原因


# ---------- 視窗 ----------
@pytest.fixture
def 框(qapp, monkeypatch):
    monkeypatch.setattr(names_page, "確認", lambda *a: True)
    w = names_page.名詞清單框()
    yield w
    w.計時器.stop()
    w.close()
    w.deleteLater()                  # 在 QApplication 還在時刪掉；留到程式結束才由 Python 回收會在關閉時當掉
    from PySide6.QtCore import QCoreApplication, QEvent
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


def 列文字(框, 欄):
    return [框.表.item(r, 欄).text() for r in range(框.表.rowCount())]


def test_視窗列出名詞_這一場出現過的排前面_來源用白話(暫存詞庫, 框):
    庫 = 做詞庫(暫存詞庫, ["艾倫｜エレン｜手動", "米卡莎｜ミカサ｜候選", "稻妻｜イナズマ｜候選｜已查",
                       "呼拉圈｜フラフープ｜上網｜https://a.example/x", "蛋白粉｜プロテイン｜忽略"])
    庫.記下出現("[00:01] ミカサとフラフープ")
    框.打開(庫, 本場=True)
    assert 列文字(框, names_page.原文欄) == ["ミカサ", "フラフープ", "エレン", "イナズマ"]
    assert 列文字(框, names_page.來源欄) == ["自動找到・未確認", "上網查到", "你填的", "自動找到・上網查無"]
    assert 列文字(框, names_page.這場欄) == ["●", "●", "", ""]
    assert 框.表.cellWidget(1, names_page.網址欄) is not None              # 上網的網址可以點
    assert not (框.表.item(0, names_page.原文欄).flags() & names_page.Qt.ItemIsEditable)    # 原文不能改
    assert 框.表.item(0, names_page.寫法欄).flags() & names_page.Qt.ItemIsEditable


def test_視窗改寫法_確認_刪除_新增(暫存詞庫, 框):
    庫 = 做詞庫(暫存詞庫, ["曼太郎｜マン太郎｜候選", "米卡莎｜ミカサ｜候選", "蛋白粉｜プロテイン｜候選"])
    框.打開(庫)
    框.表.item(0, names_page.寫法欄).setText("Mantarou")      # 等同雙擊改完按 Enter
    qapp_處理()
    assert "Mantarou｜マン太郎｜手動" in 讀(庫.路徑).splitlines()
    assert "已存檔" in 框.狀態字.text()
    框.表.selectRow(列文字(框, names_page.原文欄).index("ミカサ"))
    框.確認選取()
    assert "米卡莎｜ミカサ｜手動" in 讀(庫.路徑).splitlines()
    框.表.selectRow(列文字(框, names_page.原文欄).index("プロテイン"))
    框.刪除選取()
    assert "蛋白粉｜プロテイン｜忽略" in 讀(庫.路徑).splitlines()
    assert "プロテイン" not in 列文字(框, names_page.原文欄)
    框.新寫法.setText("Kaeru")
    框.新原文.setText("カエル")
    框.新增()
    assert 讀(庫.路徑).splitlines()[-1] == "Kaeru｜カエル｜手動"
    assert 框.新寫法.text() == "" and "カエル" in 列文字(框, names_page.原文欄)
    框.新寫法.setText("")
    框.新增()
    assert "顯示寫法" in 框.狀態字.text()


def test_視窗刪除要確認_取消就不動(暫存詞庫, 框, monkeypatch):
    庫 = 做詞庫(暫存詞庫, ["蛋白粉｜プロテイン｜候選"])
    原本 = 讀(庫.路徑)
    monkeypatch.setattr(names_page, "確認", lambda *a: False)
    框.打開(庫)
    框.表.selectRow(0)
    框.刪除選取()
    assert 讀(庫.路徑) == 原本


def qapp_處理():
    from PySide6.QtWidgets import QApplication
    QApplication.processEvents()
    QApplication.processEvents()


def test_有新候選或查證結果時自動更新_編輯中不打斷(暫存詞庫, 框):
    庫 = 做詞庫(暫存詞庫, ["曼太郎｜マン太郎｜候選"])
    框.打開(庫, 本場=True)
    庫.自動加入([("米卡莎", "ミカサ")])                 # 話題摘要剛加入新的候選
    框._看變化()
    assert "ミカサ" in 列文字(框, names_page.原文欄)
    庫.套用查證("ミカサ", "米卡莎", "https://a.example/m")    # 上網查證查到
    框._看變化()
    r = 列文字(框, names_page.原文欄).index("ミカサ")
    assert 框.表.item(r, names_page.來源欄).text() == "上網查到"
    # 使用者正在編輯一格，同時又有新的候選加入
    框.表.editItem(框.表.item(列文字(框, names_page.原文欄).index("マン太郎"), names_page.寫法欄))
    編輯框 = 框.表.findChild(QLineEdit)
    編輯框.setText("Manta")
    assert 框.編輯中()
    庫.自動加入([("艾倫", "エレン")])
    框._看變化()
    assert 框.編輯中() and 編輯框.text() == "Manta"          # 沒有被打斷或清掉
    assert "エレン" not in 列文字(框, names_page.原文欄)
    框.表.commitData(編輯框)
    框.表.closeEditor(編輯框, QAbstractItemDelegate.NoHint)
    qapp_處理()
    框._看變化()
    assert "エレン" in 列文字(框, names_page.原文欄)
    assert "Manta｜マン太郎｜手動" in 讀(庫.路徑).splitlines()


def test_記事本改檔後視窗自動更新(暫存詞庫, 框):
    庫 = 做詞庫(暫存詞庫, ["曼太郎｜マン太郎｜候選"])
    框.打開(庫)
    time.sleep(0.02)
    寫(庫.路徑, "曼太郎｜マン太郎｜候選\n阿爾敏｜アルミン｜手動\n")
    os.utime(庫.路徑, (time.time() + 5, time.time() + 5))
    框._看變化()
    assert "アルミン" in 列文字(框, names_page.原文欄)


def test_視窗操作到記事本剛改過的行_提示並重新載入(暫存詞庫, 框):
    庫 = 做詞庫(暫存詞庫, ["米卡莎｜ミカサ｜候選"])
    框.打開(庫)
    寫(庫.路徑, "Mikasa｜ミカサ｜手動\n")
    框.表.selectRow(0)
    框.刪除選取()
    assert 讀(庫.路徑) == "Mikasa｜ミカサ｜手動\n"
    assert "別處被改過" in 框.狀態字.text()
    assert 列文字(框, names_page.寫法欄) == ["Mikasa"]


def test_用記事本打開_沒有檔案先建立(暫存詞庫, 框, monkeypatch):
    打開們 = []
    monkeypatch.setattr(names_page, "用記事本打開", 打開們.append)
    庫 = glossary.詞庫("新主")
    框.打開(庫)
    框.打開記事本()
    assert 打開們 == [庫.路徑] and os.path.exists(庫.路徑)


# ---------- 入口：啟動面板按鈕、膠囊選單 ----------
選單們 = []          # 選單要留著，動作才不會被刪掉


def _名詞動作(台):
    m = QMenu()
    台.膠囊.填選單(m)
    選單們.append(m)
    return next(a for a in m.actions() if a.text().startswith("名詞清單"))


def test_啟動面板網址無效時按鈕停用並顯示原因(環境):
    台 = 環境["台"]
    啟 = 台.啟動面板
    啟.網址框.setText("")
    assert not 啟.名詞鈕.isEnabled() and "Twitch 頻道網址" in 啟.名詞原因.text()
    a = _名詞動作(台)
    assert not a.isEnabled() and "（" in a.text()             # 膠囊選單也停用並寫出原因
    啟.網址框.setText("https://www.twitch.tv/videos/123")
    assert not 啟.名詞鈕.isEnabled() and "VOD" in 啟.名詞原因.text()
    啟.網址框.setText("https://www.youtube.com/abc")
    assert not 啟.名詞鈕.isEnabled() and 啟.名詞原因.text()
    啟.網址框.setText("https://www.twitch.tv/某頻道abc")         # 不是英數字：不是有效頻道
    assert not 啟.名詞鈕.isEnabled()
    啟.網址框.setText("https://www.twitch.tv/test_names_x")
    assert 啟.名詞鈕.isEnabled() and "test_names_x" in 啟.名詞原因.text()
    assert _名詞動作(台).isEnabled() and _名詞動作(台).text() == "名詞清單"
    for 字 in (啟.名詞原因.text(), a.text()):
        assert "config" not in 字 and ".json" not in 字 and "詞庫/" not in 字


def test_啟動面板按鈕打開那位直播主的名詞清單(環境):
    台 = 環境["台"]
    做詞庫(__import__("pathlib").Path(glossary.資料夾), ["Mantarou｜マン太郎｜手動"], 名="test_names_x")
    台.啟動面板.網址框.setText("https://www.twitch.tv/test_names_x")
    台.啟動面板.名詞鈕.click()
    框 = 台.名詞清單框
    assert 框 is not None and 框.isVisible()
    assert 框.詞庫.直播主 == "test_names_x" and not 框.本場
    assert 列文字(框, names_page.寫法欄) == ["Mantarou"]
    框.close()


def test_直播中用這一場的詞庫_文字稿重播沒有直播主時停用(環境, monkeypatch):
    台 = 環境["台"]
    monkeypatch.setattr(台, "執行中", lambda: True)
    台.檔案鈕.setChecked(True)
    a = _名詞動作(台)
    assert not a.isEnabled() and "文字稿重播沒有指定直播主" in a.text()
    本場 = 做詞庫(__import__("pathlib").Path(glossary.資料夾), ["艾倫｜エレン｜手動"], 名="live_ch")
    monkeypatch.setattr(glossary, "本場詞庫", 本場)
    assert _名詞動作(台).isEnabled()
    台.開名詞清單()
    assert 台.名詞清單框.詞庫 is 本場 and 台.名詞清單框.本場
    台.名詞清單框.close()
    monkeypatch.setattr(台, "執行中", lambda: False)      # 還原：fixture 收尾會等「沒在執行」，不改回來要白等 15 秒
