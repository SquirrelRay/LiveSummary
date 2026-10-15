# 聊天室翻譯（只有介面會用）：外語直播時把聊天室留言翻成台灣慣用繁體中文，原文和譯文一起出現在聊天室面板。
# 和逐句字幕翻譯（subtitle.py）完全分開：自己的佇列與背景執行緒、自己限速，字幕翻譯的行為不受影響。
# 什麼時候翻：config.json 的 chat_translate 開著（膠囊選單可當場切換）＋聊天室面板開著＋直播語言是外語
#            （語言自動偵測時，要等偵測到外語才翻）。三者缺一就不翻、不呼叫 API。
# 哪些不翻（跳過）：草、www、888、單一字元重複、純數字、固定短語、純表情代碼（Twitch 表情）、純符號。
#            外語直播中，全漢字的留言當作該外語送翻（例如「全然大丈夫」）；明顯是中文的（有「們、這、嗎」等字）不翻。
# 批次：第一則進來後最多等 批次秒數，或累積 批次則數 就送出。
# 每分鐘上限：config.json 的 chat_translate_max_per_min；超過就從這一批平均抽樣，沒抽到的只顯示原文。
#            每批可翻幾則用「額度桶」：桶子最多裝上限的一半，每秒補 上限÷60；熱門台因此平均分散在整分鐘，
#            不會一開始翻滿就停；另外最近 60 秒已翻的總數一定不超過上限。
# 保護字幕：收到 API 速率限制（429）就暫停 限速暫停秒，那一批與暫停期間的留言都不翻、不重送；
#            排隊超過 最久等待秒 還沒送的留言放棄翻譯（不追舊帳）。任何翻譯失敗都只顯示原文，不重送。
# 顯示：翻譯開著時留言先不顯示（顯示排隊），譯文回來後原文與譯文一起出現（chat_show 事件），不會先出原文再補譯文而閃動。
#            不翻的留言（草、表情代碼…）與被抽樣略過的留言照原本時間順序和前後的留言一起出現，不會先跑出來。
#            翻譯失敗、429、超時放棄的留言以原文出現；任何留言最多等 最久顯示秒 就一定出現（API 很慢也不會卡住）。
#            翻譯關著（設定、面板、中文直播）時，留言照舊立刻顯示。
# 用量記在 llm.聊天翻譯用量；第一則留言、第一批送出與回來、第一則顯示記在啟動里程碑（查延遲用）。
# 讓人看得懂：第一則「不翻」的留言出現前，聊天室面板先出現一行說明（哪些留言不翻、直接顯示原文），每場一次；
#            第一次翻譯失敗（出錯、讀不出譯文、則數對不上）也說明一次。結束時的統計多寫「不翻幾則」。
# 紀錄：logs\聊天室翻譯紀錄.txt。每次失敗一行（錯誤類型或 stop_reason，讀不出譯文時附模型回答的前 300 字）；
#            每場結束一行統計（送翻、已翻、各種不翻原因的則數、每批 API 秒數的平均與最大）。不含金鑰。
import os
import queue
import re
import threading
import time
from collections import Counter, deque

import app_paths
import config  # 語言清單（單一來源）
import events
import llm
import model_catalog  # 單價未知時費用是 model_catalog.未知
import startup_timeline as 里程碑
import subtitle  # 只用 讀譯文（從模型回答讀出 JSON 陣列）

批次秒數 = 8           # 第一則進來後最多等幾秒就送
批次則數 = 40          # 累積幾則就送（也是一次最多送幾則）
最久等待秒 = 20        # 排隊超過這麼久還沒送的留言放棄翻譯
最久顯示秒 = 20        # 留言進來後最多這麼久一定出現（譯文還沒回來就以原文出現）
放出間隔秒 = 0.2       # 多久檢查一次排隊中的留言能不能出現
限速暫停秒 = 60        # 收到 429 後暫停幾秒
預設每分上限 = 30

# 迷因與俚語的固定對照（只放這裡，之後擴充改這張表就好）：(原文寫法, 台灣直播慣用說法)
迷因對照 = [
    ("草、www、ｗ", "笑死、哈哈"),
    ("888、8888", "拍手"),
    ("乙、おつ、お疲れ", "辛苦了"),
    ("てぇてぇ", "好貼"),
    ("かわいい", "好可愛"),
    ("初見", "第一次來"),
    ("きた、キタ", "來了"),
    ("ナイス", "漂亮"),
    ("ドンマイ", "沒關係、別在意"),
    ("GG", "GG"),
]

