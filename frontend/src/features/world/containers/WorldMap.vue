<script setup lang="ts">
/**
 * 世界地图（Leaflet CRS.Simple + 零图片点阵画布）。
 *
 * 图层（自下而上）：底图占位 → move 轨迹线 → 疆域 polygon → 事件 marker → 地点 marker → 人物 marker。
 * 地点/人物/事件用 divIcon 自定义视觉（wm- 前缀样式在底部非 scoped style 块——
 * Leaflet 创建的 DOM 不在 Vue scoped 作用域内）。
 *
 * 坐标约定：Leaflet [lat,lng]，CRS.Simple 下 lat=y、lng=x；内部坐标 Point=[x,y]。
 * 设计意图：事件溯源的世界地图——拖时间轴，人物/疆域/轨迹/历史事件随 currentTime 回放。
 */
import { ref, computed, onMounted, onBeforeUnmount, watch, nextTick } from 'vue'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import Icon from '../../../components/Icon.vue'
import { useToast } from '../../../composables/useToast'
import { useConfirmDialog } from '../../../composables/useConfirmDialog'
import { useWorld } from '../composables/useWorld'
import { useMapEdit, resolveImageUrl, editUndo, editRedo } from '../composables/useMapEdit'
import { eventPoint, stripPointFromNote, centroid } from '../engine/eventPoint'
import { childrenIndex } from '../engine/locationTree'
import { EVENT_TYPE_COLOR, eventDisplayName } from '../engine/eventTemplates'
import { formatTime } from '../engine/timeFormat'
import { relationTypeMeta } from '../engine/relationTypes'
import {
  arcControlPoint,
  countSyntheticTail,
  distToSeg,
  pickNearest,
  pickScaleBarDays,
  resampleRing,
} from '../engine/mapGeometry'
import { escapeHtml as esc } from '../../../shared/utils/htmlText'
import RelationInlineForm from '../presentation/RelationInlineForm.vue'
import { BLANK_ATLAS_INNER, BLANK_ATLAS_VIEWBOX } from './blankAtlas'
import type { DrawMode, WorldEvent, WorldLocation, WorldMapLayer, WorldRelation } from '../engine/types'

const props = defineProps<{
  bookId: string
  /** 拾取模式：null=浏览, 'location'=点选建地点, 'quick-note'=速记新地点标位（点击 emit pick） */
  pickingMode?: 'location' | 'quick-note' | null
  /** 绘制模式：非 null 时地图点击收集顶点（point 模式单击即完成），双击/Enter/完成闭合后 emit draw-complete */
  drawMode?: DrawMode
  /** D4 比例尺标定（books.map_scale；null=未标定角标显示引导） */
  mapScale?: MapScale | null
  /** 地标脉冲高亮（面板 📍 定位回指；WorldView 定时摘除——class 常驻会在 zoomend 重渲时随机重播） */
  highlightLocationId?: string | null
}>()

const emit = defineEmits<{
  pick: [point: [number, number]]
  'draw-complete': [points: [number, number][]]
  'entity-click': [entityId: string]
  'location-detail': [locationId: string]
  /** 地标点击回指（与 popup 并存；父级据此在地点面板内高亮+滚动对应条目） */
  'location-highlight': [locationId: string]
}>()

// ===== D4 比例尺标定：拉线捕获 + 左下角比例尺角标 =====
import { pxPerDay, blankAtlasSuggestedDays, type MapScale } from '../engine/distance'

const calibrating = ref(false)
const calibPoints = ref<[number, number][]>([])
let calibLine: L.Polyline | null = null
const scaleBarText = ref('')

function startCalibrating() {
  calibrating.value = true
  calibPoints.value = []
  if (calibLine && map) { map.removeLayer(calibLine); calibLine = null }
}
function stopCalibrating() {
  calibrating.value = false
}
function renderCalibLine() {
  if (!map) return
  if (calibLine) map.removeLayer(calibLine)
  calibLine = null
  if (calibPoints.value.length) {
    calibLine = L.polyline(
      calibPoints.value.map(([x, y]) => L.latLng(y, x)),
      { color: '#c2725a', weight: 2, dashArray: '6 4' },
    ).addTo(map)
  }
}

/** 角标：按当前缩放选一个 60~160px 的整数天值画「—— ≈ N 天步程」（玩具感来源） */
function updateScaleBar() {
  const ppd = pxPerDay(props.mapScale)
  if (!map || ppd == null) { scaleBarText.value = ''; return }
  const zoom = map.getZoom()
  // CRS.Simple 覆写了 scale(zoom)=2^zoom（非 EPSG:3857 的 256·2^zoom）：
  // zoom 0 时 1 tile(256px) 恰覆盖 256 内部单位 → 1 screen px = 1/2^z 内部单位
  const unitsPerScreenPx = 1 / (2 ** zoom)
  const days = pickScaleBarDays(ppd, unitsPerScreenPx)
  scaleBarText.value = days == null ? '已标定' : `≈ ${days < 1 ? '半日' : days + ' 天'}步程`
}

function onCalibrateStart() { startCalibrating() }

onMounted(() => {
  window.addEventListener('velluma:map-calibrate-start', onCalibrateStart)
  // 初渲即有角标（2026-09-04 审计修复：此前只在缩放后出现——已标定的书
  // 加载完成时角标为空，必须先缩放一次才渲染）
  nextTick(() => updateScaleBar())
})
onBeforeUnmount(() => window.removeEventListener('velluma:map-calibrate-start', onCalibrateStart))
watch(() => props.mapScale, () => nextTick(() => updateScaleBar()))

const containerRef = ref<HTMLDivElement | null>(null)
let map: L.Map | null = null
let baseImageLayer: L.LayerGroup | null = null
let trackLayer: L.LayerGroup | null = null
let territoryLayer: L.LayerGroup | null = null
let eventLayer: L.LayerGroup | null = null
let markerLayer: L.LayerGroup | null = null
let entityLayer: L.LayerGroup | null = null
let relationLayer: L.LayerGroup | null = null
let rippleLayer: L.LayerGroup | null = null
let drawLayer: L.LayerGroup | null = null
let editHitLayer: L.LayerGroup | null = null
let editSelLayer: L.LayerGroup | null = null
/** 图片层 id → overlay 实例（编辑拖拽时直接 setBounds，避免整层重建闪烁） */
const overlayMap = new Map<string, L.ImageOverlay>()
/** 占位面板 marker（无底图时显示，有图自动隐藏） */
let blankOverlay: L.SVGOverlay | null = null

// ---- 绘制草稿状态 ----
/** 草稿顶点（内部坐标 [x,y] + 时间戳；时间戳用于双击闭合时识别伴随产生的合成顶点） */
const draftPoints = ref<{ p: [number, number]; t: number }[]>([])
/** 橡皮筋连线（最后顶点 → 光标），mousemove 高频更新独立维护 */
let rubberLine: L.Polyline | null = null
const drawing = computed(() => !!props.drawMode)
/** 预览色与最终落图色一致：疆域紫 / 路径蓝（画出来的就是将要得到的） */
const drawColor = computed(() => (props.drawMode === 'territory' ? '#a855f7' : '#3b82f6'))

const { showToast } = useToast()
const { show: showConfirm } = useConfirmDialog()

const {
  locations,
  events,
  worldState,
  entities,
  relations,
  currentTime,
  locationsById,
  updateLocationCoords,
  renameLocation,
  deleteLocation,
  mapLayers,
  mapStrokes,
  createEvent,
  createEntity,
  updateEntityArchive,
} =
  useWorld()

const { mapEditMode, selectedLayerId, queueLayerPatch, removeLayer, reorderLayer, importImage, enterMapEdit, exitMapEdit, penColor, penWidth, eraserMode, canEditUndo, canEditRedo, addStroke, eraseStroke, clearAllStrokes } =
  useMapEdit()

const editingImages = computed(() => mapEditMode.value === 'images')
/** 任何沉浸编辑（疆域绘制 / 底图编辑）时数据层禁交互 */
const inEditMode = computed(() => !!props.drawMode || mapEditMode.value !== null)
const selectedLayer = computed(
  () => mapLayers.value.find((l) => l.id === selectedLayerId.value) || null,
)
const fileInputRef = ref<HTMLInputElement | null>(null)

// 图层显隐（右上工具条）
const layerVisible = ref({
  tracks: true,
  territory: true,
  events: true,
  locations: true,
  characters: true,
  relations: true,
})

const LAYER_TOGGLES: { key: keyof typeof layerVisible.value; icon: string; label: string }[] = [
  { key: 'characters', icon: 'users', label: '实体' },
  { key: 'relations', icon: 'link', label: '关系' },
  { key: 'locations', icon: 'map-pin', label: '地点' },
  { key: 'events', icon: 'flag', label: '事件' },
  { key: 'territory', icon: 'globe', label: '疆域' },
  { key: 'tracks', icon: 'arrows-right-left', label: '移动轨迹' },
]

const entitiesById = computed<
  Record<string, { name: string; entity_type: string; intro: string; importance?: number }>
>(() => {
  const m: Record<string, { name: string; entity_type: string; intro: string; importance?: number }> = {}
  for (const e of entities.value)
    m[e.id] = { name: e.name, entity_type: e.entity_type, intro: e.intro || '', importance: e.importance }
  return m
})

/** zoom 低于此值隐藏地点/人物名字标签（只留色点），避免密集重叠 */
const LABEL_ZOOM = 0
const showLabels = () => (map ? map.getZoom() >= LABEL_ZOOM : true)

// 内部坐标范围 0..1000
const BOUNDS = L.latLngBounds([[0, 0], [1000, 1000]])

/**
 * 空白舆图默认底图：手绘风地球世界平面（无标注——空白即未书写）。
 * 海岸线/湖泊/河流/国界取自 Natural Earth 50m 真实地理数据（等距圆柱投影，
 * scripts/make_blank_atlas.py 生成 → blankAtlas.ts），svgOverlay 绑在内部坐标上
 * 随地图缩放/平移；海岸线走 #wm-ink-soft 细毛边滤镜，纬线/经线 30° 淡虚线，
 * 南缘一道未知的南方大陆虚影。⚠ viewBox 与 BLANK_ATLAS_BOUNDS 必须同为 2:1，
 * 否则大陆纵向变形。
 */

/** 空白舆图 SVG 元素（⚠ Leaflet SVGOverlay 只接受元素——传字符串不会被解析成 DOM，addLayer 直接抛错） */
function makeBlankAtlasEl(): SVGElement {
  const el = document.createElementNS('http://www.w3.org/2000/svg', 'svg')
  el.setAttribute('xmlns', 'http://www.w3.org/2000/svg')
  el.setAttribute('viewBox', BLANK_ATLAS_VIEWBOX)
  el.innerHTML = BLANK_ATLAS_INNER
  return el
}

// 地点三类配色（空心环点，与实心人物点区分）
const LOC_KIND_COLOR: Record<string, string> = {
  point: '#7c6aad',
  region: '#10b981',
  route: '#60a5fa',
}

// ===== 底图：图片拼贴层（常驻最底）+ images 编辑态交互 =====

function layerBounds(l: { x: number; y: number; w: number; h: number }): L.LatLngBounds {
  return L.latLngBounds([
    [l.y - l.h / 2, l.x - l.w / 2],
    [l.y + l.h / 2, l.x + l.w / 2],
  ])
}

async function renderBaseImages() {
  if (!map || !baseImageLayer) return
  baseImageLayer.clearLayers()
  overlayMap.clear()
  for (const l of mapLayers.value) {
    const url = await resolveImageUrl(l.image_url)
    if (!map || !baseImageLayer) return // 卸载竞态
    const ov = L.imageOverlay(url, layerBounds(l), {
      opacity: l.opacity ?? 1,
      interactive: false,
    })
    overlayMap.set(l.id, ov)
    baseImageLayer.addLayer(ov)
  }
  renderBlankAtlas()
}

/** 空白舆图：无底图（图片+笔迹皆空）时铺手绘世界平面，有内容即撤 */
const blankAtlas = computed(() => mapLayers.value.length === 0 && mapStrokes.value.length === 0)
/** 浮动提示卡只在真正一片空白时出现（有了第一个名字，提示就完成使命） */
const showBlankCard = computed(
  () => blankAtlas.value && entities.value.length === 0 && locations.value.length === 0,
)
/** 图例只在图上真有可交互节点时出现（实体可能全未落位——对着空图教拖拽是误导） */
const hasVisibleNodes = computed(
  () =>
    entities.value.some((e) => !!entityDisplayPosition(e.id)) ||
    locations.value.some((l) => l.coord_x != null && l.coord_y != null),
)

/**
 * 空白舆图在内部坐标中的落位：lng 50..950 × lat 275..725 = 2:1，与 viewBox
 * 1000×500 严格同比（等距圆柱不变形），视野初始也框到这里。
 */
const BLANK_ATLAS_BOUNDS = L.latLngBounds([
  [275, 50],
  [725, 950],
])
/** 用户接管过视野（手动拖/缩）后，初始取景不再插手 */
let viewTouched = false
let framing = false // 程序化 fitBounds 期间置位，防止自己的取景被记成用户操作

function frameInitialView() {
  if (!map || viewTouched) return
  framing = true
  map.fitBounds(blankAtlas.value ? BLANK_ATLAS_BOUNDS : BOUNDS, { animate: false })
  framing = false
}

function renderBlankAtlas() {
  if (!map) return
  if (blankAtlas.value && !blankOverlay) {
    blankOverlay = L.svgOverlay(makeBlankAtlasEl(), BLANK_ATLAS_BOUNDS).addTo(map)
  } else if (!blankAtlas.value && blankOverlay) {
    map.removeLayer(blankOverlay)
    blankOverlay = null
  }
  frameInitialView()
}

