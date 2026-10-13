"""第一次使用：首次引導、轉錄模型下載畫面、文字稿模式移到開發者選項（offscreen，不開真的視窗）。
偵測一律是假的結果（顯示卡、ffmpeg、streamlink、模型快取），下載也是假的：不連網、不下載模型、不碰真的認證管理員。
1. 第一次打開出現引導；看過（看完、跳過、關掉）後不再自動出現；從膠囊選單「使用說明」可以重新打開。
2. 換頁、上一步；第 1 頁金鑰測試成功才把「下一步」變成主按鈕；第 2 頁檢查完成前不能下一步。
3. 檢查結果：有／沒有顯示卡、顯示卡偵測逾時、ffmpeg／streamlink 找不到。
4. 第 3 頁的模型大小依顯示卡決定；已下載過顯示「已準備好」。
5. 模型未下載：啟動面板顯示下載畫面與進度、模型就緒才收起；下載失敗用白話；已下載過不顯示下載畫面。
6. 文字稿模式預設隱藏、勾開發者選項後出現；命令列的文字稿模式照舊可用。"""
import errno
import os
import sys
import threading
import time
import types

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
import test_介面冒煙 as 冒煙
from PySide6.QtWidgets import QApplication, QMenu

import api_key
import config
import events
import first_run
import live_capture
import live_topics
import llm
import onboarding
import settings_page
import transcribe
import ui_state

qapp, 環境 = 冒煙.qapp, 冒煙.環境          # fixture：和冒煙測試共用
等 = 冒煙.等
真已下載 = first_run.已下載               # conftest 把它換成「一律已下載」，測真的判斷時用這個
大 = first_run.大小("large-v3-turbo")
小 = first_run.大小("small")


@pytest.fixture
def 同步(monkeypatch):
    """測試連線、第 2 頁檢查都直接執行（不開背景執行緒）。"""
    monkeypatch.setattr(onboarding.首次引導, "背景檢查", False)
    monkeypatch.setattr(onboarding.首次引導, "背景測試", False)


def _打開引導(台):
    台.開引導()
    return 台.引導


def _選單文字(台):
    選單 = QMenu()
    台.膠囊.填選單(選單)
    return 選單, {a.text(): a for a in 選單.actions()}


# ---------------- 1. 什麼時候出現 ----------------
def test_第一次打開出現引導_不先出現啟動面板(環境, 同步):
    台 = 環境["台"]
    台.啟動面板.hide()
    assert onboarding.要自動出現()
    台.開程式()
    assert 台.引導 is not None and 台.引導.isVisible()
    assert not 台.啟動面板.isVisible()
    assert 台.引導.目前頁 == 0


def test_按跳過算看過_關掉後出現啟動面板_之後開程式不再自動出現(環境, 同步):
    台 = 環境["台"]
    台.啟動面板.hide()
    台.開程式()
    台.引導.跳過()
    assert not 台.引導.isVisible()
    assert ui_state.讀旗標(onboarding.看過旗標) is True
    assert 台.啟動面板.isVisible()                 # 關掉引導後才出現啟動面板
    台.啟動面板.hide()
    台.開程式()
    assert not 台.引導.isVisible()
    assert 台.啟動面板.isVisible()


def test_看完按開始使用也算看過(環境, 同步):
    台 = 環境["台"]
    引 = _打開引導(台)
    引.到(2, 動畫=False)
    assert 引.下一步鈕.text() == "開始使用"
    引.下一步()
    assert not 引.isVisible()
    assert not onboarding.要自動出現()


def test_沒有金鑰也不會因此每次都自動出現引導(環境, 同步, monkeypatch):
    台 = 環境["台"]
    monkeypatch.setattr(llm, "檢查金鑰", 冒煙.llm.檢查金鑰)
    ui_state.存旗標(onboarding.看過旗標, True)
    assert api_key.設定的狀態(config.目前設定()) == api_key.未設定
    台.啟動面板.hide()
    台.開程式()
    assert 台.引導 is None
    assert 台.啟動面板.isVisible()