翻譯規則 = (
    "把下面的直播聊天室留言翻成台灣慣用的繁體中文，給觀眾即時看。\n"
    "規則：\n"
    "- 一律用繁體中文，不可出現簡體字；日文的漢字詞也要換成台灣慣用的中文詞。\n"
    "- 口語、簡短，一則對一則，不要加解釋。\n"
    "- 網路用語照這張對照翻成台灣直播慣用說法：{對照}。\n"
    "- 不認得的梗、暱稱、表情代碼或專有名詞，直接保留原文，不要硬翻，也不要解釋。\n\n"
    "只回傳 JSON 陣列，不要其他文字，陣列長度必須和則數一樣，順序相同：[\"第1則譯文\", \"第2則譯文\", ...]\n\n"
    "留言：\n"
)


def 提示詞(留言們):
    對照 = "；".join(f"{原}→{譯}" for 原, 譯 in 迷因對照)
    return 翻譯規則.replace("{對照}", 對照) + "\n".join(f"{i + 1}. {t}" for i, t in enumerate(留言們))


# ---------- 跳過規則 ----------
提及 = re.compile(r"@\S+")
# Twitch 表情代碼：小寫開頭的頻道前綴＋大寫開頭的名字（hitomi32Hahaha、migiYAYA、k4senDecoy1、akariO）
表情代碼 = re.compile(r"(?<![A-Za-z0-9])[a-z][a-z0-9]{2,}[A-Z][A-Za-z0-9]*(?![A-Za-z0-9])")
常見表情 = re.compile(r"(?<![A-Za-z0-9])(?:LUL|LULW|KEKW|OMEGALUL|Kappa|PogChamp|Pog|POGGERS|monkaS|PepeHands|Sadge|"
                  r"BibleThump|Kreygasm|ResidentSleeper|NotLikeThis|SeemsGood|VoHiYo|HeyGuys|CoolCat|DansGame|"
                  r"TriHard|WutFace|FeelsBadMan|FeelsGoodMan|EZ)(?![A-Za-z0-9])")
可略的符號 = re.compile(r"[\s!！?？~～〜。、．.,，・…ー\-]+")
草們 = re.compile(r"[wWｗＷ草]+")
固定短語們 = {
    "おつ", "乙", "おつかれ", "おつかれさま", "お疲れ", "お疲れ様", "お疲れさま", "かわいい", "可愛い", "えらい", "ナイス", "ないす",
    "うまい", "こんにちは", "こんばんは", "おはよう", "ありがとう", "きた", "キタ", "はい", "うん", "おお", "おー", "えー", "へー",
    "やば", "やばい", "すご", "すごい", "初見", "ドンマイ",
    "nice", "gg", "hi", "hello", "lol", "lmao", "omg", "wow", "xd", "ok", "yes", "no",
}
假名或韓文 = re.compile(r"[぀-ヿ가-힯]")
漢字 = re.compile(r"[一-鿿]")
中文專用字 = set("們這嗎呢妳喔欸吧啦嘛哦")      # 日文幾乎不會出現的中文字：有這些、又沒有假名，就當作中文留言


def 去雜訊(內容):
    """拿掉 @提及 與表情代碼（送翻與判斷都用這個版本）。"""
    t = 提及.sub(" ", 內容)
    t = 表情代碼.sub(" ", t)
    t = 常見表情.sub(" ", t)
    return " ".join(t.split())


# Super Chat／Super Sticker 沒有文字時 yt_chat 補的固定字樣：沒有內容可翻，直接顯示原文
SC無文字們 = {"【SC】（沒有留言）", "【SC】貼圖"}


def 跳過原因(內容):
    """不需要翻譯的留言回傳原因（字串），要翻回傳 None。和直播語言無關的部分。"""
    if (內容 or "").strip() in SC無文字們:
        return "SC 沒有文字"
    t = 去雜訊(內容)
    if not t:
        return "純表情代碼"
    if not any(c.isalnum() for c in t):
        return "純符號"
    純 = 可略的符號.sub("", t)
    if not 純:
        return "純符號"
    if 純.isdigit():
        return "純數字"
    if 草們.fullmatch(純):
        return "草"
    if len(set(純)) == 1:
        return "單一字元重複"
    if 純.lower() in 固定短語們:
        return "固定短語"
    return None


