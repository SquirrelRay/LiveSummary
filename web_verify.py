# 上網查證詞庫的候選名詞（config.json 的 web_verify，預設關；命令列 --web / --no-web）
# 候選＝話題摘要自動加入詞庫的名詞，模型常寫錯（例如音譯、日文字形）。開關打開時，用 Claude 官方的上網搜尋工具查證：
#   查到有可靠來源的台灣通行寫法 → 詞庫那一行改成「上網」、最後一欄放來源網址（之後的摘要與下一場都會用）；
#   搜尋過、確定找不到 → 保持候選，最後一欄標「已查」，之後不再查（避免重複花錢）；
#   沒查成（逾時、API 錯誤、速率限制、沒真的搜尋）→ 什麼都不改，下次還能再查。
# 網址只接受上網搜尋工具真的回傳過的（搜尋結果或引用）；模型自己打出來的網址一律當作查無。
# 直播中：只查這一場新加入的候選，在背景執行緒查，不擋字幕、換話題判斷與分鐘摘要；每場最多 每場上限 個。
# 以前留下、還沒查過的候選：用 scripts/verify_glossary.py 手動查。
import json
import queue
import re
import threading
import time

import events
import glossary
import llm

每場上限 = 10           # 每一場（或小工具每次執行）最多查幾個名詞
每詞最多搜尋 = 2        # 每個名詞最多搜尋幾次（web_search 的 max_uses）；一次通常就找得到官方譯名，多一次給換關鍵字
收尾等待秒 = 30         # 結束（或按停止）後最多等背景查證幾秒；沒查完的保持未查
每詞句數 = 2            # 附上稿裡出現這個名詞的幾句

查證提示 = (
    "你要上網查證一個專有名詞在台灣通行的繁體中文寫法，結果會寫進直播摘要用的名詞詞庫。\n"
    "名詞原文：{原文}\n"
    "摘要模型給的中文寫法（可能是錯的）：{寫法}\n"
    "直播主：{直播主}\n"
    "直播分類／遊戲：{分類}\n"
    "直播標題：{標題}\n"
    "這個名詞在語音稿裡出現的句子（語音辨識的結果，可能有錯字）：\n{句子}\n\n"
    "請用 web_search 搜尋後判斷：\n"
    "- 只接受有可靠來源支持的台灣通行寫法：官方中文譯名、台灣代理商或發行商、台灣的新聞媒體、中文維基百科（台灣用詞）等。\n"
    "- 搜尋結果裡找不到可靠來源時，回答查無。不可以自己翻譯、音譯或推測寫法；摘要模型給的寫法沒有來源支持，也要回答查無。\n"
    "- 原文其實是一般詞彙（任何人都會用的普通名詞，不是人名、作品名、遊戲名、角色名、團體名、店名或地名等專有名詞），或疑似語音辨識錯誤、查不到對應的名詞時，也回答查無。\n"
    "- 原文是語音辨識的結果，可能有錯字（例如片假名被寫成漢字、長音或濁音不對，像 ドラゴン球 其實是 ドラゴンボール）；"
    "照原文查不到時，用你判斷的正確原文再搜尋一次，但最後的寫法仍然必須有搜尋結果支持。\n"
    "- 搜尋結果顯示原文本身寫錯（例如語音辨識把片假名寫成漢字）時，original 填正確的原文；原文沒錯就填空字串。\n"
    "- url 必須是這次搜尋結果裡、能支持這個寫法的網頁網址。\n"
    "回答的最後一行只輸出一個 JSON，不要其他文字：\n"
    '查到：{{"result": "found", "written": "台灣通行寫法（繁體中文）", "url": "來源網址", "original": "正確原文或空字串"}}\n'
    '查無：{{"result": "none", "reason": "一句話說明"}}'
)


def 句子們(原文, 寫法, 稿行們, 最多=每詞句數):
    """稿裡出現這個名詞（原文，沒有原文就看寫法）的前幾句，去掉行首時間。"""
    鍵 = 原文 or 寫法
    結果 = [re.sub(r"^\[[^\]]*\]\s*", "", 行).strip() for 行 in 稿行們 if 鍵 and 鍵 in 行]
    return [x for x in 結果 if x][:最多]


