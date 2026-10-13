# Read only the explicitly selected window's UIAutomation subtree.
# Used by native acceptance and diagnostic probes; stdout is a UTF-8 JSON array.
# API: https://learn.microsoft.com/dotnet/api/system.windows.automation.automationelement.fromhandle
param(
  [Parameter(Mandatory = $true)]
  [ValidateRange(1, 9223372036854775807)]
  [long]$WindowHandle
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$utf8Encoding = [System.Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = $utf8Encoding
$OutputEncoding = $utf8Encoding

try {
  Add-Type -AssemblyName UIAutomationClient
  Add-Type -AssemblyName UIAutomationTypes

  # Never fall back to RootElement/the desktop if this HWND is unavailable.
  $automationRoot = [System.Windows.Automation.AutomationElement]::FromHandle(
    [IntPtr]::new($WindowHandle)
  )
  if ($null -eq $automationRoot) {
    throw "No UIAutomation element exists for window $WindowHandle."
  }

  $automationElements = $automationRoot.FindAll(
    [System.Windows.Automation.TreeScope]::Subtree,
    [System.Windows.Automation.Condition]::TrueCondition
  )
  $controlSnapshots = @(
    foreach ($automationElement in $automationElements) {
      $controlSnapshot = $automationElement.Current
      $controlBounds = $controlSnapshot.BoundingRectangle
      $boundingRectangle = $null
      if (-not $controlBounds.IsEmpty) {
        $boundingRectangle = [ordered]@{
          left = $controlBounds.X
          top = $controlBounds.Y
          width = $controlBounds.Width
          height = $controlBounds.Height
        }
      }
      [pscustomobject][ordered]@{
        name = $controlSnapshot.Name
        controlType = $controlSnapshot.ControlType.ProgrammaticName
        automationId = $controlSnapshot.AutomationId
        className = $controlSnapshot.ClassName
        processId = $controlSnapshot.ProcessId
        nativeWindowHandle = $controlSnapshot.NativeWindowHandle
        isOffscreen = $controlSnapshot.IsOffscreen
        isEnabled = $controlSnapshot.IsEnabled
        isKeyboardFocusable = $controlSnapshot.IsKeyboardFocusable
        hasKeyboardFocus = $controlSnapshot.HasKeyboardFocus
        boundingRectangle = $boundingRectangle
      }
    }
  )
  $jsonSnapshot = ConvertTo-Json -InputObject $controlSnapshots -Depth 6 -Compress
  [Console]::WriteLine($jsonSnapshot)
} catch {
  [Console]::Error.WriteLine("UIAutomation read failed for window ${WindowHandle}: $($_.Exception.Message)")
  exit 1
}
