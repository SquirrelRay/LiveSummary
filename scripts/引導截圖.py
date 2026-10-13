"""首次引導、啟動面板下載畫面、設定框開發者選項的截圖（開發用）。
用這台電腦的真實 Windows 字型畫（不用 offscreen），視窗設成不顯示在螢幕上，畫面不會跳出來。
全部是假資料：設定檔、介面設定、金鑰庫都換到暫存資料夾；顯示卡、ffmpeg、streamlink、模型下載都是假的結果；
不連網、不下載、不碰真的認證管理員。

用法：  python scripts/引導截圖.py                 （縮放 100%，存到 測試素材/引導截圖/）
        python scripts/引導截圖.py --scale 1.5     （只截第 1 頁，檔名加 _150%）
        python scripts/引導截圖.py --sizes         （只印出 100%／125%／150% 縮放下各頁需要的大小，不截圖）"""
import argparse
import os
import shutil
import sys
import tempfile
import threading
import time

根 = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, 根)


def 系統縮放():
    """這台電腦 Windows 的顯示縮放（例如 1.5 = 150%）。"""
    import ctypes
    try:
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        return ctypes.windll.user32.GetDpiForSystem() / 96
    except (AttributeError, OSError):
        return 1.0


def 準備(scale):
    """scale：要模擬的 Windows 縮放（1 = 100%、1.25、1.5）；用 QT_SCALE_FACTOR 抵銷這台電腦本來的縮放。"""
    os.environ["QT_SCALE_FACTOR"] = str(scale / 系統縮放())
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyle("Fusion")

    import api_key
    import app as 主程式
    import config
    import first_run
    import llm
    import panel
    import startup_timeline
    import ui_state

    暫存 = tempfile.mkdtemp(prefix="引導截圖_")
    設定檔 = os.path.join(暫存, "config.json")
    shutil.copy2(os.path.join(根, "config.example.json"), 設定檔)
    config.設定檔路徑 = 設定檔
    ui_state.網址紀錄檔 = os.path.join(暫存, "網址紀錄.json")
    ui_state.介面設定檔 = os.path.join(暫存, "介面設定.json")
    panel.版面檔 = os.path.join(暫存, "版面配置.json")
    startup_timeline.紀錄.資料夾 = os.path.join(暫存, "logs")

    class 假金鑰庫:
        def __init__(self):
            self.資料 = {}

        def get_password(self, 服務, 帳號):
            return self.資料.get((服務, 帳號))

        def set_password(self, 服務, 帳號, 密碼):
            self.資料[(服務, 帳號)] = 密碼

        def delete_password(self, 服務, 帳號):
            self.資料.pop((服務, 帳號), None)
    api_key._後端 = 假金鑰庫()
    api_key._後端.set_password(api_key.認證服務名, "claude", "sk-ant-示範用假金鑰")    # 啟動面板截圖不出現「尚未設定」
    llm.測試連線 = lambda provider, 網址, 金鑰: (llm.測試成功, "連線成功，Claude 的金鑰有效。")
    first_run.已下載 = lambda 名稱: False
    first_run.顯示卡數 = lambda: 0
    first_run.找得到ffmpeg = lambda: True
    first_run.找得到streamlink = lambda: True

    app.setFont(主程式.選字型())
    app.setStyleSheet(主程式.樣式表)
    台 = 主程式.主控台()
    return app, 台, 暫存, Qt


def 等(app, 秒):
    from PySide6.QtCore import QCoreApplication, QEvent
    終 = time.time() + 秒
    while time.time() < 終:
        app.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)     # 真的事件迴圈會刪掉換下來的元件；這裡手動刪
        time.sleep(0.01)


def 存(w, 路徑):
    w.grab().save(路徑)
    print("已存：", os.path.relpath(路徑, 根))


def 做引導(台, 檢查=None):
    from PySide6.QtCore import Qt

    import onboarding
    引 = onboarding.首次引導(台, 檢查=檢查)
    引.背景測試 = False
    引.setAttribute(Qt.WA_DontShowOnScreen)
    引.show()
    return 引


def 印大小():
    import subprocess
    for s in (1, 1.25, 1.5):
        subprocess.run([sys.executable, __file__, "--_size", str(s)], check=False)      # noqa: S603  自己這支腳本


