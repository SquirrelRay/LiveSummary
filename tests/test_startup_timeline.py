"""啟動時間里程碑紀錄、面板空狀態的階段切換。全部用假時鐘與暫存資料夾，不連網、不呼叫 API。"""
import os

import pytest

import events
import startup_timeline as st


class 假時鐘:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t

    def 過(self, 秒):
        self.t += 秒


@pytest.fixture
def 紀錄(tmp_path):
    時鐘 = 假時鐘()
    return st.里程碑紀錄(資料夾=str(tmp_path), 時鐘=時鐘), 時鐘


def 讀(紀):
    with open(紀.路徑, encoding="utf-8") as f:
        return f.read()


def test_里程碑依序記下相對秒數(紀錄):
    紀, 時鐘 = 紀錄
    紀.開始({"分段長度設定(秒)": 20})
    時鐘.過(3.0)
    assert 紀.標記(st.模型載入完成) == 3.0
    時鐘.過(20.5)
    assert 紀.標記(st.第一段收滿, 實際秒=20.0) == 23.5
    時鐘.過(4.25)
    assert 紀.標記(st.第一段轉錄完成, 句數=2) == 27.75
    內容 = 讀(紀)
    assert "分段長度設定(秒) = 20" in 內容
    順序 = [內容.index(x) for x in ("按下開始", st.模型載入完成, st.第一段收滿, st.第一段轉錄完成)]
    assert 順序 == sorted(順序)
    assert "+   3.00s] 轉錄模型載入完成" in 內容
    assert "實際秒=20.0" in 內容


def test_每個里程碑只記第一次(紀錄):
    紀, 時鐘 = 紀錄
    紀.開始()
    時鐘.過(1)
    assert 紀.標記(st.翻譯請求送出) == 1.0
    時鐘.過(5)
    assert 紀.標記(st.翻譯請求送出) is None
    assert 讀(紀).count(st.翻譯請求送出) == 1


def test_沒按開始時標記不做事(紀錄):
    紀, _ = 紀錄
    assert 紀.標記(st.模型載入完成) is None
    assert 紀.路徑 is None


def test_再按一次開始會換新檔並重新計算(紀錄, tmp_path):
    紀, 時鐘 = 紀錄
    紀.開始()
    第一個 = 紀.路徑
    時鐘.過(10)
    紀.開始()
    assert 紀.標記(st.模型載入完成) == 0.0
    assert 紀.路徑 != 第一個 or os.path.exists(第一個)