def test_從膠囊選單的使用說明重新打開_從第一頁開始(環境, 同步):
    台 = 環境["台"]
    ui_state.存旗標(onboarding.看過旗標, True)
    _選單, 項 = _選單文字(台)
    assert "使用說明" in 項
    名們 = list(項)
    assert 名們.index("使用說明") < 名們.index("設定")
    項["使用說明"].trigger()
    assert 台.引導.isVisible() and 台.引導.目前頁 == 0
    台.引導.到(2, 動畫=False)
    台.引導.跳過()
    項["使用說明"].trigger()                      # 再打開一次：回到第 1 頁
    assert 台.引導.isVisible() and 台.引導.目前頁 == 0


# ---------------- 2. 換頁 ----------------
def test_換頁與上一步_步驟點跟著走(環境, 同步):
    引 = _打開引導(環境["台"])
    assert 引.上一步鈕.isHidden()
    assert 引.點.目前 == 0
    引.下一步()
    assert 引.目前頁 == 1 and 引.點.目前 == 1
    assert not 引.上一步鈕.isHidden()
    引.下一步()
    assert 引.目前頁 == 2 and 引.下一步鈕.text() == "開始使用"
    引.上一步()
    assert 引.目前頁 == 1
    引.上一步()
    assert 引.目前頁 == 0 and 引.上一步鈕.isHidden()


def test_了解更多預設收起_點了才展開_換頁就收回(環境, 同步):
    引 = _打開引導(環境["台"])
    頁 = 引.頁們[0]
    assert not 頁.展開了 and 頁.槽層.currentWidget() is 頁.操作區
    頁.了解鈕.click()
    assert 頁.展開了 and 頁.槽層.currentWidget() is 頁.說明卡
    assert "金鑰像一組密碼" in 頁.了解字.text()
    引.下一步()
    引.上一步()
    assert not 頁.展開了


def test_第1頁_金鑰測試成功才變主按鈕_顯示綠色勾(環境, 同步, monkeypatch):
    monkeypatch.setattr(llm, "測試連線", lambda provider, 網址, 金鑰: (llm.測試成功, "連線成功，Claude 的金鑰有效。"))
    引 = _打開引導(環境["台"])
    assert not 引.下一步按鈕是主按鈕()
    assert 引.金鑰標列.isHidden()
    引.區.金鑰欄.setText("sk-ant-假金鑰-引導")
    引.區.測試連線()
    assert 引.金鑰標記.等級 == first_run.好
    assert 引.金鑰標字.text() == onboarding.測試成功字
    assert 引.下一步按鈕是主按鈕()
    assert api_key.讀取已儲存("claude") == "sk-ant-假金鑰-引導"


def test_第1頁_金鑰測試失敗顯示紅色叉_不存(環境, 同步, monkeypatch):
    monkeypatch.setattr(llm, "測試連線", lambda provider, 網址, 金鑰: (llm.測試金鑰無效, "金鑰無效，請確認有沒有複製完整。"))
    引 = _打開引導(環境["台"])
    引.區.金鑰欄.setText("sk-ant-假金鑰-錯的")
    引.區.測試連線()
    assert 引.金鑰標記.等級 == first_run.錯
    assert "金鑰無效" in 引.金鑰標字.text()
    assert not 引.下一步按鈕是主按鈕()
    assert api_key.讀取已儲存("claude") is None


def test_第1頁_重用設定框的模型金鑰區_費用用大數字(環境, 同步):
    引 = _打開引導(環境["台"])
    assert isinstance(引.區, settings_page.模型金鑰區)
    assert 引.區.精簡 and 引.區.清除鈕.isHidden() and 引.區.單價字.isHidden()
    assert 引.費用大字.text().count("約 US$") == 1 and "／小時" in 引.費用大字.text()
    assert 引.費用小字.text() == onboarding.費用註
    assert 引.區.取得連結.text() and "如何取得金鑰" in 引.區.取得連結.text()


def test_第1頁_換了服務按下一步才寫進設定(環境, 同步):
    引 = _打開引導(環境["台"])
    引.區.服務選.setCurrentIndex(引.區.服務選.findData("deepseek"))
    assert config.目前設定()["provider"] == "anthropic"          # 還沒按下一步：不寫
    引.下一步()
    設 = config.目前設定()
    assert 設["provider"] == "openai_compatible" and "deepseek" in 設["base_url"]
    assert 設["model"] == "deepseek-flash"