/** images 编辑态：每图透明点击区（选中）+ 选中框/手柄 */
function renderEditImages() {
  if (!map || !editHitLayer || !editSelLayer) return
  editHitLayer.clearLayers()
  editSelLayer.clearLayers()
  geomRefs.clear()
  if (mapEditMode.value !== 'images') return
  for (const l of mapLayers.value) {
    const hit = L.rectangle(layerBounds(l), {
      stroke: false,
      fill: true,
      fillColor: '#7c6aad',
      fillOpacity: 0.05,
    })
    hit.on('click', (e) => {
      L.DomEvent.stopPropagation((e as unknown) as Event)
      selectedLayerId.value = l.id
    })
    editHitLayer.addLayer(hit)
  }
  renderSelection()
}

/** 选中图层的编辑框几何引用（拖动中直接 setBounds/setLatLng，不重建） */
const geomRefs = new Map<string, { rect: L.Rectangle; handles: L.Marker[] }>()

function makeCenterHandleIcon(): L.DivIcon {
  return L.divIcon({
    className: 'wm-handle-icon',
    html: '<div class="wm-handle wm-handle--center" title="拖动移动"></div>',
    iconSize: [0, 0],
  })
}
function makeCornerIcon(): L.DivIcon {
  return L.divIcon({
    className: 'wm-handle-icon',
    html: '<div class="wm-handle" title="拖动缩放"></div>',
    iconSize: [0, 0],
  })
}

function renderSelection() {
  if (!editSelLayer || !editHitLayer) return
  editSelLayer.clearLayers()
  geomRefs.clear()
  const l = selectedLayer.value
  if (!l || mapEditMode.value !== 'images') return
  const rect = L.rectangle(layerBounds(l), {
    color: '#7c6aad',
    weight: 1.5,
    dashArray: '6 4',
    fill: false,
    interactive: false,
  })
  editSelLayer.addLayer(rect)
  const handles: L.Marker[] = []

  // 中心手柄：拖动整图
  const center = L.marker([l.y, l.x], {
    icon: makeCenterHandleIcon(),
    draggable: true,
    zIndexOffset: 1000,
  })
  let last = { x: l.x, y: l.y, w: l.w, h: l.h }
  center.on('drag', (e) => {
    const ll = (e.target as L.Marker).getLatLng()
    last = { ...last, x: ll.lng, y: ll.lat }
    applyGeom(l.id, last)
  })
  center.on('dragend', () => {
    queueLayerPatch(props.bookId, l.id, { x: last.x, y: last.y })
    renderEditImages()
  })
  editSelLayer.addLayer(center)
  handles.push(center)

  // 4 角手柄：对角锚定自由缩放（w/h 独立，素材可拉伸）
  const anchors: [number, number][] = [
    [l.x + l.w / 2, l.y + l.h / 2], // 左上 → 锚右下
    [l.x - l.w / 2, l.y + l.h / 2], // 右上 → 锚左下
    [l.x - l.w / 2, l.y - l.h / 2], // 右下 → 锚左上
    [l.x + l.w / 2, l.y - l.h / 2], // 左下 → 锚右上
  ]
  const corners: [number, number][] = [
    [l.x - l.w / 2, l.y - l.h / 2],
    [l.x + l.w / 2, l.y - l.h / 2],
    [l.x + l.w / 2, l.y + l.h / 2],
    [l.x - l.w / 2, l.y + l.h / 2],
  ]
  corners.forEach(([cx, cy], i) => {
    const h = L.marker([cy, cx], {
      icon: makeCornerIcon(),
      draggable: true,
      zIndexOffset: 1000,
    })
    const [ax, ay] = anchors[i]
    h.on('drag', (e) => {
      const ll = (e.target as L.Marker).getLatLng()
      const nw = Math.max(20, Math.abs(ll.lng - ax))
      const nh = Math.max(20, Math.abs(ll.lat - ay))
      last = { x: (ax + ll.lng) / 2, y: (ay + ll.lat) / 2, w: nw, h: nh }
      applyGeom(l.id, last)
    })
    h.on('dragend', () => {
      queueLayerPatch(props.bookId, l.id, {
        x: last.x,
        y: last.y,
        w: last.w,
        h: last.h,
      })
      renderEditImages()
    })
    editSelLayer.addLayer(h)
    handles.push(h)
  })

  geomRefs.set(l.id, { rect, handles })
}

/** 拖动中本地几何跟随（overlay + 框 + 手柄）；数据与落库在 dragend */
function applyGeom(
  layerId: string,
  g: { x: number; y: number; w: number; h: number },
) {
  const b = layerBounds(g)
  overlayMap.get(layerId)?.setBounds(b)
  const refs = geomRefs.get(layerId)
  if (!refs) return
  refs.rect.setBounds(b)
  refs.handles[0]?.setLatLng([g.y, g.x])
  const cs: [number, number][] = [
    [g.x - g.w / 2, g.y - g.h / 2],
    [g.x + g.w / 2, g.y - g.h / 2],
    [g.x + g.w / 2, g.y + g.h / 2],
    [g.x - g.w / 2, g.y + g.h / 2],
  ]
  cs.forEach(([cx, cy], i) => refs.handles[i + 1]?.setLatLng([cy, cx]))
}

/** 以当前视图中心放置导入的图片（file 按钮与拖拽 drop 共用） */
async function importImageAtView(file: File) {
  if (!map) return
  const c = map.getCenter()
  const b = map.getBounds()
  const viewW = Math.abs(b.getEast() - b.getWest()) || 600
  await importImage(props.bookId, file, c.lng, c.lat, viewW)
}

async function onFile(e: Event) {
  const f = (e.target as HTMLInputElement).files?.[0]
  if (!f) return
  try {
    await importImageAtView(f)
    showToast('图片已导入——拖中心移动，拖角缩放', 'success')
  } catch (err) {
    showToast('导入失败：' + ((err as Error)?.message || '未知错误'), 'error')
  } finally {
    if (fileInputRef.value) fileInputRef.value.value = ''
  }
}

function removeSelected() {
  if (selectedLayer.value) removeLayer(props.bookId, selectedLayer.value.id)
}

function toggleEdit(mode: 'images' | 'draw') {
  if (mapEditMode.value === mode) exitMapEdit()
  else enterMapEdit(mode)
}

// ===== 底图：手绘笔迹（canvas 覆盖层，rAF 全量重绘同步地图）=====

// ⚠ canvas 2D 的 strokeStyle 按 CSS <color> 解析，不支持 var()（非法值被静默忽略，
// 画成上一支笔的颜色，且 var() 字符串会随 addStroke 落库）——画笔必须用固定 hex，
// 勿换主题 token（token 分主题变色，也不适合作为入库数据的颜色语义）
const PEN_COLORS = ['#6b5537', '#3f6212', '#1d4ed8', '#475569', '#b91c1c', '#1c1917']
// 渲染侧兜底：UX 重构期曾有 'var(--info)'/'var(--danger)' 入库，归一回退色
// （只修显示不改库；redo 按原串重建也照样归一）
const _STROKE_COLOR_FIX: Record<string, string> = { 'var(--info)': '#1d4ed8', 'var(--danger)': '#b91c1c' }
const PEN_SIZES = [2, 4, 8]

const strokeCanvasRef = ref<HTMLCanvasElement | null>(null)
/** 正在画的笔（内部坐标，实时预览；pointerup 时落库） */
const draftStroke = ref<[number, number][]>([])
const drawingMap = computed(() => mapEditMode.value === 'draw')
let painting = false
let strokeRafId: number | null = null

function scheduleStrokeRedraw() {
  if (strokeRafId !== null) return
  strokeRafId = requestAnimationFrame(() => {
    strokeRafId = null
    drawStrokes()
  })
}

function drawStrokes() {
  const cv = strokeCanvasRef.value
  if (!cv || !map) return
  const dpr = window.devicePixelRatio || 1
  const w = cv.clientWidth
  const h = cv.clientHeight
  if (w === 0 || h === 0) return
  const pw = Math.round(w * dpr)
  const ph = Math.round(h * dpr)
  if (cv.width !== pw || cv.height !== ph) {
    cv.width = pw
    cv.height = ph
  }
  const ctx = cv.getContext('2d')
  if (!ctx) return
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
  ctx.clearRect(0, 0, w, h)
  // 已存笔迹 + 正在画的草稿笔
  const all: { color: string; width: number; points: [number, number][] }[] = [
    ...mapStrokes.value.map((s) => ({ color: s.color, width: s.width, points: s.points as [number, number][] })),
  ]
  if (draftStroke.value.length > 1) {
    all.push({ color: penColor.value, width: penWidth.value, points: draftStroke.value })
  }
  ctx.lineCap = 'round'
  ctx.lineJoin = 'round'
  for (const s of all) {
    if (s.points.length < 2) continue
    const pts = s.points.map(([x, y]) => {
      const cp = map!.latLngToContainerPoint([y, x])
      return [cp.x, cp.y] as [number, number]
    })
    ctx.strokeStyle = _STROKE_COLOR_FIX[s.color] ?? s.color
    ctx.lineWidth = s.width
    ctx.beginPath()
    ctx.moveTo(pts[0][0], pts[0][1])
    // 中点二次贝塞尔平滑
    for (let i = 1; i < pts.length - 1; i++) {
      const mx = (pts[i][0] + pts[i + 1][0]) / 2
      const my = (pts[i][1] + pts[i + 1][1]) / 2
      ctx.quadraticCurveTo(pts[i][0], pts[i][1], mx, my)
    }
    ctx.lineTo(pts[pts.length - 1][0], pts[pts.length - 1][1])
    ctx.stroke()
  }
}

function canvasToInternal(e: PointerEvent): [number, number] | null {
  const cv = strokeCanvasRef.value
  if (!cv || !map) return null
  const r = cv.getBoundingClientRect()
  const cp = L.point(e.clientX - r.left, e.clientY - r.top)
  const ll = map.containerPointToLatLng(cp)
  return [ll.lng, ll.lat]
}

function onStrokeDown(e: PointerEvent) {
  if (mapEditMode.value !== 'draw') return
  const p = canvasToInternal(e)
  if (!p) return
  ;(e.target as HTMLElement).setPointerCapture?.(e.pointerId)
  painting = true
  if (eraserMode.value) {
    eraseAtPoint(p)
  } else {
    draftStroke.value = [p]
    scheduleStrokeRedraw()
  }
}
function onStrokeMove(e: PointerEvent) {
  if (!painting || mapEditMode.value !== 'draw') return
  const p = canvasToInternal(e)
  if (!p || !map) return
  if (eraserMode.value) {
    eraseAtPoint(p)
    return
  }
  const last = draftStroke.value[draftStroke.value.length - 1]
  if (!last) return
  // 屏幕空间 >1.5px 才收点（降密度）
  const a = map.latLngToContainerPoint([last[1], last[0]])
  const b = map.latLngToContainerPoint([p[1], p[0]])
  if (a.distanceTo(b) > 1.5) {
    draftStroke.value = [...draftStroke.value, p]
    scheduleStrokeRedraw()
  }
}
async function onStrokeUp() {
  if (!painting) return
  painting = false
  const pts = draftStroke.value
  draftStroke.value = []
  scheduleStrokeRedraw()
  if (pts.length >= 2) {
    try {
      await addStroke(props.bookId, penColor.value, penWidth.value, pts)
    } catch (err) {
      showToast('笔迹保存失败：' + ((err as Error)?.message || ''), 'error')
    }
  }
}

/** 橡皮：屏幕空间点到各笔折线距离 < 阈值 → 删除命中的那笔 */
function eraseAtPoint(p: [number, number]) {
  if (!map) return
  const cp = map.latLngToContainerPoint([p[1], p[0]])
  for (const s of [...mapStrokes.value].reverse()) {
    let hit = false
    const pts = s.points as [number, number][]
    for (let i = 0; i < pts.length - 1 && !hit; i++) {
      const a = map.latLngToContainerPoint([pts[i][1], pts[i][0]])
      const b = map.latLngToContainerPoint([pts[i + 1][1], pts[i + 1][0]])
      if (distToSeg(cp, a, b) < 10 + s.width / 2) hit = true
    }
    if (hit) {
      eraseStroke(props.bookId, s.id)
      return
    }
  }
}

/** 地点子级索引（marker 内部构造记号 / popup 计数行共用） */
const locChildren = computed(() => childrenIndex(locations.value))

function renderMarkers() {
  if (!map || !markerLayer) return
  markerLayer.clearLayers()
  if (!layerVisible.value.locations) return
  const withLabel = showLabels()
  // 有子级标记（内部构造提示）：环点内加一点
  const locKids = locChildren.value
  for (const loc of locations.value) {
    // 上图权 = parent_id IS NULL（docs/location-interior.md 渲染契约）：内部构造只进详情抽屉
    if (loc.parent_id) continue
    if (loc.coord_x == null || loc.coord_y == null) continue
    const color = LOC_KIND_COLOR[loc.kind] || LOC_KIND_COLOR.point
    const hasInner = (locKids.get(loc.id) || []).length > 0
    const icon = L.divIcon({
      className: 'wm-loc-icon',
      html: `<div class="wm-loc${hasInner ? ' wm-loc--inner' : ''}${props.highlightLocationId === loc.id ? ' wm-loc--hl' : ''}" style="--c:${color}"><span class="wm-loc-ring"></span>${
        hasInner ? '<span class="wm-loc-dot"></span>' : ''
      }${
        withLabel ? `<span class="wm-loc-name">${esc(loc.name)}</span>` : ''
      }</div>`,
      iconSize: [0, 0],
    })
    // draggable：拖拽微调位置（松手落库，不进 undo）；绘制期禁用交互让点击穿透到地图
    const m = L.marker([loc.coord_y, loc.coord_x], {
      icon,
      title: loc.name,
      draggable: !inEditMode.value,
      interactive: !inEditMode.value,
    })
    m.on('dragend', () => {
      const ll = m.getLatLng()
      updateLocationCoords(props.bookId, loc.id, ll.lng, ll.lat)
    })
    // 点击回指（popup 照常开；父级据此联动地点面板条目）
    m.on('click', () => emit('location-highlight', loc.id))
    m.bindPopup(buildLocPopupHtml(loc))
    markerLayer.addLayer(m)
  }
}

