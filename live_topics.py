# 模擬即時的「分話題摘要」引擎
# 用法：python live_topics.py 文字稿.txt --check 1 --speed 0
#   --check 幾分鐘（直播時間）檢查一次話題有沒有換，預設 1
#   --speed 重播速度：0 = 瞬間跑完（測試用）、60 = 60 倍速、1 = 真實速度
import os
import re
import sys
import json
import time
import argparse

import summarize  # 重用 call_llm、summarize_chunk，不改動它原本的功能
import llm        # 呼叫語言模型、錯誤種類、token 用量都在這裡
import events     # 結果不直接 print，改成送出事件（終端機和介面都是接收者）
import subtitle_speed   # 字幕速度段位：分段秒數與翻譯批次
import config           # 設定檔 config.json 的預設、檢查、讀取都在這裡
import timefmt          # 時間格式（未滿 1 小時 mm:ss、滿 1 小時 h:mm:ss）
import stream_clock     # 這一場的直播時軸（抓不到開播時間時，時間字前面加 +）
import glossary         # 直播主專有名詞詞庫（詞庫/直播主.txt）
import web_verify       # 上網查證詞庫的候選名詞（預設關）

# ---- 可以調整的設定 ----
# 下面三個由 執行() 依設定改寫，起始值 = config.py 的出廠預設
MIN_TOPIC_MIN = config.出廠預設()["min_topic_min"]     # 話題未滿幾分鐘，忽略「換話題」的判斷
MAX_TOPIC_MIN = config.出廠預設()["max_topic_min"]     # 話題超過幾分鐘，強制結束並開新話題
MIN_NEW_CHARS = 100   # 新文字少於這麼多字，這一輪跳過判斷
MINUTE_SENTENCES = config.出廠預設()["minute_sentences"]     # 分鐘摘要句數上限（1 到 3，可在 config.json 改）
MAX_SIDE_PER_CHECK = 2   # 每次判斷最多回報幾條支線
MAX_SIDE_PER_TOPIC = 5   # 每個話題最多保留幾條支線（超過就保留較早的）
# 「支線」的標準（現在是「窄」的）。想改成「寬」就改這段文字，例如把要求放寬成
# 「任何與主話題無關的閒聊都算，包含感謝訂閱、口頭禪以外的所有插曲」。
說話者規則 = (
    "【說話者】語音稿沒有標示誰在說話，直播可能有多人（合作、連線通話、遊戲語音、影片或角色的聲音）。\n"
    "- 稿裡出現的人名預設是「被提到、被呼喊的人」，不是說話的人。不可推論「實況主就是某某」，"
    "也不可用被提到的人名當主詞去描述說話的內容（例如稿裡有人喊「小明」，不可寫成「小明表示…」）。\n"
    "- 看不出是誰說的，就用「有人提到」「對話中提到」「有人說」這類中性說法，不要一律寫成「實況主說」。\n"
    "- 明顯是實況主自己說的（單人獨白、自稱「我」談自己的事、回應聊天室留言）照常寫「實況主」，不必每句都改成中性說法。\n"
    "- 這些規則適用於所有輸出欄位，包含目前這一題的那一件事、話題簡述、分鐘摘要、話題摘要與支線。\n"
)
支線說話者 = "支線的描述同樣遵守【說話者】規則：人名是被提到的人，看不出是誰說的就用中性說法。"
支線標準 = (
    "支線 = 實況主短暫離開主話題，閒聊了與主話題無關、但有資訊價值的內容"
    "（例如提到某個東西、近況、做了某個決定、跟觀眾的小插曲）。"
    "純粹的口頭禪、語助詞、單純的「謝謝訂閱」類感謝，不算支線。"
    "每次最多回報 2 條，沒有就回空陣列。" + 支線說話者
)

時間標記 = timefmt.時間標記     # 行首的 [mm:ss]／[h:mm:ss]／[+mm:ss]


def 轉秒(行):
    return timefmt.轉秒(行)


def 秒轉字(秒):
    """格式統一由 timefmt 決定；這一場抓不到開播時間時前面加「+」。"""
    return timefmt.秒轉字(秒, stream_clock.加號())


def 對齊時間(秒, 候選們):
    """模型回傳的時間漏了小時（[1:23:45] 寫成 [23:45]）時補回來；候選們 = 這一輪文字稿真的出現過的秒數。"""
    return timefmt.補小時(秒, 候選們)


def stream_lines(來源, speed=0):
    """一行一行吐出 (直播秒數, 文字行)。
    之後要換成真正的即時轉錄，只要改這個函式：每有新的一句就 yield (秒數, "[mm:ss] 文字")。"""
    上一秒 = None
    with open(來源, encoding="utf-8") as f:
        for 行 in f:
            行 = 行.rstrip("\n")
            if not 行.strip() or 行.startswith("# "):     # 「# 」開頭是存檔開頭的說明（直播主、開播時間），不是文字稿
                continue
            秒 = 轉秒(行)
            if 秒 is None:          # 沒有時間戳記的行，沿用上一行的時間
                秒 = 上一秒 or 0
            if speed > 0 and 上一秒 is not None and 秒 > 上一秒:
                結束時刻 = time.time() + (秒 - 上一秒) / speed
                while time.time() < 結束時刻 and not events.停止.is_set():   # 分小段睡，按停止才能馬上生效
                    time.sleep(max(0, min(0.2, 結束時刻 - time.time())))
            if events.停止.is_set():
                return
            上一秒 = 秒
            yield 秒, 行


MAX_CHAT_PER_CHECK = 15   # 每輪最多傳幾則聊天室代表留言給模型
CHAT_REPEAT_MIN = 3       # 同一句被幾個不同的人重複，就合併成一則
MAX_CHAT_PER_TOPIC = 30   # 每個話題最多保留幾則聊天室代表留言（保留較新的）


