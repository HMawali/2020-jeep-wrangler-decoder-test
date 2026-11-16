$p = New-Object System.IO.Ports.SerialPort 'COM3',115200,'None',8,'One'; $p.DtrEnable=$true; $p.ReadTimeout=300; $p.Open()
function Snd($c){ $p.Write("$c`r"); Start-Sleep -Milliseconds 120; $p.ReadExisting()|Out-Null }
function Read137($ms){
  $p.DiscardInBuffer(); $buf=''; $sw=[Diagnostics.Stopwatch]::StartNew()
  while($sw.ElapsedMilliseconds -lt $ms){ $buf += $p.ReadExisting(); Start-Sleep -Milliseconds 15 }
  $last=$null; foreach($ln in ($buf -split "`r")){ if($ln -match '^t137.(.*)$'){ $last=$matches[1] } }
  return $last
}
try {
  Snd 'C'; Snd 'M0'; Snd 'S6'; Snd 'O'
  $before = Read137 1200
  "ESS state 0x137 BEFORE: $before"
  # emulate one ~300ms button press on 0x297 (byte6 = 0x24)
  $sw=[Diagnostics.Stopwatch]::StartNew()
  while($sw.ElapsedMilliseconds -lt 300){ $p.Write("t2978F0FF0300000C24FF`r"); Start-Sleep -Milliseconds 10 }
  Start-Sleep -Milliseconds 300
  $after = Read137 1200
  "ESS state 0x137 AFTER : $after"
  if($before -ne $after){ "RESULT: STATE CHANGED -> injection toggled ESS" } else { "RESULT: no state change" }
} finally { $p.Write("C`r"); Start-Sleep -Milliseconds 80; $p.Close() }
