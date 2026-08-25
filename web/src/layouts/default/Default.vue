/**
 * 默认布局：左侧菜单 + 内容区
 */
<template>
  <a-layout class="min-h-screen">
    <!-- 左侧侧边栏 -->
    <a-layout-sider v-model:collapsed="collapsed" collapsible :width="220" :collapsed-width="64" theme="dark">
      <div class="logo">
        <span v-if="!collapsed">🤖 Agent 管理平台</span>
        <span v-else>🤖</span>
      </div>
      <a-menu theme="dark" mode="inline" :selected-keys="[activeMenuKey]" @click="onMenuClick">
        <a-menu-item v-for="item in menuItems" :key="item.path">
          <component :is="item.icon" class="menu-icon" />
          <span>{{ item.title }}</span>
        </a-menu-item>
      </a-menu>
    </a-layout-sider>

    <a-layout>
      <!-- 内容区 -->
      <a-layout-content class="layout-content">
        <slot />
      </a-layout-content>
    </a-layout>
  </a-layout>
</template>

<script setup lang="ts">
/**
 * 默认布局组件
 * - 左侧菜单：包含核心页面导航
 * - 内容区：slot 渲染 router-view
 */
import { computed, ref, type Component } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  DashboardOutlined,
  RobotOutlined,
  MessageOutlined,
  LineChartOutlined,
  ToolOutlined,
  SettingOutlined,
  ApartmentOutlined,
  BookOutlined,
  PlayCircleOutlined,
  // @ts-ignore - DatabaseOutlined 在 es/icons/index.d.ts 缺失类型
  DatabaseOutlined,
} from '@ant-design/icons-vue'

defineOptions({ name: 'DefaultLayout' })

const route = useRoute()
const router = useRouter()
const collapsed = ref(false)

interface MenuItem {
  path: string
  title: string
  // 直接存组件对象，传给 <component :is="item.icon" /> 渲染
  icon: Component
  group: string
}

// 菜单项配置（按分组）
// 注意：'新建 Agent' 不放在一级菜单里，而是 Agent 模板列表页面的"新建"按钮
const menuItems = ref<MenuItem[]>([
  { path: '/', title: 'Dashboard', icon: DashboardOutlined, group: '概览' },
  { path: '/agents', title: 'Agent 模板', icon: RobotOutlined, group: 'Agent 管理' },
  { path: '/agent-invoke', title: 'Agent 调用', icon: PlayCircleOutlined, group: 'Agent 管理' },
  { path: '/conversations', title: '会话历史', icon: MessageOutlined, group: '会话' },
  { path: '/runs', title: '运行监控', icon: LineChartOutlined, group: '监控' },
  { path: '/knowledge', title: '知识库', icon: DatabaseOutlined, group: '运维' },
  { path: '/tools', title: '工具管理', icon: ToolOutlined, group: '运维' },
  { path: '/settings/model', title: '模型配置', icon: SettingOutlined, group: '运维' },
  { path: '/a2a', title: 'A2A 拓扑', icon: ApartmentOutlined, group: '运维' },
  { path: '/docs', title: '接口文档', icon: BookOutlined, group: '运维' },
])

// 当前路由高亮 key
const activeMenuKey = computed(() => {
  // /agents/:id/edit 应当高亮 /agents
  if (route.path.startsWith('/agents')) return '/agents'
  if (route.path.startsWith('/knowledge')) return '/knowledge'
  const matched = menuItems.value.find((m) => m.path === route.path)
  return matched?.path || route.path
})

/** 点击菜单跳转 */
function onMenuClick({ key }: { key: string }) {
  router.push(key)
}
</script>

<style scoped>
.logo {
  height: 64px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  font-weight: 600;
  font-size: 15px;
  background: rgba(255, 255, 255, 0.05);
}
/* 菜单图标与文字垂直居中对齐
   注意：Ant Design 的 a-menu-item 内部用 flex 布局且 slot 内容无法被 scoped 样式穿透
   必须用 :deep() 强制穿透 */
:deep(.ant-menu-item .menu-icon) {
  display: inline-flex;
  align-items: center;
  vertical-align: middle;
  margin-right: 10px;
  line-height: 1;
  font-size: 16px;
  transform: translateY(-1px); /* 微调让 svg 视觉居中 */
}
:deep(.ant-menu-item .menu-icon svg) {
  display: block;
}
.layout-content {
  margin: 16px;
  padding: 24px;
  background: #fff;
  border-radius: 8px;
  min-height: calc(100vh - 32px);
}
</style>