/** 地点 popup：名字 + 类型/简介 + 内部构造行 + 详情/改名/删除（事件在 popupopen 委托绑定） */
function buildLocPopupHtml(loc: WorldLocation): string {
  const innerCount = (locChildren.value.get(loc.id) || []).length
  return (
    `<div class="wm-pop-title">${esc(loc.name)}</div>` +
    `<span class="wm-pop-sub">${esc(loc.kind)}</span>` +
    (loc.intro ? `<div class="wm-pop-intro">${esc(loc.intro)}</div>` : '') +
    (innerCount ? `<div class="wm-pop-inner">内部构造 ${innerCount} ›</div>` : '') +
    `<div class="wm-pop-edit" data-loc-id="${loc.id}">` +
    `<input class="wm-pop-input" data-loc-name value="${esc(loc.name)}" />` +
    `<button class="wm-pop-btn" data-act="detail" title="地点详情与内部构造">详情</button>` +
    `<button class="wm-pop-btn" data-act="save" title="保存改名">改名</button>` +
    `<button class="wm-pop-btn wm-pop-btn--danger" data-act="del" title="删除地点">删除</button>` +
    `</div>`
  )
}

/** move 轨迹线：完成的=点画墨线；在途=青墨虚线流动（行军中） */
let lastTrackSig = ''

/** 轨迹层帧频门控签名：可见 move 集 + 在途样式位——两者只在游标跨过事件
 *  time_start/time_end 边界的离散时刻变化，连续滑动帧间恒等（门控跳过重建） */
function trackSignature(): string {
  const t = currentTime.value
  const parts: string[] = []
  for (const e of events.value) {
    if (e.event_type !== 'move' || e.time_start > t) continue
    if ((((e.payload as { path?: unknown })?.path) as unknown[] | undefined)?.length < 2) continue
    parts.push(`${e.id}:${t < e.time_end ? 1 : 0}`)
  }
  return parts.join('|')
}

function renderTracks() {
  if (!map || !trackLayer) return
  trackLayer.clearLayers()
  if (!layerVisible.value.tracks) return
  const t = currentTime.value
  for (const e of events.value) {
    if (e.event_type !== 'move') continue
    if (e.time_start > t) continue // 还没发生
    const path = (e.payload.path as [number, number][] | undefined) || []
    if (path.length < 2) continue
    const latlngs = path.map(([x, y]) => [y, x] as [number, number])
    const inTransit = t < e.time_end
    const line = L.polyline(
      latlngs,
      inTransit
        ? {
            color: '#3f6f8f',
            weight: 2.6,
            opacity: 0.9,
            dashArray: '9 7',
            lineCap: 'round',
            className: 'wm-track-flow',
            interactive: !inEditMode.value,
          }
        : {
            color: '#6b5a44',
            weight: 2.2,
            opacity: 0.5,
            dashArray: '1 6',
            lineCap: 'round',
            className: 'wm-track-ink',
            interactive: !inEditMode.value,
          },
    )
    trackLayer.addLayer(line)
  }
  lastTrackSig = trackSignature()
}

/** 帧频门控（游标拖动/播放）：签名不变=可见轨迹与在途样式都没变，跳过重建 */
function syncTracksOnFrame() {
  if (!map || !trackLayer || !layerVisible.value.tracks) return
  const sig = trackSignature()
  if (sig === lastTrackSig) return
  renderTracks()
}

// ===== 实体层（单一画布）：所有实体统一上地图 =====
// 位置解析优先级：事件推演位置（人物 state）/ 疆域质心（势力）→ 画布锚位（作者摆位）。
// 拖拽语义分流：有故事的角色受历史约束（拖=录 move 事件，可撤销）；
// 没故事的（无事件角色/资产/无疆域势力）自由摆放（拖=移画布锚位）。
//
// P0 性能治理（2026-09-14 世界页审计）：marker 实例跨帧复用——renderEntities 仍是
// 全量重建入口（数据增删改/缩放/图层开关/高亮走它）；新增 syncEntitiesOnFrame 供
// 游标拖动的帧频路径：只 setLatLng 挪位、moving/生死翻转才换图标或增删单实例，
// 不再每帧销毁重建 DOM 节点（move 沿路径插值的顺滑移动 100% 保持——每帧照常挪位）。

const entityMarkers = new Map<string, L.Marker>()
/** 帧差分快照：位置变了挪 marker；moving 翻转换图标；derived 翻转（故事性变化，
 *  拖拽语义随变）换单实例重建——语义类别不宜动态改绑，重建单枚成本可忽略 */
const entityMeta = new Map<string, { x: number; y: number; moving: boolean; derived: boolean }>()
const highlightEntityId = ref<string | null>(null)

interface EntityDisplay {
  x: number
  y: number
  derived: boolean // true=事态推演位置；false=画布锚位
}

type CharState = (typeof worldState.value)['character_states'][number]
type TerritoryState = (typeof worldState.value)['territory_states'][number]

/** 帧路径预建索引：renderRelations/sync 系列共用，免逐实体 O(states) 线性扫 */
function charStateMap(): Map<string, CharState> {
  return new Map(worldState.value.character_states.map((c) => [c.entity_id, c]))
}
function territoryStateMap(): Map<string, TerritoryState> {
  return new Map(worldState.value.territory_states.map((t) => [t.faction_id, t]))
}

function entityDisplayPosition(
  entId: string,
  csMap: Map<string, CharState> = charStateMap(),
  tsMap: Map<string, TerritoryState> = territoryStateMap(),
): EntityDisplay | null {
  const cs = csMap.get(entId)
  if (cs && !cs.alive) return null // 死者不显示（史书只记生前轨迹；侧栏/抽屉仍可达）
  if (cs?.position) return { x: cs.position[0], y: cs.position[1], derived: true }
  const ts = tsMap.get(entId)
  if (ts?.polygon?.length) {
    const c = centroid(ts.polygon as [number, number][])
    if (c) return { x: c[0], y: c[1], derived: true }
  }
  const ent = entities.value.find((e) => e.id === entId)
  if (ent?.canvas_x != null && ent?.canvas_y != null) {
    return { x: ent.canvas_x, y: ent.canvas_y, derived: false }
  }
  return null
}

const NODE_COLOR: Record<string, string> = {
  character: 'var(--warn)',
  faction: '#10b981',
  asset: '#c9a227',
}

/** 高亮的「关联圈」：与高亮实体有关系的伙伴不暗（null=无高亮，全员正常亮） */
function entityRelatedSet(): Set<string> | null {
  const hl = highlightEntityId.value
  if (!hl) return null
  const related = new Set<string>()
  for (const r of relations.value) {
    if (r.source_entity_id === hl) related.add(r.target_entity_id)
    if (r.target_entity_id === hl) related.add(r.source_entity_id)
  }
  return related
}

function buildEntityIcon(
  ent: { id: string; name: string; entity_type: string; importance?: number },
  moving: boolean,
  related: Set<string> | null,
): L.DivIcon {
  const hl = highlightEntityId.value
  const t = ent.entity_type
  const color = NODE_COLOR[t] || NODE_COLOR.character
  const star = (ent.importance ?? 1) >= 7
  const dimmed = !!hl && ent.id !== hl && !related?.has(ent.id)
  const withLabel = showLabels()
  return L.divIcon({
    className: 'wm-char-icon',
    html: `<div class="wm-node wm-node--${t}${moving ? ' wm-char--moving' : ''}${
      star ? ' wm-char--star' : ''
    }${dimmed ? ' wm-node--dim' : ''}" style="--c:${color}"><span class="wm-node-head"></span>${
      withLabel ? `<span class="wm-char-name">${esc(ent.name)}</span>` : ''
    }</div>`,
    iconSize: [0, 0],
  })
}

function createEntityMarker(
  ent: (typeof entities.value)[number],
  pos: EntityDisplay,
  related: Set<string> | null,
  csMap: Map<string, CharState>,
): L.Marker {
  const moving = !!csMap.get(ent.id)?.label?.includes('在途')
  const icon = buildEntityIcon(ent, moving, related)
  const [x, y] = [pos.x, pos.y]
  const t = ent.entity_type
  // 有疆域的势力节点不可拖（疆域几何是事实）；其余可拖
  const draggable = !inEditMode.value && !(pos.derived && t === 'faction')
  const m = L.marker([y, x], { icon, zIndexOffset: 500, draggable, interactive: !inEditMode.value })
  entityMarkers.set(ent.id, m)
  entityMeta.set(ent.id, { x, y, moving, derived: pos.derived })

  m.on('click', () => {
    if (inEditMode.value) return
    highlightEntityId.value = ent.id
    emit('entity-click', ent.id)
  })

  // ⇧+按下 = 建关系手势起点（临时禁用拖拽，松手恢复）
  m.on('mousedown', (e) => {
    const oe = e.originalEvent as MouseEvent & { shiftKey?: boolean }
    if (!oe.shiftKey || inEditMode.value) return
    L.DomEvent.stopPropagation(e as unknown as Event)
    e.target.dragging?.disable()
    startLink(ent.id, e)
  })

  if (pos.derived && t === 'character') {
    // 有故事的角色：拖拽松手 = 在游标时刻录 move 事件（直接创建，可撤销）
    let from: L.LatLng | null = null
    m.on('dragstart', (e) => {
      from = (e.target as L.Marker).getLatLng()
    })
    m.on('dragend', async (e) => {
      const to = (e.target as L.Marker).getLatLng()
      if (!from || (Math.abs(to.lng - from.lng) < 2 && Math.abs(to.lat - from.lat) < 2)) return
      await createEvent(props.bookId, {
        event_type: 'move',
        time_start: currentTime.value,
        time_end: currentTime.value,
        payload: {
          character_ids: [ent.id],
          path: [
            [from.lng, from.lat],
            [to.lng, to.lat],
          ],
        },
      })
      showToast(`已记录「${ent.name}」的移动（游标时刻）· Ctrl+Z 撤销`, 'success')
      from = null
    })
  } else if (draggable) {
    // 没故事的实体：拖拽 = 移画布锚位（轻量落库）
    m.on('dragend', async (e) => {
      const to = (e.target as L.Marker).getLatLng()
      await updateEntityArchive(props.bookId, ent.id, { canvas_x: to.lng, canvas_y: to.lat })
    })
  }
  return m
}

function removeEntityMarker(entId: string) {
  const m = entityMarkers.get(entId)
  if (m) entityLayer?.removeLayer(m)
  entityMarkers.delete(entId)
  entityMeta.delete(entId)
}

function renderEntities() {
  if (!map || !entityLayer) return
  entityLayer.clearLayers()
  entityMarkers.clear()
  entityMeta.clear()
  if (!layerVisible.value.characters) return
  const related = entityRelatedSet()
  const csMap = charStateMap()
  const tsMap = territoryStateMap()
  for (const ent of entities.value) {
    const pos = entityDisplayPosition(ent.id, csMap, tsMap)
    if (!pos) continue
    entityLayer.addLayer(createEntityMarker(ent, pos, related, csMap))
  }
}

/** 帧频差分（游标拖动/播放）：挪位为主，增删/换图标为辅——严禁 clearLayers */
function syncEntitiesOnFrame() {
  if (!map || !entityLayer || !layerVisible.value.characters) return
  const related = entityRelatedSet()
  const csMap = charStateMap()
  const tsMap = territoryStateMap()
  const seen = new Set<string>()
  for (const ent of entities.value) {
    const pos = entityDisplayPosition(ent.id, csMap, tsMap)
    if (!pos) continue // 死亡/无位：下方统一按未见清理
    seen.add(ent.id)
    const meta = entityMeta.get(ent.id)
    const m = entityMarkers.get(ent.id)
    if (!m || !meta) {
      entityLayer.addLayer(createEntityMarker(ent, pos, related, csMap))
      continue
    }
    // 拖拽语义类别翻转（无故事↔有故事）→ 单实例重建换绑 handler
    if (meta.derived !== pos.derived) {
      removeEntityMarker(ent.id)
      entityLayer.addLayer(createEntityMarker(ent, pos, related, csMap))
      continue
    }
    const moving = !!csMap.get(ent.id)?.label?.includes('在途')
    if (meta.moving !== moving) {
      m.setIcon(buildEntityIcon(ent, moving, related))
      meta.moving = moving
    }
    if (meta.x !== pos.x || meta.y !== pos.y) {
      m.setLatLng([pos.y, pos.x])
      meta.x = pos.x
      meta.y = pos.y
    }
  }
  // 消失的：死亡翻转/删除/失去位置
  for (const entId of [...entityMarkers.keys()]) {
    if (!seen.has(entId)) removeEntityMarker(entId)
  }
}

// ===== 关系层：活跃边画在两端实体当前位置之间，随游标演变 =====
// P0 性能治理（2026-09-14）：polyline 实例跨帧复用——帧频路径 syncRelationsOnFrame
// 只 setLatLngs 随端点伸缩（端点=实体 marker 同款差分挪位），激活/失活增删单线；
// 生长动画语义原样保留（born 仅对帧路径中新激活的边为真）。

let prevActiveRelIds = new Set<string>()
const relationLines = new Map<string, L.Polyline>()

