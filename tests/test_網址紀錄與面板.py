"""安全網測試：ui_state（頻道名、網址紀錄、介面設定）與 panel（整理面板設定、移回畫面內）。檔案一律在 tmp_path。"""
import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication

import panel
import ui_state


# ---------- 頻道名 ----------
@pytest.mark.parametrize("網址,預期", [
    ("https://www.twitch.tv/Foo", "Foo"),
    ("twitch.tv/bar", "bar"),
    ("https://www.twitch.tv/videos/123", "123"),
    ("https://www.youtube.com/@abc", "@abc"),
    ("https://youtu.be/XYZ", "影片 XYZ"),
    ("https://www.youtube.com/watch?v=VID&t=1", "影片 VID"),
    ("https://www.youtube.com/channel/UC1", "UC1"),
    ("https://m.youtube.com/live/L1", "L1"),
    ("https://example.com/a/b", "b"),
    ("example.com", "example.com"),
    ("https://www.twitch.tv/", "twitch.tv"),
])
def test_頻道名(網址, 預期):
    assert ui_state.頻道名(網址) == 預期


# ---------- 網址紀錄 ----------
@pytest.fixture
def 紀錄(tmp_path, monkeypatch):
    鐘 = iter(range(1000, 100000))
    monkeypatch.setattr(ui_state.time, "time", lambda: float(next(鐘)))     # 每次呼叫時間遞增，排序才確定
    return ui_state.網址紀錄(str(tmp_path / "網址紀錄.json")), tmp_path / "網址紀錄.json"


def 網址們(r):
    return [x["網址"] for x in r.清單()]


def test_新加的排最前面(紀錄):
    r, _ = 紀錄
    for u in ("a", "b", "c"):
        r.加入(u)
    assert 網址們(r) == ["c", "b", "a"]


def test_重複加入只更新時間並移到最前(紀錄):
    r, _ = 紀錄
    for u in ("a", "b", "c"):
        r.加入(u)
    r.加入("a")
    assert 網址們(r) == ["a", "c", "b"]


def test_空白網址不加入且前後空白會去掉(紀錄):
    r, _ = 紀錄
    r.加入("   ")
    r.加入("  x  ")
    assert 網址們(r) == ["x"]


def test_釘選的排最前面_依釘選順序(紀錄):
    r, _ = 紀錄
    for u in ("a", "b", "c", "d"):
        r.加入(u)
    r.釘選("b")
    r.釘選("a")
    assert 網址們(r) == ["b", "a", "d", "c"]          # 釘選區：先釘的在前；其後是最近用過的
    r.加入("e")
    assert 網址們(r)[:2] == ["b", "a"]


def test_取消釘選後回到一般排序(紀錄):
    r, _ = 紀錄
    for u in ("a", "b"):
        r.加入(u)
    r.釘選("a")
    r.釘選("a", False)
    assert 網址們(r) == ["b", "a"] and not any(x["釘選"] for x in r.清單())


def test_釘選不存在的網址沒事(紀錄):
    r, _ = 紀錄
    r.釘選("不存在")
    assert r.清單() == []


def test_刪除(紀錄):
    r, _ = 紀錄
    for u in ("a", "b"):
        r.加入(u)
    r.刪除("a")
    r.刪除("不存在")
    assert 網址們(r) == ["b"]


def test_沒釘選的最多留十個_釘選的不算(紀錄):
    r, _ = 紀錄
    r.加入("pin")
    r.釘選("pin")
    for i in range(15):
        r.加入(f"u{i}")
    清單 = 網址們(r)
    assert len(清單) == ui_state.最近上限 + 1
    assert 清單[0] == "pin" and 清單[1] == "u14" and "u0" not in 清單 and "u4" not in 清單 and "u5" in 清單


def test_存檔後重新讀得回來(紀錄):
    r, 路徑 = 紀錄
    r.加入("a")
    r.加入("b")
    r.釘選("a")
    r2 = ui_state.網址紀錄(str(路徑))
    assert r2.清單() == r.清單()


def test_檔案壞掉或格式不對當成沒有紀錄(tmp_path):
    p = tmp_path / "壞.json"
    p.write_text("{{{不是json", encoding="utf-8")
    assert ui_state.網址紀錄(str(p)).清單() == []
    p.write_text(json.dumps([{"網址": "ok"}, {"網址": 5}, "字串", {"網址": "  "}]), encoding="utf-8")
    assert [x["網址"] for x in ui_state.網址紀錄(str(p)).清單()] == ["ok"]
    p.write_text(json.dumps({"不是": "清單"}), encoding="utf-8")
    assert ui_state.網址紀錄(str(p)).清單() == []


# ---------- 介面設定 ----------
@pytest.fixture
def 設定檔(tmp_path, monkeypatch):
    p = tmp_path / "介面設定.json"
    monkeypatch.setattr(ui_state, "介面設定檔", str(p))
    return p


所有頁 = ["分鐘摘要", "話題摘要", "逐句翻譯", "直播稿", "聊天室"]


def test_沒有設定檔用預設(設定檔):
    assert ui_state.讀介面設定(所有頁) == (1, ["分鐘摘要", "逐句翻譯", "直播稿"])


def test_存了再讀得回來(設定檔):
    ui_state.存介面設定(2, ["聊天室", "直播稿", "話題摘要"])
    assert ui_state.讀介面設定(所有頁) == (2, ["聊天室", "直播稿", "話題摘要"])


