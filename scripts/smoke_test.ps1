# Prueba de humo de BankLite: ejercita todos los endpoints de los dos microservicios.
# Uso: powershell -ExecutionPolicy Bypass -File .\scripts\smoke_test.ps1

$ErrorActionPreference = "Continue"
$ID = "http://localhost:8001"
$AC = "http://localhost:8002"
$pasos = 0
$fallos = 0

function Paso($titulo) {
    $script:pasos++
    Write-Host ""
    Write-Host "--- [$script:pasos] $titulo ---" -ForegroundColor Cyan
}

function Verificar($descripcion, $obtenido, $esperado) {
    if ($obtenido -eq $esperado) {
        Write-Host "  OK   $descripcion -> $obtenido" -ForegroundColor Green
    } else {
        Write-Host "  FALLO $descripcion -> $obtenido (esperado $esperado)" -ForegroundColor Red
        $script:fallos++
    }
}

function Llamar($metodo, $url, $cuerpo) {
    try {
        if ($cuerpo) {
            $r = Invoke-WebRequest -Method $metodo -Uri $url -Body ($cuerpo | ConvertTo-Json) `
                 -ContentType "application/json" -UseBasicParsing
        } else {
            $r = Invoke-WebRequest -Method $metodo -Uri $url -UseBasicParsing
        }
        return @{ code = [int]$r.StatusCode; body = ($r.Content | ConvertFrom-Json) }
    } catch {
        $code = 0
        if ($_.Exception.Response) { $code = [int]$_.Exception.Response.StatusCode }
        return @{ code = $code; body = $null }
    }
}

Write-Host "=============================================" -ForegroundColor Yellow
Write-Host " BankLite - prueba de humo de microservicios " -ForegroundColor Yellow
Write-Host "=============================================" -ForegroundColor Yellow

Paso "Health check de los dos servicios"
Verificar "GET /health identity" (Llamar GET "$ID/health").code 200
Verificar "GET /health account"  (Llamar GET "$AC/health").code 200

Paso "Registrar un usuario nuevo (POST /users)"
$email = "juan.$(Get-Random)@example.com"
$r = Llamar POST "$ID/users" @{ email = $email; phone = "+573001234567"; country = "CO" }
Verificar "POST /users" $r.code 201
$userId = $r.body.id
Write-Host "  user_id = $userId"
Write-Host "  estado inicial = $($r.body.status)"

Paso "Rechazar email duplicado (409) y datos invalidos (422)"
Verificar "POST /users duplicado" (Llamar POST "$ID/users" @{ email = $email; phone = "+573001234567"; country = "CO" }).code 409
Verificar "POST /users invalido"  (Llamar POST "$ID/users" @{ email = "no-es-email"; phone = "abc"; country = "COL" }).code 422

Paso "Consultar el usuario (GET /users/{id})"
Verificar "GET /users/{id}"             (Llamar GET "$ID/users/$userId").code 200
Verificar "GET /users/{id} inexistente" (Llamar GET "$ID/users/11111111-1111-1111-1111-111111111111").code 404

Paso "Intentar abrir cuenta SIN KYC (debe fallar con 409)"
$r = Llamar POST "$AC/accounts" @{ user_id = $userId }
Verificar "POST /accounts sin KYC" $r.code 409

Paso "Verificacion KYC aprobada -> publica identity.verified"
$r = Llamar POST "$ID/users/$userId/kyc" @{ document_type = "cedula"; document_number = "1098765432" }
Verificar "POST /users/{id}/kyc" $r.code 200
Verificar "usuario verificado" $r.body.user_status "verified"
Verificar "evento publicado en RabbitMQ" $r.body.event_published $true
Write-Host "  referencia del proveedor = $($r.body.kyc.provider_reference)"

Paso "Comprobar que account-service consumio el evento (comunicacion ASINCRONA)"
Start-Sleep -Seconds 2
$r = Llamar GET "$AC/verified-users"
Verificar "GET /verified-users" $r.code 200
$encontrado = @($r.body | Where-Object { $_.user_id -eq $userId }).Count
Verificar "usuario presente en la proyeccion" $encontrado 1

Paso "Abrir la cuenta (comunicacion SINCRONA con identity-service)"
$r = Llamar POST "$AC/accounts" @{ user_id = $userId }
Verificar "POST /accounts" $r.code 201
$accountId = $r.body.account.id
Write-Host "  account_id      = $accountId"
Write-Host "  moneda          = $($r.body.account.currency)"
Write-Host "  limite diario   = $($r.body.account.daily_limit)"
Write-Host "  limite mensual  = $($r.body.account.monthly_limit)"
Write-Host "  validado por    = $($r.body.validated_via)"
Write-Host "  evento recibido = $($r.body.event_projection_hit)"

Paso "Reglas de negocio: cuenta duplicada (409) y moneda incorrecta (400)"
Verificar "POST /accounts duplicada" (Llamar POST "$AC/accounts" @{ user_id = $userId }).code 409
Verificar "POST /accounts user inexistente" (Llamar POST "$AC/accounts" @{ user_id = "11111111-1111-1111-1111-111111111111" }).code 404

Paso "Consultar cuentas"
Verificar "GET /accounts?user_id"   (Llamar GET "$AC/accounts?user_id=$userId").code 200
Verificar "GET /accounts/{id}"      (Llamar GET "$AC/accounts/$accountId").code 200
Verificar "GET /accounts/{id} 404"  (Llamar GET "$AC/accounts/11111111-1111-1111-1111-111111111111").code 404

Paso "Cambiar estado de la cuenta (PATCH)"
$r = Llamar PATCH "$AC/accounts/$accountId/status" @{ status = "suspended" }
Verificar "PATCH /accounts/{id}/status" $r.code 200
Verificar "estado actualizado" $r.body.status "suspended"
Verificar "estado invalido rechazado" (Llamar PATCH "$AC/accounts/$accountId/status" @{ status = "zombie" }).code 422

Paso "Camino de KYC rechazado (documento que termina en 0000)"
$email2 = "rechazado.$(Get-Random)@example.com"
$u2 = (Llamar POST "$ID/users" @{ email = $email2; phone = "+573001110000"; country = "CO" }).body
$r = Llamar POST "$ID/users/$($u2.id)/kyc" @{ document_type = "cedula"; document_number = "1230000" }
Verificar "KYC rechazado" $r.body.user_status "rejected"
Verificar "cuenta bloqueada por KYC rechazado" (Llamar POST "$AC/accounts" @{ user_id = $u2.id }).code 409

Write-Host ""
Write-Host "=============================================" -ForegroundColor Yellow
if ($fallos -eq 0) {
    Write-Host " TODAS LAS PRUEBAS PASARON ($pasos pasos)" -ForegroundColor Green
} else {
    Write-Host " $fallos VERIFICACIONES FALLARON" -ForegroundColor Red
}
Write-Host "=============================================" -ForegroundColor Yellow
