"""檔案位置（app_paths）：資料在 %LOCALAPPDATA%\\直播摘要、輸出在「文件」\\直播摘要；第一次啟動從專案資料夾複製舊資料。
全部用暫存資料夾（conftest 已把位置換掉），不碰真的 %LOCALAPPDATA%、「文件」、詞庫、認證管理員；含中文帳號名稱的路徑。"""
import json
import os

import conftest
import pytest

import app_paths
import config
import glossary
import panel
import startup_timeline
import ui_state


def 做舊資料(舊):
    """模擬專案資料夾裡的舊資料（含不該搬的輸出檔與 overlay_位置.json）。"""
    舊.mkdir(parents=True, exist_ok=True)
    (舊 / "config.json").write_text(json.dumps({"model": "舊模型"}), encoding="utf-8")
    (舊 / "config.backup.json").write_text("{}", encoding="utf-8")
    (舊 / "介面設定.json").write_text("{}", encoding="utf-8")
    (舊 / "網址紀錄.json").write_text("[]", encoding="utf-8")
    (舊 / "版面配置.json").write_text("{}", encoding="utf-8")
    (舊 / "翻譯錯誤紀錄.txt").write_text("錯誤\n", encoding="utf-8")
    (舊 / "詞庫").mkdir(exist_ok=True)
    (舊 / "詞庫" / "小明頻道.txt").write_text("艾倫｜エレン｜手動\n", encoding="utf-8")
    (舊 / "logs").mkdir(exist_ok=True)
    (舊 / "logs" / "啟動里程碑_1.txt").write_text("x\n", encoding="utf-8")
    (舊 / "overlay_位置.json").write_text("{}", encoding="utf-8")
    (舊 / "abc_20261014_111227_直播稿.txt").write_text("稿\n", encoding="utf-8")
    (舊 / "abc_20261014_111227_音訊").mkdir(exist_ok=True)


def 全部檔案(根):
    return {os.path.relpath(os.path.join(路, f), 根): open(os.path.join(路, f), "rb").read()
            for 路, _, 檔們 in os.walk(根) for f in 檔們}


# ---------- 測試期間的位置 ----------
def test_測試期間所有位置都在暫存資料夾():
    for 路徑 in (config.設定檔路徑, ui_state.網址紀錄檔, ui_state.介面設定檔, panel.版面檔, glossary.資料夾,
               startup_timeline.日誌資料夾, app_paths.YouTube聊天室紀錄檔(), app_paths.翻譯錯誤紀錄檔(),
               app_paths.搬家紀錄檔(), app_paths.輸出資料夾()):
        assert os.path.abspath(路徑).startswith(os.path.abspath(conftest.測試根)), 路徑
    assert app_paths.舊資料位置() is None       # 測試不會從專案資料夾搬東西


def test_各模組的路徑都來自路徑模組():
    資料 = app_paths.資料資料夾()
    assert config.設定檔路徑 == os.path.join(資料, "config.json")
    assert ui_state.網址紀錄檔 == os.path.join(資料, "網址紀錄.json")
    assert ui_state.介面設定檔 == os.path.join(資料, "介面設定.json")
    assert panel.版面檔 == os.path.join(資料, "版面配置.json")
    assert glossary.資料夾 == os.path.join(資料, "詞庫")
    assert startup_timeline.日誌資料夾 == os.path.join(資料, "logs")
    assert app_paths.YouTube聊天室紀錄檔() == os.path.join(資料, "logs", "YouTube聊天室_紀錄.txt")


# ---------- 用 Known Folder 取得位置 ----------
def test_文件與LocalAppData用KnownFolder取得_不寫死使用者資料夾(monkeypatch):
    """「文件」被 OneDrive 接管、帳號名稱是中文：拿 Known Folder 回傳的位置，不自己拼 C:\\Users\\名字\\Documents。"""
    回答 = {app_paths.FOLDERID_Documents: r"D:\OneDrive - 公司\文件",
            app_paths.FOLDERID_LocalAppData: r"C:\Users\小明\AppData\Local"}
    monkeypatch.setattr(app_paths, "_覆寫", {})
    monkeypatch.setattr(app_paths, "_known_folder", lambda 編號: 回答[編號])
    assert app_paths.輸出資料夾() == r"D:\OneDrive - 公司\文件\直播摘要"
    assert app_paths.資料資料夾() == r"C:\Users\小明\AppData\Local\直播摘要"
    assert app_paths.設定檔() == r"C:\Users\小明\AppData\Local\直播摘要\config.json"
    assert app_paths.詞庫資料夾() == r"C:\Users\小明\AppData\Local\直播摘要\詞庫"


