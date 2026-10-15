"""聊天室翻譯的介面（offscreen）：翻譯開著時原文與譯文一起出現、照原本順序；失敗／429／超時以原文出現；最新在上／在下；
只看譯文；面板與語言與設定的開關條件；膠囊選單切換；狀態列、膠囊提示、結束統計；啟動面板與設定框的費用。
用假模型（聊天翻譯器.呼叫 換掉）、假引擎、假聊天資料，不花 API、不連網。"""
import json
import os
import re
import threading

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
import test_介面冒煙 as 冒煙
from PySide6.QtWidgets import QMenu

import app
import chat_translate
import config
import cost_estimate
import events
import llm
import panel

qapp, 環境 = 冒煙.qapp, 冒煙.環境          # 共用介面冒煙測試的 fixture（offscreen 主控台、暫存設定檔、假模型）
假引擎, 從啟動面板開始, 停止並等完, 等 = 冒煙.假引擎, 冒煙.從啟動面板開始, 冒煙.停止並等完, 冒煙.等


def 讀json(路徑):
    with open(路徑, encoding="utf-8") as f:
        return json.load(f)


# ---------- 文字清單：有譯文的留言原文與譯文一起出現 ----------
def 留言(編號, 內容, 譯文=None, 使用者="u"):
    return {"編號": 編號, "時間字": f"00:{編號:02d}", "使用者": f"{使用者}{編號}", "內容": 內容, "譯文": 譯文}


def 做清單(上限=100, 置頂=False):
    頁 = app.文字清單("聊天室")
    頁.設上限(上限)
    頁.設方向(置頂)
    return 頁


@pytest.mark.parametrize("置頂", [False, True])
def test_有譯文的留言_原文與譯文同一則一起出現(qapp, 置頂):
    頁 = 做清單(置頂=置頂)
    頁.加留言(留言(1, "まだ言ってない", "還沒說"))
    頁.加留言(留言(2, "草"))
    行們 = 頁.行文字()
    assert len(行們) == 2                                    # 譯文在同一則裡，沒有多出一行
    有譯 = 行們[1 if 置頂 else 0]
    assert "まだ言ってない" in 有譯 and "↳ 還沒說" in 有譯 and 有譯.index("まだ言ってない") < 有譯.index("還沒說")
    assert 行們[0 if 置頂 else 1].endswith("草") and "↳" not in 行們[0 if 置頂 else 1]


@pytest.mark.parametrize("置頂", [False, True])
def test_顯示上限與切換方向_譯文跟著那一則(qapp, 置頂):
    頁 = 做清單(上限=3, 置頂=置頂)
    for i in range(1, 6):
        頁.加留言(留言(i, f"コメント{i}", f"譯{i}" if i % 2 else None))
    行們 = 頁.行文字()
    順序 = [re.search(r"コメント(\d)", x).group(1) for x in 行們]
    assert 順序 == (["5", "4", "3"] if 置頂 else ["3", "4", "5"])
    for x in 行們:
        號 = int(re.search(r"コメント(\d)", x).group(1))
        assert (f"↳ 譯{號}" in x) == bool(號 % 2)
    頁.設方向(not 置頂)
    assert [re.search(r"コメント(\d)", x).group(1) for x in 頁.行文字()] == 順序[::-1]
    assert all(("↳" in x) == (int(re.search(r"コメント(\d)", x).group(1)) % 2 == 1) for x in 頁.行文字())


def test_只看譯文切換(qapp):
    頁 = 做清單()
    頁.加留言(留言(1, "まだ言ってない", "還沒說"))
    頁.加留言(留言(2, "保留やめて"))
    頁.設只看譯文(True)
    行們 = 頁.行文字()
    assert "還沒說" in 行們[0] and "まだ言ってない" not in 行們[0] and "↳" not in 行們[0]
    assert "保留やめて" in 行們[1]                           # 沒譯文的照樣顯示原文
    頁.加留言(留言(3, "なっが", "好長"))
    assert "好長" in 頁.行文字()[2] and "なっが" not in 頁.行文字()[2]
    頁.設只看譯文(False)
    assert "まだ言ってない" in 頁.行文字()[0] and "↳ 還沒說" in 頁.行文字()[0]


