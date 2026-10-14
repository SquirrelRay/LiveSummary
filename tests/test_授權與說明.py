"""打包第 5 步之二：系統匣圖示說明、第三方授權清單、使用說明.txt。
不開真的 Windows 設定（os.startfile 換成假的）、不連網、不需要 ffmpeg（授權清單只讀 vendor 裡的授權文字檔，沒有就跳過）。"""
import importlib.util
import os
import sys
import zipfile
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication

import app_paths
import first_run
import tray_tip

專案 = Path(__file__).resolve().parent.parent
使用說明 = 專案 / "docs" / "使用說明.txt"


def _載入(名稱, 路徑):
    sys.path.insert(0, str(專案 / "scripts"))
    try:
        spec = importlib.util.spec_from_file_location(名稱, 路徑)
        模組 = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(模組)
        return 模組
    finally:
        sys.path.remove(str(專案 / "scripts"))


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def 假開啟(monkeypatch):
    開過 = []
    monkeypatch.setattr(os, "startfile", lambda 目標: 開過.append(目標), raising=False)
    return 開過


# ---------- 系統匣圖示說明 ----------
def test_按鈕打開Windows工作列設定(qapp, 假開啟):
    卡 = tray_tip.系統匣說明卡()
    結果 = []
    卡.開了.connect(結果.append)
    卡.按鈕.click()
    assert 假開啟 == ["ms-settings:taskbar"] and 結果 == [True]
    assert 卡.按鈕.text() == "打開工作列設定"


def test_打不開時寫出手動路徑(qapp, monkeypatch):
    def 壞(目標):
        raise OSError("不行")
    monkeypatch.setattr(os, "startfile", 壞, raising=False)
    卡 = tray_tip.系統匣說明卡()
    assert 卡.打開() is False
    assert "設定 → 個人化 → 工作列" in 卡.說明字.text()


def test_說明文字簡短():
    assert len(tray_tip.說明.splitlines()) <= 2 and "「^」" in tray_tip.說明 and "直播摘要" in tray_tip.說明


def test_首次引導最後一頁有系統匣說明卡(qapp, 假開啟):
    import onboarding

    class 假台:
        面板 = None
    引導 = onboarding.首次引導(假台(), 檢查=[])
    最後 = 引導.頁們[-1]
    assert 引導.系統匣卡.isAncestorOf(最後.操作區) or 最後.操作區.isAncestorOf(引導.系統匣卡)
    引導.系統匣卡.按鈕.click()
    assert 假開啟 == ["ms-settings:taskbar"]
    引導.close()


def test_設定框有系統匣說明與關於(qapp, 假開啟):
    import settings_page

    class 假主:
        def 執行中(self):
            return False
    頁 = settings_page.設定頁(假主())
    頁.系統匣卡.按鈕.click()
    assert 假開啟 == ["ms-settings:taskbar"]
    assert 頁.版本標.text() == "直播摘要 v1.0.0"
    assert "GPLv3" in 頁.授權字.text() and "FFmpeg（LGPL v3）" in 頁.授權字.text() and "licenses" in 頁.授權字.text()
    assert not 頁.授權鈕.isEnabled()                      # 開發環境沒有授權清單資料夾


def test_打包版授權清單資料夾在exe旁(tmp_path, monkeypatch):
    (tmp_path / "licenses").mkdir()
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "LiveSummary.exe"))
    assert app_paths.授權清單資料夾() == str(tmp_path / "licenses")
    (tmp_path / "licenses").rmdir()
    assert app_paths.授權清單資料夾() is None


# ---------- 第三方授權清單 ----------
@pytest.fixture
def 假打包(tmp_path):
    """假的 dist\\LiveSummary 與 build\\LiveSummary：_internal 放幾個對得到套件的檔、一個對不到的；PYZ 紀錄指到一個純 Python 模組。"""
    if not (專案 / "vendor" / "ffmpeg" / "LICENSE.txt").exists():
        pytest.skip("沒有 vendor\\ffmpeg（先跑 scripts\\下載ffmpeg.py）")
    import certifi
    import yaml
    site = Path(certifi.__file__).parent.parent
    輸出 = tmp_path / "dist" / "LiveSummary"
    內部 = 輸出 / "_internal"
    (內部 / "certifi").mkdir(parents=True)
    (內部 / "certifi" / "cacert.pem").write_text("x")
    (內部 / "ffmpeg" / "bin").mkdir(parents=True)
    (內部 / "ffmpeg" / "bin" / "ffmpeg.exe").write_text("x")
    (內部 / "來路不明.dll").write_text("x")
    建置 = tmp_path / "build"
    建置.mkdir()
    yaml路徑 = str(Path(yaml.__file__)).replace("\\", "\\\\")
    (建置 / "PYZ-00.toc").write_text(f"[('yaml', '{yaml路徑}', 'PYMODULE')]", encoding="utf-8")
    assert (site / "certifi" / "cacert.pem").exists()
    return 輸出, 建置


