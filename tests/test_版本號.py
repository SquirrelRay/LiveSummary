"""版本號（打包第 5 步之一）：只寫在 version.py（v1 = 1.0.0），其他地方都從那裡讀。
顯示在：設定框底部、當機紀錄、exe 檔案內容（詳細資料）、zip 檔名（LiveSummary-v1.0.0.zip）。"""
import importlib.util
import re
import sys
from pathlib import Path

import version

專案 = Path(__file__).resolve().parent.parent


def _載入(名稱, 路徑):
    spec = importlib.util.spec_from_file_location(名稱, 路徑)
    模組 = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(模組)
    return 模組


def test_第一版是1_0_0():
    assert version.版本 == "1.0.0"
    assert version.版本們() == (1, 0, 0, 0)
    assert version.版本字() == "v1.0.0"
    assert version.壓縮檔名() == "LiveSummary-v1.0.0.zip"


def test_版本們補滿四段():
    原 = version.版本
    try:
        version.版本 = "2.3"
        assert version.版本們() == (2, 3, 0, 0)
        version.版本 = "2.3.4"
        assert version.版本們() == (2, 3, 4, 0)
        assert version.壓縮檔名() == "LiveSummary-v2.3.4.zip"
    finally:
        version.版本 = 原


def test_版本號只寫在version_py一個地方():
    """其他 .py／.spec 不准自己寫死 1.0.0（tests 除外）。"""
    樣式 = re.compile(r"(?<![\d.])1\.0\.0(?![\d.])")
    for 檔 in [*專案.glob("*.py"), *(專案 / "scripts").glob("*.py"), 專案 / "LiveSummary.spec"]:
        if 檔.name == "version.py":
            continue
        for 行號, 行 in enumerate(檔.read_text(encoding="utf-8").splitlines(), 1):
            assert not 樣式.search(行), f"{檔.name}:{行號} 版本號寫死了，要從 version.py 讀：{行.strip()}"


def test_exe檔案內容的欄位來自version_py():
    資 = version.檔案資訊("LiveSummary.exe")
    assert 資["FileVersion"] == 資["ProductVersion"] == version.版本
    assert 資["FileDescription"] == 資["ProductName"] == "直播摘要"
    assert 資["OriginalFilename"] == "LiveSummary.exe" and 資["InternalName"] == "LiveSummary"
    assert version.檔案資訊("helper.exe", "別的說明")["FileDescription"] == "別的說明"


def test_打包腳本用version_py的檔名做壓縮檔():
    sys.path.insert(0, str(專案 / "scripts"))
    try:
        打包 = _載入("build_exe_測試", 專案 / "scripts" / "build_exe.py")
    finally:
        sys.path.remove(str(專案 / "scripts"))
    assert Path(打包.壓縮檔).name == "LiveSummary-v1.0.0.zip"
    assert "LiveSummary.exe" in 打包.必要檔案 and "helper.exe" in 打包.必要檔案 and not any("App" in f for f in 打包.必要檔案)


def test_spec的exe版本資源從version_py來():
    內容 = (專案 / "LiveSummary.spec").read_text(encoding="utf-8")
    assert "version.版本們()" in 內容 and "version.檔案資訊(" in 內容 and "version=版本資源檔(" in 內容


def test_設定框底部顯示版本號():
    """設定頁的版本字是 version.版本字()（單元化：不開真的視窗，只看原始碼；畫面上的字在 test_介面冒煙 驗）。"""
    內容 = (專案 / "settings_page.py").read_text(encoding="utf-8")
    assert "version.版本字()" in 內容


# ---------- 圖示位置（assets\icon.ico，之後由 Ray 提供；沒有就用預設，打包不能失敗）----------
def test_沒有圖示檔就回傳None(tmp_path, monkeypatch):
    import app_paths
    monkeypatch.setattr(app_paths, "程式資料夾", lambda: str(tmp_path))
    assert app_paths.圖示相對位置 == r"assets\icon.ico"
    assert app_paths.圖示檔() is None


def test_有圖示檔就回傳位置(tmp_path, monkeypatch):
    import app_paths
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "icon.ico").write_bytes(b"ico")
    monkeypatch.setattr(app_paths, "程式資料夾", lambda: str(tmp_path))
    assert app_paths.圖示檔() == str(tmp_path / "assets" / "icon.ico")


def test_打包設定有留圖示位置():
    內容 = (專案 / "LiveSummary.spec").read_text(encoding="utf-8")
    assert "app_paths.圖示相對位置" in 內容 and "有圖示 = os.path.isfile(圖示)" in 內容
    assert "icon=圖示 if 有圖示 else None" in 內容 and "資料 += [(圖示, \"assets\")]" in 內容
    app內容 = (專案 / "app.py").read_text(encoding="utf-8")
    assert "app_paths.圖示檔()" in app內容 and "setWindowIcon" in app內容
    assert (專案 / "assets" / "README.txt").exists()