function buildRelationLine(
  r: WorldRelation,
  a: EntityDisplay,
  b: EntityDisplay,
  born: boolean,
): L.Polyline {
  const meta = relationTypeMeta(r.relation_type)
  const hl = highlightEntityId.value
  // 三点轻弧（中点垂直偏移，随端点移动伸缩）
  const { x: cx, y: cy } = arcControlPoint(a, b)
  const dimmed = !!hl && r.source_entity_id !== hl && r.target_entity_id !== hl
  const line = L.polyline(
    [
      [a.y, a.x],
      [cy, cx],
      [b.y, b.x],
    ] as [number, number][],
    {
      color: meta.color,
      weight: 2,
      opacity: dimmed ? 0.1 : 0.72,
      dashArray: r.static ? undefined : '6 5',
      className: born ? 'wm-rel wm-rel-born' : 'wm-rel',
      interactive: !inEditMode.value,
    },
  )
  const label = r.label || meta.label
  line.bindTooltip(`${esc(label)}${r.static ? '' : ' · 事件锚定'}`, { direction: 'top', sticky: true })
  line.on('click', (e) => {
    if (inEditMode.value) return
    L.DomEvent.stopPropagation(e as unknown as Event)
    openRelationForm(r, e.originalEvent as MouseEvent)
  })
  return line
}

function renderRelations() {
  if (!map || !relationLayer) return
  relationLayer.clearLayers()
  relationLines.clear()
  if (!layerVisible.value.relations) {
    prevActiveRelIds = new Set()
    return
  }
  const activeIds = new Set<string>()
  for (const rs of worldState.value.relation_states) if (rs.active) activeIds.add(rs.relation_id)
  for (const r of relations.value) {
    if (!activeIds.has(r.id)) continue
    const a = entityDisplayPosition(r.source_entity_id)
    const b = entityDisplayPosition(r.target_entity_id)
    if (!a || !b) continue
    const born = prevActiveRelIds.size > 0 && !prevActiveRelIds.has(r.id) // 激活瞬间生长
    const line = buildRelationLine(r, a, b, born)
    relationLines.set(r.id, line)
    relationLayer.addLayer(line)
  }
  prevActiveRelIds = activeIds
}

/** 帧频差分（游标拖动/播放）：随实体端点 setLatLngs 伸缩，激活增/失活删——严禁 clearLayers */
function syncRelationsOnFrame() {
  if (!map || !relationLayer) return
  if (!layerVisible.value.relations) {
    if (relationLines.size) {
      relationLayer.clearLayers()
      relationLines.clear()
      prevActiveRelIds = new Set()
    }
    return
  }
  const activeIds = new Set<string>()
  for (const rs of worldState.value.relation_states) if (rs.active) activeIds.add(rs.relation_id)
  for (const [rid, line] of [...relationLines]) {
    if (!activeIds.has(rid)) {
      relationLayer.removeLayer(line)
      relationLines.delete(rid)
    }
  }
  const csMap = charStateMap()
  const tsMap = territoryStateMap()
  for (const r of relations.value) {
    if (!activeIds.has(r.id)) continue
    const a = entityDisplayPosition(r.source_entity_id, csMap, tsMap)
    const b = entityDisplayPosition(r.target_entity_id, csMap, tsMap)
    if (!a || !b) {
      const line = relationLines.get(r.id)
      if (line) {
        relationLayer.removeLayer(line)
        relationLines.delete(r.id)
      }
      continue
    }
    let line = relationLines.get(r.id)
    if (!line) {
      const born = prevActiveRelIds.size > 0 && !prevActiveRelIds.has(r.id) // 激活瞬间生长
      line = buildRelationLine(r, a, b, born)
      relationLines.set(r.id, line)
      relationLayer.addLayer(line)
    } else {
      const { x: cx, y: cy } = arcControlPoint(a, b)
      line.setLatLngs([
        [a.y, a.x],
        [cy, cx],
        [b.y, b.x],
      ] as [number, number][])
    }
  }
  prevActiveRelIds = activeIds
}

// ===== ⇧+拖线建关系（脑图手势平移到地图）=====

interface DraftRelationForm {
  x: number
  y: number
  sourceId: string
  targetId: string
  existing: WorldRelation | null
}
const draftForm = ref<DraftRelationForm | null>(null)
const linkRubber = ref<{ x1: number; y1: number; x2: number; y2: number } | null>(null)
let linking: { sourceId: string; marker: L.Marker } | null = null

function startLink(sourceId: string, e: { target: L.Marker }) {
  linking = { sourceId, marker: e.target }
  const p = map?.latLngToContainerPoint(e.target.getLatLng())
  if (p) linkRubber.value = { x1: p.x, y1: p.y, x2: p.x, y2: p.y }
}

function onLinkPointerMove(e: PointerEvent) {
  if (!linking || !linkRubber.value || !containerRef.value) return
  const r = containerRef.value.getBoundingClientRect()
  linkRubber.value.x2 = e.clientX - r.left
  linkRubber.value.y2 = e.clientY - r.top
}

function onLinkPointerUp(e: PointerEvent) {
  if (!linking) return
  const { sourceId, marker } = linking
  linking = null
  linkRubber.value = null
  marker.dragging?.enable()
  if (!map || !containerRef.value) return
  // 命中最近的其他实体节点（容器坐标 26px 内）
  const r = containerRef.value.getBoundingClientRect()
  const px = e.clientX - r.left
  const py = e.clientY - r.top
  const candidates: Array<[string, { x: number; y: number }]> = []
  for (const [id, mk] of entityMarkers) {
    if (id === sourceId) continue
    candidates.push([id, map.latLngToContainerPoint(mk.getLatLng())])
  }
  const bestId = pickNearest(px, py, candidates, 26)
  if (bestId) {
    const a = entityDisplayPosition(sourceId)
    const b = entityDisplayPosition(bestId)
    const ax = a ? (map.latLngToContainerPoint([a.y, a.x]).x) : px
    const ay = a ? (map.latLngToContainerPoint([a.y, a.x]).y) : py
    const bx = b ? (map.latLngToContainerPoint([b.y, b.x]).x) : px
    const by = b ? (map.latLngToContainerPoint([b.y, b.x]).y) : py
    openRelationFormAt((ax + bx) / 2, (ay + by) / 2, sourceId, bestId, null)
  }
}

function clampFormPos(x: number, y: number): { x: number; y: number } {
  const w = containerRef.value?.clientWidth || 800
  const h = containerRef.value?.clientHeight || 600
  return {
    x: Math.min(Math.max(x - 150, 8), Math.max(8, w - 308)),
    y: Math.min(Math.max(y + 10, 8), Math.max(8, h - 300)),
  }
}

function openRelationForm(r: WorldRelation, oe: MouseEvent) {
  if (!containerRef.value) return
  const rect = containerRef.value.getBoundingClientRect()
  openRelationFormAt(
    oe.clientX - rect.left,
    oe.clientY - rect.top,
    r.source_entity_id,
    r.target_entity_id,
    r,
  )
}

function openRelationFormAt(
  x: number,
  y: number,
  sourceId: string,
  targetId: string,
  existing: WorldRelation | null,
) {
  const p = clampFormPos(x, y)
  draftForm.value = { x: p.x, y: p.y, sourceId, targetId, existing }
}

// ===== 右键空白：在此建实体（地图成为唯一编辑画布）=====

const ctxMenu = ref<{ x: number; y: number; ix: number; iy: number } | null>(null)
const createForm = ref<{ x: number; y: number; ix: number; iy: number; name: string; type: 'character' | 'faction' | 'asset' } | null>(null)

function onMapContextMenu(e: L.LeafletMouseEvent) {
  if (inEditMode.value || props.pickingMode || props.drawMode) return
  L.DomEvent.preventDefault(e as unknown as Event)
  ctxMenu.value = { x: e.containerPoint.x, y: e.containerPoint.y, ix: e.latlng.lng, iy: e.latlng.lat }
  createForm.value = null
}

function ctxCreateEntity() {
  const c = ctxMenu.value
  if (!c) return
  ctxMenu.value = null
  createForm.value = { x: c.x, y: c.y, ix: c.ix, iy: c.iy, name: '', type: 'character' }
}

async function submitCreateEntity() {
  const f = createForm.value
  if (!f || !f.name.trim()) return
  await createEntity(props.bookId, {
    entity_type: f.type,
    name: f.name.trim(),
    canvas_x: f.ix,
    canvas_y: f.iy,
  })
  const t = f.type === 'character' ? '角色' : f.type === 'faction' ? '势力' : '资产'
  showToast(`${t}「${f.name.trim()}」已建立`, 'success')
  createForm.value = null
}

function renderTerritory() {
  if (!map || !territoryLayer) return
  // 时刻大跳（点章节锚/事件点）→ 疆域平滑形变；连续小步（播放/拖游标）→ 即时贴合
  const jump = Math.abs(currentTime.value - lastStateTime) > 45
  lastStateTime = currentTime.value
  if (!layerVisible.value.territory) {
    territoryLayer.clearLayers()
    territoryPolys.clear()
    return
  }
  const desired = new Map(
    worldState.value.territory_states.map((ts) => [ts.faction_id, (ts.polygon || []) as [number, number][]]),
  )
  // 消失的疆域移除
  for (const [fid, entry] of [...territoryPolys]) {
    if (!desired.has(fid)) {
      territoryLayer.removeLayer(entry.poly)
      territoryPolys.delete(fid)
    }
  }
  for (const [fid, polygon] of desired) {
    if (!polygon || polygon.length < 3) continue
    const existing = territoryPolys.get(fid)
    if (!existing) {
      const poly = L.polygon(
        polygon.map(([x, y]) => [y, x] as [number, number]),
        TERRITORY_STYLE(),
      )
      const ent = entitiesById.value[fid]
      poly.bindPopup(`<b>${esc(ent?.name || fid)}</b><br/><span class="wm-pop-sub">疆域</span>`)
      territoryLayer.addLayer(poly)
      territoryPolys.set(fid, { poly, pts: polygon })
    } else if (jump) {
      morphPolygon(existing, polygon)
    } else {
      existing.pts = polygon
      existing.poly.setLatLngs(polygon.map(([x, y]) => [y, x] as [number, number]))
    }
  }
}

/** 疆域样式：墨迹晕染（古卷水彩——SVG 位移滤镜给边界毛边，见模板 wm-ink defs） */
function TERRITORY_STYLE(): L.PolylineOptions {
  return {
    color: '#6d5a86',
    weight: 2,
    opacity: 0.8,
    dashArray: '10 7',
    lineJoin: 'round' as const,
    fillColor: '#8b6f9e',
    fillOpacity: 0.13,
    interactive: !inEditMode.value,
    className: 'wm-territory',
  }
}

// ===== 疆域 morph（顶点数不同时按弧长重采样到相同 N 再插值）=====

interface TerritoryEntry {
  poly: L.Polygon
  pts: [number, number][]
  raf?: number
}
const territoryPolys = new Map<string, TerritoryEntry>()
let lastStateTime = 0

function morphPolygon(entry: TerritoryEntry, targetPts: [number, number][]) {
  const n = Math.max(16, Math.max(entry.pts.length, targetPts.length))
  const from = resampleRing(entry.pts, n)
  const to = resampleRing(targetPts, n)
  if (from.length !== n || to.length !== n) {
    entry.pts = targetPts
    entry.poly.setLatLngs(targetPts.map(([x, y]) => [y, x] as [number, number]))
    return
  }
  if (entry.raf) cancelAnimationFrame(entry.raf)
  const t0 = performance.now()
  const dur = 380
  const step = (now: number) => {
    const p = Math.min(1, (now - t0) / dur)
    const e = 1 - Math.pow(1 - p, 3) // easeOutCubic
    const cur = from.map(
      (f, i) =>
        [f[0] + (to[i][0] - f[0]) * e, f[1] + (to[i][1] - f[1]) * e] as [number, number],
    )
    entry.poly.setLatLngs(cur.map(([x, y]) => [y, x] as [number, number]))
    if (p < 1) entry.raf = requestAnimationFrame(step)
    else {
      entry.raf = undefined
      entry.pts = targetPts
    }
  }
  entry.raf = requestAnimationFrame(step)
}

// ===== 事件涟漪：游标前扫过的事件在其地点绽放类型色涟漪（静止时无动画）=====

let ripplePrevT: number | null = null

function spawnRipples(t: number) {
  if (!map || !rippleLayer) return
  if (ripplePrevT == null || t < ripplePrevT) {
    ripplePrevT = t // 回拖不重放涟漪
    return
  }
  const crossed = events.value.filter((e) => e.time_start > ripplePrevT! && e.time_start <= t)
  ripplePrevT = t
  for (const e of crossed) {
    const pt = eventPoint(e, locationsById.value)
    if (!pt) continue
    const color = EVENT_TYPE_COLOR[e.event_type] || 'var(--text-muted)'
    const big =
      e.event_type === 'battle' || e.event_type === 'territory_change' || e.event_type === 'war_declare'
    const icon = L.divIcon({
      className: 'wm-ripple-icon',
      html: `<span class="wm-ripple${big ? ' wm-ripple--big' : ''}" style="--c:${color}"></span>`,
      iconSize: [0, 0],
    })
    const m = L.marker([pt[1], pt[0]], { icon, interactive: false, zIndexOffset: 900 })
    rippleLayer.addLayer(m)
    setTimeout(() => rippleLayer?.removeLayer(m), 1500)
  }
}

/**
 * 事件标记层（本页核心红利）：time_start ≤ 当前时刻、可定位的历史事件
 * 以类型色小菱形标注在地图上——拖时间轴，历史逐帧浮现。
 * P0 性能治理（2026-09-14）：marker 实例按事件 id 复用——帧频路径
 * syncEventMarkersOnFrame 按「可见集」增删差分（前扫浮现/回拖消失），
 * 不再每帧销毁重建全部 divIcon+popup。
 */
const eventMarkers = new Map<string, L.Marker>()

