param([string]$Rate='S6')
# Physical 29-bit sweep: tester->ECU = 18DA{xx}F1, ECU->tester = 18DAF1{xx}
$p = New-Object System.IO.Ports.SerialPort 'COM3',115200,'None',8,'One'; $p.DtrEnable=$true; $p.ReadTimeout=200; $p.Open()
function Snd($c){ $p.Write("$c`r"); Start-Sleep -Milliseconds 120; $p.ReadExisting()|Out-Null }
$resp=@{}
try {
  Snd 'C'; Snd 'M0'; Snd $Rate; Snd 'O'; $p.DiscardInBuffer()
  for ($a=0; $a -le 0xFF; $a++) {
    $id = 'T18DA{0:X2}F18' -f $a
    $p.Write("$id`0210030000000000`r")
    Start-Sleep -Milliseconds 7
    foreach($ln in ($p.ReadExisting() -split "`r")){
      if($ln -cmatch '^T(18DAF1[0-9A-Fa-f]{2})[0-8]([0-9A-Fa-f]*)$'){ $resp[$matches[1].ToUpper()]=$matches[2].ToUpper() }
    }
  }
  Start-Sleep -Milliseconds 200
  foreach($ln in ($p.ReadExisting() -split "`r")){ if($ln -cmatch '^T(18DAF1[0-9A-Fa-f]{2})[0-8]([0-9A-Fa-f]*)$'){ $resp[$matches[1].ToUpper()]=$matches[2].ToUpper() } }
} finally { $p.Write("C`r"); Start-Sleep -Milliseconds 80; $p.Close() }
if($resp.Count -eq 0){ "No physical 29-bit responders on $Rate" }
else { "Physical 29-bit responders (source addr = last 2 hex):"; foreach($k in ($resp.Keys|Sort-Object)){ "  $k : $($resp[$k])" } }