def 不翻原因(內容, 語言):
    """這則留言在這個直播語言下不送翻的原因（字串）；要送翻回傳 None。"""
    if 語言 not in config.外語們:
        return "不是外語直播"
    原因 = 跳過原因(內容)
    if 原因:
        return 原因
    t = 去雜訊(內容)
    if not 假名或韓文.search(t) and 漢字.search(t) and any(c in 中文專用字 for c in t):
        return "中文留言"
    return None                          # 全漢字的留言在外語直播中當作該外語


def 要翻譯(內容, 語言):
    """這則留言在這個直播語言下要不要送翻。語言不是外語（中文、還在自動偵測）一律不翻。"""
    return 不翻原因(內容, 語言) is None


# 聊天室面板的說明行（每場各一次）：不翻的留言不是壞掉
不翻說明 = ("（聊天室翻譯開著：只有表情、草／www、888、數字、常見短語（例如 おつ、かわいい、ナイス）"
          "或中文的留言不翻，直接顯示原文；其他留言會在原文下面出現 ↳ 譯文）")
失敗說明 = "（聊天室翻譯有一批沒翻成功（{原因}），那幾則只顯示原文；之後的留言照常翻譯）"


def 寫紀錄(文字):
    """寫一行到 logs\\聊天室翻譯紀錄.txt；寫不進去不影響翻譯。"""
    try:
        os.makedirs(app_paths.日誌資料夾(), exist_ok=True)
        with open(app_paths.聊天翻譯紀錄檔(), "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {文字}\n")
    except OSError:
        pass


def 抽樣(項目們, n):
    """平均抽 n 則（保留先後順序）。"""
    if n >= len(項目們):
        return list(項目們)
    if n <= 0:
        return []
    步 = len(項目們) / n
    return [項目們[int(i * 步)] for i in range(n)]


class 顯示排隊:
    """聊天室翻譯開著時，留言先排在這裡，照原本的時間順序放出去顯示：
    最前面那則「定案」了（譯文回來、確定不翻、翻譯失敗或被抽樣略過）才放；後面的不能超車。
    最前面那則等超過 最久顯示秒 還沒定案，就以原文放出（之後才回來的譯文不再補上，避免閃動）。
    會被擷取聊天室、翻譯、放出三條執行緒同時用，所以全部上鎖。"""

    def __init__(self, 最久秒):
        self.最久秒 = 最久秒
        self._項們 = deque()        # 每項：{"資料", "時間", "定案", "譯文"}
        self._索引 = {}             # 編號 → 項
        self._鎖 = threading.Lock()

    def 加(self, 資料, 時間, 等譯文):
        項 = {"資料": 資料, "時間": 時間, "定案": not 等譯文, "譯文": None}
        with self._鎖:
            self._項們.append(項)
            self._索引[資料["編號"]] = 項

    def 定案(self, 編號, 譯文=None):
        """譯文 None = 不翻／翻不到，以原文顯示。已經放出去或不認得的編號不做事。"""
        with self._鎖:
            項 = self._索引.get(編號)
            if 項 is not None and not 項["定案"]:
                項["定案"], 項["譯文"] = True, 譯文 or None

    def 取出(self, 現在, 全部=False):
        """可以顯示的留言（照順序）：[(資料, 譯文)]。全部=True：不管定案沒有，全部放出（沒定案的用原文）。"""
        出 = []
        with self._鎖:
            while self._項們:
                項 = self._項們[0]
                if not (項["定案"] or 全部 or 現在 - 項["時間"] >= self.最久秒):
                    break
                self._項們.popleft()
                del self._索引[項["資料"]["編號"]]
                出.append((項["資料"], 項["譯文"] if 項["定案"] else None))
        return 出

    def __len__(self):
        with self._鎖:
            return len(self._項們)