function createEventMarker(e: WorldEvent): L.Marker | null {
  const pt = eventPoint(e, locationsById.value)
  if (!pt) return null
  const color = EVENT_TYPE_COLOR[e.event_type] || 'var(--text-muted)'
  const label = eventDisplayName(e)
  const icon = L.divIcon({
    className: 'wm-evt-icon',
    html: `<span class="wm-evt" style="--c:${color}" title="${esc(label)}"></span>`,
    iconSize: [0, 0],
  })
  const m = L.marker([pt[1], pt[0]], { icon, zIndexOffset: 200, interactive: !inEditMode.value })
  const note = stripPointFromNote(e.note)
  m.bindPopup(
    `<b>${esc(label)}</b> <span class="wm-pop-sub">${esc(formatTime(e.time_start))}</span>${
      note ? `<br/>${esc(note)}` : ''
    }`,
  )
  return m
}

function renderEventMarkers() {
  if (!map || !eventLayer) return
  eventLayer.clearLayers()
  eventMarkers.clear()
  if (!layerVisible.value.events) return
  const t = currentTime.value
  for (const e of events.value) {
    if (e.time_start > t) continue
    const m = createEventMarker(e)
    if (!m) continue
    eventMarkers.set(e.id, m)
    eventLayer.addLayer(m)
  }
}

/** 帧频差分（游标拖动/播放）：按可见集增删单枚——严禁 clearLayers */
function syncEventMarkersOnFrame() {
  if (!map || !eventLayer || !layerVisible.value.events) return
  const t = currentTime.value
  const visible = new Set<string>()
  for (const e of events.value) {
    if (e.time_start > t) continue
    visible.add(e.id)
    if (eventMarkers.has(e.id)) continue
    const m = createEventMarker(e)
    if (!m) continue
    eventMarkers.set(e.id, m)
    eventLayer.addLayer(m)
  }
  for (const [id, m] of [...eventMarkers]) {
    if (!visible.has(id)) {
      eventLayer.removeLayer(m)
      eventMarkers.delete(id)
    }
  }
}

/**
 * 绘制草稿层（最顶层）：顶点圆点 + 虚线预览 + territory ≥3 点时半透明填充。
 * 手画即所得——预览色与最终落图色一致（疆域紫 / 路径蓝）。
 */
function renderDraw() {
  if (!map || !drawLayer) return
  drawLayer.clearLayers()
  rubberLine = null
  const pts = draftPoints.value
  if (!props.drawMode || pts.length === 0) return
  const color = drawColor.value
  const latlngs = pts.map(({ p: [x, y] }) => [y, x] as [number, number])
  // 填充垫最底（territory 闭合预览）
  if (props.drawMode === 'territory' && pts.length >= 3) {
    drawLayer.addLayer(
      L.polygon(latlngs, { stroke: false, fillColor: color, fillOpacity: 0.13, interactive: false }),
    )
  }
  // 虚线预览
  if (pts.length >= 2) {
    drawLayer.addLayer(
      L.polyline(latlngs, { color, weight: 2, dashArray: '6 6', opacity: 0.9, interactive: false }),
    )
  }
  // 顶点圆点（首点略大，提示闭合起点）
  pts.forEach(({ p }, i) => {
    drawLayer!.addLayer(
      L.circleMarker([p[1], p[0]], {
        radius: i === 0 ? 5.5 : 4,
        color: '#fff',
        weight: 2,
        fillColor: color,
        fillOpacity: 1,
        interactive: false,
      }),
    )
  })
}

/** 闭合绘制：territory 需 ≥3 顶点，move-path ≥0；不达标静默忽略（继续画）。point 单击即完成，不经此路 */
function finishDraw() {
  if (!props.drawMode || props.drawMode === 'point') return
  const need = props.drawMode === 'territory' ? 3 : 0
  if (draftPoints.value.length < need) return
  const pts = draftPoints.value.map(({ p }) => [p[0], p[1]] as [number, number])
  clearDraft()
  emit('draw-complete', pts)
}

/** 删上一个顶点（Backspace） */
function undoVertex() {
  if (!props.drawMode || draftPoints.value.length === 0) return
  draftPoints.value.pop()
  renderDraw()
}

function clearDraft() {
  draftPoints.value = []
  renderDraw()
}

function zoomIn() {
  map?.zoomIn()
}
function zoomOut() {
  map?.zoomOut()
}

onMounted(() => {
  if (!containerRef.value) return
  map = L.map(containerRef.value, {
    crs: L.CRS.Simple,
    minZoom: -2,
    maxZoom: 3,
    zoomSnap: 0.25,
    zoomControl: false, // 自绘缩放按钮（右上工具条）
    attributionControl: false,
    doubleClickZoom: false, // 双击留给「绘制闭合」；缩放已有自绘 +/- 按钮
  })
  baseImageLayer = L.layerGroup().addTo(map) // 底图图片（最底）
  trackLayer = L.layerGroup().addTo(map)
  territoryLayer = L.layerGroup().addTo(map)
  rippleLayer = L.layerGroup().addTo(map)
  eventLayer = L.layerGroup().addTo(map)
  markerLayer = L.layerGroup().addTo(map)
  entityLayer = L.layerGroup().addTo(map)
  relationLayer = L.layerGroup().addTo(map)
  drawLayer = L.layerGroup().addTo(map)
  editHitLayer = L.layerGroup().addTo(map)
  editSelLayer = L.layerGroup().addTo(map) // 底图编辑框最顶
  map.fitBounds(BOUNDS)
  // 用户一旦手动拖/缩，初始取景（空白舆图框世界平面）就不再插手
  map.on('dragstart zoomstart', () => {
    if (!framing) viewTouched = true
  })
  // 右键空白：在此建实体（单一画布入口）；地图点击关闭悬浮菜单/表单
  map.on('contextmenu', onMapContextMenu)
  map.on('click', () => {
    ctxMenu.value = null
    if (!linking) createForm.value = null
  })
  // ⇧拖线建关系：window 级指针跟踪（松手命中最近实体节点）
  window.addEventListener('pointermove', onLinkPointerMove)
  window.addEventListener('pointerup', onLinkPointerUp)
  map.on('click', (e: L.LeafletMouseEvent) => {
    // D4 比例尺标定：收两点（内部 [x,y]）→ 派发给 WorldView 选档落库
    if (calibrating.value) {
      calibPoints.value.push([e.latlng.lng, e.latlng.lat])
      renderCalibLine()
      if (calibPoints.value.length >= 2) {
        const pts = calibPoints.value.slice(0, 2)
        // §2.2 空白舆图预填：无底图层且未标定时，画线按地球隐含尺度（图宽=赤道一圈）
        // 折算步行日随事件带出——选档卡预填默认值，作者可改可推翻
        let suggestedDays: number | undefined
        if (blankAtlas.value && !(props.mapScale?.refs?.length)) {
          const len = Math.hypot(pts[1][0] - pts[0][0], pts[1][1] - pts[0][1])
          const atlasWidth = BLANK_ATLAS_BOUNDS.getEast() - BLANK_ATLAS_BOUNDS.getWest()
          suggestedDays = blankAtlasSuggestedDays(len, atlasWidth)
        }
        window.dispatchEvent(new CustomEvent('velluma:map-calibrate-line', {
          detail: { points: pts, ...(suggestedDays ? { suggested_days: suggestedDays } : {}) },
        }))
        stopCalibrating()
      }
      return
    }
    if (props.drawMode) {
      // point 模式一击即完成（单击即所取，无顶点可攒，无需闭合动作）
      if (props.drawMode === 'point') {
        emit('draw-complete', [[e.latlng.lng, e.latlng.lat]])
        return
      }
      // 绘制优先：点击收集顶点（[lng,lat] → 内部 [x,y]，带时间戳供双击识别）
      draftPoints.value.push({ p: [e.latlng.lng, e.latlng.lat], t: Date.now() })
      renderDraw()
      return
    }
    if (mapEditMode.value === 'images') {
      selectedLayerId.value = null // 点空白取消选中（图上的点击已被 stopPropagation）
      return
    }
    if (props.pickingMode) {
      emit('pick', [e.latlng.lng, e.latlng.lat])
    }
  })
  map.on('dblclick', (e: L.LeafletMouseEvent) => {
    if (!props.drawMode) return
    // 双击闭合。双击会伴随 1~2 次 click（数量随事件源不定，真实浏览器为 2）——
    // 把「与双击同位置且 600ms 内」的尾部合成顶点剥掉再闭合；
    // 用户真实顶点时间更早或位置不同，不会被误删。
    const removed = countSyntheticTail(draftPoints.value, e.latlng.lng, e.latlng.lat, Date.now())
    for (let i = 0; i < removed; i++) draftPoints.value.pop()
    finishDraw()
  })
  map.on('mousemove', (e: L.LeafletMouseEvent) => {
    if (!props.drawMode || draftPoints.value.length === 0 || !drawLayer) return
    const last = draftPoints.value[draftPoints.value.length - 1]
    const ll: [number, number][] = [
      [last.p[1], last.p[0]],
      [e.latlng.lat, e.latlng.lng],
    ]
    if (!rubberLine) {
      rubberLine = L.polyline(ll, {
        color: drawColor.value,
        weight: 1.5,
        dashArray: '4 6',
        opacity: 0.55,
        interactive: false,
      })
      drawLayer.addLayer(rubberLine)
    } else {
      rubberLine.setLatLngs(ll)
    }
  })
  // 缩放结束：按 zoom 阈值重渲带名字标签的层（缩小藏名字，放大显示）
  map.on('zoomend', () => {
    renderMarkers()
    renderEntities()
  renderRelations()
    scheduleStrokeRedraw()
    updateScaleBar()
  })
  // 笔迹 canvas 与地图视图同步（拖动/缩放/窗口变化 → rAF 重绘）
  map.on('move zoom viewreset resize', scheduleStrokeRedraw)
  // 地点 popup 的就地改名/删除/详情（popup DOM 随开随建，委托绑定无泄漏）
  map.on('popupopen', (e: L.PopupEvent) => {
    const root = e.popup.getElement()
    const box = root?.querySelector('.wm-pop-edit') as HTMLElement | null
    if (!box) return
    const locId = box.dataset.locId || ''
    const input = box.querySelector('[data-loc-name]') as HTMLInputElement | null
    const doSave = () => {
      const n = (input?.value || '').trim()
      if (n) {
        renameLocation(props.bookId, locId, n)
        showToast('地点已改名', 'success')
      }
      map?.closePopup()
    }
    box.querySelector('[data-act="save"]')?.addEventListener('click', doSave)
    input?.addEventListener('keydown', (ev) => {
      if (ev.key === 'Enter') {
        ev.stopPropagation()
        doSave()
      }
    })
    box.querySelector('[data-act="detail"]')?.addEventListener('click', () => {
      map?.closePopup()
      emit('location-detail', locId)
    })
    box.querySelector('[data-act="del"]')?.addEventListener('click', async () => {
      const loc = locations.value.find((l) => l.id === locId)
      const innerCount = (locChildren.value.get(locId) || []).length
      map?.closePopup()
      const ok = await showConfirm({
        title: '删除地点',
        message: `确定删除地点「${loc?.name || ''}」吗？`,
        warning:
          (innerCount ? `含 ${innerCount} 个内部构造，将一并删除。` : '') +
          '关联事件的地点引用会被清空（可用 Ctrl+Z 撤销）。',
        confirmText: '删除',
      })
      if (ok) {
        await deleteLocation(props.bookId, locId)
        showToast('地点已删除', 'success')
      }
    })
  })
  renderBaseImages()
  renderEditImages()
  renderMarkers()
  renderTracks()
  renderEntities()
  renderRelations()
  renderTerritory()
  renderEventMarkers()
})

watch(locations, renderMarkers, { deep: true })
// 面板 📍 回指脉冲：prop 变化重渲 marker 层挂/摘 wm-loc--hl（null→id→null 两次触发，
// WorldView 侧 nextTick 分离保证连点同目标也能重播）
watch(() => props.highlightLocationId, () => renderMarkers())
// ===== 渲染管线（P0 性能治理 2026-09-14：高频/低频分离）=====
// 低频：宏观数据真正增删改（事件/地点——地点变更经 locationsById 波及事件点/
// 实体回退位）→ 全量重建全部数据层。保留 deep：增删改可能就地变更数组元素，
// 低频路径的深比较开销可忽略（此前每帧版 deep 才是杀手）。
// （mapLayers/mapStrokes 有意不入此监听：底图/笔迹不进这五层、各有专属 watch，
//   blanket 监听会让笔迹逐笔触发全层重建。）
watch([events, locations], () => {
  spawnRipples(currentTime.value)
  renderTracks()
  renderEntities()
  renderRelations()
  renderTerritory()
  renderEventMarkers()
}, { deep: true })
// 高频：游标拖动/播放（上游 rAF 节流至每帧一次）→ 只做差分，严禁 clearLayers
// 全量重建——实体 marker 复用 setLatLng 挪位（move 沿路径插值移动效果不变）、
// 关系线 setLatLngs 随端点伸缩、事件 marker 按可见集增删、轨迹签名门控
// （仅跨事件边界才重建）、疆域层本就是形变差分（territoryPolys Map）。
watch(currentTime, () => {
  spawnRipples(currentTime.value)
  syncTracksOnFrame()
  syncEntitiesOnFrame()
  syncRelationsOnFrame()
  renderTerritory()
  syncEventMarkersOnFrame()
})
watch(layerVisible, () => {
  renderMarkers()
  renderTracks()
  renderEntities()
  renderRelations()
  renderTerritory()
  renderEventMarkers()
}, { deep: true })
// 进入/退出沉浸编辑（疆域绘制 / 底图编辑）：清草稿 + 重渲各层（数据层禁交互）
watch([entities, relations], () => {
  renderEntities()
  renderRelations()
}, { deep: true })
watch(highlightEntityId, () => {
  renderEntities()
  renderRelations()
})
watch(inEditMode, () => {
  clearDraft()
  renderMarkers()
  renderTracks()
  renderEntities()
  renderRelations()
  renderTerritory()
  renderEventMarkers()
})
// 底图数据变化：重渲图片层 + 编辑框（拖动落库后触发，位置已就位仅刷新引用）
watch(mapLayers, () => {
  renderBaseImages()
  renderEditImages()
}, { deep: true })
watch(mapEditMode, () => renderEditImages())
watch(selectedLayerId, () => renderSelection())
watch(mapStrokes, () => {
  scheduleStrokeRedraw()
  renderBlankAtlas() // 笔迹是底图的一种：第一笔落下即撤下空白舆图
}, { deep: true })
watch(draftStroke, scheduleStrokeRedraw, { deep: true })
// 进入/退出画笔：清草稿重绘
watch(drawingMap, () => {
  painting = false
  draftStroke.value = []
  scheduleStrokeRedraw()
})

