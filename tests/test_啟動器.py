"""LiveSummary.exe 啟動器（打包第 5 步之一，stub\\Stub.cs）：
在檔案總管直接點開 zip 裡的 exe 時，Windows 只把「那一個檔案」解壓縮到暫存資料夾，PyInstaller 的主程式一定跑不起來
（而且它在 Python 開始執行前就會跳英文錯誤，程式裡沒辦法改成中文），所以使用者點的是這支獨立的小啟動器：
旁邊檔案齊全 → 啟動 LiveSummaryApp.exe 後結束；缺檔 → 中文提示後結束。
慢測試（用 Windows 內建的 csc.exe 真的編譯、真的開視窗）：python scripts/check.py --all 才跑。"""
import ctypes
import os
import shutil
import sys
import time
from ctypes import wintypes
from pathlib import Path

import pytest

import external
import version

專案 = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(專案 / "scripts"))
import stub_build

sys.path.remove(str(專案 / "scripts"))

壓縮檔提示 = "請先把整個壓縮檔解壓縮，再執行 LiveSummary.exe"


# ---------- 快速測試（不編譯）----------
def test_提示文字和條件寫在原始碼裡():
    內容 = (專案 / "stub" / "Stub.cs").read_text(encoding="utf-8")
    assert 壓縮檔提示 in 內容
    assert '"LiveSummaryApp.exe"' in 內容 and '"helper.exe"' in 內容 and '"_internal"' in 內容      # 缺這些才提示


def test_spec的主程式名稱和啟動器找的一致():
    assert stub_build.主程式檔名 == "LiveSummaryApp.exe"
    assert f'主程式檔名 = "{stub_build.主程式檔名.removesuffix(".exe")}"' in (專案 / "LiveSummary.spec").read_text(encoding="utf-8")


def test_找得到內建的csc():
    assert stub_build.找csc(), "Windows 內建的 csc.exe 找不到：打包用的 LiveSummary.exe 啟動器編不出來"


# ---------- 慢測試：真的編譯、真的跑 ----------
user32 = ctypes.windll.user32
EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
WM_CLOSE = 0x0010


def _視窗們(pid):
    找到 = []

    def 回呼(hwnd, _):
        p = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
        if p.value == pid and user32.IsWindowVisible(hwnd):
            找到.append(hwnd)
        return True
    user32.EnumWindows(EnumWindowsProc(回呼), 0)
    return 找到


def _文字(hwnd):
    緩衝 = ctypes.create_unicode_buffer(2048)
    user32.GetWindowTextW(hwnd, 緩衝, 2048)
    return 緩衝.value


def _視窗文字們(hwnd):
    """對話框本身的標題＋底下每個子控制項的文字。"""
    字們 = [_文字(hwnd)]

    def 回呼(h, _):
        字們.append(_文字(h))
        return True
    user32.EnumChildWindows(hwnd, EnumWindowsProc(回呼), 0)
    return "\n".join(字們)


def _等視窗(程序, 秒=15):
    終 = time.time() + 秒
    while time.time() < 終:
        視窗們 = _視窗們(程序.pid)
        if 視窗們:
            return 視窗們[0]
        if 程序.poll() is not None:
            return None
        time.sleep(0.1)
    return None


@pytest.fixture(scope="module")
def 啟動器exe(tmp_path_factory):
    根 = tmp_path_factory.mktemp("啟動器編譯")
    return stub_build.編譯(str(根 / "LiveSummary.exe"), str(根 / "obj"))


@pytest.fixture(scope="module")
def 假主程式exe(tmp_path_factory):
    """假的 LiveSummaryApp.exe：把收到的引數和自己的工作資料夾寫進旁邊的 啟動記號.txt 就結束。"""
    根 = tmp_path_factory.mktemp("假主程式")
    (根 / "Fake.cs").write_text(
        'using System; using System.IO;\n'
        'static class Fake { static void Main(string[] a) {\n'
        '  File.WriteAllText(Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "啟動記號.txt"),\n'
        '    string.Join("|", a) + "\\n" + Environment.CurrentDirectory, new System.Text.UTF8Encoding(false)); } }\n',
        encoding="utf-8")
    exe = 根 / "LiveSummaryApp.exe"
    結果 = external.執行([stub_build.找csc(), "/nologo", "/target:exe", f"/out:{exe}", "/codepage:65001", str(根 / "Fake.cs")],
                       timeout=120, capture_output=True)
    assert 結果.returncode == 0 and exe.exists(), 結果.stdout
    return str(exe)


def _跑並等提示(exe):
    程序 = external.開啟([exe])
    try:
        視窗 = _等視窗(程序)
        assert 視窗 is not None, "啟動器沒有跳出提示視窗"
        文字 = _視窗文字們(視窗)
        user32.PostMessageW(視窗, WM_CLOSE, 0, 0)
        程序.wait(timeout=15)
        return 文字, 程序.returncode
    finally:
        if 程序.poll() is None:
            程序.kill()


@pytest.mark.parametrize("暫存名", ["4b62cb0c-264a-4128-8a85-c12289107b8f_LiveSummary-v1.0.0.zip.b8f",    # 實測：Windows 11 檔案總管
                                    "Temp1_LiveSummary-v1.0.0.zip"])
