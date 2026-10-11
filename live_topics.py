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

# ---- 可以調整的設定 ----
MIN_TOPIC_MIN = 3     # 話題未滿幾分鐘，忽略「換話題」的判斷
MAX_TOPIC_MIN = 15    # 話題超過幾分鐘，強制結束並開新話題
MIN_NEW_CHARS = 100   # 新文字少於這麼多字，這一輪跳過判斷
MINUTE_SENTENCES = 2     # 分鐘摘要句數上限（1 到 3，可在 config.json 改）
MAX_SIDE_PER_CHECK = 2   # 每次判斷最多回報幾條支線
MAX_SIDE_PER_TOPIC = 5   # 每個話題最多保留幾條支線（超過就保留較早的）
# 「支線」的標準（現在是「窄」的）。想改成「寬」就改這段文字，例如把要求放寬成
# 「任何與主話題無關的閒聊都算，包含感謝訂閱、口頭禪以外的所有插曲」。
支線標準 = (
    "支線 = 實況主短暫離開主話題，閒聊了與主話題無關、但有資訊價值的內容"
    "（例如提到某個東西、近況、做了某個決定、跟觀眾的小插曲）。"
    "純粹的口頭禪、語助詞、單純的「謝謝訂閱」類感謝，不算支線。"
    "每次最多回報 2 條，沒有就回空陣列。"
)

時間標記 = re.compile(r"^\[(?:(\d+):)?(\d+):(\d+)\]")


def 轉秒(行):
    m = 時間標記.match(行)
    if not m:
        return None
    h, mi, s = m.groups()
    return int(h or 0) * 3600 + int(mi) * 60 + int(s)


def 秒轉字(秒):
    秒 = int(秒)
    return f"{秒 // 60:02d}:{秒 % 60:02d}"


