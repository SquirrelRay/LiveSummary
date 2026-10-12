直播重點摘要（階段 1）

第一次設定：
1. 安裝套件：pip install anthropic
2. 設定金鑰（只做一次，PowerShell）：
   setx ANTHROPIC_API_KEY "你的金鑰"
   設完後「關掉再重開」終端機才會生效。

使用：
   python summarize.py sample.txt --type game
   python summarize.py 文字稿.txt --type chat

結果會印在畫面上，並存成「原檔名_摘要.md」。

設定檔 config.json（用 live_topics.py 時）：
  功能開關和常用數字都寫在 config.json，用記事本打開改就好，改完存檔，下次執行就生效。
  命令列參數只是「這一次」臨時覆蓋，優先順序：命令列 > config.json > 程式內建預設。
  欄位：chat（聊天室）、minute_summary（分鐘摘要）、save_audio（存音訊）、fix_with_chat（聊天室參考詞修正）、
        check_minutes、min_topic_min、max_topic_min、model、whisper_model、language、minute_sentences（1 到 3）。
  看目前實際生效的設定與來源：  python live_topics.py --show-config
  臨時覆蓋範例：  --no-chat / --chat、--no-minute / --minute、--no-save-audio / --save-audio、--fix / --no-fix
  注意：API 金鑰不要寫進 config.json，只放在環境變數（預設 ANTHROPIC_API_KEY，可用 api_key_env 改名字）。
  金鑰無效時，程式會用一句中文停下來，不會繼續空跑。

外語直播（日文等）：
  config.json 的 language 可填 "zh"（預設，中文）、"ja"（日文）、"en"（英文）、"ko"（韓文）、"auto"（自動偵測）。
  命令列臨時覆蓋：  python live_topics.py --live 網址 --lang ja     或   --lang auto
  auto：用第一段（約 20 秒）有人聲的音訊判斷語言（靜音或只有音樂的段會跳過、等下一段），判斷出來就鎖定，之後都用這個語言；失敗會印警告並退回中文。
  不管直播什麼語言，摘要一律是繁體中文；專有名詞第一次出現會附原文，看不懂的詞會標「不確定」。
  轉錄外語影片：  python transcribe.py 影片或網址 --lang ja
  文字稿模式跑外語稿：  python live_topics.py 日文稿.txt --lang ja
  --show-config 會顯示 language 目前的值與來源。

切換語言模型（live_topics.py；config.json 改這幾欄）：
  provider     ："anthropic"（預設，Claude）或 "openai_compatible"（OpenAI、DeepSeek、Ollama 等）
  base_url     ：服務網址，空白 = 該家預設
  api_key_env  ：金鑰放在哪個「環境變數名稱」（不是金鑰本身！）；留空 = 不需要金鑰（Ollama）
  model        ：模型名稱
  price_input / price_output：每百萬 token 的美元單價，只用來估算費用（單價未查證，請自行到官網確認）
  呼叫模型的程式都在 llm.py。summarize.py 單獨使用時仍固定用 Claude。
  用 openai_compatible 前要先裝套件：pip install openai
  金鑰無效、或連不上伺服器（例如 Ollama 沒開）時，程式會用一句中文說明並停止。
  拿不到 token 數的服務，結束時會顯示「無法計算」。

  範例（2026-10-10 查官方文件；模型名稱常會更新，用之前請再到官網確認）：
  OpenAI：（金鑰先 setx OPENAI_API_KEY "你的金鑰"）
    "provider": "openai_compatible", "base_url": "https://api.openai.com/v1",
    "api_key_env": "OPENAI_API_KEY", "model": "gpt-6-luna"
    （base_url 是從官方範例網址推得的；gpt-6-luna 是官方列的小型便宜款，大型款 gpt-6-astra）
  DeepSeek：（金鑰先 setx DEEPSEEK_API_KEY "你的金鑰"）
    "provider": "openai_compatible", "base_url": "https://api.deepseek.com",
    "api_key_env": "DEEPSEEK_API_KEY", "model": "deepseek-flash"
    （另有 deepseek-v4-pro）
  Ollama（本機，不用金鑰，先開 Ollama 並下載模型）：
    "provider": "openai_compatible", "base_url": "http://localhost:11434/v1",
    "api_key_env": "", "model": "gpt-oss:20b", "price_input": 0, "price_output": 0
    （model 換成你自己用 ollama pull 下載的模型名稱）
  換回 Claude：
    "provider": "anthropic", "base_url": "", "api_key_env": "ANTHROPIC_API_KEY", "model": "claude-haiku-5-5"

舊的摘要框／字幕框與精簡模式已移除（由啟動面板 → 浮動膠囊 → 可自由擺放的面板取代）：
  全域快捷鍵（Ctrl+Shift+S／A／D／X）、主控台的「字幕」「面板」「精簡」按鈕、Ctrl+Shift+M 都沒有了。
  config.json 裡舊的 overlay 區塊與 hotkey_compact 已停用：讀入時直接忽略、不跳警告，設定框儲存時也不會改寫或刪除它們。
  overlay_位置.json、介面設定.json 裡的「精簡」不再讀取，留著無妨。

設定框（啟動面板的齒輪、膠囊／系統匣選單的「設定」；主控台已沒有「設定」分頁）：
  可調字幕模式、聊天室、分鐘摘要、參考詞修正、延伸思考、分鐘摘要句數、內容顯示方向、各分頁顯示上限、翻譯批次、模型服務與模型名稱、存檔。
  按「儲存」才寫回 config.json，寫之前自動備份成 config.backup.json；只改表單上的欄位，其他欄位原樣保留。
  「還原預設值」會把表單變回預設（一樣要按「儲存」才寫入）。金鑰只顯示「已設定／未設定」。
  執行中改到的功能、模型等項目會標「下次開始生效」。

