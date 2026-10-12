"""檢查直播（連線階段）：用假的子程序，不連網、不需要 streamlink。
- 按結束（events.停止）時要在約 0.2 秒內放棄並殺掉子程序，丟出中文錯誤「已取消啟動」，不能卡住、不留背景程序。
- 正常完成時要送出 stage 事件。
"""
import json
import subprocess
import time

import pytest

import events
import live_capture


class 假子程序:
    def __init__(self, 回應=None, 要等多久=999):
        self.回應 = 回應
        self.起 = time.time()
        self.要等多久 = 要等多久
        self.被殺了 = False

    def communicate(self, timeout=None):
        if self.被殺了:
            return "", ""
        if time.time() - self.起 < self.要等多久:
            time.sleep(timeout or 0)
            raise subprocess.TimeoutExpired("fake", timeout)
        return json.dumps(self.回應), ""

    def kill(self):
        self.被殺了 = True


@pytest.fixture(autouse=True)
def _清事件():
    events.停止.clear()
    送出們 = []
    events.接收者們.append(lambda 種類, 內容: 送出們.append((種類, 內容)))
    yield 送出們
    events.接收者們.clear()
    events.停止.clear()


def test_等待中按結束_很快取消並殺掉子程序(monkeypatch):
    子 = 假子程序()
    monkeypatch.setattr(live_capture.subprocess, "Popen", lambda *a, **k: 子)
    events.停止.set()
    起 = time.time()
    with pytest.raises(live_capture.直播錯誤, match="已取消啟動"):
        live_capture.檢查直播("https://www.twitch.tv/fake")
    assert time.time() - 起 < 2
    assert 子.被殺了


def test_正常完成_送出stage事件並回傳串流名(monkeypatch, _清事件):
    子 = 假子程序({"streams": {"audio_only": {}}}, 要等多久=0)
    monkeypatch.setattr(live_capture.subprocess, "Popen", lambda *a, **k: 子)
    assert live_capture.檢查直播("https://www.twitch.tv/fake") == "audio_only"
    assert ("stage", {"階段": "連線直播、確認有開播"}) in _清事件


def test_沒開播_丟出中文錯誤(monkeypatch):
    子 = 假子程序({"error": "No streams found"}, 要等多久=0)
    monkeypatch.setattr(live_capture.subprocess, "Popen", lambda *a, **k: 子)
    with pytest.raises(live_capture.直播錯誤, match="沒有開播"):
        live_capture.檢查直播("https://www.twitch.tv/fake")
