# 直播資訊：開播時間、直播標題、遊戲分類、直播主名稱（不需要任何金鑰）
# YouTube：查YouTube() 讀觀看頁（頻道 ID、直播主、@帳號、標題、分類、開播時間、是否直播中），見下面的 YouTube 段。
# 來源順序：Twitch 網頁公開 GQL（和 Twitch 網頁、streamlink 用的是同一個公開 Client-ID）→ 頻道網頁的 ld+json（備援）→ 都失敗回傳 None。
# 每個請求 3 秒逾時；背景查詢和 streamlink 的開播檢查並行，按「結束」（events.停止）就不再等。
# 只用標準函式庫；不用 yt-dlp、不用第三方服務。測試用 取得= 注入假回應，不連網。
import html
import json
import re
import threading
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

import events
import platforms  # 網址 → 平台、要讀的 YouTube 觀看頁

GQL網址 = "https://gql.twitch.tv/gql"
網頁ClientID = "kimne78kx3ncx6brgo4mv6wki5h1ko"    # Twitch 網頁本身用的公開 Client-ID（不是個人金鑰）
逾時秒 = 3
最久等秒 = 逾時秒 * 2 + 0.5      # GQL 和網頁各 3 秒，再多給一點；網址解析（DNS）卡住也不會一直等


def _http(網址, 資料=None, 標頭=None, 逾時=逾時秒):
    # 網址只會是程式內組出來的 https（GQL、twitch.tv 頻道網頁、youtube.com 觀看頁）
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


# ---------- YouTube：讀觀看頁（不需要金鑰）----------
# 觀看頁裡有兩段 JSON：ytInitialPlayerResponse（影片：videoDetails、microformat 的 liveBroadcastDetails）
# 與 ytInitialData（頻道頁：metadata.channelMetadataRenderer）。頻道沒在直播時 /live 會是頻道頁，只拿得到頻道資訊。
# 讀不到、格式變了：一律回傳「不知道」（None 或空字串），不丟例外。
YouTube逾時秒 = 6       # 觀看頁約 1 MB，比 Twitch 的請求慢
YouTube標頭 = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)", "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8"}
YouTube頻道ID = re.compile(r"^UC[\w-]{22}$")


def _頁內JSON(文, 名稱):
    """「var 名稱 = {…};」→ dict；找不到或讀不懂回傳 None。"""
    m = re.search(re.escape(名稱) + r"\s*=\s*\{", 文)
    if not m:
        return None
    try:
        物件, _ = json.JSONDecoder().raw_decode(文, m.end() - 1)
    except ValueError:
        return None
    return 物件 if isinstance(物件, dict) else None


def _取(物件, *路徑):
    """一層一層往下拿；任何一層不是 dict 或沒有這個鍵就回傳 None。"""
    for 鍵 in 路徑:
        if not isinstance(物件, dict):
            return None
        物件 = 物件.get(鍵)
    return 物件


def _字(值):
    return 值.strip() if isinstance(值, str) else ""


def _帳號(網址字):
    m = re.search(r"youtube\.com/(@[^/?#\s\"]+)", _字(網址字))
    return urllib.parse.unquote(m.group(1)) if m else ""


def _時刻(值):
    """epoch 秒（字串或數字）→ float；讀不懂回傳 None。"""
    try:
        return float(值) if 值 not in (None, "", True, False) else None
    except (TypeError, ValueError):
        return None


def 解析YouTube頁(文):
    """觀看頁（或頻道頁）的 HTML → {頻道ID, 直播主, 帳號, 標題, 分類, 開播(epoch), 直播中(True/False/None), 影片ID,
    狀態, 原因, 預定開始(epoch), 即將開始(True/False), 直播內容(True/False/None)}；
    狀態／原因是 playabilityStatus（OK、LIVE_STREAM_OFFLINE、LOGIN_REQUIRED…），開播檢查失敗時拿來寫白話訊息。
    每一項讀不到就是空字串／None。整頁都看不出是哪個頻道時回傳 None。"""
    播放 = _頁內JSON(文, "ytInitialPlayerResponse") or {}
    可播 = _取(播放, "playabilityStatus") or {}
    細節 = _取(播放, "videoDetails") or {}
    微 = _取(播放, "microformat", "playerMicroformatRenderer") or _取(播放, "microformat", "microformatDataRenderer") or {}
    直播 = _取(微, "liveBroadcastDetails") or {}
    頻道 = _取(_頁內JSON(文, "ytInitialData"), "metadata", "channelMetadataRenderer") or {}
    頻道ID = next((x for x in (_字(_取(細節, "channelId")), _字(_取(微, "externalChannelId")), _字(_取(頻道, "externalId")))
                 if YouTube頻道ID.match(x)), "")
    if not 頻道ID:
        m = re.search(r'<link rel="canonical" href="https://www\.youtube\.com/channel/(UC[\w-]{22})"', 文)
        頻道ID = m.group(1) if m else ""
    if not 頻道ID:
        return None
    直播中 = 直播.get("isLiveNow") if isinstance(直播.get("isLiveNow"), bool) else 細節.get("isLive")
    return {
        "頻道ID": 頻道ID,
        "直播主": _字(_取(細節, "author")) or _字(_取(微, "ownerChannelName")) or _字(_取(頻道, "title")),
        "帳號": _帳號(_取(微, "ownerProfileUrl")) or _帳號(_取(頻道, "vanityChannelUrl")),
        "標題": _字(_取(細節, "title")),
        "分類": _字(_取(微, "category")),
        "開播": 解析時間(直播.get("startTimestamp")) if 直播.get("startTimestamp") else None,
        "直播中": 直播中 if isinstance(直播中, bool) else None,
        "影片ID": _字(_取(細節, "videoId")),
        "狀態": _字(_取(可播, "status")),
        "原因": _字(_取(可播, "reason")) or _字(_取(可播, "reason", "simpleText")),
        "預定開始": _時刻(_取(可播, "liveStreamability", "liveStreamabilityRenderer", "offlineSlate",
                             "liveStreamOfflineSlateRenderer", "scheduledStartTime")),
        "即將開始": _取(細節, "isUpcoming") is True,
        "直播內容": 細節.get("isLiveContent") if isinstance(細節.get("isLiveContent"), bool) else None,
    }


