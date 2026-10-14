// LiveSummary.exe 啟動器（C#，由 scripts/stub_build.py 用 Windows 內建的 csc.exe 編譯，約 10 KB；版本資訊與圖示由 build 時帶入）。
//
// 為什麼需要它：PyInstaller 的主程式 exe（LiveSummaryApp.exe）一定要和旁邊的 _internal 資料夾放在一起。
// 在檔案總管裡直接點開 zip 裡的 exe，Windows 只會把「那一個檔案」解壓縮到暫存資料夾，PyInstaller 的開機程式找不到
// _internal\python313.dll，會先跳出一個英文的「Failed to load Python DLL」錯誤——這時 Python 程式碼還沒開始跑，沒辦法在程式裡改成中文提示。
// 所以使用者點的 LiveSummary.exe 是這支獨立的小啟動器：旁邊的檔案齊全就啟動 LiveSummaryApp.exe 然後結束；
// 不齊全（從壓縮檔裡直接開、只複製了 exe…）就跳中文提示然後結束。
// 條件很嚴：只有「真的缺 LiveSummaryApp.exe、helper.exe 或 _internal 資料夾」才會提示，檔案齊全的正常解壓縮不會被擋。
using System;
using System.Diagnostics;
using System.IO;
using System.Text;
using System.Windows.Forms;

static class Stub
{
    const string 標題 = "直播摘要";
    const string 主程式 = "LiveSummaryApp.exe";

    [STAThread]
    static int Main(string[] args)
    {
        string 資料夾 = AppDomain.CurrentDomain.BaseDirectory;
        string[] 必要 = { 主程式, "helper.exe", "_internal" };
        StringBuilder 缺 = new StringBuilder();
        foreach (string 名 in 必要)
        {
            string 路徑 = Path.Combine(資料夾, 名);
            if (!File.Exists(路徑) && !Directory.Exists(路徑))
            {
                if (缺.Length > 0) 缺.Append("、");
                缺.Append(名);
            }
        }

        if (缺.Length > 0)
        {
            string 訊息;
            if (在壓縮檔暫存裡(資料夾))
                訊息 = "請先把整個壓縮檔解壓縮，再執行 LiveSummary.exe。\n\n"
                     + "在壓縮檔裡直接點開時，Windows 只會取出這一個檔案，程式需要旁邊的整個資料夾才能執行。\n"
                     + "做法：在壓縮檔上按右鍵 → 全部解壓縮，再到解壓縮出來的資料夾裡執行 LiveSummary.exe。";
            else
                訊息 = "程式檔案不完整（找不到：" + 缺 + "）。\n\n"
                     + "請重新把整個壓縮檔解壓縮，並確認 LiveSummary.exe 和旁邊的其他檔案、資料夾放在一起（不要只複製 LiveSummary.exe）。";
            MessageBox.Show(訊息, 標題, MessageBoxButtons.OK, MessageBoxIcon.Warning);
            return 1;
        }

        try
        {
            ProcessStartInfo 啟動 = new ProcessStartInfo(Path.Combine(資料夾, 主程式));
            啟動.UseShellExecute = false;
            啟動.WorkingDirectory = 資料夾;
            啟動.Arguments = 引數(args);
            Process.Start(啟動);
            return 0;
        }
        catch (Exception e)
        {
            MessageBox.Show("無法啟動程式：" + e.Message, 標題, MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 1;
        }
    }

    // 檔案總管把 zip 裡的檔案取出到暫存資料夾，資料夾名稱帶著壓縮檔名：
    //   實測（Windows 11）：%TEMP%\<GUID>_LiveSummary-v1.0.0.zip.b8f\LiveSummary\LiveSummary.exe
    //   舊版／其他情況：%TEMP%\Temp1_LiveSummary-v1.0.0.zip\…（重複就是 Temp2_、Temp3_…）
    // 所以只要路徑裡有一層資料夾名稱含「.zip」就算。
    static bool 在壓縮檔暫存裡(string 資料夾)
    {
        return System.Text.RegularExpressions.Regex.IsMatch(資料夾.ToLowerInvariant(), @"\\[^\\]*\.zip[^\\]*(\\|$)");
    }

    static string 引數(string[] args)
    {
        StringBuilder 結果 = new StringBuilder();
        foreach (string a in args)
        {
            if (結果.Length > 0) 結果.Append(' ');
            結果.Append('"').Append(a.Replace("\"", "\\\"")).Append('"');
        }
        return 結果.ToString();
    }
}
