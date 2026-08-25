<template>
  <a-drawer
    :open="open"
    class="retrieval-drawer"
    width="min(1080px, 100vw)"
    title="检索测试"
    :destroy-on-close="false"
    @close="closeDrawer"
  >
    <div class="retrieval-layout">
      <aside class="control-panel">
        <section class="control-section">
          <label class="field-label">检索模式</label>
          <a-segmented v-model:value="form.mode" block :options="modeOptions" />
          <p class="mode-description">{{ modeDescription }}</p>
        </section>

        <section class="control-section">
          <label class="field-label">查询内容</label>
          <a-textarea
            v-model:value="form.query"
            :auto-size="{ minRows: 4, maxRows: 8 }"
            :maxlength="10000"
            show-count
            placeholder="输入需要检索的问题或关键词"
            @keydown.ctrl.enter.prevent="runRetrieval"
          />
          <a-button type="primary" block size="large" :loading="searching" @click="runRetrieval">
            <template #icon><SearchOutlined /></template>
            开始检索
          </a-button>
          <span class="keyboard-tip">Ctrl + Enter 快速执行</span>
        </section>

        <section class="control-section">
          <div class="section-title">召回参数</div>
          <div class="number-grid">
            <label><span>返回数量</span><a-input-number v-model:value="form.top_k" :min="1" :max="100" /></label>
            <label><span>候选数量</span><a-input-number v-model:value="form.fetch_k" :min="1" :max="200" /></label>
          </div>
          <label v-if="form.mode !== 'keyword'" class="slider-field">
            <span>相似度阈值 <strong>{{ form.similarity_threshold.toFixed(2) }}</strong></span>
            <a-slider v-model:value="form.similarity_threshold" :min="-1" :max="1" :step="0.05" />
          </label>
        </section>

        <a-collapse ghost>
          <a-collapse-panel key="advanced" header="高级参数">
            <div v-if="form.mode === 'hybrid'" class="advanced-fields">
              <label class="slider-field">
                <span>向量权重 <strong>{{ form.vector_weight.toFixed(1) }}</strong></span>
                <a-slider v-model:value="form.vector_weight" :min="0" :max="2" :step="0.1" />
              </label>
              <label class="slider-field">
                <span>关键词权重 <strong>{{ form.keyword_weight.toFixed(1) }}</strong></span>
                <a-slider v-model:value="form.keyword_weight" :min="0" :max="2" :step="0.1" />
              </label>
              <label class="inline-field"><span>RRF 平滑参数</span><a-input-number v-model:value="form.rrf_k" :min="1" :max="1000" /></label>
            </div>
            <label class="inline-field"><span>单库保底结果</span><a-input-number v-model:value="form.per_collection_min_keep" :min="0" :max="10" /></label>
            <a-checkbox v-model:checked="form.metadata_headers">使用标题元数据增强召回</a-checkbox>

            <div class="rerank-header">
              <div><strong>Rerank 重排</strong><small>对召回候选进行二次排序</small></div>
              <a-switch v-model:checked="form.rerank_enabled" />
            </div>
            <div v-if="form.rerank_enabled" class="advanced-fields">
              <a-select
                v-model:value="form.rerank_model_code"
                :loading="modelsLoading"
                placeholder="选择已启用的 Rerank 模型"
                show-search
                option-filter-prop="label"
                :options="rerankModelOptions"
              />
              <div class="number-grid">
                <label><span>重排候选</span><a-input-number v-model:value="form.rerank_max_candidates" :min="1" :max="200" /></label>
                <label><span>单条字符</span><a-input-number v-model:value="form.rerank_max_chars" :min="100" :max="10000" :step="100" /></label>
              </div>
            </div>

            <label class="field-label file-filter-label">限定文档范围</label>
            <a-select
              v-model:value="form.file_ids"
              mode="multiple"
              allow-clear
              show-search
              option-filter-prop="label"
              placeholder="不选择表示检索全部已索引文档"
              :options="documentOptions"
              :max-tag-count="2"
            />
          </a-collapse-panel>
        </a-collapse>
      </aside>

      <main class="result-panel">
        <header class="result-header">
          <div>
            <h2>召回结果</h2>
            <p>查看实际命中的切片、来源和相关性分数。</p>
          </div>
          <div v-if="lastRunAt" class="run-meta">
            <span>{{ elapsedMs }} ms</span>
            <span>{{ output?.result_count || 0 }} 条结果</span>
            <a-tag v-if="output?.rerank_used" color="purple">已重排</a-tag>
          </div>
        </header>

        <a-alert
          v-if="errorMessage"
          type="error"
          show-icon
          closable
          :message="errorMessage"
          @close="errorMessage = ''"
        />

        <div v-if="searching" class="loading-state">
          <a-spin size="large" />
          <strong>正在检索知识库</strong>
          <span>正在执行 {{ modeLabel }}，请稍候</span>
        </div>

        <a-empty
          v-else-if="!output"
          description="输入查询内容，运行一次检索测试"
          class="result-empty"
        />

        <a-empty
          v-else-if="!output.results.length"
          description="本次没有召回结果，可以尝试降低阈值或扩大候选数量"
          class="result-empty"
        />

        <ol v-else class="result-list">
          <li v-for="(item, index) in output.results" :key="item.chunk_id" class="result-item">
            <div class="rank">{{ index + 1 }}</div>
            <div class="result-body">
              <div class="result-title">
                <div>
                  <FileTextOutlined />
                  <strong>{{ item.source || item.file_id }}</strong>
                  <a-tag>切片 {{ item.chunk_index }}</a-tag>
                </div>
                <div class="score">
                  <span>score</span>
                  <strong>{{ formatScore(item.score) }}</strong>
                </div>
              </div>
              <p>{{ item.content }}</p>
              <footer>
                <code>{{ item.file_id }}</code>
                <a-button type="text" size="small" @click="copyContent(item.content)">
                  <template #icon><CopyOutlined /></template>复制内容
                </a-button>
              </footer>
            </div>
          </li>
        </ol>
      </main>
    </div>
  </a-drawer>
