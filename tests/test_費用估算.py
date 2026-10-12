"""每小時費用估算（cost_estimate）：純計算，不開視窗、不連網、不花 API。"""
import re

import pytest

import cost_estimate as ce
import live_topics
import subtitle_speed


def 設定(**改):
    """外語直播、聊天室開、分鐘摘要開、思考關（和專案目前的 config.json 相近），單價 1／5。"""
    基本 = dict(live_topics.內建預設(), language="ja", chat=True, minute_summary=True, summary_thinking=False,
              price_input=1.0, price_output=5.0)
    return 基本 | 改


def 項(結果, 鍵):
    return next(x for x in 結果["項目們"] if x["鍵"] == 鍵)


# ---------- 金額跟著單價走 ----------
def test_改單價金額跟著變():
    原 = ce.估算(設定(), "balanced", True)
    倍 = ce.估算(設定(price_input=2.0, price_output=10.0), "balanced", True)
    for 鍵 in ("翻譯", "判斷", "分鐘", "話題"):
        assert 項(倍, 鍵)["每小時"] == pytest.approx(項(原, 鍵)["每小時"] * 2, abs=0.011)
    assert 倍["合計"] > 原["合計"] * 1.9
    免費 = ce.估算(設定(price_input=0, price_output=0), "balanced", True)      # 本機模型
    assert 免費["合計"] == 0


def test_翻譯金額用段位的每小時token和目前單價():
    輸入, 輸出 = subtitle_speed.每小時翻譯用量("balanced")
    預期 = 輸入 / 1e6 * 1.0 + 輸出 / 1e6 * 5.0
    assert 項(ce.估算(設定(), "balanced", True), "翻譯")["每小時"] == pytest.approx(預期, abs=0.005)


def test_越準的段位翻譯越省_其他項目不受段位影響():
    結果 = {c: ce.估算(設定(), c, True) for c in subtitle_speed.代碼們}
    翻譯 = [項(結果[c], "翻譯")["每小時"] for c in subtitle_speed.代碼們]
    assert 翻譯 == sorted(翻譯, reverse=True) and 翻譯[0] > 翻譯[-1]
    for 鍵 in ("判斷", "分鐘", "話題"):
        assert len({項(r, 鍵)["每小時"] for r in 結果.values()}) == 1
        assert not 項(結果["fast"], 鍵)["受段位影響"]
    assert 項(結果["fast"], "翻譯")["受段位影響"]


# ---------- 沒開的功能：未開啟 $0、不計入合計 ----------
def test_翻譯面板沒開_顯示未開啟0元_合計減少():
    開 = ce.估算(設定(), "balanced", True)
    關 = ce.估算(設定(), "balanced", False)
    翻 = 項(關, "翻譯")
    assert not 翻["開啟"] and 翻["每小時"] == 0 and "逐句翻譯面板沒開" in 翻["狀態"]
    assert ce.項目金額字(翻) == "未開啟 $0"
    assert 關["合計"] == pytest.approx(開["合計"] - 項(開, "翻譯")["每小時"], abs=0.011)
    assert 關["合計"] < 開["合計"]


def test_中文直播與原文模式_不翻譯():
    for 改 in ({"language": "zh"}, {"subtitle_mode": "original"}):
        結果 = ce.估算(設定() | 改, "balanced", True)
        assert not 項(結果, "翻譯")["開啟"] and 項(結果, "翻譯")["每小時"] == 0
    assert 項(ce.估算(設定() | {"subtitle_mode": "translate", "language": "zh"}, "balanced", True), "翻譯")["開啟"]


def test_分鐘摘要關掉_該項未開啟且不計入():
    關 = ce.估算(設定() | {"minute_summary": False}, "balanced", True)
    開 = ce.估算(設定(), "balanced", True)
    assert not 項(關, "分鐘")["開啟"] and ce.項目金額字(項(關, "分鐘")) == "未開啟 $0"
    assert 關["合計"] < 開["合計"]


