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


_套件索引快取 = []      # .venv 裡每個檔案 → 所屬套件：整場測試不會變，真的掃一次（約 2.5 萬個檔、1 秒）就好，各測試共用（只讀不改）


def _載入(名稱, 路徑):
    sys.path.insert(0, str(專案 / "scripts"))
    try:
        spec = importlib.util.spec_from_file_location(名稱, 路徑)
        模組 = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(模組)
        if hasattr(模組, "_套件索引"):
            真的 = 模組._套件索引

            def 共用索引():
                if not _套件索引快取:
                    _套件索引快取.append(真的())
                return _套件索引快取[0]
            模組._套件索引 = 共用索引
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
    總表, 項目們, 對不到, 警告們 = licenses.寫出(str(輸出), str(建置))
    名們 = {x["名稱"] for x in 項目們}
    assert any("來路不明.dll" in x for x in 警告們)
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


def test_使用說明指向程式裡的使用說明視窗():
    import onboarding
    文字 = 使用說明.read_text(encoding="utf-8")
    assert "「直播摘要 使用說明」視窗（不是這份文字檔）" in 文字
    assert 'setWindowTitle("直播摘要 使用說明")' in (專案 / "onboarding.py").read_text(encoding="utf-8")   # 和程式裡的視窗標題一致
    assert f"第 1 頁「{onboarding.頁們[0]['標題']}」" in 文字
    assert "使用說明第 1 頁" not in 文字


def test_使用說明的費用註明以發布時價格估算_版本從version_py來():
    import version
    原稿 = 使用說明.read_text(encoding="utf-8")
    assert "{版本} 發布時各服務的價格估算" in 原稿 and version.版本 not in 原稿      # 原稿不寫死版本號
    打包 = _載入("build_exe_測試4", 專案 / "scripts" / "build_exe.py")
    文字 = 打包._使用說明內容()
    assert f"以 {version.版本字()} 發布時各服務的價格估算" in 文字 and "價格可能調整" in 文字
    assert "以程式內顯示的估算和服務的帳單為準" in 文字 and "{" not in 文字


# ---------- 授權收尾：補充全文、原始碼取得方式、OpenSSL 來源 ----------
def test_授權清單_補充全文與固定項目與原始碼取得方式(假打包):
    import shutil
    from importlib import metadata

    import certifi
    licenses = _載入("licenses_測試2", 專案 / "scripts" / "licenses.py")
    下載 = _載入("下載ffmpeg_測試", 專案 / "scripts" / "下載ffmpeg.py")
    輸出, 建置 = 假打包
    內部 = 輸出 / "_internal"
    site = Path(certifi.__file__).parent.parent
    (內部 / "ctranslate2").mkdir()
    shutil.copyfile(site / "ctranslate2" / "libiomp5md.dll", 內部 / "ctranslate2" / "libiomp5md.dll")   # 真的那份：要對到 intel-openmp
    (內部 / "msvcp140.dll").write_bytes(b"x")
    總表, 項目們, 對不到, 警告們 = licenses.寫出(str(輸出), str(建置))
    項 = {x["名稱"]: x for x in 項目們}
    assert 對不到 == ["來路不明.dll"]                                  # msvcp140.dll 歸到 VC++ 執行階段
    openmp = 項["Intel OpenMP 執行期"]
    assert openmp["版本"] == "2025.3.0" and any("Intel End User License Agreement" in t for _, t in openmp["全文們"])
    assert r"_internal\msvcp140.dll" in 項["Microsoft Visual C++ 執行階段"]["全文們"][0][1]
    assert any("MIT License" in t for _, t in 項["ctranslate2"]["全文們"])         # 上游 v4.8.2 的 LICENSE
    assert not any("沒有授權全文" in x for x in 警告們)
    內容 = Path(總表).read_text(encoding="utf-8-sig")
    assert "原始碼取得方式" in 內容 and f"https://github.com/FFmpeg/FFmpeg/tree/{下載.原始碼提交}" in 內容
    assert 下載.原始碼檔名 in 內容 and f"certifi-{metadata.version('certifi')}.tar.gz" in 內容