</template>

<script setup lang="ts">
/** 知识库检索测试抽屉：配置召回参数并展示切片级检索结果。 */
import { computed, reactive, ref, watch } from 'vue'
import { message } from 'ant-design-vue'
import { CopyOutlined, FileTextOutlined, SearchOutlined } from '@ant-design/icons-vue'
import { searchModelConfigs } from '@/api/modelConfigs'
import {
  testKnowledgeRetrieval,
  type KnowledgeDocumentRecord,
  type KnowledgeRetrievalMode,
  type KnowledgeRetrievalOutput,
  type KnowledgeRetrievalPayload,
} from '@/api/knowledge'

const props = defineProps<{
  open: boolean
  collectionName: string
  documents: KnowledgeDocumentRecord[]
}>()
const emit = defineEmits<{ 'update:open': [value: boolean] }>()

const searching = ref(false)
const modelsLoading = ref(false)
const errorMessage = ref('')
const output = ref<KnowledgeRetrievalOutput | null>(null)
const elapsedMs = ref(0)
const lastRunAt = ref('')
const rerankModels = ref<{ model_code: string; model_name: string }[]>([])

const form = reactive({
  mode: 'vector' as KnowledgeRetrievalMode,
  query: '',
  top_k: 10,
  fetch_k: 30,
  similarity_threshold: 0.2,
  rrf_k: 60,
  vector_weight: 1,
  keyword_weight: 1,
  per_collection_min_keep: 0,
  metadata_headers: false,
  rerank_enabled: false,
  rerank_model_code: '',
  rerank_max_candidates: 30,
  rerank_max_chars: 1500,
  file_ids: [] as string[],
})

