# dismiss_unity_modal.ps1 - 关掉卡住 Unity 编辑器的原生模态对话框
#
# 为什么需要：Unity 的「Save Changes?」等对话框是独立的 #32770 原生窗口，
# 模态期间编辑器整个卡住，AgentBridge 完全无响应 —— 表现为指令超时。
# 从外部看只觉得"Unity 没反应"，很容易误判成网络/编译问题。
#
# 安全策略：只点「不保存 / 否 / 取消」这类非提交按钮，
# 绝不点「保存 / 是」—— 那会写用户的工程文件（场景、Prefab 等）。
#
# 注意：本文件必须是 UTF-8 with BOM，否则 PowerShell 5.1 按 ANSI 读会乱码报错。

param([switch]$Json)
$ErrorActionPreference = 'Stop'

Add-Type @"
using System;
using System.Text;
using System.Collections.Generic;
using System.Runtime.InteropServices;
public class Modal {
  public delegate bool EnumProc(IntPtr h, IntPtr l);
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr l);
  [DllImport("user32.dll")] public static extern bool EnumChildWindows(IntPtr p, EnumProc cb, IntPtr l);
  [DllImport("user32.dll")] public static extern int GetWindowText(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll")] public static extern int GetClassName(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
  [DllImport("user32.dll")] public static extern IntPtr SendMessage(IntPtr h, uint m, IntPtr w, IntPtr l);

  public static List<string[]> FindDialogs(uint pid) {
    var found = new List<string[]>();
    EnumWindows((h, l) => {
      uint p; GetWindowThreadProcessId(h, out p);
      if (p != pid || !IsWindowVisible(h)) return true;
      var cls = new StringBuilder(64); GetClassName(h, cls, 64);
      if (cls.ToString() != "#32770") return true;
      EnumChildWindows(h, (ch, l2) => {
        var cc = new StringBuilder(64); GetClassName(ch, cc, 64);
        if (cc.ToString() != "Button") return true;
        var ct = new StringBuilder(200); GetWindowText(ch, ct, 200);
        found.Add(new string[] { h.ToString(), ch.ToString(), ct.ToString() });
        return true;
      }, IntPtr.Zero);
      return true;
    }, IntPtr.Zero);
    return found;
  }
  public static void Click(IntPtr btn) { SendMessage(btn, 0x00F5, IntPtr.Zero, IntPtr.Zero); }
}
"@

$p = Get-Process Unity -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowHandle -ne 0 } | Select-Object -First 1
if (-not $p) {
  if ($Json) { Write-Output '{"ok":false,"reason":"no-unity"}' } else { Write-Output "no unity process" }
  exit 1
}

$dialogs = [Modal]::FindDialogs([uint32]$p.Id)
if ($dialogs.Count -eq 0) {
  if ($Json) { Write-Output '{"ok":true,"dismissed":0}' } else { Write-Output "no modal dialog" }
  exit 0
}

# 只点这些非提交按钮（小写比较）
$safe = @("don't save", "dont save", "no", "cancel", "close")
$clicked = @()
foreach ($d in $dialogs) {
  $btnHwnd = [IntPtr]$d[1]
  $text = $d[2].Replace("&", "").Trim().ToLower()
  $isSafe = $false
  foreach ($s in $safe) { if ($text -eq $s -or $text.Contains($s)) { $isSafe = $true; break } }
  if ($isSafe) {
    [Modal]::Click($btnHwnd)
    $clicked += $d[2].Replace("&", "")
  }
}

if ($clicked.Count -eq 0) {
  $all = ($dialogs | ForEach-Object { $_[2].Replace("&", "") }) -join " / "
  if ($Json) {
    Write-Output ('{"ok":false,"dismissed":0,"reason":"no-safe-button","buttons":"' + $all + '"}')
  } else {
    Write-Output ("modal found but only committing buttons: " + $all + " - left alone for safety")
  }
  exit 2
}

if ($Json) {
  Write-Output ('{"ok":true,"dismissed":' + $clicked.Count + ',"clicked":"' + ($clicked -join ",") + '"}')
} else {
  Write-Output ("dismissed modal, clicked: " + ($clicked -join ", "))
}
exit 0