/** 聚焦到内部坐标 (x, y)——外部（事件/地点列表点击）调用 */
let lastFocus: { x: number; y: number; t: number } | null = null
function focusAt(x: number, y: number, title?: string) {
  if (!map) return
  // 连点抑制：setView 动画在飞时中心尚未到位，连点同一目标会从半路重新起飞（地图上看起来就是"不停地移动"）；
  // 目标已在屏中心附近且缩放够时同样不再动相机，只换气泡。
  const now = Date.now()
  const sameAsLast = lastFocus != null && lastFocus.x === x && lastFocus.y === y && now - lastFocus.t < 1200
  const nearCenter =
    map.getZoom() >= 1 &&
    map.latLngToContainerPoint([y, x]).distanceTo(map.getSize().divideBy(2)) < 40
  if (!sameAsLast && !nearCenter) {
    map.setView([y, x], Math.max(map.getZoom(), 1), { animate: true })
  }
  lastFocus = { x, y, t: now }
  if (title) {
    // autoPan 关闭：相机已对准目标，气泡偏移若再触发自动平移会与下一次点击的 setView 互相拉锯
    L.popup({ closeButton: true, autoPan: false })
      .setLatLng([y, x])
      .setContent(`<b>${esc(title)}</b>`)
      .openOn(map)
  }
}
/**
 * 回到全图：视野收拢到全部内容（底图 + 地点 + 实体），空图回初始全幅。
 * 罗盘饰件的实功能——平移迷路后一键回家（maxZoom 防单点冲到最大倍率）。
 */
function fitAll() {
  if (!map) return
  const pts: L.LatLngExpression[] = []
  for (const l of mapLayers.value) {
    const lb = layerBounds(l)
    pts.push(lb.getSouthWest(), lb.getNorthEast())
  }
  for (const loc of locations.value) {
    if (loc.coord_x != null && loc.coord_y != null) pts.push([loc.coord_y, loc.coord_x])
  }
  for (const mk of entityMarkers.values()) pts.push(mk.getLatLng())
  if (!pts.length) {
    map.fitBounds(blankOverlay ? BLANK_ATLAS_BOUNDS : BOUNDS) // 空图回世界平面
    return
  }
  map.fitBounds(L.latLngBounds(pts), { padding: [48, 48], maxZoom: 1, animate: true })
}

defineExpose({ focusAt, fitAll, finishDraw, undoVertex, importImageAtView })

onBeforeUnmount(() => {
  if (strokeRafId !== null) cancelAnimationFrame(strokeRafId)
  window.removeEventListener('pointermove', onLinkPointerMove)
  window.removeEventListener('pointerup', onLinkPointerUp)
  map?.remove()
  map = null
  baseImageLayer = null
  trackLayer = null
  territoryLayer = null
  rippleLayer = null
  eventLayer = null
  markerLayer = null
  entityLayer = null
  relationLayer = null
  drawLayer = null
  editHitLayer = null
  editSelLayer = null
  blankOverlay = null
  rubberLine = null
})
</script>

<template>
  <div class="world-map-wrap">
    <div ref="containerRef" class="world-map" :class="{ drawing: drawMode }"></div>

    <!-- D4 比例尺角标（左下；随缩放重算长度——像真地图的图例，玩具感来源） -->
    <div v-if="scaleBarText" class="wm-scalebar" title="比例尺标定（⋯ 菜单可重标）">
      <span class="wm-scalebar-line"></span>{{ scaleBarText }}
    </div>
    <!-- D4 标定拉线提示 -->
    <div v-if="calibrating" class="wm-calib-hint">在地图上点两个点——这段路你走多久？</div>

    <!-- 墨迹滤镜 defs：疆域 SVG 位移毛边（古卷水彩晕染）；-soft 为空白舆图细线版 -->
    <svg class="wm-svg-defs" width="0" height="0" aria-hidden="true">
      <defs>
        <filter id="wm-ink" x="-8%" y="-8%" width="116%" height="116%">
          <feTurbulence type="fractalNoise" baseFrequency="0.045" numOctaves="2" seed="7" result="n" />
          <feDisplacementMap in="SourceGraphic" in2="n" scale="4.5" xChannelSelector="R" yChannelSelector="G" />
        </filter>
        <filter id="wm-ink-soft" x="-4%" y="-4%" width="108%" height="108%">
          <feTurbulence type="fractalNoise" baseFrequency="0.09" numOctaves="2" seed="11" result="n" />
          <feDisplacementMap in="SourceGraphic" in2="n" scale="2.2" xChannelSelector="R" yChannelSelector="G" />
        </filter>
      </defs>
    </svg>

    <!-- 烛光暗角（羊皮古卷氛围；不拦截交互） -->
    <div class="wm-vignette"></div>

    <!-- 空白舆图浮动提示卡（真正一片空白时；点透不拦交互，有了第一个名字即退场） -->
    <div v-if="showBlankCard" class="wm-blankcard">
      <div class="wm-blankcard-over">BLANK ATLAS</div>
      <div class="wm-blankcard-title">空白舆图</div>
      <div class="wm-blankcard-orn">
        <svg viewBox="0 0 120 12" width="110" height="11"><path d="M0,6 H48 M72,6 H120" stroke="currentColor" stroke-width="1"/><path d="M60,1 L65,6 L60,11 L55,6 Z" fill="none" stroke="currentColor" stroke-width="1"/></svg>
      </div>
      <div class="wm-blankcard-sub">
        点右缘工具条的「图片 / 画笔」铺上你的第一张底图，<br/>或直接在账本上点第一个名字——世界会从第一个名字长出来。
      </div>
    </div>

    <!-- 图例（单一画布的编辑入口可发现性；默认收起为一行，hover 展开手势明细）。
         02 期 §5.2：tabindex + focus-within 补键盘对等（pop 是纯信息面板，display 模式保留） -->
    <div v-if="!inEditMode && hasVisibleNodes" class="wm-legend">
      <span class="wm-legend-tag" tabindex="0">图例</span>
      <div class="wm-legend-pop">
        <div class="wm-legend-row"><kbd>⇧ 拖</kbd><span>甲节点 → 乙节点：结缘</span></div>
        <div class="wm-legend-row"><kbd>右键</kbd><span>空白处：落一个新名字</span></div>
        <div class="wm-legend-row"><kbd>拖</kbd><span>有故事的角色：记一次远行</span></div>
      </div>
    </div>

    <!-- ⇧拖线建关系的橡皮筋线 -->
    <svg v-if="linkRubber" class="wm-link-rubber">
      <line
        :x1="linkRubber.x1"
        :y1="linkRubber.y1"
        :x2="linkRubber.x2"
        :y2="linkRubber.y2"
        stroke="#7c6aad"
        stroke-width="2"
        stroke-dasharray="6 4"
      />
    </svg>

    <!-- 右键菜单：在此建实体 -->
    <div v-if="ctxMenu" class="wm-ctx" :style="{ left: ctxMenu.x + 'px', top: ctxMenu.y + 'px' }" @mousedown.stop @contextmenu.prevent>
      <div class="wm-ctx-title">在此位置</div>
      <button class="wm-ctx-item" @click="ctxCreateEntity">
        <Icon name="plus" :size="13" />
        建实体…
      </button>
    </div>

    <!-- 就地建实体（名字 + 类型，落锚位） -->
    <div v-if="createForm" class="wm-cform" :style="{ left: createForm.x + 'px', top: createForm.y + 'px' }" @mousedown.stop @contextmenu.prevent @keydown.esc="createForm = null">
      <div class="wm-cform-title">新实体 · 落在锚位</div>
      <div class="wm-cform-row">
        <div class="wm-cform-seg">
          <button
            v-for="t in [
              { v: 'character', label: '角色' },
              { v: 'faction', label: '势力' },
              { v: 'asset', label: '资产' },
            ]"
            :key="t.v"
            class="wm-cform-seg-btn"
            :class="{ active: createForm.type === t.v }"
            @click="createForm.type = t.v as typeof createForm.type"
          >
            {{ t.label }}
          </button>
        </div>
      </div>
      <input
        v-model="createForm.name"
        class="wm-cform-input"
        placeholder="名字（Enter 建立）"
        @keydown.enter.prevent="submitCreateEntity"
      />
      <div class="wm-cform-hint">无事件历史的实体自由摆放；拖动即可调整位置</div>
    </div>

    <!-- 建关系 / 编辑关系（点关系线或 ⇧拖线落点） -->
    <div v-if="draftForm" class="wm-rform" :style="{ left: draftForm.x + 'px', top: draftForm.y + 'px' }" @mousedown.stop @contextmenu.prevent>
      <RelationInlineForm
        :book-id="bookId"
        :source-id="draftForm.sourceId"
        :target-id="draftForm.targetId"
        :existing="draftForm.existing"
        @saved="draftForm = null"
        @cancel="draftForm = null"
      />
    </div>

    <!-- 手绘笔迹层（pointer-events 仅画笔态开启，其余穿透到地图） -->
    <canvas
      ref="strokeCanvasRef"
      class="wm-stroke-canvas"
      :class="{ drawing: mapEditMode === 'draw' }"
      @pointerdown="onStrokeDown"
      @pointermove="onStrokeMove"
      @pointerup="onStrokeUp"
      @pointercancel="onStrokeUp"
    ></canvas>

    <!-- 右上工具条：底图编辑入口 + 缩放 + 图层显隐 -->
    <div class="wm-toolbar">
      <button
        class="wm-tool"
        :class="{ on: mapEditMode === 'images' }"
        title="底图 · 导入图片拼贴"
        @click="toggleEdit('images')"
      >
        <Icon name="map" :size="14" />
      </button>
      <button
        class="wm-tool"
        :class="{ on: mapEditMode === 'draw' }"
        title="底图 · 手绘"
        @click="toggleEdit('draw')"
      >
        <Icon name="paint-brush" :size="14" />
      </button>
      <span class="wm-tool-sep"></span>
      <button class="wm-tool" title="放大" @click="zoomIn">
        <Icon name="plus" :size="14" />
      </button>
      <button class="wm-tool" title="缩小" @click="zoomOut">
        <Icon name="minus" :size="14" />
      </button>
      <span class="wm-tool-sep"></span>
      <button
        v-for="tg in LAYER_TOGGLES"
        :key="tg.key"
        class="wm-tool"
        :class="{ on: layerVisible[tg.key] }"
        :title="`${tg.label}图层`"
        @click="layerVisible[tg.key] = !layerVisible[tg.key]"
      >
        <Icon :name="tg.icon" :size="14" />
      </button>
    </div>

    <!-- 底图编辑面板（编辑态，左上浮动） -->
    <div v-if="mapEditMode" class="wm-editbar">
      <template v-if="mapEditMode === 'images'">
        <button class="wm-ebtn wm-ebtn--primary" @click="fileInputRef?.click()">
          <Icon name="arrow-up-tray" :size="13" />
          导入图片
        </button>
        <template v-if="selectedLayer">
          <span class="wm-esep"></span>
          <button
            class="wm-ebtn"
            title="置于顶层"
            @click="reorderLayer(bookId, selectedLayer.id, 'front')"
          >
            <Icon name="chevron-up" :size="13" />
            置顶
          </button>
          <button
            class="wm-ebtn"
            title="置于底层"
            @click="reorderLayer(bookId, selectedLayer.id, 'back')"
          >
            <Icon name="chevron-down" :size="13" />
            置底
          </button>
          <button class="wm-ebtn wm-ebtn--danger" title="删除图片（Del）" @click="removeSelected">
            <Icon name="trash" :size="13" />
          </button>
        </template>
        <span class="wm-ehint">点击图片选中 · 拖中心移动 · 拖角缩放 · 也可直接拖文件进地图</span>
      </template>
      <template v-else-if="mapEditMode === 'draw'">
        <div class="wm-palette">
          <button
            v-for="c in PEN_COLORS"
            :key="c"
            class="wm-swatch"
            :class="{ active: penColor === c && !eraserMode }"
            :style="{ background: c }"
            :title="`画笔 ${c}`"
            @click="penColor = c; eraserMode = false"
          ></button>
        </div>
        <span class="wm-esep"></span>
        <div class="wm-sizes">
          <button
            v-for="s in PEN_SIZES"
            :key="s"
            class="wm-size"
            :class="{ active: penWidth === s && !eraserMode }"
            :title="`粗细 ${s}`"
            @click="penWidth = s; eraserMode = false"
          >
            <span :style="{ width: s + 4 + 'px', height: s + 4 + 'px' }"></span>
          </button>
        </div>
        <span class="wm-esep"></span>
        <button
          class="wm-ebtn"
          :class="{ 'wm-ebtn--active': eraserMode }"
          title="橡皮（划过删除命中的笔迹）"
          @click="eraserMode = !eraserMode"
        >
          <Icon name="no-symbol" :size="13" />
          橡皮
        </button>
        <button
          class="wm-ebtn"
          :disabled="!canEditUndo"
          title="撤销（Ctrl+Z）"
          @click="editUndo()"
        >
          <Icon name="arrow-uturn-left" :size="13" />
        </button>
        <button
          class="wm-ebtn"
          :disabled="!canEditRedo"
          title="重做（Ctrl+Y）"
          @click="editRedo()"
        >
          <Icon name="arrow-uturn-right" :size="13" />
        </button>
        <button class="wm-ebtn wm-ebtn--danger" title="清空全部笔迹" @click="clearAllStrokes(bookId)">
          <Icon name="trash" :size="13" />
        </button>
        <span class="wm-ehint">拖动即绘制 · Esc 完成</span>
      </template>
      <button class="wm-ebtn wm-ebtn--done" title="退出编辑（Esc）" @click="exitMapEdit">
        完成
      </button>
      <input
        ref="fileInputRef"
        type="file"
        accept=".png,.jpg,.jpeg,.webp,.gif"
        hidden
        @change="onFile"
      />
    </div>
  </div>
