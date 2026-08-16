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
import { ref, computed, onMounted, onBeforeUnmount, watch } from 'vue'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import Icon from '../../../components/Icon.vue'
import { useToast } from '../../../composables/useToast'
import { useConfirmDialog } from '../../../composables/useConfirmDialog'
import { useWorld } from '../composables/useWorld'
import { useMapEdit, resolveImageUrl, editUndo, editRedo } from '../composables/useMapEdit'
import { eventPoint, stripPointFromNote, centroid } from '../engine/eventPoint'
import { EVENT_TYPE_COLOR, getTemplate } from '../engine/eventTemplates'
import { formatTime } from '../engine/timeFormat'
import { relationTypeMeta } from '../engine/relationTypes'
import RelationInlineForm from '../presentation/RelationInlineForm.vue'
import type { DrawMode, WorldLocation, WorldMapLayer, WorldRelation } from '../engine/types'

const props = defineProps<{
  bookId: string
  /** 拾取模式：null=浏览, 'location'=点选建地点（点击 emit pick） */
  pickingMode?: 'location' | null
  /** 绘制模式：非 null 时地图点击收集顶点，双击/Enter/完成闭合后 emit draw-complete */
  drawMode?: DrawMode
}>()

const emit = defineEmits<{
  pick: [point: [number, number]]
  'draw-complete': [points: [number, number][]]
  'entity-click': [entityId: string]
}>()

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
 * 空白舆图默认底图：手绘风世界平面（地球大陆轮廓，无标注——空白即未书写）。
 * svgOverlay 绑在内部坐标上，随地图缩放/平移，像一张真实的古旧世界地图；
 * 海岸线走 #wm-ink 位移滤镜出毛边，纬线/经线淡虚线，南缘一道未知的南方大陆虚影。
 */
