# 第一阶段使用锁文件构建确定版本的 Vue 静态资源。
FROM node:22-alpine AS builder

WORKDIR /opt/ai-web

COPY web/package.json web/package-lock.json ./
RUN npm ci

COPY web/ .

# 生产页面统一通过同源 /api 访问 Nginx，再由 Nginx 转发到后端容器。
ARG VITE_API_BASE=/api
ENV VITE_API_BASE=${VITE_API_BASE}

RUN npm run build

# 第二阶段只保留静态资源和 Nginx，避免把 Node 构建环境带入运行镜像。
FROM nginx:1.29-alpine

COPY docker/frontend/default.conf /etc/nginx/conf.d/default.conf
COPY --from=builder /opt/ai-web/dist /usr/share/nginx/html

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD wget --quiet --tries=1 --spider http://127.0.0.1/health || exit 1