</template>

<style scoped>
.world-map-wrap {
  position: relative;
  width: 100%;
  height: 100%;
  /* 独立层叠上下文（2026-08-25 从 .world-map 上移到此）：wrap 内全部覆盖层
     ——暗角 645 / 空白舆图卡 660 / 图例 700 / 右键菜单 850 / 创建表单 860——
     此前与页面 z-110 的模态在根层叠上下文混排，空白舆图卡曾压盖住通读向导
     模态（实测：「建好勾选的」按钮区被拦）。关在 wrap 内后模态恒在其上。 */
  isolation: isolate;
}
/* 羊皮古卷画布：做旧纸底 + 纤维纹 + 淡墨绘制网格（零图片，纯 CSS gradient 不触 CSP） */
.world-map {
  width: 100%;
  height: 100%;
  min-height: 400px;
  background-color: #e7d7b6;
  background-image:
    /* 淡墨经纬细线（古地图绘制网格） */
    linear-gradient(rgba(107, 90, 68, 0.07) 1px, transparent 1px),
    linear-gradient(90deg, rgba(107, 90, 68, 0.07) 1px, transparent 1px),
    /* 纸面纤维（两组低角度细纹交错） */
    repeating-linear-gradient(93deg, rgba(122, 92, 50, 0.03) 0 2px, transparent 2px 5px),
    repeating-linear-gradient(3deg, rgba(122, 92, 50, 0.022) 0 2px, transparent 2px 6px),
    /* 中心受光、边缘沉色的做旧渐层 */
    radial-gradient(ellipse at 46% 42%, rgba(255, 249, 231, 0.5), rgba(216, 195, 156, 0.35) 62%, rgba(196, 172, 130, 0.42) 100%),
    linear-gradient(160deg, #ecdfc3 0%, #e5d4b0 55%, #dcc8a0 100%);
  background-size:
    96px 96px,
    96px 96px,
    auto,
    auto,
    auto,
    auto;
  /* Leaflet 内部 pane z-index 高达 700——本层隔离只收 pane；
     外层 .world-map-wrap 的 isolation 才挡页面模态（2026-08-25 上移） */
  isolation: isolate;
}
:deep(.leaflet-container) {
  background: transparent;
  font: inherit;
}
/* 烛光暗角：压过数据层但不拦交互（阴影 pane 500 / marker 600 / tooltip 650 之上取 645） */
.wm-vignette {
  position: absolute;
  inset: 0;
  pointer-events: none;
  z-index: 645;
  background:
    radial-gradient(ellipse at 50% 46%, transparent 52%, rgba(74, 56, 30, 0.12) 78%, rgba(60, 44, 22, 0.3) 100%);
  mix-blend-mode: multiply;
}
.wm-svg-defs {
  position: absolute;
  width: 0;
  height: 0;
  pointer-events: none;
}
/* 绘制期十字光标（压过 Leaflet 的 grab 手型） */
.world-map.drawing :deep(.leaflet-container) {
  cursor: crosshair !important;
}
.wm-toolbar {
  position: absolute;
  left: 12px;
  top: 50%;
  transform: translateY(-50%);
  display: flex;
  flex-direction: column;
  gap: 4px;
  z-index: 500;
  padding: 4px;
  background: rgba(236, 228, 211, 0.92); /* 与右缘图标栏同族：暖纸底 + 暖墨边 */
  backdrop-filter: blur(3px);
  border: 1px solid rgba(107, 90, 68, 0.28);
  border-radius: 12px;
  box-shadow: 0 4px 16px rgba(96, 72, 36, 0.14);
}
.wm-tool {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border: none;
  border-radius: 8px;
  background: transparent;
  color: rgba(109, 90, 60, 0.75);
  cursor: pointer;
  transition: all 0.12s;
}
.wm-tool:hover {
  background: rgba(120, 95, 50, 0.1);
  color: rgba(74, 68, 56, 0.95);
}
.wm-tool.on {
  background: rgba(124, 106, 173, 0.14);
  color: var(--accent-500);
}
.wm-tool:focus-visible {
  outline: 2px solid rgba(124, 106, 173, 0.55);
  outline-offset: 1px;
}
.wm-tool-sep {
  height: 1px;
  margin: 1px 3px;
  background: rgba(107, 90, 68, 0.22);
}
/* ===== 底图编辑面板（左上浮动） ===== */
.wm-editbar {
  position: absolute;
  top: 12px;
  left: 12px;
  z-index: 500;
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 8px;
  background: rgba(236, 228, 211, 0.92);
  backdrop-filter: blur(3px);
  border: 1px solid rgba(107, 90, 68, 0.28);
  border-radius: 12px;
  box-shadow: 0 4px 16px rgba(96, 72, 36, 0.14);
  max-width: calc(100% - 90px);
  flex-wrap: wrap;
}
.wm-ebtn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 5px 10px;
  border: 1px solid var(--border-color);
  border-radius: 7px;
  background: transparent;
  color: var(--text-secondary);
  font-size: 12px;
  font-family: inherit;
  cursor: pointer;
  transition: all 0.13s;
  white-space: nowrap;
}
.wm-ebtn:hover {
  border-color: var(--accent-500);
  color: var(--accent-500);
}
.wm-ebtn--primary {
  background: var(--accent-500);
  border-color: var(--accent-500);
  color: #fff;
}
.wm-ebtn--primary:hover {
  background: var(--accent-600);
  color: #fff;
}
.wm-ebtn--danger:hover {
  border-color: var(--danger);
  color: var(--danger);
}
.wm-ebtn--done {
  font-weight: 600;
}
.wm-esep {
  width: 1px;
  height: 16px;
  background: var(--border-color);
  margin: 0 2px;
}
.wm-ehint {
  font-size: var(--text-xs);
  color: var(--text-muted);
  white-space: nowrap;
}
/* 画笔态笔迹 canvas */
.wm-stroke-canvas {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  pointer-events: none;
  z-index: 460;
}
.wm-stroke-canvas.drawing {
  pointer-events: auto;
  cursor: crosshair;
}
/* 画笔工具 */
.wm-palette {
  display: flex;
  gap: 4px;
}
.wm-swatch {
  width: 18px;
  height: 18px;
  border-radius: 9999px;
  border: 2px solid #fff;
  box-shadow: 0 0 0 1px var(--border-color);
  cursor: pointer;
  transition: box-shadow 0.12s;
}
.wm-swatch.active {
  box-shadow: 0 0 0 2px var(--accent-500);
}
.wm-sizes {
  display: flex;
  gap: 4px;
}
.wm-size {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  border: 1px solid var(--border-color);
  border-radius: 7px;
  background: transparent;
  cursor: pointer;
}
.wm-size span {
  border-radius: 9999px;
  background: var(--text-secondary);
}
.wm-size.active {
  border-color: var(--accent-500);
  background: rgba(124, 106, 173, 0.1);
}
.wm-ebtn--active {
  border-color: var(--accent-500);
  color: var(--accent-500);
  background: rgba(124, 106, 173, 0.1);
  font-weight: 600;
}

/* D4 比例尺角标 + 标定提示（2026-09-04 审计修复：此前模板有元素无样式——
   未定位块排在地图容器之后的文档流里，实际不可见） */
.wm-scalebar {
  position: absolute;
  left: 14px;
  bottom: 14px;
  z-index: 650;
  display: inline-flex;
  align-items: center;
  gap: 0.45rem;
  padding: 0.25rem 0.6rem;
  border-radius: 999px;
  background: rgba(250, 247, 240, 0.92);
  border: 1px solid rgba(120, 100, 80, 0.25);
  color: #6b5c4c;
  font-size: var(--text-xs);
  letter-spacing: 0.05em;
  pointer-events: none;
}

.wm-scalebar-line {
  display: inline-block;
  width: 56px;
  height: 0;
  border-top: 2px solid #6b5c4c;
  border-left: 2px solid #6b5c4c;
  border-right: 2px solid #6b5c4c;
}

.wm-calib-hint {
  position: absolute;
  top: 14px;
  left: 50%;
  transform: translateX(-50%);
  z-index: 650;
  padding: 0.35rem 0.9rem;
  border-radius: 999px;
  background: rgba(250, 247, 240, 0.95);
  border: 1px solid rgba(194, 114, 90, 0.45);
  color: #8c4a38;
  font-size: 12px;
  pointer-events: none;
}
</style>

<style>
/* ===== 全局（Leaflet divIcon 的 DOM 在 Vue scoped 之外）===== */