def _讀頁(網址, 取得):
    """讀一頁並解析 → (資訊 或 None, 原因)。"""
    try:
        文 = 取得(網址, None, YouTube標頭, YouTube逾時秒).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return None, "找不到" if e.code in (400, 404) else "連線"
    except Exception:      # noqa: BLE001  連不上、逾時、其他 HTTP 錯誤：都算「連線」
        return None, "連線"
    try:
        結果 = 解析YouTube頁(文)
    except Exception:      # noqa: BLE001  格式變了：當作不知道
        結果 = None
    return 結果, "" if 結果 else "格式"


def 查YouTube詳細(網址, 取得=_http):
    """YouTube 網址 → (資訊 或 None, 原因)。原因：""＝讀到了；"網址"＝不是支援的 YouTube 直播網址；
    "連線"＝連不上或逾時；"找不到"＝YouTube 回應沒有這一頁（帳號或影片不存在）；
    "格式"＝頁面讀到了但看不出是哪個頻道（YouTube 改版等）。不丟例外。
    頻道網址（/@帳號/live 等）有些版本的頁面缺開播時間：看得出影片 ID 時再讀一次那部影片的觀看頁補齊。"""
    資 = platforms.判斷(網址)
    if 資.平台 != platforms.YOUTUBE or not 資.支援:
        return None, "網址"
    結果, 原因 = _讀頁(platforms.觀看頁網址(資), 取得)
    if 結果 is None:
        return None, 原因
    if not 資.影片 and 結果["影片ID"] and (結果["開播"] is None or not 結果["分類"] or not 結果["帳號"]):
        補, _ = _讀頁(f"https://www.youtube.com/watch?v={結果['影片ID']}", 取得)
        if 補 and 補["頻道ID"] == 結果["頻道ID"]:
            結果.update({k: v for k, v in 補.items() if v not in ("", None)})
    if not 結果["帳號"] and 資.帳號:
        結果["帳號"] = 資.帳號
    結果["來源"] = "YouTube網頁"
    return 結果, ""


def 查YouTube(網址, 取得=_http):
    """YouTube 網址 → 資訊 dict；不知道回傳 None。"""
    return 查YouTube詳細(網址, 取得)[0]


def 查YouTube直播(網址, 取得=_http, 停止=None):
    """開始擷取用（背景查詢的 查法）：查YouTube 的結果加上時軸要的欄位（遊戲＝分類）；查不到回傳 None。
    還沒開始的直播，頁面的 startTimestamp 是「預定」開始時間，不能當開播時間：開播改成 None、放到 預定開始。"""
    if 停止 is not None and 停止.is_set():
        return None
    結果 = 查YouTube(網址, 取得)
    if not 結果:
        return None
    if 結果["即將開始"] or 結果["直播中"] is False:
        結果["預定開始"] = 結果["預定開始"] or (結果["開播"] if 結果["即將開始"] else None)
        結果["開播"] = None
    結果["遊戲"] = 結果["分類"]
    return 結果


class 背景查詢:
    """開始擷取前在背景查直播資訊，和 streamlink 的開播檢查並行；用 等() 取結果。"""

    def __init__(self, 頻道, 取得=_http, 查法=None):
        """查法：查詢（Twitch，預設；頻道是頻道名稱）或 查YouTube直播（頻道是網址）。"""
        self.結果 = None
        self._完成 = threading.Event()

        def 跑():
            try:
                self.結果 = (查法 or 查詢)(頻道, 取得, events.停止)
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
