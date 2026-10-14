# 簡體字轉繁體：給使用者看的中文輸出（分鐘摘要、話題摘要、支線、逐句翻譯、聊天室翻譯）最後一道關卡。
# 簡體字的來源：Whisper 轉出的中文稿偶爾（VOD 腳本用自動偵測時則是整份）是簡體，模型照抄人名、詞語。
# 用 OpenCC（Apache-2.0，可與 GPLv3 一起發布）的 s2tw（簡體 → 台灣繁體字形，不改用詞）。
# 原則：已經是繁體的文字一字不動。OpenCC 對繁體文字也會改（干擾→幹擾、于→於、台灣→臺灣），
#   所以以「子句」為單位，只有子句裡出現確定是簡體的字才轉那一句（整句有上下文，后来→後來 這類才轉得對）。
# 不轉的：
#   - 詞庫裡手動、上網確認過的顯示寫法與原文（使用者設定的寫法照原樣，就算是簡體或日文漢字）；
#   - 括號裡的原文：含假名的一律不轉；外語直播（保護括號=True）括號裡全部不轉（日文人名的漢字，例如 国木田 不能變 國木田）。
import functools
import re
import threading

import glossary

# OpenCC 1.4.2 的 STCharacters 裡「簡轉繁候選包含自己」的字：在繁體裡本來就合法（干、于、台、后、里…），
# 只有這些字的子句不當作簡體。產生方法：opencc_dict -i STCharacters.ocd2 -o 字.txt -f ocd2 -t text，取候選含自己的那些行。
兼用字 = frozenset(
    "㐹万丑丰了于云亘仆仇价仿伙余佛佣俊修借僵克党具冢冬准凌几凶出划刮制千升卜占卷厂厘只台叶吁吃合吊同后向"
    "吣呆周咨咸咽哄唇喂噪回困坐坯堤夫夸奸姜娘它家尸局岩岳巨布帘席干幸广庵弦彩征御志念恤愈愿戚扇才扎托扣折"
    "抵拐拿挂挨挽捆捍据搜斗斤斫旋昆暗曲札朱朴杆杠杯杰松板极果柜栗核梁棱檗欲沈沾泛注浚涂涌淀游溪漓澄焰熏狸"
    "玩琅璇症皂矩确硷私秋种穗筑筱糊系累耇胄背胜胡腊腌膻致舍芸苔苹范荐蒙蔑藤虫蚝蜡蝎表谷豆象跖辟适郁酸采里"
    "雇雕面")

保護來源們 = ("手動", "上網")      # 詞庫裡這兩種來源的寫法與原文不轉（候選是模型自動加的，照樣轉）
_子句分隔 = re.compile(r"([，。、；：！？,.;:!?\s「」『』《》〈〉“”‘’…—【】\[\]（）()])")
_括號段 = re.compile(r"[（(][^（）()]*[）)]")
_假名 = re.compile(r"[぀-ヿㇰ-ㇿ]")
_佔位起點 = 0xE000                 # Unicode 私用區：OpenCC 不會動這些字元
_轉換器 = None
_鎖 = threading.Lock()             # 摘要、逐句翻譯、聊天室翻譯在不同執行緒，共用一個轉換器


def _opencc():
    """回傳 OpenCC 轉換器；沒裝 opencc 回傳 None（輸出照原樣，不讓摘要或翻譯失敗）。"""
    global _轉換器
    if _轉換器 is None:
        try:
            import opencc
            _轉換器 = opencc.OpenCC("s2tw")
        except Exception:          # noqa: BLE001  沒裝或字典讀不到：不轉
            _轉換器 = False
    return _轉換器 or None


def _轉(字):
    with _鎖:
        return _opencc().convert(字)


@functools.lru_cache(maxsize=8192)
def 是簡體字(字):
    """這個字確定是簡體（繁體不用這個字形）。"""
    return 字 not in 兼用字 and "一" <= 字 <= "鿿" and _opencc() is not None and _轉(字) != 字


def 保護詞們():
    """這一場詞庫裡不能被轉的寫法與原文（手動、上網）。沒有詞庫就是空的。"""
    詞庫 = glossary.本場詞庫
    if 詞庫 is None:
        return []
    return [w for e in list(詞庫.條目們) if e.來源 in 保護來源們 for w in (e.寫法, e.原文) if w]


def 轉繁體(文字, 保護括號=False, 保護詞=None):
    """把文字裡的簡體子句轉成台灣繁體；本來就是繁體的子句原樣保留。
    保護括號：外語直播時傳 True，括號裡的原文（日文人名等）一律不轉。保護詞：不給就用這一場詞庫的手動、上網寫法。"""
    if not 文字 or _opencc() is None:
        return 文字
    保留 = []

    def 遮(m):
        保留.append(m.group(0))
        return chr(_佔位起點 + len(保留) - 1)

    詞們 = sorted({w for w in (保護詞們() if 保護詞 is None else 保護詞) if w}, key=len, reverse=True)
    if 詞們:
        文字 = re.sub("|".join(map(re.escape, 詞們)), 遮, 文字)
    文字 = _括號段.sub(lambda m: 遮(m) if (保護括號 or _假名.search(m.group(0))) else m.group(0), 文字)
    文字 = "".join(_轉(段) if any(是簡體字(c) for c in 段) else 段 for 段 in _子句分隔.split(文字))
    for i in range(len(保留) - 1, -1, -1):          # 後遮的（括號）先還原，裡面才露出先遮的詞庫寫法
        文字 = 文字.replace(chr(_佔位起點 + i), 保留[i])
    return 文字