const modeOptions = [
  { label: '向量检索', value: 'vector' },
  { label: '关键词检索', value: 'keyword' },
  { label: '混合检索', value: 'hybrid' },
]
const modeDescriptions: Record<KnowledgeRetrievalMode, string> = {
  vector: '按语义相似度召回，适合自然语言问题和近义表达。',
  keyword: '按文字命中召回，适合专有名词、编号和精确词语。',
  hybrid: '融合向量与关键词排名，兼顾语义理解和精确命中。',
}
const modeDescription = computed(() => modeDescriptions[form.mode])
const modeLabel = computed(() => modeOptions.find((item) => item.value === form.mode)?.label || form.mode)
const rerankModelOptions = computed(() => rerankModels.value.map((item) => ({
  label: item.model_code === item.model_name ? item.model_code : `${item.model_code} · ${item.model_name}`,
  value: item.model_code,
})))
const documentOptions = computed(() => props.documents
  .filter((item) => item.status === 'indexed')
  .map((item) => ({ label: item.file_name || item.file_id, value: item.file_id })))

/** 在首次打开抽屉时加载可用的 Rerank 模型。 */
watch(() => props.open, (open) => {
  if (open && !rerankModels.value.length) loadRerankModels()
})

/** 查询平台中已启用的 Rerank 模型。 */
async function loadRerankModels() {
  modelsLoading.value = true
  try {
    const result = await searchModelConfigs({ model_type: 'rerank', enabled: true, page: 1, page_size: 100 })
    rerankModels.value = result.items
  } finally {
    modelsLoading.value = false
  }
}

/** 根据表单生成后端 RetrievalInput，避免向接口发送当前模式不使用的参数。 */
function buildPayload(): KnowledgeRetrievalPayload {
  const retrievalConfig: KnowledgeRetrievalPayload['retrieval_config'] = {
    mode: form.mode,
    top_k: form.top_k,
    fetch_k: form.fetch_k,
    similarity_threshold: form.similarity_threshold,
    metric_type: 'COSINE',
    rrf_k: form.rrf_k,
    per_collection_min_keep: form.per_collection_min_keep,
  }
  if (form.mode === 'hybrid') {
    retrievalConfig.hybrid_weights = {
      vector: form.vector_weight,
      keyword: form.keyword_weight,
    }
  }

  const payload: KnowledgeRetrievalPayload = {
    collection_list: [props.collectionName],
    query: form.query.trim(),
    retrieval_config: retrievalConfig,
    enhance_config: { metadata_headers: form.metadata_headers },
  }
  if (form.file_ids.length) payload.filter_config = { file_ids: form.file_ids }
  if (form.rerank_enabled) {
    payload.rerank_config = {
      enable: true,
      model_code: form.rerank_model_code,
      max_candidates: form.rerank_max_candidates,
      max_chars: form.rerank_max_chars,
    }
  }
  return payload
}

/** 校验参数并执行一次真实知识库检索。 */
async function runRetrieval() {
  if (!form.query.trim()) {
    message.warning('请输入查询内容')
    return
  }
  if (form.top_k > form.fetch_k) {
    message.warning('单库检索时，返回数量不能大于候选数量')
    return
  }
  if (form.mode === 'hybrid' && form.vector_weight === 0 && form.keyword_weight === 0) {
    message.warning('向量权重和关键词权重不能同时为 0')
    return
  }
  if (form.rerank_enabled && !form.rerank_model_code) {
    message.warning('请选择 Rerank 模型')
    return
  }

  searching.value = true
  errorMessage.value = ''
  const startedAt = performance.now()
  try {
    output.value = await testKnowledgeRetrieval(buildPayload())
    elapsedMs.value = Math.round(performance.now() - startedAt)
    lastRunAt.value = new Date().toISOString()
  } catch (error) {
    output.value = null
    errorMessage.value = error instanceof Error ? error.message : '检索请求失败'
  } finally {
    searching.value = false
  }
}

/** 关闭检索测试抽屉。 */
function closeDrawer() {
  emit('update:open', false)
}

/** 复制命中切片正文。 */
async function copyContent(content: string) {
  await navigator.clipboard.writeText(content)
  message.success('切片内容已复制')
}

