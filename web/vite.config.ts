import tailwindcss from '@tailwindcss/vite'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'path'
import { type Plugin } from 'vite'
import { defineConfig, loadEnv } from 'vite'

const transformHtmlPlugin = (data: Record<string, string>): Plugin => ({
  name: 'transform-html',
  transformIndexHtml: {
    order: 'pre',
    handler(html: string) {
      return html.replace(/<%=\s*(\w+)\s*%>/gi, (match, p1) => data[p1] || '')
    },
  },
})

export default defineConfig(({ mode }) => {
  // 加载 .env 与 .env.[mode] 中的变量
  const env = loadEnv(mode, process.cwd(), '')
  // 后端服务地址，缺省指向本地 3000
  const backendURL = env.VITE_BACKEND_URL || 'http://localhost:3000'
  return {
    plugins: [
      vue(),
      tailwindcss(),
      transformHtmlPlugin({
        title: 'Agent 管理平台',
        description: '基于 AI-backend 的 Agent 管理平台',
      }),
    ],
    resolve: {
      alias: {
        '@': resolve(__dirname, 'src'),
        '@tests': resolve(__dirname, 'tests'),
      },
    },
    // 将前端 /api 代理到后端服务，方便本地联调
    // 后端真实路由前缀是 /agent（无 /api），因此代理时需要 rewrite 去掉 /api 前缀
    // 前端最终请求：/api/agent/health → http://localhost:8090/agent/health
    server: {
      port: 5173,
      proxy: {
        '/api': {
          target: backendURL,
          changeOrigin: true,
          rewrite: (path) => path.replace(/^\/api/, ''),
        },
      },
    },
    css: {
      preprocessorOptions: {
        scss: {
          additionalData: `@use "@/scss/variables" as *;`,
        },
      },
    },
    test: {
      globals: true,
      clearMocks: true,
      globalSetup: './tests/vitest.global-setup.ts',
      setupFiles: ['./tests/vitest.globals.ts', './tests/vitest.router-mock-setup.ts'],
      environment: 'jsdom',
      reporters: ['default'],
      coverage: {
        reporter: ['text', 'json'],
      },
    },
  }
})
