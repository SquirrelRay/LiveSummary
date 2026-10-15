"""檢查更新（全部用假的 GitHub 回應，不連網）：
有新版、已是最新、略過的版本、網路錯誤、逾時、404、格式錯誤、版本號比較（1.0.10 比 1.0.9 新）、
失敗只寫 log 不跳視窗、更新視窗的按鈕、設定框的開關與「關於」按鈕。"""
import io
import json
import os
import urllib.error

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
import test_介面冒煙 as 冒煙

import app_paths
import config
import ui_state
import update_check
import version


class 假回應:
    def __init__(self, 位元組):
        self._io = io.BytesIO(位元組)

    def read(self, n=-1):
        return self._io.read(n)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def 假發布(tag="v9.9.9", body="修好了很多東西", url=None, **其他):
    資料 = {"tag_name": tag, "body": body, "html_url": url or f"{version.專案網址}/releases/tag/{tag}", **其他}
    return json.dumps(資料).encode("utf-8")


def 開(內容):
    """假的 開網址：記下被呼叫的網址與逾時，回傳固定內容。"""
    呼叫 = []

    def f(網址, 逾時):
        呼叫.append((網址, 逾時))
        return 假回應(內容)
    f.呼叫 = 呼叫
    return f


def 丟(例外):
    def f(網址, 逾時):
        raise 例外
    return f


qapp, 環境 = 冒煙.qapp, 冒煙.環境          # fixture：和冒煙測試共用


# ---------- 版本號比較 ----------
@pytest.mark.parametrize("新, 舊", [
    ("1.0.10", "1.0.9"), ("v1.1.0", "1.0.99"), ("2.0.0", "1.99.99"), ("1.0.1", "1.0.0"), ("1.0.0.1", "1.0.0"), ("V1.2", "1.1.9"),
])
def test_版本號逐段比整數(新, 舊):
    assert update_check.較新(新, 舊)
    assert not update_check.較新(舊, 新)


@pytest.mark.parametrize("甲, 乙", [("1.0.0", "1.0.0"), ("v1.0.0", "1.0.0"), ("1.0", "1.0.0")])
def test_相同版本不算較新(甲, 乙):
    assert not update_check.較新(甲, 乙)
    assert not update_check.較新(乙, 甲)


@pytest.mark.parametrize("壞", ["", None, "abc", "latest", "版本一"])
def test_不是版本號_不算較新也不炸(壞):
    assert update_check.解析版本(壞) is None
    assert not update_check.較新(壞, "1.0.0")
    assert not update_check.較新("1.0.0", 壞)


def test_版本號帶後綴只看數字部分():
    assert update_check.解析版本("v1.2.3-beta.1") == (1, 2, 3)


# ---------- 檢查（五種結果）----------
def test_有新版():
    開網 = 開(假發布("v1.0.10", "新功能 A\n新功能 B"))
    結 = update_check.檢查("1.0.9", "", 開網)
    assert 結.狀態 == update_check.狀態_新版
    assert 結.版本 == "1.0.10"
    assert "新功能 A" in 結.內容
    assert 結.網址.startswith(version.專案網址 + "/")
    網址, 逾時 = 開網.呼叫[0]
    assert 網址 == f"https://api.github.com/repos/{version.GitHub倉庫}/releases/latest"
    assert 逾時 <= 5


def test_已是最新():
    assert update_check.檢查("1.0.0", "", 開(假發布("v1.0.0"))).狀態 == update_check.狀態_最新
    assert update_check.檢查("1.0.10", "", 開(假發布("v1.0.9"))).狀態 == update_check.狀態_最新      # GitHub 上的比本機舊也不提醒


def test_略過的版本不再提醒_更新的版本照常提醒():
    內容 = 假發布("v1.1.0")
    assert update_check.檢查("1.0.0", "1.1.0", 開(內容)).狀態 == update_check.狀態_略過
    assert update_check.檢查("1.0.0", "v1.1.0", 開(內容)).狀態 == update_check.狀態_略過
    assert update_check.檢查("1.0.0", "1.1.0", 開(假發布("v1.2.0"))).狀態 == update_check.狀態_新版