def _卡住的檢查(放行, 結果們):
    def 包(結果):
        def 做():
            放行.wait(5)
            return 結果
        return 做
    return [(鍵, 鍵, 包(r)) for 鍵, r in 結果們]


def test_第2頁_打開就自動檢查_全部完成前不能下一步(環境, monkeypatch):
    monkeypatch.setattr(onboarding.首次引導, "背景測試", False)
    放行 = threading.Event()
    台 = 環境["台"]
    引 = onboarding.首次引導(台, 檢查=_卡住的檢查(放行, [
        ("顯示卡", (first_run.檢查結果(first_run.好, "NVIDIA 顯示卡：可即時轉錄"), True)),
        ("ffmpeg", first_run.檢查結果(first_run.好, "ffmpeg：可以處理直播聲音")),
        ("streamlink", first_run.檢查結果(first_run.好, "streamlink：可以連上直播"))]))
    引.顯示()
    引.下一步()
    assert 引.目前頁 == 1
    assert not 引.下一步鈕.isEnabled()
    assert all(列.轉.isVisibleTo(引) for 列 in 引.檢查列們.values())      # 每項先轉圈
    引.下一步()
    assert 引.目前頁 == 1                                                   # 停用時按不動
    放行.set()
    assert 等(lambda: 引.檢查完了())
    assert 引.下一步鈕.isEnabled() and 引.下一步按鈕是主按鈕()
    assert [列.文字() for 列 in 引.檢查列們.values()] == [
        "✓ NVIDIA 顯示卡：可即時轉錄", "✓ ffmpeg：可以處理直播聲音", "✓ streamlink：可以連上直播"]
    引.close()


def test_第2頁_沒有顯示卡_找不到ffmpeg與streamlink(環境, 同步, monkeypatch):
    monkeypatch.setattr(first_run, "顯示卡數", lambda: 0)
    monkeypatch.setattr(first_run, "有NVIDIA驅動", lambda: False)
    monkeypatch.setattr(first_run, "找得到ffmpeg", lambda: False)
    monkeypatch.setattr(first_run, "找得到streamlink", lambda: False)
    引 = _打開引導(環境["台"])
    引.到(1, 動畫=False)
    assert 引.檢查完了() and 引.下一步鈕.isEnabled()               # 有 ✕ 也可以先往下看（要先處理才能用）
    字們 = [列.文字() for 列 in 引.檢查列們.values()]
    assert 字們 == ["⚠ 沒有 NVIDIA 顯示卡：轉錄會比較慢，可能跟不上直播",
                  "✕ 找不到 ffmpeg：安裝後重新開啟程式",
                  "✕ 找不到 streamlink：安裝後重新開啟程式"]
    assert 引.顯示卡可用 is False


# ---------------- 3. 檢查結果（純函式）----------------
def test_顯示卡_有可用的():
    結果, 可用 = first_run.檢查顯示卡(數卡=lambda: 1, 查驅動=lambda: True)
    assert first_run.結果字(結果) == "✓ NVIDIA 顯示卡：可即時轉錄" and 可用 is True


def test_顯示卡_沒有():
    結果, 可用 = first_run.檢查顯示卡(數卡=lambda: 0, 查驅動=lambda: False)
    assert first_run.結果字(結果) == "⚠ 沒有 NVIDIA 顯示卡：轉錄會比較慢，可能跟不上直播" and 可用 is False


def test_顯示卡_有卡但目前不能用():
    結果, 可用 = first_run.檢查顯示卡(數卡=lambda: 0, 查驅動=lambda: True)
    assert first_run.結果字(結果) == "⚠ NVIDIA 顯示卡目前無法使用：轉錄會比較慢" and 可用 is False


def test_顯示卡_偵測逾時或出錯_當作無法確認_不會卡住():
    開始 = time.time()
    結果, 可用 = first_run.檢查顯示卡(逾時=0.2, 數卡=lambda: time.sleep(3) or 1, 查驅動=lambda: True)
    assert time.time() - 開始 < 1.5
    assert first_run.結果字(結果) == "⚠ 無法確認顯示卡：開始後會自動判斷" and 可用 is None

    def 壞():
        raise OSError("假的：函式庫載不起來")
    結果, 可用 = first_run.檢查顯示卡(數卡=壞)
    assert 結果["等級"] == first_run.注意 and 可用 is None