# ---------- 主控台與面板一起跑 ----------
class 假聊天模型:
    """放行：None = 馬上回答；Event = 等它被設起來才回答（用來確認譯文回來前留言不會出現）。例外：要丟的例外。"""

    def __init__(self):
        self.批們 = []
        self.放行 = None
        self.例外 = None

    def __call__(self, 提示詞):
        留言們 = re.findall(r"^\d+\. (.*)$", 提示詞.split("留言：", 1)[1], re.MULTILINE)
        self.批們.append(留言們)
        if self.放行 is not None:
            self.放行.wait(10)
        if self.例外:
            raise self.例外
        llm._記用量(100, 20, "聊天翻譯")
        return json.dumps([f"譯:{t}" for t in 留言們], ensure_ascii=False)


@pytest.fixture
def 聊天(環境, monkeypatch):
    monkeypatch.setattr(chat_translate, "批次秒數", 0)        # 不等 8 秒（批次規則另外用假時鐘測過）
    monkeypatch.setattr(llm, "預先載入", lambda: None)
    台 = 環境["台"]
    模型 = 假聊天模型()
    台.聊天翻譯器.呼叫 = 模型
    yield 台, 模型
    if 模型.放行 is not None:
        模型.放行.set()


_號 = iter(range(10_000, 99_999))


def 送留言(內容們):
    號們 = []
    for 內容 in 內容們:
        號 = next(_號)
        號們.append(號)
        events.送出("chat_line", 秒=0, 時間字="00:00", 使用者="viewer", 內容=內容, 編號=號)
    return 號們


def 開始外語直播(台, monkeypatch, 聊天翻譯=True):
    台.聊天翻譯器.開啟 = 聊天翻譯
    config.寫入設定({"chat_translate": 聊天翻譯})
    從啟動面板開始(台, monkeypatch, 假引擎())
    台.聊天翻譯器.語言 = "ja"


def 全部行(頁):
    """畫面上由舊到新的每一行（含聊天室翻譯的說明行；最新在上時倒回來）。"""
    行們 = 頁.行文字()
    return 行們[::-1] if 頁.置頂 else 行們


def 是說明行(行):
    return 行.startswith("（聊天室翻譯")


def 留言們(頁):
    """畫面上由舊到新的留言內容（不含說明行）。"""
    return [x for x in 全部行(頁) if not 是說明行(x)]


@pytest.mark.parametrize("置頂", [False, True])
def test_翻譯開啟_譯文回來前不顯示_回來後原文與譯文照順序一起出現(聊天, monkeypatch, 置頂):
    台, 模型 = 聊天
    開始外語直播(台, monkeypatch)
    台.設方向(置頂)
    台.面板.開關("聊天室", True)
    面 = 台.面板.面板們["聊天室"]
    模型.放行 = threading.Event()
    送留言(["まだ言ってない", "草", "hitomi32Hahaha", "保留やめて"])
    assert 等(lambda: 模型.批們, 10)                                  # 已經送去翻譯，模型還沒回答
    等(lambda: False, 0.6)
    assert 面.清單頁.行文字() == [] and 台.聊天頁.行文字() == []          # 跳過的「草」也不能先跑出來
    模型.放行.set()
    assert 等(lambda: len(留言們(面.清單頁)) == 4, 10), 面.清單頁.行文字()
    行們 = 留言們(面.清單頁)
    說明在 = [i for i, x in enumerate(全部行(面.清單頁)) if 是說明行(x)]
    assert len(說明在) == 1 and 全部行(面.清單頁)[說明在[0] + 1].endswith("草")    # 第一則不翻的留言前面說明一次
    assert 全部行(面.清單頁)[說明在[0]] == chat_translate.不翻說明
    assert "まだ言ってない" in 行們[0] and "↳ 譯:まだ言ってない" in 行們[0]
    assert 行們[1].endswith("草") and 行們[2].endswith("hitomi32Hahaha") and "↳" not in 行們[1] + 行們[2]   # 跳過的照原文
    assert "↳ 譯:保留やめて" in 行們[3]
    assert [t for 批 in 模型.批們 for t in 批] == ["まだ言ってない", "保留やめて"]   # 跳過的不送翻（批次 0 秒時可能分兩批）
    assert 等(lambda: len(留言們(台.聊天頁)) == 4)                      # 主控台的聊天室分頁也一樣（說明行也有）
    assert sum(map(是說明行, 台.聊天頁.行文字())) == 1
    assert [x.split(" ↳")[0] for x in 留言們(台.聊天頁)] == [x.split(" ↳")[0] for x in 行們]
    面.改字級(+2)                                                       # 換字級會重建清單：譯文還在
    assert "↳ 譯:まだ言ってない" in 留言們(台.面板.面板們["聊天室"].清單頁)[0]
    次數 = len(模型.批們)
    assert 等(lambda: 台.聊天翻譯藥丸.text().startswith(f"聊天翻譯 {次數} 次 · $"))
    assert not 台.聊天翻譯藥丸.isHidden() and f"聊天翻譯 {次數} 次" in 台.膠囊.提示文字()
    assert 台.膠囊.聊天翻譯費用 > 0 and 台.膠囊.總費用() >= 台.膠囊.聊天翻譯費用
    停止並等完(台)