def test_欄數超出範圍或型別不對用一欄(設定檔):
    for 壞 in (0, 4, "2", True, None):
        設定檔.write_text(json.dumps({"欄數": 壞, "每欄分頁": ["聊天室"]}), encoding="utf-8")
        assert ui_state.讀介面設定(所有頁)[0] == 1


def test_分頁重複或不存在會被剔除並補齊(設定檔):
    設定檔.write_text(json.dumps({"欄數": 3, "每欄分頁": ["聊天室", "聊天室", "不存在"]}), encoding="utf-8")
    欄數, 頁們 = ui_state.讀介面設定(所有頁)
    assert 欄數 == 3 and len(頁們) == 3 and len(set(頁們)) == 3 and 頁們[0] == "聊天室"
    assert all(p in 所有頁 for p in 頁們)


def test_只改指定欄位_其他欄位保留(設定檔):
    ui_state.存膠囊位置((10, 20))
    ui_state.存介面設定(2, ["直播稿"])
    assert ui_state.讀膠囊位置() == (10, 20)
    ui_state.存旗標("提示過")
    assert ui_state.讀旗標("提示過") is True and ui_state.讀旗標("別的") is False
    assert ui_state.讀介面設定(所有頁)[0] == 2


def test_膠囊位置壞掉回傳None(設定檔):
    assert ui_state.讀膠囊位置() is None
    設定檔.write_text(json.dumps({"膠囊位置": [1, "x"]}), encoding="utf-8")
    assert ui_state.讀膠囊位置() is None
    設定檔.write_text(json.dumps({"膠囊位置": [True, 2]}), encoding="utf-8")
    assert ui_state.讀膠囊位置() is None


# ---------- panel.整理面板設定 ----------
def test_整理面板設定_種類不認得回傳None():
    assert panel.整理面板設定({"種類": "不存在"}) is None
    assert panel.整理面板設定("字串") is None
    assert panel.整理面板設定(None) is None


def test_整理面板設定_缺的用預設():
    s = panel.整理面板設定({"種類": "直播稿"})
    assert s["種類"] == "直播稿" and s["樣式"] == "清單" and s["置頂"] is True and s["穿透"] is False
    assert (s["x"], s["y"], s["w"], s["h"]) == (100, 100, 420, 300)
    assert s["清單字級"] == 14 and s["字幕字級"] == 28 and s["字幕則數"] == 2


def test_整理面板設定_數值夾在合法範圍():
    s = panel.整理面板設定({"種類": "直播稿", "文字透明度": 0, "清單背景": 5, "清單字級": 1, "字幕字級": 999,
                     "字幕則數": 99, "x": 10 ** 9})
    assert s["文字透明度"] == 0.1 and s["清單背景"] == 1.0
    assert s["清單字級"] == 8 and s["字幕字級"] == 96 and s["字幕則數"] == 10 and s["x"] == 100000


def test_整理面板設定_壞型別用預設():
    s = panel.整理面板設定({"種類": "直播稿", "樣式": "亂寫", "置頂": "是", "清單字級": True, "x": "左邊"})
    assert s["樣式"] == "清單" and s["置頂"] is True and s["清單字級"] == 14 and s["x"] == 100


def test_整理面板設定_尺寸不得小於最小值():
    s = panel.整理面板設定({"種類": "逐句翻譯", "樣式": "字幕", "w": 1, "h": 1})
    assert (s["w"], s["h"]) == panel.最小尺寸["字幕"]
    s = panel.整理面板設定({"種類": "直播稿", "w": 1, "h": 1})
    assert (s["w"], s["h"]) == panel.最小尺寸["清單"]


# ---------- panel.移回畫面內（只需要 QGuiApplication，不建視窗） ----------
@pytest.fixture(scope="module")
def 畫面():
    app = QApplication.instance() or QApplication([])
    return QGuiApplication.primaryScreen().availableGeometry(), app


def 面板(x, y, w, h):
    return panel.整理面板設定({"種類": "直播稿", "x": x, "y": y, "w": w, "h": h})


def test_已在畫面內不動(畫面):
    g, _ = 畫面
    s = 面板(g.x() + 10, g.y() + 10, 300, 200)
    assert panel.移回畫面內(s) is s


def test_超出畫面右下會移回(畫面):
    g, _ = 畫面
    s = panel.移回畫面內(面板(g.x() + g.width() + 5000, g.y() + g.height() + 5000, 300, 200))
    assert g.contains(s["x"], s["y"]) and s["x"] + s["w"] <= g.x() + g.width() and s["y"] + s["h"] <= g.y() + g.height()
    assert (s["w"], s["h"]) == (300, 200)


def test_超出畫面左上會移回(畫面):
    g, _ = 畫面
    s = panel.移回畫面內(面板(g.x() - 5000, g.y() - 5000, 300, 200))
    assert (s["x"], s["y"]) == (g.x(), g.y())


def test_比畫面還大就縮到畫面大小(畫面):
    g, _ = 畫面
    s = panel.移回畫面內(面板(g.x(), g.y(), g.width() + 3000, g.height() + 3000))
    assert (s["w"], s["h"]) == (g.width(), g.height()) and (s["x"], s["y"]) == (g.x(), g.y())


def test_移回畫面內不改原本的dict(畫面):
    g, _ = 畫面
    原 = 面板(g.x() + 99999, g.y(), 300, 200)
    x0 = 原["x"]
    panel.移回畫面內(原)
    assert 原["x"] == x0
