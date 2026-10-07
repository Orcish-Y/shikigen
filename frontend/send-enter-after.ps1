[CmdletBinding()]
param(
    [Parameter()]
    [ValidateRange(0.01, 10080)]
    [double]$DelayMinutes = 60,

    [Parameter()]
    [ValidateRange(0, 3600)]
    [double]$StatusEnterDelaySeconds = 1,

    [Parameter()]
    [ValidateRange(0, 10080)]
    [double]$ContinueDelayMinutes = 1,

    [Parameter()]
    [ValidateRange(0, 3600)]
    [double]$ContinueEnterDelaySeconds = 1,

    [Parameter()]
    [string]$WindowTitle
)

$ErrorActionPreference = 'Stop'

if (-not ('DelayedEnter.KeyboardInput' -as [type])) {
    Add-Type -TypeDefinition @'
using System;
using System.ComponentModel;
using System.Runtime.InteropServices;

namespace DelayedEnter {
    public static class KeyboardInput {
        private const uint InputKeyboard = 1;
        private const uint KeyEventKeyUp = 0x0002;
        private const uint KeyEventUnicode = 0x0004;
        private const ushort VirtualKeyReturn = 0x000D;

        [StructLayout(LayoutKind.Sequential)]
        private struct Input {
            public uint Type;
            public InputUnion Union;
        }

        [StructLayout(LayoutKind.Explicit)]
        private struct InputUnion {
            [FieldOffset(0)]
            public KeyboardInputData Keyboard;

            [FieldOffset(0)]
            public MouseInputData Mouse;
        }

        [StructLayout(LayoutKind.Sequential)]
        private struct KeyboardInputData {
            public ushort VirtualKey;
            public ushort ScanCode;
            public uint Flags;
            public uint Time;
            public UIntPtr ExtraInfo;
        }

        [StructLayout(LayoutKind.Sequential)]
        private struct MouseInputData {
            public int X;
            public int Y;
            public uint MouseData;
            public uint Flags;
            public uint Time;
            public UIntPtr ExtraInfo;
        }

        [DllImport("user32.dll", SetLastError = true)]
        private static extern uint SendInput(uint inputCount, Input[] inputs, int inputSize);

        public static void TypeText(string text) {
            if (String.IsNullOrEmpty(text)) {
                return;
            }

            Input[] inputs = new Input[text.Length * 2];
            for (int index = 0; index < text.Length; index++) {
                KeyboardInputData keyDown = new KeyboardInputData {
                    ScanCode = text[index],
                    Flags = KeyEventUnicode
                };
                KeyboardInputData keyUp = new KeyboardInputData {
                    ScanCode = text[index],
                    Flags = KeyEventUnicode | KeyEventKeyUp
                };

                inputs[index * 2] = new Input {
                    Type = InputKeyboard,
                    Union = new InputUnion { Keyboard = keyDown }
                };
                inputs[index * 2 + 1] = new Input {
                    Type = InputKeyboard,
                    Union = new InputUnion { Keyboard = keyUp }
                };
            }

            Send(inputs);
        }

        public static void PressEnter() {
            KeyboardInputData keyDown = new KeyboardInputData {
                VirtualKey = VirtualKeyReturn
            };
            KeyboardInputData keyUp = new KeyboardInputData {
                VirtualKey = VirtualKeyReturn,
                Flags = KeyEventKeyUp
            };

            Send(new Input[] {
                new Input {
                    Type = InputKeyboard,
                    Union = new InputUnion { Keyboard = keyDown }
                },
                new Input {
                    Type = InputKeyboard,
                    Union = new InputUnion { Keyboard = keyUp }
                }
            });
        }

        private static void Send(Input[] inputs) {
            uint sentCount = SendInput((uint)inputs.Length, inputs, Marshal.SizeOf(typeof(Input)));
            if (sentCount != (uint)inputs.Length) {
                throw new Win32Exception(Marshal.GetLastWin32Error(), "Windows did not accept all simulated keyboard input.");
            }
        }
    }
}
'@
}

