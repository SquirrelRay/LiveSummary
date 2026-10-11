# 逐句字幕（只有介面會用，命令列不會用到）
# 原文模式：收到 transcript_line 就直接送出 subtitle 事件，不花 API。
# 翻譯模式：每累積約 8 秒或 4 句（config.json 的 translate_batch_seconds／translate_batch_lines 可調），批次翻成台灣慣用繁體中文再送出；翻譯失敗就送原文。
# 翻譯的呼叫次數與 token 另外記在 llm.翻譯用量，不和摘要混在一起。
# 翻譯模式的每一句（原文、譯文）另外送出 translation_line 事件給「逐句翻譯」分頁，並即時存成「原檔名_逐句翻譯.txt」：
# 檔案在第一句寫入時才建立、已有同名舊檔就改用加了時間的新檔名（不覆蓋）；翻譯失敗或逾時沒翻的句子存原文並標「未翻譯」。
import os
import re
import json
import time
import queue
import threading

import events
import llm

批次秒數 = 8      # 第一句進來後最多等幾秒就翻（開始時由 config.json 覆蓋）
批次句數 = 4      # 累積幾句就翻（開始時由 config.json 覆蓋）
每批上限 = 8      # 一次最多翻幾句（翻譯慢、句子塞車時用）

翻譯規則 = (
    "把下面的直播逐句字幕翻成台灣慣用的繁體中文，給觀眾即時看。\n"
    "規則：\n"
    "- 一律用繁體中文，不可出現簡體字。\n"
    "- 日文的漢字詞也要翻成台灣慣用的中文詞（例如 赤→紅、円→日圓），不可沿用日文漢字或日文字形（例如 獣→獸）。\n"
    "- 作品名、人名、遊戲名等專有名詞，翻成中文後把原文放在括號裡，例如「艾連（エレン）」；不確定怎麼翻就直接寫原文。\n"
    "- 正文不可夾雜假名或英文單字，專有名詞的原文除外（放在括號裡）。\n"
    "- 口語、簡短，一句對一句，不要加解釋。\n\n"
    "只回傳 JSON 陣列，不要其他文字，陣列長度必須和句數一樣，順序相同：[\"第1句譯文\", \"第2句譯文\", ...]\n\n"
    "字幕：\n"
)


def 要翻譯(模式, 語言, 文字):
    """模式：original / translate / auto。auto：中文直播用原文，其他語言翻譯。"""
    if 模式 == "original":
        return False
    if 模式 == "translate":
        return True
    if 語言 == "zh":
        return False
    if 語言 in ("ja", "en", "ko"):
        return True
    # 語言是 auto（自動偵測）：看這句字來判斷——有假名或韓文、或完全沒有中文字，就翻譯
    if re.search(r"[぀-ヿ가-힯]", 文字):
        return True
    return not re.search(r"[一-鿿]", 文字)


def 讀譯文(回答):
    """從模型的回答裡讀出譯文清單。回答前後可能多了說明文字或程式碼框，所以不能整段直接讀：
    找出回答裡每一個 JSON 陣列，優先用「最後一個」（模型有時會先寫一段說明，最後才給正式答案）。讀不出來回傳 None。"""
    解碼 = json.JSONDecoder()
    找到 = []
    for m in re.finditer(r"\[", 回答):
        try:
            物件, _ = 解碼.raw_decode(回答, m.start())
        except ValueError:
            continue
        if isinstance(物件, list) and 物件 and all(isinstance(x, str) for x in 物件):
            找到.append([x.strip() for x in 物件])
    return 找到[-1] if 找到 else None


