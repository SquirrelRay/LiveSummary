"""另開程序與程式自己帶的檔案（打包第 3 步）：
- 所有外部程式呼叫都經過 external.開啟，一律加 CREATE_NO_WINDOW（不跳黑色視窗）；原始碼裡沒有其他地方直接開程序。
- 開發 vs 打包後：streamlink／yt_audio 的指令、隨附 ffmpeg、顯示卡函式庫（cuBLAS）的位置。
  打包後用假的 sys.frozen、sys._MEIPASS、sys.executable 指到暫存資料夾模擬，不需要真的 exe。
- ffmpeg：隨附的優先，沒有才用系統上的；找到哪個寫進啟動里程碑紀錄。
- scripts/下載ffmpeg.py：SHA-256 不符時拒絕使用（假下載，不連網）。"""
import importlib.util
import io
import os
import re
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

import app_paths
import events
import external
import live_capture as lc
import startup_timeline as st
import transcribe

專案 = Path(__file__).resolve().parent.parent
不開視窗 = subprocess.CREATE_NO_WINDOW
真的python = sys.executable          # 打包版 fixture 會把 sys.executable 換成假的 exe


@pytest.fixture
def 打包版(monkeypatch, tmp_path):
    """模擬 PyInstaller 資料夾形式：tmp/直播摘要/直播摘要.exe、tmp/直播摘要/_internal（= sys._MEIPASS）。"""
    根 = tmp_path / "直播摘要"
    內部 = 根 / "_internal"
    內部.mkdir(parents=True)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(內部), raising=False)
    monkeypatch.setattr(sys, "executable", str(根 / "直播摘要.exe"))
    return 根


@pytest.fixture
def 記下Popen(monkeypatch):
    呼叫們 = []

    class 假程序:
        def __init__(self, 參數, **選項):
            self.args, self.選項, self.returncode = 參數, 選項, 0
            呼叫們.append(self)

        def communicate(self, timeout=None):
            return "", ""

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(subprocess, "Popen", 假程序)
    return 呼叫們


# ---------- 統一的開程序函式 ----------
def test_開啟一律加上不開視窗(記下Popen):
    external.開啟(["a.exe", "1"], stdout=subprocess.PIPE)
    external.開啟(["b.exe"], creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)       # 呼叫端自己的旗標保留
    assert 記下Popen[0].args == ["a.exe", "1"] and 記下Popen[0].選項["creationflags"] == 不開視窗
    assert 記下Popen[0].選項["stdout"] == subprocess.PIPE
    assert 記下Popen[1].選項["creationflags"] == 不開視窗 | subprocess.CREATE_NEW_PROCESS_GROUP


def test_執行也經過開啟_capture_output變成管線(記下Popen):
    r = external.執行(["nvidia-smi", "-L"], capture_output=True, text=True, timeout=2)
    assert r.returncode == 0 and r.args == ["nvidia-smi", "-L"]
    選項 = 記下Popen[0].選項
    assert 選項["creationflags"] == 不開視窗 and 選項["stdout"] == 選項["stderr"] == subprocess.PIPE


def test_執行逾時_殺掉子程序再丟出(monkeypatch):
    class 卡住:
        args, returncode, 殺了 = ["x"], None, False

        def __init__(self, *a, **k):
            卡住.實例 = self

        def communicate(self, timeout=None):
            if not self.殺了:
                raise subprocess.TimeoutExpired("x", timeout)
            return "", ""

        def kill(self):
            self.殺了 = True

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False
    monkeypatch.setattr(subprocess, "Popen", 卡住)
    with pytest.raises(subprocess.TimeoutExpired):
        external.執行(["x"], timeout=0.01)
    assert 卡住.實例.殺了


def test_原始碼裡只有external直接開程序():
    """避免以後新增的呼叫漏掉 CREATE_NO_WINDOW：程式（與會打包的模組）只准 external.py 用 subprocess 開程序。
    scripts\\check.py（git hook 用的檢查）、scripts\\引導截圖.py 是開發工具、只重跑 python 本身，不打包，不算。"""
    樣式 = re.compile(r"subprocess\.(Popen|run|call|check_call|check_output|getoutput|getstatusoutput)\b"
                    r"|os\.(system|popen|spawn\w*|exec\w*)\(|\bQProcess\b")
    例外 = {"external.py", os.path.join("scripts", "check.py"), os.path.join("scripts", "引導截圖.py")}
    違規 = []
    for 檔 in [*專案.glob("*.py"), *(專案 / "scripts").glob("*.py")]:
        相對 = str(檔.relative_to(專案))
        if 相對 in 例外:
            continue
        for 行號, 行 in enumerate(檔.read_text(encoding="utf-8").splitlines(), 1):
            if 樣式.search(行):
                違規.append(f"{相對}:{行號}: {行.strip()}")
    assert not 違規, "\n".join(違規)


