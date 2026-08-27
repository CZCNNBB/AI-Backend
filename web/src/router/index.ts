/**
 * Vue Router 路由配置
 * 10 个核心页面 + 原有示例页
 */
import { createRouter, createWebHashHistory, type RouteRecordRaw } from 'vue-router'
import type { LayoutKey } from '@/layouts/registry'
import Home from '@/views/Home.vue'

const history = createWebHashHistory()

type RouteWithLayoutMeta = Omit<RouteRecordRaw, 'meta'> & {
  meta: {
    layout: LayoutKey
    title?: string
  }
}

const routes = [
  // 1. Dashboard 首页
  {
    path: '/',
    name: 'Dashboard',
    component: Home,
    meta: { layout: 'default', title: 'Dashboard' },
  },
  // 2. Agent 模板管理列表
  {
    path: '/agents',
    name: 'AgentList',
    component: () => import('@/views/agents/AgentList.vue'),
    meta: { layout: 'default', title: 'Agent 模板' },
  },
  // 3. Agent 模板编辑 - 创建
  {
    path: '/agents/create',
    name: 'AgentCreate',
    component: () => import('@/views/agents/AgentEdit.vue'),
    meta: { layout: 'default', title: '新建 Agent' },
  },
  // 3. Agent 模板编辑 - 编辑
  {
    path: '/agents/:agent_id/edit',
    name: 'AgentEdit',
    component: () => import('@/views/agents/AgentEdit.vue'),
    meta: { layout: 'default', title: '编辑 Agent' },
  },
  // 4. Agent Playground 试跑台（重定向到新调用页）
  {
    path: '/agents/:agent_id/playground',
    name: 'AgentPlayground',
    redirect: (to) => ({ path: '/agent-invoke', query: { agent_id: to.params.agent_id } }),
    meta: { layout: 'default', title: 'Playground' },
  },
  // 4.1 Agent 调用页
  {
    path: '/agent-invoke',
    name: 'AgentInvoke',
    component: () => import('@/views/agents/AgentInvoke.vue'),
    meta: { layout: 'default', title: 'Agent 调用' },
  },
  // 5. 会话历史列表
  {
    path: '/conversations',
    name: 'ConversationList',
    component: () => import('@/views/conversations/ConversationList.vue'),
    meta: { layout: 'default', title: '会话历史' },
  },
  // 6. 会话详情
  {
    path: '/conversations/:conversation_id',
    name: 'ConversationDetail',
    component: () => import('@/views/conversations/ConversationDetail.vue'),
    meta: { layout: 'default', title: '会话详情' },
  },
  // 7. Agent 运行监控
  {
    path: '/runs',
    name: 'RunMonitor',
    component: () => import('@/views/runs/RunMonitor.vue'),
    meta: { layout: 'default', title: '运行监控' },
  },
  // 8. 知识库管理（列表）
  {
    path: '/knowledge',
    name: 'KnowledgeList',
    component: () => import('@/views/knowledge/KnowledgeList.vue'),
    meta: { layout: 'default', title: '知识库' },
  },
  // 8.1 知识库新建
  {
    path: '/knowledge/create',
    name: 'KnowledgeCreate',
    component: () => import('@/views/knowledge/KnowledgeForm.vue'),
    meta: { layout: 'default', title: '新建知识库' },
  },
  // 8.2 知识库详情工作台
  {
    path: '/knowledge/:knowledge_id',
    name: 'KnowledgeDetail',
    component: () => import('@/views/knowledge/KnowledgeDetail.vue'),
    meta: { layout: 'default', title: '知识库详情' },
  },
  // 8.3 编辑知识库
  {
    path: '/knowledge/:knowledge_id/edit',
    name: 'KnowledgeEdit',
    component: () => import('@/views/knowledge/KnowledgeForm.vue'),
    meta: { layout: 'default', title: '编辑知识库' },
  },
  // 9. 工具管理
  {
    path: '/platforms',
    name: 'PlatformManager',
    component: () => import('@/views/platforms/PlatformManager.vue'),
    meta: { layout: 'default', title: '业务平台' },
  },
  // 10. 工具管理
  {
    path: '/tools',
    name: 'ToolManager',
    component: () => import('@/views/tools/ToolManager.vue'),
    meta: { layout: 'default', title: '工具管理' },
  },
  // 11. 模型配置
  {
    path: '/settings/model',
    name: 'ModelConfig',
    component: () => import('@/views/settings/ModelConfig.vue'),
    meta: { layout: 'default', title: '模型配置' },
  },
  // 10. A2A 可视化
  {
    path: '/a2a',
    name: 'A2AVisualizer',
    component: () => import('@/views/a2a/A2AVisualizer.vue'),
    meta: { layout: 'default', title: 'A2A 拓扑' },
  },
  // 11. 接口文档
  {
    path: '/docs',
    name: 'ApiDocs',
    component: () => import('@/views/docs/ApiDocs.vue'),
    meta: { layout: 'default', title: '接口文档' },
  },
  // 保留示例页
  {
    path: '/empty',
    name: 'Empty',
    component: () => import('@/views/Empty.vue'),
    meta: { layout: 'empty', title: 'Empty' },
  },
] satisfies RouteWithLayoutMeta[]

const router = createRouter({
  linkActiveClass: 'active',
  history,
  routes,
})

export { router }