def test_網路錯誤安靜跳過():
    for 例外 in (urllib.error.URLError("getaddrinfo failed"), ConnectionResetError("斷線"), OSError("沒網路")):
        結 = update_check.檢查("1.0.0", "", 丟(例外))
        assert 結.狀態 == update_check.狀態_失敗 and "連不上" in 結.原因


def test_逾時安靜跳過():
    for 例外 in (TimeoutError(), urllib.error.URLError(TimeoutError("timed out"))):
        結 = update_check.檢查("1.0.0", "", 丟(例外))
        assert 結.狀態 == update_check.狀態_失敗 and "逾時" in 結.原因


def test_專案還不存在_404安靜跳過():
    錯 = urllib.error.HTTPError("https://api.github.com/x", 404, "Not Found", {}, None)
    結 = update_check.檢查("1.0.0", "", 丟(錯))
    assert 結.狀態 == update_check.狀態_失敗 and "404" in 結.原因


def test_其他HTTP錯誤_例如被限流():
    錯 = urllib.error.HTTPError("https://api.github.com/x", 403, "rate limit", {}, None)
    結 = update_check.檢查("1.0.0", "", 丟(錯))
    assert 結.狀態 == update_check.狀態_失敗 and "403" in 結.原因


@pytest.mark.parametrize("內容", [
    b"", b"<html>not json</html>", b"[]", b'"v1.0.0"', b"{}", b'{"tag_name": 5}', b'{"tag_name": "nightly"}',
    b'{"name": "v2.0.0"}', b"\xff\xfe\x00",
])
def test_格式錯誤安靜跳過(內容):
    結 = update_check.檢查("1.0.0", "", 開(內容))
    assert 結.狀態 == update_check.狀態_失敗
    assert 結.原因


def test_沒料到的錯誤也不丟出來():
    結 = update_check.檢查("1.0.0", "", 丟(RuntimeError("怪事")))
    assert 結.狀態 == update_check.狀態_失敗


def test_下載網址只收本專案的頁面():
    壞 = 假發布("v2.0.0", url="https://evil.example.com/download")
    assert update_check.檢查("1.0.0", "", 開(壞)).網址 == version.發布頁網址
    沒有 = json.dumps({"tag_name": "v2.0.0"}).encode()
    結 = update_check.檢查("1.0.0", "", 開(沒有))
    assert 結.網址 == version.發布頁網址 and 結.內容 == ""


def test_更新內容太長會截斷():
    長 = "字" * 5000
    短 = update_check.截斷內容(長)
    assert len(短) <= update_check.內容上限 + 1 and 短.endswith("…")
    assert update_check.截斷內容("簡短") == "簡短"
    assert "沒有附" in update_check.截斷內容("  ")


# ---------- 背景檢查器：log 與訊號 ----------
def _log():
    p = app_paths.更新檢查紀錄檔()
    return open(p, encoding="utf-8").read().splitlines() if os.path.exists(p) else []


def _跑檢查器(開網址, 略過=""):
    收到 = []
    檢 = update_check.更新檢查器(開網址=開網址, 目前版本="1.0.0", 讀略過=lambda: 略過)
    檢.有新版.connect(收到.append)
    檢._跑()                          # 直接在這個執行緒跑一次（真的啟動是 開始() 的背景執行緒）
    return 收到


def test_失敗只寫一行log_不送訊號(qapp):
    錯 = urllib.error.HTTPError("https://api.github.com/x", 404, "Not Found", {}, None)
    前 = len(_log())
    assert _跑檢查器(丟(錯)) == []
    新 = _log()[前:]
    assert len(新) == 1 and "404" in 新[0] and "已略過" in 新[0]


def test_最新與略過_不送訊號(qapp):
    assert _跑檢查器(開(假發布("v1.0.0"))) == []
    assert _跑檢查器(開(假發布("v2.0.0")), 略過="2.0.0") == []


def test_有新版送訊號(qapp):
    收到 = _跑檢查器(開(假發布("v2.0.0")))
    assert len(收到) == 1 and 收到[0].版本 == "2.0.0"
    assert any("有新版 2.0.0" in 行 for 行 in _log())


