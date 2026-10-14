"""打包版不帶 av（PyAV）：替身模組（pyi_rth_av替身.py）、打包驗收（dist 裡沒有 av）、
打包會用到的程式只傳 numpy 陣列給 faster-whisper（不傳檔案路徑，替身才不會被用到）。
不連網、不需要真的轉錄模型（假模型）；子程序的那一個標成 slow。"""
import ast
import importlib.util
import sys
from pathlib import Path

import numpy as np
import pytest

專案 = Path(__file__).resolve().parent.parent
替身檔 = 專案 / "pyi_rth_av替身.py"


def _載入(名稱, 路徑):
    spec = importlib.util.spec_from_file_location(名稱, 路徑)
    模組 = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(模組)
    return 模組


# ---------- 替身模組 ----------
def test_替身被用到時丟出清楚的中文錯誤():
    hook = _載入("av替身_測試", 替身檔)
    替身 = hook.做替身()
    with pytest.raises(hook.沒有av錯誤, match="打包版沒有附 av（PyAV）.*只能傳 numpy 陣列.*av.open"):
        替身.open("x.wav")
    with pytest.raises(RuntimeError, match="當機紀錄"):             # 是 RuntimeError，當機紀錄會接到
        _ = 替身.audio
    assert not hasattr(替身, "__path__") and not hasattr(替身, "__file__")   # 匯入機制查的屬性照一般模組


def test_找不到av才放替身_找得到就不放(monkeypatch):
    hook = _載入("av替身_測試2", 替身檔)
    原本 = sys.modules.pop("av", None)
    try:
        assert hook.安裝() is False and "av" not in sys.modules        # 開發環境找得到真的 av：不放替身
        真的找 = importlib.util.find_spec
        monkeypatch.setattr(importlib.util, "find_spec", lambda 名, *a: None if 名 == "av" else 真的找(名, *a))
        assert hook.安裝() is True and sys.modules["av"].替身 is True
        assert hook.安裝() is False                                     # 已經有了：不重複放
    finally:
        sys.modules.pop("av", None)
        if 原本 is not None:
            sys.modules["av"] = 原本


