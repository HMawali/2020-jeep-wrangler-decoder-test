param([string]$Rate='S6', [int]$Start=0x700, [int]$End=0x7FF)
$p = New-Object System.IO.Ports.SerialPort 'COM3',115200,'None',8,'One'; $p.DtrEnable=$true; $p.ReadTimeout=200; $p.Open()
function Snd($c){ $p.Write("$c`r"); Start-Sleep -Milliseconds 120; $p.ReadExisting()|Out-Null }
$resp = @{}
try {
  Snd 'C'; Snd 'M0'; Snd $Rate; Snd 'O'; $p.DiscardInBuffer()
  for ($id=$Start; $id -le $End; $id++) {
    $hx = '{0:X3}' -f $id
    $p.Write("t${hx}80210030000000000`r")   # 10 03 = enter extended diagnostic session (benign)
    Start-Sleep -Milliseconds 6
    $buf = $p.ReadExisting()
    foreach ($ln in ($buf -split "`r")) {
      if ($ln -match '^t([0-9A-Fa-f]{3})[0-8]([0-9A-Fa-f]*)$') {
        $rid=[Convert]::ToInt32($matches[1],16)
        if ($rid -ge 0x600) { $resp[$matches[1].ToUpper()] = $matches[2].ToUpper() }
      }
    }
  }
  # drain
  Start-Sleep -Milliseconds 200; $buf=$p.ReadExisting()
  foreach ($ln in ($buf -split "`r")) { if ($ln -match '^t([0-9A-Fa-f]{3})[0-8]([0-9A-Fa-f]*)$') { $rid=[Convert]::ToInt32($matches[1],16); if ($rid -ge 0x600){ $resp[$matches[1].ToUpper()]=$matches[2].ToUpper() } } }
} finally { $p.Write("C`r"); Start-Sleep -Milliseconds 80; $p.Close() }
if ($resp.Count -eq 0) { "No diagnostic responders in 0x{0:X3}-0x{1:X3} on $Rate" -f $Start,$End }
else { "Responders:"; foreach ($k in ($resp.Keys | Sort-Object)) { $d=$resp[$k]; $svc = if ($d.StartsWith('50')) {'session OK (50)'} elseif ($d.StartsWith('7F')) {'negative (7F)'} else {''}; "  0x$k : $d   $svc" } }