# ---------- 開發時（沒打包）----------
def test_開發時_streamlink與yt_audio用python():
    assert not app_paths.已打包()
    assert external.streamlink指令("--json", "u") == [sys.executable, "-m", "streamlink_cli", "--json", "u"]
    指令 = external.yt_audio指令("u", "worst")
    assert 指令[0] == sys.executable and 指令[2:] == ["u", "worst"]
    assert os.path.samefile(指令[1], 專案 / "yt_audio.py")


def test_開發時_隨附ffmpeg在專案的vendor():
    assert Path(app_paths.隨附ffmpeg()) == 專案 / "vendor" / "ffmpeg" / "bin" / "ffmpeg.exe"


def test_開發時_顯示卡函式庫找site_packages(monkeypatch, tmp_path):
    import site
    bin路徑 = tmp_path / "nvidia" / "cublas" / "bin"
    bin路徑.mkdir(parents=True)
    (tmp_path / "nvidia" / "沒有bin").mkdir()
    monkeypatch.setattr(site, "getsitepackages", lambda: [str(tmp_path), str(tmp_path / "不存在")])
    assert app_paths.顯示卡函式庫資料夾們() == [str(bin路徑)]


# ---------- 打包後（模擬）----------
def test_打包後_streamlink改用helper(打包版):
    helper = str(打包版 / "helper.exe")
    assert app_paths.已打包()
    assert external.streamlink指令("--json", "u") == [helper, "--streamlink", "--json", "u"]
    assert external.yt_audio指令("u", "worst") == [helper, "--yt-audio", "u", "worst"]


def test_打包後_檢查直播呼叫helper而且不開視窗(打包版, monkeypatch):
    記下Popen = []

    class 回應:
        returncode = 0

        def __init__(self, 參數, **選項):
            self.args, self.選項 = 參數, 選項
            記下Popen.append(self)

        def communicate(self, timeout=None):
            return '{"streams": {"audio_only": {}}}', ""
    monkeypatch.setattr(subprocess, "Popen", 回應)
    assert lc.檢查直播("https://www.twitch.tv/fake") == "audio_only"
    p = 記下Popen[0]
    assert p.args[:2] == [str(打包版 / "helper.exe"), "--streamlink"] and p.選項["creationflags"] & 不開視窗


def test_打包後_隨附ffmpeg在MEIPASS(打包版, monkeypatch):
    exe = 打包版 / "_internal" / "ffmpeg" / "bin" / "ffmpeg.exe"
    assert Path(app_paths.隨附ffmpeg()) == exe
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"")
    monkeypatch.setattr(app_paths.shutil, "which", lambda 名: r"C:\系統\ffmpeg.exe")
    assert app_paths.ffmpeg位置() == (str(exe), "隨附")          # 系統上也有，還是隨附的優先


def test_打包後_隨附ffmpeg不存在_改用系統上的(打包版, monkeypatch):
    monkeypatch.setattr(app_paths.shutil, "which", lambda 名: r"C:\系統\ffmpeg.exe")
    assert app_paths.ffmpeg位置() == (r"C:\系統\ffmpeg.exe", "系統")


def test_都找不到ffmpeg_丟出中文錯誤(打包版, monkeypatch):
    monkeypatch.setattr(app_paths.shutil, "which", lambda 名: None)
    monkeypatch.setattr(app_paths.glob, "glob", lambda *a, **k: [])
    assert app_paths.ffmpeg位置() == (None, None)
    with pytest.raises(lc.直播錯誤, match="找不到 ffmpeg"):
        lc.找ffmpeg()


def test_找到哪個ffmpeg寫進啟動里程碑紀錄(打包版, monkeypatch, tmp_path):
    exe = Path(app_paths.隨附ffmpeg())
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"")
    紀 = st.里程碑紀錄(資料夾=str(tmp_path / "logs"))
    monkeypatch.setattr(st, "紀錄", 紀)
    紀.開始()
    assert lc.找ffmpeg() == str(exe)
    內容 = Path(紀.路徑).read_text(encoding="utf-8")
    assert "找到 ffmpeg" in 內容 and "來源=隨附" in 內容 and str(exe) in 內容