@pytest.mark.slow
def test_從壓縮檔暫存資料夾單獨開_跳解壓縮提示並結束(啟動器exe, tmp_path, 暫存名):
    """檔案總管開 zip 裡的 exe：只會有這一個檔案，放在 %TEMP%\\Temp1_壓縮檔名.zip\\LiveSummary\\。"""
    資料夾 = tmp_path / 暫存名 / "LiveSummary"
    資料夾.mkdir(parents=True)
    exe = shutil.copy(啟動器exe, 資料夾 / "LiveSummary.exe")
    文字, 結束碼 = _跑並等提示(exe)
    assert 壓縮檔提示 in 文字 and "直播摘要" in 文字
    assert 結束碼 == 1                                 # 提示後結束，沒有啟動任何程式


@pytest.mark.slow
def test_其他地方單獨複製了exe_說程式檔案不完整(啟動器exe, tmp_path):
    資料夾 = tmp_path / "某個資料夾"
    資料夾.mkdir()
    exe = shutil.copy(啟動器exe, 資料夾 / "LiveSummary.exe")
    文字, 結束碼 = _跑並等提示(exe)
    assert "程式檔案不完整" in 文字 and "LiveSummaryApp.exe" in 文字 and "_internal" in 文字
    assert 壓縮檔提示 not in 文字                       # 不是壓縮檔暫存位置就不亂說
    assert 結束碼 == 1


@pytest.mark.slow
def test_只缺_internal也提示(啟動器exe, 假主程式exe, tmp_path):
    """主程式在、helper.exe 在，但沒有 _internal（PyInstaller 一定跑不起來）。"""
    資料夾 = tmp_path / "缺內部"
    資料夾.mkdir()
    shutil.copy(啟動器exe, 資料夾 / "LiveSummary.exe")
    shutil.copy(假主程式exe, 資料夾 / "LiveSummaryApp.exe")
    (資料夾 / "helper.exe").write_bytes(b"x")
    文字, 結束碼 = _跑並等提示(str(資料夾 / "LiveSummary.exe"))
    assert "_internal" in 文字 and "helper.exe" not in 文字.split("找不到：")[-1].split("）")[0]
    assert 結束碼 == 1


@pytest.mark.slow
def test_檔案齊全的正常解壓縮_不跳提示_啟動主程式_就算放在Temp資料夾裡(啟動器exe, 假主程式exe, tmp_path):
    """tmp_path 本身就在 %TEMP% 底下（和壓縮檔暫存位置一樣在暫存資料夾裡）：只要檔案齊全就一定不能被擋。"""
    資料夾 = tmp_path / "Temp1_就算名字很像.zip" / "LiveSummary"
    (資料夾 / "_internal").mkdir(parents=True)
    shutil.copy(啟動器exe, 資料夾 / "LiveSummary.exe")
    shutil.copy(假主程式exe, 資料夾 / "LiveSummaryApp.exe")
    (資料夾 / "helper.exe").write_bytes(b"x")
    程序 = external.開啟([str(資料夾 / "LiveSummary.exe"), "--參數 一", "b"])
    try:
        程序.wait(timeout=20)
        assert _視窗們(程序.pid) == []
        assert 程序.returncode == 0
        記號 = 資料夾 / "啟動記號.txt"
        終 = time.time() + 10
        while not 記號.exists() and time.time() < 終:
            time.sleep(0.1)
        行們 = 記號.read_text(encoding="utf-8").splitlines()
        assert 行們[0] == "--參數 一|b"                 # 引數原樣傳給主程式
        assert os.path.normcase(行們[1]).rstrip("\\") == os.path.normcase(str(資料夾)).rstrip("\\")     # 工作資料夾是 exe 所在位置
    finally:
        if 程序.poll() is None:
            程序.kill()


@pytest.mark.slow
def test_啟動器的檔案內容有版本號(啟動器exe):
    import pefile
    pe = pefile.PE(啟動器exe)
    try:
        表 = {}
        for 資訊 in pe.FileInfo:
            for 項 in 資訊:
                for 字串表 in getattr(項, "StringTable", []) or []:
                    表.update({k.decode(): v.decode() for k, v in 字串表.entries.items()})
    finally:
        pe.close()
    assert 表["FileVersion"] == version.版本 and 表["ProductVersion"] == version.版本
    assert 表["FileDescription"] == "直播摘要" and 表["ProductName"] == "直播摘要"
    assert os.path.getsize(啟動器exe) < 100 * 1024


@pytest.mark.slow
def test_有圖示檔時啟動器套用_沒有時用預設都編得出來(tmp_path):
    """assets/icon.ico 之後才會有：沒有時編譯不能失敗；有時（這裡用 Qt 產生一個 ico）也要編得出來。"""
    from PySide6.QtGui import QColor, QImage
    ico = tmp_path / "icon.ico"
    圖 = QImage(64, 64, QImage.Format_ARGB32)
    圖.fill(QColor("#3366cc"))
    assert 圖.save(str(ico), "ICO")
    沒圖示 = stub_build.編譯(str(tmp_path / "a" / "LiveSummary.exe"), str(tmp_path / "a" / "obj"), 圖示=str(tmp_path / "不存在.ico"))
    有圖示 = stub_build.編譯(str(tmp_path / "b" / "LiveSummary.exe"), str(tmp_path / "b" / "obj"), 圖示=str(ico))
    assert os.path.getsize(有圖示) > os.path.getsize(沒圖示)         # 圖示資源讓檔案變大
