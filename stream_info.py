# 直播資訊：開播時間、直播標題、遊戲分類、直播主名稱（不需要任何金鑰）
# 來源順序：Twitch 網頁公開 GQL（和 Twitch 網頁、streamlink 用的是同一個公開 Client-ID）→ 頻道網頁的 ld+json（備援）→ 都失敗回傳 None。
# 每個請求 3 秒逾時；背景查詢和 streamlink 的開播檢查並行，按「結束」（events.停止）就不再等。
# 只用標準函式庫；不用 yt-dlp、不用第三方服務。測試用 取得= 注入假回應，不連網。
import html
import json
import re
import threading
import urllib.request
from datetime import datetime

import events

GQL網址 = "https://gql.twitch.tv/gql"
網頁ClientID = "kimne78kx3ncx6brgo4mv6wki5h1ko"    # Twitch 網頁本身用的公開 Client-ID（不是個人金鑰）
逾時秒 = 3
最久等秒 = 逾時秒 * 2 + 0.5      # GQL 和網頁各 3 秒，再多給一點；網址解析（DNS）卡住也不會一直等


def _http(網址, 資料=None, 標頭=None, 逾時=逾時秒):
    # 網址只會是程式內固定的 https（GQL 與 twitch.tv 頻道網頁）
    請求 = urllib.request.Request(網址, data=資料, headers=標頭 or {})    # noqa: S310
    with urllib.request.urlopen(請求, timeout=逾時) as 回應:   # noqa: S310
        return 回應.read()


def 解析時間(字):
    """「2026-10-12T09:38:28Z」（可有小數秒）→ epoch 秒數；讀不懂回傳 None。"""
    try:
        return datetime.fromisoformat(str(字).strip().replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return None


def 從GQL(頻道, 取得=_http):
    """失敗（連不上、逾時、欄位缺失、沒開播）一律丟出例外，交給 查詢() 改走備援。"""
    查詢字 = "{user(login:" + json.dumps(頻道) + "){login displayName stream{createdAt title game{displayName name}}}}"
    原始 = 取得(GQL網址, json.dumps({"query": 查詢字}).encode(),
              {"Client-ID": 網頁ClientID, "Content-Type": "application/json"})
    使用者 = json.loads(原始)["data"]["user"]
    串流 = 使用者["stream"]
    開播 = 解析時間(串流["createdAt"])
    if 開播 is None:
        raise ValueError("createdAt 讀不懂")
    遊戲 = 串流.get("game") or {}
    return {"開播": 開播, "標題": 串流.get("title") or "", "遊戲": 遊戲.get("displayName") or 遊戲.get("name") or "",
            "直播主": 使用者.get("displayName") or 頻道, "來源": "GQL"}


def _走訪(物件):
    """ld+json 巢狀資料攤平成一串 dict。"""
    if isinstance(物件, dict):
        yield 物件
        for v in 物件.values():
            yield from _走訪(v)
    elif isinstance(物件, list):
        for v in 物件:
            yield from _走訪(v)


def 從網頁(頻道, 取得=_http):
    """頻道網頁的 ld+json 有 startDate（開播時間）；標題與遊戲從 og:description「標題 | Streaming 遊戲 for N viewers.」拆。"""
    文 = 取得(f"https://www.twitch.tv/{頻道}", None, {"User-Agent": "Mozilla/5.0"}).decode("utf-8", "replace")
    開播, 直播主 = None, ""
    for 區塊 in re.findall(r'<script type="application/ld\+json">(.*?)</script>', 文, re.DOTALL):
        try:
            資料 = json.loads(區塊)
        except ValueError:
            continue
        for d in _走訪(資料):
            if 開播 is None and "startDate" in d:
                開播 = 解析時間(d["startDate"])
            if not 直播主 and d.get("@type") == "Person" and d.get("name"):
                直播主 = d["name"]
    if 開播 is None:
        raise ValueError("網頁沒有 startDate")
    標題 = 遊戲 = ""
    m = re.search(r'<meta (?:property|name)="og:description" content="([^"]*)"', 文)
    if m:
        拆 = re.match(r"(.*) \| Streaming (.*?) for [\d,]+ viewers", html.unescape(m.group(1)))
        if 拆:
            標題, 遊戲 = 拆.group(1).strip(), 拆.group(2).strip()
    return {"開播": 開播, "標題": 標題, "遊戲": 遊戲, "直播主": 直播主 or 頻道, "來源": "網頁"}


def 查詢(頻道, 取得=_http, 停止=None):
    """GQL → 網頁 → None。回傳 {開播(epoch), 標題, 遊戲, 直播主, 來源}；停止 被設定就不再試下一個。"""
    for 方法 in (從GQL, 從網頁):
        if 停止 is not None and 停止.is_set():
            return None
        try:
            return 方法(頻道, 取得)
        except Exception:     # noqa: S112, BLE001 任何失敗都改走下一個來源，最後退回「從開始起算」
            continue
    return None


class 背景查詢:
    """開始擷取前在背景查直播資訊，和 streamlink 的開播檢查並行；用 等() 取結果。"""

    def __init__(self, 頻道, 取得=_http):
        self.結果 = None
        self._完成 = threading.Event()

        def 跑():
            try:
                self.結果 = 查詢(頻道, 取得, events.停止)
            finally:
                self._完成.set()

        threading.Thread(target=跑, daemon=True).start()

    def 等(self, 最久=最久等秒, 停止=None):
        """等到查完、超過 最久 秒、或按了「結束」（停止）為止。沒結果回傳 None（呼叫的人退回「從開始起算」）。"""
        停止 = 停止 or events.停止
        剩 = 最久
        while 剩 > 0 and not self._完成.is_set():
            if 停止.is_set():
                return None
            self._完成.wait(0.1)
            剩 -= 0.1
        return self.結果 if self._完成.is_set() else None
