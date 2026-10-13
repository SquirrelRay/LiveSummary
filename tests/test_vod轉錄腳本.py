"""開發用腳本 scripts/vod_to_transcript.py：全部用假的下載、假的轉錄、假的 Whisper 段落，不連網、不跑真模型、不花 API。
重點：起點不是 0 時，直播稿的時間戳是 VOD 內的原始時間；超過 1 小時用 h:mm:ss；文字稿重播模式能讀、快轉。"""
import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import vod_to_transcript as v

import live_topics as lt

播放清單 = "#EXTM3U\n" + "".join(f"#EXTINF:10.000,\nseg{i}.ts\n" for i in range(720))     # 10 秒一段，共 2 小時


def 段(start, text, no_speech=0.0, logprob=-0.2, compression=1.2):
    return SimpleNamespace(start=start, end=start + 2, text=text, no_speech_prob=no_speech,
                           avg_logprob=logprob, compression_ratio=compression)


# ---------- 時間與編號 ----------
@pytest.mark.parametrize(("字", "秒"), [("0", 0), ("90", 90), ("6:25", 385), ("0:06:25", 385), ("1:30:00", 5400), ("1:02:03.5", 3723.5)])
def test_解析時間(字, 秒):
    assert v.解析時間(字) == 秒


@pytest.mark.parametrize("壞", ["", "abc", "1:2:3:4", "-5", "1:"])
def test_解析時間_壞格式(壞):
    with pytest.raises(ValueError, match="時間格式"):
        v.解析時間(壞)


def test_編號與檔名代號():
    assert v.vod編號("https://www.twitch.tv/videos/2898838036?t=1h") == "2898838036"
    assert v.vod編號("2850504790") == "2850504790"
    with pytest.raises(ValueError, match="VOD 編號"):
        v.vod編號("https://www.twitch.tv/somechannel")
    assert v.時間代號(385) == "0h06m25s" and v.時間代號(5400) == "1h30m00s"
    assert v.時間參數(385) == "00:06:25" and v.時間參數(5400) == "01:30:00"


# ---------- streamlink 的起點規則 ----------
@pytest.mark.parametrize(("起點", "實際"), [(0, 0), (385, 390), (390, 390), (391, 400), (5400, 5400)])
def test_實際起點是分段邊界_不早於要求(起點, 實際):
    assert v.算實際起點(播放清單, 起點) == 實際      # 第二支 VOD 要求 6:25 → 6:30 開始


def test_實際起點_沒有分段或超過結尾():
    assert v.算實際起點("#EXTM3U\n", 385) == 385
    assert v.算實際起點("#EXTM3U\n#EXTINF:10.0,\na.ts\n#EXTINF:10.0,\nb.ts\n", 999) == 10     # 停在最後一個分段


# ---------- Whisper 段落 → 直播稿的行 ----------
def test_起點不為0_時間戳是VOD內原始時間():
    行們 = v.段轉行們([段(0.4, "第一句"), 段(61.0, "第二句")], 390.0)
    assert 行們 == ["[06:30] 第一句", "[07:31] 第二句"]          # 第一行從 6:25 附近，不是 0:00


def test_超過一小時用h_mm_ss():
    行們 = v.段轉行們([段(0, "剛好一小時"), 段(3599.6, "快兩小時前"), 段(1800, "x")], 3600.0)
    assert 行們[0] == "[1:00:00] 剛好一小時" and 行們[1].startswith("[1:59:59]") and 行們[2].startswith("[1:30:00]")


def test_過濾幻聽_沒人講話_重複_空白():
    行們 = v.段轉行們([
        段(1, "字幕視聴ありがとうございました"),                  # 幻聽
        段(2, "亂猜的", no_speech=0.9, logprob=-1.5),            # 沒人講話
        段(3, "重複重複重複", compression=3.0),                  # 重複度太高
        段(4, "  "), 段(5, "正常句"), 段(6, "正常句"), 段(7, "另一句")], 0.0)
    assert 行們 == ["[00:05] 正常句", "[00:07] 另一句"]          # 跟上一句一模一樣的也跳過


