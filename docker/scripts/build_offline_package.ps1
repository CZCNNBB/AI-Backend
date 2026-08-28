param(
    [Parameter(Mandatory = $false)]
    [ValidatePattern('^[0-9A-Za-z._-]+$')]
    [string]$Version = "1.0.0"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

# 根据脚本位置计算仓库根目录，确保可以从任意工作目录执行。
$repositoryRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..\..")).Path
$releaseRoot = Join-Path $repositoryRoot "release"
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$packageName = "ai-backend-$Version-linux-amd64-$timestamp"
$packageDirectory = Join-Path $releaseRoot $packageName
$packageSqlDirectory = Join-Path $packageDirectory "sql"
$packageDockerDirectory = Join-Path $packageDirectory "docker"

$backendImage = "ai-backend:$Version"
$webImage = "ai-web:$Version"
$requiredImages = @(
    $backendImage,
    $webImage,
    "postgres-rag:pg18",
    "milvusdb/milvus:v3.0.0",
    "quay.io/coreos/etcd:v3.5.25",
    "minio/minio:RELEASE.2024-05-28T17-19-04Z"
)

# 检查 Docker Engine，避免构建到一半才发现 Docker Desktop 未启动。
docker info *> $null
if ($LASTEXITCODE -ne 0) {
    throw "Docker Engine 不可用，请先启动 Docker Desktop。"
}

# 当前离线包固定面向 Linux AMD64；服务器架构不同则不能直接使用。
$dockerPlatform = docker info --format '{{.OSType}}/{{.Architecture}}'
if ($dockerPlatform.Trim() -ne "linux/x86_64") {
    throw "当前 Docker 平台为 $dockerPlatform，本脚本只生成 linux/amd64 离线包。"
}

# PostgreSQL 使用本机已经验证过的自定义 pg18 镜像，缺失时不自动换成其他镜像。
# 直接读取精确 tag 的镜像 ID，避免 Docker Desktop 刚重启时原生命令退出码被误判。
$postgresImageId = docker image ls --quiet --filter "reference=postgres-rag:pg18"
if ([string]::IsNullOrWhiteSpace(($postgresImageId | Select-Object -First 1))) {
    throw "缺少 postgres-rag:pg18，请先恢复 db-clean 使用的 PostgreSQL 镜像。"
}

# 确保 Milvus 官方三个基础镜像存在；缺失时由构建机联网拉取固定版本。
$milvusImages = @(
    "milvusdb/milvus:v3.0.0",
    "quay.io/coreos/etcd:v3.5.25",
    "minio/minio:RELEASE.2024-05-28T17-19-04Z"
)
foreach ($imageName in $milvusImages) {
    $existingImageId = docker image ls --quiet --filter "reference=$imageName"
    if ([string]::IsNullOrWhiteSpace(($existingImageId | Select-Object -First 1))) {
        docker pull --platform linux/amd64 $imageName
        if ($LASTEXITCODE -ne 0) {
            throw "拉取镜像失败: $imageName"
        }
    }
}

# 通过环境变量覆盖示例文件中的镜像版本，使 Compose 构建结果带上本次发布版本。
$env:AI_BACKEND_IMAGE = $backendImage
$env:AI_WEB_IMAGE = $webImage

Push-Location $repositoryRoot
try {
    docker compose `
        --file "docker\compose.yaml" `
        --file "docker\compose.build.yaml" `
        build
    if ($LASTEXITCODE -ne 0) {
        throw "AI-backend 或 AI-web 镜像构建失败。"
    }
}
finally {
    Pop-Location
}

# 使用时间戳目录生成新包，不覆盖或删除之前的离线发布物。
New-Item -ItemType Directory -Path $packageSqlDirectory -Force | Out-Null
New-Item -ItemType Directory -Path $packageDockerDirectory -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $repositoryRoot "docker\compose.yaml") -Destination (Join-Path $packageDockerDirectory "compose.yaml")
Copy-Item -LiteralPath (Join-Path $repositoryRoot "sql\00000000_init_empty_database.sql") -Destination (Join-Path $packageSqlDirectory "00000000_init_empty_database.sql")
Copy-Item -LiteralPath (Join-Path $repositoryRoot "docker\offline\start.sh") -Destination (Join-Path $packageDirectory "start.sh")
Copy-Item -LiteralPath (Join-Path $repositoryRoot "docker\offline\stop.sh") -Destination (Join-Path $packageDirectory "stop.sh")
Copy-Item -LiteralPath (Join-Path $repositoryRoot "docker\offline\logs.sh") -Destination (Join-Path $packageDirectory "logs.sh")
Copy-Item -LiteralPath (Join-Path $repositoryRoot "docker\offline\README.md") -Destination (Join-Path $packageDirectory "README.md")

# PowerShell/Windows 可能使用 CRLF，交付给 Linux 的 Shell 脚本统一转换为 UTF-8 LF。
$utf8WithoutBom = [System.Text.UTF8Encoding]::new($false)

# 运行时 Compose 不读取 .env；这里仅把本次打包版本写入发布目录中的镜像名称。
# 源码目录的 compose.yaml 保持默认版本，服务器仍可在解压后直接编辑发布副本。
$packageComposePath = Join-Path $packageDockerDirectory "compose.yaml"
$packageComposeContent = [System.IO.File]::ReadAllText($packageComposePath)
$packageComposeContent = $packageComposeContent.Replace("image: ai-backend:1.0.0", "image: $backendImage")
$packageComposeContent = $packageComposeContent.Replace("image: ai-web:1.0.0", "image: $webImage")
[System.IO.File]::WriteAllText($packageComposePath, $packageComposeContent, $utf8WithoutBom)

foreach ($shellScriptName in @("start.sh", "stop.sh", "logs.sh")) {
    $shellScriptPath = Join-Path $packageDirectory $shellScriptName
    $shellScriptContent = [System.IO.File]::ReadAllText($shellScriptPath).Replace("`r`n", "`n")
    [System.IO.File]::WriteAllText($shellScriptPath, $shellScriptContent, $utf8WithoutBom)
}

# docker image save 会保留镜像名称、tag 和全部运行层，服务器可以直接 docker load。
$imagesTarPath = Join-Path $packageDirectory "images.tar"
docker image save --output $imagesTarPath @requiredImages
if ($LASTEXITCODE -ne 0) {
    throw "Docker 镜像导出失败。"
}

# 保存镜像包校验值，上传服务器后可检查文件是否传输完整。
$imageHash = Get-FileHash -Algorithm SHA256 -LiteralPath $imagesTarPath
$checksumLine = "$($imageHash.Hash.ToLowerInvariant())  images.tar`n"
[System.IO.File]::WriteAllText(
    (Join-Path $packageDirectory "SHA256SUMS"),
    $checksumLine,
    $utf8WithoutBom
)

# 最外层再压缩为单个 tar.gz，方便上传服务器；解压后仍保留 Docker 原生 images.tar。
$archivePath = "$packageDirectory.tar.gz"
tar -czf $archivePath -C $releaseRoot $packageName
if ($LASTEXITCODE -ne 0) {
    throw "离线部署包压缩失败。"
}

Write-Output "离线部署包生成完成：$archivePath"
Write-Output "服务器架构要求：linux/amd64"
Write-Output "镜像数量：$($requiredImages.Count)"