def test_ffmpeg與streamlink():
    assert first_run.結果字(first_run.檢查ffmpeg(lambda: True)) == "✓ ffmpeg：可以處理直播聲音"
    assert first_run.結果字(first_run.檢查ffmpeg(lambda: False)) == "✕ 找不到 ffmpeg：安裝後重新開啟程式"
    assert first_run.結果字(first_run.檢查streamlink(lambda: True)) == "✓ streamlink：可以連上直播"
    assert first_run.結果字(first_run.檢查streamlink(lambda: False)) == "✕ 找不到 streamlink：安裝後重新開啟程式"


# ---------------- 4. 第 3 頁的模型卡片 ----------------
@pytest.mark.parametrize("顯示卡, 大小字", [(True, "1.6 GB"), (None, "1.6 GB"), (False, "486 MB")])
def test_第3頁_模型大小依顯示卡(環境, 同步, monkeypatch, 顯示卡, 大小字):
    monkeypatch.setattr(first_run, "已下載", lambda 名稱: False)
    引 = _打開引導(環境["台"])
    引.顯示卡可用 = 顯示卡
    引.到(2, 動畫=False)
    assert 引.模型字.text() == f"第一次開始會下載轉錄模型（約 {大小字}，只需一次）"
    assert 引.模型圖示.isVisibleTo(引)


def test_第3頁_已下載過_顯示已準備好(環境, 同步):
    引 = _打開引導(環境["台"])
    引.到(2, 動畫=False)
    assert 引.模型字.text() == "轉錄模型已準備好"
    assert 引.模型標記.等級 == first_run.好 and 引.模型圖示.isHidden()


def test_要用的模型():
    assert first_run.要用的模型(True, "large-v3-turbo") == "large-v3-turbo"
    assert first_run.要用的模型(None, "large-v3-turbo") == "large-v3-turbo"
    assert first_run.要用的模型(False, "large-v3-turbo") == transcribe.CPU_MODEL == "small"


# ---------------- 5. 轉錄模型：判斷已下載、下載進度、失敗 ----------------
def _假快取(tmp_path, monkeypatch):
    monkeypatch.setattr(first_run, "快取根", lambda: str(tmp_path))
    return os.path.join(str(tmp_path), "models--mobiuslabsgmbh--faster-whisper-large-v3-turbo")


def test_已下載_看快取裡有沒有必要的檔案(tmp_path, monkeypatch):
    資料夾 = _假快取(tmp_path, monkeypatch)
    assert 真已下載("large-v3-turbo") is False
    快照 = os.path.join(資料夾, "snapshots", "abc123")
    os.makedirs(快照)
    for 檔 in ("model.bin", "config.json"):
        open(os.path.join(快照, 檔), "w").close()
    assert 真已下載("large-v3-turbo") is False             # 還少 tokenizer.json（下載到一半）
    open(os.path.join(快照, "tokenizer.json"), "w").close()
    assert 真已下載("large-v3-turbo") is True
    assert 真已下載(str(tmp_path)) is True                  # 自己放的模型資料夾也算


def test_大小與進度字():
    assert first_run.大小字(大) == "1.6 GB" and first_run.大小字(小) == "486 MB"
    assert first_run.進度字(800_000_000, 大) == "已下載 0.8／1.6 GB"
    assert first_run.進度字(120_000_000, 小) == "已下載 120／486 MB"
    assert first_run.已等字(83) == "已等 1:23"


def _收事件():
    收到 = []
    events.接收者們.append(lambda 種類, 內容: 收到.append((種類, dict(內容))) if 種類 == "model" else None)
    return 收到


def test_準備模型_沒下載過就下載並回報進度(tmp_path, monkeypatch):
    資料夾 = _假快取(tmp_path, monkeypatch)
    monkeypatch.setattr(first_run, "已下載", lambda 名稱: False)
    舊 = list(events.接收者們)
    收到 = _收事件()

    def 假下載(名稱):                         # 一點一點寫進快取的 blobs（和真的下載一樣），不連網
        os.makedirs(os.path.join(資料夾, "blobs"), exist_ok=True)
        with open(os.path.join(資料夾, "blobs", "abc.incomplete"), "wb") as f:
            for _ in range(4):
                f.write(b"x" * 1000)
                f.flush()
                time.sleep(0.06)
    try:
        assert first_run.準備模型("large-v3-turbo", 下載=假下載, 間隔=0.02) is True
    finally:
        events.接收者們[:] = 舊
    狀態們 = [c["狀態"] for _, c in 收到]
    assert 狀態們[0] == "下載中" and 狀態們[-1] == "完成"
    已們 = [c["已"] for _, c in 收到 if c["狀態"] == "下載中"]
    assert max(已們) > 0 and 已們 == sorted(已們)
    assert all(c["總"] == 大 for _, c in 收到)