def 提示詞(e, 脈絡, 句們):
    return 查證提示.format(
        原文=e.原文 or "（沒有原文）", 寫法=e.寫法, 直播主=脈絡.get("直播主") or "不明",
        分類=脈絡.get("分類") or "不明", 標題=脈絡.get("標題") or "不明",
        句子="\n".join(f"- {s}" for s in 句們) or "（沒有找到）")


def _最後JSON(文字):
    解碼 = json.JSONDecoder()
    找到 = None
    for m in re.finditer(r"\{", 文字):
        try:
            物件, _ = 解碼.raw_decode(文字, m.start())
        except ValueError:
            continue
        if isinstance(物件, dict) and "result" in 物件:
            找到 = 物件
    return 找到


def _網址鍵(網址):
    return re.sub(r"#.*$", "", 網址.strip()).rstrip("/").lower()


def 判讀(回覆):
    """llm.上網搜尋() 的回覆 → (狀態, 寫法, 網址, 正式原文, 說明)。狀態：確認／查無／失敗。
    失敗＝沒查成（沒有任何一次搜尋成功、回覆看不懂），之後可以再查；查無才會標「已查」。"""
    if 回覆["搜尋成功"] == 0:
        原因 = "、".join(回覆["搜尋錯誤"]) or "模型沒有搜尋"
        return "失敗", "", "", "", f"沒有成功的搜尋（{原因}）"
    資料 = _最後JSON(回覆["文字"])
    if not 資料:
        return "失敗", "", "", "", "回覆看不懂"
    if 資料.get("result") != "found":
        return "查無", "", "", "", str(資料.get("reason", "")).strip()[:60]
    寫法 = str(資料.get("written", "")).strip()
    網址 = str(資料.get("url", "")).strip()
    原文 = str(資料.get("original", "")).strip()
    if not 寫法 or len(寫法) > glossary.最長 or glossary.分隔.search(寫法) or glossary._日文(寫法):
        return "查無", "", "", "", f"寫法不合格（{寫法 or '空的'}）"
    真的網址 = {_網址鍵(u): u for u in 回覆["網址們"]}
    if _網址鍵(網址) not in 真的網址:
        return "查無", "", "", "", "來源網址不在搜尋結果裡"
    return "確認", 寫法, 真的網址[_網址鍵(網址)], 原文 if len(原文) <= glossary.最長 else "", ""


def 查詢(e, 脈絡, 稿行們, 模型):
    """問一個候選（不寫檔）。回傳 (狀態, 寫法, 網址, 正式原文, 說明)。金鑰錯誤以外的例外都當作「失敗」。"""
    try:
        return 判讀(llm.上網搜尋(提示詞(e, 脈絡, 句子們(e.原文, e.寫法, 稿行們)), 模型, 每詞最多搜尋))
    except llm.查證失敗 as ex:
        return "失敗", "", "", "", f"沒查成（{ex}）"
    except llm.模型錯誤:
        raise
    except Exception as ex:          # noqa: BLE001 任何意外都不能影響摘要
        return "失敗", "", "", "", f"沒查成（{type(ex).__name__}）"


def 寫回(詞庫, e, 結果):
    """查詢() 的結果寫回詞庫，回傳 (狀態, 說明文字)。失敗不寫，保持未查。"""
    狀態, 寫法, 網址, 正式原文, 說明 = 結果
    if 狀態 == "失敗":
        return "失敗", f"{e.顯示()}：{說明}，保持未查"
    try:
        詞庫.套用查證(e.鍵(), 寫法 if 狀態 == "確認" else None, 網址, 正式原文)
    except OSError as ex:
        return "失敗", f"{e.顯示()}：詞庫存檔失敗（{ex}），保持未查"
    if 狀態 == "確認":
        附 = f"，正式原文：{正式原文}" if 正式原文 and 正式原文 != e.原文 else ""
        return "確認", f"{e.顯示()} → {寫法}（{網址}{附}）"
    return "查無", f"{e.顯示()}：查無（{說明}），標為已查"


