<!--
  MarkdownView
  - 把 Markdown 文本安全地渲染成 HTML。
  - 使用 marked 解析；遇到空内容显示空字符串，避免"undefined"。
  - 流式友好：内容按 prop 更新即可，marked 会增量解析。
-->
<template>
  <div class="markdown-view" v-html="rendered"></div>
</template>

<script setup lang="ts">
/**
 * 轻量 Markdown 渲染组件。
 * 仅依赖 marked；不做代码高亮，保持体积小、加载快。
 */
import { computed } from 'vue'
import { marked } from 'marked'

const props = withDefaults(
  defineProps<{
    /** 原始 Markdown 文本。 */
    content?: string
    /** 是否启用 GFM（表格、删除线、任务列表等）。默认开启。 */
    gfm?: boolean
    /** 是否允许内联 HTML。默认关闭，避免脚本注入。 */
    html?: boolean
  }>(),
  {
    content: '',
    gfm: true,
    html: false,
  },
)

/** 把 marked 解析结果缓存为响应式计算属性，避免每次重渲染都重新解析。 */
const rendered = computed(() => {
  const text = String(props.content || '')
  if (!text.trim()) return ''
  try {
    // marked.parse 默认是同步的（async=false 时），可以安全用作 computed。
    return marked.parse(text, {
      gfm: props.gfm,
      breaks: true, // 流式输出常带单换行，按 <br> 渲染更自然
      async: false,
    }) as string
  } catch {
    // 解析失败时回退为转义后的纯文本，避免破坏页面。
    return escapeHtml(text)
  }
})

/** 把特殊字符转义为 HTML 实体，作为异常路径的兜底。 */
function escapeHtml(text: string): string {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}
</script>

<style scoped>
/*
 * 覆盖父元素可能继承的 white-space: pre-wrap / pre-line：
 * 这些属性会让 markdown 解析出的 block 元素之间被插入隐藏的换行，
 * 表现为"段落之间出现大段空隙"。这里强制 normal 即可消除。
 */
.markdown-view {
  font-size: 14px;
  line-height: 1.6;
  color: inherit;
  word-break: break-word;
  white-space: normal;
}
/*
 * 用通配 deep 把所有后代都设回 normal，覆盖 v-html 内容里任何
 * 继承自外层容器的空白控制属性。
 */
.markdown-view :deep(*) {
  white-space: normal;
}

.markdown-view :deep(p) {
  margin: 0;
}
.markdown-view :deep(h1),
.markdown-view :deep(h2),
.markdown-view :deep(h3),
.markdown-view :deep(h4) {
  margin: 0;
  font-weight: 600;
  line-height: 1.4;
}
/* 给兄弟 block 元素之间补一个统一的紧凑间距，避免贴太紧 */
.markdown-view :deep(p) + :deep(p),
.markdown-view :deep(p) + :deep(ul),
.markdown-view :deep(p) + :deep(ol),
.markdown-view :deep(p) + :deep(pre),
.markdown-view :deep(p) + :deep(blockquote),
.markdown-view :deep(ul) + :deep(p),
.markdown-view :deep(ul) + :deep(ul),
.markdown-view :deep(ol) + :deep(p),
.markdown-view :deep(ol) + :deep(ol),
.markdown-view :deep(pre) + :deep(p),
.markdown-view :deep(blockquote) + :deep(p),
.markdown-view :deep(h1) + :deep(*),
.markdown-view :deep(h2) + :deep(*),
.markdown-view :deep(h3) + :deep(*),
.markdown-view :deep(h4) + :deep(*) {
  margin-top: 6px;
}
.markdown-view :deep(h1) { font-size: 1.4em; }
.markdown-view :deep(h2) { font-size: 1.25em; }
.markdown-view :deep(h3) { font-size: 1.1em; }
.markdown-view :deep(h4) { font-size: 1em; }
.markdown-view :deep(ul),
.markdown-view :deep(ol) {
  margin: 0;
  padding-left: 22px;
}
.markdown-view :deep(li) {
  margin: 2px 0;
}
.markdown-view :deep(li > p) {
  margin: 0;
}
.markdown-view :deep(code) {
  font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', monospace;
  font-size: 0.9em;
  padding: 1px 6px;
  border-radius: 4px;
  background: rgba(125, 125, 125, 0.12);
}
.markdown-view :deep(pre) {
  margin: 0;
  padding: 10px 12px;
  border-radius: 6px;
  background: rgba(125, 125, 125, 0.1);
  overflow-x: auto;
}
.markdown-view :deep(pre) + :deep(*) {
  margin-top: 6px;
}
.markdown-view :deep(pre code) {
  padding: 0;
  background: transparent;
  font-size: 13px;
  line-height: 1.5;
}
.markdown-view :deep(blockquote) {
  margin: 0;
  padding: 4px 10px;
  border-left: 3px solid #d9d9d9;
  color: #666;
  background: rgba(125, 125, 125, 0.05);
}
.markdown-view :deep(table) {
  border-collapse: collapse;
  margin: 0;
  width: 100%;
  font-size: 13px;
}
.markdown-view :deep(th),
.markdown-view :deep(td) {
  border: 1px solid #e8e8e8;
  padding: 6px 10px;
  text-align: left;
}
.markdown-view :deep(th) {
  background: rgba(125, 125, 125, 0.08);
  font-weight: 600;
}
.markdown-view :deep(a) {
  color: #1677ff;
  text-decoration: none;
}
.markdown-view :deep(a):hover {
  text-decoration: underline;
}
.markdown-view :deep(hr) {
  border: none;
  border-top: 1px solid #e8e8e8;
  margin: 12px 0;
}
.markdown-view :deep(strong) {
  font-weight: 600;
}
.markdown-view :deep(del) {
  color: #999;
}
</style>