def test_準備模型_已下載過什麼都不做():
    舊 = list(events.接收者們)
    收到 = _收事件()
    try:
        assert first_run.準備模型("large-v3-turbo", 下載=lambda 名稱: pytest.fail("不該下載")) is False
        first_run.預告("large-v3-turbo")
    finally:
        events.接收者們[:] = 舊
    assert 收到 == []


@pytest.mark.parametrize("例外, 關鍵字", [
    (ConnectionError("Connection refused"), "連不上網路"),
    (OSError(errno.ENOSPC, "No space left on device"), "硬碟空間不夠"),
    (ValueError("奇怪的錯"), "請稍後再按一次「開始」重試"),
])
def test_準備模型_下載失敗用白話(monkeypatch, 例外, 關鍵字):
    monkeypatch.setattr(first_run, "已下載", lambda 名稱: False)
    舊 = list(events.接收者們)
    收到 = _收事件()

    def 壞(名稱):
        raise 例外
    try:
        with pytest.raises(first_run.模型下載錯誤) as e:
            first_run.準備模型("large-v3-turbo", 下載=壞, 間隔=0.01)
    finally:
        events.接收者們[:] = 舊
    訊息 = str(e.value)
    assert 關鍵字 in 訊息 and 訊息.startswith("轉錄模型下載失敗")
    for 字 in ("Connection", "errno", "ENOSPC", "ValueError", "huggingface", "CUDA"):
        assert 字 not in 訊息
    if 關鍵字 == "硬碟空間不夠":
        assert "1.6 GB" in 訊息
    assert 收到[-1][1]["狀態"] == "失敗" and 收到[-1][1]["訊息"] == 訊息


# ---- 引擎：沒有顯示卡直接用 small；顯示卡失敗退回 CPU 時另外準備 small；下載失敗不退回 ----
class 假Whisper:
    def __init__(self, 名稱, device, compute_type):
        if device == "cuda" and 假Whisper.顯示卡壞:
            raise RuntimeError("假的：顯示卡不能用")
        self.名稱 = 名稱

    def transcribe(self, 音訊, language=None):
        return [], None


@pytest.fixture
def 假faster_whisper(monkeypatch):
    模組 = types.ModuleType("faster_whisper")
    模組.WhisperModel = 假Whisper
    假Whisper.顯示卡壞 = False
    monkeypatch.setitem(sys.modules, "faster_whisper", 模組)
    monkeypatch.setattr(transcribe, "找顯示卡函式庫", lambda: None)
    準備們 = []
    monkeypatch.setattr(first_run, "準備模型", lambda 名稱: 準備們.append(名稱))
    return 準備們


def test_引擎_沒有顯示卡_只準備small(假faster_whisper, monkeypatch):
    monkeypatch.setattr(first_run, "顯示卡數", lambda: 0)
    model = live_capture.載入模型("ja")
    assert model.名稱 == "small" and 假faster_whisper == ["small"]


def test_引擎_有顯示卡_只準備顯示卡用的模型(假faster_whisper):
    model = live_capture.載入模型("ja")
    assert model.名稱 == transcribe.GPU_MODEL and 假faster_whisper == [transcribe.GPU_MODEL]


def test_引擎_顯示卡執行失敗退回CPU_另外準備small(假faster_whisper):
    假Whisper.顯示卡壞 = True
    model = live_capture.載入模型("ja")
    assert model.名稱 == "small" and 假faster_whisper == [transcribe.GPU_MODEL, "small"]