@pytest.mark.skipif(os.name != "nt", reason="Known Folder 是 Windows API")
def test_真的KnownFolder_API回傳存在的資料夾():
    """只讀：確認 SHGetKnownFolderPath 呼叫得到（不建立、不寫入任何東西）。"""
    文件 = app_paths._known_folder(app_paths.FOLDERID_Documents)
    本機 = app_paths._known_folder(app_paths.FOLDERID_LocalAppData)
    assert 文件 and os.path.isdir(文件)
    assert 本機 and os.path.isdir(本機)
    assert os.path.normcase(本機) == os.path.normcase(os.environ["LOCALAPPDATA"])


def test_KnownFolder拿不到時用備援(monkeypatch):
    monkeypatch.setattr(app_paths, "_覆寫", {})
    monkeypatch.setattr(app_paths, "_known_folder", lambda 編號: None)
    monkeypatch.setenv("LOCALAPPDATA", r"C:\Users\小明\AppData\Local")
    assert app_paths.資料資料夾() == r"C:\Users\小明\AppData\Local\直播摘要"
    assert app_paths.輸出資料夾().endswith(os.path.join("Documents", "直播摘要"))


def test_打包版沒有舊位置(monkeypatch):
    monkeypatch.setattr(app_paths, "_覆寫", {})
    monkeypatch.setattr(app_paths.sys, "frozen", True, raising=False)
    assert app_paths.舊資料位置() is None


# ---------- 搬家 ----------
@pytest.fixture
def 中文帳號(tmp_path):
    """模擬中文帳號名稱：舊位置在桌面的專案資料夾，新位置在 AppData\\Local、「文件」。"""
    使用者 = tmp_path / "Users" / "小明"
    return {"舊": 使用者 / "Desktop" / "直播摘要",
            "資料": 使用者 / "AppData" / "Local" / "直播摘要",
            "輸出": 使用者 / "Documents" / "直播摘要"}


def test_舊位置有資料_新位置空的_複製成功且舊檔還在(中文帳號):
    舊, 新 = 中文帳號["舊"], 中文帳號["資料"]
    做舊資料(舊)
    舊快照 = 全部檔案(舊)
    搬了 = app_paths.搬舊資料(舊=str(舊), 新=str(新))
    assert 搬了 == list(app_paths.搬家項目)
    assert 全部檔案(舊) == 舊快照                      # 舊檔一個都沒少、沒改
    assert json.loads((新 / "config.json").read_text(encoding="utf-8")) == {"model": "舊模型"}
    assert (新 / "詞庫" / "小明頻道.txt").read_text(encoding="utf-8") == "艾倫｜エレン｜手動\n"
    assert (新 / "logs" / "啟動里程碑_1.txt").exists()
    # 不搬：輸出檔、音訊、已經沒人讀的 overlay_位置.json
    assert not (新 / "overlay_位置.json").exists()
    assert not list(新.glob("*_直播稿.txt")) and not list(新.glob("*_音訊"))
    assert not os.path.exists(str(新) + ".搬家中")


def test_新位置是空資料夾也算沒資料(中文帳號):
    舊, 新 = 中文帳號["舊"], 中文帳號["資料"]
    做舊資料(舊)
    新.mkdir(parents=True)
    assert "config.json" in app_paths.搬舊資料(舊=str(舊), 新=str(新))
    assert (新 / "config.json").exists()


def test_新位置已有資料_完全不動(中文帳號):
    舊, 新 = 中文帳號["舊"], 中文帳號["資料"]
    做舊資料(舊)
    新.mkdir(parents=True)
    (新 / "config.json").write_text('{"model": "新模型"}', encoding="utf-8")
    之前 = 全部檔案(新)
    assert app_paths.搬舊資料(舊=str(舊), 新=str(新)) == []
    assert 全部檔案(新) == 之前
    assert not (新 / "詞庫").exists()


def test_只有空資料夾不算有資料_有任何檔案就算(中文帳號):
    """啟動準備會先建好空的 詞庫、logs：只有空資料夾照樣搬；詞庫裡有一個檔案就算已有資料、不搬。"""
    舊, 新 = 中文帳號["舊"], 中文帳號["資料"]
    做舊資料(舊)
    (新 / "詞庫").mkdir(parents=True)
    (新 / "logs").mkdir()
    assert "config.json" in app_paths.搬舊資料(舊=str(舊), 新=str(新))

    另一個新 = 新.parent / "另一個"
    (另一個新 / "詞庫").mkdir(parents=True)
    (另一個新 / "詞庫" / "自己的.txt").write_text("x\n", encoding="utf-8")
    assert app_paths.搬舊資料(舊=str(舊), 新=str(另一個新)) == []
    assert not (另一個新 / "config.json").exists()