def test_延伸思考開啟_摘要輸出變多_費用變高():
    關 = ce.估算(設定(), "balanced", False)
    開 = ce.估算(設定() | {"summary_thinking": True}, "balanced", False)
    assert 開["合計"] > 關["合計"] * 1.5


def test_合計等於各項顯示金額相加():
    結果 = ce.估算(設定(), "accurate", True)
    assert 結果["合計"] == pytest.approx(sum(x["每小時"] for x in 結果["項目們"]), abs=1e-9)
    assert all(round(x["每小時"], 2) == x["每小時"] for x in 結果["項目們"])


# ---------- 文字格式 ----------
def test_一行說明只有字幕翻譯與摘要兩項_加總等於合計():
    結果 = ce.估算(設定(), "balanced", True)
    字 = ce.一行說明(結果)
    assert re.fullmatch(r"每小時約 US\$\d+\.\d{2}（估算）＝ (字幕翻譯|摘要) \$\d+\.\d{2} ＋ (字幕翻譯|摘要) \$\d+\.\d{2}", 字)
    總, 甲, 乙 = (float(x) for x in re.findall(r"\$(\d+\.\d{2})", 字))
    assert 總 == pytest.approx(甲 + 乙) and 甲 >= 乙 and 總 == 結果["合計"]
    摘要 = sum(項(結果, k)["每小時"] for k in ("判斷", "分鐘", "話題"))
    assert f"摘要 ${摘要:.2f}" in 字 and "其他" not in 字 and "話題追蹤" not in 字


def test_一行說明_翻譯沒開時固定寫未開啟():
    結果 = ce.估算(設定(), "balanced", False)
    assert ce.一行說明(結果) == f"每小時約 US${結果['合計']:.2f}（估算）＝ 字幕翻譯 未開啟 $0 ＋ 摘要 ${結果['合計']:.2f}"


def test_費用表_摘要歸類與名稱():
    結果 = ce.估算(設定(), "balanced", True)
    列們 = ce.表格列們(結果)
    assert [列[0] for 列 in 列們] == ["項目", "字幕翻譯", "摘要（小計）", "　話題追蹤（每分鐘檢查）", "　分鐘摘要", "　話題摘要", "合計"]
    assert float(列們[2][1][1:]) == pytest.approx(sum(float(列[1][1:]) for 列 in 列們[3:6]))
    assert 列們[-1][1] == f"US${結果['合計']:.2f}"
    assert ce.估算(設定(check_minutes=2), "balanced", True)["項目們"][1]["名稱"] == "話題追蹤（每 2 分鐘檢查）"


def test_合計字格式():
    assert ce.合計字({"合計": 0.4}) == "US$0.40"
    assert ce.金額(0.186) == "$0.19"


# ---------- 與實際紀錄對照（思考比較.md：中文、文字稿模式、11.35 分鐘、10 次判斷＋1 次話題摘要） ----------
def _紀錄用量(思考):
    s = 設定(summary_thinking=思考) | {"language": "zh"}
    判斷 = ce.摘要用量(s, 10, 580, 0)          # 10 次判斷（含分鐘摘要）
    話題 = ce.摘要用量(s, 11.35, 580, 1)       # 1 則話題摘要，文字稿 11.35 分鐘 × 580 字
    輸入 = 判斷["判斷"][0] + 判斷["分鐘"][0] + 話題["話題"][0]
    輸出 = 判斷["判斷"][1] + 判斷["分鐘"][1] + 話題["話題"][1]
    return 輸入, 輸出


def test_估算與實際紀錄相差不到10趴():
    輸入, 輸出 = _紀錄用量(False)
    assert abs(輸入 - 25_014) / 25_014 < 0.10 and abs(輸出 - 4_765) / 4_765 < 0.10
    輸入, 輸出 = _紀錄用量(True)
    assert abs(輸入 - 24_714) / 24_714 < 0.10 and abs(輸出 - 17_641) / 17_641 < 0.15