def test_引擎_下載失敗不退回CPU_直接停下(假faster_whisper, monkeypatch):
    def 壞(名稱):
        raise first_run.模型下載錯誤("轉錄模型下載失敗：連不上網路。")
    monkeypatch.setattr(first_run, "準備模型", 壞)
    with pytest.raises(first_run.模型下載錯誤):
        live_capture.載入模型("ja")


# ---- 啟動面板的下載畫面 ----
def _按開始(台):
    面 = 台.啟動面板
    面.狀態.開始("檢查直播")
    面._套用狀態()
    return 面


def test_啟動面板_模型未下載_開始擷取後先不收起_顯示下載進度_就緒才收起(環境):
    台 = 環境["台"]
    面 = _按開始(台)
    面.收事件("model", {"狀態": "將下載", "模型": "large-v3-turbo", "總": 大, "已": 0})
    面.收事件("files", {})
    assert 面.isVisible()                                   # 還在下載：不收起
    assert 面.下載區.isVisibleTo(面) and not 面.進度條.isVisibleTo(面)
    assert 面.下載字.text() == "第一次使用：正在下載轉錄模型（1.6 GB，只需一次）"
    面.收事件("model", {"狀態": "下載中", "模型": "large-v3-turbo", "總": 大, "已": 800_000_000})
    assert 面.下載條.maximum() == 100 and 面.下載條.value() == 49
    assert 面.下載細節.text().startswith("已下載 0.8／1.6 GB　已等 ")
    面.收事件("model", {"狀態": "完成", "模型": "large-v3-turbo", "總": 大, "已": 大})
    面.收事件("model", {"狀態": "就緒"})
    assert not 面.isVisible() and 面.下載區.isHidden()
    assert not 面.等待中


def test_啟動面板_取不到總大小_用會動的進度條與已等時間(環境):
    面 = _按開始(環境["台"])
    面.收事件("model", {"狀態": "下載中", "模型": "自己的模型", "總": None, "已": 0})
    assert 面.下載條.maximum() == 0                         # 0～0 = 會動的進度條
    assert 面.下載細節.text().startswith("已等 ")
    assert "大小不明" in 面.下載字.text()


def test_啟動面板_下載失敗_用白話顯示在面板裡(環境):
    面 = _按開始(環境["台"])
    面.收事件("model", {"狀態": "將下載", "模型": "large-v3-turbo", "總": 大, "已": 0})
    訊息 = first_run.白話錯誤(ConnectionError("x"))
    面.收事件("model", {"狀態": "失敗", "模型": "large-v3-turbo", "總": 大, "訊息": 訊息})
    面.收事件("error", {"訊息": 訊息})
    assert 面.isVisible() and not 面.等待中
    assert 面.狀態字.text() == 訊息 and "連不上網路" in 訊息
    assert 面.下載區.isHidden()                             # 不重複顯示兩次
    assert 面.開始鈕.isEnabled()                            # 可以再按一次開始


def test_啟動面板_已下載過_不顯示下載畫面_照舊收起(環境):
    台 = 環境["台"]
    面 = _按開始(台)
    面.收事件("files", {})
    assert not 面.isVisible() and 面.下載區.isHidden()


def test_啟動面板_直播中退回CPU要下載small_重新打開顯示這次的大小_好了自動收起(環境):
    台 = 環境["台"]
    面 = 台.啟動面板
    面.hide()
    面.收事件("model", {"狀態": "下載中", "模型": "small", "總": 小, "已": 100_000_000})
    assert 面.isVisible() and "486 MB" in 面.下載字.text()
    assert 面.下載細節.text().startswith("已下載 100／486 MB")
    面.收事件("model", {"狀態": "就緒"})
    assert not 面.isVisible()


def test_live_topics_下載錯誤會變成白話的error事件(monkeypatch):
    class 假直播:
        稿路徑 = "假稿.txt"
        聊天 = None

        def __init__(self, *a, **k):
            pass

        def __iter__(self):
            raise first_run.模型下載錯誤("轉錄模型下載失敗：連不上網路。請確認網路連線後，再按一次「開始」重新下載。")
    monkeypatch.setattr(live_capture, "live_session", 假直播)
    monkeypatch.setattr(llm, "檢查金鑰", lambda *a: None)
    舊 = list(events.接收者們)
    錯誤們 = []
    events.接收者們.append(lambda 種類, 內容: 錯誤們.append(內容["訊息"]) if 種類 == "error" else None)
    try:
        設定 = config.出廠預設() | {"save_summary": False, "save_transcript": False, "chat": False}
        assert live_topics.執行(設定, 網址="https://www.twitch.tv/假頻道") is False
    finally:
        events.接收者們[:] = 舊
    assert 錯誤們 == ["轉錄模型下載失敗：連不上網路。請確認網路連線後，再按一次「開始」重新下載。"]