/* 地点 marker：空心环点 + 名字标签 */
.wm-loc-icon {
  background: transparent;
  border: none;
}
.wm-loc {
  display: flex;
  align-items: center;
  gap: 5px;
  transform: translate(-8px, -8px);
}
.wm-loc-ring {
  /* divIcon iconSize [0,0] → 容器宽 0；行 flex 负空间全压到无内容的环上
     （13px 被压成 4.8px 宽竖条），禁止收缩保圆环 */
  flex-shrink: 0;
  width: 13px;
  height: 13px;
  border-radius: 9999px;
  background: rgba(249, 242, 226, 0.92);
  border: 3px solid var(--c, #7c6aad);
  box-shadow: 0 1px 5px rgba(60, 44, 22, 0.3);
  transition: transform 0.15s ease-out;
}
/* 有内部构造的地点：环心加一点（提示「里面还有东西，点开详情」） */
.wm-loc-dot {
  position: absolute;
  left: 0;
  top: 0;
  width: 13px;
  height: 13px;
  display: flex;
  align-items: center;
  justify-content: center;
  pointer-events: none;
}
.wm-loc-dot::after {
  content: '';
  width: 4px;
  height: 4px;
  border-radius: 9999px;
  background: var(--c, #7c6aad);
}
.wm-loc--inner {
  position: relative;
}
.wm-loc:hover .wm-loc-ring {
  transform: scale(1.25);
}
/* 面板 📍 定位/联动回指：地标声呐脉冲（3 拍自止；class 由 WorldView 定时摘除，
   常驻会在 zoomend 等重渲时机随机重播） */
.wm-loc--hl .wm-loc-ring {
  animation: wm-loc-pulse 0.8s ease-out 3;
}
@keyframes wm-loc-pulse {
  0% {
    box-shadow: 0 1px 5px rgba(60, 44, 22, 0.3), 0 0 0 0 color-mix(in srgb, var(--c, #7c6aad) 55%, transparent);
  }
  100% {
    box-shadow: 0 1px 5px rgba(60, 44, 22, 0.3), 0 0 0 16px transparent;
  }
}
@media (prefers-reduced-motion: reduce) {
  .wm-loc--hl .wm-loc-ring {
    animation: none;
    transform: scale(1.35); /* 降级为静态放大提示 */
  }
}
.wm-loc-name {
  font-size: var(--text-xs);
  font-weight: 600;
  color: var(--text-primary, #2c2c2c);
  background: var(--bg-canvas, #fefdfb);
  border: 1px solid var(--border-color, #e0dbd3);
  padding: 1px 6px;
  border-radius: 6px;
  white-space: nowrap;
  box-shadow: 0 1px 4px rgba(60, 48, 30, 0.14);
}

/* 人物 marker：实心圆点 + 名字；存活呼吸烛光、在途青墨脉冲、核心角色星芒 */
.wm-char-icon {
  background: transparent;
  border: none;
}
.wm-char {
  display: flex;
  flex-direction: column;
  align-items: center;
  transform: translate(-8px, -8px);
}
.wm-char-head {
  width: 15px;
  height: 15px;
  border-radius: 9999px;
  background: var(--c, var(--warn));
  border: 2.5px solid #f4ead4;
  box-shadow: 0 1px 6px rgba(0, 0, 0, 0.4);
  animation: wm-breathe 3.2s ease-in-out infinite;
}
@keyframes wm-breathe {
  50% {
    box-shadow:
      0 1px 6px rgba(0, 0, 0, 0.4),
      0 0 10px 2px rgba(255, 214, 140, 0.4);
  }
}
.wm-char-name {
  margin-top: 3px;
  font-family: "Noto Serif SC", "Source Han Serif SC", "STSong", "SimSun", serif;
  font-size: var(--text-xs);
  font-weight: 600;
  letter-spacing: 0.03em;
  color: var(--text-primary, #2c2c2c);
  background: rgba(249, 242, 226, 0.85);
  border: none;
  border-bottom: 1px solid rgba(107, 90, 68, 0.4);
  padding: 1px 7px;
  border-radius: 4px;
  white-space: nowrap;
}
.wm-char--moving .wm-char-head {
  background: #3f6f8f;
  animation: wm-pulse 1.2s ease-in-out infinite;
}
/* 核心角色（importance≥7）：金环星芒 */
.wm-char--star .wm-char-head {
  border-color: #c9a227;
}
.wm-char--star .wm-char-head::after {
  content: '';
  position: absolute;
  width: 15px;
  height: 15px;
  border-radius: 9999px;
  border: 1.5px dashed rgba(201, 162, 39, 0.85);
  animation: wm-star-spin 14s linear infinite;
}
.wm-char-head {
  position: relative;
}
@keyframes wm-star-spin {
  to {
    transform: rotate(360deg);
  }
}
@keyframes wm-pulse {
  50% {
    box-shadow: 0 0 0 7px rgba(63, 111, 143, 0.28);
  }
}

/* 实体节点（单一画布）：角色圆 / 势力方 / 资产菱，锚位与推演位同体系 */
.wm-node {
  display: flex;
  flex-direction: column;
  align-items: center;
  transform: translate(-8px, -8px);
}
.wm-node-head {
  position: relative;
  width: 15px;
  height: 15px;
  background: var(--c, var(--warn));
  border: 2.5px solid #f4ead4;
  box-shadow: 0 1px 6px rgba(0, 0, 0, 0.4);
  animation: wm-breathe 3.2s ease-in-out infinite;
}
.wm-node--character .wm-node-head {
  border-radius: 9999px;
}
.wm-node--faction .wm-node-head {
  border-radius: 3px;
  width: 17px;
  height: 17px;
}
.wm-node--asset .wm-node-head {
  width: 14px;
  height: 14px;
  transform: rotate(45deg);
  border-radius: 2px;
}
.wm-node--dim {
  opacity: 0.35;
}
.wm-node--dim .wm-node-head {
  animation: none;
}

/* 关系连线：激活瞬间生长（淡入 + 辉光渐隐） */
path.wm-rel {
  cursor: pointer;
}
path.wm-rel-born {
  animation: wm-rel-born 0.8s ease-out;
}
@keyframes wm-rel-born {
  0% {
    opacity: 0;
    filter: drop-shadow(0 0 0 rgba(0, 0, 0, 0));
  }
  35% {
    opacity: 1;
    filter: drop-shadow(0 0 6px rgba(124, 106, 173, 0.8));
  }
  100% {
    opacity: 0.72;
    filter: drop-shadow(0 0 0 rgba(0, 0, 0, 0));
  }
}

/* 图例卡：默认收起「图例」小签，hover 展开手势明细（kbd 键帽替代等号链） */
.wm-legend {
  position: absolute;
  left: 12px;
  bottom: 10px;
  z-index: 700;
}
.wm-legend-tag {
  display: inline-block;
  padding: 4px 12px;
  border-radius: 9999px;
  background: rgba(249, 242, 226, 0.85);
  border: 1px solid rgba(107, 90, 68, 0.3);
  color: rgba(109, 90, 60, 0.85);
  font-size: var(--text-xs);
  letter-spacing: 0.28em;
  text-indent: 0.28em;
  cursor: default;
}
.wm-legend-pop {
  display: none;
  position: absolute;
  left: 0;
  bottom: 30px;
  width: 216px;
  background: rgba(249, 242, 226, 0.96);
  border: 1px solid rgba(107, 90, 68, 0.3);
  border-radius: 8px;
  padding: 10px 12px;
  box-shadow: 0 8px 24px rgba(96, 72, 36, 0.18);
}
.wm-legend:hover .wm-legend-pop,
.wm-legend:focus-within .wm-legend-pop {
  display: block;
}
.wm-legend-row {
  display: flex;
  align-items: center;
  gap: 7px;
  margin: 4px 0;
  font-size: var(--text-xs);
  color: rgba(74, 68, 56, 0.85);
}
.wm-legend-row kbd {
  font-family: inherit;
  font-size: var(--text-xs);
  color: rgba(74, 68, 56, 0.9);
  border: 1px solid rgba(107, 90, 68, 0.35);
  border-bottom-width: 2px;
  border-radius: 4px;
  padding: 0 5px;
  background: rgba(244, 238, 225, 0.9);
  white-space: nowrap;
}

/* ⇧拖线橡皮筋 */
.wm-link-rubber {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  pointer-events: none;
  z-index: 800;
}

/* 右键菜单 / 建实体表单 / 关系表单容器 */
.wm-ctx {
  position: absolute;
  z-index: 850;
  min-width: 150px;
  background: var(--bg-canvas, #fefdfb);
  border: 1px solid var(--border-color, #e0dbd3);
  border-radius: 10px;
  box-shadow: 0 12px 32px rgba(0, 0, 0, 0.18);
  padding: 6px;
  transform: translate(-8px, -8px);
}
.wm-ctx-title {
  padding: 3px 8px 6px;
  font-size: var(--text-xs);
  color: var(--text-muted, #a89e90);
  border-bottom: 1px solid var(--border-color, #e0dbd3);
  margin-bottom: 4px;
}
.wm-ctx-item {
  display: flex;
  align-items: center;
  gap: 7px;
  width: 100%;
  padding: 6px 8px;
  border: none;
  border-radius: 7px;
  background: transparent;
  color: var(--text-secondary);
  font-size: 13px;
  font-family: inherit;
  text-align: left;
  cursor: pointer;
}
.wm-ctx-item:hover {
  background: var(--hover-bg, #f0ebe2);
  color: var(--accent-500);
}
.wm-cform,
.wm-rform {
  position: absolute;
  z-index: 860;
  background: var(--bg-canvas, #fefdfb);
  border: 1px solid var(--border-color, #e0dbd3);
  border-radius: 12px;
  box-shadow: 0 12px 32px rgba(0, 0, 0, 0.18);
  padding: 12px;
}
.wm-cform {
  width: 240px;
}
.wm-cform-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--accent-500);
  margin-bottom: 8px;
}
.wm-cform-row {
  margin-bottom: 8px;
}
.wm-cform-seg {
  display: flex;
  gap: 5px;
}
.wm-cform-seg-btn {
  flex: 1;
  padding: 5px 0;
  border: 1px solid var(--border-color, #e0dbd3);
  border-radius: 8px;
  background: transparent;
  color: var(--text-secondary);
  font-size: 12px;
  font-family: inherit;
  cursor: pointer;
  transition: all 0.12s;
}
.wm-cform-seg-btn.active {
  border-color: var(--accent-500);
  color: var(--accent-500);
  background: rgba(124, 106, 173, 0.08);
  font-weight: 600;
}
.wm-cform-input {
  width: 100%;
  box-sizing: border-box;
  padding: 7px 9px;
  border: 1px solid var(--border-color, #e0dbd3);
  border-radius: 8px;
  background: var(--bg-canvas, #fefdfb);
  color: var(--text-primary);
  font-size: 13px;
  font-family: inherit;
  outline: none;
}
.wm-cform-input:focus {
  border-color: var(--accent-500);
}
.wm-cform-hint {
  margin-top: 7px;
  font-size: var(--text-xs);
  color: var(--text-muted, #a89e90);
  line-height: 1.5;
}

/* 疆域：墨迹晕染（SVG 位移滤镜给边界毛边，纸面水彩感） */
path.wm-territory {
  filter: url(#wm-ink);
}

/* 轨迹：在途虚线流动（行军） */
path.wm-track-flow {
  animation: wm-dash-flow 1.15s linear infinite;
}
@keyframes wm-dash-flow {
  to {
    stroke-dashoffset: -64;
  }
}

/* 事件涟漪：游标扫过时刻绽放（一次性动画，1.5s 后由 JS 移除） */
.wm-ripple-icon {
  background: transparent;
  border: none;
}
.wm-ripple {
  position: absolute;
  width: 8px;
  height: 8px;
  margin: -4px 0 0 -4px;
  border-radius: 9999px;
  border: 2px solid var(--c, var(--text-muted));
  animation: wm-ripple 1.4s ease-out forwards;
}
.wm-ripple::after {
  content: '';
  position: absolute;
  inset: -2px;
  border-radius: 9999px;
  border: 1.5px solid var(--c, var(--text-muted));
  animation: wm-ripple 1.4s 0.22s ease-out forwards;
}
.wm-ripple--big,
.wm-ripple--big::after {
  border-width: 3px;
}
@keyframes wm-ripple {
  from {
    transform: scale(0.4);
    opacity: 0.95;
  }
  to {
    transform: scale(7);
    opacity: 0;
  }
}

/* 事件 marker：圆形印章（印泥做旧 + 手按不规则边） */
.wm-evt-icon {
  background: transparent;
  border: none;
}
.wm-evt {
  display: block;
  width: 11px;
  height: 11px;
  transform: translate(-5.5px, -5.5px) rotate(8deg);
  background: transparent;
  border: 2.5px solid var(--c, var(--text-muted));
  border-radius: 46% 54% 52% 48% / 52% 46% 54% 48%;
  box-shadow:
    inset 0 0 0 1.5px rgba(244, 234, 212, 0.55),
    0 1px 3px rgba(60, 44, 22, 0.35);
  cursor: pointer;
  transition: transform 0.15s ease-out;
}
.wm-evt:hover {
  transform: translate(-5.5px, -5.5px) rotate(8deg) scale(1.35);
}

/* 底图编辑手柄（中心十字 / 角方块） */
.wm-handle-icon {
  background: transparent;
  border: none;
}
.wm-handle {
  width: 12px;
  height: 12px;
  transform: translate(-6px, -6px);
  background: #fff;
  border: 2px solid #7c6aad;
  border-radius: 3px;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.3);
  cursor: move;
}
.wm-handle--center {
  border-radius: 9999px;
  background: #7c6aad;
}

/* Leaflet 弹窗纸面化：默认白泡+灰箭头在羊皮纸上出戏——换纸面底/暖墨边/暖色关闭钮 */
.world-map :deep(.leaflet-popup-content-wrapper) {
  background: rgba(250, 245, 232, 0.97);
  border: 1px solid rgba(107, 90, 68, 0.32);
  border-radius: 10px;
  box-shadow: 0 10px 26px rgba(60, 48, 30, 0.2);
  color: var(--text-primary);
  font-family: inherit;
}
.world-map :deep(.leaflet-popup-content) {
  margin: 10px 14px;
  line-height: 1.55;
  font-size: 12px;
}
.world-map :deep(.leaflet-popup-tip) {
  background: rgba(250, 245, 232, 0.97);
  border: 1px solid rgba(107, 90, 68, 0.32);
  box-shadow: none;
}
.world-map :deep(.leaflet-popup-close-button) {
  color: rgba(109, 90, 60, 0.6);
  font-size: 15px;
  padding: 5px 7px 0 0;
}
.world-map :deep(.leaflet-popup-close-button:hover) {
  color: rgba(74, 68, 56, 0.95);
  background: transparent;
}

/* popup 次要文字 */
.wm-pop-sub {
  color: var(--text-muted, #a89e90);
  font-size: var(--text-xs);
}
.wm-pop-title {
  font-weight: 700;
  font-size: 13px;
  margin-bottom: 2px;
  color: var(--text-primary, #2c2c2c);
}
.wm-pop-intro {
  margin-top: 4px;
  font-size: var(--text-xs);
  line-height: 1.5;
  color: var(--text-secondary, var(--text-secondary));
  max-width: 200px;
}
.wm-pop-inner {
  margin-top: 4px;
  font-size: var(--text-xs);
  color: var(--accent-400, #8b6de8);
}
/* 地点 popup 就地改名/删除 */
.wm-pop-edit {
  display: flex;
  align-items: center;
  gap: 4px;
  margin-top: 8px;
}
.wm-pop-input {
  flex: 1;
  min-width: 140px;
  padding: 4px 8px;
  border: 1px solid var(--border-color, #e0dbd3);
  border-radius: 6px;
  background: var(--bg-canvas, #fff);
  color: var(--text-primary, #2c2c2c);
  font-size: 12px;
  font-family: inherit;
  outline: none;
}
.wm-pop-input:focus {
  border-color: var(--accent-500, #7c6aad);
}
.wm-pop-btn {
  padding: 3px 8px;
  border: 1px solid var(--border-color, #e0dbd3);
  border-radius: 6px;
  background: transparent;
  color: var(--text-secondary, var(--text-secondary));
  font-size: var(--text-xs);
  font-family: inherit;
  cursor: pointer;
  white-space: nowrap;
}
.wm-pop-btn:hover {
  border-color: var(--accent-500, #7c6aad);
  color: var(--accent-500, #7c6aad);
}
.wm-pop-btn--danger:hover {
  border-color: var(--danger);
  color: var(--danger);
}

/* 空白舆图浮动提示卡：纸面卡片浮在手绘世界平面上（插画本体是 svgOverlay，随图缩放平移） */
.wm-blankcard {
  position: absolute;
  left: 50%;
  top: 40%;
  transform: translate(-50%, -50%);
  z-index: 660; /* 越过烛光暗角（645），浮卡不能被压暗 */
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  padding: 20px 28px 18px;
  border: 1px solid rgba(110, 85, 45, 0.28);
  border-radius: 14px;
  background: rgba(250, 245, 232, 0.94);
  box-shadow: 0 12px 32px rgba(60, 48, 30, 0.16);
  color: rgba(109, 90, 60, 0.85);
  text-align: center;
  pointer-events: none;
  animation: wm-blankcard-bob 6s ease-in-out infinite;
}
@keyframes wm-blankcard-bob {
  0%, 100% { transform: translate(-50%, -50%); }
  50% { transform: translate(-50%, calc(-50% - 4px)); }
}
@media (prefers-reduced-motion: reduce) {
  .wm-blankcard { animation: none; }
}
.wm-blankcard-over {
  font-size: var(--text-xs);
  letter-spacing: 0.42em;
  text-indent: 0.42em;
  color: #b08d3e;
}
.wm-blankcard-title {
  font-family: "Noto Serif SC", "Source Han Serif SC", "STSong", "SimSun", serif;
  font-size: var(--text-2xl);
  font-weight: 700;
  letter-spacing: 0.14em;
  color: rgba(74, 68, 56, 0.78);
}
.wm-blankcard-orn {
  color: rgba(110, 85, 45, 0.45);
  line-height: 1;
}
.wm-blankcard-sub {
  margin-top: 5px;
  font-size: var(--text-xs);
  line-height: 1.9;
  color: var(--text-muted, #a89e90);
}
</style>