def 量(scale):
    app, 台, _, _Qt = 準備(scale)
    引 = 做引導(台)
    app.processEvents()
    寬, 高 = 引.width(), 引.height()
    print(f"縮放 {int(scale * 100)}%：引導視窗 {寬}×{高}（邏輯像素，實際 {round(寬 * scale)}×{round(高 * scale)} 像素），"
          f"需要 {引.需要的大小()}")
    for i, 頁 in enumerate(引.頁們):
        for 展開 in (False, True):
            頁.展開(展開)
            app.processEvents()
            版 = 頁.layout()
            要 = 版.totalHeightForWidth(頁.width()) if 版.hasHeightForWidth() else 版.totalSizeHint().height()
            print(f"  第 {i + 1} 頁{'（了解更多展開）' if 展開 else ''}：需要高 {要}，可用 {頁.height()}"
                  f"{'  ← 放不下！' if 要 > 頁.height() else ''}")
        頁.展開(False)
    區 = 引.區
    for w in (區.金鑰欄, 區.測試鈕, 區.眼睛鈕, 區.服務選, 區.模型選, 區.取得連結, 引.費用大字, 引.費用小字):
        if w.isVisible() and w.width() < w.minimumSizeHint().width():
            print("  ← 被截斷：", type(w).__name__, w.width(), "<", w.minimumSizeHint().width())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scale", type=float, default=1.0)
    ap.add_argument("--sizes", action="store_true")
    ap.add_argument("--_size", type=float, default=None)
    a = ap.parse_args()
    if a.sizes:
        return 印大小()
    if a._size:
        return 量(a._size)
    app, 台, 暫存, Qt = 準備(a.scale)
    import first_run
    出 = os.path.join(根, "測試素材", "引導截圖")
    os.makedirs(出, exist_ok=True)
    尾 = "" if a.scale == 1 else f"_{int(a.scale * 100)}%"

    # 第 1 頁：貼上（假的）金鑰、測試連線成功
    引 = 做引導(台)
    api_key = sys.modules["api_key"]
    api_key._後端.delete_password(api_key.認證服務名, "claude")      # 第 1 頁從「還沒有金鑰」開始，貼上後測試連線
    引.區.載入設定(sys.modules["config"].目前設定())
    引._更新金鑰標記()
    引.區.金鑰欄.setText("sk-ant-示範用假金鑰")
    引.區.測試連線()
    等(app, 0.3)
    存(引, os.path.join(出, f"引導_1_模型與金鑰{尾}.png"))
    if a.scale != 1:
        return

    # 第 2 頁：檢查中（假檢查卡住，等截完圖才放行）→ 檢查完成（有 ✓ 也有 ⚠）
    放行 = threading.Event()

    def 卡住(結果):
        def 做():
            放行.wait(10)
            return 結果
        return 做
    假檢查 = [("顯示卡", "NVIDIA 顯示卡", 卡住((first_run.檢查結果(first_run.注意, "沒有 NVIDIA 顯示卡：轉錄會比較慢，可能跟不上直播"), False))),
           ("ffmpeg", "ffmpeg", 卡住(first_run.檢查結果(first_run.好, "ffmpeg：可以處理直播聲音"))),
           ("streamlink", "streamlink", 卡住(first_run.檢查結果(first_run.好, "streamlink：可以連上直播")))]
    引2 = 做引導(台, 檢查=假檢查)
    引2.到(1, 動畫=False)
    等(app, 0.3)
    存(引2, os.path.join(出, "引導_2_檢查中.png"))
    放行.set()
    等(app, 0.5)
    存(引2, os.path.join(出, "引導_2_檢查完成.png"))
    引2.頁們[1].展開(True)
    等(app, 0.2)
    存(引2, os.path.join(出, "引導_了解更多展開.png"))
    引2.頁們[1].展開(False)
    引2.到(2, 動畫=False)
    等(app, 0.2)
    存(引2, os.path.join(出, "引導_3_開始使用.png"))

    # 啟動面板：下載轉錄模型（有進度）與取不到進度的樣子
    面 = 台.啟動面板
    面.setAttribute(Qt.WA_DontShowOnScreen)
    面.狀態.開始("檢查直播")
    面.網址框.setText("https://www.twitch.tv/demo_channel")
    面.下載.時鐘 = lambda: 1000.0
    面._收模型({"狀態": "將下載", "模型": "large-v3-turbo", "總": first_run.大小("large-v3-turbo"), "已": 0})
    面.下載.開始 = 1000.0 - 83
    面._收模型({"狀態": "下載中", "模型": "large-v3-turbo", "總": first_run.大小("large-v3-turbo"), "已": 812_000_000})
    面.收事件("files", {})
    面.show()
    等(app, 0.3)
    存(面, os.path.join(出, "啟動面板_下載中.png"))
    面._收模型({"狀態": "下載中", "模型": "自訂模型", "總": None, "已": 0})
    面.下載.開始 = 1000.0 - 27
    面._更新下載區()
    等(app, 0.3)
    存(面, os.path.join(出, "啟動面板_下載中_取不到進度.png"))
    面._收模型({"狀態": "失敗", "模型": "large-v3-turbo", "總": first_run.大小("large-v3-turbo"),
              "訊息": first_run.白話錯誤(ConnectionError("Connection refused"))})
    面.收事件("error", {"訊息": first_run.白話錯誤(ConnectionError("Connection refused"))})
    等(app, 0.3)
    存(面, os.path.join(出, "啟動面板_下載失敗.png"))
    面.hide()

    # 設定框：最下面的開發者選項（展開、已勾選）
    台.開設定框()
    框 = 台.設定框
    框.hide()
    框.setAttribute(Qt.WA_DontShowOnScreen)
    框.resize(框.width(), 620)
    框.show()
    框.頁.展開開發者(True)
    框.頁.文字稿勾.setChecked(True)
    等(app, 0.3)
    框.頁.verticalScrollBar().setValue(框.頁.verticalScrollBar().maximum())
    等(app, 0.3)
    存(框, os.path.join(出, "設定框_開發者選項.png"))
    shutil.rmtree(暫存, ignore_errors=True)


if __name__ == "__main__":
    main()
