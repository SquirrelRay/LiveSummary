"""檔案位置（app_paths）：資料在 %LOCALAPPDATA%\\LiveSummary、輸出在「文件」\\直播摘要；
第一次啟動從舊位置（%LOCALAPPDATA%\\直播摘要 優先，再來是專案資料夾）複製舊資料。
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
    assert app_paths.舊資料位置們() == []       # 測試不會從真的舊位置（AppData、專案資料夾）搬東西


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
    assert app_paths.資料資料夾() == r"C:\Users\小明\AppData\Local\LiveSummary"
    assert app_paths.設定檔() == r"C:\Users\小明\AppData\Local\LiveSummary\config.json"
    assert app_paths.詞庫資料夾() == r"C:\Users\小明\AppData\Local\LiveSummary\詞庫"


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
    assert app_paths.資料資料夾() == r"C:\Users\小明\AppData\Local\LiveSummary"
    assert app_paths.輸出資料夾().endswith(os.path.join("Documents", "直播摘要"))


def test_舊位置順序_改名前的AppData優先_專案資料夾只有開發時(monkeypatch):
    monkeypatch.setattr(app_paths, "_覆寫", {})
    monkeypatch.setattr(app_paths, "_known_folder", lambda 編號: r"C:\Users\小明\AppData\Local")
    專案 = os.path.dirname(os.path.abspath(app_paths.__file__))
    assert app_paths.舊資料位置們() == [r"C:\Users\小明\AppData\Local\直播摘要", 專案]
    monkeypatch.setattr(app_paths.sys, "frozen", True, raising=False)
    assert app_paths.舊資料位置們() == [r"C:\Users\小明\AppData\Local\直播摘要"]      # 打包版沒有專案資料夾


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


# ---------- 改名搬家：%LOCALAPPDATA%\直播摘要 → %LOCALAPPDATA%\LiveSummary ----------
@pytest.fixture
def 改名(tmp_path):
    """中文帳號：改名前的資料在 AppData\\Local\\直播摘要，新位置 AppData\\Local\\LiveSummary，專案資料夾在桌面。"""
    本機 = tmp_path / "Users" / "小明" / "AppData" / "Local"
    return {"舊AppData": 本機 / "直播摘要", "新": 本機 / "LiveSummary",
            "專案": tmp_path / "Users" / "小明" / "Desktop" / "直播摘要",
            "輸出": tmp_path / "Users" / "小明" / "Documents" / "直播摘要"}


def 做改名前資料(舊AppData):
    """模擬第2步後的 %LOCALAPPDATA%\\直播摘要：程式資料＋除錯用音訊（音訊不搬）。"""
    舊AppData.mkdir(parents=True)
    (舊AppData / "config.json").write_text(json.dumps({"model": "AppData的模型"}), encoding="utf-8")
    (舊AppData / "介面設定.json").write_text("{}", encoding="utf-8")
    (舊AppData / "詞庫").mkdir()
    (舊AppData / "詞庫" / "小明頻道.txt").write_text("艾倫｜エレン｜手動\n", encoding="utf-8")
    (舊AppData / "logs").mkdir()
    (舊AppData / "logs" / "搬家紀錄.txt").write_text("從專案資料夾搬過\n", encoding="utf-8")
    做音訊場(舊AppData / "音訊", "abc_20261014_111227_音訊")


def test_改名_AppData舊資料優先_不混專案資料夾的_舊檔不動(改名):
    做改名前資料(改名["舊AppData"])
    做舊資料(改名["專案"])           # 專案資料夾也有（比較舊的）資料
    舊快照 = 全部檔案(改名["舊AppData"])
    專案快照 = 全部檔案(改名["專案"])
    搬了 = app_paths.搬舊資料(舊=[str(改名["舊AppData"]), str(改名["專案"])], 新=str(改名["新"]))
    assert 搬了 == ["config.json", "介面設定.json", "詞庫", "logs"]
    新 = 改名["新"]
    assert json.loads((新 / "config.json").read_text(encoding="utf-8")) == {"model": "AppData的模型"}
    assert (新 / "詞庫" / "小明頻道.txt").read_text(encoding="utf-8") == "艾倫｜エレン｜手動\n"
    assert not (新 / "網址紀錄.json").exists()          # 只從一個來源搬，不拿專案資料夾的補
    assert not (新 / "音訊").exists()                   # 除錯用音訊不搬
    assert 全部檔案(改名["舊AppData"]) == 舊快照 and 全部檔案(改名["專案"]) == 專案快照
    assert not os.path.exists(str(新) + ".搬家中")


def test_改名_AppData只有音訊沒有程式資料_退回專案資料夾(改名):
    做音訊場(改名["舊AppData"] / "音訊", "abc_20261014_111227_音訊")
    做舊資料(改名["專案"])
    來源, 要搬 = app_paths.搬家來源([str(改名["舊AppData"]), str(改名["專案"])], str(改名["新"]))
    assert 來源 == str(改名["專案"]) and "config.json" in 要搬


def test_改名_AppData不存在_退回專案資料夾(改名):
    做舊資料(改名["專案"])
    assert "網址紀錄.json" in app_paths.搬舊資料(舊=[str(改名["舊AppData"]), str(改名["專案"])], 新=str(改名["新"]))


def test_改名_新位置已有資料_不搬(改名):
    做改名前資料(改名["舊AppData"])
    (改名["新"] / "logs").mkdir(parents=True)
    (改名["新"] / "logs" / "啟動里程碑_1.txt").write_text("x\n", encoding="utf-8")
    assert app_paths.搬家來源([str(改名["舊AppData"])], str(改名["新"])) == (None, [])
    assert app_paths.搬舊資料(舊=[str(改名["舊AppData"])], 新=str(改名["新"])) == []
    assert not (改名["新"] / "config.json").exists()


def test_改名_打包版啟動準備_從AppData搬_訊息寫來源(改名, monkeypatch):
    """打包版沒有專案資料夾，但改名前的 AppData 照樣搬（這台電腦第一次開 LiveSummary.exe 就讀得到原本的設定）。"""
    做改名前資料(改名["舊AppData"])
    monkeypatch.setattr(app_paths, "_覆寫", {})
    monkeypatch.setattr(app_paths, "_known_folder", lambda 編號: str(改名["舊AppData"].parent)
                        if 編號 == app_paths.FOLDERID_LocalAppData else str(改名["輸出"].parent))
    monkeypatch.setattr(app_paths.sys, "frozen", True, raising=False)
    assert app_paths.資料資料夾() == str(改名["新"])
    訊息 = app_paths.啟動準備()
    assert str(改名["舊AppData"]) in 訊息 and str(改名["新"]) in 訊息 and "舊檔沒有刪除" in 訊息
    assert json.loads((改名["新"] / "config.json").read_text(encoding="utf-8")) == {"model": "AppData的模型"}
    紀錄 = (改名["新"] / "logs" / "搬家紀錄.txt").read_text(encoding="utf-8")
    assert "從專案資料夾搬過" in 紀錄 and str(改名["舊AppData"]) in 紀錄      # 舊紀錄跟著搬，新的一行接在後面
    assert app_paths.啟動準備() == ""                                         # 第二次不再搬


def test_改名_複製失敗_訊息寫AppData來源_下次再試(改名, monkeypatch):
    做改名前資料(改名["舊AppData"])
    monkeypatch.setattr(app_paths, "_覆寫", {"資料": str(改名["新"]), "輸出": str(改名["輸出"]),
                                            "舊": [str(改名["舊AppData"]), str(改名["專案"])]})

    def 壞掉(*a, **k):
        raise OSError("磁碟滿了")
    monkeypatch.setattr(app_paths.shutil, "copytree", 壞掉)
    訊息 = app_paths.啟動準備()
    assert "失敗" in 訊息 and str(改名["舊AppData"]) in 訊息
    assert not (改名["新"] / "config.json").exists()
    monkeypatch.undo()
    assert "config.json" in app_paths.搬舊資料(舊=[str(改名["舊AppData"])], 新=str(改名["新"]))


# ---------- 除錯用音訊：位置與只留最近 5 場 ----------
def 做音訊場(根, 名, 檔=("0001_00-12.wav", "0002_12-24.wav")):
    d = 根 / 名
    d.mkdir(parents=True)
    for f in 檔:
        (d / f).write_bytes(b"RIFF")
    return d


def test_音訊放在資料資料夾底下_不在輸出資料夾():
    assert app_paths.音訊資料夾() == os.path.join(app_paths.資料資料夾(), "音訊")
    assert not app_paths.音訊資料夾().startswith(app_paths.輸出資料夾())
    assert app_paths.音訊場資料夾名("@abc", "20261014_144017") == "@abc_20261014_144017_音訊"


def test_超過保留場數_刪最舊的(tmp_path):
    名們 = [f"abc_2026101{i}_120000_音訊" for i in range(1, 8)]          # 7 場，1 號最舊
    for 名 in 名們:
        做音訊場(tmp_path, 名)
    刪掉 = app_paths.清理舊音訊(目錄=str(tmp_path))                        # 預設留 4 個舊的（+ 新的這場 = 5）
    assert sorted(刪掉) == sorted(名們[:3])
    assert sorted(os.listdir(tmp_path)) == sorted(名們[3:])


def test_不同直播主混在一起_照時間排_不看名稱開頭(tmp_path):
    做音訊場(tmp_path, "zzz_20261001_100000_音訊")           # 名稱字母最大、但時間最舊
    for i in range(2, 6):
        做音訊場(tmp_path, f"aaa_2026100{i}_100000_音訊")
    assert app_paths.清理舊音訊(目錄=str(tmp_path)) == ["zzz_20261001_100000_音訊"]


def test_沒超過保留場數_不刪(tmp_path):
    for i in range(1, 5):
        做音訊場(tmp_path, f"abc_2026101{i}_120000_音訊")
    assert app_paths.清理舊音訊(目錄=str(tmp_path)) == []
    assert len(os.listdir(tmp_path)) == 4


def test_名稱不符合格式的東西一律不碰(tmp_path):
    for i in range(1, 8):
        做音訊場(tmp_path, f"abc_2026101{i}_120000_音訊")
    不碰 = [做音訊場(tmp_path, "我的重要資料", ("a.wav",)),
          做音訊場(tmp_path, "abc_20261001_音訊", ("a.wav",)),               # 少了時間
          做音訊場(tmp_path, "abc_20261001_120000_音訊備份", ("a.wav",)),
          做音訊場(tmp_path, "_20261001_120000_音訊x", ("a.wav",)),
          做音訊場(tmp_path, "舊_20260101_010101_音訊", ("a.wav", "筆記.txt")),   # 格式對但有 wav 以外的檔案
          ]
    (tmp_path / "abc_20260101_000000_音訊.txt").write_text("檔案不是資料夾", encoding="utf-8")
    (tmp_path / "readme.txt").write_text("x", encoding="utf-8")
    刪掉 = app_paths.清理舊音訊(目錄=str(tmp_path))
    assert len(刪掉) == 3 and all(n.startswith("abc_2026101") for n in 刪掉)
    for d in 不碰:
        assert d.exists()
    assert (tmp_path / "abc_20260101_000000_音訊.txt").exists() and (tmp_path / "readme.txt").exists()


def test_音訊位置不存在_不出錯(tmp_path):
    assert app_paths.清理舊音訊(目錄=str(tmp_path / "沒有這個資料夾")) == []
    assert app_paths.清理舊音訊() == []          # conftest 的暫存資料夾裡也還沒有 音訊\


def test_音訊根目錄是檔案不是資料夾_不出錯(tmp_path):
    f = tmp_path / "音訊"
    f.write_text("x", encoding="utf-8")
    assert app_paths.清理舊音訊(目錄=str(f)) == []


def test_刪不掉一個_其他照刪不出錯(tmp_path, monkeypatch):
    for i in range(1, 8):
        做音訊場(tmp_path, f"abc_2026101{i}_120000_音訊")
    真 = app_paths.shutil.rmtree

    def 壞一個(路徑, *a, **k):
        if "20261001" in 路徑 or "20261011" in 路徑:
            raise PermissionError("被占用")
        return 真(路徑, *a, **k)
    monkeypatch.setattr(app_paths.shutil, "rmtree", 壞一個)
    刪掉 = app_paths.清理舊音訊(目錄=str(tmp_path))
    assert "abc_20261011_120000_音訊" not in 刪掉 and len(刪掉) == 2


def test_開始新的一場_音訊進資料資料夾_並清掉最舊的(tmp_path, monkeypatch):
    """live_session 建立時：音訊資料夾在 app_paths.音訊資料夾() 底下、舊的只留 4 場（加這一場 = 5）。"""
    import live_capture as lc
    根 = tmp_path / "音訊"
    monkeypatch.setattr(app_paths, "_覆寫", {**app_paths._覆寫, "資料": str(tmp_path)})
    舊們 = [f"taiji_2026100{i}_120000_音訊" for i in range(1, 8)]
    for 名 in 舊們:
        做音訊場(根, 名)
    monkeypatch.setattr(lc, "檢查直播", lambda *a, **k: "audio_only")
    monkeypatch.setattr(lc.stream_info, "背景查詢", lambda *a, **k: None)
    monkeypatch.setattr(lc, "取得時軸", lambda *a, **k: None)
    monkeypatch.setattr(lc, "找ffmpeg", lambda: "ffmpeg")
    s = lc.live_session("https://www.twitch.tv/taiji", 稿目錄=str(tmp_path / "輸出"), 用聊天室=False, 存音訊=True)
    assert os.path.dirname(s.音訊資料夾) == str(根)
    assert os.path.basename(s.音訊資料夾).startswith("taiji_") and s.音訊資料夾.endswith("_音訊")
    assert sorted(os.listdir(根)) == sorted(舊們[3:])             # 舊的剩 4 場
    s2 = lc.live_session("https://www.twitch.tv/taiji", 稿目錄=str(tmp_path / "輸出"), 用聊天室=False, 存音訊=False)
    assert s2.音訊資料夾 is None and sorted(os.listdir(根)) == sorted(舊們[3:])      # 沒開存音訊：不清理
