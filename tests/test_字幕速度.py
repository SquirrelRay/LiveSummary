"""字幕速度段位（config.json 的 subtitle_speed）：分段秒數、翻譯批次、里程碑紀錄、時間戳、舊設定相容、幻聽過濾。
全部用假模型、假時鐘、假的音訊串流與假的翻譯函式，不連網、不呼叫 API、不需要 ffmpeg／streamlink。
介面上的部分（啟動面板、設定框）在 test_介面冒煙.py。"""
import json
import time
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from conftest import 秒數
from test_first_subtitle_latency import 字幕器, 等, 給句子  # noqa: F401  字幕器是 fixture

import live_capture as lc
import live_topics
import llm
import startup_timeline as st
import subtitle
import subtitle_speed
import transcribe

段位表 = [("fast", "速度", 8, 1, 8), ("balanced", "平衡", 12, 1, 8), ("accurate", "準度", 20, 8, 8)]


# ---------------- 段位對應 ----------------
@pytest.mark.parametrize(("代碼", "名稱", "分段", "批秒", "批句"), 段位表)
def test_段位對應的參數(代碼, 名稱, 分段, 批秒, 批句):
    p = subtitle_speed.取得(代碼)
    assert (p["名稱"], p["分段秒"], p["批次秒"], p["批次句"]) == (名稱, 分段, 批秒, 批句)


def test_預設是平衡_不認得的代碼也用平衡():
    assert subtitle_speed.預設 == "balanced"
    assert subtitle_speed.取得("亂填")["分段秒"] == 12
    assert subtitle_speed.取得(["不能雜湊"])["分段秒"] == 12
    assert not subtitle_speed.合法(["不能雜湊"]) and not subtitle_speed.合法("平衡")


def test_估算越快第一句越早_越準每小時翻譯越省():
    第一句 = [subtitle_speed.估算第一句(c) for c in subtitle_speed.代碼們]
    費用 = [subtitle_speed.估算每小時翻譯費用(c, 1.0, 5.0) for c in subtitle_speed.代碼們]
    assert 第一句 == sorted(第一句) and 費用 == sorted(費用, reverse=True)
    assert subtitle_speed.估算第一句("accurate") == (29, 33)        # 和 20 秒分段的實測紀錄吻合（29.2／32.2 秒）
    assert "估算" in subtitle_speed.詳細說明("balanced", 1.0, 5.0)
    assert subtitle_speed.估算每小時翻譯費用("balanced", 0, 0) == 0     # 本機模型（單價 0）不花錢


# ---------------- 三個段位各跑一次假流程：里程碑開頭、第一段收滿時間、時間戳 ----------------
def _句子們(monkeypatch):
    """假轉錄：每段吐兩句（段內 0.5 秒、3.0 秒），文字每段不同，才不會被「跟上一句一樣」擋掉。"""
    次 = {"n": 0}

    def 轉錄(model, 音訊, 語言):
        次["n"] += 1
        return [(0.5, f"第{次['n']}段甲"), (3.0, f"第{次['n']}段乙")]
    monkeypatch.setattr(lc, "轉錄一段", 轉錄)


@pytest.mark.parametrize(("代碼", "名稱", "分段", "批秒", "批句"), 段位表)
def test_三個段位_假流程_里程碑與時間戳(流程, monkeypatch, 代碼, 名稱, 分段, 批秒, 批句):
    monkeypatch.setattr(lc, "段秒數", lc.段秒數)            # 測完還原
    _句子們(monkeypatch)
    st.紀錄.開始({"來源": "直播網址", **subtitle_speed.里程碑說明(代碼)})      # 和 app.py 按開始時寫的開頭一樣
    lc.設定分段(subtitle_speed.取得(代碼)["分段秒"])         # 和 live_topics.執行 一樣
    一段 = np.full(分段 * lc.取樣率, 8000, dtype=np.int16).tobytes()   # 假取樣率 2：一段 = 分段秒數 × 2 個取樣
    assert len(一段) == lc.每段位元組
    紀, _, s = 流程([一段, 一段, 一段], 語言="ja")

    開頭 = Path(紀.路徑).read_text(encoding="utf-8").split("# 啟動里程碑")[-1].split("[+")[0]   # 最後一次「開始」寫的開頭
    assert f"字幕速度段位 = {名稱}（{代碼}）" in 開頭
    assert f"分段長度設定(秒) = {分段}" in 開頭
    assert f"翻譯批次秒數 = {批秒}" in 開頭 and f"翻譯批次句數 = {批句}" in 開頭
    assert 秒數(紀, st.第一段收滿) == 分段                     # 第一段收滿的時間 = 這個段位的分段秒數
    assert f"分段設定秒={分段}，實際秒={float(分段)}" in Path(紀.路徑).read_text(encoding="utf-8")

    預期 = [(i * 分段 + 段內, f"第{i + 1}段{字}") for i in range(3) for 段內, 字 in ((0.5, "甲"), (3.0, "乙"))]
    assert [秒 for 秒, _ in s.吐出] == [秒 for 秒, _ in 預期]
    assert [行 for _, 行 in s.吐出] == [f"{transcribe.時間(秒)} {字}" for 秒, 字 in 預期]


