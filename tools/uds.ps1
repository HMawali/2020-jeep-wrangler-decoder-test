param(
  [string]$Rate = 'S6',          # 500k = CAN-C powertrain
  [string]$Request = '0100',     # UDS/OBD service+data, hex (e.g. 0100, 0902, 03, 22F190)
  [string]$TxId = '7DF',         # 7DF = functional broadcast; 7E0 = PCM physical
  [int]$TimeoutMs = 1500
)
$p = New-Object System.IO.Ports.SerialPort 'COM3',115200,'None',8,'One'
$p.ReadTimeout = 300; $p.DtrEnable = $true; $p.Open()
function Raw($c) { $p.Write("$c`r"); Start-Sleep -Milliseconds 120; $p.ReadExisting() | Out-Null }
function Frame($id,$bytes) { $d = ($bytes | ForEach-Object { '{0:X2}' -f $_ }) -join ''; "t$id" + '8' + $d }
# parse one slcan line -> @{id=int; data=byte[]}
function Parse($ln) {
  if ($ln -match '^t([0-9A-Fa-f]{3})([0-8])([0-9A-Fa-f]*)$') {
    $id=[Convert]::ToInt32($matches[1],16); $hex=$matches[3]
    $b = for ($i=0;$i -lt $hex.Length;$i+=2){ [Convert]::ToByte($hex.Substring($i,2),16) }
    return @{ id=$id; data=@($b) }
  }
}
$result = @{}
try {
  Raw 'C'; Raw 'M0'; Raw $Rate; Raw 'O'    # normal mode: must ACK/transmit for diagnostics
  $p.DiscardInBuffer()
  $req = for ($i=0;$i -lt $Request.Length;$i+=2){ [Convert]::ToByte($Request.Substring($i,2),16) }
  $sf = @($req.Count) + $req; while ($sf.Count -lt 8){ $sf += 0 }
  $p.Write((Frame $TxId $sf) + "`r")
  $buf=''; $asm=@{}; $expect=@{}
  $sw=[Diagnostics.Stopwatch]::StartNew()
  while ($sw.ElapsedMilliseconds -lt $TimeoutMs) {
    $buf += $p.ReadExisting()
    $parts = $buf -split "`r"; $buf = $parts[-1]
    foreach ($ln in $parts[0..($parts.Count-2)]) {
      $f = Parse $ln; if (-not $f) { continue }
      $id=$f.id; if ($id -lt 0x7E8 -or $id -gt 0x7EF) { continue }
      $d=$f.data; if ($d.Count -lt 1) { continue }
      $pci = $d[0] -shr 4
      if ($pci -eq 0) {                          # single frame
        $n=$d[0] -band 0x0F; $result[$id]=@($d[1..$n])
      } elseif ($pci -eq 1) {                     # first frame -> send flow control, collect
        $tot=(($d[0] -band 0x0F) -shl 8) -bor $d[1]
        $asm[$id]=[System.Collections.Generic.List[byte]]::new()
        $d[2..7] | ForEach-Object { $asm[$id].Add($_) }
        $expect[$id]=$tot
        $phys = $id - 8
        $p.Write((Frame ('{0:X3}' -f $phys) @(0x30,0x00,0x00,0,0,0,0,0)) + "`r")  # FC: clear to send
      } elseif ($pci -eq 2) {                     # consecutive frame
        if ($asm.ContainsKey($id)) { $d[1..7] | ForEach-Object { if ($asm[$id].Count -lt $expect[$id]) { $asm[$id].Add($_) } } }
      }
    }
    foreach ($k in @($asm.Keys)) { if ($asm[$k].Count -ge $expect[$k]) { $result[$k]=$asm[$k].ToArray(); $asm.Remove($k) } }
    if ($result.Count -gt 0 -and $asm.Count -eq 0 -and $sw.ElapsedMilliseconds -gt 400) { break }
  }
} finally { $p.Write("C`r"); Start-Sleep -Milliseconds 80; $p.Close() }

if ($result.Count -eq 0) { "NO RESPONSE to $Request on Tx=0x$TxId"; return }
foreach ($id in ($result.Keys | Sort-Object)) {
  $b=$result[$id]; $hex=($b | ForEach-Object { '{0:X2}' -f $_ }) -join ' '
  $ascii = -join ($b | ForEach-Object { if ($_ -ge 32 -and $_ -lt 127) { [char]$_ } else { '.' } })
  "0x{0:X3}: {1}   | {2}" -f $id, $hex, $ascii
}
