# 直播主專有名詞詞庫：每個直播主一個純文字檔（詞庫/直播主.txt），用記事本就能讀改。
# 用途：讓摘要的名字寫法前後一致（只保證一致、不保證正確）。詞庫本身不上網、不另外呼叫模型（上網查證在 web_verify.py，預設關）：
#   - 開始時讀入，每一輪換話題判斷與每次話題摘要的提示詞附上詞庫（最多 上限 個）。
#   - 話題摘要那一次呼叫順便列出這一題有把握的名詞（【名詞】那一行），新的原文自動加進詞庫並存檔。
# 檔案格式（每行一個名詞）：中文寫法｜原文｜來源｜備註（備註可省略）
#   來源：手動、候選、上網。只寫「中文寫法」或「中文寫法｜原文」的行當作手動。
#   上網＝上網查證確認過的台灣通行寫法（和手動一樣提供給摘要），備註是來源網址（可能再接「正式原文：…」）。
#   候選的備註「已查」＝上網查證查過、找不到可靠寫法，之後不再查。
#   候選＝話題摘要自動加入的：當場可以給之後的摘要用，下一場起不提供給摘要（模型可能編錯字）；改成「手動」才會使用。
#   舊檔裡的「自動」一律當作候選處理（檔案內容不改寫）。
#   「#」開頭的行是說明；格式不對的行略過不用，但存檔時原樣保留，不會被刪掉。
import os
import re
import tempfile
import threading

資料夾 = os.path.join(os.path.dirname(os.path.abspath(__file__)), "詞庫")    # 測試會改成暫存資料夾
上限 = 30                 # 提示詞最多附幾個名詞
每題最多新增 = 10         # 一次話題摘要最多自動加入幾個
來源們 = ("手動", "候選", "自動", "上網")      # 「自動」是舊檔的寫法，讀進來當候選
分隔 = re.compile(r"[｜|]")
最長 = 30                 # 寫法或原文超過這麼多字，當作不是名詞
已查 = "已查"             # 候選的備註：上網查證查過、查無，之後不再查
_鎖們 = {}                # 詞庫檔路徑 -> 鎖：「重讀→修改→寫檔」整段與記憶體詞庫的更新都要拿鎖（背景查證與話題摘要可能同時寫）
_鎖們的鎖 = threading.Lock()


def 檔案鎖(路徑):
    """同一個詞庫檔共用一把鎖（不同的 詞庫 物件、scripts 的小工具也一樣）。"""
    with _鎖們的鎖:
        return _鎖們.setdefault(os.path.normcase(os.path.abspath(路徑)), threading.RLock())

檔頭 = (
    "# 直播主專有名詞詞庫：{直播主}\n"
    "# 每行一個名詞：中文寫法｜原文｜來源（手動／候選）。中文直播的名字可以只寫「中文寫法」。\n"
    "# 手動加入：照格式新增一行，來源寫「手動」（或不寫）。刪除：整行刪掉。手動的行不會被程式改動或刪除。\n"
    "# 「候選」是話題摘要自動加入的，只在加入的那一場使用；確認寫法沒錯，把「候選」改成「手動」，下一場起才會使用。\n"
    "# 「上網」是上網查證確認過的寫法（最後一欄是來源網址），和手動一樣每一場都會使用；候選最後一欄「已查」＝查過、查無。\n"
    "# 「#」開頭的行是說明，不會被讀取。存檔請用 UTF-8。\n"
)

詞庫提示 = (
    "【直播主詞庫】這位直播主過去出現過的名字與固定寫法（中文寫法（原文））：{詞們}\n"
    "使用規則：\n"
    "- 語音稿裡出現詞庫中的名字（原文或發音對得上）時，一律沿用詞庫的中文寫法，不要另創寫法。\n"
    "- 使用詞庫的名字時，中文寫法寫在外面、原文放在括號裡，不可反過來（例如「普莉露（プリル）」，不可寫成「プリル（普莉露）」）；"
    "詞庫的詞條沒有原文時，就只寫中文。\n"
    "- 語音稿沒有提到的名字，不可因為詞庫裡有就寫進摘要。\n"
    "- 詞庫裡沒有的名字，照原本的規則處理。\n\n"
)

