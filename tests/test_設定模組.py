"""設定模組 config.py：出廠預設不受執行時改寫的全域值影響（還原預設值的 bug）、寫入前備份、原子寫入、範例設定檔、沒有 config.json 也能用。
config.json 一律換到 tmp_path，不讀也不寫本機的 config.json；假模型，不花 API、不連網。"""
import json
import os
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

import capsule
import config
import events
import live_topics
import llm
import settings_page
import summarize
import transcribe

範例檔 = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.example.json")

# 和出廠預設都不一樣的「上一場」設定
上一場 = {"model": "上一場的模型", "whisper_model": "tiny", "min_topic_min": 5, "max_topic_min": 40,
         "minute_sentences": 3, "price_input": 9.0, "price_output": 99.0, "language": "ja"}


@pytest.fixture
def 設定檔(tmp_path, monkeypatch):
    路徑 = tmp_path / "config.json"
    monkeypatch.setattr(config, "設定檔路徑", str(路徑))
    return 路徑


@pytest.fixture
def 保留全域值(monkeypatch):
    """執行() 會改寫這些全域值；先登記給 monkeypatch，測試結束自動還原，不污染其他測試。"""
    for 模組, 名們 in ((live_topics, ("MIN_TOPIC_MIN", "MAX_TOPIC_MIN", "MINUTE_SENTENCES")),
                     (summarize, ("MODEL", "語言說明")), (transcribe, ("GPU_MODEL",)),
                     (llm, ("PROVIDER", "BASE_URL", "API_KEY_ENV", "摘要_思考"))):
        for 名 in 名們:
            monkeypatch.setattr(模組, 名, getattr(模組, 名))
    monkeypatch.setattr(live_topics, "單價", dict(live_topics.單價))
    monkeypatch.setattr(live_topics, "存檔", dict(live_topics.存檔))
    monkeypatch.setattr(live_topics, "統計", dict(live_topics.統計))
    monkeypatch.setattr(llm, "用量", dict(llm.用量))
    monkeypatch.setattr(events, "接收者們", [])
    events.停止.clear()


def 跑一場假的(tmp_path, monkeypatch, 設定):
    """用假模型跑一場文字稿（會改寫 summarize.MODEL、transcribe.GPU_MODEL、MIN_TOPIC_MIN 等全域值）。"""
    稿 = tmp_path / "稿.txt"
    稿.write_text("".join(f"[{m:02d}:00] 第{m}分鐘" + "字" * 120 + "\n" for m in range(4)), encoding="utf-8")
    monkeypatch.setattr(llm, "檢查金鑰", lambda: None)
    monkeypatch.setattr(summarize, "call_llm", lambda 提示詞: json.dumps(
        {"decision": "same", "topic_brief": "假話題", "side_notes": []}, ensure_ascii=False))
    monkeypatch.setattr(summarize, "summarize_chunk", lambda *a, **k: "【話題標題】假\n【摘要】假")
    llm.套用設定(設定)
    assert live_topics.執行(設定, 檔案=str(稿)) is True


# ---------- 還原預設值：一律是出廠預設，不是上一場的值 ----------
def test_跑過一場後_出廠預設不變(tmp_path, monkeypatch, 設定檔, 保留全域值):
    出廠 = config.出廠預設()
    跑一場假的(tmp_path, monkeypatch, 出廠 | 上一場)
    assert summarize.MODEL == "上一場的模型" and transcribe.GPU_MODEL == "tiny"          # 全域值真的被改寫了
    assert (live_topics.MIN_TOPIC_MIN, live_topics.MAX_TOPIC_MIN, live_topics.MINUTE_SENTENCES) == (5, 40, 3)
    assert config.出廠預設() == 出廠
    with open(範例檔, encoding="utf-8") as f:
        assert config.出廠預設() == json.load(f)


def test_跑過一場後_不合法的值退回出廠預設(tmp_path, monkeypatch, 設定檔, 保留全域值):
    跑一場假的(tmp_path, monkeypatch, config.出廠預設() | 上一場)
    設定檔.write_text(json.dumps({"model": "", "whisper_model": 1, "min_topic_min": 50, "max_topic_min": 10}), encoding="utf-8")
    設定, 來源, 警告們 = config.載入設定()
    assert (設定["model"], 設定["whisper_model"]) == ("claude-haiku-5-5", "large-v3-turbo")
    assert (設定["min_topic_min"], 設定["max_topic_min"]) == (3, 15)
    assert "改用預設值 'claude-haiku-5-5'" in 警告們[0] and 來源["model"] == "內建預設"


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def test_設定框還原預設值_跑過一場後仍是出廠預設(qapp, tmp_path, monkeypatch, 設定檔, 保留全域值):
    跑一場假的(tmp_path, monkeypatch, config.出廠預設() | 上一場)
    設定檔.write_text(json.dumps(config.出廠預設() | 上一場, ensure_ascii=False), encoding="utf-8")
    主 = SimpleNamespace(面板=SimpleNamespace(翻譯將啟用=lambda: True, 聊天將開啟=lambda: False), 設方向=lambda 置頂: None, 執行中=lambda: False)
    頁 = settings_page.設定頁(主)
    頁.載入()
    assert 頁.欄["model"].text() == "上一場的模型" and 頁.欄["minute_sentences"].value() == 3     # 表單是 config.json 的值
    頁.還原預設()
    出廠 = config.出廠預設()
    assert 頁.讀全部() == {k: 出廠[k] for k in 頁.讀全部()}
    assert 頁.欄["model"].text() == "claude-haiku-5-5"
    頁.deleteLater()


