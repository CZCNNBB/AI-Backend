/**
 * 10. A2A 可视化页
 * - 展示所有 Agent 之间的 A2A 调用关系
 * - 简单 SVG 拓扑图（自实现，避免额外依赖）
 */
<template>
  <div>
    <h2 class="page-title">🔗 A2A 拓扑图</h2>

    <a-card>
      <template #title>
        <a-space>
          <span>Agent 调用关系</span>
          <a-tag color="blue">主 Agent: {{ mainAgents.length }}</a-tag>
          <a-tag color="cyan">子 Agent: {{ subAgents.length }}</a-tag>
          <a-tag color="purple">调用边: {{ edges.length }}</a-tag>
        </a-space>
      </template>
      <template #extra>
        <a-button type="primary" @click="loadAll">🔄 刷新</a-button>
      </template>

      <a-empty v-if="!agents.length" description="暂无 Agent 数据" />

      <div v-else ref="canvasRef" class="canvas">
        <svg :width="canvasSize.w" :height="canvasSize.h" class="svg-canvas">
          <!-- 边 -->
          <g>
            <line
              v-for="e in edgeLines"
              :key="e.key"
              :x1="e.x1"
              :y1="e.y1"
              :x2="e.x2"
              :y2="e.y2"
              stroke="#52c41a"
              stroke-width="1.5"
              marker-end="url(#arrow)"
            />
          </g>
          <defs>
            <marker id="arrow" markerWidth="10" markerHeight="10" refX="10" refY="3" orient="auto">
              <path d="M0,0 L0,6 L9,3 z" fill="#52c41a" />
            </marker>
          </defs>

          <!-- 节点 -->
          <g v-for="n in positions" :key="n.agent_id">
            <circle :cx="n.x" :cy="n.y" :r="22" :fill="n.is_sub_agent ? '#1890ff' : '#722ed1'" />
            <text :x="n.x" :y="n.y + 40" text-anchor="middle" font-size="12" fill="#333">
              {{ n.agent_name }}
            </text>
            <text :x="n.x" :y="n.y + 56" text-anchor="middle" font-size="10" fill="#999">
              {{ n.agent_id }}
            </text>
          </g>
        </svg>
      </div>

      <!-- 图例 -->
      <a-divider />
      <a-space>
        <a-tag color="purple">🟣 主 Agent (可调用他人)</a-tag>
        <a-tag color="blue">🔵 子 Agent (可被 A2A)</a-tag>
        <a-tag color="green">— 调用边 (主→子)</a-tag>
      </a-space>
    </a-card>

    <!-- Agent 列表 -->
    <a-card title="📋 Agent 列表" class="mt-4">
      <a-table :columns="columns" :data-source="agents" :pagination="false" row-key="agent_id" size="middle">
        <template #bodyCell="{ column, record }">
          <template v-if="column.dataIndex === 'is_sub_agent'">
            <a-tag :color="record.config?.is_sub_agent ? 'blue' : 'default'">
              {{ record.config?.is_sub_agent ? '可被 A2A' : '普通' }}
            </a-tag>
          </template>
          <template v-else-if="column.dataIndex === 'sub_agent_list'">
            <a-tag v-for="s in record.config?.sub_agent_list || []" :key="s" color="cyan" class="m-1">
              {{ s }}
            </a-tag>
            <span v-if="!(record.config?.sub_agent_list || []).length">-</span>
          </template>
          <template v-else-if="column.dataIndex === 'action'">
            <a-button type="link" size="small" @click="router.push(`/agents/${record.agent_id}/edit`)">
              编辑
            </a-button>
          </template>
        </template>
      </a-table>
    </a-card>
  </div>
</template>

<script setup lang="ts">
/**
 * A2A 可视化页逻辑
 * - 加载所有 active Agent
 * - 简单环形布局绘制节点和边
 */
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { searchAgentTemplates, type AgentTemplate } from '@/api/agentTemplate'

defineOptions({ name: 'A2AVisualizerView' })

const router = useRouter()
const agents = ref<AgentTemplate[]>([])

const canvasSize = ref({ w: 1000, h: 600 })

const columns = [
  { title: 'Agent ID', dataIndex: 'agent_id', width: 180 },
  { title: '名称', dataIndex: 'agent_name', width: 180 },
  { title: 'A2A', dataIndex: 'is_sub_agent', width: 100 },
  { title: '可调用子 Agent', dataIndex: 'sub_agent_list' },
  { title: '操作', dataIndex: 'action', width: 100 },
]

/** 加载所有 Agent */
async function loadAll() {
  const res = await searchAgentTemplates({ status: 'active', page: 1, page_size: 200 })
  agents.value = res.items
  // 自适应画布
  canvasSize.value = { w: Math.max(1000, agents.value.length * 120), h: Math.max(500, agents.value.length * 80) }
}

/** 主 Agent */
const mainAgents = computed(() => agents.value.filter((a) => !a.config?.is_sub_agent))
/** 子 Agent */
const subAgents = computed(() => agents.value.filter((a) => a.config?.is_sub_agent))
/** 边（A2A 拓扑需要从 Run Chain 中聚合；这里先展示 sub_agent 节点） */
const edges = computed(() => {
  const out: { from: string; to: string }[] = []
  // 后端 AgentTemplateConfig 没有 sub_agent_list 字段，
  // 真正的 A2A 调用关系需要从 AgentRunChain 中聚合，TODO
  return out
})

/** 节点位置（环形布局） */
const positions = computed(() => {
  const n = agents.value.length
  if (!n) return []
  const cx = canvasSize.value.w / 2
  const cy = canvasSize.value.h / 2
  const r = Math.min(cx, cy) - 80
  return agents.value.map((a, i) => {
    const angle = (i / n) * 2 * Math.PI - Math.PI / 2
    return {
      agent_id: a.agent_id,
      agent_name: a.agent_name,
      is_sub_agent: !!a.config?.is_sub_agent,
      x: cx + r * Math.cos(angle),
      y: cy + r * Math.sin(angle),
    }
  })
})

/** 计算边端点（指向节点边缘而非中心） */
const edgeLines = computed(() => {
  const posMap = new Map(positions.value.map((p) => [p.agent_id, p]))
  return edges.value
    .map((e, i) => {
      const f = posMap.get(e.from)
      const t = posMap.get(e.to)
      if (!f || !t) return null
      // 缩短端点
      const dx = t.x - f.x
      const dy = t.y - f.y
      const dist = Math.sqrt(dx * dx + dy * dy)
      if (!dist) return null
      const offset = 24
      return {
        key: i,
        x1: f.x + (dx / dist) * offset,
        y1: f.y + (dy / dist) * offset,
        x2: t.x - (dx / dist) * offset,
        y2: t.y - (dy / dist) * offset,
      }
    })
    .filter((x): x is NonNullable<typeof x> => !!x)
})

onMounted(loadAll)
</script>

<style scoped>
.page-title {
  margin: 0 0 16px;
  font-size: 20px;
  font-weight: 600;
}
.canvas {
  width: 100%;
  overflow: auto;
  background: #fafafa;
  border-radius: 6px;
}
.svg-canvas {
  display: block;
  margin: 0 auto;
}
.m-1 {
  margin: 2px;
}
.mt-4 {
  margin-top: 16px;
}
</style>
