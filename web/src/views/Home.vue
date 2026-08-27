/**
 * 1. Dashboard 首页
 * - 系统健康状态
 * - 今日/本周运行统计
 * - 最近运行记录
 * - 快捷入口
 */
<template>
  <div>
    <h2 class="page-title">📊 系统总览</h2>

    <a-alert
      v-if="!debugContextReady"
      type="info"
      show-icon
      class="mb-4"
      message="尚未配置调试业务身份"
      description="系统健康和 Agent 模板管理仍可正常使用；运行统计需要先在页面顶部配置平台 API Key 和外部用户 ID。"
    />

    <!-- 顶部健康状态卡片 -->
    <a-row :gutter="16" class="mb-4">
      <a-col :span="6">
        <a-card>
          <a-statistic title="Agent 服务" :value="health.agent.status">
            <template #suffix>
              <a-tag :color="health.agent.status === 'ok' ? 'green' : 'red'">
                {{ health.agent.status === 'ok' ? '健康' : '异常' }}
              </a-tag>
            </template>
          </a-statistic>
        </a-card>
      </a-col>
      <a-col :span="6">
        <a-card>
          <a-statistic title="PostgreSQL" :value="health.db.status">
            <template #suffix>
              <a-tag :color="health.db.status === 'ok' ? 'green' : 'red'">
                {{ health.db.status === 'ok' ? '健康' : '异常' }}
              </a-tag>
            </template>
          </a-statistic>
        </a-card>
      </a-col>
      <a-col :span="6">
        <a-card>
          <a-statistic title="模型网关" :value="health.model.status">
            <template #suffix>
              <a-tag :color="health.model.status === 'ok' ? 'green' : 'red'">
                {{ health.model.status === 'ok' ? '健康' : '异常' }}
              </a-tag>
            </template>
          </a-statistic>
        </a-card>
      </a-col>
      <a-col :span="6">
        <a-card>
          <a-statistic title="Agent 模板总数" :value="stats.agentCount" />
        </a-card>
      </a-col>
    </a-row>

    <!-- 运行统计卡片 -->
    <a-row :gutter="16" class="mb-4">
      <a-col :span="6">
        <a-card>
          <a-statistic title="今日运行总量" :value="stats.todayTotal" />
        </a-card>
      </a-col>
      <a-col :span="6">
        <a-card>
          <a-statistic
            title="今日成功率"
            :value="stats.todaySuccessRate"
            :precision="2"
            suffix="%"
            :value-style="{ color: stats.todaySuccessRate >= 90 ? '#3f8600' : '#cf1322' }"
          />
        </a-card>
      </a-col>
      <a-col :span="6">
        <a-card>
          <a-statistic title="本周运行总量" :value="stats.weekTotal" />
        </a-card>
      </a-col>
      <a-col :span="6">
        <a-card>
          <a-statistic title="平均耗时(ms)" :value="stats.avgElapsed" />
        </a-card>
      </a-col>
    </a-row>

    <!-- 快捷入口 -->
    <a-card title="🚀 快捷入口" class="mb-4">
      <a-space wrap>
        <a-button type="primary" @click="router.push('/agents/create')">
          ➕ 新建 Agent
        </a-button>
        <a-button @click="router.push('/agents')">🤖 Agent 模板管理</a-button>
        <a-button @click="router.push('/runs')">📈 运行监控</a-button>
        <a-button @click="router.push('/conversations')">💬 会话历史</a-button>
      </a-space>
    </a-card>

    <!-- 最近运行记录 -->
    <a-card title="⏱️ 最近 5 条运行记录">
      <a-table
        :columns="runColumns"
        :data-source="recentRuns"
        :loading="loading"
        :pagination="false"
        row-key="run_id"
        size="middle"
      >
        <template #bodyCell="{ column, record }">
          <template v-if="column.dataIndex === 'status'">
            <a-tag :color="statusColor(record.status)">{{ record.status }}</a-tag>
          </template>
          <template v-else-if="column.dataIndex === 'elapsed_ms'">
            {{ record.elapsed_ms ?? '-' }} ms
          </template>
          <template v-else-if="column.dataIndex === 'started_at'">
            {{ formatTime(record.started_at) }}
          </template>
          <template v-else-if="column.dataIndex === 'action'">
            <a-button type="link" size="small" @click="router.push('/runs')">查看</a-button>
          </template>
        </template>
      </a-table>
    </a-card>
  </div>
</template>

<script setup lang="ts">
/**
 * Dashboard 页面逻辑
 * - 加载健康状态
 * - 加载最近 5 条运行记录
 * - 简单统计：成功 / 失败 / 平均耗时
 */
import { onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { getHealth } from '@/api/capabilities'
import { searchAgentRuns, type AgentRun } from '@/api/agentRun'
import { searchAgentTemplates } from '@/api/agentTemplate'
import dayjs from 'dayjs'
import {
  BUSINESS_DEBUG_CONTEXT_CHANGED,
  hasCompleteBusinessDebugContext,
} from '@/utils/businessDebugContext'

defineOptions({ name: 'DashboardView' })

const router = useRouter()
const loading = ref(false)
const debugContextReady = ref(hasCompleteBusinessDebugContext())

// 健康状态
const health = reactive({ agent: { status: 'unknown' }, db: { status: 'unknown' }, model: { status: 'unknown' } })
// 统计
const stats = reactive({
  agentCount: 0,
  todayTotal: 0,
  weekTotal: 0,
  todaySuccessRate: 0,
  avgElapsed: 0,
})
// 最近运行
const recentRuns = ref<AgentRun[]>([])

const runColumns = [
  { title: 'Run ID', dataIndex: 'run_id', width: 220, ellipsis: true },
  { title: 'Agent', dataIndex: 'agent_id', width: 140 },
  { title: '类型', dataIndex: 'run_type', width: 80 },
  { title: '状态', dataIndex: 'status', width: 90 },
  { title: '耗时', dataIndex: 'elapsed_ms', width: 100 },
  { title: '开始时间', dataIndex: 'started_at', width: 180 },
  { title: '操作', dataIndex: 'action', width: 80 },
]

/** 状态颜色映射 */
function statusColor(s: string) {
  return s === 'success' ? 'green' : s === 'failed' ? 'red' : 'blue'
}

/** 格式化时间 */
function formatTime(t?: string) {
  return t ? dayjs(t).format('YYYY-MM-DD HH:mm:ss') : '-'
}

/** 加载所有数据 */
async function loadAll() {
  loading.value = true
  try {
    // 1. 健康状态
    try {
      const h = await getHealth()
      // 后端 /agent/health 返回 {service, status}，三个卡片都用它填充
      health.agent = h
      health.db = h
      health.model = h
    } catch {
      health.agent = { status: 'unknown' }
      health.db = { status: 'unknown' }
      health.model = { status: 'unknown' }
    }

    // 2. Agent 模板数量
    try {
      const tpl = await searchAgentTemplates({ page: 1, page_size: 1 })
      stats.agentCount = tpl.total
    } catch {
      stats.agentCount = 0
    }

    // 3. 最近 5 条运行记录
    debugContextReady.value = hasCompleteBusinessDebugContext()
    if (!debugContextReady.value) {
      recentRuns.value = []
      stats.weekTotal = 0
      stats.todayTotal = 0
      stats.todaySuccessRate = 0
      stats.avgElapsed = 0
      return
    }
    try {
      const runRes = await searchAgentRuns({ page: 1, page_size: 5 })
      recentRuns.value = runRes.items || []
    } catch {
      recentRuns.value = []
    }

    // 4. 本周统计（前端在内存中按 started_at 过滤，后端不支持 started_at_from）
    // 后端 page_size 上限 100，分多页拉取合并
    try {
      const allItems: unknown[] = []
      let page = 1
      const maxPageSize = 100
      while (true) {
        const res: any = await searchAgentRuns({ page, page_size: maxPageSize } as any)
        const items = res.items || []
        allItems.push(...items)
        if (items.length < maxPageSize) break
        page += 1
        if (page > 10) break // 防御：最多 10 页（1000 条）
      }
      const weekFrom = dayjs().startOf('week')
      const weekItems = (allItems as any[]).filter((r) => r.started_at && dayjs(r.started_at).isAfter(weekFrom))
      stats.weekTotal = allItems.length
      const todayFrom = dayjs().startOf('day')
      const todayItems = weekItems.filter((r) => r.started_at && dayjs(r.started_at).isAfter(todayFrom))
      stats.todayTotal = todayItems.length
      const success = todayItems.filter((r) => r.status === 'success').length
      stats.todaySuccessRate = todayItems.length ? (success / todayItems.length) * 100 : 0
      const totalElapsed = todayItems.reduce((sum, r) => sum + (r.elapsed_ms || 0), 0)
      stats.avgElapsed = todayItems.length ? Math.round(totalElapsed / todayItems.length) : 0
    } catch {
      stats.weekTotal = 0
      stats.todayTotal = 0
      stats.todaySuccessRate = 0
      stats.avgElapsed = 0
    }
  } finally {
    loading.value = false
  }
}

/** 调试身份变化后重新决定是否加载业务运行数据。 */
function onDebugContextChanged(): void {
  debugContextReady.value = hasCompleteBusinessDebugContext()
  void loadAll()
}

onMounted(() => {
  window.addEventListener(BUSINESS_DEBUG_CONTEXT_CHANGED, onDebugContextChanged)
  void loadAll()
})
onBeforeUnmount(() => window.removeEventListener(BUSINESS_DEBUG_CONTEXT_CHANGED, onDebugContextChanged))
</script>

<style scoped>
.page-title {
  margin: 0 0 16px;
  font-size: 20px;
  font-weight: 600;
}
.mb-4 {
  margin-bottom: 16px;
}
</style>