@pytest.mark.parametrize(("分段", "預期"), [(8, ["[00:16]", "[00:19]"]), (12, ["[00:24]", "[00:27]"]),
                                         (20, ["[00:40]", "[00:43]"])])
def test_第三段的時間戳(流程, monkeypatch, 分段, 預期):
    monkeypatch.setattr(lc, "段秒數", lc.段秒數)
    _句子們(monkeypatch)
    lc.設定分段(分段)
    一段 = np.full(分段 * lc.取樣率, 8000, dtype=np.int16).tobytes()
    _, _, s = 流程([一段] * 3, 語言="ja")
    assert [行.split(" ")[0] for _, 行 in s.吐出[4:]] == 預期


@pytest.mark.parametrize(("代碼", "分段"), [("fast", 8), ("balanced", 12), ("accurate", 20)])
def test_執行時依段位設定分段長度(monkeypatch, 代碼, 分段):
    monkeypatch.setattr(lc, "段秒數", lc.段秒數)
    monkeypatch.setattr(lc, "每段位元組", lc.每段位元組)
    monkeypatch.setattr(llm, "檢查金鑰", lambda: None)
    看到 = []

    def 假直播(*a, **k):
        看到.append((lc.段秒數, lc.每段位元組))
        raise lc.直播錯誤("假的，不連網")
    monkeypatch.setattr(lc, "live_session", 假直播)
    設定 = live_topics.內建預設() | {"subtitle_speed": 代碼}
    assert live_topics.執行(設定, 網址="https://www.twitch.tv/假頻道") is False
    assert 看到 == [(分段, 分段 * 16000 * 2)]


# ---------------- 翻譯批次：一段的句子整批送出 ----------------
def _換段位(monkeypatch, 代碼):
    p = subtitle_speed.取得(代碼)
    monkeypatch.setattr(subtitle, "批次秒數", p["批次秒"])
    monkeypatch.setattr(subtitle, "批次句數", p["批次句"])


@pytest.mark.parametrize("代碼", ["balanced", "fast"])
def test_平衡與速度_一段6句整批送出_不被4句拆開(字幕器, monkeypatch, 代碼):  # noqa: F811
    d, 鐘, 批們 = 字幕器
    _換段位(monkeypatch, 代碼)
    給句子(d, ["首"])
    assert 等(lambda: len(批們) == 1)
    給句子(d, ["一", "二", "三", "四", "五", "六"])           # 同一段轉錄出來的 6 句，幾乎同時進來
    time.sleep(0.8)
    assert len(批們) == 1                                     # 還沒滿 1 秒、也沒滿 8 句：先等
    鐘.t += 1.1
    assert 等(lambda: len(批們) == 2)
    time.sleep(0.5)
    assert len(批們) == 2 and 批們[1][1] == ["一", "二", "三", "四", "五", "六"]    # 一次送出，不是 4＋2


def test_平衡_滿8句馬上送(字幕器, monkeypatch):  # noqa: F811
    d, _, 批們 = 字幕器
    _換段位(monkeypatch, "balanced")
    給句子(d, ["首"])
    assert 等(lambda: len(批們) == 1)
    給句子(d, [str(i) for i in range(8)])
    assert 等(lambda: len(批們) == 2)                         # 假時鐘沒前進，滿 8 句就送
    assert 批們[1][1] == [str(i) for i in range(8)]


def test_準度_等滿8秒才送_一樣整批(字幕器, monkeypatch):  # noqa: F811
    d, 鐘, 批們 = 字幕器
    _換段位(monkeypatch, "accurate")
    給句子(d, ["首"])
    assert 等(lambda: len(批們) == 1)
    給句子(d, ["一", "二", "三", "四", "五", "六"])
    鐘.t += 1.1
    time.sleep(0.8)
    assert len(批們) == 1                                     # 1.1 秒：準度段位還不送
    鐘.t += 7.0                                               # 8.1 秒
    assert 等(lambda: len(批們) == 2)
    assert 批們[1][1] == ["一", "二", "三", "四", "五", "六"]