def 代表留言(留言們):
    """留言們：[(秒, 使用者, 內容)]。回傳 [(秒, 字串)]，最多 MAX_CHAT_PER_CHECK 則。
    規則：同一句被 3 人以上重複就合併成一則；其餘照出現順序平均挑。"""
    分組 = {}
    for 秒, 人, 內容 in 留言們:
        分組.setdefault(內容.strip().lower(), []).append((秒, 人, 內容))
    重複, 其他 = [], []
    for 組 in 分組.values():
        人數 = len({人 for _, 人, _ in 組})
        if 人數 >= CHAT_REPEAT_MIN:
            重複.append((組[0][0], f"[{秒轉字(組[0][0])}] （{人數} 人重複）{組[0][2]}"))
        else:
            其他.extend((秒, f"[{秒轉字(秒)}] {人}: {內容}") for 秒, 人, 內容 in 組)
    其他.sort()
    剩 = max(MAX_CHAT_PER_CHECK - len(重複), 0)
    if len(其他) > 剩:    # 太多就平均挑，不要只看開頭
        其他 = [其他[i * len(其他) // 剩] for i in range(剩)] if 剩 else []
    return sorted(重複[:MAX_CHAT_PER_CHECK] + 其他)


# ---- 聊天室參考詞（幫摘要修正語音轉錄的專有名詞寫法，不改原始直播稿）----
REF_WINDOW_MIN = 3     # 看最近幾分鐘的聊天室
REF_MIN_USERS = 2      # 一個詞要被幾個不同的人輸入才算
MAX_REF_WORDS = 10     # 最多幾個參考詞
不算詞的字 = set("的了是我你他她它不有在就也都很這那嗎啊吧呢欸喔哈和跟與及或但而所以因為如果還要會可能什麼怎麼好對喔哦啦吶得覺喜歡想說看先又自己最後知道開始一定嘛")
常見招呼 = {"安安", "早安", "晚安", "早早", "大家", "哈哈", "笑死"}
參考詞規則 = (
    "聊天室參考詞（近期被不同人重複輸入的詞，通常是正確寫法，但只是參考，聊天室可能故意玩梗打錯字）：{詞們}\n"
    "規則：\n"
    "- 語音稿的寫法本身已經是通順、合理的詞時（包含常見的同義或異體寫法，例如爆雷與暴雷），不要改成聊天室的寫法。\n"
    "- 只有語音稿的詞明顯是辨識錯誤（讀不通、疑似同音或近音錯字），而且聊天室有對得上的參考詞時，才採用參考詞的寫法。\n"
    "- 找不到對得上的語音稿詞，不要硬改，也不要把參考詞寫成實況主說過的話。\n"
    "- 語音稿與聊天室衝突時，事實以語音稿為準，只有「寫法」可以採用聊天室的。\n\n"
)


def 找參考詞(留言們):
    """留言們：[(秒, 使用者, 內容)]。回傳最多 MAX_REF_WORDS 個詞。
    作法：只看連續的中文字，取 2 到 4 字的片段，被 2 個以上不同的人輸入就算；
    含「的、了、我」這類常用字的片段、招呼語、@提及、英文表情代碼都不算。"""
    出現 = {}   # 片段 -> 輸入過的人
    for _, 人, 內容 in 留言們:
        內容 = re.sub(r"@\S+", " ", 內容)
        for 段 in re.findall(r"[一-鿿]+", 內容):
            for n in (2, 3, 4):
                for i in range(len(段) - n + 1):
                    片 = 段[i:i + n]
                    if 片 in 常見招呼 or any(c in 不算詞的字 for c in 片):
                        continue
                    出現.setdefault(片, set()).add(人)
    候選 = {w: len(u) for w, u in 出現.items() if len(u) >= REF_MIN_USERS}
    # 較短的片段如果被更長、人數一樣的片段包住，就只留長的
    候選 = {w: n for w, n in 候選.items()
            if not any(w != v and w in v and m >= n for v, m in 候選.items())}
    排序 = sorted(候選, key=lambda w: (-候選[w], -len(w)))
    return 排序[:MAX_REF_WORDS]


def 加參考詞(話題, 詞們):
    """把這一輪的參考詞併進話題（新的排前面，最多 MAX_REF_WORDS 個）。"""
    話題["參考詞"] = list(dict.fromkeys(詞們 + 話題["參考詞"]))[:MAX_REF_WORDS]


class 聊天重播:
    """只為了測試：讀已存的聊天室檔（[mm:ss] 使用者: 內容），假裝是即時聊天室。"""

    def __init__(self, 路徑):
        self.訊息們 = []
        for 行 in open(路徑, encoding="utf-8"):
            m = re.match(r"^\[\+?(?:(\d+):)?(\d+):(\d+)\] ([^:]+): (.*)$", 行.rstrip("\n"))
            if m:
                h, mi, s, 人, 內容 = m.groups()
                self.訊息們.append((int(h or 0) * 3600 + int(mi) * 60 + int(s), 人, 內容))
        self.收到 = len(self.訊息們)
        self.過濾 = 0

    def 取出(self, 開始秒, 結束秒):
        return [m for m in self.訊息們 if 開始秒 < m[0] <= 結束秒]

    def 關閉(self):
        pass


分鐘規則 = (
    "另外請替『新文字』這一輪寫一則分鐘摘要 minute_summary（和上面的判斷在同一次回答完成）。\n"
    "- summary：只根據語音稿（新文字），只針對這一輪，{句數}繁體中文（不可出現簡體字），"
    "正文不可夾雜英文單字或日文，專有名詞的原文除外（放在括號裡）；以新文字裡一個代表性的時間戳記開頭（照文字稿原樣抄，含方括號與小時，例如 [1:23:45]）。不可把聊天室留言放進 summary。\n"
    "- audience：這一輪聊天室的反應與梗，最多 1 句，沒有明顯內容、或沒有聊天室留言就填空字串。"
    "只有 audience 可以引用聊天室留言。\n"
    "- 引用聊天室內容時一律翻成台灣慣用的繁體中文，不可保留日文原句、日文漢字字形（例如 獣→獸）或假名；"
    "www、草 等笑的表現寫成「聊天室在笑」之類的中文描述；真的需要保留原文的梗，翻成中文後把原文放在括號裡。\n"
    "- 誰先說了什麼，要以語音稿的時間順序為準；不可把語音稿裡的話寫成聊天室說的。\n\n"
)


def 取最後JSON(回答):
    """關閉思考時用：回答裡可能先有說明文字，取最後一個完整的 JSON（優先有 decision 欄位的）。讀不出來丟出 ValueError。"""
    解碼 = json.JSONDecoder()
    找到 = []
    for m in re.finditer(r"\{", 回答):
        try:
            物件, _ = 解碼.raw_decode(回答, m.start())
        except ValueError:
            continue
        if isinstance(物件, dict):
            找到.append(物件)
    有 = [o for o in 找到 if "decision" in o]
    if not (有 or 找到):
        raise ValueError("讀不出 JSON")
    return (有 or 找到)[-1]


換話題規則 = (
    "你在即時監看一場直播的文字稿，判斷『新文字』主要在聊的事，還是不是『目前話題』那一件事。\n"
    "【話題的粒度】一個話題＝一件事：話題的標題用一件事就講得完，不需要用「、」把不同的事串起來。"
    "話題長短不拘：同一件事聊 2 分鐘就是 2 分鐘一題，聊 20 分鐘就是 20 分鐘一題。\n"
    "【算 new_topic】新文字的主要內容已經是另一件事，而且不只一兩句：\n"
    "- 從一件事換到另一件不同的事，例如從午餐吃什麼換到週末要看的電影、從某款遊戲的關卡換到要不要換新手機。\n"
    "- 兩件事屬於同一個大類（例如都是「近況」「閒聊」「遊戲」「跟聊天室互動」）不代表是同一件事；"
    "要看具體在聊的那件事有沒有換。\n"
    "- 新的那件事是從原本的事自然聊過去的，也算換了；只要它已經成為新文字主要在聊的內容。\n"
    "【算 same】\n"
    "- 同一件事的細節延伸、補充、舉例、前因後果。\n"
    "- 離題一兩句又回來。\n"
    "- 短暫念聊天室留言、打招呼、感謝訂閱或贈禮。\n"
    "- 新文字太零碎，看不出主要在聊什麼。\n"
    "比對的對象一律是下面的「目前話題」：它是這個話題開始時定下的那一件事，之後不會改寫。"
    "不要因為新文字是從目前話題延伸出來的，就把新的那件事併進目前話題。\n"
)


主題分隔 = re.compile(r"以及|並且|、|與|与|及|並|并|／|/|；|，|,")
# 換話題規則裡「算 same」的內容（打招呼、感謝訂閱或贈禮、念聊天室留言）不能當錨點：提示詞要求模型不要這樣寫，
# 這裡再擋一次（只比對錨點本身那十幾個字，所以不會誤傷正常主題）。
雜訊主題 = re.compile(r"打招呼|問候|招呼|早安|午安|晚安|感謝|謝謝|道謝|訂閱|贈禮|贈送|念留言|唸留言|讀留言|念聊天室|聊天室留言")


def 是雜訊主題(字):
    return bool(雜訊主題.search(字))


def 單一主題(字):
    """錨點只能是一件事：模型寫成「A與B」「A、B」時只留第一件（提示詞要求最主要的寫前面）。
    第一件短於 2 個字（例如「吃」）就原樣保留，避免切壞；「和」「跟」常出現在一件事裡（例如「跟聊天室互動」），不切。"""
    字 = 字.strip()
    m = 主題分隔.search(字)
    if m and len(字[:m.start()].strip()) >= 2:
        return 字[:m.start()].strip()
    return 字


def 問話題(主題, 最後幾行, 新行們, 聊天們=None, 要分鐘=False, 參考詞=None, 詞庫段=""):
    """問模型話題有沒有換。主題：這個話題開始時定下的「一件事」（之後不改寫，判斷一律跟它比對，避免簡述每輪漂移）。
    回傳 (decision, new_topic_start, brief, side_notes, minute, topic)；解析失敗就當 same。
    brief 是給介面顯示的簡述；topic 是模型認定的「目前這一題的那一件事」（new_topic 時是新的那件事）。
    minute 是 (summary, audience)，沒有或失敗就是 None。聊天們：聊天室代表留言的字串清單，沒有就傳 None。
    詞庫段：直播主詞庫的提示段落（glossary.詞庫.提示段()）；沒有詞庫或詞庫是空的就是空字串，提示詞不變。"""
    句數字 = "1 句" if MINUTE_SENTENCES == 1 else f"1 到 {MINUTE_SENTENCES} 句"
    聊天段 = ""
    if 聊天們:
        聊天段 = "聊天室留言（" + summarize.聊天室規則 + "）：\n" + "\n".join(聊天們) + "\n\n"
    if 參考詞:
        聊天段 += 參考詞規則.replace("{詞們}", "、".join(參考詞))
    提示詞 = (
        換話題規則 + 說話者規則 +
        "另外，請把新文字裡的短支線記錄下來（不影響上面的 same / new_topic 判斷）。" + 支線標準 + "\n\n"
        + summarize.語言說明
        + 詞庫段
        + (分鐘規則.replace("{句數}", 句數字) if 要分鐘 else "") +
        f"目前話題（開始時定下的一件事，不會改寫）：{主題 or '（剛開始，還沒有定下；用最後幾行判斷）'}\n\n"
        "目前話題最後幾行：\n" + ("\n".join(最後幾行) or "（無）") + "\n\n"
        "新文字：\n" + "\n".join(新行們) + "\n\n"
        + 聊天段 + 時間戳規則 +
        "只回傳 JSON，不要其他文字：\n"
        '{"decision": "same" 或 "new_topic", '
        '"new_topic_start": "時間戳記（只有 new_topic 時填：新的那件事開始的那一行，必須是新文字裡真的出現過的時間戳記，照原樣抄、不含方括號，例如 1:23:45）", '
        '"topic": "目前這一題的那一件事，10 到 20 字。只能寫一件事：不可用「與」「、」「及」「並」把兩件事接在一起；'
        '新文字同時聊了兩件事時，只寫最主要的那一件。打招呼、感謝訂閱或贈禮、念聊天室留言不是一件事，不可以寫成這一題的那一件事'
        '（新文字主要只有這些時，decision 填 same，topic 照寫原本那件事）。same 寫原本那件事；new_topic 寫新的那件事", '
        '"topic_brief": "給介面顯示的目前話題簡述，1 到 2 句，繁體中文（若是 new_topic，寫新話題的簡述）", '
        '"side_notes": [{"time": "時間戳記（必須是新文字裡真的出現過的時間戳記，照原樣抄、不含方括號）", "note": "一句話描述這段支線，繁體中文"}]'
        + (', "minute_summary": {"summary": "[時間戳記] 這一輪的{句數}摘要", "audience": "聊天室反應，最多 1 句，沒有就空字串"}'
           if 要分鐘 else "").replace("{句數}", 句數字)
        + '}'
    )
    try:
        回答 = summarize.call_llm(提示詞)
        資料 = json.loads(re.search(r"\{.*\}", 回答, re.S).group(0)) if llm.摘要_思考 else 取最後JSON(回答)
        決定 = 資料.get("decision", "same")
        簡述結果 = str(資料.get("topic_brief", 主題 or ""))
        主題結果 = 單一主題(str(資料.get("topic") or "").strip()[:40] or 簡述結果.strip()[:40])   # 沒給 topic 就用簡述開頭頂替
        if 是雜訊主題(主題結果):
            主題結果 = ""          # 打招呼、感謝、念留言不能當錨點：回傳空字串，引擎不會拿它換錨點
        決定 = 決定 if 決定 in ("same", "new_topic") else "same"
        切點 = str(資料.get("new_topic_start", ""))
    except llm.模型錯誤:
        raise                      # 金鑰或連線有問題要立刻停，不能當成「話題沒變」
    except Exception:
        統計["JSON失敗"] += 1
        return "same", "", 主題 or "", [], None, 主題 or ""
    有的秒 = {轉秒(l) for l in 新行們} - {None}     # 這一輪新文字真的出現過的時間（模型漏了小時就照這些補回）
    # 分鐘摘要：欄位缺失或格式不對就略過這一輪
    分鐘 = None
    if 要分鐘:
        try:
            m = 資料["minute_summary"]
            摘要字 = str(m["summary"]).strip()
            標 = 時間標記.match(摘要字)
            if 標:          # 開頭的時間：補回漏掉的小時，格式統一（例如 [83:45] → [1:23:45]）
                摘要字 = f"[{秒轉字(對齊時間(timefmt.組秒(*標.groups()), 有的秒))}]" + 摘要字[標.end():]
            if 摘要字:
                分鐘 = (摘要字, str(m.get("audience", "")).strip() if 聊天們 else "")
        except Exception:
            分鐘 = None
    # 支線：欄位缺失或格式不對就當作沒有；時間必須真的出現在新文字裡
    支線們 = []
    try:
        for 項 in (資料.get("side_notes") or [])[:MAX_SIDE_PER_CHECK]:
            秒 = 對齊時間(轉秒(f"[{項['time']}]"), 有的秒)
            note = str(項["note"]).strip()
            if 秒 in 有的秒 and note:
                支線們.append((秒, note))
    except Exception:
        pass
    return 決定, 切點, 簡述結果, 支線們, 分鐘, 主題結果


時間戳規則 = "時間戳記一律照文字稿原樣抄（例如 [1:23:45]、[05:12]、[+12:34]），不可省略小時、不可改寫格式。\n\n"

話題格式 = (
    "請用繁體中文（不可出現簡體字），嚴格照下面格式輸出，不要加 #、**、標題符號或其他裝飾，也不要多餘的話：\n"
    "【話題標題】一句話，只寫這一題最主要的那一件事；不可用「、」「與」「並」「及」把不同的事串起來，其他次要的內容放在【摘要】\n"
    "【時間範圍】{起} - {訖}\n"
    "【摘要】2 到 4 句\n"
    "【重點】\n"
    "- [時間戳記] 重點一\n"
    "- [時間戳記] 重點二（最多 3 點，每點開頭保留對應的時間戳記）\n"
    "【支線】\n"
    "- [時間戳記] 支線一（照文字稿開頭提供的「已知支線」列出，保留時間戳記；沒有已知支線就寫成「【支線】無」同一行）\n"
    + 時間戳規則 +
    "每一項的標籤和內容寫在同一行，項目之間不空行。\n"
    "【摘要】和【重點】不要重複已知支線的內容。\n"
    "【重點】和【支線】只能放語音稿的內容，聊天室內容只能出現在【觀眾反應】。\n"
    "正文不可夾雜英文單字或日文，專有名詞的原文除外（放在括號裡）。\n"
    + 說話者規則 +
    "不要編造文字稿裡沒有的內容。"
)


觀眾反應格式 = (
    "【觀眾反應】最多 2 句，描述聊天室對這個話題的反應與出現的梗（沒有明顯內容就寫「無」）。"
    "引用聊天室內容時一律翻成台灣慣用的繁體中文，不可保留日文原句、日文漢字字形（例如 獣→獸）或假名；"
    "www、草 等笑的表現寫成「聊天室在笑」之類的中文描述；真的需要保留原文的梗，翻成中文後把原文放在括號裡\n"
)


def 結果檔名(基底, 要分鐘):
    """回傳 (話題摘要檔, 分鐘摘要檔或 None)。舊結果檔已存在就改用加了執行時間的新檔名，絕不覆蓋。"""
    from datetime import datetime

    def 名字(後綴):
        return (基底 + "_話題摘要" + 後綴 + ".md",
                (基底 + "_分鐘摘要" + 後綴 + ".md") if 要分鐘 else None)
    後綴, 號 = "", 1
    while any(f and os.path.exists(f) for f in 名字(後綴)):
        後綴 = "_" + datetime.now().strftime("%Y%m%d-%H%M") + ("" if 號 == 1 else f"_{號}")
        號 += 1
    return 名字(後綴)


def 輸出話題摘要(話題, 結束秒, 輸出檔, 詞庫=None, 查證=None):
    """詞庫：這一場的直播主詞庫（沒有就傳 None）。有詞庫時提示詞附上詞庫，並請模型在最後一行列出【名詞】；
    【名詞】那一行從顯示與存檔的內文拿掉，新的名詞自動加進詞庫。
    查證：上網查證（web_verify.背景查證，開關關著就是 None）；新加入的候選丟給它在背景查，不等結果。"""
    起, 訖 = 秒轉字(話題["開始"]), 秒轉字(話題["最後"])
    支線文字 = "\n".join(f"- [{秒轉字(s)}] {n}" for s, n in 話題["支線"]) or "（無）"
    聊天們 = [字 for _, 字 in 話題["聊天"]]
    格式 = 話題格式.replace("{起}", 起).replace("{訖}", 訖)
    if 聊天們:     # 聊天室沒抓到時，整個【觀眾反應】欄位省略
        格式 = 格式.replace("每一項的標籤", 觀眾反應格式 + "每一項的標籤", 1)
    參考段 = 參考詞規則.replace("{詞們}", "、".join(話題["參考詞"])) if 話題["參考詞"] else ""
    詞庫段 = ""
    if 詞庫 is not None:
        詞庫段 = 詞庫.提示段("\n".join(話題["行們"]))
        格式 = 格式.replace("每一項的標籤", glossary.名詞格式 + "每一項的標籤", 1)
    內文 = summarize.summarize_chunk(
        詞庫段 + 參考段 + "已知支線：\n" + 支線文字 + "\n\n以下是文字稿：\n" + "\n".join(話題["行們"]), 類型="chat",
        聊天室紀錄=聊天們 or None, 格式=格式)
    內文, 名詞們 = glossary.拆名詞(內文)     # 【名詞】只給詞庫用，不顯示、不存檔
    if 詞庫 is not None and 名詞們:
        try:
            新的 = 詞庫.自動加入(名詞們, 原稿="\n".join(話題["行們"]))
        except OSError as e:             # 詞庫存檔失敗不影響摘要
            新的 = []
            events.送出("info", 印出=f"詞庫存檔失敗：{e}")
        if 新的:
            events.送出("info", 印出="詞庫新增：" + "、".join(x.顯示() for x in 新的))
            if 查證 is not None:
                查證.加入(新的, 話題["行們"])
    候選 = {轉秒(l) for l in 話題["行們"]} - {None}     # 內文裡的時間：補回漏掉的小時、格式統一
    內文 = timefmt.換內文時間(內文, lambda 秒: 秒轉字(對齊時間(秒, 候選)))
    區塊 = f"=== {秒轉字(結束秒)} 話題結束 ===\n{內文}\n"
    events.送出("topic_summary", 開始=起, 結束=秒轉字(結束秒), 開始秒=話題["開始"], 結束秒=結束秒, 內文=內文,
                印出="\n" + 區塊)
    if 存檔["摘要"]:
        寫入結果檔(輸出檔, 區塊 + "\n")


def 寫入結果檔(路徑, 文字):
    """附加寫入摘要檔；第一次建立時先寫存檔開頭的說明（直播主、標題、開播時間）。"""
    新檔 = not os.path.exists(路徑)
    with open(路徑, "a", encoding="utf-8") as f:
        if 新檔:
            f.write(stream_clock.檔頭())
        f.write(文字)


def 新話題():
    return {"開始": None, "最後": None, "行們": [], "簡述": "", "主題": "", "支線": [], "聊天": [], "參考詞": []}


def 加聊天(話題, 聊天們):
    """聊天們：[(秒, 字串)]。每個話題最多留 MAX_CHAT_PER_TOPIC 則（保留較新的）。"""
    話題["聊天"] = (話題["聊天"] + 聊天們)[-MAX_CHAT_PER_TOPIC:]


def 加支線(話題, 支線們):
    """把支線記到話題底下：意思相近的不重複記，最多保留 MAX_SIDE_PER_TOPIC 條（保留較早的）。"""
    from difflib import SequenceMatcher
    for 秒, note in 支線們:
        if len(話題["支線"]) >= MAX_SIDE_PER_TOPIC:
            break
        if any(abs(秒 - s) < 30 or SequenceMatcher(None, note, n).ratio() > 0.6 for s, n in 話題["支線"]):
            continue
        話題["支線"].append((秒, note))


def 加入(話題, 新行們):
    for 秒, 行 in 新行們:
        if 話題["開始"] is None:
            話題["開始"] = 秒
        話題["最後"] = 秒
        話題["行們"].append(行)


統計 = {"分鐘摘要": 0, "JSON失敗": 0}
存檔 = {"摘要": True}               # 由 執行() 依設定 save_summary 填入：關掉時摘要照常產生，只是不寫檔
單價 = {"輸入": config.出廠預設()["price_input"], "輸出": config.出廠預設()["price_output"]}   # 由 執行() 依設定填入，只用來估算費用


def 送狀態():
    """送出這場目前的呼叫次數、token 與估算費用（命令列不印）。"""
    u = llm.用量
    費用 = None if u["缺token"] else u["輸入"] / 1e6 * 單價["輸入"] + u["輸出"] / 1e6 * 單價["輸出"]
    events.送出("status", 次數=u["次數"], 輸入=u["輸入"], 輸出=u["輸出"], 費用=費用)


def 輸出分鐘摘要(分鐘, 支線們, 秒, 有聊天, 分鐘檔):
    """印出並存檔一則分鐘摘要。支線直接用同一次回傳的 side_notes。"""
    摘要字, 觀眾 = 分鐘
    if not 時間標記.match(摘要字):
        摘要字 = f"[{秒轉字(秒)}] {摘要字}"
    行們 = [摘要字]
    if 支線們:
        行們.append("　支線：" + "；".join(f"[{秒轉字(s)}] {n}" for s, n in 支線們))
    if 有聊天 and 觀眾:
        行們.append("　觀眾反應：" + 觀眾)
    文字 = "\n".join(行們)
    events.送出("minute_summary", 秒=秒, 摘要=摘要字, 支線=list(支線們),
                觀眾反應=觀眾 if 有聊天 else "", 印出=文字)
    if 分鐘檔 and 存檔["摘要"]:
        寫入結果檔(分鐘檔, 文字 + "\n\n")
    統計["分鐘摘要"] += 1


def 引擎(行來源, check_min, 輸出檔, 聊天=None, 分鐘檔=None, 修正=True, 詞庫=None, 查證=None):
    """行來源：一個會一直吐出 (秒數, 文字行) 的東西（檔案重播或真正的直播都可以）。
    聊天：聊天室物件（沒有就傳 None，引擎照舊只用語音稿）。詞庫：直播主詞庫（沒有就傳 None，不讀不寫）。
    查證：上網查證（沒開就是 None）。"""
    迭代 = iter(行來源)
    try:
        return _引擎(迭代, check_min, 輸出檔, 聊天, 分鐘檔, 修正, 詞庫, 查證)
    except (Exception, KeyboardInterrupt):    # 任何錯誤都要先關掉音訊擷取，不留下 ffmpeg
        if hasattr(迭代, "close"):
            迭代.close()           # 關掉音訊擷取（ffmpeg、streamlink）與聊天室
        raise


def _引擎(迭代, check_min, 輸出檔, 聊天, 分鐘檔, 修正, 詞庫=None, 查證=None):
    話題 = 新話題()
    待處理 = []          # 還沒判斷過的新行
    上次檢查 = None
    聊天起 = 0           # 聊天室這一輪從哪個秒數開始算
    話題數 = 0
    現在 = 0
    已送聊天 = -1        # 重播聊天室：已經送出到哪個秒數

    while True:
        try:
            秒, 行 = next(迭代)
        except StopIteration:
            if events.停止.is_set():
                events.送出("info", 印出="\n收到停止，正在結束並輸出最後一個話題...")
            break
        except KeyboardInterrupt:
            events.送出("info", 印出="\n收到 Ctrl+C，正在結束並輸出最後一個話題...")
            break
        if events.停止.is_set():      # 介面按了停止：和 Ctrl+C 一樣收尾
            events.送出("info", 印出="\n收到停止，正在結束並輸出最後一個話題...")
            break
        現在 = 秒
        events.送出("transcript_line", 秒=秒, 時間字=秒轉字(秒), 內容=時間標記.sub("", 行).strip(), 行=行)
        if isinstance(聊天, 聊天重播):    # 重播的聊天室跟著文字稿時間送出（真正的聊天室由 chat_capture 即時送出）
            for 留言秒, 人, 內容 in 聊天.取出(已送聊天, 秒):
                events.送出("chat_line", 秒=留言秒, 時間字=秒轉字(留言秒), 使用者=人, 內容=內容,
                            編號=events.新留言編號())
            已送聊天 = max(已送聊天, 秒)
        if 上次檢查 is None:
            上次檢查 = 秒
        待處理.append((秒, 行))
        字數 = sum(len(l) for _, l in 待處理)
        if 秒 - 上次檢查 < check_min * 60 or 字數 < MIN_NEW_CHARS:
            continue

        本輪聊天, 本輪詞 = [], []
        if 聊天:
            本輪聊天 = 代表留言(聊天.取出(聊天起, 秒))
            聊天起 = 秒
            if 修正:     # 從最近幾分鐘的聊天室找參考詞（沒有聊天室就整項略過）
                本輪詞 = 找參考詞(聊天.取出(max(0, 秒 - REF_WINDOW_MIN * 60), 秒))
        詞庫段 = 詞庫.提示段("\n".join(話題["行們"][-10:] + [l for _, l in 待處理])) if 詞庫 is not None else ""
        try:
            決定, 切點字, 簡述, 支線們, 分鐘, 主題 = 問話題(
                話題["主題"], 話題["行們"][-10:], [l for _, l in 待處理],
                [字 for _, 字 in 本輪聊天] or None, 要分鐘=bool(分鐘檔), 參考詞=本輪詞 or None, 詞庫段=詞庫段)
        except KeyboardInterrupt:      # 等模型回答時按 Ctrl+C：照一般的 Ctrl+C 流程收尾
            events.送出("info", 印出="\n已中斷，正在整理最後一個話題...")
            if hasattr(迭代, "close"):
                迭代.close()           # 先關掉音訊擷取與 ffmpeg
            break
        上次檢查 = 秒
        送狀態()

        # 判斷是否真的要換話題
        切位置 = None
        if 決定 == "new_topic" and 話題["行們"]:
            切秒 = 對齊時間(轉秒(f"[{切點字}]"), {轉秒(l) for _, l in 待處理})
            for i, (_, l) in enumerate(待處理):
                if 切秒 is not None and 轉秒(l) == 切秒:     # 用行首的時間比對（直播秒是小數，行首只到整秒）
                    切位置 = i
                    break
            if 切位置 is not None and 切秒 - 話題["開始"] < MIN_TOPIC_MIN * 60:
                切位置 = None   # 話題太短，忽略
        if 切位置 is not None:
            加入(話題, 待處理[:切位置])
            切時間 = 切秒       # 行首的整秒（支線的時間也是整秒）
            加支線(話題, [x for x in 支線們 if x[0] < 切時間])   # 切點之前歸舊話題
            加聊天(話題, [x for x in 本輪聊天 if x[0] < 切時間])
            加參考詞(話題, 本輪詞)
            if 話題["行們"]:
                輸出話題摘要(話題, 秒, 輸出檔, 詞庫, 查證)
                送狀態()
                話題數 += 1
            話題 = 新話題()
            話題["主題"] = 主題        # 新話題的那一件事：只在話題開始時定下，之後的判斷都跟它比
            加入(話題, 待處理[切位置:])
            加支線(話題, [x for x in 支線們 if x[0] >= 切時間])  # 切點之後歸新話題
            加聊天(話題, [x for x in 本輪聊天 if x[0] >= 切時間])
            加參考詞(話題, 本輪詞)
        else:
            # 定下或換掉這一題的那一件事：
            #   話題剛開始（第一輪或強制結束後）→ 定下；
            #   模型判 new_topic 但沒切（未滿最短分鐘數、或切點對不上行首）→ 不切話題，但錨點換成新的那件事，
            #   之後的輪次跟新的事比對（否則新的事會一直被當成舊錨點的延續）。話題開始時間不動：這些行確實在這一題裡。
            if 主題 and (not 話題["主題"] or 決定 == "new_topic"):      # 空字串＝模型給的是打招呼、感謝這類，不當錨點
                話題["主題"] = 主題
            加入(話題, 待處理)
            加支線(話題, 支線們)
            加聊天(話題, 本輪聊天)
            加參考詞(話題, 本輪詞)
            # 太久強制結束，下一輪重新開始
            if 話題["最後"] - 話題["開始"] > MAX_TOPIC_MIN * 60:
                events.送出("info", 印出=f"（話題超過 {MAX_TOPIC_MIN} 分鐘，強制結束）")
                輸出話題摘要(話題, 秒, 輸出檔, 詞庫, 查證)
                送狀態()
                話題數 += 1
                話題 = 新話題()
                簡述 = ""
        待處理 = []
        if 分鐘:
            輸出分鐘摘要(分鐘, 支線們, 秒, 聊天 is not None, 分鐘檔)
        話題["簡述"] = 簡述
        進行 = (秒 - 話題["開始"]) / 60 if 話題["開始"] is not None else 0
        events.送出("current_topic", 秒=秒, 簡述=簡述, 進行分鐘=進行,
                    印出=f"[{秒轉字(秒)}] 目前話題：{簡述 or '（新話題剛開始）'}（已進行 {進行:.0f} 分鐘）")

    # 文字稿讀完：剩下的也要輸出
    加入(話題, 待處理)
    if 話題["行們"]:
        輸出話題摘要(話題, 現在, 輸出檔, 詞庫, 查證)
        送狀態()
        話題數 += 1
    return 話題數


def main():
    global MIN_TOPIC_MIN, MAX_TOPIC_MIN, MINUTE_SENTENCES
    ap = argparse.ArgumentParser(description="直播分話題摘要。功能開關可寫在 config.json，命令列參數只負責臨時覆蓋。")
    ap.add_argument("檔案", nargs="?")
    ap.add_argument("--check", type=float, default=None, help="幾分鐘檢查一次話題（預設見 config.json）")
    ap.add_argument("--speed", type=float, default=0)
    ap.add_argument("--live", help="Twitch 直播網址，例如 https://www.twitch.tv/頻道名稱")
    ap.add_argument("--lang", default=None, help="直播語言：" + "、".join(config.語言代碼們) + "（自動偵測並鎖定），預設見 config.json")
    ap.add_argument("--chat", action=argparse.BooleanOptionalAction, default=None,
                    help="--live 模式下是否抓聊天室（--chat / --no-chat）")
    ap.add_argument("--minute", action=argparse.BooleanOptionalAction, default=None,
                    help="是否產生分鐘摘要（--minute / --no-minute）")
    ap.add_argument("--save-audio", action=argparse.BooleanOptionalAction, default=None,
                    help="--live 模式下是否存音訊檔（--save-audio / --no-save-audio）")
    ap.add_argument("--fix", action=argparse.BooleanOptionalAction, default=None,
                    help="是否用聊天室參考詞修正摘要裡的詞（--fix / --no-fix）")
    ap.add_argument("--chat-file", help="（測試用）文字稿模式下，一併讀取已存的聊天室檔")
    ap.add_argument("--web", action=argparse.BooleanOptionalAction, default=None,
                    help="是否上網查證詞庫的候選名詞（--web / --no-web，只支援 anthropic，另外計費）")
    ap.add_argument("--streamer", help="文字稿模式：指定直播主名字，讀寫 詞庫/名字.txt（沒給就不用詞庫）；直播網址模式自動用頻道名稱")
    ap.add_argument("--show-config", action="store_true", help="印出目前實際生效的設定與來源，然後結束")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    設定, 來源, 警告們 = config.載入設定({
        "chat": args.chat, "minute_summary": args.minute, "save_audio": args.save_audio,
        "fix_with_chat": args.fix, "check_minutes": args.check, "language": args.lang,
        "web_verify": args.web,
    })
    for w in 警告們:
        print("警告：" + w)
    llm.套用設定(設定)
    if args.show_config:
        config.印設定(設定, 來源, llm.金鑰狀態())
        return

    if not args.live and not args.檔案:
        print("用法：python live_topics.py 文字稿.txt   或   python live_topics.py --live 直播網址")
        sys.exit(1)
    events.接收者們.append(events.印到終端機)    # 命令列：事件直接印到終端機
    if not 執行(設定, 檔案=args.檔案, 網址=args.live, speed=args.speed, 聊天檔=args.chat_file,
                直播主=args.streamer):
        sys.exit(1)


def 載入詞庫(直播主):
    """讀入直播主詞庫並印一行說明；沒有直播主（文字稿模式沒給 --streamer）回傳 None。"""
    名字 = glossary.檔名安全(直播主)
    if not 名字:
        return None
    詞庫 = glossary.詞庫(名字)
    if 詞庫.讀錯誤:
        events.送出("info", 印出=f"詞庫讀不到（{詞庫.讀錯誤}），這一場不使用也不寫入：{詞庫.路徑}")
        return None
    用, 候選 = 詞庫.數量()
    上網 = sum(1 for e in 詞庫.條目們 if e.來源 == "上網")
    行 = (f"已載入詞庫：{名字}，手動 {用 - 上網} 個" + (f"、上網 {上網} 個" if 上網 else "")
         + (f"（另有候選 {候選} 個，這一場不使用）" if 候選 else ""))
    if 詞庫.格式錯:
        行 += f"（{詞庫.格式錯} 行格式不對，已略過，檔案裡保留原樣）"
    events.送出("info", 印出=行)
    return 詞庫


def 開始查證(設定, 詞庫, 直播主):
    """開關打開又有詞庫時，建立這一場的背景查證；provider 不支援時印一句說明，其他照常（回傳 None）。"""
    if not 設定.get("web_verify"):
        return None
    if not llm.支援上網查證():
        events.送出("info", 印出=f"上網查證無法使用：目前的模型服務（{設定['provider']}）沒有支援的上網搜尋工具，"
                                 "這一場不查證，其他功能照常。")
        return None
    if 詞庫 is None:
        events.送出("info", 印出="上網查證：這一場沒有使用詞庫（文字稿模式沒給 --streamer），不查證。")
        return None
    資訊 = stream_clock.資訊() or {}
    脈絡 = {"直播主": 資訊.get("直播主") or 直播主, "分類": 資訊.get("遊戲", ""), "標題": 資訊.get("標題", "")}
    events.送出("info", 印出=f"上網查證：開啟（只查這一場新加入的候選，最多 {web_verify.每場上限} 個，另外計費）")
    return web_verify.背景查證(詞庫, 脈絡, 設定["model"])


def 執行(設定, 檔案=None, 網址=None, speed=0, 聊天檔=None, 直播主=None):
    """跑一整場（命令列與介面共用）。結果都用事件送出。成功回傳 True，出錯回傳 False。
    設定：config.載入設定() 的結果（llm.套用設定 要先做好）。
    直播主：文字稿模式用來指定詞庫（沒給就不讀不寫詞庫）；直播網址模式一律用頻道名稱，這個參數不用。"""
    global MIN_TOPIC_MIN, MAX_TOPIC_MIN, MINUTE_SENTENCES
    # 這一場重新計算（介面可以連續跑好幾場）
    stream_clock.清除()      # 直播網址模式由 live_capture 建立這一場的時軸；文字稿模式沒有時軸
    for k in llm.用量:
        llm.用量[k] = 0
    for k in llm.查證用量:
        llm.查證用量[k] = 0
    統計["分鐘摘要"] = 0
    統計["JSON失敗"] = 0
    單價["輸入"], 單價["輸出"] = 設定["price_input"], 設定["price_output"]
    存檔["摘要"] = bool(設定["save_summary"])

    # 把設定套用到各個模組（模型名稱、話題長短、分鐘摘要句數）
    import transcribe
    summarize.MODEL = 設定["model"]
    transcribe.GPU_MODEL = 設定["whisper_model"]
    MIN_TOPIC_MIN, MAX_TOPIC_MIN = 設定["min_topic_min"], 設定["max_topic_min"]
    MINUTE_SENTENCES = 設定["minute_sentences"]
    summarize.語言說明 = ""
    if 設定["language"] != "zh":      # 外語：提示詞加外語說明；中文維持原樣
        summarize.語言說明 = summarize.外語提示
        if 設定["language"] == "auto" and not 網址:
            events.送出("info", 印出="提醒：文字稿模式無法自動偵測語言，一律照外語說明處理。")

    events.送出("stage", 階段="檢查 API 金鑰")
    錯誤 = llm.檢查金鑰()
    if 錯誤:
        events.送出("error", 訊息=錯誤, 印出=錯誤)
        return False

    if 網址:
        import live_capture
        live_capture.設定分段(subtitle_speed.取得(設定["subtitle_speed"])["分段秒"])
        try:
            行來源 = live_capture.live_session(網址, 設定["language"], 用聊天室=設定["chat"],
                                                 存音訊=設定["save_audio"], 存稿=設定["save_transcript"],
                                                 存聊天=設定["save_chat"])
        except live_capture.直播錯誤 as e:
            events.送出("error", 訊息=str(e), 印出=str(e))
            return False
        基底 = os.path.splitext(行來源.稿路徑)[0]
        直播主 = live_capture.頻道名稱(網址)
    else:
        行來源 = stream_lines(檔案, speed)
        基底 = os.path.splitext(檔案)[0]
    # 結果檔在第一筆內容寫入時才建立（出錯或沒內容就不會留下空白檔）；檔名保證是新的，舊結果檔不會被動到
    輸出檔, 分鐘檔 = 結果檔名(基底, 設定["minute_summary"])
    聊天 = getattr(行來源, "聊天", None)
    if 聊天檔 and not 網址:
        聊天 = 聊天重播(聊天檔)
    # 告訴介面各分頁對應的存檔位置（分頁只顯示最近的內容，較早的在檔案裡）
    # 存檔關閉的項目傳 None（介面就顯示「較早的內容已移除」，不顯示「打開檔案」）；基底 = 逐句翻譯存檔用的檔名開頭
    events.送出("files", 基底=os.path.abspath(基底),
                稿=os.path.abspath(行來源.稿路徑 if 網址 else 檔案) if 設定["save_transcript"] else None,
                聊天=(os.path.abspath(聊天.存檔路徑) if 網址 and 聊天 and 聊天.存檔路徑
                     else os.path.abspath(聊天檔) if 聊天檔 and not 網址 and 設定["save_chat"] else None),
                分鐘=os.path.abspath(分鐘檔) if 分鐘檔 and 存檔["摘要"] else None,
                話題=os.path.abspath(輸出檔) if 存檔["摘要"] else None)
    詞庫 = 載入詞庫(直播主)
    查證 = 開始查證(設定, 詞庫, 直播主)
    送狀態()
    try:
        話題數 = 引擎(行來源, 設定["check_minutes"], 輸出檔, 聊天, 分鐘檔, 修正=設定["fix_with_chat"], 詞庫=詞庫,
                    查證=查證)
    except llm.模型錯誤 as e:
        if 聊天:
            聊天.關閉()
        if 查證:
            查證.收尾(0)
        events.送出("error", 訊息=str(e), 印出="\n" + str(e))
        return False
    except KeyboardInterrupt:          # 整理最後話題時又按了一次 Ctrl+C
        if 聊天:
            聊天.關閉()
        if 查證:
            查證.收尾(0)
        events.送出("error", 訊息="已中斷。", 印出="\n已中斷。")
        return False
    if 聊天:
        聊天.關閉()
    查證行 = None
    if 查證:
        if 查證.進行中():
            events.送出("info", 印出=f"等待上網查證收尾（最多 {web_verify.收尾等待秒} 秒）...")
        查證行 = 查證.收尾() + "；" + llm.查證用量文字(設定["price_input"], 設定["price_output"])

    行們 = ["\n完成：切出 " + str(話題數) + " 個話題，" + llm.用量文字(設定["price_input"], 設定["price_output"])]
    音訊行 = 行來源.音訊統計() if hasattr(行來源, "音訊統計") else None
    if 音訊行:
        行們.append(音訊行)
    if 分鐘檔:
        行們.append(f"分鐘摘要：共產出 {統計['分鐘摘要']} 則")
    if 查證行:
        行們.append(查證行)
    if 聊天:
        行們.append(f"聊天室：收到 {聊天.收到} 則，過濾掉 {聊天.過濾} 則"
                  + ("" if 聊天.收到 else "（沒收到留言，可能沒連上）"))
    檔案們 = [f for f in (輸出檔, 分鐘檔) if f and 存檔["摘要"] and os.path.exists(f)]
    行們.append(("已存成：" + "、".join(檔案們)) if 檔案們 else
              "沒有產生任何內容，所以沒有建立結果檔。" if 存檔["摘要"] else "摘要存檔已關閉（save_summary），沒有建立結果檔。")
    events.送出("finished", 話題數=話題數, 檔案們=檔案們, 印出="\n".join(行們))
    return True


if __name__ == "__main__":
    main()
