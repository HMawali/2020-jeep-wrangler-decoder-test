param([string]$Rate='S4')
# FCA/ISO 29-bit diagnostics: functional request 18DB33F1, physical responses 18DAF1xx
$p = New-Object System.IO.Ports.SerialPort 'COM3',115200,'None',8,'One'; $p.DtrEnable=$true; $p.ReadTimeout=250; $p.Open()
function Snd($c){ $p.Write("$c`r"); Start-Sleep -Milliseconds 120; $p.ReadExisting()|Out-Null }
$resp=@{}
try {
  Snd 'C'; Snd 'M0'; Snd $Rate; Snd 'O'; $p.DiscardInBuffer()
  foreach ($svc in @('0210030000000000','023E000000000000','0209020000000000')) {   # ext session, tester present, VIN
    $p.Write("T18DB33F18$svc`r")
    $sw=[Diagnostics.Stopwatch]::StartNew()
    while($sw.ElapsedMilliseconds -lt 600){
      $buf=$p.ReadExisting()
      foreach($ln in ($buf -split "`r")){
        if($ln -cmatch '^T([0-9A-Fa-f]{8})[0-8]([0-9A-Fa-f]*)$'){ $resp[$matches[1].ToUpper()]=$matches[2].ToUpper() }
      }
      Start-Sleep -Milliseconds 20
    }
  }
} finally { $p.Write("C`r"); Start-Sleep -Milliseconds 80; $p.Close() }
if($resp.Count -eq 0){ "No 29-bit diagnostic responders on $Rate" }
else { "29-bit responders:"; foreach($k in ($resp.Keys|Sort-Object)){ "  0x$k : $($resp[$k])" } }