@pytest.mark.parametrize("情境", ["失敗", "429", "超時"])
def test_翻譯失敗_429_超時_以原文出現不卡住(聊天, monkeypatch, 情境):
    台, 模型 = 聊天
    if 情境 == "失敗":
        模型.例外 = RuntimeError("伺服器錯誤")
    elif 情境 == "429":
        模型.例外 = llm.限速錯誤("429")
    else:                                                               # API 一直沒回來：最久顯示秒 到了就以原文出現
        monkeypatch.setattr(chat_translate, "最久顯示秒", 0.8)
        模型.放行 = threading.Event()
    開始外語直播(台, monkeypatch)
    台.面板.開關("聊天室", True)
    面 = 台.面板.面板們["聊天室"]
    送留言(["まだ言ってない", "草"])
    assert 等(lambda: len(留言們(面.清單頁)) == 2, 10), 面.清單頁.行文字()
    行們 = 留言們(面.清單頁)
    assert "まだ言ってない" in 行們[0] and 行們[1].endswith("草") and all("↳" not in x for x in 行們)
    說明們 = [x for x in 面.清單頁.行文字() if 是說明行(x)]
    assert chat_translate.不翻說明 in 說明們                            # 「草」不翻：說明一次
    assert any("沒翻成功（呼叫模型出錯）" in x for x in 說明們) == (情境 == "失敗")   # 失敗才說明失敗
    if 情境 == "超時":
        模型.放行.set()                                                 # 晚到的譯文不再補上
        等(lambda: False, 0.6)
        assert all("↳" not in x for x in 留言們(面.清單頁))
    停止並等完(台)


@pytest.mark.parametrize("情境", ["設定關", "面板關", "中文直播"])
def test_翻譯關閉時原文立刻顯示_翻譯呼叫為0(聊天, monkeypatch, 情境):
    台, 模型 = 聊天
    開始外語直播(台, monkeypatch, 聊天翻譯=情境 != "設定關")
    if 情境 != "面板關":
        台.面板.開關("聊天室", True)
    if 情境 == "中文直播":
        台.聊天翻譯器.語言 = "zh"
    送留言(["まだ言ってない", "保留やめて", "なっが"])
    assert 等(lambda: len(台.聊天頁.行文字()) == 3, 0.5)                # 不等翻譯：立刻出現
    if 情境 != "面板關":
        assert len(台.面板.面板們["聊天室"].清單頁.行文字()) == 3
    等(lambda: False, 1.0)                                              # 給翻譯執行緒時間：確認真的沒翻
    assert 模型.批們 == [] and llm.聊天翻譯用量["次數"] == 0
    停止並等完(台)


