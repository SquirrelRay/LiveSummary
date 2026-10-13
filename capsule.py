# 浮動膠囊與系統匣圖示（新介面第二階段第一步）
#   膠囊：小小的膠囊形狀視窗，無邊框、永遠在最上層（沿用面板的置頂規則：只有前景是全螢幕程式才重新拉上來，
#         不蓋截圖工具等系統視窗），永遠不穿透。平常半透明，滑鼠移上去變清楚，離開後慢慢變回半透明。
#         可拖曳，放開時吸附到最近的螢幕邊緣；位置記在 介面設定.json，開啟時超出螢幕就移回。
#         點一下展開選單；滑鼠停著顯示直播時間、轉錄狀態、呼叫次數、估算費用。
#   狀態燈：灰＝尚未開始、綠＝擷取中且轉錄跟得上、黃＝轉錄跟不上、紅＝發生錯誤、閃爍＝正在收尾整理。
#   系統匣：右下角圖示（顏色跟著狀態燈），右鍵選單和膠囊選單相同，另外多「重設膠囊位置」。
#   語言警告：自動偵測語言不確定或失敗時，膠囊上多一段黃色「⚠ 語言」（燈色不變，燈色只代表擷取狀態），
#         膠囊旁跳出約 8 秒的提示泡；重新偵測成功或這一場結束就消失。
#   錯誤提示：直播中途的錯誤、config.json 的警告，也用同一個提示泡顯示在膠囊旁（主控台常收著看不到）。
# 膠囊不另外跑引擎，也不改主控台的行為：停止、結束都直接呼叫主控台原本的停止與關閉流程。

from PySide6.QtCore import Qt, QTimer, QPoint, QRect, QObject, QPropertyAnimation, QEvent
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPixmap, QIcon, QCursor, QGuiApplication
from PySide6.QtWidgets import QApplication, QWidget, QLabel, QMenu, QMessageBox, QSystemTrayIcon, QToolTip

import overlay          # 置頂規則（Windows 原生）
import panel            # 面板選單（直接重用 建立面板選單）
import ui_state         # 膠囊位置
import config
import stream_clock     # 滑鼠提示裡跳動的直播時間

灰, 綠, 黃, 紅 = "#8a91a5", "#3ecf8e", "#f5b84a", "#ff5c7a"
狀態們 = {    # 狀態 → (燈色, 文字)
    "未開始": (灰, "尚未開始"),
    "擷取中": (綠, "擷取中"),
    "跟不上": (黃, "轉錄跟不上"),
    "錯誤": (紅, "發生錯誤"),
    "收尾": (黃, "正在收尾整理"),
}
半透明, 不透明 = 0.5, 1.0
高 = 30
吸附距離 = 0          # 吸附後離螢幕邊緣幾像素


def 確認(父, 標題, 文字):
    """跳出「是／否」確認框，回傳 True = 確定。（測試時可以換掉）"""
    框 = QMessageBox(QMessageBox.Question, 標題, 文字, QMessageBox.Yes | QMessageBox.No, None)    # 不掛在膠囊上：放螢幕中間，不會被膠囊擋住
    框.button(QMessageBox.Yes).setText("確定")
    框.button(QMessageBox.No).setText("取消")
    框.setDefaultButton(QMessageBox.No)
    框.setWindowFlag(Qt.WindowStaysOnTopHint, True)
    if 父 is not None:                     # 放在膠囊所在螢幕的正中間
        框.adjustSize()
        框.move(父.screen().availableGeometry().center() - 框.rect().center())
    return 框.exec() == QMessageBox.Yes


def 寫設定(鍵, 值):
    """只改 config.json 的一個欄位，其他欄位原樣保留（備份、原子寫入都由 config.寫入設定 負責）。成功回傳 True。"""
    try:
        config.寫入設定({鍵: 值})
        return True
    except Exception:
        return False