const BLANK_ATLAS_INNER = `
  <g stroke="rgba(110,85,45,.12)" stroke-width="1" fill="none" stroke-dasharray="4 6">
    <path d="M0,86 H1000"/><path d="M0,190 H1000"/><path d="M0,293 H1000"/><path d="M0,397 H1000"/>
    <path d="M167,0 V500"/><path d="M333,0 V500"/><path d="M500,0 V500"/><path d="M667,0 V500"/><path d="M833,0 V500"/>
  </g>
  <g filter="url(#wm-ink)" stroke="rgba(110,85,45,.55)" stroke-width="1.7" stroke-linejoin="round" fill="rgba(110,85,45,.06)">
    <!-- 北美（阿拉斯加→哈德逊湾→中美地峡→墨西哥湾→佛罗里达→纽芬兰） -->
    <path d="M33,67 L47,71 L42,79 L56,93 L69,97 L83,86 L97,90 L125,97 L139,107 L153,124 L156,131 L156,145 L160,163 L172,176 L175,180 L183,190 L194,214 L189,197 L183,184 L206,214 L222,234 L236,238 L244,245 L250,247 L258,250 L264,259 L269,262 L285,267 L286,264 L269,259 L262,254 L258,239 L255,233 L256,219 L249,219 L246,229 L233,228 L228,217 L231,203 L246,191 L252,192 L256,188 L266,190 L271,197 L272,201 L275,206 L277,204 L276,195 L274,188 L275,183 L278,180 L290,172 L289,166 L294,153 L303,147 L306,148 L309,141 L319,143 L324,138 L331,134 L322,128 L346,131 L354,129 L344,122 L333,114 L322,103 L314,93 L286,103 L272,114 L244,97 L236,90 L250,76 L264,66 L239,62 L194,62 L153,52 L111,53 Z"/>
    <!-- 南美（巴西鼓包→拉普拉塔→巴塔哥尼亚→智利峡湾→秘鲁海岸） -->
    <path d="M292,262 L303,250 L314,257 L331,262 L339,269 L356,276 L358,293 L367,293 L393,321 L381,345 L372,376 L356,403 L344,412 L337,424 L328,448 L319,466 L317,482 L306,470 L297,466 L296,455 L297,441 L297,421 L301,407 L302,390 L304,374 L305,357 L292,341 L286,334 L276,300 L285,279 L285,267 Z"/>
    <path d="M310,483 L322,480 L326,486 L315,490 Z"/>
    <!-- 格陵兰 + 冰岛 -->
    <path d="M379,87 L368,80 L356,66 L342,45 L328,31 L352,21 L389,10 L417,17 L431,24 L439,45 L425,55 L394,69 Z"/>
    <path d="M447,69 L453,66 L459,69 L456,73 L449,73 Z"/>
    <!-- 非洲（突尼斯→锡德拉湾→红海→非洲之角→好望角→几内亚湾→塞内加尔） -->
    <path d="M484,170 L508,166 L529,166 L531,165 L542,181 L553,188 L556,183 L583,185 L590,190 L597,210 L606,224 L610,241 L619,252 L643,252 L642,257 L633,279 L612,302 L609,315 L603,356 L599,376 L586,396 L578,408 L556,413 L551,410 L540,371 L533,355 L537,336 L534,314 L526,290 L515,277 L500,275 L486,275 L479,274 L463,264 L456,252 L451,242 L456,231 L457,211 L473,185 Z"/>
    <path d="M631,345 L638,352 L640,365 L634,378 L628,368 L626,355 Z"/>
    <!-- 欧亚（伊比利亚→斯堪的纳维亚→白令→堪察加→中国海岸→中南半岛→印度→阿拉伯→地中海） -->
    <path d="M475,166 L474,152 L478,143 L492,143 L497,140 L487,127 L496,123 L505,117 L514,112 L528,108 L526,104 L529,94 L526,93 L529,87 L516,90 L515,85 L529,75 L539,59 L553,53 L571,48 L592,72 L597,69 L614,62 L639,59 L681,55 L694,45 L722,41 L764,31 L792,26 L806,38 L861,45 L917,48 L972,52 L994,71 L972,66 L972,72 L944,115 L936,90 L933,97 L919,88 L897,114 L881,131 L866,145 L846,156 L834,162 L840,164 L838,186 L828,209 L824,212 L817,216 L800,219 L796,221 L801,238 L803,251 L797,263 L791,257 L779,247 L787,278 L789,285 L788,289 L779,274 L774,259 L767,235 L761,235 L758,221 L747,218 L740,224 L731,232 L723,248 L722,258 L715,265 L712,259 L706,240 L702,228 L702,219 L686,208 L671,206 L635,190 L636,195 L643,206 L650,209 L661,205 L656,203 L663,212 L653,235 L625,250 L621,250 L608,221 L597,191 L596,185 L599,178 L596,167 L585,166 L575,166 L566,162 L559,163 L563,168 L554,151 L542,141 L538,136 L534,137 L538,143 L551,155 L544,159 L540,153 L534,149 L529,146 L525,140 L520,143 L508,144 L506,150 L499,157 L488,167 L484,169 Z"/>
    <!-- 不列颠群岛 / 地中海岛屿 -->
    <path d="M494,107 L498,95 L503,86 L509,79 L514,86 L511,95 L512,103 L506,110 L498,110 Z"/>
    <path d="M483,107 L486,100 L492,97 L494,104 L490,110 L484,110 Z"/>
    <path d="M533,159 L542,158 L545,162 L536,163 Z"/>
    <ellipse cx="524" cy="152" rx="3" ry="5"/><ellipse cx="522" cy="146" rx="2.5" ry="4"/>
    <path d="M556,171 L566,170" fill="none"/>
    <!-- 内陆海（黑海/里海/咸海/贝加尔） -->
    <path d="M575,148 L585,140 L600,135 L612,136 L620,132 L635,134 L645,140 L638,147 L620,151 L598,152 L582,151 Z" fill="none"/>
    <path d="M642,166 L649,152 L651,138 L645,122 L637,131 L634,148 L637,160 Z" fill="none"/>
    <ellipse cx="668" cy="138" rx="3" ry="2" fill="none"/>
    <path d="M790,112 L810,106" fill="none"/>
    <!-- 东亚岛弧（日本/台湾/海南/菲律宾） -->
    <path d="M875,169 L884,158 L893,148 L900,141 L906,148 L900,158 L890,166 L881,172 Z"/>
    <path d="M901,134 L908,130 L912,136 L905,140 Z"/>
    <path d="M872,175 L876,172 L878,177 L873,179 Z"/>
    <path d="M829,224 L832,218 L835,222 L831,228 Z"/>
    <ellipse cx="807" cy="229" rx="4" ry="3"/>
    <path d="M833,255 L838,245 L843,238 L846,244 L842,255 L838,262 Z"/>
    <path d="M841,232 L845,226 L848,231 L844,236 Z"/>
    <!-- 南亚岛屿 -->
    <ellipse cx="719" cy="271" rx="2.5" ry="4"/>
    <circle cx="710" cy="285" r="1.2"/><circle cx="713" cy="290" r="1.2"/>
    <!-- 南洋群岛（苏门答腊/爪哇/婆罗洲/苏拉威西/新几内亚） -->
    <path d="M770,270 L785,282 L800,295 L810,305 L805,308 L790,297 L775,283 L765,273 Z"/>
    <path d="M810,312 L825,315 L840,318 L845,320 L830,320 L815,317 Z"/>
    <path d="M820,275 L835,270 L850,278 L855,293 L845,303 L830,300 L818,288 Z"/>
    <path d="M858,285 L866,280 L872,286 L865,295 L860,300 Z"/>
    <path d="M880,303 L900,297 L925,293 L940,297 L930,305 L905,308 L885,307 Z"/>
    <circle cx="850" cy="322" r="1.5"/>
    <!-- 澳洲 + 塔斯马尼亚 + 新西兰 -->
    <path d="M821,403 L828,414 L844,393 L861,396 L878,386 L903,424 L907,428 L920,410 L925,388 L905,352 L896,330 L894,338 L889,353 L878,341 L867,333 L863,335 L844,338 L816,370 L814,381 L819,402 Z"/>
    <path d="M903,431 L910,428 L913,434 L906,438 Z"/>
    <path d="M972,424 L978,417 L982,421 L976,430 Z"/>
    <path d="M974,438 L981,434 L984,441 L977,447 Z"/>
    <!-- 大湖 / 咸湖 -->
    <ellipse cx="264" cy="135" rx="4" ry="2.5" fill="none"/>
    <ellipse cx="272" cy="133" rx="3.5" ry="2" fill="none"/>
    <ellipse cx="278" cy="138" rx="3" ry="2" fill="none"/>
    <ellipse cx="191" cy="152" rx="2.5" ry="1.5" fill="none"/>
    <!-- 大河（细流） -->
    <g stroke="rgba(110,85,45,.38)" stroke-width="1" fill="none">
      <path d="M310,283 C330,278 345,285 358,290"/>
      <path d="M590,190 L587,215 L584,240"/>
      <path d="M782,203 L810,196 L836,190"/>
      <path d="M252,192 L254,170 L257,150"/>
      <path d="M534,314 L548,302"/>
    </g>
    <!-- 山脉（小三角） -->
    <g stroke="rgba(110,85,45,.4)" stroke-width="0.9" fill="none">
      <path d="M180,145 l4,-6 l4,6 M196,165 l4,-6 l4,6 M212,185 l4,-6 l4,6"/>
      <path d="M291,310 l4,-6 l4,6 M295,350 l4,-6 l4,6 M299,390 l4,-6 l4,6 M300,430 l4,-6 l4,6"/>
      <path d="M528,133 l4,-5 l4,6 M540,132 l4,-5 l4,6"/>
      <path d="M490,178 l4,-5 l4,6"/>
      <path d="M705,203 l4,-6 l4,6 M720,199 l4,-6 l4,6 M735,196 l4,-6 l4,6"/>
      <path d="M600,310 l4,-5 l4,6"/>
      <path d="M672,90 l4,-5 l4,6 M675,105 l4,-5 l4,6"/>
      <path d="M850,80 l4,-5 l4,6"/>
    </g>
    <!-- 国界（古图点状虚线） -->
    <g stroke="rgba(110,85,45,.42)" stroke-width="0.9" fill="none" stroke-dasharray="1.2 3" stroke-linecap="round">
      <path d="M150,125 L205,120 L255,124 L300,120"/>
      <path d="M190,190 L225,186 L262,180"/>
      <path d="M96,97 L108,75"/>
      <path d="M300,252 L320,275 L340,290 L355,310"/>
      <path d="M355,345 L365,368 L360,385"/>
      <path d="M286,300 L292,340 L297,380"/>
      <path d="M490,158 L505,155"/>
      <path d="M530,140 L545,132"/>
      <path d="M560,128 L575,125"/>
      <path d="M572,85 L580,100"/>
      <path d="M500,168 L498,185"/>
      <path d="M566,180 L570,200"/>
      <path d="M575,217 L605,214"/>
      <path d="M480,200 L510,205 L530,210"/>
      <path d="M505,260 L515,275"/>
      <path d="M560,350 L585,360"/>
      <path d="M750,120 L800,130 L850,140 L880,130"/>
      <path d="M700,200 L740,190 L770,195"/>
      <path d="M695,215 L700,225"/>
      <path d="M640,120 L690,125"/>
      <path d="M615,190 L630,200"/>
      <path d="M850,340 L855,400"/>
      <path d="M885,335 L890,415"/>
    </g>
  </g>
  <path d="M60,470 C250,452 420,462 560,455 C700,448 840,460 940,452" stroke="rgba(110,85,45,.3)" stroke-width="1.2" fill="none" stroke-dasharray="6 5"/>
  <g stroke="rgba(110,85,45,.28)" stroke-width="1" fill="none">
    <path d="M195,318 q5,-5 10,0"/><path d="M425,255 q5,-5 10,0"/><path d="M695,335 q5,-5 10,0"/>
    <path d="M495,445 q5,-5 10,0"/><path d="M115,145 q5,-5 10,0"/>
  </g>`

