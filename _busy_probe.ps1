$ErrorActionPreference='Continue'
Add-Type @"
using System;using System.Runtime.InteropServices;
public class K{ [DllImport("user32.dll")] public static extern void keybd_event(byte k,byte s,uint f,IntPtr e); }
"@
$wd='C:\Users\wenwen\Desktop\MXD\maple_bot_v2'; $log=Join-Path $wd 'debug.log'; $out=Join-Path $wd '_busy_out.txt'
if(Test-Path $out){Remove-Item $out -Force}
function W($s){ $s | Out-File -FilePath $out -Encoding UTF8 -Append }
function Send($vk){ [K]::keybd_event($vk,0,0,[IntPtr]::Zero); Start-Sleep -Milliseconds 90; [K]::keybd_event($vk,0,2,[IntPtr]::Zero) }
function Med($a){ if(-not $a -or $a.Count -eq 0){return '-'} $b=$a|Sort-Object; $b[[int]($b.Count/2)] }
function TS($line){ if($line -match '^\[(\d\d):(\d\d):(\d\d)\]'){ return ([int]$Matches[1])*3600+([int]$Matches[2])*60+[int]$Matches[3] } return -1 }

$t0=Get-Date
W ("START "+$t0.ToString('HH:mm:ss'))
Send 0x79   # F10
W ("F10 sent "+(Get-Date).ToString('HH:mm:ss'))
Start-Sleep -Seconds 26
Send 0x7B   # F12
W ("F12 sent "+(Get-Date).ToString('HH:mm:ss'))
Start-Sleep -Seconds 2

$ws=($t0.AddSeconds(4)); $we=($t0.AddSeconds(26))
$wsSec=$ws.Hour*3600+$ws.Minute*60+$ws.Second; $weSec=$we.Hour*3600+$we.Minute*60+$we.Second
$win = Get-Content $log -Encoding UTF8 | Where-Object { $t=TS $_; $t -ge 0 -and $t -ge $wsSec -and $t -le $weSec }
W ("WINDOW_LINES="+$win.Count+"  稳态窗 "+$ws.ToString('HH:mm:ss')+"~"+$we.ToString('HH:mm:ss'))

$fps=@(); $draw=@(); foreach($l in $win){ if($l -match '\[FPS统计\] 帧率=([\d.]+).*绘制=(\d+)'){ $fps+=[double]$Matches[1]; $draw+=[int]$Matches[2] } }
if($fps.Count){ W ("帧率fps n="+$fps.Count+" min="+($fps|Measure-Object -Minimum).Minimum+" med="+(Med $fps)+" max="+($fps|Measure-Object -Maximum).Maximum+" | 绘制ms/秒 med="+(Med $draw)+" max="+($draw|Measure-Object -Maximum).Maximum) }

$busyRounds=@(); $busyGrab=@(); $busyTgt='-'; $idleN=0; $busyN=0
foreach($l in $win){
 if($l -match '\[截图耗时\] (\d+)轮 周期忙 .*目标(\d+)ms 本轮(\d+)ms'){ $busyN++; $busyRounds+=[int]$Matches[1]; $busyTgt=$Matches[2]; $busyGrab+=[int]$Matches[3] }
 elseif($l -match '周期闲'){ $idleN++ }
}
W ("截图: 忙帧秒数="+$busyN+" 闲帧秒数="+$idleN+" 目标="+$busyTgt+"ms 忙档轮数/秒 med="+(Med $busyRounds)+" 单轮grab ms min="+($busyGrab|Measure-Object -Minimum).Minimum+" med="+(Med $busyGrab)+" max="+($busyGrab|Measure-Object -Maximum).Maximum)

$pm=@(); foreach($l in $win){ if($l -match '\[人物耗时\] \d+帧 人物匹配(\d+)'){ $pm+=[int]$Matches[1] } }
if($pm.Count){ W ("人物匹配 ms/秒 med="+(Med $pm)+" max="+($pm|Measure-Object -Maximum).Maximum+" (=每帧约 "+[math]::Round((Med $pm)/22,1)+"ms)") }
$nf=@();$yolo=@();$hb=@(); foreach($l in $win){ if($l -match '\[识别B耗时\] (\d+)新帧 怪模板(\d+) YOLO(\d+) 血条(\d+)'){ $nf+=[int]$Matches[1];$yolo+=[int]$Matches[3];$hb+=[int]$Matches[4] } }
if($nf.Count){ W ("B线程 新帧/秒 med="+(Med $nf)+" YOLO ms med="+(Med $yolo)+" max="+($yolo|Measure-Object -Maximum).Maximum+" 血条ms med="+(Med $hb)) }

$diagN=0;$tgtN=0;$monMax=0;$monSum=0;$reactMax=0;$lastDiag=@()
foreach($l in $win){ if($l -match '\[战斗诊断\].*怪数=(\d+) has_target=(\w+) react余=(\d+)ms.*锁定=(\S+)'){
  $diagN++; $mon=[int]$Matches[1]; $monMax=[math]::Max($monMax,$mon); $monSum+=$mon; if($Matches[4] -ne 'None'){$tgtN++}; $reactMax=[math]::Max($reactMax,[int]$Matches[3]); $lastDiag+=$l } }
if($diagN){ W ("战斗诊断 n="+$diagN+" 锁定非空率="+[math]::Round(100*$tgtN/$diagN)+"% 怪数max="+$monMax+" 均值="+[math]::Round($monSum/$diagN,1)+" react余max="+$reactMax+"ms") }

foreach($kw in @('锁怪','换目标','空打','发呆','无位移','平台边界','爬梯','cross','巡游','瞬移','Traceback','异常','攻击','血条命中','伤害数字')){ $c=($win|Select-String -SimpleMatch $kw).Count; if($c -gt 0){ W ("EVENT {0,-8} x{1}" -f $kw,$c) } }
W '----- 异常/发呆/边界/Traceback 样本 -----'
$win | Select-String '发呆|无位移|平台边界|Traceback|异常|空打|爬梯失败|cross' | Select-Object -Last 18 | ForEach-Object { W $_.Line }
W '----- 战斗诊断最后5条 -----'
$lastDiag | Select-Object -Last 5 | ForEach-Object { W $_ }
W ("END "+(Get-Date).ToString('HH:mm:ss'))