# ---------- 寫入：備份、原子寫入、保留其他欄位 ----------
def test_寫入前備份_只改指定欄位_其他原樣保留(設定檔):
    原本 = {"chat": True, "overlay": {"summary_box": {"font_size": 17}}, "hotkey_compact": "Ctrl+Shift+M",
          "translate_batch_lines": 4, "表單外的欄位": [1, 2]}
    設定檔.write_text(json.dumps(原本, ensure_ascii=False, indent=2), encoding="utf-8")
    寫前 = 設定檔.read_bytes()
    config.寫入設定({"chat": False, "minute_sentences": 3})
    assert (設定檔.parent / "config.backup.json").read_bytes() == 寫前
    之後 = json.loads(設定檔.read_text(encoding="utf-8"))
    assert 之後 == 原本 | {"chat": False, "minute_sentences": 3}
    assert [p.name for p in 設定檔.parent.iterdir() if p.name.endswith(".tmp")] == []


def test_沒有config_json時寫入_建立新檔不備份(設定檔):
    config.寫入設定({"chat": False})
    assert json.loads(設定檔.read_text(encoding="utf-8")) == {"chat": False}
    assert not (設定檔.parent / "config.backup.json").exists()


def _寫一半就失敗(內容, f, **k):
    f.write('{"chat": fal')
    raise OSError("磁碟滿了（模擬）")


@pytest.mark.parametrize("壞在", ["寫暫存檔", "取代原檔"])
def test_寫入中途失敗_原本的config_json不會損壞(設定檔, monkeypatch, 壞在):
    設定檔.write_text(json.dumps({"chat": True, "overlay": {"a": 1}}, ensure_ascii=False, indent=2), encoding="utf-8")
    寫前 = 設定檔.read_bytes()
    if 壞在 == "寫暫存檔":
        monkeypatch.setattr(config.json, "dump", _寫一半就失敗)
    else:
        monkeypatch.setattr(config.os, "replace", lambda *a: (_ for _ in ()).throw(OSError("檔案被鎖住（模擬）")))
    with pytest.raises(OSError):
        config.寫入設定({"chat": False})
    assert 設定檔.read_bytes() == 寫前
    assert [p.name for p in 設定檔.parent.iterdir() if p.name.endswith(".tmp")] == []     # 暫存檔清掉


def test_膠囊寫設定_走同一個寫入函式(設定檔):
    設定檔.write_text(json.dumps({"overlay": {"a": 1}, "chat": False}), encoding="utf-8")
    寫前 = 設定檔.read_bytes()
    assert capsule.寫設定("capsule_show_usage", True) is True
    assert json.loads(設定檔.read_text(encoding="utf-8")) == {"overlay": {"a": 1}, "chat": False, "capsule_show_usage": True}
    assert (設定檔.parent / "config.backup.json").read_bytes() == 寫前       # 膠囊也會先備份


def test_膠囊寫設定_原檔讀不懂就失敗且不動原檔(設定檔):
    設定檔.write_text("{壞掉", encoding="utf-8")
    assert capsule.寫設定("capsule_show_usage", True) is False
    assert 設定檔.read_text(encoding="utf-8") == "{壞掉"


# ---------- 範例檔、沒有 config.json ----------
def test_範例設定檔就是出廠預設_讀入不警告(設定檔):
    with open(範例檔, encoding="utf-8") as f:
        assert json.load(f) == config.出廠預設()
    設定檔.write_bytes(Path(範例檔).read_bytes())
    設定, 來源, 警告們 = config.載入設定()
    assert 警告們 == [] and 設定 == config.出廠預設() and set(來源.values()) == {"config.json"}


def test_沒有config_json_全部用出廠預設_不警告也不建立檔案(設定檔):
    設定, 來源, 警告們 = config.載入設定()
    assert 警告們 == [] and 設定 == config.出廠預設() and set(來源.values()) == {"內建預設"}
    assert not 設定檔.exists()


def test_出廠預設_每次是新的一份():
    a = config.出廠預設()
    a["model"] = "被改掉"
    assert config.出廠預設()["model"] == "claude-haiku-5-5"


def test_語言清單():
    assert config.語言代碼們 == ("zh", "ja", "en", "ko", "auto")
    assert config.外語們 == ("ja", "en", "ko")
    assert config.語言選項()[-1] == ("自動偵測", "auto") and config.語言選項(自動在前=True)[0] == ("自動偵測", "auto")
