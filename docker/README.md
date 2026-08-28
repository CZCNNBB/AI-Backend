# Docker 部署文件

本目录集中保存 AI-backend 的全部 Docker 构建、编排和离线交付文件，根目录不放置 Dockerfile 或 Compose 文件。

```text
docker/
├── backend/
│   ├── Dockerfile
│   └── Dockerfile.dockerignore
├── frontend/
│   ├── Dockerfile
│   ├── Dockerfile.dockerignore
│   └── default.conf
├── offline/
│   ├── start.sh
│   ├── stop.sh
│   ├── logs.sh
│   └── README.md
├── scripts/
│   └── build_offline_package.ps1
├── compose.yaml
└── compose.build.yaml
```

## 本机联网构建

```powershell
docker compose `
  --file docker\compose.yaml `
  --file docker\compose.build.yaml `
  build ai-backend ai-web
```

`compose.build.yaml` 只供有源码的构建机使用。离线服务器只使用 `compose.yaml` 和已经导入的镜像。

离线部署不依赖 `.env`。服务器可以在解压后直接编辑 `docker/compose.yaml`，
再执行 `./start.sh` 应用现场配置。

## 生成 Linux AMD64 离线包

```powershell
.\docker\scripts\build_offline_package.ps1 -Version 1.0.0
```

发布物生成在 `release/`，脚本不会覆盖以前的包。完整部署步骤参见：

```text
docs/Docker离线部署说明.md
```
