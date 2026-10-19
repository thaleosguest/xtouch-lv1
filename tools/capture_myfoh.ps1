# Capture du trafic MyFOH / MyMon <-> LV1 (pktmon, intégré à Windows), pour trouver les commandes /Set.
# À lancer dans un PowerShell EN ADMINISTRATEUR :
#     & "$env:USERPROFILE\Documents\xTouchController_LV1_workspace\tools\capture_myfoh.ps1"
# Le port de la LV1 (il change à chaque démarrage de la LV1) est lu dans le journal de XTouch-LV1 ; sinon : -Port 61306.
# Faire les gestes dans MyFOH pendant la capture, puis appuyer sur Entrée : la capture est arrêtée et convertie.
param([int]$Port = 0)

$ws = Join-Path $env:USERPROFILE "Documents\xTouchController_LV1_workspace"
if ($Port -eq 0) {
    $console = Join-Path $env:LOCALAPPDATA "Programs\XTouch-LV1\xtouch_console.txt"
    $line = Select-String -Path $console -Pattern "LV1 trouv.+ : .* port (\d+)" -ErrorAction SilentlyContinue | Select-Object -Last 1
    if ($line) { $Port = [int]$line.Matches[0].Groups[1].Value }
}
if ($Port -eq 0) { Write-Host "Port de la LV1 introuvable : relancer avec -Port <n°>"; exit 1 }

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$etl = Join-Path $ws "myfoh_$stamp.etl"
$pcap = Join-Path $ws "myfoh_$stamp.pcapng"

pktmon filter remove | Out-Null
pktmon filter add LV1 -t TCP -p $Port | Out-Null
pktmon start --capture --comp nics --pkt-size 0 -f $etl | Out-Null
Write-Host ""
Write-Host "Capture en cours (LV1 port $Port), depuis $(Get-Date -Format 'HH:mm:ss')."
Write-Host "Faites les gestes dans MyFOH (5 s entre chaque), puis appuyez sur Entrée ici."
Read-Host | Out-Null
pktmon stop | Out-Null
pktmon etl2pcap $etl -o $pcap | Out-Null
pktmon filter remove | Out-Null
Write-Host "Capture enregistrée : $pcap"
