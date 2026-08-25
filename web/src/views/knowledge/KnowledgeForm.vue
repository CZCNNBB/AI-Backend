<template>
  <div class="form-page">
    <header class="page-header">
      <div class="title-side">
        <a-button type="text" @click="goBack"><template #icon><ArrowLeftOutlined /></template></a-button>
        <div><h1>{{ isEdit ? '编辑知识库' : '新建知识库' }}</h1><p>{{ isEdit ? '调整基础信息、运行状态和后续文档的默认切片方式。' : '创建一个可供 Agent 检索的资料集合。' }}</p></div>
      </div>
    </header>

    <a-spin :spinning="loading">
      <a-form ref="formRef" :model="form" :rules="rules" layout="vertical" class="knowledge-form">
        <section class="form-section">
          <div class="section-heading"><span>1</span><div><h2>基础信息</h2><p>用于管理页和 Agent 运行时识别知识库。</p></div></div>
          <div class="section-body two-column">
            <a-form-item label="知识库名称" name="name">
              <a-input v-model:value="form.name" placeholder="例如：AI 工程岗位资料库" :maxlength="100" show-count />
            </a-form-item>
            <a-form-item v-if="isEdit" label="运行状态" name="status">
              <a-segmented v-model:value="form.status" :options="statusOptions" block />
            </a-form-item>
            <a-form-item label="描述" class="full-column">
              <a-textarea v-model:value="form.description" placeholder="说明资料范围和适用场景" :rows="3" :maxlength="500" show-count />
            </a-form-item>
          </div>
        </section>

        <section class="form-section">
          <div class="section-heading"><span>2</span><div><h2>Embedding 模型</h2><p>决定向量维度和索引空间，知识库创建后不可修改。</p></div></div>
          <div class="section-body">
            <a-alert v-if="isEdit" type="info" show-icon message="Embedding 模型已锁定">
              <template #description>当前使用 {{ form.embedding_model_code }}，如需更换模型，请创建新的知识库并重新入库。</template>
            </a-alert>
            <a-skeleton v-else-if="loadingModels" active :paragraph="{ rows: 3 }" />
            <a-empty v-else-if="!embeddingModels.length && !isEdit" description="暂无可用的 Embedding 模型">
              <a-button type="primary" @click="router.push('/settings/model')">前往模型配置</a-button>
            </a-empty>
            <a-radio-group v-else-if="!isEdit" v-model:value="form.embedding_model_code" class="model-group">
              <button v-for="model in embeddingModels" :key="model.model_code" type="button"
                class="model-row" :class="{ selected: form.embedding_model_code === model.model_code }"
                @click="form.embedding_model_code = model.model_code">
                <a-radio :value="model.model_code" />
                <span class="model-main"><strong>{{ model.model_code }}</strong><small>{{ model.description || model.model_name }}</small></span>
                <span class="model-meta"><b>{{ getDimension(model) ?? '-' }}</b> 维</span>
              </button>
            </a-radio-group>
          </div>
        </section>

        <section class="form-section">
          <div class="section-heading"><span>3</span><div><h2>默认切片</h2><p>应用于后续提交的文档，单次入库仍可覆盖。</p></div></div>
          <div class="section-body">
            <a-form-item label="切片策略">
              <a-select v-model:value="form.split_config.type" style="max-width: 420px">
                <a-select-option value="recursive_character">递归字符切片</a-select-option>
                <a-select-option value="markdown_document_header_then_recursive">Markdown 标题 + 递归细切</a-select-option>
                <a-select-option value="markdown_header">Markdown 标题切片</a-select-option>
                <a-select-option value="character">固定字符切片</a-select-option>
                <a-select-option value="qa_separator">问答分隔切片</a-select-option>
              </a-select>
            </a-form-item>
            <div class="split-grid">
              <a-form-item label="分块大小">
                <a-input-number v-model:value="form.split_config.chunk_size" :min="100" :max="8000" :step="100" style="width:100%" />
                <span class="field-help">单个分块的目标字符数。</span>
              </a-form-item>
              <a-form-item label="重叠长度">
                <a-input-number v-model:value="form.split_config.chunk_overlap" :min="0" :max="2000" :step="20" style="width:100%" />
                <span class="field-help">建议为分块大小的 10% 至 20%。</span>
              </a-form-item>
              <a-form-item v-if="showSeparator" label="分隔符">
                <a-select v-model:value="form.split_config.separator">
                  <a-select-option :value="'\n\n'">双换行</a-select-option>
                  <a-select-option :value="'\n'">单换行</a-select-option>
                  <a-select-option :value="'。\n'">句号加换行</a-select-option>
                </a-select>
              </a-form-item>
            </div>
          </div>
        </section>

        <footer class="submit-bar">
          <a-button @click="goBack">取消</a-button>
          <a-button type="primary" :loading="submitting" @click="submitForm">
            {{ isEdit ? '保存修改' : '创建知识库' }}
          </a-button>
        </footer>
      </a-form>
    </a-spin>
  </div>
</template>

<script setup lang="ts">
/** 知识库创建与编辑表单。 */
import { computed, onMounted, reactive, ref } from 'vue'
import type { FormInstance } from 'ant-design-vue'
import { message } from 'ant-design-vue'
import { ArrowLeftOutlined } from '@ant-design/icons-vue'
import { useRoute, useRouter } from 'vue-router'
import { createKnowledgeBase, getKnowledgeBase, updateKnowledgeBase } from '@/api/knowledge'
import { listEnabledEmbeddingModels, type ModelConfigItem } from '@/api/modelConfigs'