逐句翻譯（字幕模式 subtitle_mode："original" 原文、"translate" 一律翻譯、"auto" 中文原文其他語言翻譯）：
  語言選「自動偵測」時，偵測到外語後字幕會自動切成翻譯。
  翻譯呼叫已關閉延伸思考並限制輸出長度，費用約為原本的 1/6。
  批次：translate_batch_seconds（預設 8 秒）、translate_batch_lines（預設 4 句），可在 config.json 或設定框調。
  翻譯另外計費，主控台「翻譯」藥丸與結束訊息會分開顯示次數與費用。

逐句翻譯分頁、並排、網址紀錄（介面 app.py 才有）：
  逐句翻譯分頁：每則顯示時間、譯文（主）和較小較淡的原文。翻譯模式下，同時即時存成「原檔名_逐句翻譯.txt」
  （第一句寫入時才建立；同名舊檔已存在就改用加了時間的新檔名，不覆蓋）。翻譯失敗或逾時沒翻的句子存原文並標「【未翻譯】」。
  原文模式（例如中文直播）：分頁只顯示原文，頂端註明「目前為原文模式」，不另存檔。
  翻譯要「逐句翻譯」面板開著才會進行（沒開就不翻，省費用；其他面板不需要翻譯）。分頁最多顯示幾則：config.json 的 ui_max_translation（預設 500），超過顯示「較早的內容已存檔」與「打開檔案」。
  並排：分頁列右邊的「並排」選 1／2／3 欄，每欄各有一條分頁列，各自選要看的分頁；同一個分頁只會在一欄出現，
  在這一欄選到別欄正在看的分頁會兩欄互換。視窗窄於約 1100 自動剩 1 欄、窄於約 1600 最多 2 欄，變寬自動回到你選的欄數。
  欄數與每欄選的分頁記在 介面設定.json（本機檔案，不進 git）。
  網址紀錄：點直播網址欄會列出最近用過的 10 個網址（顯示頻道名稱），點一下填入；★ 可釘選（固定在最上方，不計入 10 個），✕ 刪除。
  只有成功開始擷取的網址才會記下，存在 網址紀錄.json（本機檔案，不進 git）。
  設定框的數字欄位、下拉選單：沒點選時滑鼠滾輪只捲動整個設定頁，不會誤改數值。

按「停止」後會顯示「正在產生最後一個話題的摘要，約需 10 秒…」，完成後膠囊旁出現幾秒後自動消失的小提示（「已結束」，有存檔時「已結束，已存檔」），不再跳彈窗。

啟動面板（python app.py 開程式時出現，主控台不會自動出現）：
  網址欄（點一下有網址紀錄）、語言（預設「自動偵測」）、開始、右上角齒輪（設定）、✕（收起）。
  按「開始」＝主控台的「開始」；成功開始擷取後啟動面板收起，並套用上次使用的版面（沒有就用預設版面）讓面板出現。
  按下開始後面板顯示「啟動中…（目前階段）」與跑動的進度條，開始鈕停用；啟動中也可按「結束」直接關閉程式（不需確認）。
  網址錯誤、頻道沒開播等錯誤直接顯示在啟動面板裡。收起後可從膠囊／系統匣選單「開始…」打開（直播中沒有這項）。
  膠囊／系統匣選單另有「設定」（和齒輪同一個設定視窗）、「顯示主控台」。關閉主控台只是收起，要結束程式請用「結束程式」。

存檔（設定的「存檔」區，config.json 的 save_summary、save_transcript、save_chat、save_translation、save_audio，預設全關）：
  打開的項目才寫檔（存在專案資料夾，「打開存檔資料夾」可直接打開）；關掉的內容只顯示在畫面上，
  分頁與面板超過顯示上限時顯示「較早的內容已移除」（沒有「打開檔案」）。直播稿、聊天室、音訊只在直播網址模式有作用。

版本存檔（Git，只存在這台電腦，不會上傳）：
  存一個新的存檔點：  git add -A && git commit -m "這次改了什麼"
  回到上一版（放棄還沒存檔的修改）：  git restore .
  回到上一個存檔點的樣子（保留歷史）：  git revert HEAD
  看有哪些存檔點：  git log --oneline

啟動時間里程碑紀錄：每次按「開始」，會在 logs/啟動里程碑_日期_時間.txt 記下各階段（模型載入、第一段音訊、第一段轉錄、第一句翻譯、第一句顯示）從按下開始起算的秒數，不含金鑰。
面板（分鐘摘要、話題摘要、逐句翻譯）還沒有內容時，會依階段顯示「載入模型中…／聆聽中，等待第一段…／轉錄與翻譯中…」，第一句出現後消失。

狀態列的「語言」藥丸：一直顯示目前語言（例如「語言：日文（自動偵測）」「語言：日文（手動）」，自動偵測中顯示「偵測中…」）。
語言設為自動時，旁邊有「重新偵測」鈕（膠囊選單也有，固定在「開始…／停止」下方）：不中斷直播，用下一段有人聲的音訊重新判斷。信心低於 0.4 時，第一次會退回中文並明確標示「偵測不確定」；重新偵測低信心則維持原語言。
主控台收著時也看得到語言警告：偵測不確定或失敗時，膠囊上多一段黃色「⚠ 語言」（燈色不變），膠囊旁跳出約 8 秒的提示；
膠囊與系統匣的滑鼠提示也會顯示目前語言。重新偵測成功或按停止後，「⚠ 語言」就消失。
錯誤提示：直播中途的錯誤（例如金鑰失效）、config.json 的設定警告，除了主控台的提示條，也會在膠囊旁用紅框中文提示約 12 秒。
啟動中的錯誤（網址錯誤、沒開播）照舊顯示在啟動面板裡。
