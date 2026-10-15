"""scripts/check.py（git hook 跑的提交前檢查）：空的 commit 才跳過、git 出錯照常檢查；依序測試另外跑；平行與依序兩段都要過。
不真的跑 pytest、ruff、git：用假的子程序結果。"""
import importlib.util
import os
import sys
from types import SimpleNamespace

import pytest

專案根 = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_規格 = importlib.util.spec_from_file_location("提交前檢查", os.path.join(專案根, "scripts", "check.py"))
check = importlib.util.module_from_spec(_規格)
_規格.loader.exec_module(check)


@pytest.mark.parametrize("回傳碼,沒變更", [(0, True), (1, False), (128, False)])
def test_只有git說沒有變更才算空commit_出錯照常檢查(monkeypatch, 回傳碼, 沒變更):
    呼叫們 = []
    monkeypatch.setattr(check.subprocess, "run", lambda 參數, **k: 呼叫們.append(參數) or SimpleNamespace(returncode=回傳碼))
    assert check.沒有變更() is 沒變更
    assert 呼叫們 == [["git", "diff", "--cached", "--quiet"]]


def _假檢查(monkeypatch, 沒變更):
    跑了 = []
    monkeypatch.setattr(check, "沒有變更", lambda: 沒變更)
    monkeypatch.setattr(check, "check_pytest", lambda 全部=False: 跑了.append("pytest") or True)
    monkeypatch.setattr(check, "check_ruff", lambda: 跑了.append("ruff") or True)
    return 跑了


def test_hook_空的commit直接通過_不跑檢查(monkeypatch, capsys):
    跑了 = _假檢查(monkeypatch, 沒變更=True)
    monkeypatch.setattr(sys, "argv", ["check.py", "--commit"])
    assert check.main() == 0 and 跑了 == []
    assert "沒有任何檔案變更" in capsys.readouterr().out


def test_hook_有變更照常完整檢查(monkeypatch):
    跑了 = _假檢查(monkeypatch, 沒變更=False)
    monkeypatch.setattr(sys, "argv", ["check.py", "--commit"])
    assert check.main() == 0 and 跑了 == ["pytest", "ruff"]


def test_手動檢查不管有沒有變更都跑(monkeypatch):
    跑了 = _假檢查(monkeypatch, 沒變更=True)
    monkeypatch.setattr(sys, "argv", ["check.py"])
    assert check.main() == 0 and 跑了 == ["pytest", "ruff"]


def test_hook_呼叫check時帶commit():
    with open(os.path.join(專案根, ".githooks", "pre-commit"), encoding="utf-8") as f:
        內容 = f.read()
    assert 'scripts/check.py --commit' in 內容 and "--all" not in 內容.split("exec", 1)[1]


def test_依序測試檔_找得到真視窗的測試():
    檔們 = check.依序測試檔()
    assert "tests/test_YouTube介面修正.py" in 檔們
    assert "tests/test_提交前檢查.py" not in 檔們              # 只是提到標記名稱的不算


def _假pytest(monkeypatch, 結果們):
    參數們 = []

    def 假跑(參數):
        參數們.append(參數)
        return 結果們.pop(0)
    monkeypatch.setattr(check, "run", 假跑)
    monkeypatch.setattr(check, "有平行套件", lambda: True)
    monkeypatch.setattr(check, "依序測試檔", lambda: ["tests/test_甲.py"])
    return 參數們


def _結果(碼, 輸出=""):
    return SimpleNamespace(returncode=碼, stdout=輸出, stderr="")


def test_一般檢查_平行跑其他_依序的另外跑_都不含慢測試(monkeypatch, capsys):
    參數們 = _假pytest(monkeypatch, [_結果(0, "1300 passed in 20s"), _結果(5)])      # 依序的都是慢測試：沒選到（5）不算失敗
    assert check.check_pytest() is True
    平行, 依序 = 參數們
    assert "-n" in 平行 and 平行[平行.index("-m") + 1] == "not slow and not 依序"
    assert 依序[依序.index("-m") + 1] == "not slow and 依序" and "no:xdist" in 依序 and 依序[-1] == "tests/test_甲.py"
    assert "平行 1300 個" in capsys.readouterr().out


def test_完整檢查_兩段都含慢測試_數量都列出(monkeypatch, capsys):
    參數們 = _假pytest(monkeypatch, [_結果(0, "1380 passed"), _結果(0, "1 passed")])
    assert check.check_pytest(全部=True) is True
    assert 參數們[0][參數們[0].index("-m") + 1] == "not 依序"
    assert 參數們[1][參數們[1].index("-m") + 1] == "依序"
    assert "平行 1380 個＋依序 1 個" in capsys.readouterr().out


@pytest.mark.parametrize("結果們", [[_結果(1, "1 failed")], [_結果(0, "9 passed"), _結果(1, "1 failed")],
                                  [_結果(0, "9 passed"), _結果(5)]])
def test_任何一段失敗就擋下_完整檢查時依序的沒跑到也算失敗(monkeypatch, 結果們):
    _假pytest(monkeypatch, 結果們)
    全部 = len(結果們) == 2 and 結果們[1].returncode == 5
    assert check.check_pytest(全部=全部) is False


def test_沒裝平行套件_全部依序跑_照樣檢查(monkeypatch):
    參數們 = []
    monkeypatch.setattr(check, "run", lambda 參數: 參數們.append(參數) or _結果(0, "1381 passed"))
    monkeypatch.setattr(check, "有平行套件", lambda: False)
    assert check.check_pytest() is True
    assert len(參數們) == 1 and "-n" not in 參數們[0] and 參數們[0][參數們[0].index("-m") + 1] == "not slow"