名詞格式 = (
    "【名詞】這一題語音稿裡出現、而且你有把握寫法的專有名詞，只列人名、作品名、遊戲名、角色名、團體名、店名、地名、梗名，"
    "格式「中文寫法（原文）」：台灣慣用的繁體中文寫法在前、原文在括號裡，不可反過來，用「；」分隔；原文本來就是中文的只寫中文；"
    "註明「不確定」的、看不懂的、疑似轉錄錯誤的不要列；一般詞彙一律不要列（食物、日用品、運動器材、玩具種類等任何人都會用的普通名詞，例如蛋白粉、呼拉圈、籃球）；沒有就寫「【名詞】無」。這一行放在最後\n"
)


def 檔名安全(名字):
    """直播主名字轉成可當檔名的字（去掉 Windows 檔名不能用的字元）。"""
    名字 = re.sub(r'[\\/:*?"<>|\s]+', "_", str(名字 or "")).strip("._")
    return 名字[:60]


def _鍵(字):
    return re.sub(r"\s+", "", 字).casefold()


class 條目:
    def __init__(self, 寫法, 原文="", 來源="手動", 備註=""):
        self.寫法, self.原文, self.來源, self.備註 = 寫法, 原文, 來源, 備註

    def 鍵(self):
        """同一個名詞的判斷：有原文看原文，沒有原文（中文名字）看寫法。"""
        return _鍵(self.原文 or self.寫法)

    def 顯示(self):
        return f"{self.寫法}（{self.原文}）" if self.原文 and self.原文 != self.寫法 else self.寫法

    def 存檔行(self):
        行 = f"{self.寫法}｜{self.原文}｜{self.來源}"
        return 行 + "｜" + 分隔.sub(lambda m: "%7C", self.備註) if self.備註 else 行     # 網址裡的「|」編碼掉，免得被當成欄位分隔

    def 已查過(self):
        """候選查過、查無（備註「已查」）。"""
        return self.來源 == "候選" and self.備註.startswith(已查)

    def 待查證(self):
        """還沒查過的候選（上網、手動、已查過的候選都不查）。"""
        return self.來源 == "候選" and not self.已查過()

    def 網址(self):
        m = re.search(r"https?://\S+", self.備註)
        return m.group(0) if m else ""


def 解析行(行):
    """一行 → 條目；說明行、空行回傳 None；格式不對丟出 ValueError。"""
    行 = 行.strip()
    if not 行 or 行.startswith("#"):
        return None
    欄 = [x.strip() for x in 分隔.split(行)]
    if len(欄) > 4:
        raise ValueError("欄位太多")
    寫法 = 欄[0]
    原文 = 欄[1] if len(欄) > 1 else ""
    來源 = (欄[2] if len(欄) > 2 else "") or "手動"
    備註 = 欄[3] if len(欄) > 3 else ""
    if not 寫法 or 來源 not in 來源們 or len(寫法) > 最長 or len(原文) > 最長:
        raise ValueError("格式不對")
    return 條目(寫法, 原文, "候選" if 來源 == "自動" else 來源, 備註)      # 舊檔的「自動」＝候選


def 讀檔(路徑):
    """回傳 (條目們, 原始行們, 格式錯行數)。檔案不存在 → 空的。讀不懂（不是 UTF-8 等）丟出例外。"""
    if not os.path.exists(路徑):
        return [], [], 0
    with open(路徑, encoding="utf-8-sig") as f:
        原始 = f.read().splitlines()
    條目們, 錯 = [], 0
    for 行 in 原始:
        try:
            e = 解析行(行)
        except ValueError:
            錯 += 1
            continue
        if e:
            條目們.append(e)
    return 條目們, 原始, 錯


