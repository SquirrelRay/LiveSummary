# 逐句字幕（只有介面會用，命令列不會用到）
# 原文模式：收到 transcript_line 就直接送出 subtitle 事件，不花 API。
# 翻譯模式：每累積約 8 秒或 4 句（config.json 的 translate_batch_seconds／translate_batch_lines 可調），批次翻成台灣慣用繁體中文再送出；翻譯失敗就送原文。
# 翻譯的呼叫次數與 token 另外記在 llm.翻譯用量，不和摘要混在一起。
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


class 字幕器:
    def __init__(self):
        self.啟用 = False          # 疊加層開著才產生字幕（關著就不翻，省錢）
        self._執行緒 = None
        self._停 = threading.Event()
        self._停.set()             # 還沒開始
        self._佇列 = queue.Queue()
        self.延遲們 = []           # 每批「第一句進來 → 翻好顯示」花了幾秒
        self.模式, self.語言, self.模型, self.單價 = "auto", "zh", "", (0, 0)

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
        self._停 = threading.Event()
        self._佇列 = queue.Queue()
        self._執行緒 = threading.Thread(target=self._跑, daemon=True)
        self._執行緒.start()

    def 結束(self):
        """這一場結束：還沒翻的句子就不翻了。"""
        self._停.set()

    def 接收(self, 種類, 內容):
        """events 的接收者：只處理 transcript_line（另外記下自動偵測到的語言）。"""
        if 種類 == "language_detected":
            self.語言 = 內容["語言"]
            return
        if 種類 != "transcript_line" or not self.啟用 or self._停.is_set():
            return
        文字 = 內容["內容"]
        if not 文字:
            return
        if 要翻譯(self.模式, self.語言, 文字):
            self._佇列.put((time.time(), 內容["時間字"], 文字))
        else:
            events.送出("subtitle", 時間字=內容["時間字"], 文字=文字, 已翻譯=False)

    def _跑(self):
        緩衝 = []
        while not self._停.is_set():
            try:
                緩衝.append(self._佇列.get(timeout=0.3))
            except queue.Empty:
                pass
            if not 緩衝:
                continue
            if len(緩衝) < 批次句數 and time.time() - 緩衝[0][0] < 批次秒數:
                continue
            批, 緩衝 = 緩衝[:每批上限], 緩衝[每批上限:]
            譯們 = self._翻(批)
            if self._停.is_set():      # 按了停止：這批不顯示了，但用量還是要算
                self.送狀態()
                return
            for (_, 時間字, 原文), 譯 in zip(批, 譯們):
                events.送出("subtitle", 時間字=時間字, 文字=譯 or 原文, 已翻譯=bool(譯))
            self.延遲們.append(time.time() - 批[0][0])
            self.送狀態()

    def _翻(self, 批):
        """回傳每句的譯文；失敗的句子是空字串（顯示原文）。任何錯誤都不往外丟。"""
        提示詞 = 翻譯規則 + "\n".join(f"{i + 1}. {原文}" for i, (_, _, 原文) in enumerate(批))
        try:
            回答 = llm.call_llm(提示詞, self.模型, 類別="翻譯")
            譯們 = json.loads(re.search(r"\[.*\]", 回答, re.S).group(0))
            譯們 = [str(x).strip() for x in 譯們]
            if len(譯們) != len(批):
                return [""] * len(批)
            return 譯們
        except Exception as e:
            events.送出("info", 印出=f"（逐句翻譯失敗，先顯示原文：{type(e).__name__}）")
            return [""] * len(批)

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
