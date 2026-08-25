<!--
  接口文档页面
  - 左侧：按 group 分组的接口导航
  - 右侧：接口详情（请求/响应字段 + JSON 示例 + 备注）
  - 数据来源于 ./apiDocs.data.ts，后端接口变动时同步更新该文件即可
-->
<template>
  <div class="api-docs">
    <h2 class="page-title">📘 Agent 平台接口文档</h2>

    <!-- 顶部使用说明 -->
    <a-alert
      class="mb-4"
      type="info"
      show-icon
      message="使用说明"
      description="本页罗列 Agent 平台当前提供的全部 HTTP 接口。基础地址：{{ apiBaseUrl }}，所有接口统一返回 { code, msg, data } 三段结构。后续接口有新增或调整时,同步更新 src/views/docs/apiDocs.data.ts 即可。"
    />

    <a-layout>
      <!-- 左侧导航 -->
      <a-layout-sider
        class="docs-sider"
        width="220"
        theme="light"
        :style="{ background: '#fafafa', paddingTop: '8px' }"
      >
        <a-menu
          mode="inline"
          :selected-keys="[activeAnchor]"
          @click="onMenuClick"
        >
          <a-menu-item v-for="group in groups" :key="group.group">
            <component :is="group.icon" class="menu-icon" />
            <span>{{ group.group }}</span>
          </a-menu-item>
        </a-menu>
      </a-layout-sider>

      <!-- 右侧详情 -->
      <a-layout-content class="docs-content">
        <a-empty v-if="groups.length === 0" description="暂无接口数据" />
        <div
          v-for="group in groups"
          :id="anchorId(group.group)"
          :key="group.group"
          class="doc-group"
        >
          <h3 class="group-title">
            <component :is="group.icon" class="group-icon" />
            {{ group.group }}
          </h3>
          <a-card
            v-for="api in group.items"
            :key="`${api.method}-${api.path}`"
            class="api-card mb-4"
            :id="anchorId(`${group.group}-${api.method}-${api.path}`)"
          >
            <!-- 标题：method + path + name -->
            <template #title>
              <a-space>
                <a-tag :color="methodColorMap[api.method]">{{ api.method }}</a-tag>
                <code class="path-code">{{ api.path }}</code>
                <span class="api-name">{{ api.name }}</span>
              </a-space>
            </template>

            <p class="api-summary">{{ api.summary }}</p>

            <!-- 请求字段 -->
            <template v-if="api.requestFields.length">
              <h4 class="section-title">📥 请求参数</h4>
              <a-table
                :columns="fieldColumns"
                :data-source="api.requestFields"
                :pagination="false"
                size="small"
                row-key="name"
              />
            </template>
            <a-empty v-else-if="api.method !== 'GET'" description="无请求体" :image="emptyImg" />

            <!-- 响应字段 -->
            <template v-if="api.responseFields.length">
              <h4 class="section-title mt-3">📤 响应字段（data 内）</h4>
              <a-table
                :columns="fieldColumns"
                :data-source="api.responseFields"
                :pagination="false"
                size="small"
                row-key="name"
              />
            </template>

            <!-- 请求示例 -->
            <template v-if="api.requestExample">
              <h4 class="section-title mt-3">🧪 请求示例</h4>
              <pre class="code-block">{{ api.requestExample }}</pre>
            </template>

            <!-- 响应示例 -->
            <template v-if="api.responseExample">
              <h4 class="section-title mt-3">✅ 响应示例</h4>
              <pre class="code-block">{{ api.responseExample }}</pre>
            </template>

            <!-- 备注 -->
            <template v-if="api.notes && api.notes.length">
              <h4 class="section-title mt-3">💡 备注</h4>
              <ul class="notes-list">
                <li v-for="(note, idx) in api.notes" :key="idx">{{ note }}</li>
              </ul>
            </template>

            <!-- 完整 URL 提示 -->
            <a-tag class="mt-3" color="cyan">
              完整 URL：{{ apiBaseUrl }}/agent{{ api.path }}
            </a-tag>
          </a-card>
        </div>
      </a-layout-content>
    </a-layout>
  </div>
</template>

<script setup lang="ts">
/**
 * 接口文档页面
 * - 数据驱动：所有接口信息在 apiDocs.data.ts 中维护
 * - 支持分组左侧导航 + 锚点滚动
 */