class 字幕器:
    def __init__(self):
        self.啟用 = False          # 疊加層開著才產生字幕（關著就不翻，省錢）
        self._執行緒 = None
        self._停 = threading.Event()
        self._停.set()             # 還沒開始
        self._佇列 = queue.Queue()
        self._緩衝 = []            # 已收到、還沒送去翻的句子
        self._進行中 = False       # 有一批正在翻
        self._收尾 = threading.Event()   # 按了停止：把剩下的句子翻完再結束
        self.收尾完成 = threading.Event()
        self.收尾剩 = 0            # 按停止時還沒翻的句數（測試與回報用）
        self.收尾翻 = 0            # 收尾時實際翻好幾句
        self.延遲們 = []           # 每批「第一句進來 → 翻好顯示」花了幾秒
        self.模式, self.語言, self.模型, self.單價 = "auto", "zh", "", (0, 0)
        self.存檔基底 = None       # 「原檔名」（不含副檔名），由介面在收到 files 事件時設定
        self.存檔路徑 = None       # 第一句寫入後才有
        self._檔鎖 = threading.Lock()
        self._緩衝鎖 = threading.Lock()

    def 開始(self, 模式, 語言, 模型, 單價輸入, 單價輸出, 秒數=None, 句數=None):
        global 批次秒數, 批次句數
        self.結束()
        if 秒數:
            批次秒數 = 秒數
        if 句數:
            批次句數 = int(句數)
        self.模式, self.語言, self.模型 = 模式, 語言, 模型
        self.單價 = (單價輸入, 單價輸出)
        for k in llm.翻譯用量:
            llm.翻譯用量[k] = 0
        self.延遲們 = []
        self.存檔基底 = self.存檔路徑 = None
        self._停 = threading.Event()
        self._佇列 = queue.Queue()
        self._緩衝 = []
        self._進行中 = False
        self._收尾 = threading.Event()
        self.收尾完成 = threading.Event()
        self.收尾剩 = self.收尾翻 = 0
        self._執行緒 = threading.Thread(target=self._跑, daemon=True)
        self._執行緒.start()

    def 結束(self):
        """這一場結束：還沒翻的句子就不翻了（存檔裡標「未翻譯」）。"""
        self._停.set()
        self._放棄剩下()

    def _放棄剩下(self):
        """緩衝與佇列裡還沒翻的句子，記成「未翻譯」。可重複呼叫（每句只記一次）。"""
        with self._緩衝鎖:
            剩 = list(self._緩衝)
            self._緩衝.clear()
            while True:
                try:
                    剩.append(self._佇列.get_nowait())
                except queue.Empty:
                    break
        for _, 時間字, 原文 in 剩:
            self._記錄(時間字, 原文, "")

    def _記錄(self, 時間字, 原文, 譯):
        """記下翻譯模式的一句：寫進逐句翻譯存檔，並送出 translation_line 事件。譯 = 空字串代表沒翻到。"""
        with self._檔鎖:
            路徑 = self._寫存檔(時間字, 原文, 譯)
        events.送出("translation_line", 時間字=時間字, 原文=原文, 譯文=譯 or None, 已翻譯=bool(譯), 檔案=路徑)

    def _寫存檔(self, 時間字, 原文, 譯):
        if not self.存檔基底:
            return None
        try:
            if self.存檔路徑 is None:       # 第一句才建立；舊檔已存在就換新檔名，絕不覆蓋
                後綴, 號 = "", 1
                while os.path.exists(self.存檔基底 + "_逐句翻譯" + 後綴 + ".txt"):
                    後綴 = "_" + time.strftime("%Y%m%d-%H%M") + ("" if 號 == 1 else f"_{號}")
                    號 += 1
                self.存檔路徑 = os.path.abspath(self.存檔基底 + "_逐句翻譯" + 後綴 + ".txt")
            with open(self.存檔路徑, "a", encoding="utf-8") as f:
                f.write(f"[{時間字}] {原文}" + chr(10) + "　　→ " + (譯 if 譯 else "【未翻譯】") + chr(10))
        except Exception:
            return None
        return self.存檔路徑

    def 有待翻(self):
        """還有句子沒翻（含正在翻的那一批）。"""
        return bool(self._執行緒 and self._執行緒.is_alive() and not self._停.is_set()
                    and (self._緩衝 or self._進行中 or not self._佇列.empty()))

    def 收尾(self):
        """按了停止：不再收新句子，把還沒翻的翻完（翻譯在背景執行緒做；完成時 收尾完成 會被設起來）。
        呼叫的人負責設逾時：超時就呼叫 結束() 放棄，剩下的句子不再重送。"""
        self.收尾剩 = len(self._緩衝) + self._佇列.qsize()
        self._收尾.set()

    def 接收(self, 種類, 內容):
        """events 的接收者：只處理 transcript_line（另外記下自動偵測到的語言）。"""
        if 種類 == "language_detected":
            self.語言 = 內容["語言"]
            return
        if 種類 != "transcript_line" or not self.啟用 or self._停.is_set() or self._收尾.is_set():
            return
        文字 = 內容["內容"]
        if not 文字:
            return
        if 要翻譯(self.模式, self.語言, 文字):
            self._佇列.put((time.time(), 內容["時間字"], 文字))
        else:
            events.送出("subtitle", 時間字=內容["時間字"], 文字=文字, 已翻譯=False)

    def _排乾(self, 緩衝):
        """收尾：把剩下的句子一批一批翻完（失敗不重送，顯示原文）。被放棄（結束()）就立刻停。"""
        while True:
            try:
                緩衝.append(self._佇列.get_nowait())
            except queue.Empty:
                break
        while 緩衝 and not self._停.is_set():
            with self._緩衝鎖:
                批, 緩衝[:] = 緩衝[:每批上限], 緩衝[每批上限:]
            if not 批:
                break
            self._進行中 = True
            譯們 = self._翻(批)
            self._進行中 = False
            if self._停.is_set():      # 超時被放棄：這批不顯示字幕了，但用量還是要算；翻好的照樣記進逐句翻譯
                for (_, 時間字, 原文), 譯 in zip(批, 譯們):
                    self._記錄(時間字, 原文, 譯)
                self.送狀態()
                return
            for (_, 時間字, 原文), 譯 in zip(批, 譯們):
                events.送出("subtitle", 時間字=時間字, 文字=譯 or 原文, 已翻譯=bool(譯))
                self._記錄(時間字, 原文, 譯)
            self.收尾翻 += len(批)
            self.延遲們.append(time.time() - 批[0][0])
            self.送狀態()
        self.收尾完成.set()

    def _跑(self):
        緩衝 = self._緩衝
        while not self._停.is_set():
            try:
                緩衝.append(self._佇列.get(timeout=0.3))
            except queue.Empty:
                pass
            if self._收尾.is_set():
                self._排乾(緩衝)
                return
            if not 緩衝:
                continue
            if len(緩衝) < 批次句數 and time.time() - 緩衝[0][0] < 批次秒數:
                continue
            with self._緩衝鎖:
                批, 緩衝[:] = 緩衝[:每批上限], 緩衝[每批上限:]
            if not 批:
                continue
            self._進行中 = True
            譯們 = self._翻(批)
            self._進行中 = False
            if self._停.is_set():      # 按了停止：這批不顯示字幕了，但用量還是要算；翻好的照樣記進逐句翻譯
                for (_, 時間字, 原文), 譯 in zip(批, 譯們):
                    self._記錄(時間字, 原文, 譯)
                self.送狀態()
                return
            for (_, 時間字, 原文), 譯 in zip(批, 譯們):
                events.送出("subtitle", 時間字=時間字, 文字=譯 or 原文, 已翻譯=bool(譯))
                self._記錄(時間字, 原文, 譯)
            self.延遲們.append(time.time() - 批[0][0])
            self.送狀態()
        self._放棄剩下()

    def _翻(self, 批):
        """回傳每句的譯文；失敗的句子是空字串（顯示原文）。任何錯誤都不往外丟。"""
        提示詞 = 翻譯規則 + "\n".join(f"{i + 1}. {原文}" for i, (_, _, 原文) in enumerate(批))
        回答 = ""
        try:
            回答 = llm.call_llm(提示詞, self.模型, 類別="翻譯")
        except Exception as e:
            self._記錄失敗(批, 回答, e)
            events.送出("info", 印出="（這幾句翻譯失敗，暫時顯示原文）")
            return [""] * len(批)
        譯們 = 讀譯文(回答)
        if 譯們 is None:                 # 讀不出來：不重送（避免多花錢），直接顯示原文
            self._記錄失敗(批, 回答, ValueError("讀不出譯文"))
            events.送出("info", 印出="（這幾句翻譯失敗，暫時顯示原文）")
            return [""] * len(批)
        if len(譯們) != len(批):         # 句數對不上：對得上的照常顯示，缺的那幾句顯示原文
            self._記錄失敗(批, 回答, ValueError(f"句數對不上（要 {len(批)} 句，收到 {len(譯們)} 句）"))
            events.送出("info", 印出="（有幾句翻譯缺漏，缺的暫時顯示原文）")
            譯們 = (譯們 + [""] * len(批))[:len(批)]
        return 譯們

    def _記錄失敗(self, 批, 回答, 錯誤):
        """翻譯失敗時把模型原始回傳、停止原因、句數寫進 翻譯錯誤紀錄.txt（找原因用）。"""
        try:
            with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "翻譯錯誤紀錄.txt"), "a", encoding="utf-8") as f:
                f.write(f"=== {time.strftime('%H:%M:%S')} 送 {len(批)} 句；停止原因={llm.最後停止原因}；"
                        f"錯誤={type(錯誤).__name__}；回傳 {len(回答)} 字 ===" + chr(10) + 回答 + chr(10) + chr(10))
        except Exception:
            pass

    def 費用(self):
        u = llm.翻譯用量
        if u["缺token"]:
            return None
        return u["輸入"] / 1e6 * self.單價[0] + u["輸出"] / 1e6 * self.單價[1]

    def 送狀態(self):
        u = llm.翻譯用量
        events.送出("status", 翻譯次數=u["次數"], 翻譯輸入=u["輸入"], 翻譯輸出=u["輸出"], 翻譯費用=self.費用(),
                    翻譯延遲=(sum(self.延遲們) / len(self.延遲們)) if self.延遲們 else None)

    def 統計文字(self):
        u = llm.翻譯用量
        if not u["次數"]:
            return ""
        費用 = self.費用()
        延遲 = f"，平均延遲約 {sum(self.延遲們) / len(self.延遲們):.1f} 秒" if self.延遲們 else ""
        if 費用 is None:
            return f"逐句翻譯（另計）：呼叫 {u['次數']} 次，token 與費用無法計算{延遲}"
        return (f"逐句翻譯（另計）：呼叫 {u['次數']} 次，輸入 {u['輸入']} / 輸出 {u['輸出']} token，"
                f"估算 {費用:.3f} 美元（單價未查證）{延遲}")