def 安全寫入(路徑, 文字):
    """先寫同資料夾的暫存檔再取代原檔（比照 config.寫入設定），寫到一半失敗原檔不會壞。"""
    os.makedirs(os.path.dirname(路徑), exist_ok=True)
    fd, 暫存 = tempfile.mkstemp(prefix="詞庫.", suffix=".txt.tmp", dir=os.path.dirname(路徑))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(文字)
        os.replace(暫存, 路徑)
    except BaseException:
        if os.path.exists(暫存):
            os.remove(暫存)
        raise


# ---- 模型回覆的【名詞】清單 ----
名詞行 = re.compile(r"^[ \t]*[-*]?[ \t]*【名詞】", re.MULTILINE)
括號 = re.compile(r"^(.+?)[（(]([^（）()]+)[）)]$")
假名 = re.compile(r"[぀-ヿ]")
# 常見的日文新字體（台灣繁體不用這個字形）。中文寫法裡出現這些字＝還沒翻成台灣寫法
日文字形 = set("弾鉄伝説読売気広応関来図対発変戦帰黒楽様県駅転労円単団悪圧囲価歓権検険験剣厳済歯児実写釈収従渋"
           "獣縦処条乗譲触尽粋静専浅銭禅装層総騒蔵続帯滞沢遅昼聴稲闘独弐悩脳廃拝麦髪抜仏塀辺宝豊没満万黙薬訳"
           "揺頼乱覧竜両猟緑涙塁励霊齢恋炉楼湾")
不是名詞 = re.compile(r"無關|有關|相關|之類|等等|不是|沒有|好像|可能")


def _日文(字):
    return bool(假名.search(字)) or any(c in 日文字形 for c in 字)


def _整理(寫法, 原文):
    """一個名詞的檢查與修正，回傳 (寫法, 原文)，不收就回傳 None。
    模型偶爾寫反成「原文（中文）」：中文寫法是日文、括號裡是中文時對調；兩邊都是日文就不收。"""
    if 原文 and _日文(寫法) and not _日文(原文) and re.search(r"[一-鿿]", 原文):
        寫法, 原文 = 原文, 寫法
    if _日文(寫法) or 不是名詞.search(寫法):     # 中文寫法裡還有假名或日文字形：模型沒把握怎麼翻，不收
        return None
    return 寫法, ("" if 原文 == 寫法 else 原文)


def 拆名詞(內文):
    """從話題摘要回覆裡拿掉【名詞】那一段（含後面接著的條列行），回傳 (乾淨內文, [(寫法, 原文)])。
    沒有【名詞】就原樣回傳、清單是空的。格式看不懂的項目略過。"""
    ms = list(名詞行.finditer(內文))
    if not ms:
        return 內文, []
    m = ms[-1]
    後面 = 內文[m.end():].split("\n")
    清單行 = [後面[0]]
    剩下 = []
    for i, 行 in enumerate(後面[1:], 1):
        if 行.strip() and not 行.lstrip().startswith("【"):
            清單行.append(行)        # 模型把清單換行寫成條列：算同一段
        else:
            剩下 = 後面[i:]
            break
    乾淨 = (內文[:m.start()].rstrip() + ("\n" + "\n".join(剩下) if any(x.strip() for x in 剩下) else "")).rstrip()
    return 乾淨, 解析名詞("；".join(清單行))


def 解析名詞(字):
    結果 = []
    for 項 in re.split(r"[；;、\n]", 字):
        項 = re.sub(r"^[\s\-*・•]+", "", 項).strip().rstrip("。.")
        if not 項 or 項 in ("無", "（無）", "沒有") or "不確定" in 項 or "?" in 項 or "？" in 項:
            continue
        m = 括號.match(項)
        寫法, 原文 = (m.group(1).strip(), m.group(2).strip()) if m else (項, "")
        if (not re.search(r"\w", 寫法) or re.search(r"[（）()【】]", 寫法 + 原文)
                or len(寫法) > 最長 or len(原文) > 最長 or 分隔.search(寫法 + 原文)):
            continue
        項目 = _整理(寫法, 原文)
        if 項目:
            結果.append(項目)
    return 結果