def test_授權清單涵蓋帶進去的套件與固定項目(假打包):
    licenses = _載入("licenses_測試", 專案 / "scripts" / "licenses.py")
    輸出, 建置 = 假打包
    總表, 項目們, 對不到 = licenses.寫出(str(輸出), str(建置))
    名們 = {x["名稱"] for x in 項目們}
    assert {"Python", "FFmpeg", "certifi", "PyYAML"} <= 名們
    assert "PyInstaller（開機程式與執行期模組）" in 名們
    assert "pytest" not in 名們 and "ruff" not in 名們             # 沒帶進去的開發工具不列
    assert 對不到 == ["來路不明.dll"]
    內容 = Path(總表).read_text(encoding="utf-8-sig")
    assert "GPLv3" in 內容 and "MPL-2.0" in 內容 and "LGPL-3.0" in 內容 and "來路不明.dll" in 內容
    for 項目 in 項目們:                                           # 每一項都有自己的全文檔
        檔 = Path(總表).parent / licenses._檔名(項目)
        assert 檔.exists() and f"授權：{項目['授權']}" in 檔.read_text(encoding="utf-8")
    certifi檔 = (Path(總表).parent / licenses._檔名(next(x for x in 項目們 if x["名稱"] == "certifi"))).read_text(encoding="utf-8")
    assert "Mozilla Public License" in certifi檔                  # 授權全文原樣收進來


def test_打包驗收要檢查授權清單與使用說明():
    打包 = _載入("build_exe_測試2", 專案 / "scripts" / "build_exe.py")
    assert any("第三方授權清單.txt" in f for f in 打包.必要檔案)
    assert Path(打包.使用說明) == 使用說明 and 使用說明.exists()


def test_使用說明放在壓縮檔最上層(tmp_path, monkeypatch):
    打包 = _載入("build_exe_測試3", 專案 / "scripts" / "build_exe.py")
    輸出根 = tmp_path / "dist"
    輸出 = 輸出根 / "LiveSummary"
    (輸出 / "licenses").mkdir(parents=True)
    (輸出 / "LiveSummary.exe").write_text("x")
    (輸出 / "licenses" / "第三方授權清單.txt").write_text("x", encoding="utf-8")
    monkeypatch.setattr(打包, "輸出根", str(輸出根))
    monkeypatch.setattr(打包, "輸出", str(輸出))
    monkeypatch.setattr(打包, "壓縮檔", str(輸出根 / "LiveSummary-v1.0.0.zip"))
    打包.壓縮()
    with zipfile.ZipFile(輸出根 / "LiveSummary-v1.0.0.zip") as z:
        名們 = z.namelist()
        文字 = z.read("使用說明.txt").decode("utf-8")
    assert "使用說明.txt" in 名們 and "LiveSummary/LiveSummary.exe" in 名們
    assert 文字.startswith("﻿") and "\r\n" in 文字 and "\r\r" not in 文字


# ---------- 使用說明.txt ----------
def test_使用說明涵蓋必要內容():
    文字 = 使用說明.read_text(encoding="utf-8")
    for 要有 in ("全部解壓縮", "LiveSummary.exe", "API 金鑰", "platform.claude.com",
               "Windows 10 或 Windows 11（64 位元）", "NVIDIA", "不是必要",
               "Windows 已保護您的電腦", "其他資訊", "仍要執行", "沒有付費數位簽章",
               "防毒", "「^」", "%LOCALAPPDATA%\\LiveSummary", "認證管理員", "「直播摘要」", "@直播摘要",
               "「文件」資料夾裡的「直播摘要」資料夾", "實際金額以服務的帳單為準"):
        assert 要有 in 文字, 要有


def test_使用說明的模型大小和程式一致():
    文字 = 使用說明.read_text(encoding="utf-8")
    assert f"約 {first_run.大小字(first_run.模型大小['large-v3-turbo'])}" in 文字           # 1.6 GB
    小 = first_run.模型大小["small"] / 1e6
    assert 480 <= 小 <= 500 and "約 490 MB" in 文字                                         # 486 MB 寫成「約 490 MB」