class 聊天翻譯器:
    def __init__(self, 時鐘=time.time):
        self.時鐘 = 時鐘
        self.開啟 = False           # config.json 的 chat_translate（膠囊選單可當場切換）
        self.面板開著 = False       # 聊天室面板開著
        self.語言 = "zh"
        self.模型 = ""
        self.單價 = (0, 0)
        self.每分上限 = 預設每分上限
        self._佇列 = queue.Queue()
        self._緩衝 = []             # 已收到、還沒送的留言：(收到時間, 編號, 送翻文字)
        self.排隊 = 顯示排隊(最久顯示秒)
        self._停 = threading.Event()
        self._停.set()              # 還沒開始
        self._執行緒 = None
        self._放出執行緒 = None
        self._暫停到 = 0.0          # 收到 429 後暫停到這個時間
        self._額度 = None           # 額度桶裡還有幾則（None = 還沒開始，第一次用時裝滿）
        self._額度時間 = None       # 上次補額度的時間
        self._最近送翻 = deque()    # 最近 60 秒每一則送翻留言的時間
        self.統計 = self._新統計()
        self._場重設()

    def _場重設(self):
        self.不翻原因們 = Counter()  # 不翻原因 → 則數（結束時寫進紀錄與統計）
        self._不翻編號 = set()      # 確定不翻、還沒放出的留言編號（放出第一則時先出說明行）
        self._已說明 = set()        # 這一場已經在聊天室面板說明過的事："不翻"、"失敗"
        self._API秒們 = []          # 每批翻譯的 API 秒數
        self._已寫統計 = False

    @staticmethod
    def _新統計():
        return {"送翻": 0, "已翻": 0, "抽樣略過": 0, "逾時放棄": 0, "限速放棄": 0, "失敗": 0, "限速次數": 0}

    def 呼叫(self, 提示詞):
        return llm.call_llm(提示詞, self.模型, 類別="聊天翻譯")

    def 啟用中(self):
        return self.開啟 and self.面板開著 and self.語言 in config.外語們

    def 開始(self, 開啟, 語言, 模型, 單價輸入, 單價輸出, 每分上限=預設每分上限, 執行緒=True):
        """新的一場。執行緒=False：不開背景執行緒（測試自己呼叫 處理一次、放出一次）。"""
        self._停.set()              # 上一場的執行緒停下來（上一場結束時已經把排隊的留言放出去了）
        self.開啟, self.語言, self.模型 = bool(開啟), 語言, 模型
        self.單價 = (單價輸入, 單價輸出)
        self.每分上限 = int(每分上限)
        for k in llm.聊天翻譯用量:
            llm.聊天翻譯用量[k] = 0
        self.統計 = self._新統計()
        self._佇列 = queue.Queue()
        self._緩衝 = []
        self.排隊 = 顯示排隊(最久顯示秒)
        self._暫停到 = 0.0
        self._額度 = self._額度時間 = None
        self._最近送翻 = deque()
        self._場重設()
        self._停 = threading.Event()
        if 執行緒:
            self._執行緒 = threading.Thread(target=self._跑, daemon=True)
            self._執行緒.start()
            self._放出執行緒 = threading.Thread(target=self._放, daemon=True)
            self._放出執行緒.start()

    def 結束(self):
        """這一場結束：還沒翻的留言就不翻了，排隊中的留言立刻以原文（已翻好的帶譯文）顯示，不會卡住。"""
        self._停.set()
        self._緩衝 = []
        self._佇列 = queue.Queue()
        self.放出一次(全部=True)
        self._寫統計()

    def _寫統計(self):
        """這一場的聊天室翻譯統計寫進紀錄（一場一行；沒收到任何要處理的留言就不寫）。"""
        s = self.統計
        if self._已寫統計 or not (s["送翻"] or self.不翻原因們):
            return
        self._已寫統計 = True
        不翻 = "、".join(f"{k} {v}" for k, v in self.不翻原因們.most_common()) or "無"
        秒們 = self._API秒們
        秒 = f"平均 {sum(秒們) / len(秒們):.2f}、最大 {max(秒們):.2f}" if 秒們 else "（沒有呼叫）"
        寫紀錄(f"本場統計：語言={self.語言}，模型={self.模型}；送翻 {s['送翻']} 則（{len(秒們)} 批），已翻 {s['已翻']}，"
             f"失敗 {s['失敗']}，抽樣略過 {s['抽樣略過']}，逾時放棄 {s['逾時放棄']}，限速放棄 {s['限速放棄']}；"
             f"不翻 {sum(self.不翻原因們.values())} 則（{不翻}）；每批 API 秒數：{秒}")

    def _說明一次(self, 事, 說明):
        """聊天室面板出現一行說明（每場每件事一次）。"""
        if 事 in self._已說明:
            return
        self._已說明.add(事)
        events.送出("chat_status", 狀態="翻譯說明", 說明=說明, 印出=說明)

    def 接收(self, 種類, 內容):
        """events 的接收者：只處理 chat_line（另外記下自動偵測到的語言）。
        聊天室翻譯開著時，留言先排隊、不立刻顯示：在事件內容標 暫留=True（這個接收者排在介面前面，
        介面看到 暫留 就不顯示），等放出時再送 chat_show 事件（原文、譯文一起）。"""
        if 種類 == "language_detected":
            self.語言 = 內容["語言"]
            return
        if 種類 != "chat_line" or self._停.is_set() or not self.啟用中() or 內容.get("編號") is None:
            return
        現在 = self.時鐘()
        里程碑.標記(里程碑.聊天第一則)
        原因 = 不翻原因(內容["內容"], self.語言)
        等譯文 = 原因 is None
        資料 = {"編號": 內容["編號"], "時間字": 內容["時間字"], "使用者": 內容["使用者"], "內容": 內容["內容"]}
        if not 等譯文:
            self.不翻原因們[原因] += 1
            self._不翻編號.add(內容["編號"])
        self.排隊.加(資料, 現在, 等譯文)
        內容["暫留"] = True
        if 等譯文:
            self._佇列.put((現在, 內容["編號"], 去雜訊(內容["內容"])))

    def _跑(self):
        停 = self._停
        llm.預先載入()              # 先載入模型服務的套件（anthropic 約 2.5 秒），第一批翻譯不必等
        while not 停.is_set():
            try:
                self._緩衝.append(self._佇列.get(timeout=0.3))
            except queue.Empty:
                pass
            if not 停.is_set():
                self.處理一次()

    def _放(self):
        停 = self._停
        while not 停.wait(放出間隔秒):
            self.放出一次()

    def 放出一次(self, 全部=False):
        """把可以顯示的留言照順序送出 chat_show 事件。聊天室翻譯中途關掉（設定、面板、語言）就全部放出。"""
        for 資料, 譯文 in self.排隊.取出(self.時鐘(), 全部 or not self.啟用中()):
            if 資料["編號"] in self._不翻編號:
                self._不翻編號.discard(資料["編號"])
                self._說明一次("不翻", 不翻說明)       # 第一則不翻的留言出現前先說明，不會看起來像翻譯壞掉
            里程碑.標記(里程碑.聊天第一則顯示, 有譯文=bool(譯文))
            events.送出("chat_show", **資料, 譯文=譯文)

    def _放棄(self, 項們, 原因):
        self.統計[原因] += len(項們)
        for _, 編號, _ in 項們:
            self.排隊.定案(編號)

    def 桶容量(self):
        return max(1, (self.每分上限 + 1) // 2)

    def _本批額度(self, 現在):
        """這一批最多可以翻幾則：額度桶裡的整數則數，而且最近 60 秒的總數不超過上限。"""
        if self._額度 is None:
            self._額度 = float(self.桶容量())
        else:
            self._額度 = min(self.桶容量(), self._額度 + (現在 - self._額度時間) * self.每分上限 / 60)
        self._額度時間 = 現在
        while self._最近送翻 and 現在 - self._最近送翻[0] >= 60:
            self._最近送翻.popleft()
        剩 = self.每分上限 - len(self._最近送翻)
        return max(0, min(剩, int(self._額度 + 1e-9)))

    def 處理一次(self):
        """看緩衝該不該送出一批；該送就送（呼叫模型，同步等回答）。有呼叫模型回傳 True。"""
        while True:
            try:
                self._緩衝.append(self._佇列.get_nowait())
            except queue.Empty:
                break
        if not self._緩衝:
            return False
        現在 = self.時鐘()
        if 現在 < self._暫停到:                       # 429 暫停中：這段時間的留言都不翻（以原文顯示）
            self._放棄(self._緩衝, "限速放棄")
            self._緩衝.clear()
            return False
        if not self.啟用中():                          # 中途關掉面板或設定：排隊中的也不翻
            self._放棄(self._緩衝, "逾時放棄")
            self._緩衝.clear()
            return False
        新 = [x for x in self._緩衝 if 現在 - x[0] <= 最久等待秒]
        self._放棄([x for x in self._緩衝 if 現在 - x[0] > 最久等待秒], "逾時放棄")
        self._緩衝[:] = 新
        if not 新 or (len(新) < 批次則數 and 現在 - 新[0][0] < 批次秒數):
            return False
        批 = 新[:批次則數]
        del self._緩衝[:批次則數]
        選 = 抽樣(批, self._本批額度(現在))
        self._放棄([x for x in 批 if x not in 選], "抽樣略過")
        if not 選:
            return False
        self._額度 -= len(選)
        self._最近送翻.extend([現在] * len(選))
        self.統計["送翻"] += len(選)
        里程碑.標記(里程碑.聊天第一批送出, 則數=len(選), 等了秒=round(現在 - 選[0][0], 1))
        self._翻(選)
        return True

    def _翻(self, 批):
        開始 = self.時鐘()
        try:
            回答 = self.呼叫(提示詞([t for _, _, t in 批]))
        except llm.限速錯誤:
            self._暫停到 = self.時鐘() + 限速暫停秒
            self.統計["限速次數"] += 1
            self._放棄(批, "限速放棄")
            里程碑.標記(里程碑.聊天第一批回來, 失敗="限速")
            events.送出("info", 印出=f"（聊天室翻譯碰到 API 速率限制，暫停 {限速暫停秒} 秒；這段時間的留言只顯示原文，字幕翻譯不受影響）")
            self.送狀態()
            return
        except Exception as e:      # noqa: BLE001  任何錯誤（連線、金鑰、伺服器）都只顯示原文、不重送，不能讓翻譯執行緒停掉
            self._放棄(批, "失敗")
            錯誤 = llm.錯誤描述(e)
            里程碑.標記(里程碑.聊天第一批回來, 失敗=type(e).__name__)
            寫紀錄(f"翻譯失敗：{len(批)} 則，錯誤類型={錯誤}，花了 {self.時鐘() - 開始:.2f} 秒")
            self._說明一次("失敗", 失敗說明.format(原因="呼叫模型出錯"))
            self.送狀態()
            return
        秒 = self.時鐘() - 開始
        self._API秒們.append(秒)
        里程碑.標記(里程碑.聊天第一批回來, API秒=round(秒, 2))
        譯們 = subtitle.讀譯文(回答) or []
        if len(譯們) != len(批):             # 句數對不上：對得上的照用，缺的只顯示原文
            self.統計["失敗"] += len(批) - min(len(譯們), len(批))
            原因 = "讀不出譯文" if not 譯們 else f"則數對不上：送 {len(批)} 則、回 {len(譯們)} 則"
            寫紀錄(f"翻譯失敗：{原因}，stop_reason={llm.停止原因們.get('聊天翻譯') or '（無）'}，API {秒:.2f} 秒，"
                 f"回答 {len(回答 or '')} 字：{(回答 or '')[:300]!r}")
            self._說明一次("失敗", 失敗說明.format(原因=原因))
        譯們 = (譯們 + [""] * len(批))[:len(批)]
        for (_, 編號, _), 譯 in zip(批, 譯們, strict=True):
            if 譯:
                self.統計["已翻"] += 1
            self.排隊.定案(編號, 譯 or None)
        self.送狀態()

    # ---------- 用量 ----------
    def 費用(self):
        u = llm.聊天翻譯用量
        if u["缺token"]:
            return None
        return model_catalog.算費用(u["輸入"], u["輸出"], self.單價)     # 單價未知 → model_catalog.未知

    def 送狀態(self):
        events.送出("status", 聊天翻譯次數=llm.聊天翻譯用量["次數"], 聊天翻譯費用=self.費用())

    def 統計文字(self):
        u = llm.聊天翻譯用量
        if not u["次數"]:
            return ""
        費用 = self.費用()
        不翻 = sum(n for k, n in self.不翻原因們.items() if k != "不是外語直播")
        翻 = f"，翻了 {self.統計['已翻']} 則" + (f"，{不翻} 則不需要翻（表情、草、常見短語等）" if 不翻 else "")
        if 費用 is None:
            return f"聊天室翻譯（另計）：呼叫 {u['次數']} 次{翻}，token 與費用無法計算"
        if 費用 == model_catalog.未知:
            return f"聊天室翻譯（另計）：呼叫 {u['次數']} 次{翻}，輸入 {u['輸入']} / 輸出 {u['輸出']} token，{model_catalog.未知字}"
        return (f"聊天室翻譯（另計）：呼叫 {u['次數']} 次{翻}，輸入 {u['輸入']} / 輸出 {u['輸出']} token，"
                f"估算 {費用:.3f} 美元（金額為估算，實際以 API 帳單為準）")
