$ErrorActionPreference='Continue'
$wd='C:\Users\wenwen\Desktop\MXD\maple_bot_v2'; $log=Join-Path $wd 'debug.log'; $out=Join-Path $wd '_busy2_out.txt'; $flag=Join-Path $wd 'data\_run_cmd.flag'
if(Test-Path $out){Remove-Item $out -Force}
function W($s){ $s | Out-File -FilePath $out -Encoding UTF8 -Append }
function Med($a){ if(-not $a -or $a.Count -eq 0){return '-'} $b=$a|Sort-Object; $b[[int]($b.Count/2)] }
function TS($l){ if($l -match '^\[(\d\d):(\d\d):(\d\d)\]'){ return ([int]$Matches[1])*3600+([int]$Matches[2])*60+[int]$Matches[3] } return -1 }

W ("RUNNING_AT "+(Get-Date).ToString('HH:mm:ss')+'  采集22秒...')
Start-Sleep -Seconds 22
$we=Get-Date
[IO.File]::WriteAllText($flag,'F12',[Text.Encoding]::ASCII)
W ("F12 sent @ "+$we.ToString('HH:mm:ss'))
Start-Sleep -Seconds 2
$ws=$we.AddSeconds(-20); $wsSec=$ws.Hour*3600+$ws.Minute*60+$ws.Second; $weSec=$we.Hour*3600+$we.Minute*60+$we.Second
$win = Get-Content $log -Encoding UTF8 | Where-Object { $t=TS $_; $t -ge 0 -and $t -ge $wsSec -and $t -le $weSec }
W ("WINDOW "+$ws.ToString('HH:mm:ss')+"~"+$we.ToString('HH:mm:ss')+" lines="+$win.Count)

$fps=@();$draw=@(); foreach($l in $win){ if($l -match '\[FPS统计\] 帧率=([\d.]+).*?绘制=(\d+)'){ $fps+=[double]$Matches[1]; $draw+=[int]$Matches[2] } }
if($fps.Count){ W ("帧率fps min="+($fps|Measure-Object -Minimum).Minimum+" med="+(Med $fps)+" max="+($fps|Measure-Object -Maximum).Maximum+" | 绘制ms med="+(Med $draw)+" max="+($draw|Measure-Object -Maximum).Maximum) }

$br=@();$bg=@();$tgt='';$idle=0;$busy=0
foreach($l in $win){ if($l -match '周期忙.*?目标(\d+)ms 本轮(\d+)ms.*?(\d+)轮'){ } 
 if($l -match '\[截图耗时\] (\d+)轮 周期忙 .*?目标(\d+)ms 本轮(\d+)ms'){ $busy++; $br+=[int]$Matches[1]; $tgt=$Matches[2]; $bg+=[int]$Matches[3] }
 elseif($l -match '周期闲'){ $idle++ } }
if($br.Count){ W ("截图忙: 忙秒="+$busy+" 闲秒="+$idle+" 目标="+$tgt+"ms 轮/秒 med="+(Med $br)+" min轮="+($br|Measure-Object -Minimum).Minimum+" grab本轮 min="+($bg|Measure-Object -Minimum).Minimum+" med="+(Med $bg)+" max="+($bg|Measure-Object -Maximum).Maximum) }

$pm=@(); foreach($l in $win){ if($l -match '\[人物耗时\] \d+帧 人物匹配(\d+)'){ $pm+=[int]$Matches[1] } }
if($pm.Count){ W ("人物匹配 ms/秒 med="+(Med $pm)+" max="+($pm|Measure-Object -Maximum).Maximum) }
$nf=@();$yolo=@();$hb=@(); foreach($l in $win){ if($l -match '\[识别B耗时\] (\d+)新帧 怪模板(\d+) YOLO(\d+) 血条(\d+)'){ $nf+=[int]$Matches[1];$yolo+=[int]$Matches[3];$hb+=[int]$Matches[4] } }
if($nf.Count){ W ("B 新帧/秒 med="+(Med $nf)+" YOLOms med="+(Med $yolo)+" max="+($yolo|Measure-Object -Maximum).Maximum+" 血条ms med="+(Med $hb)) }

$dn=0;$tn=0;$mmax=0;$msum=0;$pursue=0;$atk=0;$last=@()
foreach($l in $win){
 if($l -match '\[战斗诊断\].*?怪数=(\d+) has_target=(\w+).*?锁定=(\S+)'){ $dn++; $m=[int]$Matches[1]; $mmax=[math]::Max($mmax,$m); $msum+=$m; if($Matches[3] -ne 'None'){$tn++}; $last+=$l }
 if($l -match '状态=pursue'){ $pursue++ }
}
if($dn){ W ("战斗诊断 n="+$dn+" 锁定非空率="+[math]::Round(100*$tn/$dn)+"% 怪数max="+$mmax+" 均值="+[math]::Round($msum/$dn,1)+" pursue行="+$pursue) }
foreach($kw in @('主攻','群攻','空怪诊断','空打','发呆','无位移','平台边界','爬梯','cross','瞬移','Traceback','异常','血条','伤害数字','出手')){ $c=($win|Select-String -SimpleMatch $kw).Count; if($c -gt 0){ W ("EVENT {0,-7} x{1}" -f $kw,$c) } }
W '--- 异常/发呆/空怪/边界 样本(末12) ---'
$win | Select-String '发呆|无位移|平台边界|Traceback|异常|空怪诊断|爬梯|cross' | Select-Object -Last 12 | ForEach-Object { W $_.Line }
W '--- 战斗诊断 末5 ---'
$last | Select-Object -Last 5 | ForEach-Object { W $_ }
W ("END "+(Get-Date).ToString('HH:mm:ss'))