defineOptions({ name: 'KnowledgeForm' })
const route = useRoute()
const router = useRouter()
const knowledgeId = computed(() => String(route.params.knowledge_id || ''))
const isEdit = computed(() => !!knowledgeId.value)
const formRef = ref<FormInstance>()
const loading = ref(false)
const loadingModels = ref(false)
const submitting = ref(false)
const embeddingModels = ref<ModelConfigItem[]>([])
const form = reactive({
  name: '',
  description: '',
  status: 'active' as 'active' | 'disabled',
  embedding_model_code: '',
  split_config: {
    type: 'recursive_character',
    chunk_size: 800,
    chunk_overlap: 100,
    separator: '\n\n',
  } as Record<string, unknown> & { type: string; chunk_size: number; chunk_overlap: number; separator: string },
})
const rules = {
  name: [{ required: true, message: '请输入知识库名称', trigger: 'blur' }],
  embedding_model_code: [{ required: true, message: '请选择 Embedding 模型' }],
}
const statusOptions = [{ label: '运行中', value: 'active' }, { label: '已停用', value: 'disabled' }]
const showSeparator = computed(() => ['recursive_character', 'character', 'qa_separator'].includes(form.split_config.type))

/** 加载可用于新建知识库的 Embedding 模型。 */
async function loadEmbeddingModels() {
  loadingModels.value = true
  try { embeddingModels.value = await listEnabledEmbeddingModels() }
  catch { embeddingModels.value = [] }
  finally { loadingModels.value = false }
}

/** 编辑模式下加载已有知识库配置。 */
async function loadDetail() {
  if (!isEdit.value) return
  loading.value = true
  try {
    const record = await getKnowledgeBase(knowledgeId.value)
    form.name = record.name
    form.description = record.description || ''
    form.status = record.status === 'disabled' ? 'disabled' : 'active'
    form.embedding_model_code = record.embedding_model_code
    Object.assign(form.split_config, record.split_config)
  } finally { loading.value = false }
}

/** 校验并提交创建或编辑请求。 */
async function submitForm() {
  try { await formRef.value?.validate() } catch { return }
  if (!isEdit.value && !form.embedding_model_code) {
    message.warning('请选择 Embedding 模型')
    return
  }
  submitting.value = true
  try {
    if (isEdit.value) {
      await updateKnowledgeBase({
        knowledge_id: knowledgeId.value,
        name: form.name.trim(),
        description: form.description.trim() || null,
        status: form.status,
        split_config: { ...form.split_config },
      })
      message.success('知识库配置已更新')
      router.push(`/knowledge/${knowledgeId.value}`)
    } else {
      const created = await createKnowledgeBase({
        name: form.name.trim(),
        description: form.description.trim() || null,
        embedding_model_code: form.embedding_model_code,
        split_config: { ...form.split_config },
      })
      message.success('知识库已创建')
      router.push(`/knowledge/${created.knowledge_id}`)
    }
  } finally { submitting.value = false }
}

/** 返回详情或列表。 */
function goBack() {
  router.push(isEdit.value ? `/knowledge/${knowledgeId.value}` : '/knowledge')
}

/** 从模型扩展配置读取向量维度。 */
function getDimension(model: ModelConfigItem): number | null {
  const value = model.extra_config?.dimension
  return typeof value === 'number' ? value : null
}

onMounted(async () => {
  if (isEdit.value) await loadDetail()
  else await loadEmbeddingModels()
})
</script>

<style scoped>
.page-header{margin-bottom:22px}.title-side{display:flex;align-items:flex-start;gap:8px}.title-side h1{margin:0;color:#172033;font-size:24px}.title-side p{margin:5px 0 0;color:#727d90}.knowledge-form{max-width:1040px}.form-section{display:grid;grid-template-columns:240px minmax(0,1fr);padding:28px 0;border-top:1px solid #e7eaf0}.section-heading{display:flex;align-items:flex-start;gap:12px;padding-right:28px}.section-heading>span{display:inline-flex;align-items:center;justify-content:center;width:26px;height:26px;flex:0 0 26px;border-radius:6px;color:#fff;background:#3366cc;font-size:12px;font-weight:700}.section-heading h2{margin:1px 0 5px;color:#273247;font-size:15px}.section-heading p{margin:0;color:#8490a3;font-size:12px;line-height:1.6}.section-body{min-width:0}.two-column{display:grid;grid-template-columns:1fr 1fr;gap:0 18px}.full-column{grid-column:1/-1}.model-group{display:flex;flex-direction:column;width:100%;gap:8px}.model-row{display:flex;align-items:center;gap:12px;width:100%;padding:13px 15px;border:1px solid #dfe4ec;border-radius:7px;background:#fff;text-align:left;cursor:pointer}.model-row:hover,.model-row.selected{border-color:#5b82d1;background:#f5f8ff}.model-main{display:flex;flex:1;flex-direction:column;min-width:0}.model-main strong{color:#263248}.model-main small{margin-top:3px;overflow:hidden;color:#7d889b;text-overflow:ellipsis;white-space:nowrap}.model-meta{color:#7d889b;font-size:12px}.model-meta b{color:#33415a}.split-grid{display:grid;grid-template-columns:1fr 1fr;gap:0 18px;max-width:680px}.field-help{display:block;margin-top:5px;color:#8a94a6;font-size:11px}.submit-bar{position:sticky;bottom:0;display:flex;justify-content:flex-end;gap:10px;padding:16px 0;background:rgba(255,255,255,.96);border-top:1px solid #e7eaf0;z-index:5}@media(max-width:760px){.form-section{grid-template-columns:1fr;gap:18px}.two-column,.split-grid{grid-template-columns:1fr}.section-heading{padding-right:0}}
</style>