def test_結束時排隊中的留言全部出現(聊天, monkeypatch):
    台, 模型 = 聊天
    開始外語直播(台, monkeypatch)
    台.面板.開關("聊天室", True)
    模型.放行 = threading.Event()
    送留言(["まだ言ってない"])
    assert 等(lambda: 模型.批們, 10)
    停止並等完(台)
    assert 等(lambda: len(台.聊天頁.行文字()) == 1), 台.聊天頁.行文字()


def test_關掉聊天室面板_當場停止翻譯(聊天, monkeypatch):
    台, 模型 = 聊天
    開始外語直播(台, monkeypatch)
    台.面板.開關("聊天室", True)
    送留言(["まだ言ってない"])
    assert 等(lambda: len(模型.批們) == 1)
    台.面板.開關("聊天室", False)
    assert not 台.聊天翻譯器.面板開著
    送留言(["保留やめて"])
    等(lambda: False, 1.0)
    assert len(模型.批們) == 1
    停止並等完(台)


def 選單項(選單, 文字):
    for a in 選單.actions():
        if a.text() == 文字 or a.text().startswith(文字):
            return a
    raise AssertionError(f"選單裡沒有「{文字}」：{[a.text() for a in 選單.actions()]}")


def test_膠囊選單_聊天室翻譯開關當場生效並寫回設定(聊天, monkeypatch):
    台, 模型 = 聊天
    開始外語直播(台, monkeypatch, 聊天翻譯=False)
    台.面板.開關("聊天室", True)
    m = QMenu()
    台.膠囊.填選單(m)
    a = 選單項(m, "聊天室翻譯：")
    assert a.text() == "聊天室翻譯：關" and a.isCheckable() and not a.isChecked()
    a.setChecked(True)                                                  # 直播中切換：當場生效
    assert 台.聊天翻譯器.開啟
    assert 讀json(config.設定檔路徑)["chat_translate"] is True
    assert not 台.聊天翻譯藥丸.isHidden()
    送留言(["まだ言ってない"])
    assert 等(lambda: len(模型.批們) == 1)
    m2 = QMenu()
    台.膠囊.填選單(m2)
    a = 選單項(m2, "聊天室翻譯：")
    assert a.text() == "聊天室翻譯：開" and a.isChecked()
    a.setChecked(False)
    送留言(["保留やめて"])
    等(lambda: False, 1.0)
    assert len(模型.批們) == 1
    停止並等完(台)


def test_只看譯文_在膠囊選單的面板子選單裡_針對聊天室面板(聊天, monkeypatch):
    台, _ = 聊天
    開始外語直播(台, monkeypatch)
    台.面板.開關("聊天室", True)
    送留言(["まだ言ってない"])
    面 = 台.面板.面板們["聊天室"]
    assert 等(lambda: any("↳" in x for x in 面.清單頁.行文字()))
    m = QMenu()
    台.膠囊.填選單(m)
    子 = 選單項(m, "面板").menu()
    子.aboutToShow.emit()
    聊設 = 選單項(子, "聊天室 設定").menu()
    a = 選單項(聊設, "只看譯文")
    assert a.isCheckable() and not a.isChecked()
    a.trigger()
    assert 面.設["只看譯文"] and 面.清單頁.只看譯文
    assert any(x.endswith("譯:まだ言ってない") and "まだ言ってない " not in x for x in 面.清單頁.行文字())
    assert "只看譯文" not in [a.text() for a in 選單項(子, "分鐘摘要 設定").menu().actions()]   # 只有聊天室面板有
    台.面板.存目前()
    存檔 = 讀json(panel.版面檔)
    assert next(x for x in 存檔["目前"] if x["種類"] == "聊天室")["只看譯文"] is True
    停止並等完(台)


def test_結束統計多一行聊天室翻譯(聊天, monkeypatch):
    台, _ = 聊天
    開始外語直播(台, monkeypatch)
    台.面板.開關("聊天室", True)
    送留言(["まだ言ってない"])
    assert 等(lambda: llm.聊天翻譯用量["次數"] == 1)
    訊息們 = []
    monkeypatch.setattr(台, "_訊息", lambda 字, *a, **k: 訊息們.append(字))
    停止並等完(台)
    assert any("聊天室翻譯（另計）：呼叫 1 次" in x for x in 訊息們), 訊息們