class 膠囊(QWidget):
    def __init__(self, 管):
        super().__init__(None, Qt.FramelessWindowHint | Qt.Tool)
        self.管 = 管
        self.setWindowTitle("直播摘要 膠囊")
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_AlwaysShowToolTips)       # 主控台不在前景時也顯示提示
        self.setCursor(Qt.PointingHandCursor)
        f = QFont(QApplication.font())
        f.setPixelSize(13)
        f.setBold(True)
        self.setFont(f)
        self.燈亮 = True              # 閃爍用
        self.懸停 = False
        self._按下 = None             # (按下的全域點, 當時視窗左上角)
        self._拖了 = False
        self.setWindowOpacity(半透明)
        self.動畫 = QPropertyAnimation(self, b"windowOpacity", self)
        self.置頂計時 = QTimer(self, interval=500, timeout=self._保持置頂)
        self.游標位置 = QCursor.pos  # 測試時可以換掉
        self.懸停計時 = QTimer(self, interval=80, timeout=self._看懸停)
        self.調整大小()

    # ---------- 外觀 ----------
    def 用量字(self):
        return self.管.用量短字() if self.管.顯示用量 else ""

    def 文字段們(self):
        """燈與三個點右邊的文字：[(文字, 顏色)]。語言警告（黃）在前，用量在後。"""
        段們 = []
        if self.管.語言警示():
            段們.append(("⚠ 語言", 黃))
        if self.用量字():
            段們.append((self.用量字(), "#e7e9ef"))
        return 段們

    def 調整大小(self):
        量 = QFontMetrics(self.font())
        段們 = self.文字段們()
        寬 = 44 + sum(量.horizontalAdvance(字) + 10 for 字, _ in 段們)
        if (寬, 高) != (self.width(), self.height()):
            舊右 = self.geometry().right()
            靠右 = self.isVisible() and self._靠右邊()
            self.setFixedSize(寬, 高)
            if 靠右:                      # 吸在右邊時，變寬往左長，不會跑出螢幕
                self.move(舊右 - 寬 + 1, self.y())
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = self.rect().adjusted(1, 1, -1, -1)
        p.setPen(QColor(139, 108, 255, 230) if self.懸停 or self.管.選單開著 else QColor(255, 255, 255, 40))
        p.setBrush(QColor(22, 25, 32, 240))
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        色 = QColor(狀態們[self.管.狀態][0])
        if self.管.狀態 == "收尾" and not self.燈亮:
            色.setAlpha(50)
        p.setPen(Qt.NoPen)
        p.setBrush(色)
        p.drawEllipse(QPoint(15, self.height() // 2), 6, 6)
        p.setBrush(QColor(231, 233, 239, 200))       # 三個小點 = 點一下有選單
        for i in range(3):
            p.drawEllipse(QPoint(29 + i * 4, self.height() // 2), 1, 1)
        x = 42
        for 字, 字色 in self.文字段們():
            p.setPen(QColor(字色))
            p.drawText(QRect(x, 0, self.width() - x, self.height()), Qt.AlignVCenter | Qt.AlignLeft, 字)
            x += QFontMetrics(self.font()).horizontalAdvance(字) + 10

    # ---------- 半透明 ↔ 清楚 ----------
    def _動到(self, 目標, 毫秒):
        if self.動畫.endValue() == 目標 and self.動畫.state() == QPropertyAnimation.Running:
            return
        if abs(self.windowOpacity() - 目標) < 0.01:
            return
        self.動畫.stop()
        self.動畫.setDuration(毫秒)
        self.動畫.setStartValue(self.windowOpacity())
        self.動畫.setEndValue(目標)
        self.動畫.start()

    def _看懸停(self):
        在上面 = self.isVisible() and self.frameGeometry().contains(self.游標位置())
        if 在上面 != self.懸停:
            self.懸停 = 在上面
            self.update()
        if 在上面 or self.管.選單開著 or self._按下:
            self._動到(不透明, 150)          # 移上去很快變清楚
        else:
            self._動到(半透明, 900)          # 離開後慢慢變回半透明

    # ---------- 置頂（和面板同一套規則）----------
    def _套置頂(self):
        h = int(self.winId())
        樣式 = overlay.user32.GetWindowLongPtrW(h, overlay.GWL_EXSTYLE)
        if 樣式 & overlay.WS_EX_TRANSPARENT:          # 永遠不穿透
            overlay.user32.SetWindowLongPtrW(h, overlay.GWL_EXSTYLE, 樣式 & ~overlay.WS_EX_TRANSPARENT)
        overlay.user32.SetWindowPos(h, overlay.HWND_TOPMOST, 0, 0, 0, 0, overlay.SWP_旗標)

    def _保持置頂(self):
        """每 0.5 秒檢查一次：
        1. 前景是全螢幕程式 → 拉到最上層（和以前一樣；面板拉上來時會排在膠囊下面，不會互搶）。
           截圖工具、工作管理員、開始選單等系統視窗不算全螢幕程式，不去蓋它們。
        2. 否則只在有面板蓋在膠囊上面時（例如剛點過、拖過面板）才動：移到最高那個面板的正上方
           （不跳過截圖畫面等其他置頂視窗）。沒被蓋就完全不動前後順序。"""
        if not self.isVisible():
            return
        h = int(self.winId())
        if overlay.前景是全螢幕程式():
            overlay.user32.SetWindowPos(h, overlay.HWND_TOPMOST, 0, 0, 0, 0, overlay.SWP_旗標)
            return
        蓋著 = overlay.在上方的(h, self.管.面板視窗們())
        if 蓋著:
            上 = overlay.上方視窗(蓋著[-1])
            overlay.user32.SetWindowPos(h, 上 or overlay.HWND_TOPMOST, 0, 0, 0, 0, overlay.SWP_旗標)

    def 視窗旗標(self):
        """測試用：(是否置頂, 是否穿透)。"""
        樣式 = overlay.user32.GetWindowLongPtrW(int(self.winId()), overlay.GWL_EXSTYLE)
        return bool(樣式 & panel.WS_EX_TOPMOST), bool(樣式 & overlay.WS_EX_TRANSPARENT)

    # ---------- 位置 ----------
    def 預設位置(self):
        g = QGuiApplication.primaryScreen().availableGeometry()
        return QPoint(g.right() - self.width() + 1 - 吸附距離, g.y() + g.height() // 3)

    def _所在螢幕(self, 框=None):
        框 = 框 or self.frameGeometry()
        中 = 框.center()
        for sc in QGuiApplication.screens():
            if sc.availableGeometry().contains(中):
                return sc.availableGeometry()
        def 重疊(sc):
            r = sc.availableGeometry().intersected(框)
            return r.width() * r.height() if r.isValid() else 0
        最好 = max(QGuiApplication.screens(), key=重疊)
        return (最好 if 重疊(最好) > 0 else QGuiApplication.primaryScreen()).availableGeometry()

    def _靠右邊(self):
        g = self._所在螢幕()
        return abs(self.frameGeometry().right() - g.right()) <= 吸附距離 + 2

    def 移回畫面內(self, 點):
        """點（左上角）放不進任何螢幕就移回：整個膠囊都要在某個螢幕的可用範圍內。"""
        框 = QRect(點, self.size())
        for sc in QGuiApplication.screens():
            if sc.availableGeometry().contains(框):
                return 點
        g = self._所在螢幕(框)
        return QPoint(min(max(點.x(), g.x()), g.right() - self.width() + 1),
                      min(max(點.y(), g.y()), g.bottom() - self.height() + 1))

    def 吸附(self):
        """放開時吸到最近的螢幕邊緣（上下左右四邊選最近的一邊），並確保在螢幕內。"""
        g = self._所在螢幕()
        x, y = self.x(), self.y()
        距 = {"左": x - g.x(), "右": g.right() - (x + self.width() - 1),
             "上": y - g.y(), "下": g.bottom() - (y + self.height() - 1)}
        邊 = min(距, key=lambda k: abs(距[k]))
        if 邊 == "左":
            x = g.x() + 吸附距離
        elif 邊 == "右":
            x = g.right() - self.width() + 1 - 吸附距離
        elif 邊 == "上":
            y = g.y() + 吸附距離
        else:
            y = g.bottom() - self.height() + 1 - 吸附距離
        x = min(max(x, g.x()), g.right() - self.width() + 1)
        y = min(max(y, g.y()), g.bottom() - self.height() + 1)
        self.move(x, y)
        return 邊

    def 還原位置(self):
        位 = ui_state.讀膠囊位置()
        點 = QPoint(*位) if 位 else self.預設位置()
        self.move(self.移回畫面內(點))

    def 存位置(self):
        ui_state.存膠囊位置((self.x(), self.y()))

    def 重設位置(self):
        self.move(self.預設位置())
        self.存位置()

    # ---------- 滑鼠提示：開著時每秒更新（直播時間會跳）----------
    def event(self, e):
        if e.type() == QEvent.ToolTip:
            self.管.顯示提示(e.globalPos())
            return True
        return super().event(e)

    # ---------- 滑鼠：拖曳 / 點一下 ----------
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._按下 = (e.globalPosition().toPoint(), self.pos())
            self._拖了 = False

    def mouseMoveEvent(self, e):
        if not self._按下:
            return
        起點, 原位 = self._按下
        差 = e.globalPosition().toPoint() - 起點
        if not self._拖了 and 差.manhattanLength() < 5:      # 動一點點不算拖曳（算點一下）
            return
        self._拖了 = True
        self.move(原位 + 差)

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.LeftButton or not self._按下:
            return
        self._按下 = None
        if self._拖了:
            self.吸附()
            self.存位置()
        else:
            self.管.開選單()

    # ---------- 顯示 ----------
    def 顯示(self):
        self.還原位置()
        self.show()
        self._套置頂()
        self.置頂計時.start()
        self.懸停計時.start()

    def 收掉(self):
        self.置頂計時.stop()
        self.懸停計時.stop()
        self.close()


class 提示泡(QLabel):
    """膠囊旁的小提示（例如「已結束」）：不搶焦點、滑鼠點擊穿過，幾秒後自動消失。"""

    def __init__(self):
        super().__init__(None, Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint | Qt.WindowTransparentForInput)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setWindowTitle("直播摘要 提示")
        self.setStyleSheet("QLabel { background: transparent; color: #ffffff; border: none; padding: 7px 14px;"
                           " font-size: 14px; font-weight: 700; }")
        self.計時 = QTimer(self, singleShot=True, timeout=self.hide)
        self.置頂計時 = QTimer(self, interval=150, timeout=self._置頂)
        self.錯誤 = False
        self.setMaximumWidth(420)
        self.setWordWrap(True)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QColor(紅 if self.錯誤 else 黃 if self.錯誤 is None else "#8b6cff"))
        p.setBrush(QColor(29, 32, 41))
        p.drawRoundedRect(self.rect().adjusted(0, 0, -1, -1), 10, 10)
        p.end()
        super().paintEvent(e)

    def 顯示(self, 字, 膠, 秒, 錯誤=False):
        """錯誤：False = 一般（紫框）、True = 錯誤（紅框）、None = 警告（黃框）。"""
        self.錯誤 = 錯誤
        self.setText(字)
        self.adjustSize()
        g, 螢 = 膠.frameGeometry(), 膠._所在螢幕()
        x = g.left() - self.width() - 6 if g.center().x() > 螢.center().x() else g.right() + 6    # 往螢幕內側放
        y = g.center().y() - self.height() // 2
        if not 膠.isVisible():
            x, y = 螢.right() - self.width() - 20, 螢.bottom() - self.height() - 20
        self.move(min(max(x, 螢.x()), 螢.right() - self.width()), min(max(y, 螢.y()), 螢.bottom() - self.height()))
        self.show()
        self.raise_()
        # 面板、膠囊在前景是全螢幕程式時會每 0.5 秒把自己拉到最上層；提示顯示的這幾秒也一直拉自己到最上層，才不會被蓋住
        self.update()
        self.置頂計時.start()
        self.計時.start(int(秒 * 1000))

    置頂計時 = None

    def _置頂(self):
        if self.isVisible():
            overlay.user32.SetWindowPos(int(self.winId()), overlay.HWND_TOPMOST, 0, 0, 0, 0, overlay.SWP_旗標)
        else:
            self.置頂計時.stop()


class 系統匣(QSystemTrayIcon):
    def __init__(self, 管):
        super().__init__(管)
        self.管 = 管
        self.選單 = QMenu()
        self.選單.setStyleSheet(panel.選單樣式)
        self.選單.aboutToShow.connect(lambda: 管.填選單(self.選單, 含重設=True))
        self.setContextMenu(self.選單)
        self.更新()

    def 更新(self):
        色, 字 = 狀態們[self.管.狀態]
        圖 = QPixmap(32, 32)
        圖.fill(Qt.transparent)
        p = QPainter(圖)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(22, 25, 32))
        p.drawRoundedRect(1, 6, 30, 20, 10, 10)
        c = QColor(色)
        if self.管.狀態 == "收尾" and not self.管.膠囊.燈亮:
            c.setAlpha(60)
        p.setBrush(c)
        p.drawEllipse(QPoint(16, 16), 7, 7)
        p.end()
        self.setIcon(QIcon(圖))
        語言 = self.管.語言字()
        self.setToolTip("直播摘要：" + 字 + (("\n" + ("⚠ " if self.管.語言警示() else "") + 語言) if 語言 else ""))


class 膠囊管理(QObject):
    """狀態、選單、膠囊與系統匣的共同管理者。狀態由主控台的事件與執行狀態決定。"""

    def __init__(self, 台):
        super().__init__(台)
        self.台 = 台
        self.狀態 = "未開始"
        self.跟上 = None
        self.出錯 = False
        self.費用 = 0.0              # 摘要估算費用（None = 無法計算）
        self.翻譯費用 = 0.0          # 翻譯估算費用（None = 無法計算）
        self.聊天翻譯費用 = 0.0      # 聊天室翻譯估算費用（None = 無法計算）
        self.面板子選單 = {}         # 每個選單各自一份「面板」子選單（建立一次，每次顯示前自己重新填）
        self._匣狀態 = None          # 系統匣上次畫的 (狀態, 語言字, 語言警示)，變了才重畫
        self.選單開著 = False
        self._執行中 = False
        self.顯示用量 = bool(config.目前設定()["capsule_show_usage"])
        self.膠囊 = 膠囊(self)
        self.選單 = QMenu()
        self.選單.setStyleSheet(panel.選單樣式)
        self.選單.aboutToShow.connect(lambda: self.填選單(self.選單))
        self.選單.aboutToHide.connect(self._選單關了)
        self.系統匣 = 系統匣(self)
        台.橋.收到.connect(self.收事件)        # 和主控台同一條事件
        self.計時 = QTimer(self, interval=150, timeout=self.更新)
        self.閃計時 = QTimer(self, interval=450, timeout=self._閃)
        self.提示計時 = QTimer(self, interval=1000, timeout=self._刷新提示)     # 只在膠囊的滑鼠提示開著時跑

    # ---------- 顯示 / 收掉 ----------
    def 顯示(self):
        self.更新()
        self.膠囊.顯示()
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.系統匣.show()
        self.計時.start()

    def 收掉(self):
        self.計時.stop()
        self.閃計時.stop()
        self.提示計時.stop()
        self.選單.close()
        self.系統匣.hide()
        self.膠囊.收掉()

    # ---------- 狀態 ----------
    def 收事件(self, 種類, 內容):
        if 種類 == "status":
            if "跟上" in 內容:
                self.跟上 = 內容["跟上"]
            if "次數" in 內容:
                self.費用 = 內容["費用"]
            if "翻譯費用" in 內容:
                self.翻譯費用 = 內容["翻譯費用"]
            if "聊天翻譯費用" in 內容:
                self.聊天翻譯費用 = 內容["聊天翻譯費用"]
        elif 種類 == "error":
            self.出錯 = True
        self.更新()

    def 計算狀態(self):
        台 = self.台
        if 台.結束中:
            return "收尾"
        if 台.執行中():
            return "錯誤" if self.出錯 else "跟不上" if self.跟上 is False else "擷取中"
        return "錯誤" if self.出錯 else "未開始"

    def 更新(self):
        執行中 = self.台.執行中()
        if 執行中 and not self._執行中:          # 新的一場開始：清掉上一場的錯誤與用量
            self.出錯, self.跟上, self.費用, self.翻譯費用, self.聊天翻譯費用 = False, None, 0.0, 0.0, 0.0
        self._執行中 = 執行中
        新 = self.計算狀態()
        if 新 == "收尾" and not self.閃計時.isActive():
            self.膠囊.燈亮 = True
            self.閃計時.start()
        elif 新 != "收尾" and self.閃計時.isActive():
            self.閃計時.stop()
            self.膠囊.燈亮 = True
        self.狀態 = 新
        self.膠囊.setToolTip(self.提示文字())
        self.膠囊.調整大小()
        匣 = (新, self.語言字(), self.語言警示())
        if 匣 != self._匣狀態:
            self._匣狀態 = 匣
            self.系統匣.更新()

    def _閃(self):
        self.膠囊.燈亮 = not self.膠囊.燈亮
        self.膠囊.update()
        self.系統匣.更新()

    def 面板視窗們(self):
        """目前開著的面板的視窗代號（膠囊要一直在它們上面）。"""
        面板 = getattr(self.台, "面板", None)
        return [int(面.winId()) for 面 in (面板.面板們.values() if 面板 else []) if 面.isVisible()]

    def 語言警示(self):
        """這一場進行中、而且自動偵測語言不確定或失敗。停止後（語言狀態回到閒置）一定是 False，不會殘留。"""
        s = self.台.語言狀態
        return s.顯示中() and s.有警示()

    def 語言字(self):
        s = self.台.語言狀態
        return s.文字() if s.顯示中() else ""

    def 總費用(self):
        if self.費用 is None or self.翻譯費用 is None or self.聊天翻譯費用 is None:
            return None
        return (self.費用 or 0.0) + (self.翻譯費用 or 0.0) + (self.聊天翻譯費用 or 0.0)

    def 用量短字(self):
        總 = self.總費用()
        return "$—" if 總 is None else f"${總:.2f}"

    def 時間字(self):
        """滑鼠提示的直播時間：直播中用直播時鐘算「現在」（每秒都會變）；沒在直播、收尾中、還算不出來就用狀態列藥丸的字。"""
        台 = self.台
        軸 = stream_clock.目前()
        if 台.執行中() and not 台.結束中 and 軸 is not None:
            秒 = 軸.現在直播秒()
            if 秒 is not None:
                return 台._時間藥丸字(軸.字(秒))
        return 台.時間藥丸.text()

    def 提示文字(self):
        台 = self.台
        行們 = ["直播摘要：" + 狀態們[self.狀態][1],
              self.時間字(), 台.轉錄藥丸.text(), "摘要：" + 台.費用藥丸.text(), 台.翻譯藥丸.text(),
              *([台.聊天翻譯藥丸.text()] if not 台.聊天翻譯藥丸.isHidden() else []),
              "（金額為估算，實際以 API 帳單為準）"]
        if self.語言字():
            行們.insert(1, ("⚠ " if self.語言警示() else "") + self.語言字())
        資 = 台.直播資訊          # 直播主、標題、分類只顯示在這裡（不放狀態列、不送給模型）
        if 資:
            行們[1:1] = [f"{名}：{資[鍵]}" for 名, 鍵 in (("直播主", "直播主"), ("標題", "標題"), ("分類", "遊戲")) if 資.get(鍵)]
        return "\n".join(行們)

    def 顯示提示(self, 點):
        """滑鼠停在膠囊上（Qt 的 ToolTip 事件）：顯示提示，並開始每秒更新。"""
        QToolTip.showText(點, self.提示文字(), self.膠囊)
        self.提示計時.start()

    def 提示開著(self):
        """膠囊的提示還開著：提示框可見、而且滑鼠還在膠囊上。"""
        膠 = self.膠囊
        return QToolTip.isVisible() and 膠.isVisible() and 膠.frameGeometry().contains(膠.游標位置())

    def _刷新提示(self):
        """每秒一次：提示關了（或滑鼠離開）就停掉計時器，不在背景空跑；還開著就換成最新的文字。"""
        if not self.提示開著():
            self.提示計時.stop()
            return
        QToolTip.showText(self.膠囊.游標位置(), self.提示文字(), self.膠囊)

    # ---------- 選單 ----------
    def 開選單(self):
        self.選單開著 = True
        self.膠囊.update()
        g = self.膠囊.frameGeometry()
        self.選單.adjustSize()
        螢 = self.膠囊._所在螢幕()
        寬, 選高 = self.選單.sizeHint().width(), self.選單.sizeHint().height()
        x = g.right() - 寬 if g.center().x() > 螢.center().x() else g.left()       # 往螢幕內側展開
        y = g.bottom() + 4 if g.bottom() + 4 + 選高 <= 螢.bottom() else g.top() - 選高 - 4
        self.選單.popup(QPoint(max(螢.x(), x), max(螢.y(), y)))

    def _選單關了(self):
        self.選單開著 = False
        self.膠囊.update()

    def 填選單(self, 選單, 含重設=False):
        台 = self.台
        選單.clear()
        if not 台.執行中() and not 台.結束中:          # 閒置時才有「開始…」（打開啟動面板）
            選單.addAction("開始…").triggered.connect(台.啟動面板.顯示)
        a = 選單.addAction("停止")
        a.setEnabled(台.執行中() and not 台.結束中)
        a.triggered.connect(self.問停止)
        if 台.語言狀態.顯示中():                      # 語言兩項固定放在這裡（開始…／停止下方的第一組）
            選單.addSeparator()
            a = 選單.addAction(("⚠ " if self.語言警示() else "") + 台.語言狀態.文字())    # 目前語言（只是顯示）
            a.setEnabled(False)
            if 台.語言狀態.顯示按鈕():
                a = 選單.addAction("重新偵測語言")
                a.setEnabled(台.語言狀態.可重新偵測())
                a.triggered.connect(台.重新偵測語言)
        選單.addSeparator()
        子 = self.面板子選單.get(id(選單))
        if 子 is None:
            子 = panel.建立面板選單(台.面板, None)      # 直接重用主控台的「面板」選單
            子.setTitle("面板")
            self.面板子選單[id(選單)] = 子
        選單.addMenu(子)
        開 = 台.聊天翻譯器.開啟
        a = 選單.addAction("聊天室翻譯：" + ("開" if 開 else "關"))      # 當場生效；外語直播且聊天室面板開著才會翻
        a.setCheckable(True)
        a.setChecked(開)
        a.setToolTip("外語直播時把聊天室留言翻成繁體中文（聊天室面板要開著）；另外計費")
        a.toggled.connect(台.設聊天翻譯)
        時 = 選單.addMenu("時間顯示")          # 摘要卡片的時間；當場生效，並寫回 config.json
        for 名, 值 in (("直播時間", "stream"), ("幾分鐘前", "ago")):
            a = 時.addAction(名)
            a.setCheckable(True)
            a.setChecked(台.時間顯示 == 值)
            a.triggered.connect(lambda _=False, 值=值: 台.設時間顯示(值))
        if 台.直播資訊 and not 台.直播資訊["有開播"]:
            a = 時.addAction("（這一場抓不到開播時間，摘要卡片一律顯示幾分鐘前）")
            a.setEnabled(False)
        a = 選單.addAction("顯示用量")
        a.setCheckable(True)
        a.setChecked(self.顯示用量)
        a.toggled.connect(self.設顯示用量)
        選單.addAction("設定").triggered.connect(台.開設定框)
        選單.addAction("顯示主控台").triggered.connect(self.顯示主控台)
        if 含重設:
            選單.addAction("重設膠囊位置").triggered.connect(self.膠囊.重設位置)
        選單.addSeparator()
        選單.addAction("結束程式").triggered.connect(self.結束程式)

    # ---------- 動作 ----------
    def 問停止(self):
        台 = self.台
        if not 台.執行中() or 台.結束中:
            return
        if 確認(self.膠囊, "停止", "確定要停止嗎？"):
            if 台.執行中() and not 台.結束中:
                台.停止()                    # 和主控台的「停止」完全相同（含收尾翻譯與整理最後話題）

    def 設顯示用量(self, 開):
        self.顯示用量 = bool(開)
        寫設定("capsule_show_usage", self.顯示用量)
        self.膠囊.調整大小()

    def 顯示主控台(self):
        台 = self.台
        if 台.isMinimized():
            台.showNormal()
        台.show()
        台.raise_()
        台.activateWindow()
        overlay.user32.SetForegroundWindow(int(台.winId()))

    def 結束程式(self):
        台 = self.台
        if 台.執行中() and not 確認(self.膠囊, "結束程式", "直播進行中，確定要停止並結束程式嗎？\n（會照原本的流程整理最後一個話題後再關閉）"):
            return
        台.要結束 = True        # 關主控台平常只是收起；這裡才真的結束
        台.close()              # 執行中會先乾淨收尾，完成後自動關閉

    # ---------- 膠囊旁的小提示（幾秒後自動消失）----------
    def 小提示(self, 字, 秒=4, 錯誤=False):
        if not hasattr(self, "提示泡"):
            self.提示泡 = 提示泡()
        self.提示泡.顯示(字, self.膠囊, 秒, 錯誤)

    def 錯誤提示(self, 字, 秒=12):
        """直播中途的錯誤、config.json 的警告：紅框提示泡（主控台的提示層照舊也有）。"""
        self.小提示(字, 秒, 錯誤=True)

    def 語言警告提示(self):
        """自動偵測語言不確定或失敗：膠囊旁黃框提示約 8 秒，並立刻更新膠囊上的「⚠ 語言」。"""
        self.更新()
        if not self.語言警示():
            return
        字 = "⚠ " + self.台.語言狀態.文字()
        if self.台.語言狀態.顯示按鈕():
            字 += "\n點膠囊打開選單，可「重新偵測語言」"
        self.小提示(字, 8, 錯誤=None)