def test_打包後_顯示卡函式庫在MEIPASS_加進DLL搜尋與PATH(打包版, monkeypatch):
    bin路徑 = 打包版 / "_internal" / "nvidia" / "cublas" / "bin"
    bin路徑.mkdir(parents=True)
    import site
    monkeypatch.setattr(site, "getsitepackages", lambda: pytest.fail("打包後不該找 site-packages"))
    assert app_paths.顯示卡函式庫資料夾們() == [str(bin路徑)]

    加的 = []
    monkeypatch.setattr(transcribe.os, "add_dll_directory", 加的.append)
    monkeypatch.setattr(transcribe, "_加過", set())
    monkeypatch.setenv("PATH", r"C:\原本")
    transcribe.找顯示卡函式庫()
    transcribe.找顯示卡函式庫()          # 重複呼叫：不重複加
    assert 加的 == [str(bin路徑)]
    assert os.environ["PATH"] == str(bin路徑) + os.pathsep + r"C:\原本"


def test_打包後_沒有顯示卡函式庫資料夾_不出錯(打包版, monkeypatch):
    monkeypatch.setattr(transcribe, "_加過", set())
    monkeypatch.setattr(transcribe.os, "add_dll_directory", lambda p: pytest.fail("不該加"))
    assert app_paths.顯示卡函式庫資料夾們() == []
    transcribe.找顯示卡函式庫()


# ---------- helper.py（打包後 helper.exe 的進入點）----------
def test_helper參數不對_印用法回傳2(capsys):
    import helper
    assert helper.main([]) == 2
    assert helper.main(["--yt-audio", "只有網址"]) == 2
    assert "用法" in capsys.readouterr().err


def test_helper_yt_audio模式轉給yt_audio(monkeypatch):
    import helper
    import yt_audio
    收到 = []
    monkeypatch.setattr(yt_audio, "main", 收到.append)
    helper.main(["--yt-audio", "u", "worst"])
    assert 收到 == [["u", "worst"]]


@pytest.mark.slow          # 真的另開子程序（python helper.py），不連網
def test_helper_用打包後的指令跑得起streamlink(打包版):
    """打包後的指令把 helper.exe 換成「python helper.py」實際跑一次（--version 不連網），確認參數對得上。"""
    指令 = external.streamlink指令("--version")
    assert 指令[0] == str(打包版 / "helper.exe")
    r = external.執行([真的python, str(專案 / "helper.py"), *指令[1:]], capture_output=True, text=True,
                    encoding="utf-8", errors="replace", timeout=60)
    assert r.returncode == 0 and (r.stdout + r.stderr).startswith("streamlink ")


# ---------- scripts/下載ffmpeg.py ----------
def _載入下載腳本():
    spec = importlib.util.spec_from_file_location("下載ffmpeg", 專案 / "scripts" / "下載ffmpeg.py")
    模組 = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(模組)
    return 模組


def _假壓縮檔(多的=None):
    緩衝 = io.BytesIO()
    with zipfile.ZipFile(緩衝, "w") as z:
        z.writestr("ffmpeg-n9-win64-lgpl-shared/bin/ffmpeg.exe", b"fake exe")
        z.writestr("ffmpeg-n9-win64-lgpl-shared/LICENSE.txt", b"LGPL")
        if 多的:
            z.writestr(多的, b"x")
    return 緩衝.getvalue()


def _假網路(資料, 次數):
    def 開(網址, timeout=None):
        次數.append(網址)
        return io.BytesIO(資料)
    return 開


def test_下載ffmpeg_雜湊正確_解開到目的資料夾(tmp_path):
    import hashlib
    v = _載入下載腳本()
    資料 = _假壓縮檔()
    次數 = []
    目的 = tmp_path / "vendor" / "ffmpeg"
    exe = v.準備("https://假/ff.zip", "ff.zip", hashlib.sha256(資料).hexdigest(), str(目的), _假網路(資料, 次數), 進度=lambda *a: None)
    assert Path(exe) == 目的 / "bin" / "ffmpeg.exe" and Path(exe).read_bytes() == b"fake exe"
    assert (目的 / "LICENSE.txt").exists() and (目的 / "來源.txt").exists()
    assert (tmp_path / "vendor" / "下載" / "ff.zip").exists()          # 壓縮檔留著備份
    v.準備("https://假/ff.zip", "ff.zip", hashlib.sha256(資料).hexdigest(), str(目的), _假網路(資料, 次數), 進度=lambda *a: None)
    assert len(次數) == 1                                               # 已下載過且雜湊對：不重下


