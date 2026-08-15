/**
 * 应用路由（V3.1 F1 新建）。
 *
 * 五个顶层目的地（规格 §3）：
 * - /library            书架
 * - /workspace/:bookId/:chapterId?  写作台（★ 主视图）
 * - /outline/:bookId    大纲板
 * - /bible/:bookId      设定中心
 * - /insights/:bookId   数据
 *
 * 模式：createWebHashHistory —— Electron 打包后 file:// 加载 dist/index.html，
 * hash 路由刷新不 404，开发与生产行为一致。
 */
import { createRouter, createWebHashHistory, type RouteRecordRaw } from 'vue-router'

const routes: RouteRecordRaw[] = [
  {
    path: '/',
    redirect: '/library',
  },
  {
    path: '/library',
    name: 'library',
    component: () => import('../features/library/containers/LibraryView.vue'),
    meta: { title: '书架', rail: true, railKey: 'library' },
  },
  {
    path: '/workspace/:bookId/:chapterId?',
    name: 'workspace',
    component: () => import('../features/workspace/containers/WorkspaceView.vue'),
    meta: { title: '写作台', rail: true, railKey: 'workspace' },
  },
  {
    path: '/outline/:bookId',
    name: 'outline',
    component: () => import('../features/outline/containers/OutlineView.vue'),
    meta: { title: '大纲板', rail: true, railKey: 'outline' },
  },
  {
    path: '/bible/:bookId',
    name: 'bible',
    component: () => import('../features/bible/containers/BibleView.vue'),
    meta: { title: '设定中心', rail: true, railKey: 'bible' },
  },
  {
    path: '/canon/:bookId',
    name: 'canon',
    component: () => import('../features/canon/containers/CanonView.vue'),
    meta: { title: '作者脑中世界（Canon）', rail: true, railKey: 'canon' },
  },
  {
    path: '/world/:bookId',
    name: 'world',
    component: () => import('../features/world/containers/WorldView.vue'),
    meta: { title: '世界设定', rail: true, railKey: 'world' },
  },
  {
    path: '/insights/:bookId',
    name: 'insights',
    component: () => import('../features/insights/containers/InsightsView.vue'),
    meta: { title: '数据', rail: true, railKey: 'insights' },
  },
  // 兼容旧入口：无 bookId 的 workspace 重定向到书架
  {
    path: '/workspace',
    redirect: '/library',
  },
]

export const router = createRouter({
  history: createWebHashHistory(),
  routes,
})

export default router