class 詞庫:
    def __init__(self, 直播主, 資料夾路徑=None):
        self.直播主 = 直播主
        self.路徑 = os.path.join(資料夾路徑 or 資料夾, 檔名安全(直播主) + ".txt")
        self.條目們 = []
        self.格式錯 = 0
        self.可寫 = True          # 讀不懂原檔時不寫，免得把使用者的檔案蓋掉
        self.讀錯誤 = ""
        self._用過 = {}           # 鍵 -> 這一場最後一次用到的順序（越大越新）
        self._序 = 0
        self._本場 = set()        # 這一場自動加入的候選（鍵）：當場可用，下一場起不提供給摘要
        try:
            self.條目們, _, self.格式錯 = 讀檔(self.路徑)
        except (OSError, ValueError) as e:
            self.可寫 = False
            self.讀錯誤 = str(e)

    def 可用(self, e):
        """可以提供給摘要的條目：手動、上網；候選只有這一場自動加入的才算。"""
        return e.來源 != "候選" or e.鍵() in self._本場

    def 數量(self):
        """(提供給摘要的數量, 這一場不使用的候選數量)。"""
        用 = sum(1 for e in self.條目們 if self.可用(e))
        return 用, len(self.條目們) - 用

    def 鍵們(self):
        return {e.鍵() for e in self.條目們}

    def 標記用過(self, 鍵們):
        for k in 鍵們:
            self._序 += 1
            self._用過[k] = self._序

    def 挑選(self, 相關文字="", 上限數=None):
        """選出要放進提示詞的名詞：手動的優先，其次這一場最近用到的、出現在相關文字裡的，再來是較晚加入的。"""
        上限數 = 上限 if 上限數 is None else 上限數

        def 出現(e):
            return bool(相關文字) and ((e.原文 and e.原文 in 相關文字) or e.寫法 in 相關文字)
        帶位置 = [p for p in enumerate(self.條目們) if self.可用(p[1])]
        手動 = sorted([p for p in 帶位置 if p[1].來源 == "手動"], key=lambda p: (not 出現(p[1]), p[0]))
        其他 = sorted([p for p in 帶位置 if p[1].來源 != "手動"],
                    key=lambda p: (not 出現(p[1]), -self._用過.get(p[1].鍵(), 0), -p[0]))
        選 = [e for _, e in (手動 + 其他)[:上限數]]
        return [e for e in self.條目們 if e in 選]         # 照檔案順序列出，比較好讀

    def 提示段(self, 相關文字=""):
        """詞庫是空的時回傳空字串（提示詞完全不出現詞庫段落）。"""
        選 = self.挑選(相關文字)
        if not 選:
            return ""
        return 詞庫提示.replace("{詞們}", "、".join(e.顯示() for e in 選))

    def 自動加入(self, 名詞們, 原稿=None):
        """名詞們：[(寫法, 原文)]。只加詞庫裡還沒有的；手動的資料不會被改動或刪除。
        原稿：這一題的語音稿。有給時，原文（沒有原文就看寫法）必須真的出現在稿裡才收：
        模型有詞庫可看時，常把詞庫裡的名字整串抄進清單（稿裡根本沒提到），不能算「這一題用到」。
        存檔前重讀一次檔案（直播中使用者可能用記事本改過），新的接在最後。回傳真的加入的條目。"""
        if 原稿 is not None:
            稿 = _鍵(原稿)
            名詞們 = [(w, o) for w, o in 名詞們 if _鍵(o or w) in 稿]
        if not self.可寫:
            return []
        with 檔案鎖(self.路徑):        # 背景的上網查證可能同時寫回同一個檔
            return self._自動加入(名詞們)

    def _自動加入(self, 名詞們):
        try:
            現有, 原始, self.格式錯 = 讀檔(self.路徑)
        except (OSError, ValueError) as e:
            self.可寫, self.讀錯誤 = False, str(e)
            return []
        self.條目們 = 現有
        已有 = self.鍵們()
        已有寫法 = {_鍵(e.寫法) for e in 現有}
        新的, 用到 = [], []
        for 寫法, 原文 in 名詞們:
            e = 條目(寫法, 原文, "候選")
            k = e.鍵()
            if k in 已有 or (not 原文 and _鍵(寫法) in 已有寫法):
                用到.append(k)
                continue
            if len(新的) >= 每題最多新增:
                break
            新的.append(e)
            已有.add(k)
            已有寫法.add(_鍵(寫法))
            用到.append(k)
        self.標記用過(用到)
        self._本場 |= {e.鍵() for e in 新的}
        if not 新的:
            return []
        行們 = 原始 if 原始 else 檔頭.replace("{直播主}", self.直播主).rstrip("\n").split("\n")
        文字 = "\n".join(行們 + [e.存檔行() for e in 新的]) + "\n"
        安全寫入(self.路徑, 文字)      # 失敗丟出例外，由呼叫的人提示（摘要照常）
        self.條目們 = 現有 + 新的
        return 新的

    def 待查證們(self):
        """還沒查過的候選（scripts/verify_glossary.py 用；直播中只查這一場新加入的）。同一個名詞已有手動或上網的不查。"""
        定了 = {e.鍵() for e in self.條目們 if e.來源 != "候選"}
        return [e for e in self.條目們 if e.待查證() and e.鍵() not in 定了]

    def 還要查(self, 鍵):
        """這個名詞現在還是「沒查過的候選」嗎（使用者可能剛把它改成手動或刪掉）。"""
        return any(e.鍵() == 鍵 and e.待查證() for e in self.條目們) and not any(
            e.鍵() == 鍵 and e.來源 != "候選" for e in self.條目們)

    def 套用查證(self, 鍵, 寫法=None, 網址="", 正式原文=""):
        """上網查證的結果寫回詞庫。寫法有給＝查到（改成「上網」、備註放來源網址）；沒給＝查無（候選標「已查」）。
        只改「還沒查過的候選」那幾行；手動、上網、已查過的不動；同一個名詞已有手動或上網的詞條也不動。
        存檔前重讀檔案（使用者或話題摘要可能剛改過），整段拿鎖。回傳改了幾行。"""
        if not self.可寫:
            return 0
        with 檔案鎖(self.路徑):
            try:
                現有, 原始, self.格式錯 = 讀檔(self.路徑)
            except (OSError, ValueError) as e:
                self.可寫, self.讀錯誤 = False, str(e)
                return 0
            if any(e.鍵() == 鍵 and e.來源 != "候選" for e in 現有):
                self.條目們 = 現有
                return 0
            改了 = 0
            新行們 = []
            for 行 in 原始:
                try:
                    e = 解析行(行)
                except ValueError:
                    e = None
                if e is not None and e.鍵() == 鍵 and e.待查證():
                    if 寫法:
                        備註 = 網址 + (f" 正式原文：{正式原文}" if 正式原文 and 正式原文 != e.原文 else "")
                        e = 條目(寫法, e.原文, "上網", 備註.strip())
                    else:
                        e = 條目(e.寫法, e.原文, "候選", 已查)
                    行 = e.存檔行()
                    改了 += 1
                新行們.append(行)
            if 改了:
                安全寫入(self.路徑, "\n".join(新行們) + "\n")
                現有, _, _ = 讀檔(self.路徑)
            self.條目們 = 現有
            return 改了