def test_背景執行緒真的跑完(qapp):
    檢 = update_check.更新檢查器(開網址=丟(urllib.error.URLError("沒網路")), 目前版本="1.0.0", 讀略過=lambda: "")
    檢.開始()
    檢.執行緒.join(5)
    assert not 檢.執行緒.is_alive()
    assert any("沒網路" in 行 or "連不上" in 行 for 行 in _log())


# ---------- 視窗 ----------
def _結(版本="1.2.0", 內容="這版修了很多"):
    return update_check.結果(update_check.狀態_新版, 版本, 內容, f"{version.專案網址}/releases/tag/v{版本}")


def test_更新視窗內容與三個按鈕(qapp):
    窗 = update_check.更新視窗(_結())
    assert "1.2.0" in 窗.標題字.text() and version.版本字() in 窗.標題字.text()
    assert "這版修了很多" in 窗.內容框.toPlainText()
    assert [b.text() for b in (窗.下載鈕, 窗.稍後鈕, 窗.略過鈕)] == ["前往下載", "稍後", "略過這個版本"]


def test_更新視窗內容太長會截斷(qapp):
    窗 = update_check.更新視窗(_結(內容="長" * 5000))
    assert len(窗.內容框.toPlainText()) <= update_check.內容上限 + 1


def test_按略過_以後不再提醒(qapp):
    窗 = update_check.更新視窗(_結("3.0.0"))
    窗.略過鈕.click()
    assert 窗.選擇 == "略過"
    assert ui_state.讀略過版本() == "3.0.0"
    assert update_check.檢查("1.0.0", ui_state.讀略過版本(), 開(假發布("v3.0.0"))).狀態 == update_check.狀態_略過


def test_按稍後_不記略過(qapp):
    窗 = update_check.更新視窗(_結("4.0.0"))
    窗.稍後鈕.click()
    assert 窗.選擇 == "稍後"
    assert ui_state.讀略過版本() != "4.0.0"


def test_按前往下載_打開發布頁(qapp, monkeypatch):
    開過 = []
    monkeypatch.setattr(update_check.QDesktopServices, "openUrl", lambda u: 開過.append(u.toString()) or True)
    窗 = update_check.更新視窗(_結("5.0.0"))
    窗.下載鈕.click()
    assert 開過 == [f"{version.專案網址}/releases/tag/v5.0.0"]
    assert 窗.選擇 == "前往下載"


# ---------- 設定 ----------
def test_設定預設開_存取_合法():
    assert config.出廠預設()["check_update"] is True
    assert "check_update" in config.設定說明 and "check_update" in config.檢查
    assert config.檢查["check_update"]("不是布林") is False


def test_設定框有開關與兩個按鈕(環境, monkeypatch):
    import settings_page
    開過 = []
    monkeypatch.setattr(settings_page.QDesktopServices, "openUrl", lambda u: 開過.append(u.toString()) or True)
    台 = 環境["台"]
    台.開設定框()
    頁 = 台.設定框.頁
    勾 = 頁.欄["check_update"]
    assert 勾.isChecked() and "檢查更新" in 勾.text()
    勾.setChecked(False)
    assert 頁.讀全部()["check_update"] is False
    頁.儲存()
    assert config.目前設定()["check_update"] is False
    頁.載入(config.出廠預設())
    assert 勾.isChecked()
    assert 頁.星星鈕.text() == "⭐ 喜歡的話到 GitHub 給個星星"
    assert 頁.咖啡鈕.text() == "☕ 請我喝杯咖啡"
    頁.星星鈕.click()
    頁.咖啡鈕.click()
    assert 開過 == ["https://github.com/SquirrelRay/LiveSummary", "https://ko-fi.com/squirrelray"]


def test_關掉開關就不啟動檢查(環境, monkeypatch):
    台 = 環境["台"]
    建立 = []
    monkeypatch.setattr(update_check, "更新檢查器", lambda *a, **k: 建立.append(1))
    config.寫入設定({"check_update": False})
    台.啟動更新檢查()
    assert 建立 == []