def test_兩邊都空_啟動準備建出空資料夾(中文帳號, monkeypatch):
    舊 = 中文帳號["舊"]
    舊.mkdir(parents=True)
    monkeypatch.setattr(app_paths, "_覆寫", {"資料": str(中文帳號["資料"]), "輸出": str(中文帳號["輸出"]), "舊": str(舊)})
    assert app_paths.啟動準備() == ""
    for 資料夾 in (中文帳號["資料"], 中文帳號["資料"] / "詞庫", 中文帳號["資料"] / "logs", 中文帳號["輸出"]):
        assert 資料夾.is_dir() and not any(p.is_file() for p in 資料夾.rglob("*"))
    assert os.listdir(舊) == []


def test_沒有舊位置_啟動準備只建資料夾(中文帳號, monkeypatch):
    monkeypatch.setattr(app_paths, "_覆寫", {"資料": str(中文帳號["資料"]), "輸出": str(中文帳號["輸出"]), "舊": None})
    assert app_paths.啟動準備() == ""
    assert 中文帳號["資料"].is_dir() and 中文帳號["輸出"].is_dir()


def test_啟動準備搬了東西_回傳訊息並寫進搬家紀錄(中文帳號, monkeypatch):
    做舊資料(中文帳號["舊"])
    monkeypatch.setattr(app_paths, "_覆寫", {k: str(v) for k, v in 中文帳號.items()})
    訊息 = app_paths.啟動準備()
    assert "config.json" in 訊息 and "詞庫" in 訊息 and "舊檔沒有刪除" in 訊息
    assert str(中文帳號["資料"]) in 訊息
    紀錄 = (中文帳號["資料"] / "logs" / "搬家紀錄.txt").read_text(encoding="utf-8")
    assert "config.json" in 紀錄
    assert 中文帳號["輸出"].is_dir()
    # 第二次啟動：新位置已有資料，不再搬也不再說
    assert app_paths.啟動準備() == ""


def test_複製到一半失敗_不留半套資料_舊檔還在_下次會再試(中文帳號, monkeypatch):
    舊, 新 = 中文帳號["舊"], 中文帳號["資料"]
    做舊資料(舊)
    舊快照 = 全部檔案(舊)
    真copytree = app_paths.shutil.copytree

    def 壞掉(*a, **k):
        raise OSError("磁碟滿了")
    monkeypatch.setattr(app_paths.shutil, "copytree", 壞掉)
    monkeypatch.setattr(app_paths, "_覆寫", {k: str(v) for k, v in 中文帳號.items()})
    訊息 = app_paths.啟動準備()
    assert "失敗" in 訊息 and "磁碟滿了" in 訊息
    assert not (新 / "config.json").exists()             # 沒有半套資料
    assert not os.path.exists(str(新) + ".搬家中")
    assert 全部檔案(舊) == 舊快照
    # 新位置只有啟動準備建的空資料夾 → 下次啟動會再試
    monkeypatch.setattr(app_paths.shutil, "copytree", 真copytree)
    assert "config.json" in app_paths.搬舊資料(舊=str(舊), 新=str(新))


def test_中文路徑實際讀寫設定與詞庫(中文帳號, monkeypatch):
    """搬到中文帳號的位置後，config、詞庫照常讀寫。"""
    做舊資料(中文帳號["舊"])
    app_paths.搬舊資料(舊=str(中文帳號["舊"]), 新=str(中文帳號["資料"]))
    設定檔 = 中文帳號["資料"] / "config.json"
    monkeypatch.setattr(config, "設定檔路徑", str(設定檔))
    config.寫入設定({"model": "改過的模型"})
    assert json.loads(設定檔.read_text(encoding="utf-8"))["model"] == "改過的模型"
    assert (中文帳號["資料"] / "config.backup.json").exists()
    庫 = glossary.詞庫("小明頻道", 資料夾路徑=str(中文帳號["資料"] / "詞庫"))
    assert not 庫.讀錯誤 and [e.寫法 for e in 庫.條目們] == ["艾倫"]
    assert 庫.路徑 == str(中文帳號["資料"] / "詞庫" / "小明頻道.txt")