function Wait-ForDuration {
    param(
        [Parameter(Mandatory)]
        [TimeSpan]$Duration,

        [Parameter(Mandatory)]
        [string]$Activity
    )

    if ($Duration.TotalMilliseconds -le 0) {
        return
    }

    $deadline = [DateTime]::UtcNow.Add($Duration)
    while ($true) {
        $remaining = $deadline - [DateTime]::UtcNow
        if ($remaining.TotalMilliseconds -le 0) {
            break
        }

        $totalHours = [int][Math]::Floor($remaining.TotalHours)
        $status = '{0:00}:{1:00}:{2:00} remaining' -f $totalHours, $remaining.Minutes, $remaining.Seconds
        $percentComplete = [int][Math]::Max(0, [Math]::Min(100, 100 * (1 - ($remaining.TotalSeconds / $Duration.TotalSeconds))))
        Write-Progress -Activity $Activity -Status $status -PercentComplete $percentComplete

        $sleepMilliseconds = [int][Math]::Max(50, [Math]::Min(1000, [Math]::Ceiling($remaining.TotalMilliseconds)))
        Start-Sleep -Milliseconds $sleepMilliseconds
    }

    Write-Progress -Activity $Activity -Completed
}

$targetProcessId = $null
if (-not [string]::IsNullOrWhiteSpace($WindowTitle)) {
    $matchingProcesses = @(
        Get-Process | Where-Object {
            -not [string]::IsNullOrWhiteSpace($_.MainWindowTitle) -and
            $_.MainWindowTitle.IndexOf($WindowTitle, [System.StringComparison]::OrdinalIgnoreCase) -ge 0
        }
    )

    if ($matchingProcesses.Count -eq 0) {
        throw "没有找到标题包含 '$WindowTitle' 的窗口；未启动计时。"
    }

    if ($matchingProcesses.Count -gt 1) {
        $titles = ($matchingProcesses | ForEach-Object { "PID $($_.Id): $($_.MainWindowTitle)" }) -join [Environment]::NewLine
        throw "窗口标题 '$WindowTitle' 匹配到多个窗口，请提供更具体的标题：`n$titles"
    }

    $targetProcessId = [int]$matchingProcesses[0].Id
    Write-Host "目标窗口：$($matchingProcesses[0].MainWindowTitle) (PID $targetProcessId)"
}
else {
    Write-Warning '未指定 -WindowTitle；每次发送时都会使用当时处于前台的窗口。'
}

$sendAt = (Get-Date).AddMinutes($DelayMinutes)
Write-Host "将在 $($sendAt.ToString('yyyy-MM-dd HH:mm:ss')) 开始发送序列。" -ForegroundColor Cyan
Write-Host '按 Ctrl+C 可取消等待。'

$shell = New-Object -ComObject WScript.Shell
try {
    function Set-TargetWindowFocus {
        if ($null -ne $targetProcessId) {
            if (-not $shell.AppActivate($targetProcessId)) {
                throw "无法激活目标窗口 PID $targetProcessId；已停止，未继续发送。"
            }

            Start-Sleep -Milliseconds 300
        }
    }

    Wait-ForDuration -Duration ([TimeSpan]::FromMinutes($DelayMinutes)) -Activity '等待发送 /status'

    Set-TargetWindowFocus
    [DelayedEnter.KeyboardInput]::TypeText('/status')
    Write-Host "已输入 /status；将在 $StatusEnterDelaySeconds 秒后按 Enter。"

    Wait-ForDuration -Duration ([TimeSpan]::FromSeconds($StatusEnterDelaySeconds)) -Activity '等待提交 /status'
    Set-TargetWindowFocus
    [DelayedEnter.KeyboardInput]::PressEnter()
    Write-Host '/status 已提交。'

    Wait-ForDuration -Duration ([TimeSpan]::FromMinutes($ContinueDelayMinutes)) -Activity '等待发送“继续”'

    Set-TargetWindowFocus
    [DelayedEnter.KeyboardInput]::TypeText('继续')
    Write-Host "已输入“继续”；将在 $ContinueEnterDelaySeconds 秒后按 Enter。"

    Wait-ForDuration -Duration ([TimeSpan]::FromSeconds($ContinueEnterDelaySeconds)) -Activity '等待提交“继续”'
    Set-TargetWindowFocus
    [DelayedEnter.KeyboardInput]::PressEnter()
    Write-Host '“继续”已提交。' -ForegroundColor Green
}
finally {
    if ($null -ne $shell) {
        [void][Runtime.InteropServices.Marshal]::ReleaseComObject($shell)
    }
}
