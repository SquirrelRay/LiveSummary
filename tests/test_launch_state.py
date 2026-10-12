"""啟動面板的狀態切換邏輯（純 Python，不開視窗、不連網）。"""
from launch_state import 啟動狀態


def test_初始是待命_開始鈕可用_無進度條():
    s = 啟動狀態()
    assert s.開始鈕可用() and not s.顯示進度條() and s.文字() == ""


def test_開始後顯示啟動中與階段_開始鈕停用_有進度條():
    s = 啟動狀態()
    assert s.開始("檢查 API 金鑰")
    assert s.文字() == "啟動中…（檢查 API 金鑰）"
    assert not s.開始鈕可用() and s.顯示進度條()


def test_沒有階段就顯示通用文字():
    s = 啟動狀態()
    s.開始()
    assert s.文字() == "啟動中…"


def test_階段會依序切換():
    s = 啟動狀態()
    s.開始("檢查 API 金鑰")
    s.換階段("連線直播、確認有開播")
    s.換階段("")                      # 空階段忽略
    assert s.文字() == "啟動中…（連線直播、確認有開播）"


def test_啟動中不能重複開始():
    s = 啟動狀態()
    assert s.開始("a")
    assert not s.開始("b")
    assert s.階段 == "a"


def test_失敗後回到可操作_並顯示中文錯誤():
    s = 啟動狀態()
    s.開始("連線直播、確認有開播")
    s.失敗("頻道目前沒有開播。")
    assert s.開始鈕可用() and not s.顯示進度條()
    assert s.文字() == "頻道目前沒有開播。" and s.是錯誤()
    assert s.開始("檢查 API 金鑰")      # 可以重新開始
    assert s.錯誤 == "" and not s.是錯誤()


def test_失敗沒有訊息時用預設中文():
    s = 啟動狀態()
    s.開始()
    s.失敗()
    assert "啟動失敗" in s.文字()


def test_成功後回到待命且沒有殘留文字():
    s = 啟動狀態()
    s.開始("準備聊天室")
    s.成功()
    assert s.開始鈕可用() and s.文字() == ""


def test_待命時換階段無效():
    s = 啟動狀態()
    s.換階段("不該出現")
    assert s.文字() == ""