def stream_lines(來源, speed=0):
    """一行一行吐出 (直播秒數, 文字行)。
    之後要換成真正的即時轉錄，只要改這個函式：每有新的一句就 yield (秒數, "[mm:ss] 文字")。"""
    上一秒 = None
    with open(來源, encoding="utf-8") as f:
        for 行 in f:
            行 = 行.rstrip("\n")
            if not 行.strip():
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
            重複.append((組[0][0], f"[{轉字(組[0][0])}] （{人數} 人重複）{組[0][2]}"))
        else:
            其他.extend((秒, f"[{轉字(秒)}] {人}: {內容}") for 秒, 人, 內容 in 組)
    其他.sort()
    剩 = max(MAX_CHAT_PER_CHECK - len(重複), 0)
    if len(其他) > 剩:    # 太多就平均挑，不要只看開頭
        其他 = [其他[i * len(其他) // 剩] for i in range(剩)] if 剩 else []
    return sorted(重複[:MAX_CHAT_PER_CHECK] + 其他)


def 轉字(秒):
    return 秒轉字(秒)


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
            m = re.match(r"^\[(?:(\d+):)?(\d+):(\d+)\] ([^:]+): (.*)$", 行.rstrip("\n"))
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
    "正文不可夾雜英文單字或日文，專有名詞的原文除外（放在括號裡）；以一個代表性的 [mm:ss] 時間戳記開頭。不可把聊天室留言放進 summary。\n"
    "- audience：這一輪聊天室的反應與梗，最多 1 句，沒有明顯內容、或沒有聊天室留言就填空字串。"
    "只有 audience 可以引用聊天室留言。\n"
    "- 引用聊天室內容時一律翻成台灣慣用的繁體中文，不可保留日文原句、日文漢字字形（例如 獣→獸）或假名；"
    "www、草 等笑的表現寫成「聊天室在笑」之類的中文描述；真的需要保留原文的梗，翻成中文後把原文放在括號裡。\n"
    "- 誰先說了什麼，要以語音稿的時間順序為準；不可把實況主自己說的話寫成聊天室說的。\n\n"
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


def 問話題(簡述, 最後幾行, 新行們, 聊天們=None, 要分鐘=False, 參考詞=None):
    """問模型話題有沒有換。回傳 (decision, new_topic_start, brief, side_notes, minute)；
    解析失敗就當 same。minute 是 (summary, audience)，沒有或失敗就是 None。
    聊天們：聊天室代表留言的字串清單，沒有就傳 None。"""
    句數字 = "1 句" if MINUTE_SENTENCES == 1 else f"1 到 {MINUTE_SENTENCES} 句"
    聊天段 = ""
    if 聊天們:
        聊天段 = "聊天室留言（" + summarize.聊天室規則 + "）：\n" + "\n".join(聊天們) + "\n\n"
    if 參考詞:
        聊天段 += 參考詞規則.replace("{詞們}", "、".join(參考詞))
    提示詞 = (
        "你在即時監看一場直播的文字稿，判斷『主要在聊的話題』有沒有換。\n"
        "只有主要在聊的事情真的換了才算 new_topic。同一個話題的細節延伸、離題一兩句又回來、"
        "短暫念聊天室留言，都算 same。\n"
        "另外，請把新文字裡的短支線記錄下來（不影響上面的 same / new_topic 判斷）。" + 支線標準 + "\n\n"
        + summarize.語言說明
        + (分鐘規則.replace("{句數}", 句數字) if 要分鐘 else "") +
        f"目前話題簡述：{簡述 or '（剛開始，還沒有簡述）'}\n\n"
        "目前話題最後幾行：\n" + ("\n".join(最後幾行) or "（無）") + "\n\n"
        "新文字：\n" + "\n".join(新行們) + "\n\n"
        + 聊天段 +
        "只回傳 JSON，不要其他文字：\n"
        '{"decision": "same" 或 "new_topic", '
        '"new_topic_start": "mm:ss（只有 new_topic 時填，必須是新文字裡真的出現過的時間戳記）", '
        '"topic_brief": "更新後的目前話題簡述，1 到 2 句，繁體中文（若是 new_topic，寫新話題的簡述）", '
        '"side_notes": [{"time": "mm:ss（必須是新文字裡真的出現過的時間戳記）", "note": "一句話描述這段支線，繁體中文"}]'
        + (', "minute_summary": {"summary": "[mm:ss] 這一輪的{句數}摘要", "audience": "聊天室反應，最多 1 句，沒有就空字串"}'
           if 要分鐘 else "").replace("{句數}", 句數字)
        + '}'
    )
    try:
        回答 = summarize.call_llm(提示詞)
        資料 = json.loads(re.search(r"\{.*\}", 回答, re.S).group(0)) if llm.摘要_思考 else 取最後JSON(回答)
        決定 = 資料.get("decision", "same")
        簡述結果 = str(資料.get("topic_brief", 簡述 or ""))
        決定 = 決定 if 決定 in ("same", "new_topic") else "same"
        切點 = str(資料.get("new_topic_start", ""))
    except llm.模型錯誤:
        raise                      # 金鑰或連線有問題要立刻停，不能當成「話題沒變」
    except Exception:
        統計["JSON失敗"] += 1
        return "same", "", 簡述 or "", [], None
    # 分鐘摘要：欄位缺失或格式不對就略過這一輪
    分鐘 = None
    if 要分鐘:
        try:
            m = 資料["minute_summary"]
            摘要字 = str(m["summary"]).strip()
            if 摘要字:
                分鐘 = (摘要字, str(m.get("audience", "")).strip() if 聊天們 else "")
        except Exception:
            分鐘 = None
    # 支線：欄位缺失或格式不對就當作沒有；時間必須真的出現在新文字裡
    支線們 = []
    try:
        有的秒 = {轉秒(l) for l in 新行們}
        for 項 in (資料.get("side_notes") or [])[:MAX_SIDE_PER_CHECK]:
            秒 = 轉秒(f"[{項['time']}]")
            note = str(項["note"]).strip()
            if 秒 in 有的秒 and note:
                支線們.append((秒, note))
    except Exception:
        pass
    return 決定, 切點, 簡述結果, 支線們, 分鐘


話題格式 = (
    "請用繁體中文（不可出現簡體字），嚴格照下面格式輸出，不要加 #、**、標題符號或其他裝飾，也不要多餘的話：\n"
    "【話題標題】一句話\n"
    "【時間範圍】{起} - {訖}\n"
    "【摘要】2 到 4 句\n"
    "【重點】\n"
    "- [mm:ss] 重點一\n"
    "- [mm:ss] 重點二（最多 3 點，每點開頭保留對應的時間戳記）\n"
    "【支線】\n"
    "- [mm:ss] 支線一（照文字稿開頭提供的「已知支線」列出，保留時間戳記；沒有已知支線就寫成「【支線】無」同一行）\n"
    "每一項的標籤和內容寫在同一行，項目之間不空行。\n"
    "【摘要】和【重點】不要重複已知支線的內容。\n"
    "【重點】和【支線】只能放語音稿的內容，聊天室內容只能出現在【觀眾反應】。\n"
    "正文不可夾雜英文單字或日文，專有名詞的原文除外（放在括號裡）。\n"
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


def 輸出話題摘要(話題, 結束秒, 輸出檔):
    起, 訖 = 秒轉字(話題["開始"]), 秒轉字(話題["最後"])
    支線文字 = "\n".join(f"- [{秒轉字(s)}] {n}" for s, n in 話題["支線"]) or "（無）"
    聊天們 = [字 for _, 字 in 話題["聊天"]]
    格式 = 話題格式.replace("{起}", 起).replace("{訖}", 訖)
    if 聊天們:     # 聊天室沒抓到時，整個【觀眾反應】欄位省略
        格式 = 格式.replace("每一項的標籤", 觀眾反應格式 + "每一項的標籤", 1)
    參考段 = 參考詞規則.replace("{詞們}", "、".join(話題["參考詞"])) if 話題["參考詞"] else ""
    內文 = summarize.summarize_chunk(
        參考段 + "已知支線：\n" + 支線文字 + "\n\n以下是文字稿：\n" + "\n".join(話題["行們"]), 類型="chat",
        聊天室紀錄=聊天們 or None, 格式=格式)
    區塊 = f"=== {秒轉字(結束秒)} 話題結束 ===\n{內文}\n"
    events.送出("topic_summary", 開始=起, 結束=秒轉字(結束秒), 內文=內文, 印出="\n" + 區塊)
    with open(輸出檔, "a", encoding="utf-8") as f:
        f.write(區塊 + "\n")


def 新話題():
    return {"開始": None, "最後": None, "行們": [], "簡述": "", "支線": [], "聊天": [], "參考詞": []}


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
單價 = {"輸入": 1.0, "輸出": 5.0}   # 由 執行() 依設定填入，只用來估算費用


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
    if 分鐘檔:
        with open(分鐘檔, "a", encoding="utf-8") as f:
            f.write(文字 + "\n\n")
    統計["分鐘摘要"] += 1


def 引擎(行來源, check_min, 輸出檔, 聊天=None, 分鐘檔=None, 修正=True):
    """行來源：一個會一直吐出 (秒數, 文字行) 的東西（檔案重播或真正的直播都可以）。
    聊天：聊天室物件（沒有就傳 None，引擎照舊只用語音稿）。"""
    迭代 = iter(行來源)
    try:
        return _引擎(迭代, check_min, 輸出檔, 聊天, 分鐘檔, 修正)
    except (Exception, KeyboardInterrupt):    # 任何錯誤都要先關掉音訊擷取，不留下 ffmpeg
        if hasattr(迭代, "close"):
            迭代.close()           # 關掉音訊擷取（ffmpeg、streamlink）與聊天室
        raise


def _引擎(迭代, check_min, 輸出檔, 聊天, 分鐘檔, 修正):
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
                events.送出("chat_line", 秒=留言秒, 時間字=秒轉字(留言秒), 使用者=人, 內容=內容)
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
        try:
            決定, 切點字, 簡述, 支線們, 分鐘 = 問話題(
                話題["簡述"], 話題["行們"][-10:], [l for _, l in 待處理],
                [字 for _, 字 in 本輪聊天] or None, 要分鐘=bool(分鐘檔), 參考詞=本輪詞 or None)
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
            切秒 = 轉秒(f"[{切點字}]")
            for i, (s, _) in enumerate(待處理):
                if 切秒 is not None and s == 切秒:
                    切位置 = i
                    break
            if 切位置 is not None and 切秒 - 話題["開始"] < MIN_TOPIC_MIN * 60:
                切位置 = None   # 話題太短，忽略
        if 切位置 is not None:
            加入(話題, 待處理[:切位置])
            切時間 = 待處理[切位置][0]
            加支線(話題, [x for x in 支線們 if x[0] < 切時間])   # 切點之前歸舊話題
            加聊天(話題, [x for x in 本輪聊天 if x[0] < 切時間])
            加參考詞(話題, 本輪詞)
            if 話題["行們"]:
                輸出話題摘要(話題, 秒, 輸出檔)
                送狀態()
                話題數 += 1
            話題 = 新話題()
            加入(話題, 待處理[切位置:])
            加支線(話題, [x for x in 支線們 if x[0] >= 切時間])  # 切點之後歸新話題
            加聊天(話題, [x for x in 本輪聊天 if x[0] >= 切時間])
            加參考詞(話題, 本輪詞)
        else:
            加入(話題, 待處理)
            加支線(話題, 支線們)
            加聊天(話題, 本輪聊天)
            加參考詞(話題, 本輪詞)
            # 太久強制結束，下一輪重新開始
            if 話題["最後"] - 話題["開始"] > MAX_TOPIC_MIN * 60:
                events.送出("info", 印出=f"（話題超過 {MAX_TOPIC_MIN} 分鐘，強制結束）")
                輸出話題摘要(話題, 秒, 輸出檔)
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
        輸出話題摘要(話題, 現在, 輸出檔)
        送狀態()
        話題數 += 1
    return 話題數


# ---- 設定檔 config.json ----
# 優先順序：命令列參數 > config.json > 程式內建預設
設定檔路徑 = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

設定說明 = {
    "chat": "抓聊天室（--live）",
    "minute_summary": "分鐘摘要",
    "save_audio": "存音訊（--live）",
    "fix_with_chat": "聊天室參考詞修正",
    "summary_thinking": "摘要使用延伸思考（true 較準但較貴；false 關閉思考，較省）",
    "check_minutes": "幾分鐘檢查一次話題",
    "min_topic_min": "話題最短分鐘數",
    "max_topic_min": "話題最長分鐘數",
    "model": "摘要用的模型",
    "whisper_model": "轉錄用的 Whisper 模型",
    "language": "直播語言（zh、ja、en、ko、auto）",
    "minute_sentences": "分鐘摘要句數上限",
    "provider": "模型服務種類（anthropic 或 openai_compatible）",
    "base_url": "模型服務網址（空白 = 預設）",
    "api_key_env": "金鑰的環境變數名稱（空白 = 不需要金鑰）",
    "price_input": "輸入單價（每百萬 token 美元，未查證）",
    "price_output": "輸出單價（每百萬 token 美元，未查證）",
    "subtitle_mode": "逐句字幕（介面才有）：original 原文、translate 翻譯、auto 中文用原文其他翻譯",
    "translate_batch_seconds": "逐句翻譯：第一句進來後最多等幾秒就翻（介面才有）",
    "translate_batch_lines": "逐句翻譯：累積幾句就翻（介面才有）",
    "overlay": "摘要框與字幕框的樣式、位置、快捷鍵（介面才有，缺的欄位用預設，見 README.txt）",
}


def 內建預設():
    """內建預設值：直接取用程式裡現有的常數，維持現在的行為。"""
    import transcribe
    return {
        "chat": True, "minute_summary": True, "save_audio": True, "fix_with_chat": False,
        "summary_thinking": True, "check_minutes": 1, "min_topic_min": MIN_TOPIC_MIN, "max_topic_min": MAX_TOPIC_MIN,
        "model": summarize.MODEL, "whisper_model": transcribe.GPU_MODEL, "language": "zh",
        "minute_sentences": 2,
        "provider": "anthropic", "base_url": "", "api_key_env": "ANTHROPIC_API_KEY",
        "price_input": 1.0, "price_output": 5.0,
        "subtitle_mode": "auto", "translate_batch_seconds": 8, "translate_batch_lines": 4, "overlay": {},
    }


def _布林(v):
    return isinstance(v, bool)


def _正數(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0


def _字串(v):
    return isinstance(v, str) and v.strip() != ""


def _非負(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 0


def _文字(v):      # 可以是空字串
    return isinstance(v, str)


def _服務(v):
    return v in ("anthropic", "openai_compatible")


def _語言(v):
    return v in ("zh", "ja", "en", "ko", "auto")


def _字幕模式(v):
    return v in ("original", "translate", "auto")


def _字典(v):
    return isinstance(v, dict)


def _句數上限(v):
    return isinstance(v, int) and not isinstance(v, bool) and 1 <= v <= 8


def _句數(v):
    return isinstance(v, int) and not isinstance(v, bool) and 1 <= v <= 3


檢查 = {
    "chat": _布林, "minute_summary": _布林, "save_audio": _布林, "fix_with_chat": _布林, "summary_thinking": _布林,
    "check_minutes": _正數, "min_topic_min": _正數, "max_topic_min": _正數,
    "model": _字串, "whisper_model": _字串, "language": _語言, "minute_sentences": _句數,
    "provider": _服務, "base_url": _文字, "api_key_env": _文字,
    "price_input": _非負, "price_output": _非負,
    "subtitle_mode": _字幕模式, "translate_batch_seconds": _正數, "translate_batch_lines": _句數上限,
    "overlay": _字典,
}


def 載入設定(命令列):
    """命令列：{設定名: 值或 None}（None 代表沒有在命令列指定）。
    回傳 (設定, 來源, 警告們)。config.json 不存在、欄位缺漏、值不合法都不會崩潰。"""
    預設 = 內建預設()
    設定 = dict(預設)
    來源 = {k: "內建預設" for k in 預設}
    警告們 = []
    內容 = None
    if os.path.exists(設定檔路徑):
        try:
            with open(設定檔路徑, encoding="utf-8-sig") as f:
                內容 = json.load(f)
            if not isinstance(內容, dict):
                raise ValueError("最外層不是欄位清單")
        except Exception as e:
            警告們.append(f"設定檔 config.json 讀不懂（{e}），全部改用內建預設。")
            內容 = None
    for k, v in (內容 or {}).items():
        if k not in 預設:
            警告們.append(f"設定檔裡有不認得的欄位「{k}」，已忽略。")
        elif 檢查[k](v):
            設定[k], 來源[k] = v, "config.json"
        else:
            警告們.append(f"設定檔的 {k} 值不合法（{v!r}），改用預設值 {預設[k]!r}。")
    if 設定["min_topic_min"] >= 設定["max_topic_min"]:
        警告們.append("設定檔的 min_topic_min 必須小於 max_topic_min，兩個都改用預設值。")
        for k in ("min_topic_min", "max_topic_min"):
            設定[k], 來源[k] = 預設[k], "內建預設"
    for k, v in 命令列.items():
        if v is None:
            continue
        if k in 檢查 and not 檢查[k](v):
            警告們.append(f"命令列的 {k} 值不合法（{v!r}），已忽略。")
            continue
        設定[k], 來源[k] = v, "命令列"
    return 設定, 來源, 警告們


def 印設定(設定, 來源):
    print(f"設定檔：{設定檔路徑}（{'存在' if os.path.exists(設定檔路徑) else '不存在，全部用內建預設'}）")
    print("目前實際生效的設定（優先順序：命令列 > config.json > 內建預設）：")
    for k in 設定說明:
        print(f"  {k:17} = {設定[k]!r:18} ← {來源[k]}　（{設定說明[k]}）")
    print(f"  API 金鑰：{llm.金鑰狀態()}（只從環境變數讀取，不顯示內容）")


def main():
    global MIN_TOPIC_MIN, MAX_TOPIC_MIN, MINUTE_SENTENCES
    ap = argparse.ArgumentParser(description="直播分話題摘要。功能開關可寫在 config.json，命令列參數只負責臨時覆蓋。")
    ap.add_argument("檔案", nargs="?")
    ap.add_argument("--check", type=float, default=None, help="幾分鐘檢查一次話題（預設見 config.json）")
    ap.add_argument("--speed", type=float, default=0)
    ap.add_argument("--live", help="Twitch 直播網址，例如 https://www.twitch.tv/頻道名稱")
    ap.add_argument("--lang", default=None, help="直播語言：zh、ja、en、ko、auto（自動偵測並鎖定），預設見 config.json")
    ap.add_argument("--chat", action=argparse.BooleanOptionalAction, default=None,
                    help="--live 模式下是否抓聊天室（--chat / --no-chat）")
    ap.add_argument("--minute", action=argparse.BooleanOptionalAction, default=None,
                    help="是否產生分鐘摘要（--minute / --no-minute）")
    ap.add_argument("--save-audio", action=argparse.BooleanOptionalAction, default=None,
                    help="--live 模式下是否存音訊檔（--save-audio / --no-save-audio）")
    ap.add_argument("--fix", action=argparse.BooleanOptionalAction, default=None,
                    help="是否用聊天室參考詞修正摘要裡的詞（--fix / --no-fix）")
    ap.add_argument("--chat-file", help="（測試用）文字稿模式下，一併讀取已存的聊天室檔")
    ap.add_argument("--show-config", action="store_true", help="印出目前實際生效的設定與來源，然後結束")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    設定, 來源, 警告們 = 載入設定({
        "chat": args.chat, "minute_summary": args.minute, "save_audio": args.save_audio,
        "fix_with_chat": args.fix, "check_minutes": args.check, "language": args.lang,
    })
    for w in 警告們:
        print("警告：" + w)
    llm.套用設定(設定)
    if args.show_config:
        印設定(設定, 來源)
        return

    if not args.live and not args.檔案:
        print("用法：python live_topics.py 文字稿.txt   或   python live_topics.py --live 直播網址")
        sys.exit(1)
    events.接收者們.append(events.印到終端機)    # 命令列：事件直接印到終端機
    if not 執行(設定, 檔案=args.檔案, 網址=args.live, speed=args.speed, 聊天檔=args.chat_file):
        sys.exit(1)


def 執行(設定, 檔案=None, 網址=None, speed=0, 聊天檔=None):
    """跑一整場（命令列與介面共用）。結果都用事件送出。成功回傳 True，出錯回傳 False。
    設定：載入設定() 的結果（llm.套用設定 要先做好）。"""
    global MIN_TOPIC_MIN, MAX_TOPIC_MIN, MINUTE_SENTENCES
    # 這一場重新計算（介面可以連續跑好幾場）
    for k in llm.用量:
        llm.用量[k] = 0
    統計["分鐘摘要"] = 0
    統計["JSON失敗"] = 0
    單價["輸入"], 單價["輸出"] = 設定["price_input"], 設定["price_output"]

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

    錯誤 = llm.檢查金鑰()
    if 錯誤:
        events.送出("error", 訊息=錯誤, 印出=錯誤)
        return False

    if 網址:
        import live_capture
        try:
            行來源 = live_capture.live_session(網址, 設定["language"], 用聊天室=設定["chat"],
                                                 存音訊=設定["save_audio"])
        except live_capture.直播錯誤 as e:
            events.送出("error", 訊息=str(e), 印出=str(e))
            return False
        基底 = os.path.splitext(行來源.稿路徑)[0]
    else:
        行來源 = stream_lines(檔案, speed)
        基底 = os.path.splitext(檔案)[0]
    # 結果檔在第一筆內容寫入時才建立（出錯或沒內容就不會留下空白檔）；檔名保證是新的，舊結果檔不會被動到
    輸出檔, 分鐘檔 = 結果檔名(基底, 設定["minute_summary"])
    聊天 = getattr(行來源, "聊天", None)
    if 聊天檔 and not 網址:
        聊天 = 聊天重播(聊天檔)
    送狀態()
    try:
        話題數 = 引擎(行來源, 設定["check_minutes"], 輸出檔, 聊天, 分鐘檔, 修正=設定["fix_with_chat"])
    except llm.模型錯誤 as e:
        if 聊天:
            聊天.關閉()
        events.送出("error", 訊息=str(e), 印出="\n" + str(e))
        return False
    except KeyboardInterrupt:          # 整理最後話題時又按了一次 Ctrl+C
        if 聊天:
            聊天.關閉()
        events.送出("error", 訊息="已中斷。", 印出="\n已中斷。")
        return False
    if 聊天:
        聊天.關閉()

    行們 = ["\n完成：切出 " + str(話題數) + " 個話題，" + llm.用量文字(設定["price_input"], 設定["price_output"])]
    音訊行 = 行來源.音訊統計() if hasattr(行來源, "音訊統計") else None
    if 音訊行:
        行們.append(音訊行)
    if 分鐘檔:
        行們.append(f"分鐘摘要：共產出 {統計['分鐘摘要']} 則")
    if 聊天:
        行們.append(f"聊天室：收到 {聊天.收到} 則，過濾掉 {聊天.過濾} 則"
                  + ("" if 聊天.收到 else "（沒收到留言，可能沒連上）"))
    檔案們 = [f for f in (輸出檔, 分鐘檔) if f and os.path.exists(f)]
    行們.append(("已存成：" + "、".join(檔案們)) if 檔案們 else "沒有產生任何內容，所以沒有建立結果檔。")
    events.送出("finished", 話題數=話題數, 檔案們=檔案們, 印出="\n".join(行們))
    return True


if __name__ == "__main__":
    main()