def test_紀錄不含金鑰(紀錄, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-SECRET-123")
    紀, _ = 紀錄
    紀.開始({"摘要模型": "claude-haiku-5-5", "語言設定": "ja"})
    紀.標記(st.翻譯回來, 回傳字數=10)
    內容 = 讀(紀)
    assert "SECRET" not in 內容 and "sk-ant" not in 內容


def test_資料夾無法寫入也不丟例外(tmp_path):
    擋住 = tmp_path / "檔案不是資料夾"
    擋住.write_text("x")
    紀 = st.里程碑紀錄(資料夾=str(擋住 / "logs"), 時鐘=假時鐘())
    assert 紀.開始() is None
    紀.標記(st.模型載入完成)      # 只要不丟例外就好


def test_全域標記會送出milestone事件(tmp_path, monkeypatch):
    收到 = []
    monkeypatch.setattr(st, "紀錄", st.里程碑紀錄(資料夾=str(tmp_path), 時鐘=假時鐘()))
    events.接收者們.append(lambda 種類, 內容: 收到.append((種類, 內容)))
    try:
        st.開始()
        st.標記(st.模型載入完成)
        st.標記(st.模型載入完成)      # 重複的不再送
    finally:
        events.接收者們.clear()
    assert [(k, c["名稱"]) for k, c in 收到] == [("milestone", st.模型載入完成)]


# ---- 面板空狀態階段 ----
def test_階段依序切換_三種提示():
    a = st.啟動階段()
    assert a.提示() == ""                       # 沒按開始沒有提示
    a.重設()
    assert a.提示() == "載入模型中…"
    a.收里程碑(st.模型載入完成)
    assert a.提示() == "聆聽中，等待第一段…"
    a.收里程碑(st.第一段送轉錄)
    assert a.提示() == "轉錄與翻譯中…"
    a.收里程碑(st.第一句顯示)
    assert a.提示() == ""                       # 第一句出現後提示消失


def test_階段只會往前不會倒退():
    a = st.啟動階段()
    a.重設()
    a.收里程碑(st.第一段送轉錄)
    a.收里程碑(st.模型載入完成)                 # 晚到的舊里程碑不能把提示倒退
    assert a.提示() == "轉錄與翻譯中…"


def test_翻譯請求送出也算轉錄與翻譯中():
    a = st.啟動階段()
    a.重設()
    a.收里程碑(st.翻譯請求送出)
    assert a.提示() == "轉錄與翻譯中…"


def test_完成後晚到的里程碑不會讓提示再出現():
    a = st.啟動階段()
    a.重設()
    a.收里程碑(st.第一句顯示)
    a.收里程碑(st.第一段送轉錄)
    assert a.提示() == ""


def test_沒開字幕時以文字稿代替第一句():
    a = st.啟動階段()
    a.重設()
    a.收里程碑(st.第一句顯示_無字幕)
    assert a.提示() == ""


def test_文字稿重播與結束都沒有提示():
    a = st.啟動階段()
    a.重設(有模型=False)
    assert a.提示() == ""
    a.重設()
    a.結束()
    assert a.提示() == ""


# ---------- 每個里程碑只記一次：「第一句顯示」有字幕／沒開字幕是同一件事 ----------
def test_第一句顯示_有字幕之後_沒開字幕的版本不再記(紀錄):
    紀, 時鐘 = 紀錄
    紀.開始()
    時鐘.過(42.3)
    assert 紀.標記(st.第一句顯示) == 42.3
    時鐘.過(48.1)                                    # 例如之後關掉了逐句翻譯面板
    assert 紀.標記(st.第一句顯示_無字幕) is None
    內容 = 讀(紀)
    assert 內容.count("第一句顯示") == 1 and st.第一句顯示_無字幕 not in 內容


def test_第一句顯示_沒開字幕先發生_之後有字幕也不再記(紀錄):
    紀, 時鐘 = 紀錄
    紀.開始()
    時鐘.過(30)
    assert 紀.標記(st.第一句顯示_無字幕) == 30
    時鐘.過(10)
    assert 紀.標記(st.第一句顯示) is None
    assert 讀(紀).count("第一句顯示") == 1


def test_每個里程碑都只記一次(紀錄):
    紀, 時鐘 = 紀錄
    紀.開始()
    名們 = [getattr(st, k) for k in dir(st) if isinstance(getattr(st, k), str) and getattr(st, k).startswith("第一")]
    名們 += [st.直播檢查完成, st.模型載入完成, st.擷取已啟動, st.語言偵測完成]
    for _ in range(3):
        for 名 in 名們:
            時鐘.過(1)
            紀.標記(名)
    內容 = 讀(紀)
    for 名 in 名們:
        assert 內容.count(f"] {名}") <= 1, 名
    assert 內容.count("第一句顯示") == 1


def test_重新開始一場_同組里程碑重新計算(紀錄):
    紀, _ = 紀錄
    紀.開始()
    紀.標記(st.第一句顯示)
    紀.開始()
    assert 紀.標記(st.第一句顯示_無字幕) is not None


def test_聊天室翻譯的里程碑各記一次(紀錄):
    紀, 時鐘 = 紀錄
    紀.開始()
    for _ in range(2):
        for 名 in (st.聊天第一則, st.聊天第一批送出, st.聊天第一批回來, st.聊天第一則顯示):
            時鐘.過(1)
            紀.標記(名)
    內容 = 讀(紀)
    for 名 in (st.聊天第一則, st.聊天第一批送出, st.聊天第一批回來, st.聊天第一則顯示):
        assert 內容.count(名) == 1