# ---------------- 舊設定相容 ----------------
def _寫設定(tmp_path, monkeypatch, 內容):
    路徑 = tmp_path / "config.json"
    路徑.write_text(json.dumps(內容, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(live_topics, "設定檔路徑", str(路徑))


def test_舊config沒有subtitle_speed_視為平衡_不警告(tmp_path, monkeypatch):
    _寫設定(tmp_path, monkeypatch, {"chat": False, "translate_batch_seconds": 8, "translate_batch_lines": 4})
    設定, 來源, 警告們 = live_topics.載入設定({})
    assert 警告們 == []
    assert 設定["subtitle_speed"] == "balanced" and 來源["subtitle_speed"] == "內建預設"
    assert "translate_batch_seconds" not in 設定 and "translate_batch_lines" not in 設定   # 已停用：被段位取代


def test_舊的translate_batch值是壞的也不警告(tmp_path, monkeypatch):
    _寫設定(tmp_path, monkeypatch, {"translate_batch_seconds": "很多", "translate_batch_lines": 99})
    assert live_topics.載入設定({})[2] == []


@pytest.mark.parametrize("代碼", ["fast", "balanced", "accurate"])
def test_讀得到三個段位(tmp_path, monkeypatch, 代碼):
    _寫設定(tmp_path, monkeypatch, {"subtitle_speed": 代碼})
    設定, 來源, 警告們 = live_topics.載入設定({})
    assert 警告們 == [] and 設定["subtitle_speed"] == 代碼 and 來源["subtitle_speed"] == "config.json"


@pytest.mark.parametrize("壞值", ["平衡", "turbo", 12, ["fast"], None])
def test_subtitle_speed壞值_警告並用平衡_不崩潰(tmp_path, monkeypatch, 壞值):
    _寫設定(tmp_path, monkeypatch, {"subtitle_speed": 壞值})
    設定, _, 警告們 = live_topics.載入設定({})
    assert 設定["subtitle_speed"] == "balanced"
    assert len(警告們) == 1 and "subtitle_speed" in 警告們[0]


def test_這一場的段位可以覆蓋config(tmp_path, monkeypatch):
    _寫設定(tmp_path, monkeypatch, {"subtitle_speed": "accurate"})
    assert live_topics.載入設定({"subtitle_speed": "fast"})[0]["subtitle_speed"] == "fast"


# ---------------- 幻聽過濾（幻聽例句來自 2026-10-12 量測時的實際轉錄結果；正常句子是自編的） ----------------
@pytest.mark.parametrize("文字", [
    "字幕視聴ありがとうございました。",          # 中文直播 5 秒分段時出現兩次，原本的清單（要有「ご」）擋不到
    "ご視聴ありがとうございました",
    "最後までご視聴いただきありがとうございました",
    "我實在是繁體中文的",                      # 8 秒分段時：中文提示詞外洩
    "以下是繁體中文的直播逐字稿。",            # 提示詞原封不動吐出來
    "繁體中文的直播逐字稿",
])
def test_幻聽與提示詞外洩_會被擋(文字):
    assert lc.是幻聽(文字)


@pytest.mark.parametrize("文字", [
    "感謝路人甲的訂閱",                  # 四種分段都有，是主播真的在講
    "歡迎新來的朋友",
    "嗯,還好,時間還早。",
    "有吃晚餐嗎?有啊,剛吃完泡麵。",
    "這一關我們等一下再回來打,因為現在裝備還不夠,我們先去旁邊練等級。",
    "這個遊戲有繁體中文嗎",                    # 講到繁體中文的正常句子
    "我覺得繁體中文的字比較好看",
    "まだ生きてるよ",
    "ナイスプレイ!",
    "敵がまだ残ってるよ",
])
def test_正常句子不會被誤擋(文字):
    assert not lc.是幻聽(文字)


def test_轉錄一段_實際套用幻聽過濾():
    """假模型吐出的段落裡夾著幻聽與提示詞外洩，轉錄一段 只留下正常的句子。"""
    def 段(start, text):
        return SimpleNamespace(start=start, text=" " + text, no_speech_prob=0.1, avg_logprob=-0.3, compression_ratio=1.2)

    class 假模型:
        def transcribe(self, 音訊, **k):
            assert k["initial_prompt"] == lc.中文提示
            return [段(0.0, "感謝路人甲的訂閱"), 段(2.0, "字幕視聴ありがとうございました。"),
                    段(4.0, "我實在是繁體中文的"), 段(6.0, "嗯,還好,時間還早。")], None

    音訊 = np.full(32000, 0.3, dtype=np.float32)
    assert lc.轉錄一段(假模型(), 音訊, "zh") == [(0.0, "感謝路人甲的訂閱"), (6.0, "嗯,還好,時間還早。")]