# ---------- 下載與轉檔的指令（假執行，不連網）----------
def test_下載指令只抓指定時段_不下載整支(tmp_path):
    呼叫 = []

    def 假執行(指令, **k):
        呼叫.append(指令)
        Path(指令[指令.index("-o") + 1]).write_bytes(b"x" * 10)
        return SimpleNamespace(returncode=0, stdout="", stderr="")
    v.下載音訊("https://www.twitch.tv/videos/1", 385, 5010, tmp_path / "a.ts", 假執行)
    指令 = 呼叫[0]
    assert 指令[指令.index("--hls-start-offset") + 1] == "00:06:25" and 指令[指令.index("--hls-duration") + 1] == "01:23:30"
    assert 指令[-1] == "audio_only" and "streamlink_cli" in 指令
    v.下載音訊("https://www.twitch.tv/videos/1", 0, None, tmp_path / "b.ts", 假執行)
    assert "--hls-duration" not in 呼叫[1]                                    # 沒給終點：到結尾


def test_下載失敗有中文說明(tmp_path):
    with pytest.raises(RuntimeError, match="下載音訊失敗.*unable"):
        v.下載音訊("u", 0, 10, tmp_path / "a.ts", lambda *a, **k: SimpleNamespace(returncode=1, stdout="", stderr="error: unable to open"))


def test_ffmpeg轉檔指令():
    呼叫 = []
    v.轉成wav("a.ts", "a.wav", "ffmpeg", lambda 指令, **k: (呼叫.append(指令), SimpleNamespace(returncode=0, stderr=""))[1])
    assert 呼叫[0][:2] == ["ffmpeg", "-y"] and "16000" in 呼叫[0] and 呼叫[0][-1] == "a.wav" and "-vn" in 呼叫[0]


# ---------- 整個流程：假下載、假轉錄 ----------
def 跑流程(tmp_path, 起, 訖, 清單=lambda 網址: 播放清單):
    紀錄 = {}

    def 假下載(網址, 起點, 時長, 輸出):
        紀錄["下載"] = (起點, 時長)
        Path(輸出).write_bytes(b"ts")

    def 假轉檔(來源, 輸出, ffmpeg):
        Path(輸出).write_bytes(b"wav")

    def 假轉錄(wav, 起點, 語言):
        紀錄["轉錄起點"] = 起點
        return v.段轉行們([段(1, "開頭一句"), 段(4000, "一小時後的一句"), 段(4100, "最後一句")], 起點), "ja", "ja（自動偵測，信心 0.98）"

    結果 = v.處理("https://www.twitch.tv/videos/2898838036", 起, 訖, "auto", tmp_path / "素材", 取清單=清單, 下載=假下載,
                轉檔=假轉檔, 轉錄函式=假轉錄, 找ffmpeg=lambda: "ffmpeg", 進度=lambda *a: None)
    return 結果, 紀錄


def test_流程_起點不為0_直播稿從6分半開始且用原始時間(tmp_path):
    結果, 紀錄 = 跑流程(tmp_path, 385.0, 5400.0)
    assert 紀錄["下載"] == (385.0, 5400 - 390) and 紀錄["轉錄起點"] == 390.0       # 實際起點 6:30；時長算到 1:30:00 為止
    行們 = 結果["稿"].read_text(encoding="utf-8").splitlines()
    assert 行們[0].startswith("# 開發測試用") and "要求 06:25～1:30:00" in 行們[1] and "實際音訊從 06:30 開始" in 行們[1]
    內容 = [l for l in 行們 if l.startswith("[")]
    assert 內容 == ["[06:31] 開頭一句", "[1:13:10] 一小時後的一句", "[1:14:50] 最後一句"]
    assert 結果["行數"] == 3 and 結果["語言代碼"] == "ja" and "自動偵測" in 結果["語言"]
    assert 結果["稿"].parent.name == "素材" and 結果["稿"].name == "vod2898838036_0h06m25s-1h30m00s_直播稿.txt"
    assert 結果["wav"].exists() and not 結果["wav"].with_suffix(".ts").exists()        # ts 轉完就刪、wav 保留