@pytest.mark.slow
def test_沒有av時faster_whisper照常匯入_讀檔案才報錯():
    """另開 Python：讓替身以為找不到 av（模擬打包版沒帶）→ 放替身 → import faster_whisper 成功（用的是替身）；
    decode_audio 讀檔案丟出中文錯誤。"""
    程式 = f"""
import importlib.util, runpy, sys
真的找 = importlib.util.find_spec
importlib.util.find_spec = lambda 名, *a: None if 名 == "av" else 真的找(名, *a)
runpy.run_path({str(替身檔)!r})
importlib.util.find_spec = 真的找
import faster_whisper
from faster_whisper import WhisperModel
assert getattr(sys.modules["av"], "替身", False)
try:
    faster_whisper.decode_audio("不存在.wav")
except RuntimeError as e:
    print("錯誤：" + str(e))
"""
    import external
    r = external.執行([sys.executable, "-X", "utf8", "-c", 程式], capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert r.returncode == 0, r.stderr
    assert "錯誤：打包版沒有附 av（PyAV）" in r.stdout


# ---------- 打包設定與驗收 ----------
def test_spec排除av並放替身():
    spec = (專案 / "LiveSummary.spec").read_text(encoding="utf-8")
    assert '"av"]' in spec and 'av替身 = os.path.join(專案, "pyi_rth_av替身.py")' in spec
    assert '主程式 = 分析("app.py", 執行期hook=[av替身])' in spec and "runtime_hooks=list(執行期hook)" in spec


def test_打包驗收找出av的檔案(tmp_path):
    sys.path.insert(0, str(專案 / "scripts"))
    try:
        打包 = _載入("build_exe_av測試", 專案 / "scripts" / "build_exe.py")
    finally:
        sys.path.remove(str(專案 / "scripts"))
    內部 = tmp_path / "_internal"
    for 相對 in ("av/_core.pyd", "av.libs/libx264-165-abc.dll", "av-17.1.0.dist-info/METADATA",
                 "某處/libx265.dll", "ffmpeg/bin/avcodec-62.dll", "avahi/x.txt", "faster_whisper/audio.pyc"):
        (內部 / 相對).parent.mkdir(parents=True, exist_ok=True)
        (內部 / 相對).write_bytes(b"x")
    找到 = {Path(x).as_posix() for x in 打包.av的檔案(str(tmp_path))}
    assert 找到 == {"_internal/av/_core.pyd", "_internal/av.libs/libx264-165-abc.dll",
                  "_internal/av-17.1.0.dist-info/METADATA", "_internal/某處/libx265.dll"}   # 隨附 ffmpeg 的 avcodec 不算
    (tmp_path / "空").mkdir()
    (tmp_path / "空" / "_internal").mkdir()
    assert 打包.av的檔案(str(tmp_path / "空")) == []


# ---------- 打包會用到的程式只傳 numpy 陣列 ----------
# 呼叫 faster-whisper 轉錄／偵測語言的地方只准在這些函式裡；transcribe.轉錄（傳檔案路徑）只給開發工具用，打包的程式不准呼叫它
允許的呼叫處 = {("live_capture", "載入模型"), ("live_capture", "偵測語言"), ("live_capture", "轉錄一段"), ("transcribe", "轉錄")}
只給開發工具 = {("transcribe", "轉錄"), ("transcribe", "main"), ("transcribe", "下載音訊")}


def _本地模組們():
    return {p.stem for p in 專案.glob("*.py")}


def _打包會用到的模組():
    """從 app.py、helper.py 沿著 import（含函式裡的 import）找到的專案模組（打包版會帶進去的程式）。"""
    本地 = _本地模組們()
    已看, 待看 = set(), ["app", "helper"]
    while 待看:
        名 = 待看.pop()
        if 名 in 已看:
            continue
        已看.add(名)
        樹 = ast.parse((專案 / f"{名}.py").read_text(encoding="utf-8"))
        for 節點 in ast.walk(樹):
            if isinstance(節點, ast.Import):
                新 = [a.name.split(".")[0] for a in 節點.names]
            elif isinstance(節點, ast.ImportFrom) and 節點.module and 節點.level == 0:
                新 = [節點.module.split(".")[0]]
            else:
                continue
            待看 += [x for x in 新 if x in 本地 and x not in 已看]
    return 已看


def _所在函式(樹):
    """每個節點 → 包著它的最外層函式名稱。"""
    結果 = {}
    for 函式 in [n for n in 樹.body if isinstance(n, (ast.FunctionDef, ast.ClassDef))]:
        for 子 in ast.walk(函式):
            結果[id(子)] = 函式.name
        if isinstance(函式, ast.ClassDef):
            for 方法 in [n for n in 函式.body if isinstance(n, ast.FunctionDef)]:
                for 子 in ast.walk(方法):
                    結果[id(子)] = f"{函式.name}.{方法.name}"
    return 結果


def test_打包會用到的模組包含轉錄相關的程式():
    模組們 = _打包會用到的模組()
    assert {"live_capture", "transcribe", "first_run", "live_topics"} <= 模組們
    assert "vod_to_transcript" not in 模組們


def test_打包會用到的程式只在允許的地方呼叫faster_whisper():
    違規 = []
    for 名 in sorted(_打包會用到的模組()):
        樹 = ast.parse((專案 / f"{名}.py").read_text(encoding="utf-8"))
        所在 = _所在函式(樹)
        for 節點 in ast.walk(樹):
            if isinstance(節點, ast.Name) and 節點.id == "decode_audio" or \
                    isinstance(節點, ast.Attribute) and 節點.attr == "decode_audio":
                違規.append(f"{名}.py:{節點.lineno} 用到 decode_audio（會讀檔案，打包版沒有 av）")
            if isinstance(節點, ast.Call) and isinstance(節點.func, ast.Attribute) \
                    and 節點.func.attr in ("transcribe", "detect_language") \
                    and (名, 所在.get(id(節點), "（模組最上層）")) not in 允許的呼叫處:
                違規.append(f"{名}.py:{節點.lineno} 在 {所在.get(id(節點), '模組最上層')} 呼叫 .{節點.func.attr}()")
    assert not 違規, "打包會用到的程式只能在 live_capture 的三個函式傳 numpy 陣列給 faster-whisper：\n" + "\n".join(違規)


def test_傳檔案路徑的transcribe_轉錄只給開發工具用():
    """transcribe.轉錄() 傳的是檔案路徑：打包的程式（transcribe.py 以外）不准呼叫，transcribe.py 裡也只有 main 呼叫它。"""
    違規 = []
    for 名 in sorted(_打包會用到的模組()):
        樹 = ast.parse((專案 / f"{名}.py").read_text(encoding="utf-8"))
        所在 = _所在函式(樹)
        for 節點 in ast.walk(樹):
            if 名 != "transcribe":
                if isinstance(節點, ast.Attribute) and isinstance(節點.value, ast.Name) and 節點.value.id == "transcribe" \
                        and ("transcribe", 節點.attr) in 只給開發工具:
                    違規.append(f"{名}.py:{節點.lineno} 用到 transcribe.{節點.attr}")
                if isinstance(節點, ast.ImportFrom) and 節點.module == "transcribe" \
                        and any(("transcribe", a.name) in 只給開發工具 for a in 節點.names):
                    違規.append(f"{名}.py:{節點.lineno} from transcribe import …")
            elif isinstance(節點, ast.Call) and isinstance(節點.func, ast.Name) and 節點.func.id in ("轉錄", "main"):
                if 所在.get(id(節點), "（模組最上層）") not in ("main", "（模組最上層）"):
                    違規.append(f"transcribe.py:{節點.lineno} 在 {所在.get(id(節點))} 呼叫 {節點.func.id}()")
    assert not 違規, "\n".join(違規)


class _只收陣列的模型:
    """假的 WhisperModel：轉錄、偵測語言只要收到不是 numpy 陣列的東西就失敗。"""
    def __init__(self, *a, **k):
        self.收到 = []

    def _檢查(self, 音訊):
        assert isinstance(音訊, np.ndarray), f"傳給 faster-whisper 的不是 numpy 陣列：{type(音訊).__name__}"
        self.收到.append(音訊.dtype)

    def transcribe(self, 音訊, **k):
        self._檢查(音訊)
        return iter([]), None

    def detect_language(self, 音訊, **k):
        self._檢查(音訊)
        return "ja", 0.99, []


def test_直播轉錄實際傳給faster_whisper的是numpy陣列(monkeypatch):
    import faster_whisper

    import first_run
    import live_capture
    import transcribe
    模型們 = []

    def 做模型(*a, **k):
        模型們.append(_只收陣列的模型())
        return 模型們[-1]
    monkeypatch.setattr(faster_whisper, "WhisperModel", 做模型)
    monkeypatch.setattr(transcribe, "找顯示卡函式庫", lambda: None)
    monkeypatch.setattr(first_run, "顯示卡可用", lambda: True)
    monkeypatch.setattr(first_run, "準備模型", lambda *a, **k: None)
    monkeypatch.setattr(live_capture.events, "送出", lambda *a, **k: None)
    model = live_capture.載入模型("ja")                                  # 試音（np.zeros）
    音訊 = (np.random.default_rng(0).standard_normal(16000) * 0.1).astype(np.float32)
    live_capture.轉錄一段(model, 音訊, "ja")
    live_capture.偵測語言(model, [音訊, 音訊])
    assert model.收到 == [np.float32] * 4