def 查一個(詞庫, e, 脈絡, 稿行們, 模型):
    """查一個候選並寫回詞庫（小工具用）。回傳 (狀態, 說明文字)。"""
    return 寫回(詞庫, e, 查詢(e, 脈絡, 稿行們, 模型))


class 背景查證:
    """直播中在背景查這一場新加入的候選。加入() 不會等；收尾() 最多等 收尾等待秒。"""

    def __init__(self, 詞庫, 脈絡, 模型, 上限=每場上限):
        self.詞庫, self.脈絡, self.模型, self.上限 = 詞庫, 脈絡, 模型, 上限
        self.計數 = {"查": 0, "確認": 0, "查無": 0, "失敗": 0, "略過": 0}
        self._佇列 = queue.Queue()
        self._停 = threading.Event()
        self._鎖 = threading.Lock()
        self._進行中 = 0
        self._閒 = threading.Condition(self._鎖)
        threading.Thread(target=self._跑, daemon=True).start()

    def 加入(self, 條目們, 稿行們):
        """條目們：這一題剛自動加入的候選。超過每場上限的略過（保持未查，之後用小工具查）。"""
        with self._鎖:
            for e in 條目們:
                if self._停.is_set():
                    return
                if self.計數["查"] >= self.上限:
                    self.計數["略過"] += 1
                    continue
                self.計數["查"] += 1
                self._進行中 += 1
                self._佇列.put((e, list(稿行們)))

    def _跑(self):
        while True:
            項 = self._佇列.get()
            if 項 is None:
                return
            e, 稿行們 = 項
            狀態 = "失敗"
            try:
                if self._停.is_set():
                    pass                                   # 已經收尾：排隊中的不查，保持未查
                elif not self.詞庫.還要查(e.鍵()):
                    events.送出("info", 印出=f"上網查證：{e.顯示()}：詞庫裡已不是待查的候選，略過")
                else:
                    結果 = 查詢(e, self.脈絡, 稿行們, self.模型)
                    with self._鎖:                         # 寫回也拿著鎖：收尾不會在寫到一半時算數字
                        if not self._停.is_set():          # 收尾時間到了才回來：不寫回，保持未查
                            狀態, 字 = 寫回(self.詞庫, e, 結果)
                            events.送出("info", 印出="上網查證：" + 字)
            except llm.模型錯誤 as ex:
                events.送出("info", 印出=f"上網查證停止：{ex}")
                self._停.set()
            except Exception as ex:      # noqa: BLE001 背景執行緒不能讓整場停掉
                events.送出("info", 印出=f"上網查證出錯（{type(ex).__name__}），這個名詞保持未查")
            with self._鎖:
                if not self._停.is_set() or 狀態 != "失敗":
                    self.計數[狀態] += 1
                self._進行中 -= 1
                self._閒.notify_all()

    def 進行中(self):
        with self._鎖:
            return self._進行中

    def 收尾(self, 最久=收尾等待秒):
        """不再接新的，最多等 最久 秒讓排隊中的查完；沒查完的保持未查（之後回來的結果仍照規則寫回或丟掉）。回傳結束訊息那一行。"""
        截止 = time.monotonic() + 最久
        with self._鎖:
            while self._進行中 and time.monotonic() < 截止:
                self._閒.wait(min(0.2, max(0.0, 截止 - time.monotonic())))
            self._停.set()
            c = dict(self.計數)
        self._佇列.put(None)          # 讓背景執行緒結束（正在查的那一個回來後就結束）
        return 結束文字(c, self.上限)


def 結束文字(c, 上限=每場上限):
    未完成 = c["查"] - c["確認"] - c["查無"]
    行 = f"上網查證：查 {c['查']} 個，確認 {c['確認']} 個，查無 {c['查無']} 個，未完成 {未完成} 個"
    if c.get("略過"):
        行 += f"（超過上限 {上限} 個，另有 {c['略過']} 個沒查，保持未查）"
    return 行