def test_流程_讀不到播放清單_退回要求起點並警告(tmp_path):
    def 壞(網址):
        raise OSError("連不上")
    _, 紀錄 = 跑流程(tmp_path, 385.0, 5400.0, 清單=壞)
    assert 紀錄["轉錄起點"] == 385.0


def test_流程_終點必須比起點晚(tmp_path):
    with pytest.raises(ValueError, match="--end"):
        v.處理("https://www.twitch.tv/videos/1", 100, 100, "ja", tmp_path)


def test_流程_不抓聊天室_只產生音訊與直播稿(tmp_path):
    結果, _ = 跑流程(tmp_path, 0.0, 600.0)
    assert sorted(p.suffix for p in 結果["稿"].parent.iterdir()) == [".txt", ".wav"]


# ---------- 文字稿重播模式能讀這份直播稿（不從 0:00 開始、有 # 開頭說明行、超過 1 小時）----------
def test_重播模式讀得懂這份直播稿_不從0開始(tmp_path):
    結果, _ = 跑流程(tmp_path, 385.0, 5400.0)
    秒們 = [秒 for 秒, _ in lt.stream_lines(str(結果["稿"]))]
    assert 秒們 == [391, 4390, 4490]                  # 說明行被略過；時間是 VOD 內的秒數（6:31、1:13:10、1:14:50）


def test_重播快轉_speed決定等待時間_0是不等(tmp_path):
    稿 = tmp_path / "稿.txt"
    稿.write_text("[1:00:00] 甲\n[1:00:10] 乙\n[1:00:20] 丙\n", encoding="utf-8")
    開始 = time.time()
    assert [s for s, _ in lt.stream_lines(str(稿), speed=0)] == [3600, 3610, 3620]
    assert time.time() - 開始 < 0.5                  # speed=0：瞬間跑完
    開始 = time.time()
    list(lt.stream_lines(str(稿), speed=100))        # 20 秒的稿 ÷ 100 倍 = 約 0.2 秒
    assert 0.15 < time.time() - 開始 < 1.5


def test_快轉不影響換話題判斷_speed0與快轉的提示詞與結果完全相同(tmp_path, monkeypatch):
    """引擎只看稿裡的時間，不看現實時鐘：同一份不從 0:00 開始、超過 1 小時的稿，用不同 speed 跑，送給模型的提示詞一模一樣。"""
    import json

    import events
    import llm
    import summarize
    稿 = tmp_path / "稿.txt"
    稿.write_text("# 說明行\n" + "".join(f"[{timefmt_標記(3600 + s)}] 第{s}秒" + "字" * 110 + "\n" for s in range(0, 601, 60)), encoding="utf-8")

    def 跑(speed):
        提示們, 摘要們 = [], []
        monkeypatch.setattr(events, "接收者們", [])
        monkeypatch.setattr(lt, "統計", {"分鐘摘要": 0, "JSON失敗": 0})
        monkeypatch.setattr(lt, "存檔", {"摘要": False})
        monkeypatch.setattr(llm, "摘要_思考", True)
        回覆們 = [{"decision": "same"}] * 4 + [{"decision": "new_topic", "new_topic_start": "1:05:00", "topic_brief": "新"}]
        monkeypatch.setattr(summarize, "call_llm", lambda p: (提示們.append(p), json.dumps(回覆們.pop(0) if 回覆們 else {"decision": "same"}))[1])
        monkeypatch.setattr(summarize, "summarize_chunk", lambda 文字, **k: (摘要們.append(文字), "摘要")[1])
        n = lt.引擎(lt.stream_lines(str(稿), speed), 1, "x")
        return n, 提示們, 摘要們
    快 = 跑(0)
    慢 = 跑(2000)                      # 600 秒的稿 ÷ 2000 倍 = 0.3 秒
    assert 快 == 慢 and 快[0] == 2     # 第 5 輪在 1:05:00 切出新話題；兩種速度完全一樣
    assert "第300秒" in 快[2][1] and "第300秒" not in 快[2][0]


def timefmt_標記(秒):
    import timefmt
    return timefmt.秒轉字(秒)