/** 使用稳定精度展示不同检索模式的分数。 */
function formatScore(score: number) {
  return Math.abs(score) >= 0.01 ? score.toFixed(4) : score.toFixed(6)
}
</script>

<style scoped>
.retrieval-layout{display:grid;grid-template-columns:330px minmax(0,1fr);gap:28px;min-height:calc(100vh - 110px)}.control-panel{padding-right:24px;border-right:1px solid #e8ebf0}.control-section{display:flex;flex-direction:column;gap:10px;padding:0 0 20px;margin-bottom:20px;border-bottom:1px solid #edf0f4}.field-label,.section-title{color:#273247;font-size:13px;font-weight:600}.mode-description{min-height:36px;margin:0;color:#7a8598;font-size:12px;line-height:1.5}.keyboard-tip{color:#9aa3b2;font-size:11px;text-align:center}.number-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}.number-grid label,.advanced-fields{display:flex;flex-direction:column;gap:7px}.number-grid span,.inline-field>span,.slider-field>span{color:#707c8f;font-size:12px}.number-grid :deep(.ant-input-number){width:100%}.slider-field{display:block}.slider-field>span{display:flex;justify-content:space-between}.slider-field strong{color:#315fbd}.advanced-fields{gap:13px}.inline-field{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:13px}.rerank-header{display:flex;align-items:center;justify-content:space-between;margin:18px 0 12px;padding-top:16px;border-top:1px solid #edf0f4}.rerank-header>div{display:flex;flex-direction:column}.rerank-header small{margin-top:3px;color:#8a94a5}.file-filter-label{display:block;margin:18px 0 8px}.result-header{display:flex;align-items:flex-start;justify-content:space-between;gap:20px;padding-bottom:16px;border-bottom:1px solid #e8ebf0}.result-header h2{margin:0;color:#1c2739;font-size:18px}.result-header p{margin:5px 0 0;color:#7c8798;font-size:12px}.run-meta{display:flex;align-items:center;gap:8px;color:#667287;font-size:12px}.loading-state,.result-empty{display:flex;flex-direction:column;align-items:center;justify-content:center;min-height:400px}.loading-state{gap:10px;color:#768196}.loading-state strong{margin-top:8px;color:#2a3548}.result-list{display:flex;flex-direction:column;gap:12px;margin:18px 0 0;padding:0;list-style:none}.result-item{display:grid;grid-template-columns:32px minmax(0,1fr);gap:12px;padding:15px;border:1px solid #e5e9f0;border-radius:8px;background:#fff}.rank{display:flex;align-items:center;justify-content:center;width:28px;height:28px;border-radius:6px;color:#315fbd;background:#edf3ff;font-size:12px;font-weight:700}.result-title,.result-title>div,.result-body footer{display:flex;align-items:center}.result-title{justify-content:space-between;gap:14px}.result-title>div:first-child{min-width:0;gap:8px}.result-title strong{overflow:hidden;color:#273247;text-overflow:ellipsis;white-space:nowrap}.score{flex-shrink:0;gap:6px!important}.score span{color:#929bab;font-size:10px;text-transform:uppercase}.score strong{color:#2e64c5;font-family:ui-monospace,SFMono-Regular,Consolas,monospace;font-size:12px}.result-body>p{margin:12px 0;color:#445066;line-height:1.75;white-space:pre-wrap}.result-body footer{justify-content:space-between;gap:12px;padding-top:10px;border-top:1px solid #f0f2f5}.result-body code{overflow:hidden;color:#9099a8;font-size:10px;text-overflow:ellipsis;white-space:nowrap}@media(max-width:820px){.retrieval-layout{grid-template-columns:1fr}.control-panel{padding-right:0;border-right:0;border-bottom:1px solid #e8ebf0}.result-header{flex-direction:column}.run-meta{flex-wrap:wrap}}@media(max-width:520px){.number-grid{grid-template-columns:1fr}.result-item{grid-template-columns:1fr}.rank{display:none}.result-title{align-items:flex-start;flex-direction:column}.score{align-self:flex-end}}
</style>
