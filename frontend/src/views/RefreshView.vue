<template>
  <div>
    <el-card shadow="never" style="margin-bottom: 14px">
      <el-row :gutter="12" align="middle">
        <el-col :span="6">
          <el-select v-model="centerId" placeholder="研究中心" size="small" style="width: 100%" @change="onCenterChange">
            <el-option v-for="c in centers" :key="c.id" :value="c.id"
              :label="`${c.code} ${c.name}`" />
          </el-select>
        </el-col>
        <el-col :span="6">
          <el-select v-model="productId" placeholder="数据产品分区" size="small" style="width: 100%" @change="loadAll">
            <el-option v-for="c in contracts" :key="c.id" :value="c.product_id"
              :label="`${c.product_code}（${c.frequency}，交付窗 ${c.expected_window_days} 天 ${c.cutoff_time} 前）`" />
          </el-select>
        </el-col>
        <el-col :span="6">
          <el-date-picker v-model="winFrom" type="date" value-format="YYYY-MM-DD" size="small"
            placeholder="画像窗口起" style="width: 100%" @change="loadProfile" />
        </el-col>
        <el-col :span="6">
          <el-date-picker v-model="winTo" type="date" value-format="YYYY-MM-DD" size="small"
            placeholder="画像窗口止" style="width: 100%" @change="loadProfile" />
        </el-col>
      </el-row>
    </el-card>

    <el-tabs v-model="tab">
      <!-- ===================== 画像与就绪判定 ===================== -->
      <el-tab-pane label="时效画像与就绪判定" name="profile">
        <el-row :gutter="14">
          <el-col :span="14">
            <el-card shadow="never" v-loading="profileLoading">
              <template #header><b>刷新时效画像（{{ profile?.center_code }} × {{ profile?.product_code }}）</b></template>
              <template v-if="profile">
                <el-descriptions :column="3" border size="small">
                  <el-descriptions-item label="频率/排程">
                    {{ profile.frequency }}｜周{{ profile.weekday_schedule.join('、') }}
                  </el-descriptions-item>
                  <el-descriptions-item label="固定交付窗">
                    {{ profile.expected_window_days }} 天，{{ profile.cutoff_time }} 前
                  </el-descriptions-item>
                  <el-descriptions-item label="分区/事件数">
                    {{ profile.partition_count }} / {{ profile.total_events }}
                  </el-descriptions-item>
                  <el-descriptions-item label="准时 / 延迟">
                    <el-tag type="success" size="small">{{ profile.on_time_count }}</el-tag>
                    /
                    <el-tag type="warning" size="small">{{ profile.late_count }}</el-tag>
                  </el-descriptions-item>
                  <el-descriptions-item label="迟到补传比例">
                    {{ (profile.backfill_ratio * 100).toFixed(1) }}%（{{ profile.backfill_partition_count }} 个分区）
                  </el-descriptions-item>
                  <el-descriptions-item label="历史更正 / 质控失败 / 待校验">
                    {{ profile.correction_count }} /
                    <el-tag type="danger" size="small">{{ profile.qc_failed_count }}</el-tag> /
                    <el-tag type="warning" size="small">{{ profile.pending_qc_count }}</el-tag>
                  </el-descriptions-item>
                </el-descriptions>

                <div class="block-title">首次发布延迟分布（小时，负数=提前于交付窗）</div>
                <el-table :data="delayRows" size="small" border>
                  <el-table-column prop="label" label="指标" width="110" />
                  <el-table-column prop="value" label="小时数" />
                </el-table>

                <div class="block-title">更正延迟（与首次发布延迟分别统计，小时）</div>
                <el-table :data="correctionRows" size="small" border>
                  <el-table-column prop="label" label="指标" width="110" />
                  <el-table-column prop="value" label="小时数" />
                </el-table>

                <div class="block-title">
                  统计模式阈值（历史 p{{ (profile.statistical.quantile * 100).toFixed(0) }} 条件时效区间）
                  <el-tag :type="profile.statistical.usable ? 'success' : 'info'" size="small" style="margin-left: 8px">
                    {{ profile.statistical.usable ? '历史充足可用' : `历史不足，需 ${profile.statistical.min_history_required} 个` }}
                  </el-tag>
                </div>
                <el-text type="info" size="small">
                  当前阈值 {{ profile.statistical.ready_threshold_hours ?? '—' }} 小时，
                  基于 {{ profile.statistical.history_size }} 个已校验首次发布批次
                </el-text>

                <div class="block-title">连续未更新区间</div>
                <el-empty v-if="!profile.gaps.length" description="窗口内无缺口" :image-size="50" />
                <el-table v-else :data="profile.gaps" size="small" border>
                  <el-table-column prop="from" label="起" width="130" />
                  <el-table-column prop="to" label="止" width="130" />
                  <el-table-column prop="days" label="连续缺分区数" min-width="120" />
                </el-table>
              </template>
            </el-card>
          </el-col>

          <el-col :span="10">
            <el-card shadow="never">
              <template #header><b>就绪判定器（项目 × 产品 × 分析截止日）</b></template>
              <el-form label-width="92px" size="small">
                <el-form-item label="课题">
                  <el-select v-model="readyForm.project_id" style="width: 100%">
                    <el-option v-for="p in projects" :key="p.id" :value="p.id" :label="`${p.code} ${p.name}`" />
                  </el-select>
                </el-form-item>
                <el-form-item label="研究窗起">
                  <el-date-picker v-model="readyForm.window_from" type="date"
                    value-format="YYYY-MM-DD" style="width: 100%" />
                </el-form-item>
                <el-form-item label="分析截止日">
                  <el-date-picker v-model="readyForm.analysis_cutoff" type="date"
                    value-format="YYYY-MM-DD" style="width: 100%" />
                </el-form-item>
                <el-form-item label="判定模式">
                  <el-radio-group v-model="readyForm.mode">
                    <el-radio value="fixed">固定期限</el-radio>
                    <el-radio value="statistical">统计阈值</el-radio>
                  </el-radio-group>
                </el-form-item>
                <el-button type="primary" @click="evaluate" :loading="readyLoading">评估是否可启动分析</el-button>
                <el-text type="info" size="small" style="margin-left: 8px">
                  固定期限按目录约定追责；统计阈值按历史到达分布识别中心差异
                </el-text>
              </el-form>

              <template v-if="verdict">
                <el-divider style="margin: 12px 0" />
                <el-descriptions :column="1" border size="small">
                  <el-descriptions-item label="总体状态">
                    <el-tag :type="stateType(verdict.state)" size="small">{{ verdict.state }}</el-tag>
                    <span v-if="verdict.superseded" style="margin-left: 8px">
                      <el-tag type="info" size="small">涉及分区已有新批次（快照已冻结）</el-tag>
                    </span>
                  </el-descriptions-item>
                  <el-descriptions-item label="判定汇总">{{ verdict.reason }}</el-descriptions-item>
                </el-descriptions>

                <div class="block-title">实际数据水位（不只是红黄状态）</div>
                <el-descriptions :column="2" border size="small">
                  <el-descriptions-item label="可用分区">
                    {{ verdict.watermark.available_partition_count }} 个
                  </el-descriptions-item>
                  <el-descriptions-item label="最新可用分区">
                    {{ verdict.watermark.latest_available_partition ?? '—' }}
                  </el-descriptions-item>
                  <el-descriptions-item label="可用记录数">
                    {{ verdict.watermark.total_records }}
                  </el-descriptions-item>
                  <el-descriptions-item label="最新可用时间">
                    {{ verdict.watermark.latest_available_at ?? '—' }}
                  </el-descriptions-item>
                  <el-descriptions-item label="待校验分区">
                    {{ verdict.watermark.pending_qc_partitions.join('、') || '无' }}
                  </el-descriptions-item>
                  <el-descriptions-item label="质控失败分区">
                    {{ verdict.watermark.qc_failed_partitions.join('、') || '无' }}
                  </el-descriptions-item>
                  <el-descriptions-item label="已更正分区" :span="2">
                    {{ verdict.watermark.corrected_partitions.join('、') || '无' }}
                  </el-descriptions-item>
                </el-descriptions>

                <el-button size="small" text type="primary" @click="showPartitions = !showPartitions">
                  {{ showPartitions ? '收起分区级判定' : '展开分区级判定与原因' }}
                </el-button>
                <el-table v-if="showPartitions" :data="verdict.evidence.partition_verdicts" size="small"
                  max-height="260" border style="margin-top: 6px">
                  <el-table-column prop="partition_date" label="分区日" width="105" />
                  <el-table-column label="状态" width="92">
                    <template #default="{ row }">
                      <el-tag :type="stateType(row.state)" size="small">{{ row.state }}</el-tag>
                    </template>
                  </el-table-column>
                  <el-table-column label="判定依据（阈值/模式/原因）" min-width="220">
                    <template #default="{ row }">
                      <div style="line-height: 1.5">
                        <div>{{ row.reason }}</div>
                        <el-text type="info" size="small">
                          截止 {{ row.expected_due_at }}｜{{ row.mode_used }}
                          <template v-if="row.threshold_hours !== null">｜阈值 {{ row.threshold_hours }}h</template>
                          <template v-if="row.mode_note">｜{{ row.mode_note }}</template>
                        </el-text>
                      </div>
                    </template>
                  </el-table-column>
                </el-table>
              </template>
            </el-card>
          </el-col>
        </el-row>
      </el-tab-pane>

      <!-- ===================== 刷新事件 ===================== -->
      <el-tab-pane label="刷新事件" name="events">
        <el-card shadow="never">
          <template #header>
            <div style="display: flex; justify-content: space-between; align-items: center">
              <b>批次刷新事件（生成/接收/校验全过程）</b>
              <el-button v-if="isAdmin" type="primary" size="small" @click="openRegister">登记批次接收</el-button>
            </div>
          </template>
          <el-table :data="events" size="small" v-loading="eventLoading" max-height="560">
            <el-table-column prop="partition_date" label="分区日" width="105" />
            <el-table-column prop="batch_no" label="批次号" width="165" show-overflow-tooltip />
            <el-table-column label="性质" width="90">
              <template #default="{ row }">
                <el-tag :type="row.event_kind === '更正发布' ? 'warning' : (row.event_kind === '迟到补传' ? 'danger' : 'info')"
                  size="small">{{ row.event_kind }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="状态" width="90">
              <template #default="{ row }">
                <el-tag :type="eventStatusType(row.status)" size="small">{{ row.status }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="received_at" label="接收时间" width="165" />
            <el-table-column prop="validated_at" label="质控通过" width="165" />
            <el-table-column label="首次延迟(h)" width="100">
              <template #default="{ row }">{{ row.first_publish_delay_hours ?? '—' }}</template>
            </el-table-column>
            <el-table-column label="更正延迟(h)" width="100">
              <template #default="{ row }">{{ row.correction_delay_hours ?? '—' }}</template>
            </el-table-column>
            <el-table-column prop="fail_reason" label="失败原因" min-width="180" show-overflow-tooltip>
              <template #default="{ row }">{{ row.fail_reason || '—' }}</template>
            </el-table-column>
            <el-table-column v-if="isAdmin" label="质控操作" width="150" fixed="right">
              <template #default="{ row }">
                <el-button v-if="row.status === '已接收'" size="small" text type="success"
                  @click="openQc(row, true)">通过</el-button>
                <el-button v-if="row.status === '已接收'" size="small" text type="danger"
                  @click="openQc(row, false)">失败</el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-tab-pane>

      <!-- ===================== 停诊与快照 ===================== -->
      <el-tab-pane label="停诊窗口与历史快照" name="admin">
        <el-row :gutter="14">
          <el-col :span="11">
            <el-card shadow="never">
              <template #header>
                <div style="display: flex; justify-content: space-between; align-items: center">
                  <b>计划停诊/停采（窗口内标记预期无采集）</b>
                  <el-button v-if="isAdmin" type="primary" size="small" @click="pauseDialog = true">登记停诊</el-button>
                </div>
              </template>
              <el-table :data="pauses" size="small">
                <el-table-column prop="pause_from" label="起" width="110" />
                <el-table-column prop="pause_to" label="止" width="110" />
                <el-table-column prop="reason" label="原因" min-width="150" />
              </el-table>
            </el-card>
          </el-col>
          <el-col :span="13">
            <el-card shadow="never">
              <template #header><b>历史就绪快照（冻结水位，可由刷新事件复算）</b></template>
              <el-table :data="snapshots" size="small" max-height="420">
                <el-table-column prop="id" label="ID" width="55" />
                <el-table-column prop="analysis_cutoff" label="截止日" width="105" />
                <el-table-column label="模式" width="85">
                  <template #default="{ row }">
                    {{ row.mode === 'fixed' ? '固定期限' : '统计阈值' }}
                  </template>
                </el-table-column>
                <el-table-column label="状态" width="85">
                  <template #default="{ row }">
                    <el-tag :type="stateType(row.state)" size="small">{{ row.state }}</el-tag>
                  </template>
                </el-table-column>
                <el-table-column label="冻结" width="75">
                  <template #default="{ row }">
                    <el-tag :type="row.superseded ? 'info' : 'success'" size="small">
                      {{ row.superseded ? '已过时' : '当前' }}
                    </el-tag>
                  </template>
                </el-table-column>
                <el-table-column prop="reason" label="原因" min-width="160" show-overflow-tooltip />
                <el-table-column label="操作" width="80">
                  <template #default="{ row }">
                    <el-button size="small" text type="primary" @click="recompute(row)">复算</el-button>
                  </template>
                </el-table-column>
              </el-table>
            </el-card>
          </el-col>
        </el-row>
      </el-tab-pane>
    </el-tabs>

    <!-- 登记批次 -->
    <el-dialog v-model="registerDialog" title="登记批次接收" width="560px">
      <el-form :model="regForm" label-width="110px" size="small">
        <el-form-item label="分区数据日">
          <el-date-picker v-model="regForm.partition_date" type="date" value-format="YYYY-MM-DD" style="width: 100%" />
        </el-form-item>
        <el-form-item label="接收时间">
          <el-date-picker v-model="regForm.received_at" type="datetime"
            value-format="YYYY-MM-DD HH:mm:ss" style="width: 100%" />
        </el-form-item>
        <el-form-item label="批次性质">
          <el-radio-group v-model="regForm.event_kind" @change="onKindChange">
            <el-radio value="全量刷新">全量刷新</el-radio>
            <el-radio value="迟到补传">迟到补传</el-radio>
            <el-radio value="更正发布">更正发布</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item v-if="regForm.event_kind === '更正发布'" label="被更正批次">
          <el-select v-model="regForm.correction_of_id" style="width: 100%" placeholder="选择同分区已校验批次">
            <el-option v-for="e in correctableEvents" :key="e.id" :value="e.id"
              :label="`${e.batch_no}（版次 ${e.revision_no}）`" />
          </el-select>
        </el-form-item>
        <el-form-item label="记录数">
          <el-input-number v-model="regForm.record_count" :min="0" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="registerDialog = false">取消</el-button>
        <el-button type="primary" @click="submitRegister">登记</el-button>
      </template>
    </el-dialog>

    <!-- 质控对话框 -->
    <el-dialog v-model="qcDialog" :title="qcPass ? '质控通过' : '登记质控失败'" width="480px">
      <el-form label-width="100px" size="small">
        <el-form-item :label="qcPass ? '通过时间' : '失败时间'">
          <el-date-picker v-model="qcForm.time" type="datetime"
            value-format="YYYY-MM-DD HH:mm:ss" style="width: 100%" />
        </el-form-item>
        <el-form-item v-if="qcPass" label="记录数">
          <el-input-number v-model="qcForm.record_count" :min="0" />
        </el-form-item>
        <el-form-item v-else label="失败原因">
          <el-input v-model="qcForm.reason" type="textarea" :rows="2" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="qcDialog = false">取消</el-button>
        <el-button :type="qcPass ? 'success' : 'danger'" @click="submitQc">确认</el-button>
      </template>
    </el-dialog>

    <!-- 停诊对话框 -->
    <el-dialog v-model="pauseDialog" title="登记计划停诊/停采" width="480px">
      <el-form :model="pauseForm" label-width="100px" size="small">
        <el-form-item label="停诊区间">
          <el-date-picker v-model="pauseRange" type="daterange" value-format="YYYY-MM-DD"
            start-placeholder="起" end-placeholder="止" style="width: 100%" />
        </el-form-item>
        <el-form-item label="适用产品">
          <el-select v-model="pauseForm.product_id" clearable placeholder="留空=中心整体停诊" style="width: 100%">
            <el-option v-for="c in contracts" :key="c.id" :value="c.product_id" :label="c.product_code" />
          </el-select>
        </el-form-item>
        <el-form-item label="原因">
          <el-input v-model="pauseForm.reason" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="pauseDialog = false">取消</el-button>
        <el-button type="primary" @click="submitPause">登记</el-button>
      </template>
    </el-dialog>

    <!-- 复算对照 -->
    <el-dialog v-model="recomputeDialog" title="就绪快照复算对照" width="640px">
      <template v-if="recomputeResult">
        <el-descriptions :column="1" border size="small">
          <el-descriptions-item label="冻结状态">
            <el-tag :type="stateType(recomputeResult.frozen_state)" size="small">
              {{ recomputeResult.frozen_state }}
            </el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="复算状态">
            <el-tag :type="stateType(recomputeResult.recomputed_state)" size="small">
              {{ recomputeResult.recomputed_state }}
            </el-tag>
            <el-tag :type="recomputeResult.state_changed ? 'warning' : 'success'" size="small" style="margin-left: 8px">
              {{ recomputeResult.state_changed ? '结论已变化' : '结论一致' }}
            </el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="冻结水位">
            可用 {{ recomputeResult.frozen_watermark.available_partition_count }} 分区，
            最新 {{ recomputeResult.frozen_watermark.latest_available_partition ?? '—' }}，
            {{ recomputeResult.frozen_watermark.total_records }} 条记录
          </el-descriptions-item>
          <el-descriptions-item label="当前复算水位">
            可用 {{ recomputeResult.recomputed_watermark.available_partition_count }} 分区，
            最新 {{ recomputeResult.recomputed_watermark.latest_available_partition ?? '—' }}，
            {{ recomputeResult.recomputed_watermark.total_records }} 条记录
          </el-descriptions-item>
          <el-descriptions-item label="复算原因">{{ recomputeResult.recomputed_reason }}</el-descriptions-item>
        </el-descriptions>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import api, { currentUser } from '../api'

const user = currentUser()
const isAdmin = user?.role === 'ADMIN'

const centers = ref([])
const contracts = ref([])
const projects = ref([])
const pauses = ref([])
const events = ref([])
const snapshots = ref([])
const profile = ref(null)
const verdict = ref(null)
const tab = ref('profile')

const centerId = ref(null)
const productId = ref(null)
const winFrom = ref(null)
const winTo = ref(null)
const profileLoading = ref(false)
const eventLoading = ref(false)
const readyLoading = ref(false)
const showPartitions = ref(false)

const readyForm = reactive({ project_id: null, window_from: null, analysis_cutoff: null, mode: 'fixed' })

const delayRows = computed(() => {
  if (!profile.value) return []
  const m = profile.value.delay_hours
  return [
    { label: '最小', value: m.min ?? '—' },
    { label: 'P50 中位', value: m.p50 ?? '—' },
    { label: 'P90', value: m.p90 ?? '—' },
    { label: '最大', value: m.max ?? '—' },
    { label: '平均', value: m.mean ?? '—' },
  ]
})
const correctionRows = computed(() => {
  if (!profile.value) return []
  const m = profile.value.correction_delay_hours
  return [
    { label: 'P50', value: m.p50 ?? '—' },
    { label: 'P90', value: m.p90 ?? '—' },
    { label: '最大', value: m.max ?? '—' },
  ]
})

function stateType(s) {
  return { 及时: 'success', 延迟: 'warning', 缺失: 'danger', 待校验: 'warning', 预期无采集: 'info' }[s] || 'info'
}
function eventStatusType(s) {
  return { 已校验: 'success', 已更正: 'info', 已接收: 'warning', 校验失败: 'danger' }[s] || 'info'
}

async function loadBase() {
  const [c, ct, pj] = await Promise.all([
    api.get('/refresh/centers'), api.get('/refresh/contracts'), api.get('/projects'),
  ])
  centers.value = c.data
  contracts.value = ct.data
  projects.value = pj.data
  if (!centerId.value && c.data.length) centerId.value = c.data[0].id
  onCenterChange()
  if (projects.value.length) readyForm.project_id = projects.value[0].id
}

function onCenterChange() {
  const list = contracts.value.filter((c) => c.center_id === centerId.value)
  productId.value = list.length ? list[0].product_id : null
  loadAll()
}

async function loadAll() {
  if (!centerId.value || !productId.value) return
  await Promise.all([loadProfile(), loadEvents(), loadPauses(), loadSnapshots()])
  if (!readyForm.window_from) readyForm.window_from = winFrom.value
  if (!readyForm.analysis_cutoff) readyForm.analysis_cutoff = winTo.value
}

async function loadProfile() {
  if (!centerId.value || !productId.value) return
  profileLoading.value = true
  try {
    const { data } = await api.get('/refresh/profiles', {
      params: { center_id: centerId.value, product_id: productId.value,
        window_from: winFrom.value || undefined, window_to: winTo.value || undefined },
    })
    profile.value = data
  } finally {
    profileLoading.value = false
  }
}

async function loadEvents() {
  eventLoading.value = true
  try {
    const { data } = await api.get('/refresh/events', {
      params: { center_id: centerId.value, product_id: productId.value },
    })
    events.value = data
  } finally {
    eventLoading.value = false
  }
}

async function loadPauses() {
  const { data } = await api.get('/refresh/pauses', { params: { center_id: centerId.value } })
  pauses.value = data
}

async function loadSnapshots() {
  const { data } = await api.get('/refresh/readiness', {
    params: { center_id: centerId.value, product_id: productId.value },
  })
  snapshots.value = data
}

async function evaluate() {
  readyLoading.value = true
  try {
    const { data } = await api.post('/refresh/readiness', {
      center_id: centerId.value, product_id: productId.value, ...readyForm,
    })
    verdict.value = data
    ElMessage.success(`判定完成：${data.state}`)
    loadSnapshots()
  } finally {
    readyLoading.value = false
  }
}

// ---------- 登记批次 ----------
const registerDialog = ref(false)
const regForm = reactive({
  partition_date: null, received_at: null, event_kind: '全量刷新',
  correction_of_id: null, record_count: 0,
})
const correctableEvents = computed(() =>
  events.value.filter((e) => e.partition_date === regForm.partition_date && e.status === '已校验'))

function openRegister() {
  regForm.partition_date = null
  regForm.received_at = null
  regForm.event_kind = '全量刷新'
  regForm.correction_of_id = null
  regForm.record_count = 0
  registerDialog.value = true
}
function onKindChange() {
  if (regForm.event_kind !== '更正发布') regForm.correction_of_id = null
}
async function submitRegister() {
  const { data } = await api.post('/refresh/events', {
    center_id: centerId.value, product_id: productId.value, ...regForm,
  })
  ElMessage.success(`已登记 ${data.event.batch_no}，${data.snapshots_marked_superseded} 条旧快照标记过时`)
  registerDialog.value = false
  await loadAll()
}

// ---------- 质控 ----------
const qcDialog = ref(false)
const qcPass = ref(true)
const qcTarget = ref(null)
const qcForm = reactive({ time: null, reason: '', record_count: 0 })
function openQc(row, pass) {
  qcTarget.value = row
  qcPass.value = pass
  qcForm.time = new Date().toISOString().slice(0, 19).replace('T', ' ')
  qcForm.reason = ''
  qcForm.record_count = row.record_count || 0
  qcDialog.value = true
}
async function submitQc() {
  const url = `/refresh/events/${qcTarget.value.id}/${qcPass.value ? 'qc-pass' : 'qc-fail'}`
  const payload = qcPass.value
    ? { validated_at: qcForm.time, record_count: qcForm.record_count }
    : { failed_at: qcForm.time, reason: qcForm.reason || '质控未通过' }
  const { data } = await api.post(url, payload)
  ElMessage.success(`批次 ${data.event.batch_no} → ${data.event.status}`)
  qcDialog.value = false
  await loadAll()
}

// ---------- 停诊 ----------
const pauseDialog = ref(false)
const pauseRange = ref([])
const pauseForm = reactive({ product_id: null, reason: '计划停诊' })
async function submitPause() {
  if (!pauseRange.value?.length) return ElMessage.warning('请选择停诊区间')
  await api.post('/refresh/pauses', {
    center_id: centerId.value, product_id: pauseForm.product_id,
    pause_from: pauseRange.value[0], pause_to: pauseRange.value[1], reason: pauseForm.reason,
  })
  ElMessage.success('停诊窗口已登记')
  pauseDialog.value = false
  await loadPauses()
  await loadProfile()
}

// ---------- 复算 ----------
const recomputeDialog = ref(false)
const recomputeResult = ref(null)
async function recompute(row) {
  const { data } = await api.post(`/refresh/readiness/${row.id}/recompute`)
  recomputeResult.value = data
  recomputeDialog.value = true
}

onMounted(async () => {
  const today = new Date()
  const fmt = (d) => d.toISOString().slice(0, 10)
  winTo.value = fmt(today)
  winFrom.value = fmt(new Date(today.getTime() - 27 * 86400000))
  await loadBase()
})
</script>

<style scoped>
.block-title {
  font-weight: 600;
  font-size: 13px;
  color: #1f2d3d;
  margin: 14px 0 6px;
}
</style>
