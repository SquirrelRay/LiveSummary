"""舊的 config.json 裡已停用的欄位（舊字幕框的 overlay 區塊、精簡模式的 hotkey_compact）：讀入時靜默忽略，不跳警告。
不需要介面、不呼叫 API。設定框儲存時保留這些舊區塊的測試在 test_介面冒煙.py（要建視窗）。"""
import json

import live_topics

舊overlay = {
    "click_through": True,
    "hotkey_toggle": "Ctrl+Shift+S",
    "summary_box": {"show": True, "font_size": 17, "position": "top"},
    "subtitle_box": {"show": True, "font_size": 19, "lines": 2},
}


def _寫設定(tmp_path, monkeypatch, 內容):
    路徑 = tmp_path / "config.json"
    路徑.write_text(json.dumps(內容, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(live_topics, "設定檔路徑", str(路徑))
    return 路徑


def test_舊的overlay與hotkey_compact_不跳警告(tmp_path, monkeypatch):
    _寫設定(tmp_path, monkeypatch, {"chat": False, "overlay": 舊overlay, "hotkey_compact": "Ctrl+Shift+M"})
    設定, 來源, 警告們 = live_topics.載入設定({})
    assert 警告們 == []
    assert 設定["chat"] is False and 來源["chat"] == "config.json"      # 其他欄位照常讀
    assert "overlay" not in 設定 and "hotkey_compact" not in 設定        # 已停用：不再出現在設定裡


def test_已停用欄位就算值是壞的也不警告(tmp_path, monkeypatch):
    _寫設定(tmp_path, monkeypatch, {"overlay": "壞掉", "hotkey_compact": 123})
    assert live_topics.載入設定({})[2] == []


def test_真的不認得的欄位仍然警告(tmp_path, monkeypatch):
    _寫設定(tmp_path, monkeypatch, {"overlay": {}, "打錯的欄位": 1})
    警告們 = live_topics.載入設定({})[2]
    assert len(警告們) == 1 and "打錯的欄位" in 警告們[0]


def test_專案現有的config_json_不跳警告():
    """用專案資料夾裡現有的 config.json（含舊的 overlay 區塊）讀一次。"""
    assert live_topics.載入設定({})[2] == []
