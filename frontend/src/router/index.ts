/**
 * 应用路由（V3.1 F1 新建）。
 *
 * 五个顶层目的地（规格 §3）：
 * - /library            书架
 * - /workspace/:bookId/:chapterId?  写作台（★ 主视图）
 * - /outline/:bookId    大纲板
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
    // 设定中心已整体退役（2026-09-05）：唯一真实编辑面「创作笔记」写入
    // books.global_sys_prompt，消费方全部不在活路（V3 链归档/精修改固定基线）；
    // 其余分区此前已是世界页跳转卡。旧深链一律重定向世界页（canon 先例）。
    path: '/bible/:bookId',
    name: 'bible',
    redirect: (to) => ({
      name: 'world',
      params: { bookId: to.params.bookId },
    }),
  },
  {
    // 文风模块重构 S1：独立文风页（docs/style-module-redesign.md §6.2）——
    // 旧入口 /bible 深链到文风分区的行为退役，此处为新家
    path: '/style/:bookId',
    name: 'style',
    component: () => import('../features/style/containers/StyleView.vue'),
    meta: { title: '文风', rail: true, railKey: 'style' },
  },
  {
    // C1 Canon 融合：独立脑图页退役，旧深链一律重定向到世界页「真相」账本格
    path: '/canon/:bookId',
    name: 'canon',
    redirect: (to) => ({
      name: 'world',
      params: { bookId: to.params.bookId },
      query: { panel: 'canon' },
    }),
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