def test_授權清單_Intel_OpenMP對不到版本就警告(假打包):
    licenses = _載入("licenses_測試3", 專案 / "scripts" / "licenses.py")
    輸出, 建置 = 假打包
    (輸出 / "_internal" / "ctranslate2").mkdir()
    (輸出 / "_internal" / "ctranslate2" / "libiomp5md.dll").write_bytes(b"not the real one")
    _, 項目們, _, 警告們 = licenses.寫出(str(輸出), str(建置))
    assert next(x for x in 項目們 if x["名稱"] == "Intel OpenMP 執行期")["全文們"] == []
    assert any(x.startswith("沒有授權全文") and "Intel OpenMP" in x for x in 警告們)


def test_授權清單_隨附函式庫沒提到就警告(tmp_path):
    licenses = _載入("licenses_測試4", 專案 / "scripts" / "licenses.py")
    雜 = "0123456789abcdef" * 2
    for 資料夾, 檔 in (("av.libs", f"libx264-165-{雜}.dll"), ("av.libs", f"msvcp140-{雜}.dll"), ("av.libs", f"avcodec-62-{雜}.dll"),
                    ("numpy.libs", f"libscipy_openblas64_-{雜}.dll")):
        (tmp_path / "_internal" / 資料夾).mkdir(parents=True, exist_ok=True)
        (tmp_path / "_internal" / 資料夾 / 檔).write_bytes(b"x")
    項目們 = [{"名稱": "av", "全文們": [("LICENSE.txt", "BSD license; uses FFmpeg's avcodec")]},
            {"名稱": "numpy", "全文們": [("LICENSE.txt", "bundles OpenBLAS (BSD)")]}]
    assert licenses.隨附庫沒提到(str(tmp_path), 項目們) == {"av.libs": ["libx264-165"]}     # msvcp140 另有 VC++ 一項


def test_OpenSSL必須是Python自己的(tmp_path):
    import shutil
    licenses = _載入("licenses_測試5", 專案 / "scripts" / "licenses.py")
    內部 = tmp_path / "_internal"
    內部.mkdir()
    問題, _ = licenses.OpenSSL來源問題(str(tmp_path))
    assert any("沒有 OpenSSL" in x for x in 問題)
    for 名 in ("libcrypto-3.dll", "libssl-3.dll"):
        shutil.copyfile(Path(sys.base_prefix) / "DLLs" / 名, 內部 / 名)
    assert licenses.OpenSSL來源問題(str(tmp_path)) == ([], ["libcrypto-3.dll", "libssl-3.dll"])
    (內部 / "PySide6").mkdir()
    (內部 / "PySide6" / "libssl-3-x64.dll").write_bytes(b"git")            # 像 Git 的 mingw64\bin 那份
    (內部 / "libssl-3.dll").write_bytes(b"changed")
    問題, _ = licenses.OpenSSL來源問題(str(tmp_path))
    assert len(問題) == 2 and any("libssl-3-x64.dll" in x and "不是 Python 自己的" in x for x in 問題)
    assert any("libssl-3.dll" in x and "內容不同" in x for x in 問題)


def test_打包不帶QtNetwork與cudnn_PATH只留系統與Python():
    spec = (專案 / "LiveSummary.spec").read_text(encoding="utf-8")
    assert '"PySide6.QtNetwork",' in spec and '!= "cudnn64_9.dll"' in spec
    打包 = _載入("build_exe_測試5", 專案 / "scripts" / "build_exe.py")
    assert {"cudnn64_9.dll", "libssl-3-x64.dll", "libcrypto-3-x64.dll", "Qt6Network.dll", "qtuiotouchplugin.dll"} <= set(打包.不該有)
    assert "不帶的Qt檔 = {\"qtuiotouchplugin.dll\", \"qt6network.dll\"}" in spec
    windows = os.path.normcase(os.environ.get("SystemRoot", r"C:\Windows"))
    for 路徑 in 打包.乾淨PATH().split(os.pathsep):
        正規 = os.path.normcase(路徑)
        assert 正規.startswith((windows, os.path.normcase(sys.base_prefix), os.path.normcase(os.path.dirname(sys.executable)))), 路徑
        assert "git" not in 正規