/** 空白舆图 SVG 元素（⚠ Leaflet SVGOverlay 只接受元素——传字符串不会被解析成 DOM，addLayer 直接抛错） */
function makeBlankAtlasEl(): SVGElement {
  const el = document.createElementNS('http://www.w3.org/2000/svg', 'svg')
  el.setAttribute('xmlns', 'http://www.w3.org/2000/svg')
  el.setAttribute('viewBox', '0 0 1000 500')
  el.innerHTML = BLANK_ATLAS_INNER
  return el
}

// 地点三类配色（空心环点，与实心人物点区分）
const LOC_KIND_COLOR: Record<string, string> = {
  point: '#7c6aad',
  region: '#10b981',
  route: '#60a5fa',
}

function esc(s: unknown): string {
  return String(s ?? '').replace(/[&<>"]/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c] as string,
  )
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

/** 空白舆图在内部坐标中的落位（2:1 平面几乎铺满画布，视野初始也框到这里） */
const BLANK_ATLAS_BOUNDS = L.latLngBounds([
  [200, 50],
  [800, 950],
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

const PEN_COLORS = ['#6b5537', '#3f6212', '#1d4ed8', '#475569', '#b91c1c', '#1c1917']
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
    ctx.strokeStyle = s.color
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
function distToSeg(p: L.Point, a: L.Point, b: L.Point): number {
  const dx = b.x - a.x
  const dy = b.y - a.y
  const len2 = dx * dx + dy * dy
  if (len2 === 0) return p.distanceTo(a)
  let t = ((p.x - a.x) * dx + (p.y - a.y) * dy) / len2
  t = Math.max(0, Math.min(1, t))
  return p.distanceTo(L.point(a.x + t * dx, a.y + t * dy))
}

function renderMarkers() {
  if (!map || !markerLayer) return
  markerLayer.clearLayers()
  if (!layerVisible.value.locations) return
  const withLabel = showLabels()
  for (const loc of locations.value) {
    if (loc.coord_x == null || loc.coord_y == null) continue
    const color = LOC_KIND_COLOR[loc.kind] || LOC_KIND_COLOR.point
    const icon = L.divIcon({
      className: 'wm-loc-icon',
      html: `<div class="wm-loc" style="--c:${color}"><span class="wm-loc-ring"></span>${
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
    m.bindPopup(buildLocPopupHtml(loc))
    markerLayer.addLayer(m)
  }
}

/** 地点 popup：名字 + 类型/简介 + 就地改名/删除（事件在 popupopen 委托绑定） */
function buildLocPopupHtml(loc: WorldLocation): string {
  return (
    `<div class="wm-pop-title">${esc(loc.name)}</div>` +
    `<span class="wm-pop-sub">${esc(loc.kind)}</span>` +
    (loc.intro ? `<div class="wm-pop-intro">${esc(loc.intro)}</div>` : '') +
    `<div class="wm-pop-edit" data-loc-id="${loc.id}">` +
    `<input class="wm-pop-input" data-loc-name value="${esc(loc.name)}" />` +
    `<button class="wm-pop-btn" data-act="save" title="保存改名">改名</button>` +
    `<button class="wm-pop-btn wm-pop-btn--danger" data-act="del" title="删除地点">删除</button>` +
    `</div>`
  )
}

/** move 轨迹线：完成的=点画墨线；在途=青墨虚线流动（行军中） */
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
}

// ===== 实体层（单一画布）：所有实体统一上地图 =====
// 位置解析优先级：事件推演位置（人物 state）/ 疆域质心（势力）→ 画布锚位（作者摆位）。
// 拖拽语义分流：有故事的角色受历史约束（拖=录 move 事件，可撤销）；
// 没故事的（无事件角色/资产/无疆域势力）自由摆放（拖=移画布锚位）。

const entityMarkers = new Map<string, L.Marker>()
const highlightEntityId = ref<string | null>(null)

interface EntityDisplay {
  x: number
  y: number
  derived: boolean // true=事态推演位置；false=画布锚位
}

function entityDisplayPosition(entId: string): EntityDisplay | null {
  const cs = worldState.value.character_states.find((c) => c.entity_id === entId)
  if (cs && !cs.alive) return null // 死者不显示（史书只记生前轨迹；侧栏/抽屉仍可达）
  if (cs?.position) return { x: cs.position[0], y: cs.position[1], derived: true }
  const ts = worldState.value.territory_states.find((t) => t.faction_id === entId)
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
  character: '#f59e0b',
  faction: '#10b981',
  asset: '#c9a227',
}

function renderEntities() {
  if (!map || !entityLayer) return
  entityLayer.clearLayers()
  entityMarkers.clear()
  if (!layerVisible.value.characters) return
  const withLabel = showLabels()
  const hl = highlightEntityId.value
  const related = new Set<string>()
  if (hl) {
    for (const r of relations.value) {
      if (r.source_entity_id === hl) related.add(r.target_entity_id)
      if (r.target_entity_id === hl) related.add(r.source_entity_id)
    }
  }
  for (const ent of entities.value) {
    const pos = entityDisplayPosition(ent.id)
    if (!pos) continue
    const [x, y] = [pos.x, pos.y]
    const t = ent.entity_type
    const color = NODE_COLOR[t] || NODE_COLOR.character
    const star = (ent.importance ?? 1) >= 7
    const cs = worldState.value.character_states.find((c) => c.entity_id === ent.id)
    const moving = !!cs?.label?.includes('在途')
    const dimmed = !!hl && ent.id !== hl && !related.has(ent.id)
    const icon = L.divIcon({
      className: 'wm-char-icon',
      html: `<div class="wm-node wm-node--${t}${moving ? ' wm-char--moving' : ''}${
        star ? ' wm-char--star' : ''
      }${dimmed ? ' wm-node--dim' : ''}" style="--c:${color}"><span class="wm-node-head"></span>${
        withLabel ? `<span class="wm-char-name">${esc(ent.name)}</span>` : ''
      }</div>`,
      iconSize: [0, 0],
    })
    // 有疆域的势力节点不可拖（疆域几何是事实）；其余可拖
    const draggable = !inEditMode.value && !(pos.derived && t === 'faction')
    const m = L.marker([y, x], { icon, zIndexOffset: 500, draggable, interactive: !inEditMode.value })
    entityMarkers.set(ent.id, m)

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
    entityLayer.addLayer(m)
  }
}

// ===== 关系层：活跃边画在两端实体当前位置之间，随游标演变 =====

let prevActiveRelIds = new Set<string>()

function renderRelations() {
  if (!map || !relationLayer) return
  relationLayer.clearLayers()
  if (!layerVisible.value.relations) {
    prevActiveRelIds = new Set()
    return
  }
  const activeIds = new Set<string>()
  for (const rs of worldState.value.relation_states) if (rs.active) activeIds.add(rs.relation_id)
  const hl = highlightEntityId.value
  for (const r of relations.value) {
    if (!activeIds.has(r.id)) continue
    const a = entityDisplayPosition(r.source_entity_id)
    const b = entityDisplayPosition(r.target_entity_id)
    if (!a || !b) continue
    const meta = relationTypeMeta(r.relation_type)
    const born = prevActiveRelIds.size > 0 && !prevActiveRelIds.has(r.id) // 激活瞬间生长
    // 三点轻弧（中点垂直偏移），随端点移动伸缩
    const mx = (a.x + b.x) / 2
    const my = (a.y + b.y) / 2
    const dx = b.x - a.x
    const dy = b.y - a.y
    const len = Math.hypot(dx, dy) || 1
    const off = Math.min(60, len * 0.12)
    const cx = mx - (dy / len) * off
    const cy = my + (dx / len) * off
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
    relationLayer.addLayer(line)
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
  let bestId: string | null = null
  let bestD = 26 * 26
  for (const [id, mk] of entityMarkers) {
    if (id === sourceId) continue
    const p = map.latLngToContainerPoint(mk.getLatLng())
    const d = (p.x - px) ** 2 + (p.y - py) ** 2
    if (d < bestD) {
      bestD = d
      bestId = id
    }
  }
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

function resampleRing(pts: [number, number][], n: number): [number, number][] {
  if (pts.length === 0) return []
  if (pts.length === 1) return Array.from({ length: n }, () => [...pts[0]] as [number, number])
  const segs: number[] = []
  let total = 0
  for (let i = 0; i < pts.length; i++) {
    const a = pts[i]
    const b = pts[(i + 1) % pts.length] // 闭合环采样
    const len = Math.hypot(b[0] - a[0], b[1] - a[1])
    segs.push(len)
    total += len
  }
  const out: [number, number][] = []
  for (let k = 0; k < n && total > 0; k++) {
    let target = (k / n) * total
    for (let i = 0; i < segs.length; i++) {
      if (target <= segs[i] || i === segs.length - 1) {
        const t = segs[i] === 0 ? 0 : Math.min(1, target / segs[i])
        const a = pts[i]
        const b = pts[(i + 1) % pts.length]
        out.push([a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t])
        break
      }
      target -= segs[i]
    }
  }
  return out
}

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
    const color = EVENT_TYPE_COLOR[e.event_type] || '#94a3b8'
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
 */
function renderEventMarkers() {
  if (!map || !eventLayer) return
  eventLayer.clearLayers()
  if (!layerVisible.value.events) return
  const t = currentTime.value
  for (const e of events.value) {
    if (e.time_start > t) continue
    const pt = eventPoint(e, locationsById.value)
    if (!pt) continue
    const color = EVENT_TYPE_COLOR[e.event_type] || '#94a3b8'
    const label = getTemplate(e.event_type)?.label || e.event_type
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
    eventLayer.addLayer(m)
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

/** 闭合绘制：territory 需 ≥3 顶点，move-path ≥0；不达标静默忽略（继续画） */
function finishDraw() {
  if (!props.drawMode) return
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
    if (props.drawMode) {
      // 绘制优先：点击收集顶点（[lng,lat] → 内部 [x,y]，带时间戳供双击识别）
      draftPoints.value.push({ p: [e.latlng.lng, e.latlng.lat], t: Date.now() })
      renderDraw()
      return
    }
    if (mapEditMode.value === 'images') {
      selectedLayerId.value = null // 点空白取消选中（图上的点击已被 stopPropagation）
      return
    }
    if (props.pickingMode === 'location') {
      emit('pick', [e.latlng.lng, e.latlng.lat])
    }
  })
  map.on('dblclick', (e: L.LeafletMouseEvent) => {
    if (!props.drawMode) return
    // 双击闭合。双击会伴随 1~2 次 click（数量随事件源不定，真实浏览器为 2）——
    // 把「与双击同位置且 600ms 内」的尾部合成顶点剥掉再闭合；
    // 用户真实顶点时间更早或位置不同，不会被误删。
    const now = Date.now()
    let removed = 0
    while (removed < 2) {
      const last = draftPoints.value[draftPoints.value.length - 1]
      if (!last) break
      const sameSpot =
        Math.abs(last.p[0] - e.latlng.lng) < 0.01 && Math.abs(last.p[1] - e.latlng.lat) < 0.01
      if (now - last.t < 600 && sameSpot) {
        draftPoints.value.pop()
        removed++
      } else break
    }
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
  })
  // 笔迹 canvas 与地图视图同步（拖动/缩放/窗口变化 → rAF 重绘）
  map.on('move zoom viewreset resize', scheduleStrokeRedraw)
  // 地点 popup 的就地改名/删除（popup DOM 随开随建，委托绑定无泄漏）
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
    box.querySelector('[data-act="del"]')?.addEventListener('click', async () => {
      const loc = locations.value.find((l) => l.id === locId)
      map?.closePopup()
      const ok = await showConfirm({
        title: '删除地点',
        message: `确定删除地点「${loc?.name || ''}」吗？`,
        warning: '关联事件的地点引用会被清空（可用 Ctrl+Z 撤销）。',
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
watch([worldState, currentTime, events], () => {
  spawnRipples(currentTime.value)
  renderTracks()
  renderEntities()
  renderRelations()
  renderTerritory()
  renderEventMarkers()
}, { deep: true })
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
function focusAt(x: number, y: number, title?: string) {
  if (!map) return
  map.setView([y, x], Math.max(map.getZoom(), 1), { animate: true })
  if (title) {
    L.popup({ closeButton: true })
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

    <!-- 墨迹滤镜 defs：疆域 SVG 位移毛边（古卷水彩晕染） -->
    <svg class="wm-svg-defs" width="0" height="0" aria-hidden="true">
      <defs>
        <filter id="wm-ink" x="-8%" y="-8%" width="116%" height="116%">
          <feTurbulence type="fractalNoise" baseFrequency="0.045" numOctaves="2" seed="7" result="n" />
          <feDisplacementMap in="SourceGraphic" in2="n" scale="4.5" xChannelSelector="R" yChannelSelector="G" />
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

    <!-- 图例（单一画布的编辑入口可发现性；默认收起为一行，hover 展开手势明细） -->
    <div v-if="!inEditMode && hasVisibleNodes" class="wm-legend">
      <span class="wm-legend-tag">图例</span>
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
  /* 独立层叠上下文：Leaflet 内部 pane z-index 高达 700，
     不隔离会压过页面 z-110 的模态/确认弹窗 */
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
  border-color: #dc2626;
  color: #dc2626;
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
  font-size: 11px;
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
  width: 13px;
  height: 13px;
  border-radius: 9999px;
  background: rgba(249, 242, 226, 0.92);
  border: 3px solid var(--c, #7c6aad);
  box-shadow: 0 1px 5px rgba(60, 44, 22, 0.3);
  transition: transform 0.15s ease-out;
}
.wm-loc:hover .wm-loc-ring {
  transform: scale(1.25);
}
.wm-loc-name {
  font-size: 11px;
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
  background: var(--c, #f59e0b);
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
  font-size: 11px;
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
  background: var(--c, #f59e0b);
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
  font-size: 10px;
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
.wm-legend:hover .wm-legend-pop {
  display: block;
}
.wm-legend-row {
  display: flex;
  align-items: center;
  gap: 7px;
  margin: 4px 0;
  font-size: 11px;
  color: rgba(74, 68, 56, 0.85);
}
.wm-legend-row kbd {
  font-family: inherit;
  font-size: 9.5px;
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
  font-size: 11px;
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
  font-size: 10px;
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
  border: 2px solid var(--c, #94a3b8);
  animation: wm-ripple 1.4s ease-out forwards;
}
.wm-ripple::after {
  content: '';
  position: absolute;
  inset: -2px;
  border-radius: 9999px;
  border: 1.5px solid var(--c, #94a3b8);
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
  border: 2.5px solid var(--c, #94a3b8);
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
  font-size: 11px;
}
.wm-pop-title {
  font-weight: 700;
  font-size: 13px;
  margin-bottom: 2px;
  color: var(--text-primary, #2c2c2c);
}
.wm-pop-intro {
  margin-top: 4px;
  font-size: 11.5px;
  line-height: 1.5;
  color: var(--text-secondary, #64748b);
  max-width: 200px;
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
  color: var(--text-secondary, #64748b);
  font-size: 11px;
  font-family: inherit;
  cursor: pointer;
  white-space: nowrap;
}
.wm-pop-btn:hover {
  border-color: var(--accent-500, #7c6aad);
  color: var(--accent-500, #7c6aad);
}
.wm-pop-btn--danger:hover {
  border-color: #dc2626;
  color: #dc2626;
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
  font-size: 9px;
  letter-spacing: 0.42em;
  text-indent: 0.42em;
  color: #b08d3e;
}
.wm-blankcard-title {
  font-family: "Noto Serif SC", "Source Han Serif SC", "STSong", "SimSun", serif;
  font-size: 19px;
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
  font-size: 11px;
  line-height: 1.9;
  color: var(--text-muted, #a89e90);
}
</style>
