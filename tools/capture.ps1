param([string]$Rate = '6', [int]$Seconds = 30, [string]$Out)
$p = New-Object System.IO.Ports.SerialPort 'COM3',115200,'None',8,'One'
$p.ReadBufferSize = 1MB; $p.DtrEnable = $true; $p.Open()
function Cmd($c) { $p.DiscardInBuffer(); $p.Write("$c`r"); Start-Sleep -Milliseconds 150; $p.ReadExisting() | Out-Null }
$w = New-Object System.IO.StreamWriter($Out, $false)
$w.WriteLine('time_s,type,id,dlc,data')
$stats = @{}
$pending = ''
try {
  Cmd 'C'; Cmd 'M1'; Cmd "S$Rate"; $p.Write("O`r")   # silent mode: never transmits/ACKs
  $sw = [Diagnostics.Stopwatch]::StartNew()
  while ($sw.Elapsed.TotalSeconds -lt $Seconds) {
    $pending += $p.ReadExisting()
    $parts = $pending -split "`r"
    $pending = $parts[-1]
    $t = $sw.Elapsed.TotalSeconds
    foreach ($f in $parts[0..($parts.Count-2)]) {
      if ($f -match '^([tr])([0-9A-Fa-f]{3})([0-8])([0-9A-Fa-f]*)$' -or $f -match '^([TR])([0-9A-Fa-f]{8})([0-8])([0-9A-Fa-f]*)$' -or $f -match '^([dDbB])([0-9A-Fa-f]{3,8})([0-9A-F])([0-9A-Fa-f]*)$') {
        $type=$matches[1]; $id=$matches[2].ToUpper(); $dlc=$matches[3]; $data=$matches[4].ToUpper()
        $w.WriteLine(('{0:F4},{1},{2},{3},{4}' -f $t,$type,$id,$dlc,$data))
        if (-not $stats.ContainsKey($id)) { $stats[$id] = @{n=0;first=$t;last=$t;dlc=$dlc;payloads=@{};firstData=$data;lastData=$data;mask=@{}} }
        $s = $stats[$id]; $s.n++; $s.last=$t; $s.payloads[$data]=1
        for ($i=0; $i -lt [Math]::Min($data.Length,$s.firstData.Length)/2; $i++) { if ($data.Substring($i*2,2) -ne $s.firstData.Substring($i*2,2)) { $s.mask[$i]=1 } }
        $s.lastData = $data
      }
    }
    Start-Sleep -Milliseconds 20
  }
} finally { try { $p.Write("C`r") } catch {}; $p.Close(); $w.Close() }
$total = 0; foreach ($v in $stats.Values) { $total += $v.n }
"Captured $total frames, $($stats.Count) unique IDs in $Seconds s -> $Out"
$stats.GetEnumerator() | Sort-Object { [Convert]::ToInt32($_.Key,16) } | ForEach-Object {
  $s=$_.Value; $hz = if ($s.last -gt $s.first) { ($s.n-1)/($s.last-$s.first) } else { 0 }
  $chg = (($s.mask.Keys | Sort-Object) -join ',')
  [pscustomobject]@{ ID='0x'+$_.Key; Count=$s.n; Hz=[Math]::Round($hz,1); DLC=$s.dlc; Unique=$s.payloads.Count; ChangingBytes=$chg; LastData=$s.lastData }
} | Format-Table -AutoSize | Out-String -Width 200
