param(
  [string]$Rate = 'S4',          # 125k = CAN-IHS
  [string]$Frame = 't2FA80100C81A00FF0000',  # 0x2FA, 8 bytes, byte0 bit0 = 1 (door open)
  [int]$Seconds = 6,
  [int]$IntervalMs = 20          # ~50 Hz, faster than the real module's ~2 Hz
)
$p = New-Object System.IO.Ports.SerialPort 'COM3',115200,'None',8,'One'
$p.ReadTimeout = 400; $p.DtrEnable = $true; $p.Open()
function Cmd($c) { $p.DiscardInBuffer(); $p.Write("$c`r"); Start-Sleep -Milliseconds 150; ($p.ReadExisting() -replace "`r",'\r' -replace "`a",'BEL') }
try {
  Cmd 'C' | Out-Null
  "normal mode M0 -> '$(Cmd 'M0')'"      # leave silent mode: node will ACK and transmit
  "bitrate $Rate   -> '$(Cmd $Rate)'"
  "err before open -> '$(Cmd 'E')'"
  "open O          -> '$(Cmd 'O')'"
  $ok = 0; $fail = 0
  $sw = [Diagnostics.Stopwatch]::StartNew()
  while ($sw.Elapsed.TotalSeconds -lt $Seconds) {
    $p.DiscardInBuffer()
    $p.Write("$Frame`r")
    Start-Sleep -Milliseconds $IntervalMs
    $r = $p.ReadExisting()
    if ($r -match "`a") { $fail++ } elseif ($r -match "`r") { $ok++ }
  }
  "sent ok=$ok  fail(BEL)=$fail  over $Seconds s"
  "err after inject-> '$(Cmd 'E')'"
} finally { $p.Write("C`r"); Start-Sleep -Milliseconds 100; $p.Close() }