def test_third_party_licenses和venv版本一致():
    from importlib import metadata
    licenses = _載入("licenses_測試6", 專案 / "scripts" / "licenses.py")
    for 套件, 前綴們 in licenses.上游全文.items():
        for 前綴 in 前綴們:
            資料夾 = Path(licenses.補充根) / f"{前綴}-{metadata.version(套件)}"
            assert (資料夾 / "來源.txt").exists() and licenses.補充全文(資料夾.name), 資料夾        # 升級套件後要重跑 scripts\取得授權全文.py
    for 檔 in licenses.附加聲明.values():
        assert (Path(licenses.補充根) / 檔).exists()
    assert (Path(licenses.補充根) / "vc-runtime" / "說明.txt").exists()


def test_取得授權全文_Qt只收打包會帶到的模組():
    m = _載入("取得授權全文_測試", 專案 / "scripts" / "取得授權全文.py")
    assert m.Qt要收("src/3rdparty/harfbuzz-ng/qt_attribution.json", {"QDocModule": "qtgui"})
    assert m.Qt要收("src/3rdparty/libtiff/qt_attribution.json", {"QDocModule": "qtimageformats"})
    assert not m.Qt要收("src/3rdparty/libpsl/qt_attribution.json", {"QDocModule": "qtnetwork"})       # QtNetwork 沒帶
    assert not m.Qt要收("src/3rdparty/wayland/protocols/xdg-shell/qt_attribution.json", {"QDocModule": "qtgui"})
    assert not m.Qt要收("src/testlib/3rdparty/catch2/qt_attribution.json", {"QDocModule": "qttestlib"})


def test_本程式的圖示不算來源待確認(假打包):
    licenses = _載入("licenses_測試7", 專案 / "scripts" / "licenses.py")
    輸出, 建置 = 假打包
    (輸出 / "_internal" / "assets").mkdir()
    (輸出 / "_internal" / "assets" / "icon.ico").write_bytes(b"x")
    _, _, 對不到, _ = licenses.寫出(str(輸出), str(建置))
    assert 對不到 == ["來路不明.dll"]


# ---------- 第三階段準備：強制 CPU 測試 bat、測試清單 ----------
def test_強制CPU的bat設環境變數並啟動程式():
    bat = 專案 / "scripts" / "強制CPU測試.bat"
    文字 = bat.read_bytes().decode("utf-8")
    assert "\r\n" in 文字 and "set CUDA_VISIBLE_DEVICES=-1" in 文字 and "LiveSummary.exe" in 文字
    打包 = _載入("build_exe_測試6", 專案 / "scripts" / "build_exe.py")
    assert 打包.測試bat == "強制CPU測試.bat"


@pytest.mark.slow
def test_CUDA_VISIBLE_DEVICES為負一時判斷成沒有顯示卡_改用small():
    """另開 Python 設環境變數：顯示卡數 0 → 顯示卡可用 False → 要用的模型是 small（和 bat 的做法一樣）。"""
    import external
    程式 = ("import first_run; print(first_run.顯示卡數(), first_run.顯示卡可用(), first_run.要用的模型(first_run.顯示卡可用()))")
    r = external.執行([sys.executable, "-X", "utf8", "-c", 程式], capture_output=True, text=True, encoding="utf-8", timeout=120,
                    env={**os.environ, "CUDA_VISIBLE_DEVICES": "-1"}, cwd=str(專案))
    assert r.returncode == 0, r.stderr
    assert r.stdout.split()[-3:] == ["0", "False", "small"]


def test_測試清單涵蓋必要項目():
    文字 = (專案 / "docs" / "乾淨電腦測試清單.md").read_text(encoding="utf-8")
    for 要有 in ("我沒有這個人的登入資訊", "新增沒有 Microsoft 帳戶的使用者", "測試小明", "強制CPU測試.bat", "裝置=cpu", "裝置=cuda",
               "當機紀錄.txt", "認證管理員", "刪除帳戶和資料", "OpenCC", "VC++", "中文帳號名稱", "模型下載流程", "Twitch", "YouTube", "☐"):
        assert 要有 in 文字, 要有