def test_下載ffmpeg_雜湊不符_拒絕使用(tmp_path):
    v = _載入下載腳本()
    目的 = tmp_path / "vendor" / "ffmpeg"
    with pytest.raises(v.雜湊不符, match="SHA-256 不符"):
        v.準備("https://假/ff.zip", "ff.zip", "0" * 64, str(目的), _假網路(_假壓縮檔(), []), 進度=lambda *a: None)
    assert not 目的.exists()                                            # 沒解開
    assert not (tmp_path / "vendor" / "下載" / "ff.zip").exists()       # 壞檔刪掉


def test_下載ffmpeg_壓縮檔有不安全路徑_拒絕(tmp_path):
    import hashlib
    v = _載入下載腳本()
    資料 = _假壓縮檔(多的="../../跑出去.txt")
    with pytest.raises(ValueError, match="不安全"):
        v.準備("u", "ff.zip", hashlib.sha256(資料).hexdigest(), str(tmp_path / "v" / "ffmpeg"), _假網路(資料, []),
             進度=lambda *a: None)
    assert not (tmp_path / "跑出去.txt").exists()


def test_釘住的版本是BtbN的LGPL_shared版():
    v = _載入下載腳本()
    assert v.網址.startswith("https://github.com/BtbN/FFmpeg-Builds/releases/download/autobuild-")
    assert "lgpl-shared" in v.檔名 and "gpl-shared" not in v.檔名.replace("lgpl", "")
    assert re.fullmatch(r"[0-9a-f]{64}", v.SHA256)


@pytest.fixture(autouse=True)
def _清事件():
    events.停止.clear()
    yield
    events.接收者們.clear()


# ---------- 缺外部程式時的提示：打包後與開發時不同 ----------
def test_開發時缺ffmpeg_提示安裝或跑下載腳本(monkeypatch):
    import first_run
    monkeypatch.setattr(app_paths, "ffmpeg位置", lambda: (None, None))
    assert first_run.缺ffmpeg標籤() == "找不到 ffmpeg：安裝後重新開啟程式"
    with pytest.raises(lc.直播錯誤) as e:
        lc.找ffmpeg()
    assert "winget install Gyan.FFmpeg" in str(e.value) and "下載ffmpeg.py" in str(e.value)
    assert "重新解壓縮" not in str(e.value)


def test_打包後缺ffmpeg_提示檔案不完整_不叫人裝winget(打包版, monkeypatch):
    import first_run
    import onboarding
    monkeypatch.setattr(app_paths, "ffmpeg位置", lambda: (None, None))
    with pytest.raises(lc.直播錯誤) as e:
        lc.找ffmpeg()
    assert "程式檔案不完整" in str(e.value) and "重新解壓縮" in str(e.value) and "winget" not in str(e.value)
    assert "重新解壓縮" in first_run.檢查ffmpeg(lambda: False)["標籤"]
    assert "winget" not in first_run.檢查ffmpeg(lambda: False)["標籤"]
    說明 = onboarding.怎麼處理("ffmpeg")
    assert "重新解壓縮" in 說明 and "winget" not in 說明 and "pip" not in 說明
    assert "pip" not in onboarding.怎麼處理("streamlink") and "重新解壓縮" in onboarding.怎麼處理("streamlink")


def test_開發時首次引導說明還是安裝指令():
    import onboarding
    assert "winget install Gyan.FFmpeg" in onboarding.怎麼處理("ffmpeg")
    assert "pip install streamlink" in onboarding.怎麼處理("streamlink")
    assert onboarding.怎麼處理("顯示卡") == onboarding.怎麼處理們["顯示卡"]


def test_打包後streamlink檢查看helper_exe在不在(打包版, monkeypatch):
    import first_run
    monkeypatch.undo()          # conftest 的 autouse 假的 找得到streamlink 先拿掉，測真的；下面重新模擬打包
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(打包版 / "直播摘要.exe"))
    assert first_run.找得到streamlink() is False
    assert "重新解壓縮" in first_run.檢查streamlink()["標籤"]
    (打包版 / "helper.exe").write_bytes(b"")
    assert first_run.找得到streamlink() is True
