# 平台判斷：給一個網址，判斷是 Twitch 還是 YouTube、是不是支援的直播網址，以及不用上網就看得出的資訊。
# 不連網、不丟例外；看不懂的網址回傳 支援=False 並附白話原因。
#   Twitch：twitch.tv/頻道（/videos/ 是直播檔，不支援）。
#   YouTube：watch?v=ID、/live/ID、youtu.be/ID、/@帳號（/live）、/channel/UC…（/live）、/c/名稱（/live）、/user/名稱（/live）、
#            /embed/ID、/embed/live_stream?channel=UC…；/shorts/ 擋掉。
#   YouTube 的頻道 ID 只有 /channel/ 與 embed 的 live_stream 網址看得出來；其他格式要上網查（stream_info.查YouTube）。
import re
from dataclasses import dataclass
from urllib.parse import parse_qs, quote, unquote, urlparse

TWITCH = "twitch"
YOUTUBE = "youtube"

VOD原因 = "直播檔（VOD）網址看不出是哪個頻道，請改用頻道網址"
Twitch保留路徑 = {"videos", "directory", "settings", "search", "downloads", "jobs", "turbo", "friends", "subscriptions",
             "inventory", "wallet", "p", "u", "moderator", "popout", "embed"}
Twitch頻道 = re.compile(r"^(?:https?://)?(?:www\.|m\.)?twitch\.tv/([A-Za-z0-9_]{3,25})/?(?:[?#].*)?$", re.IGNORECASE)
影片ID = re.compile(r"^[\w-]{11}$")
頻道ID = re.compile(r"^UC[\w-]{22}$")


@dataclass(frozen=True)
class 網址資訊:
    平台: str = ""          # TWITCH／YOUTUBE；認不出來是空字串
    支援: bool = False      # 是不是支援的直播網址格式
    原因: str = ""          # 不支援時的白話原因
    頻道: str = ""          # Twitch 頻道名稱
    帳號: str = ""          # YouTube @帳號（含 @）
    影片: str = ""          # YouTube 影片 ID
    頻道ID: str = ""        # YouTube 頻道 ID（UC…）
    名稱: str = ""          # YouTube 舊式網址的路徑：「c/名稱」或「user/名稱」

    @property
    def 查詢鍵(self):
        """同一個 YouTube 來源的快取鍵（不分大小寫的帳號、影片 ID、頻道 ID 或舊式名稱）；Twitch 或不支援回傳空字串。"""
        if self.平台 != YOUTUBE or not self.支援:
            return ""
        if self.頻道ID:
            return "channel:" + self.頻道ID
        if self.帳號:
            return "@" + self.帳號[1:].casefold()
        if self.影片:
            return "v:" + self.影片
        return "c:" + self.名稱.casefold()


def _不支援(平台, 原因):
    return 網址資訊(平台=平台, 原因=原因)


def _解析(網址):
    p = urlparse(網址 if "://" in 網址 else "https://" + 網址)
    主機 = (p.hostname or "").lower()
    段 = [unquote(s) for s in p.path.split("/") if s]
    return p, 主機, 段


def _twitch(網址):
    if "/videos/" in 網址.lower():
        return _不支援(TWITCH, VOD原因)
    m = Twitch頻道.match(網址)
    if not m or m.group(1).lower() in Twitch保留路徑:
        return _不支援(TWITCH, "這不是 Twitch 頻道網址（例如 https://www.twitch.tv/頻道名稱）")
    return 網址資訊(平台=TWITCH, 支援=True, 頻道=m.group(1))


def _youtube(p, 主機, 段):
    不對 = _不支援(YOUTUBE, "這不是 YouTube 直播網址（例如 https://www.youtube.com/@帳號/live）")
    if 主機 == "youtu.be":
        if len(段) == 1 and 影片ID.match(段[0]):
            return 網址資訊(平台=YOUTUBE, 支援=True, 影片=段[0])
        return 不對
    if not 段:
        return 不對
    首 = 段[0]
    if 首.lower() == "shorts":
        return _不支援(YOUTUBE, "Shorts 短影音不是直播，請改用直播網址")
    if 首 == "watch":
        v = (parse_qs(p.query).get("v") or [""])[0]
        return 網址資訊(平台=YOUTUBE, 支援=True, 影片=v) if 影片ID.match(v) and len(段) == 1 else 不對
    if 首 == "live" and len(段) == 2 and 影片ID.match(段[1]):
        return 網址資訊(平台=YOUTUBE, 支援=True, 影片=段[1])
    if 首 == "embed" and len(段) == 2:
        if 段[1] == "live_stream":
            頻 = (parse_qs(p.query).get("channel") or [""])[0]
            return 網址資訊(平台=YOUTUBE, 支援=True, 頻道ID=頻) if 頻道ID.match(頻) else 不對
        return 網址資訊(平台=YOUTUBE, 支援=True, 影片=段[1]) if 影片ID.match(段[1]) else 不對
    後 = 段[1:] if 首.startswith("@") else 段[2:]
    if 後 not in ([], ["live"]):            # 頻道底下只接受頻道首頁或 /live
        return 不對
    if 首.startswith("@") and len(首) > 1:
        return 網址資訊(平台=YOUTUBE, 支援=True, 帳號=首)
    if len(段) >= 2 and 首 == "channel":
        return 網址資訊(平台=YOUTUBE, 支援=True, 頻道ID=段[1]) if 頻道ID.match(段[1]) else 不對
    if len(段) >= 2 and 首 in ("c", "user") and 段[1]:
        return 網址資訊(平台=YOUTUBE, 支援=True, 名稱=f"{首}/{段[1]}")
    return 不對


def 判斷(網址):
    """網址 → 網址資訊。空字串、認不出的網站：平台是空字串、支援=False。"""
    網址 = (網址 or "").strip()
    if not 網址:
        return _不支援("", "請輸入 Twitch 或 YouTube 直播網址")
    try:
        p, 主機, 段 = _解析(網址)
    except ValueError:
        return _不支援("", "看不懂這個網址")
    裸 = 主機.removeprefix("www.").removeprefix("m.")
    if 裸 == "twitch.tv":
        return _twitch(網址)
    if 主機 == "youtu.be" or 主機 == "youtube.com" or 主機.endswith(".youtube.com"):
        return _youtube(p, 主機, 段)
    return _不支援("", "目前只支援 Twitch 與 YouTube 的直播網址")


def 觀看頁網址(資訊):
    """要讀哪一頁拿直播資訊：影片 → watch?v=；頻道 → 頻道的 /live（正在直播時就是那場直播的觀看頁）。不支援回傳空字串。"""
    if 資訊.平台 != YOUTUBE or not 資訊.支援:
        return ""
    if 資訊.影片:
        return f"https://www.youtube.com/watch?v={資訊.影片}"
    if 資訊.頻道ID:
        return f"https://www.youtube.com/channel/{資訊.頻道ID}/live"
    if 資訊.帳號:
        return f"https://www.youtube.com/{quote(資訊.帳號, safe='@')}/live"
    return f"https://www.youtube.com/{quote(資訊.名稱)}/live"