# ---------------- 6. 文字稿模式移到開發者選項 ----------------
def test_文字稿模式預設隱藏_勾開發者選項後出現_取消又隱藏(環境):
    台 = 環境["台"]
    assert 台.檔案鈕.isHidden() and 台.直播鈕.isChecked()
    台.開設定框()
    頁 = 台.設定框.頁
    assert 頁.開發者內容.isHidden()                         # 開發者選項預設收起
    頁.開發者鈕.click()
    assert not 頁.開發者內容.isHidden()
    assert not 頁.文字稿勾.isChecked()
    頁.文字稿勾.setChecked(True)                           # 立即生效，不用按儲存
    assert not 台.檔案鈕.isHidden()
    assert ui_state.讀旗標(settings_page.文字稿旗標) is True
    assert "show_transcript" not in config.目前設定()      # 不進 config.json
    台.檔案鈕.setChecked(True)
    台._切換來源()
    頁.文字稿勾.setChecked(False)
    assert 台.檔案鈕.isHidden() and 台.直播鈕.isChecked()   # 隱藏時切回直播網址


def test_開發者選項記住_重新打開設定框時是勾著的(環境):
    台 = 環境["台"]
    ui_state.存旗標(settings_page.文字稿旗標, True)
    台.套用開發者選項()
    assert not 台.檔案鈕.isHidden()
    台.開設定框()
    assert 台.設定框.頁.文字稿勾.isChecked()


def test_命令列的文字稿模式照舊可用(tmp_path, monkeypatch):
    稿 = tmp_path / "稿.txt"
    稿.write_text("[00:01] 你好\n", encoding="utf-8")
    monkeypatch.setattr(ui_state, "介面設定檔", str(tmp_path / "介面設定.json"))
    assert not ui_state.讀旗標(settings_page.文字稿旗標)    # 介面上的開發者選項沒勾
    叫了 = []
    monkeypatch.setattr(live_topics, "執行", lambda 設定, **k: 叫了.append(k) or True)
    monkeypatch.setattr(config, "設定檔路徑", str(tmp_path / "config.json"))
    monkeypatch.setattr(sys, "argv", ["live_topics.py", str(稿), "--speed", "0", "--lang", "zh"])
    live_topics.main()
    assert 叫了 and 叫了[0]["檔案"] == str(稿) and not 叫了[0].get("網址")


def test_一般使用者看得到的字沒有內部名詞():
    字們 = list(onboarding.怎麼處理們.values())
    for 頁 in onboarding.頁們:
        字們 += [頁["標題"], 頁["說明"], *頁["了解更多"]]
    字們 += [字 for _, 字 in onboarding.流程們]
    字們 += [onboarding.費用註, onboarding.本機費用註, onboarding.金鑰好了字, onboarding.不需要金鑰字, onboarding.測試成功字]
    for f in (first_run.檢查ffmpeg, first_run.檢查streamlink):
        字們 += [f(lambda: True)["標籤"], f(lambda: False)["標籤"]]
    for 數, 驅動 in ((1, True), (0, False), (0, True)):
        字們.append(first_run.檢查顯示卡(數卡=lambda 數=數: 數, 查驅動=lambda 驅動=驅動: 驅動)[0]["標籤"])
    字們 += [first_run.白話錯誤(e, 大) for e in (ConnectionError("x"), OSError(errno.ENOSPC, "x"), ValueError("x"))]
    全部 = "\n".join(字們)
    for 詞 in ("config.json", "provider", "CUDA", "cuda", "ctranslate2", "GPU", "faster-whisper", "Whisper", "huggingface"):
        assert 詞 not in 全部, 詞
    for 頁 in onboarding.頁們:
        assert len(頁["標題"]) <= 10
        assert 頁["說明"].count("\n") <= 1


