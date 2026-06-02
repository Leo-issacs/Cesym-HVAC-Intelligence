# setup_tarea_semanal.ps1
# Registra la tarea semanal. EJECUTAR COMO ADMINISTRADOR.

$PROYECTO = "C:\Users\leona\Personal\Works\Programacion\Projects\hvac-ai-system"
$SCRIPT   = "$PROYECTO\scripts\sync_maestro.ps1"

$accion = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument ("-NonInteractive -ExecutionPolicy Bypass -File `"" + $SCRIPT + "`"") `
    -WorkingDirectory $PROYECTO

$trigger  = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday -At "07:00"
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -RunOnlyIfNetworkAvailable

Register-ScheduledTask `
    -TaskName    "Cesym-SyncDrive" `
    -Action      $accion `
    -Trigger     $trigger `
    -Settings    $settings `
    -Description "Descarga Excel de Drive y actualiza hvac.db" `
    -RunLevel    Highest `
    -Force | Out-Null

Write-Host "Tarea Cesym-SyncDrive registrada - lunes 07:00 AM" -ForegroundColor Green
Write-Host "Para ejecutar ahora: Start-ScheduledTask -TaskName Cesym-SyncDrive"
