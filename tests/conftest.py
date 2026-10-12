import os
import sys
import threading

import numpy as np
import pytest

# 讓測試能直接 import 專案根目錄的模組
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import events
import live_capture as lc
import startup_timeline as st
import stream_clock

小段 = 4            # 測試用的假分段位元組數（只在測試裡縮小，正式程式的 20 秒分段不變）


class 假時鐘:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


class 假管線:
    """p1／p2 共用：stdout.read 每次吐出一段，並讓假時鐘前進一段的秒數（lc.段秒數，預設 20；模擬真的要等這麼久才收滿一段）。
    讀聲音的執行緒會搶先讀完，所以要等程式處理完上一段（送出 status 事件）才吐下一段，時鐘才對得上。"""

    def __init__(self, 段們, 時鐘):
        self.段們, self.時鐘 = list(段們), 時鐘
        self.stdout = self
        self.可讀 = threading.Semaphore(1)
        events.接收者們.append(lambda 種類, 內容: self.可讀.release() if 種類 == "status" else None)

    def peek(self, n=1):          # 等第一個位元組：假管線馬上就有資料，時鐘不動（音訊第 0 秒 = 時刻 0）
        return b"x"

    def read(self, n):
        self.可讀.acquire(timeout=5)
        self.時鐘.t += lc.段秒數
        return self.段們.pop(0) if self.段們 else b""

    def close(self):
        pass

    def kill(self):
        pass


def 音(振幅):
    return (np.full(小段, 振幅, dtype=np.int16)).tobytes()


靜音, 人聲, 音樂 = 音(0), 音(8000), 音(3000)      # 音樂：音量夠大，但假的 VAD 認為沒有人聲


@pytest.fixture
def 流程(monkeypatch, tmp_path):
    時鐘 = 假時鐘()
    紀 = st.里程碑紀錄(資料夾=str(tmp_path), 時鐘=時鐘)
    monkeypatch.setattr(st, "紀錄", 紀)
    紀.開始()
    monkeypatch.setattr(lc, "每段位元組", 小段)
    monkeypatch.setattr(lc, "取樣率", 2)                       # 4 位元組 = 2 個取樣 = 1 秒，只影響紀錄裡的「實際秒」
    monkeypatch.setattr(lc, "含人聲", lambda a: bool(np.abs(a).max() >= 0.2))     # 假 VAD：只有 8000 以上算人聲
    偵測到 = []
    monkeypatch.setattr(lc, "載入模型", lambda 語言: object())
    monkeypatch.setattr(lc, "偵測語言", lambda model, 音訊們: (偵測到.append(len(音訊們)), "ja")[1])
    monkeypatch.setattr(lc, "轉錄一段", lambda model, 音訊, 語言: [(0.5, "こんにちは")])
    events.停止.clear()
    events.重新偵測.clear()
    events.接收者們.clear()

    def 跑(段們, 語言="auto"):
        管線 = 假管線(段們, 時鐘)
        monkeypatch.setattr(lc.subprocess, "Popen", lambda *a, **k: 管線)
        s = object.__new__(lc.live_session)
        s.網址, s.串流名, s.ffmpeg, s.語言 = "https://x/fake", "audio_only", "ffmpeg", 語言
        s.稿路徑, s.存稿, s.音訊資料夾, s.聊天 = str(tmp_path / "稿.txt"), False, None, None
        s.存了段數 = s.存了位元組 = 0
        s._警告過 = False
        s.時軸 = stream_clock.時軸(開播=0.0, 時鐘=時鐘, 延遲=0.0)   # 假開播時間 = 時刻 0、沒有延遲：直播秒 = 音訊秒
        s.吐出 = list(s)              # [(直播秒數, "[mm:ss] 文字"), ...]
        return 紀, 偵測到, s

    return 跑


def 秒數(紀, 名稱):
    with open(紀.路徑, encoding="utf-8") as f:
        for 行 in f:
            if 名稱 in 行:
                return float(行.split("+")[1].split("s")[0])
    return None




# ---------- 保護：測試不准在專案資料夾留下新檔案 ----------
專案根 = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
忽略資料夾 = {".git", "__pycache__", ".pytest_cache", ".ruff_cache"}      # 工具自己的快取，不算污染


def 專案檔案們():
    """專案資料夾（含子資料夾）目前所有檔案的相對路徑集合。"""
    結果 = set()
    for 路, 資料夾們, 檔們 in os.walk(專案根):
        資料夾們[:] = [d for d in 資料夾們 if d not in 忽略資料夾]
        結果.update(os.path.relpath(os.path.join(路, f), 專案根) for f in 檔們)
    return 結果


def pytest_sessionstart(session):
    session.config._專案檔案前 = 專案檔案們()


def pytest_sessionfinish(session, exitstatus):
    新增 = sorted(專案檔案們() - session.config._專案檔案前)
    if 新增:
        sys.stderr.write("\n【失敗】測試在專案資料夾留下了新檔案（請改用 tmp_path）：\n"
                         + "\n".join(f"  {f}" for f in 新增) + "\n")
        session.exitstatus = pytest.ExitCode.TESTS_FAILED
