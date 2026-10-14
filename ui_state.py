# 介面的本機記憶（只存在這台電腦，不進 git）：
#   網址紀錄.json  最近用過的直播網址（可釘選、可刪除）
#   介面設定.json  並排欄數與每欄選的分頁
# 介面設定.json 另外記著浮動膠囊的位置、設定框的大小等小旗標（舊版留下的「精簡」欄位不再讀取，留著無妨）。兩個檔案壞了或讀不出來都不會讓程式出錯，當成沒有紀錄。
import os
import re
import json
import time
from urllib.parse import urlparse, parse_qs, unquote

import app_paths

網址紀錄檔 = app_paths.網址紀錄檔()      # 位置見 app_paths（%LOCALAPPDATA%\LiveSummary）
介面設定檔 = app_paths.介面設定檔()
最近上限 = 10         # 沒釘選的網址最多留幾個（釘選的不算）


def 頻道名(網址):
    """從網址取出頻道名稱：twitch.tv/名稱 → 名稱；youtube 的 @名稱／影片 → @名稱／影片 ID；其他取最後一段路徑或網域。"""
    try:
        p = urlparse(網址 if "://" in 網址 else "https://" + 網址)
    except Exception:
        return 網址
    主機 = (p.hostname or "").lower().removeprefix("www.").removeprefix("m.")
    段 = [unquote(s) for s in p.path.split("/") if s]
    if 主機.endswith("twitch.tv") and 段:
        return 段[1] if 段[0] == "videos" and len(段) > 1 else 段[0]
    if 主機.endswith("youtube.com") or 主機 == "youtu.be":
        if 段 and 段[0].startswith("@"):
            return 段[0]
        if 主機 == "youtu.be" and 段:
            return "影片 " + 段[0]
        v = parse_qs(p.query).get("v")
        if v:
            return "影片 " + v[0]
        if len(段) > 1 and 段[0] in ("channel", "c", "user", "live"):
            return 段[1]
    if 段:
        return 段[-1]
    return 主機 or 網址


def _讀(路徑, 預設):
    try:
        with open(路徑, encoding="utf-8-sig") as f:
            return json.load(f)
    except Exception:
        return 預設


def _寫(路徑, 內容):
    try:
        暫存 = 路徑 + ".tmp"
        with open(暫存, "w", encoding="utf-8") as f:
            json.dump(內容, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(暫存, 路徑)
    except Exception:
        pass


class 網址紀錄:
    """項目：{"網址", "釘選", "時間"}。清單順序：釘選的在前（依釘選順序），其後是最近用過的（新的在前）。"""

    def __init__(self, 路徑=None):
        self.路徑 = 路徑 or 網址紀錄檔
        self.項目們 = []
        原始 = _讀(self.路徑, [])
        if isinstance(原始, list):
            for 項 in 原始:
                if isinstance(項, dict) and isinstance(項.get("網址"), str) and 項["網址"].strip():
                    self.項目們.append({"網址": 項["網址"].strip(), "釘選": bool(項.get("釘選")),
                                      "時間": float(項["時間"]) if isinstance(項.get("時間"), (int, float)) else 0.0})
        self._整理()

    def _整理(self):
        釘 = [x for x in self.項目們 if x["釘選"]]
        其他 = sorted((x for x in self.項目們 if not x["釘選"]), key=lambda x: -x["時間"])[:最近上限]
        self.項目們 = 釘 + 其他

    def 存(self):
        _寫(self.路徑, self.項目們)

    def 清單(self):
        return [dict(x) for x in self.項目們]

    def _找(self, 網址):
        return next((x for x in self.項目們 if x["網址"] == 網址), None)

    def 加入(self, 網址):
        """成功開始擷取後呼叫：已有就更新時間（保留釘選），沒有就新增。"""
        網址 = 網址.strip()
        if not 網址:
            return
        項 = self._找(網址)
        if 項:
            項["時間"] = time.time()
        else:
            self.項目們.append({"網址": 網址, "釘選": False, "時間": time.time()})
        self._整理()
        self.存()

    def 釘選(self, 網址, 要釘=True):
        項 = self._找(網址)
        if not 項:
            return
        項["釘選"] = bool(要釘)
        if 要釘:                       # 新釘的排在釘選區最後
            self.項目們.remove(項)
            釘數 = sum(1 for x in self.項目們 if x["釘選"])
            self.項目們.insert(釘數, 項)
        self._整理()
        self.存()

    def 刪除(self, 網址):
        self.項目們 = [x for x in self.項目們 if x["網址"] != 網址]
        self.存()


預設欄頁 = ["分鐘摘要", "逐句翻譯", "直播稿"]


def 讀介面設定(所有頁名):
    """回傳 (欄數 1~3, 三欄各自的分頁名，三個互不重複且都存在)。"""
    原始 = _讀(介面設定檔, {})
    原始 = 原始 if isinstance(原始, dict) else {}
    欄數 = 原始.get("欄數")
    欄數 = 欄數 if isinstance(欄數, int) and not isinstance(欄數, bool) and 1 <= 欄數 <= 3 else 1
    選 = 原始.get("每欄分頁")
    頁們 = []
    for 名 in (選 if isinstance(選, list) else []):
        if 名 in 所有頁名 and 名 not in 頁們:
            頁們.append(名)
    for 名 in 預設欄頁 + list(所有頁名):          # 不足的用預設補齊
        if len(頁們) >= 3:
            break
        if 名 in 所有頁名 and 名 not in 頁們:
            頁們.append(名)
    return 欄數, 頁們[:3]


def _更新介面設定(**欄位):
    """只改指定的欄位，其他欄位（例如膠囊位置）原樣保留。"""
    原始 = _讀(介面設定檔, {})
    原始 = 原始 if isinstance(原始, dict) else {}
    原始.update(欄位)
    _寫(介面設定檔, 原始)


def 存介面設定(欄數, 欄頁們):
    _更新介面設定(欄數=欄數, 每欄分頁=list(欄頁們))


def 讀膠囊位置():
    """回傳 (x, y)；沒有紀錄或壞掉回傳 None。"""
    原始 = _讀(介面設定檔, {})
    位 = 原始.get("膠囊位置") if isinstance(原始, dict) else None
    if isinstance(位, list) and len(位) == 2 and all(isinstance(v, int) and not isinstance(v, bool) for v in 位):
        return 位[0], 位[1]
    return None


def 存膠囊位置(位置):
    _更新介面設定(膠囊位置=None if 位置 is None else [int(位置[0]), int(位置[1])])


def 讀設定框大小():
    """設定框上次的大小 (寬, 高)；沒有紀錄或壞掉回傳 None（超出螢幕的縮回由設定框自己處理）。"""
    原始 = _讀(介面設定檔, {})
    大小 = 原始.get("設定框大小") if isinstance(原始, dict) else None
    if (isinstance(大小, list) and len(大小) == 2
            and all(isinstance(v, int) and not isinstance(v, bool) and v > 0 for v in 大小)):
        return 大小[0], 大小[1]
    return None


def 存設定框大小(寬, 高):
    _更新介面設定(設定框大小=[int(寬), int(高)])


def 讀旗標(名):
    """一次性提示之類的開關（例如「主控台收起提示過」）。"""
    原始 = _讀(介面設定檔, {})
    return bool(isinstance(原始, dict) and 原始.get(名) is True)


def 存旗標(名, 值=True):
    _更新介面設定(**{名: bool(值)})