# ---------- 費用：啟動面板與設定框 ----------
def _總額(字):
    return float(re.search(r"US\$([\d.]+)", 字).group(1))


def test_啟動面板_聊天翻譯開啟時總費用與比較表跟著變(聊天):
    台, _ = 聊天
    啟 = 台.啟動面板
    啟.hide()
    啟.顯示()
    啟.語言選.setCurrentIndex(啟.語言選.findData("ja"))
    台.面板.存檔["目前"] = [{"種類": "逐句翻譯"}, {"種類": "聊天室"}]
    assert 台.面板.聊天將開啟()
    關 = {}
    for 代碼 in ("fast", "balanced", "accurate"):
        啟.段位鈕們[代碼].click()
        關[代碼] = _總額(啟.總費用.text())
    台.設聊天翻譯(True)                                                  # 膠囊選單切換：啟動面板總費用當場更新
    for 代碼 in ("fast", "balanced", "accurate"):
        啟.段位鈕們[代碼].click()
        開 = _總額(啟.總費用.text())
        assert 開 == pytest.approx(關[代碼] + 0.21, abs=1e-9)
        啟.顯示比較()
        assert 啟.比較框.表.text().count("聊天 $0.21") == 3
        啟.收起比較()
    台.面板.存檔["目前"] = [{"種類": "逐句翻譯"}]                         # 不會開聊天室面板：不計入
    啟.段位鈕們["balanced"].click()
    assert _總額(啟.總費用.text()) == 關["balanced"]


def test_設定框_聊天室翻譯欄位_費用表與備註(聊天):
    台, _ = 聊天
    台.面板.存檔["目前"] = [{"種類": "聊天室"}]
    台.開設定框()
    頁 = 台.設定框.頁
    assert not 頁.欄["chat_translate"].isChecked() and 頁.欄["chat_translate_max_per_min"].value() == 30
    表 = {列[0]: 列 for 列 in 頁.費用表}
    assert 表["聊天室翻譯"][1] == "未開啟 $0"
    頁.欄["chat_translate"].setChecked(True)
    表 = {列[0]: 列 for 列 in 頁.費用表}
    語言 = config.目前設定()["language"]
    if 語言 != "zh":
        assert 表["聊天室翻譯"][1] == "$0.21" and 表["聊天室翻譯"][2] == "否"
    assert 頁.聊天註.text().endswith("約 $0.30／小時（估算）")
    頁.儲存()
    之後 = 讀json(config.設定檔路徑)
    assert 之後["chat_translate"] is True and 之後["chat_translate_max_per_min"] == 30
    assert 台.聊天翻譯器.開啟                                            # 儲存後當場生效
    台.設聊天翻譯(False)                                                 # 膠囊切換：表單跟著改
    assert not 頁.欄["chat_translate"].isChecked()
    assert cost_estimate.聊天備註(config.目前設定()) == 頁.聊天註.text()


# ---------- 舊 config.json：沒有新欄位也不跳警告 ----------
def test_舊config沒有聊天翻譯欄位_用預設值不警告(tmp_path, monkeypatch):
    檔 = tmp_path / "config.json"
    舊 = {k: v for k, v in config.出廠預設().items() if not k.startswith("chat_translate")}
    檔.write_text(json.dumps(舊, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(config, "設定檔路徑", str(檔))
    設定, 來源, 警告們 = config.載入設定()
    assert 警告們 == []
    assert 設定["chat_translate"] is False and 設定["chat_translate_max_per_min"] == 30
    assert 來源["chat_translate"] == "內建預設"


@pytest.mark.parametrize("值", [0, 601, "30", True, 3.5])
def test_每分鐘上限不合法_退回預設並警告(tmp_path, monkeypatch, 值):
    檔 = tmp_path / "config.json"
    檔.write_text(json.dumps({"chat_translate_max_per_min": 值}), encoding="utf-8")
    monkeypatch.setattr(config, "設定檔路徑", str(檔))
    設定, _, 警告們 = config.載入設定()
    assert 設定["chat_translate_max_per_min"] == 30 and len(警告們) == 1
