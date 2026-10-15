# Dựng lại luồng NiFi qua REST API: upload template_nifi.xml, tạo flow trên canvas,
# điền khóa MinIO (lấy từ .env) cho các processor S3, đặt tiền tố ListS3 = raw/, rồi Start.
#
# Dùng (trong thư mục OCR_pipeline, sau khi `docker compose up -d` và NiFi đã chạy):
#     powershell -ExecutionPolicy Bypass -File tools\setup_nifi.ps1
#
# Bỏ qua nếu canvas đã có processor (tránh tạo flow trùng).
param(
    [string] $NiFi = "https://localhost:8443/nifi-api",
    [string] $EnvFile = ".env",
    [string] $Template = "template_nifi.xml"
)
$ErrorActionPreference = "Stop"

# ---- Đọc .env ----
$cfg = @{}
foreach ($line in Get-Content $EnvFile) {
    if ($line -match '^\s*([A-Z_]+)\s*=\s*(.*)\s*$') { $cfg[$Matches[1]] = $Matches[2] }
}
foreach ($k in "NIFI_USERNAME", "NIFI_PASSWORD", "MINIO_ACCESS_KEY", "MINIO_SECRET_KEY") {
    if (-not $cfg[$k]) { throw "Missing $k in $EnvFile" }
}

# curl.exe -k: NiFi dùng chứng chỉ tự ký
function Invoke-NiFi([string] $Method, [string] $Path, $Body = $null, [string] $Token) {
    $tmp = $null
    $curlArgs = @("-sk", "-X", $Method, "$NiFi$Path", "-H", "Authorization: Bearer $Token")
    if ($null -ne $Body) {
        $tmp = New-TemporaryFile
        [IO.File]::WriteAllText($tmp, ($Body | ConvertTo-Json -Depth 20), (New-Object Text.UTF8Encoding($false)))
        $curlArgs += @("-H", "Content-Type: application/json", "--data-binary", "@$tmp")
    }
    $out = & curl.exe @curlArgs
    if ($tmp) { Remove-Item $tmp }
    if ($out) { return ($out | Out-String | ConvertFrom-Json) }
}

# ---- Chờ NiFi sẵn sàng + lấy token ----
$token = $null
for ($i = 0; $i -lt 60 -and -not $token; $i++) {
    $token = & curl.exe -sk -X POST "$NiFi/access/token" --data-urlencode "username=$($cfg.NIFI_USERNAME)" --data-urlencode "password=$($cfg.NIFI_PASSWORD)"
    if (-not $token -or $token -match '<|error|Unable') { $token = $null; Start-Sleep 5 }
}
if (-not $token) { throw "Cannot log in to NiFi" }
"NiFi login OK"

$root = (Invoke-NiFi GET "/flow/process-groups/root" -Token $token).processGroupFlow
$rootId = $root.id
if ($root.flow.processors.Count -gt 0) {
    "Canvas already has $($root.flow.processors.Count) processors - skip import"
    return
}

# ---- Upload + tạo flow từ template ----
$up = & curl.exe -sk -X POST "$NiFi/process-groups/$rootId/templates/upload" -H "Authorization: Bearer $token" -F "template=@$Template"
$templateId = ([regex]::Match(($up | Out-String), '<id>([^<]+)</id>')).Groups[1].Value
if (-not $templateId) {
    # Template trùng tên đã có sẵn: dùng lại
    $templateId = ((Invoke-NiFi GET "/flow/templates" -Token $token).templates | Select-Object -First 1).id
}
if (-not $templateId) { throw "Template upload failed: $up" }
Invoke-NiFi POST "/process-groups/$rootId/template-instance" @{ templateId = $templateId; originX = 0.0; originY = 0.0 } -Token $token | Out-Null
"Template instantiated"

# ---- Cấu hình processor: khóa S3, prefix, nhánh không nối ----
# Template không lưu auto-terminate: nhánh nào không nối sang processor khác (failure, Retry, Original...)
# phải được tự hủy, nếu không processor ở trạng thái INVALID và không Start được.
$connected = @{}
foreach ($c in (Invoke-NiFi GET "/process-groups/$rootId/connections" -Token $token).connections) {
    foreach ($rel in $c.component.selectedRelationships) { $connected["$($c.component.source.id)|$rel"] = $true }
}
$procs = (Invoke-NiFi GET "/process-groups/$rootId/processors" -Token $token).processors
foreach ($p in $procs) {
    $type = $p.component.type
    $props = @{}
    if ($type -match 'aws\.s3\.(ListS3|FetchS3Object|PutS3Object)$') {
        $props["Access Key"] = $cfg.MINIO_ACCESS_KEY
        $props["Secret Key"] = $cfg.MINIO_SECRET_KEY
    }
    if ($type -match 'ListS3$') { $props["prefix"] = "raw/" }
    $terminate = @($p.component.relationships | Where-Object { -not $connected["$($p.id)|$($_.name)"] } | ForEach-Object { $_.name })
    $config = @{ autoTerminatedRelationships = $terminate }
    if ($props.Count -gt 0) { $config.properties = $props }
    $body = @{
        revision  = @{ version = $p.revision.version }
        component = @{ id = $p.id; config = $config }
    }
    Invoke-NiFi PUT "/processors/$($p.id)" $body -Token $token | Out-Null
    "Configured $($p.component.name) (auto-terminate: $($terminate -join ', '))"
}

# ---- Start toàn bộ ----
Invoke-NiFi PUT "/flow/process-groups/$rootId" @{ id = $rootId; state = "RUNNING" } -Token $token | Out-Null
Start-Sleep 5
$procs = (Invoke-NiFi GET "/process-groups/$rootId/processors" -Token $token).processors
foreach ($p in $procs) { "{0,-20} {1,-8} {2}" -f $p.component.name, $p.status.runStatus, $p.component.validationStatus }