import { computed, h, onMounted, ref } from 'vue'
import { Empty, Tag } from 'ant-design-vue'
import {
  apiBaseUrl,
  apiDocs,
  groupApiDocs,
  methodColorMap,
  type FieldDoc,
} from './apiDocs.data'

defineOptions({ name: 'ApiDocsView' })

// Empty 的简化样式，避免大图占空间
const emptyImg = Empty.PRESENTED_IMAGE_SIMPLE

/** 分组后的接口数据 */
const groups = computed(() => groupApiDocs(apiDocs))

/** 当前激活的分组锚点（用于左侧菜单高亮） */
const activeAnchor = ref<string>('')

/** 字段表格列定义
 *  说明：customRender 在 Vue 模板中接收的是 { text, value, record, index, column }
 *  我们直接用 h() 函数渲染 a-tag，避免在 <script setup> 中使用 JSX。 */
const fieldColumns = [
  { title: '字段', dataIndex: 'name', key: 'name', width: 200 },
  { title: '类型', dataIndex: 'type', key: 'type', width: 180 },
  {
    title: '必填',
    dataIndex: 'required',
    key: 'required',
    width: 80,
    customRender: ({ text }: { text: boolean | undefined }) =>
      text ? h(Tag, { color: 'red' }, () => '是') : h('span', {}, '-'),
  },
  { title: '说明', dataIndex: 'description', key: 'description' },
] as unknown as { title: string; dataIndex: keyof FieldDoc; key: string; width?: number }[]

/** 生成稳定的 DOM id */
function anchorId(name: string): string {
  return `doc-${name.replace(/[^a-zA-Z0-9_\-]/g, '-')}`
}

/** 点击左侧菜单 -> 滚动到对应分组 */
function onMenuClick({ key }: { key: string }) {
  const id = anchorId(key)
  const el = document.getElementById(id)
  if (el) {
    el.scrollIntoView({ behavior: 'smooth', block: 'start' })
    activeAnchor.value = key
  }
}

/** 滚动监听：更新左侧激活项 */
function onScroll() {
  const scrollTop = window.scrollY || document.documentElement.scrollTop
  let current = activeAnchor.value
  for (const group of groups.value) {
    const el = document.getElementById(anchorId(group.group))
    if (el && el.offsetTop - 100 <= scrollTop) {
      current = group.group
    }
  }
  if (current) activeAnchor.value = current
}

onMounted(() => {
  if (groups.value.length) activeAnchor.value = groups.value[0].group
  window.addEventListener('scroll', onScroll, { passive: true })
})
</script>

<style scoped>
.api-docs {
  padding: 0;
}
.page-title {
  margin: 0 0 16px;
  font-size: 20px;
  font-weight: 600;
}
.mb-4 {
  margin-bottom: 16px;
}
.mt-3 {
  margin-top: 16px;
}
.docs-sider {
  border-right: 1px solid #f0f0f0;
  min-height: 600px;
}
.docs-content {
  padding: 8px 24px;
  background: #fff;
}
.doc-group {
  margin-bottom: 32px;
}
.group-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 18px;
  font-weight: 600;
  margin: 16px 0 12px;
  padding-bottom: 8px;
  border-bottom: 2px solid #1677ff;
}
.group-icon {
  color: #1677ff;
  font-size: 18px;
}
.api-card {
  border-radius: 8px;
}
.api-name {
  font-weight: 500;
}
.api-summary {
  color: #595959;
  margin: 0 0 12px;
}
.path-code {
  background: #f5f5f5;
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 13px;
  color: #d4380d;
}
.section-title {
  font-size: 14px;
  font-weight: 600;
  margin: 12px 0 8px;
  color: #262626;
}
.code-block {
  background: #1e1e1e;
  color: #d4d4d4;
  padding: 12px 16px;
  border-radius: 6px;
  font-size: 12px;
  line-height: 1.6;
  overflow-x: auto;
  white-space: pre;
  margin: 0;
  font-family: 'Fira Code', 'Cascadia Code', Menlo, Consolas, monospace;
}
.notes-list {
  margin: 0;
  padding-left: 20px;
  color: #595959;
  font-size: 13px;
}
.notes-list li {
  margin: 4px 0;
}
.menu-icon {
  margin-right: 8px;
  font-size: 14px;
}
</style>
