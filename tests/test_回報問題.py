"""回報問題（設定框「關於」→「🐞 回報問題」）：白名單診斷文字、顯示卡資訊（nvidia-smi 一律用替身）、
上次實際用的轉錄裝置與模型、最近一次錯誤（只取時間與型別）、預覽視窗（取消不碰剪貼簿也不開網頁）、使用說明。
全部用假資料：不連網、不跑真的 nvidia-smi、不問真的顯示卡函式庫。"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
import test_介面冒煙 as 冒煙
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGridLayout

import app_paths
import crash_log
import diagnostics
import system_info
import version

專案 = Path(__file__).resolve().parent.parent
原本的顯示卡資訊 = diagnostics.顯示卡資訊      # autouse 會換掉；測試它本身時用這份（參數一律給替身）
qapp, 環境 = 冒煙.qapp, 冒煙.環境          # fixture：和冒煙測試共用

假網址 = "https://secret.example.internal/v1"
假環境變數 = "MY_SECRET_KEY_ENV"
假金鑰 = "sk-ant-api03-AbCdEfGhIjKlMnOpQrStUvWxYz0123456789-_AbCdEf"


class 假結果:
    def __init__(self, returncode=0, stdout=""):
        self.returncode, self.stdout, self.stderr = returncode, stdout, ""


@pytest.fixture(autouse=True)
def _不碰真的顯示卡(monkeypatch):
    """保險：任何測試都不准跑真的 nvidia-smi、問真的顯示卡函式庫。"""
    monkeypatch.setattr(diagnostics, "顯示卡資訊", lambda: "假顯示卡（8 GB），驅動 1.0")
    monkeypatch.setattr(diagnostics, "CUDA裝置數", lambda: "1")


@pytest.fixture
def 乾淨(monkeypatch):
    """沒有上次模型紀錄、沒有當機紀錄。"""
    for 檔 in (app_paths.上次轉錄模型檔(), app_paths.當機紀錄檔(),
              app_paths.當機紀錄檔().replace("當機紀錄.txt", "當機紀錄.舊.txt")):
        if os.path.exists(檔):
            os.remove(檔)


# ---------- 顯示卡 ----------
def test_解析顯示卡_名稱_VRAM_驅動():
    assert diagnostics.解析顯示卡("NVIDIA GeForce RTX 4060, 8188 MiB, 560.94\n") == "NVIDIA GeForce RTX 4060（8 GB），驅動 560.94"


def test_解析顯示卡_多張卡用分號_小記憶體用MiB():
    字 = diagnostics.解析顯示卡("NVIDIA A, 24564 MiB, 560.94\r\nNVIDIA B, 512 MiB, 560.94\n")
    assert 字 == "NVIDIA A（24 GB），驅動 560.94；NVIDIA B（512 MiB），驅動 560.94"


@pytest.mark.parametrize("輸出", ["", "亂七八糟", "a, b", "NVIDIA-SMI has failed"])
def test_解析顯示卡_讀不懂回傳None(輸出):
    assert diagnostics.解析顯示卡(輸出) is None


def test_解析顯示卡_欄位怪就各自寫無法取得():
    assert diagnostics.解析顯示卡("NVIDIA X, [N/A], C:\\Users\\a") == "NVIDIA X（無法取得），驅動 無法取得"


def test_顯示卡資訊_經external執行_有逾時_指令固定():
    叫過 = []

    def 假執行(指令, **選項):
        叫過.append((指令, 選項))
        return 假結果(0, "NVIDIA GeForce RTX 4060, 8188 MiB, 560.94\n")

    函式 = 原本的顯示卡資訊
    assert 函式(執行=假執行, 找程式=lambda 名: "假\\nvidia-smi.exe") == "NVIDIA GeForce RTX 4060（8 GB），驅動 560.94"
    指令, 選項 = 叫過[0]
    assert 指令[1:] == ["--query-gpu=name,memory.total,driver_version", "--format=csv,noheader"]
    assert 選項["timeout"] == pytest.approx(3.0) and 選項["capture_output"] is True


@pytest.mark.parametrize("情況", ["沒有nvidia-smi", "逾時", "結束碼非0", "OSError", "輸出讀不懂"])
def test_顯示卡資訊_失敗都是無法取得(情況):
    def 假執行(指令, **選項):
        if 情況 == "逾時":
            raise subprocess.TimeoutExpired(指令, 3)
        if 情況 == "OSError":
            raise OSError("不能執行")
        if 情況 == "結束碼非0":
            return 假結果(9, "")
        return 假結果(0, "NVIDIA-SMI has failed because it couldn't communicate with the NVIDIA driver")

    函式 = 原本的顯示卡資訊
    找 = (lambda 名: None) if 情況 == "沒有nvidia-smi" else (lambda 名: "nvidia-smi")
    assert 函式(執行=假執行, 找程式=找) == "無法取得"


# ---------- 上次實際用的轉錄裝置與模型 ----------
def test_記錄與讀取上次轉錄模型(乾淨):
    assert diagnostics.讀上次轉錄模型() is None
    diagnostics.記錄轉錄模型("cuda", "large-v3-turbo")
    資料 = diagnostics.讀上次轉錄模型()
    assert 資料["裝置"] == "cuda" and 資料["模型"] == "large-v3-turbo" and 資料["時間"]
    內容 = Path(app_paths.上次轉錄模型檔()).read_text(encoding="utf-8")
    assert set(json.loads(內容)) == {"裝置", "模型", "時間"} and ":\\" not in 內容


def test_上次轉錄模型檔放在程式資料夾():
    assert app_paths.上次轉錄模型檔() == os.path.join(app_paths.資料資料夾(), "上次轉錄模型.json")


def test_記錄轉錄模型寫不進去也不丟例外(monkeypatch, tmp_path):
    擋住 = tmp_path / "是檔案"
    擋住.write_text("x", encoding="utf-8")
    monkeypatch.setattr(app_paths, "上次轉錄模型檔", lambda: str(擋住 / "上次轉錄模型.json"))
    diagnostics.記錄轉錄模型("cpu", "small")


def test_讀上次轉錄模型_內容怪不出錯(乾淨):
    Path(app_paths.上次轉錄模型檔()).parent.mkdir(parents=True, exist_ok=True)
    Path(app_paths.上次轉錄模型檔()).write_text("[1, 2]", encoding="utf-8")
    assert diagnostics.讀上次轉錄模型() is None
    Path(app_paths.上次轉錄模型檔()).write_text(json.dumps({"裝置": "C:\\Users\\a", "模型": "x" * 200, "時間": "C:\\x"}), encoding="utf-8")
    資料 = diagnostics.讀上次轉錄模型()
    assert 資料["裝置"] == "其他" and len(資料["模型"]) == 61 and 資料["時間"] == ""


def test_直播流程載入模型後記下實際裝置與模型(流程, monkeypatch, 乾淨):
    import live_capture as lc
    import transcribe

    class 假內部:
        device = "cuda"

    class 假模型:
        model = 假內部()

    monkeypatch.setattr(lc, "載入模型", lambda 語言: 假模型())
    流程([b""], 語言="ja")
    assert diagnostics.讀上次轉錄模型()["裝置"] == "cuda"
    assert diagnostics.讀上次轉錄模型()["模型"] == transcribe.GPU_MODEL
    假內部.device = "cpu"
    流程([b""], 語言="ja")
    資料 = diagnostics.讀上次轉錄模型()
    assert 資料["裝置"] == "cpu" and 資料["模型"] == transcribe.CPU_MODEL


# ---------- 最近一次錯誤 ----------
def _例外資訊(例外):
    try:
        raise 例外
    except Exception:      # noqa: BLE001
        return sys.exc_info()


def test_最近錯誤只取最後一筆的時間與型別_不含訊息與traceback(乾淨, monkeypatch):
    monkeypatch.setattr(crash_log, "_金鑰們", set())
    crash_log.寫紀錄(_例外資訊(RuntimeError("第一筆")))
    crash_log.寫紀錄(_例外資訊(ValueError(f"網址 https://www.twitch.tv/someone 路徑 C:\\Users\\小明\\x {假金鑰}")))
    結果 = diagnostics.最近錯誤()
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} ValueError", 結果), 結果


def test_最近錯誤_串連的例外取最後丟出的型別():
    文字 = ("==== 2026-10-15 16:16:57 | 版本 1.0.0 | 主執行緒 ====\nPython 3.13 | Windows | 打包版\n"
          "Traceback (most recent call last):\n  File \"a.py\", line 1, in <module>\nKeyError: 'x'\n\n"
          "During handling of the above exception, another exception occurred:\n\n"
          "Traceback (most recent call last):\n  File \"b.py\", line 2, in f\n"
          "requests.exceptions.ConnectionError: 連不上 https://x\nConnection: 第二行也像型別\n")
    assert diagnostics.解析最近錯誤(文字) == "2026-10-15 16:16:57 requests.exceptions.ConnectionError"


def test_最近錯誤_Qt嚴重錯誤與其他文字():
    頭 = "==== 2026-10-15 16:16:57 | 版本 1.0.0 | 主執行緒 ====\nPython 3.13 | Windows | 打包版\n"
    assert diagnostics.解析最近錯誤(頭 + "Qt 嚴重錯誤（程式即將結束）：C:\\Users\\a\n") == "2026-10-15 16:16:57 Qt 嚴重錯誤"
    assert diagnostics.解析最近錯誤(頭 + "隨便一段 C:\\Users\\a\n") == "2026-10-15 16:16:57 其他錯誤"


def test_最近錯誤_原生層當機用檔案時間():
    文字 = ("==== 2026-10-15 16:16:57 | 版本 1.0.0 | 主執行緒 ====\nValueError: x\n"
          "Windows fatal exception: access violation\n\nThread 0x1 (most recent call first):\n  File \"C:\\Users\\a\\x.py\"\n")
    結果 = diagnostics.解析最近錯誤(文字, 修改時間=0)
    assert 結果.endswith(" 原生層當機（access violation）") and "Users" not in 結果


def test_最近錯誤_沒有紀錄(乾淨):
    assert diagnostics.解析最近錯誤("") is None
    assert diagnostics.最近錯誤() == "沒有紀錄"
    Path(app_paths.當機紀錄檔()).parent.mkdir(parents=True, exist_ok=True)
    Path(app_paths.當機紀錄檔()).write_text("", encoding="utf-8")      # faulthandler 先建出的空檔
    assert diagnostics.最近錯誤() == "沒有紀錄"


def test_最近錯誤_目前的檔沒有就看舊檔(乾淨):
    舊 = app_paths.當機紀錄檔().replace("當機紀錄.txt", "當機紀錄.舊.txt")
    Path(舊).parent.mkdir(parents=True, exist_ok=True)
    Path(舊).write_text("==== 2026-01-02 03:04:05 | 版本 1.0.0 | 主執行緒 ====\nx\nTraceback (most recent call last):\n"
                       "  File \"x\"\nOSError: y\n", encoding="utf-8")
    assert diagnostics.最近錯誤() == "2026-01-02 03:04:05 OSError"


# ---------- 整段文字：白名單 ----------
def 危險設定():
    import config
    設定 = config.出廠預設()
    設定.update(provider="openai_compatible", base_url=假網址, api_key_env=假環境變數,
              model="我的模型 " + 假金鑰 + " " + "很長" * 50, whisper_model="large-v3-turbo")
    設定["overlay"] = {"font": "秘密字型"}
    return 設定


def test_診斷文字不含金鑰_網址_環境變數名_路徑_使用者名稱(乾淨):
    diagnostics.記錄轉錄模型("cpu", "small")
    文字 = diagnostics.組文字(diagnostics.收集(危險設定()))
    for 不准 in (假網址, "secret.example", 假環境變數, 假金鑰, "sk-ant", "秘密字型", app_paths.資料資料夾(),
               os.path.expanduser("~"), os.path.basename(os.path.expanduser("~")), "http", ":\\"):
        assert 不准 not in 文字, 不准
    assert "摘要模型：我的模型 *****" in 文字


def test_自填模型截斷到60字():
    值 = diagnostics.收集(危險設定())["摘要模型"]
    assert len(值) == 61 and 值.endswith("…")
    assert diagnostics.截斷("a\nb\tc") == "a b c"


def test_診斷文字的行與順序(乾淨):
    文字 = diagnostics.組文字(diagnostics.收集())
    行們 = 文字.splitlines()
    assert 行們[0] == "【直播摘要 診斷資訊】"
    assert [行.split("：")[0] for 行 in 行們[1:]] == list(diagnostics.順序)
    assert f"程式版本：{version.版本字()}" in 文字
    assert f"Windows：{system_info.平台字()}" in 文字 and f"Python：{system_info.Python版本()}" in 文字
    assert "顯示卡：假顯示卡（8 GB），驅動 1.0" in 文字 and "可用 CUDA 裝置數：1" in 文字
    assert "運算裝置（上次載入模型）：尚未執行過" in 文字
    assert "轉錄模型（設定／實際）：large-v3-turbo／尚未執行過" in 文字
    assert "摘要服務：" in 文字 and "（anthropic）" in 文字
    assert "最近一次錯誤：沒有紀錄" in 文字
    assert re.search(r"功能：聊天室=開 分鐘摘要=開 .*上網查證=關", 文字)
    assert "存檔：摘要=開 直播稿=關" in 文字


def test_有上次模型紀錄時顯示實際裝置與模型(乾淨):
    diagnostics.記錄轉錄模型("cpu", "small")
    資料 = diagnostics.收集()
    assert 資料["運算裝置（上次載入模型）"].startswith("cpu（")
    assert 資料["轉錄模型（設定／實際）"].endswith("／small")


def test_組文字只放白名單的項目_缺的寫無法取得():
    文字 = diagnostics.組文字({"程式版本": "v9", "base_url": 假網址, "多的": "不准出現", "顯示卡": ""})
    assert 假網址 not in 文字 and "不准出現" not in 文字
    assert "程式版本：v9" in 文字 and "顯示卡：無法取得" in 文字 and "最近一次錯誤：無法取得" in 文字


def test_單項失敗只寫無法取得_整段照樣產生(monkeypatch, 乾淨):
    def 壞():
        raise RuntimeError("壞了")

    for 模組, 名 in ((system_info, "平台字"), (diagnostics, "顯示卡資訊"), (diagnostics, "最近錯誤"),
                   (diagnostics, "讀上次轉錄模型"), (diagnostics, "設定檔狀態"), (diagnostics, "外部程式狀態")):
        monkeypatch.setattr(模組, 名, 壞)
    文字 = diagnostics.產生()
    assert "Windows：無法取得" in 文字 and "顯示卡：無法取得" in 文字 and "最近一次錯誤：無法取得" in 文字
    assert "設定檔：無法取得" in 文字 and "外部程式：無法取得" in 文字
    assert "運算裝置（上次載入模型）：尚未執行過" in 文字 and f"程式版本：{version.版本字()}" in 文字


def test_設定讀不到時開關寫無法取得(monkeypatch):
    import config
    monkeypatch.setattr(config, "目前設定", lambda: (_ for _ in ()).throw(RuntimeError("壞")))
    資料 = diagnostics.收集()
    assert 資料["功能"].startswith("聊天室=無法取得") and 資料["摘要模型"] == "無法取得"


def test_設定檔狀態(monkeypatch, tmp_path):
    import config
    檔 = tmp_path / "config.json"
    monkeypatch.setattr(config, "設定檔路徑", str(檔))
    assert diagnostics.設定檔狀態() == "不存在（使用內建預設）"
    檔.write_text("{壞掉", encoding="utf-8")
    assert diagnostics.設定檔狀態() == "讀不懂（已改用內建預設）"
    檔.write_text(json.dumps({"chat": "不是布林", "我自己加的欄位": 1}), encoding="utf-8")
    assert diagnostics.設定檔狀態() == "存在，有 2 項有問題已改用預設"
    檔.write_text(json.dumps({"chat": True}), encoding="utf-8")
    assert diagnostics.設定檔狀態() == "存在且可讀"


def test_外部程式狀態不含路徑():
    字 = diagnostics.外部程式狀態()
    assert 字.startswith("ffmpeg：") and "helper.exe：開發環境不需要" in 字 and ":\\" not in 字


# ---------- crash_log 改用共用的系統版本函式（行為不變）----------
def test_當機紀錄的環境行用共用函式(monkeypatch):
    monkeypatch.setattr(system_info, "平台字", lambda: "假平台-1")
    monkeypatch.setattr(system_info, "Python版本", lambda: "9.9.9")
    assert crash_log._環境() == "Python 9.9.9 | 假平台-1 | 開發環境"


def test_共用函式和platform一致():
    import platform
    assert system_info.平台字() == platform.platform()
    assert system_info.Python版本() == platform.python_version()


# ---------- 預覽視窗 ----------
def _視窗(qapp, monkeypatch, 文字="【假的診斷】\n程式版本：v0"):
    import report_dialog
    開過 = []
    monkeypatch.setattr(report_dialog.QDesktopServices, "openUrl", lambda u: 開過.append(u.toString()) or True)
    qapp.clipboard().setText("原本的剪貼簿")
    框 = report_dialog.回報預覽框(產生=lambda: 文字, 背景=False)
    return 框, 開過


def test_預覽視窗顯示完整內容與說明(qapp, monkeypatch):
    import report_dialog
    框, _ = _視窗(qapp, monkeypatch)
    assert 框.說明.text() == "以下內容會複製到剪貼簿，不含 API 金鑰、網址或直播內容，你可以先看過"
    assert 框.內容框.isReadOnly() and 框.內容框.toPlainText() == "【假的診斷】\n程式版本：v0"
    assert 框.確認鈕.text() == "複製並開啟回報表單" and 框.取消鈕.text() == "取消" and 框.確認鈕.isEnabled()
    assert report_dialog.說明字 == 框.說明.text()


def test_取消不碰剪貼簿也不開網頁(qapp, monkeypatch):
    框, 開過 = _視窗(qapp, monkeypatch)
    框.show()
    框.取消鈕.click()
    assert qapp.clipboard().text() == "原本的剪貼簿" and 開過 == [] and not 框.isVisible()


def test_直接關視窗也不碰剪貼簿(qapp, monkeypatch):
    框, 開過 = _視窗(qapp, monkeypatch)
    框.show()
    框.close()
    assert qapp.clipboard().text() == "原本的剪貼簿" and 開過 == []


def test_確認才複製並開表單(qapp, monkeypatch):
    框, 開過 = _視窗(qapp, monkeypatch)
    框.show()
    框.確認鈕.click()
    assert qapp.clipboard().text() == "【假的診斷】\n程式版本：v0"
    assert 開過 == ["https://forms.gle/CQpC5R4uDdQVb6mY6"] and version.回報表單網址 == 開過[0]


def test_背景產生好之前不能按確認(qapp, monkeypatch):
    import threading

    import report_dialog
    放行 = threading.Event()

    def 慢():
        放行.wait(5)
        return "產生好了"

    框 = report_dialog.回報預覽框(產生=慢)
    assert not 框.確認鈕.isEnabled() and 框.內容框.toPlainText() == "正在收集診斷資訊…"
    放行.set()
    冒煙.等(lambda: 框.確認鈕.isEnabled(), 5)
    assert 框.內容框.toPlainText() == "產生好了"


def test_產生失敗也有一段文字(qapp, monkeypatch):
    def 壞():
        raise RuntimeError("壞")

    import report_dialog
    框 = report_dialog.回報預覽框(產生=壞, 背景=False)
    assert 框.內容框.toPlainText().startswith("【直播摘要 診斷資訊】") and 框.確認鈕.isEnabled()


# ---------- 設定框「關於」的按鈕 ----------
def test_關於區第5列有回報問題按鈕_按了開預覽(環境, monkeypatch):
    import report_dialog
    import settings_page
    monkeypatch.setattr(report_dialog.diagnostics, "產生", lambda: "假的診斷")
    開過 = []
    monkeypatch.setattr(report_dialog.QDesktopServices, "openUrl", lambda u: 開過.append(u.toString()) or True)
    monkeypatch.setattr(settings_page.QDesktopServices, "openUrl", lambda u: 開過.append(u.toString()) or True)
    台 = 環境["台"]
    台.開設定框()
    頁 = 台.設定框.頁
    鈕 = 頁.回報鈕
    assert 鈕.text() == "🐞 回報問題" and 鈕.cursor().shape() == Qt.PointingHandCursor
    assert version.回報表單網址 in 鈕.toolTip()
    格 = next(g for g in _所有格(頁.星星鈕.parentWidget()) if g.indexOf(鈕) >= 0)
    列, 欄, _, _ = 格.getItemPosition(格.indexOf(鈕))
    assert (列, 欄) == (5, 0) and 格.getItemPosition(格.indexOf(頁.星星鈕))[0] == 4
    鈕.click()
    框 = 頁.回報框
    冒煙.等(lambda: 框.確認鈕.isEnabled(), 5)
    assert 框.isVisible() and 框.內容框.toPlainText() == "假的診斷" and 開過 == []
    框.取消鈕.click()
    台.設定框.close()


def _所有格(w):
    結果 = []

    def 走(版):
        if isinstance(版, QGridLayout):
            結果.append(版)
        for i in range(版.count()):
            子 = 版.itemAt(i).layout()
            if 子 is not None:
                走(子)
    走(w.layout())
    return 結果


# ---------- 使用說明 ----------
def test_使用說明有回報問題段落_不再要附當機紀錄():
    文字 = (專案 / "docs" / "使用說明.txt").read_text(encoding="utf-8")
    assert "■ 回報問題" in 文字 and "「設定」→「關於」→「🐞 回報問題」" in 文字
    assert "https://forms.gle/CQpC5R4uDdQVb6mY6" in 文字 and "請不要在表單裡貼上 API 金鑰" in 文字
    assert "回報問題時請附上這個檔案" not in 文字
