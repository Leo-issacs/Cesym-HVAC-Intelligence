# setup_tarea_semanal.ps1
#
# Registra una tarea en el Programador de Tareas de Windows que ejecuta
# sync_drive.py todos los lunes a las 7:00 AM.
#
# EJECUTAR UNA SOLA VEZ como Administrador:
#   Right-click en PowerShell → "Ejecutar como administrador"
#   cd "C:\Users\leona\Personal\Works\Programacion\Projects\hvac-ai-system"
#   .\setup_tarea_semanal.ps1
#
# Para cambiar el día/hora, edita $DIA y $HORA abajo.

$PROYECTO = "C:\Users\leona\Personal\Works\Programacion\Projects\hvac-ai-system"
$PYTHON   = "$PROYECTO\cesym_data_analytics\Scripts\python.exe"
$SCRIPT   = "$PROYECTO\scripts\sync_drive.py"
$DIA      = "Monday"   # Lunes. Opciones: Monday, Tuesday, Wednesday, Thursday, Friday
$HORA     = "07:00"    # 7:00 AM

$accion = New-ScheduledTaskAction `
    -Execute $PYTHON `
    -Argument "-X utf8 `"$SCRIPT`"" `
    -WorkingDirectory $PROYECTO

$trigger = New-ScheduledTaskTrigger `
    -Weekly `
    -DaysOfWeek $DIA `
    -At $HORA

$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -RunOnlyIfNetworkAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 30)

Register-ScheduledTask `
    -TaskName    "Cesym-SyncDrive" `
    -Action      $accion `
    -Trigger     $trigger `
    -Settings    $settings `
    -Description "Descarga Excel de Google Drive y actualiza hvac.db — Cesym Analytics" `
    -RunLevel    Highest `
    -Force | Out-Null

Write-Host ""
Write-Host "Tarea registrada exitosamente:" -ForegroundColor Green
Write-Host "  Nombre:     Cesym-SyncDrive"
Write-Host "  Frecuencia: Cada $DIA a las $HORA"
Write-Host "  Python:     $PYTHON"
Write-Host "  Script:     $SCRIPT"
Write-Host ""
Write-Host "Comandos utiles:" -ForegroundColor Cyan
Write-Host "  Ejecutar ahora:  Start-ScheduledTask -TaskName 'Cesym-SyncDrive'"
Write-Host "  Ver estado:      Get-ScheduledTask -TaskName 'Cesym-SyncDrive'"
Write-Host "  Eliminar tarea:  Unregister-ScheduledTask -TaskName 'Cesym-SyncDrive' -Confirm:`$false"
Write-Host "  Ver log:         notepad '$PROYECTO\logs\sync_drive.log'"
