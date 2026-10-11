# 浮動膠囊與系統匣圖示（新介面第二階段第一步）
#   膠囊：小小的膠囊形狀視窗，無邊框、永遠在最上層（沿用面板的置頂規則：只有前景是全螢幕程式才重新拉上來，
#         不蓋截圖工具等系統視窗），永遠不穿透。平常半透明，滑鼠移上去變清楚，離開後慢慢變回半透明。
#         可拖曳，放開時吸附到最近的螢幕邊緣；位置記在 介面設定.json，開啟時超出螢幕就移回。
#         點一下展開選單；滑鼠停著顯示直播時間、轉錄狀態、呼叫次數、估算費用。
#   狀態燈：灰＝尚未開始、綠＝擷取中且轉錄跟得上、黃＝轉錄跟不上、紅＝發生錯誤、閃爍＝正在收尾整理。
#   系統匣：右下角圖示（顏色跟著狀態燈），右鍵選單和膠囊選單相同，另外多「重設膠囊位置」。
# 膠囊不另外跑引擎，也不改主控台的行為：停止、結束都直接呼叫主控台原本的停止與關閉流程。
import json

from PySide6.QtCore import Qt, QTimer, QPoint, QRect, QObject, QPropertyAnimation
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPixmap, QIcon, QCursor, QGuiApplication
from PySide6.QtWidgets import QApplication, QWidget, QLabel, QMenu, QMessageBox, QSystemTrayIcon

import overlay          # 置頂規則（Windows 原生）
import panel            # 面板選單（直接重用 建立面板選單）
import ui_state         # 膠囊位置
import live_topics

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
    """只改 config.json 的一個欄位，其他欄位原樣保留。"""
    路徑 = live_topics.設定檔路徑
    try:
        with open(路徑, encoding="utf-8-sig") as f:
            內容 = json.load(f)
        if not isinstance(內容, dict):
            return False
        內容[鍵] = 值
        with open(路徑, "w", encoding="utf-8") as f:
            json.dump(內容, f, ensure_ascii=False, indent=2)
            f.write("\n")
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

    def 調整大小(self):
        字 = self.用量字()
        寬 = 44 + (QFontMetrics(self.font()).horizontalAdvance(字) + 10 if 字 else 0)
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
        字 = self.用量字()
        if 字:
            p.setPen(QColor(231, 233, 239))
            p.drawText(QRect(42, 0, self.width() - 48, self.height()), Qt.AlignVCenter | Qt.AlignLeft, 字)

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
        """只有前景是全螢幕程式才重新拉到最上層；截圖工具、工作管理員、開始選單等系統視窗出現時不去蓋它們。"""
        if self.isVisible() and overlay.前景是全螢幕程式():
            overlay.user32.SetWindowPos(int(self.winId()), overlay.HWND_TOPMOST, 0, 0, 0, 0, overlay.SWP_旗標)

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

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QColor(139, 108, 255))
        p.setBrush(QColor(29, 32, 41))
        p.drawRoundedRect(self.rect().adjusted(0, 0, -1, -1), 10, 10)
        p.end()
        super().paintEvent(e)

    def 顯示(self, 字, 膠, 秒):
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
        self.setToolTip("直播摘要：" + 字)


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
        self.面板子選單 = {}         # 每個選單各自一份「面板」子選單（建立一次，每次顯示前自己重新填）
        self.選單開著 = False
        self._執行中 = False
        self.顯示用量 = bool(live_topics.載入設定({})[0]["capsule_show_usage"])
        self.膠囊 = 膠囊(self)
        self.選單 = QMenu()
        self.選單.setStyleSheet(panel.選單樣式)
        self.選單.aboutToShow.connect(lambda: self.填選單(self.選單))
        self.選單.aboutToHide.connect(self._選單關了)
        self.系統匣 = 系統匣(self)
        台.橋.收到.connect(self.收事件)        # 和主控台同一條事件
        self.計時 = QTimer(self, interval=150, timeout=self.更新)
        self.閃計時 = QTimer(self, interval=450, timeout=self._閃)

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
            self.出錯, self.跟上, self.費用, self.翻譯費用 = False, None, 0.0, 0.0
        self._執行中 = 執行中
        新 = self.計算狀態()
        if 新 == "收尾" and not self.閃計時.isActive():
            self.膠囊.燈亮 = True
            self.閃計時.start()
        elif 新 != "收尾" and self.閃計時.isActive():
            self.閃計時.stop()
            self.膠囊.燈亮 = True
        變了 = 新 != self.狀態
        self.狀態 = 新
        self.膠囊.setToolTip(self.提示文字())
        self.膠囊.調整大小()
        if 變了:
            self.系統匣.更新()

    def _閃(self):
        self.膠囊.燈亮 = not self.膠囊.燈亮
        self.膠囊.update()
        self.系統匣.更新()

    def 總費用(self):
        if self.費用 is None or self.翻譯費用 is None:
            return None
        return (self.費用 or 0.0) + (self.翻譯費用 or 0.0)

    def 用量短字(self):
        總 = self.總費用()
        return "$—" if 總 is None else f"${總:.2f}"

    def 提示文字(self):
        台 = self.台
        行們 = ["直播摘要：" + 狀態們[self.狀態][1],
              台.時間藥丸.text(), 台.轉錄藥丸.text(), "摘要：" + 台.費用藥丸.text(), 台.翻譯藥丸.text(),
              "（費用依 config.json 的單價估算，單價未查證）"]
        return "\n".join(行們)

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
        子 = self.面板子選單.get(id(選單))
        if 子 is None:
            子 = panel.建立面板選單(台.面板, None)      # 直接重用主控台的「面板」選單
            子.setTitle("面板")
            self.面板子選單[id(選單)] = 子
        選單.addMenu(子)
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
    def 小提示(self, 字, 秒=4):
        if not hasattr(self, "提示泡"):
            self.提示泡 = 提示泡()
        self.提示泡.顯示(字, self.膠囊, 秒)