# ---------------- 版面修正 ----------------
def test_第1頁_了解更多最多三條(環境, 同步):
    assert len(onboarding.頁們[0]["了解更多"]) == 3
    assert onboarding.頁們[1]["了解更多"] == []


def test_第2頁_沒有了解更多_只有警告與錯誤的項目有怎麼處理(環境, 同步, monkeypatch):
    monkeypatch.setattr(first_run, "顯示卡數", lambda: 0)
    monkeypatch.setattr(first_run, "有NVIDIA驅動", lambda: False)
    monkeypatch.setattr(first_run, "找得到ffmpeg", lambda: False)      # ffmpeg ✕、streamlink ✓（conftest 預設找得到）
    引 = _打開引導(環境["台"])
    引.到(1, 動畫=False)
    頁 = 引.頁們[1]
    assert 頁.了解鈕.isHidden()
    列們 = 引.檢查列們
    assert 列們["顯示卡"].結果["等級"] == first_run.注意 and not 列們["顯示卡"].處理鈕.isHidden()
    assert 列們["ffmpeg"].結果["等級"] == first_run.錯 and not 列們["ffmpeg"].處理鈕.isHidden()
    assert 列們["streamlink"].結果["等級"] == first_run.好 and 列們["streamlink"].處理鈕.isHidden()    # ✓ 不附說明
    assert all(列.處理字.isHidden() for 列 in 列們.values())                                         # 預設收起
    列們["ffmpeg"].處理鈕.click()
    assert not 列們["ffmpeg"].處理字.isHidden() and "winget install Gyan.FFmpeg" in 列們["ffmpeg"].處理字.text()
    assert 列們["ffmpeg"].處理鈕.text() == onboarding.收起處理字
    assert 列們["顯示卡"].處理字.isHidden()
    列們["ffmpeg"].處理鈕.click()
    assert 列們["ffmpeg"].處理字.isHidden() and 列們["ffmpeg"].處理鈕.text() == onboarding.怎麼處理字


def test_第1頁_只有一個金鑰狀態_引導裡的提示文字不被截斷(環境, 同步):
    api_key.儲存("claude", "sk-ant-假金鑰-已存")
    引 = _打開引導(環境["台"])
    assert 引.區.金鑰字.isHidden()                               # 設定框原本那行綠字在引導裡不顯示
    assert not 引.金鑰標列.isHidden() and 引.金鑰標字.text() == onboarding.金鑰好了字
    assert 引.區.金鑰欄.placeholderText() == "已儲存"
    assert 引.金鑰標列.parent() is 引.區.金鑰狀態列                   # 和「如何取得金鑰」同一行


def test_設定框裡的金鑰提示文字不變(環境):
    api_key.儲存("claude", "sk-ant-假金鑰-已存")
    台 = 環境["台"]
    台.開設定框()
    頁 = 台.設定框.頁
    assert 頁.金鑰欄.placeholderText() == "已儲存（要更換就貼上新的金鑰）"
    assert not 頁.金鑰字.isHidden() and "已儲存在這台電腦" in 頁.金鑰字.text()


def test_最後一頁沒有跳過(環境, 同步):
    引 = _打開引導(環境["台"])
    assert not 引.跳過鈕.isHidden()
    引.到(1, 動畫=False)
    assert not 引.跳過鈕.isHidden()
    引.到(2, 動畫=False)
    assert 引.跳過鈕.isHidden()
    引.上一步()
    assert not 引.跳過鈕.isHidden()


def test_三頁切換視窗大小固定_內容垂直置中(環境, 同步):
    引 = _打開引導(環境["台"])
    大小 = 引.size()
    上下 = []
    for i in range(3):
        引.到(i, 動畫=False)
        QApplication.processEvents()
        assert 引.size() == 大小
        頁 = 引.頁們[i]
        上 = 頁.圖示.mapTo(頁, 頁.圖示.rect().topLeft()).y()
        下 = 頁.height() - (頁.了解鈕.mapTo(頁, 頁.了解鈕.rect().bottomLeft()).y() if not 頁.了解鈕.isHidden()
                          else 頁.操作區.mapTo(頁, 頁.操作區.rect().bottomLeft()).y())
        上下.append((上, 下))
        assert abs(上 - 下) <= 24, (i, 上, 下)          # 上下留白差不多：置中，不是全擠在上面
