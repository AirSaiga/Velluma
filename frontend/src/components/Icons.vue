<script setup lang="ts">
// 专业的 SVG 图标系统 - Heroicons 风格

defineProps<{
  size?: number
  class?: string
}>()
</script>

<template>
  <!-- 角色图标 -->
  <svg v-if="$slots.default?.()[0]?.children === 'users'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" :width="size || 20" :height="size || 20" :class="$props.class">
    <path stroke-linecap="round" stroke-linejoin="round" d="M15 19.128a9.38 9.38 0 002.625.372 9.337 9.337 0 004.121-.952 4.125 4.125 0 00-7.533-2.493M15 19.128v-.003c0-1.113-.285-2.16-.786-3.07M15 19.128v.106A12.318 12.318 0 018.624 21c-2.331 0-4.512-.645-6.374-1.766l-.001-.109a6.375 6.375 0 0111.964-3.07M12 6.375a3.375 3.375 0 11-6.75 0 3.375 3.375 0 016.75 0zm8.25 2.25a2.625 2.625 0 11-5.25 0 2.625 2.625 0 015.25 0z" />
  </svg>

  <svg v-else-if="$slots.default?.()[0]?.children === 'user'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" :width="size || 20" :height="size || 20" :class="$props.class">
    <path stroke-linecap="round" stroke-linejoin="round" d="M15.75 6a3.75 3.75 0 11-7.5 0 3.75 3.75 0 017.5 0zM4.501 20.118a7.5 7.5 0 0114.998 0A17.933 17.933 0 0112 21.75c-2.676 0-5.216-.584-7.499-1.632z" />
  </svg>

  <!-- 书籍/规则图标 -->
  <svg v-else-if="$slots.default?.()[0]?.children === 'book'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" :width="size || 20" :height="size || 20" :class="$props.class">
    <path stroke-linecap="round" stroke-linejoin="round" d="M12 6.042A8.967 8.967 0 006 3.75c-1.052 0-2.062.18-3 .512v14.25A8.987 8.987 0 016 18c2.305 0 4.408.867 6 2.292m0-14.25a8.966 8.966 0 016-2.292c1.052 0 2.062.18 3 .512v14.25A8.987 8.987 0 0018 18a8.967 8.967 0 00-6 2.292m0-14.25v14.25" />
  </svg>

  <svg v-else-if="$slots.default?.()[0]?.children === 'document'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" :width="size || 20" :height="size || 20" :class="$props.class">
    <path stroke-linecap="round" stroke-linejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m2.25 0H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z" />
  </svg>

  <!-- 风格/闪耀图标 -->
  <svg v-else-if="$slots.default?.()[0]?.children === 'sparkles'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" :width="size || 20" :height="size || 20" :class="$props.class">
    <path stroke-linecap="round" stroke-linejoin="round" d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09zM18.259 8.715L18 9.75l-.259-1.035a3.375 3.375 0 00-2.455-2.456L14.25 6l1.036-.259a3.375 3.375 0 002.455-2.456L18 2.25l.259 1.035a3.375 3.375 0 002.456 2.456L21.75 6l-1.035.259a3.375 3.375 0 00-2.456 2.456zM16.894 20.567L16.5 21.75l-.394-1.183a2.25 2.25 0 00-1.423-1.423L13.5 18.75l1.183-.394a2.25 2.25 0 001.423-1.423l.394-1.183.394 1.183a2.25 2.25 0 001.423 1.423l1.183.394-1.183.394a2.25 2.25 0 00-1.423 1.423z" />
  </svg>

  <svg v-else-if="$slots.default?.()[0]?.children === 'paint-brush'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" :width="size || 20" :height="size || 20" :class="$props.class">
    <path stroke-linecap="round" stroke-linejoin="round" d="M9.53 16.122a3 3 0 00-5.78 1.128 2.25 2.25 0 01-2.4 2.245 4.5 4.5 0 008.4-2.245c0-.399-.077-.78-.22-1.128zm0 0a15.998 15.998 0 003.388-1.62m-5.048 4.025a3 3 0 01-2.455-2.456L12 3.5l5.452 9.128a3 3 0 01-2.455 2.456 16.002 16.002 0 00-5.469 1.638z" />
  </svg>

  <!-- 地图图标 -->
  <svg v-else-if="$slots.default?.()[0]?.children === 'map-pin'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" :width="size || 20" :height="size || 20" :class="$props.class">
    <path stroke-linecap="round" stroke-linejoin="round" d="M15 10.5a3 3 0 11-6 0 3 3 0 016 0z" />
    <path stroke-linecap="round" stroke-linejoin="round" d="M19.5 10.5c0 7.142-7.5 11.25-7.5 11.25S4.5 17.642 4.5 10.5a7.5 7.5 0 1115 0z" />
  </svg>

  <svg v-else-if="$slots.default?.()[0]?.children === 'map'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" :width="size || 20" :height="size || 20" :class="$props.class">
    <path stroke-linecap="round" stroke-linejoin="round" d="M9 6.75V15m6-6v8.25m.503 3.498l4.875-2.437c.381-.19.622-.58.622-1.006V4.82c0-.836-.88-1.38-1.628-1.006l-3.869 1.934c-.317.159-.69.159-1.006 0L9.503 3.252a1.125 1.125 0 00-1.006 0L3.622 5.689C3.24 5.88 3 6.27 3 6.695V19.18c0 .836.88 1.38 1.628 1.006l3.869-1.934c.317-.159.69-.159 1.006 0l4.994 2.497c.317.158.69.158 1.006 0z" />
  </svg>

  <!-- 指导/评论图标 -->
  <svg v-else-if="$slots.default?.()[0]?.children === 'chat'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" :width="size || 20" :height="size || 20" :class="$props.class">
    <path stroke-linecap="round" stroke-linejoin="round" d="M7.5 8.25h9m-9 3H12m-9.75 1.51c0 1.6 1.123 2.994 2.707 3.227 1.129.166 2.27.293 3.423.379.35.026.67.21.865.501L12 21l2.755-4.133a1.14 1.14 0 01.865-.501 48.172 48.172 0 003.423-.379c1.584-.233 2.707-1.626 2.707-3.228V6.741c0-1.602-1.123-2.995-2.707-3.228A48.394 48.394 0 0012 3c-2.392 0-4.744.015-7.053.072-1.584.233-2.707 1.626-2.707 3.228v6.741z" />
  </svg>

  <svg v-else-if="$slots.default?.()[0]?.children === 'light-bulb'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" :width="size || 20" :height="size || 20" :class="$props.class">
    <path stroke-linecap="round" stroke-linejoin="round" d="M12 18v-5.25m0 0a6.01 6.01 0 001.5-.189m-1.5.189a6.01 6.01 0 01-1.5-.189m3.75 7.478a12.06 12.06 0 01-4.5 0m3.75 2.383a14.406 14.406 0 01-3 0M14.25 18v-.192c0-.983.658-1.823 1.508-2.316a7.5 7.5 0 10-7.517 0c.85.493 1.509 1.333 1.509 2.316V18" />
  </svg>

  <!-- 笔记图标 -->
  <svg v-else-if="$slots.default?.()[0]?.children === 'pencil-square'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" :width="size || 20" :height="size || 20" :class="$props.class">
    <path stroke-linecap="round" stroke-linejoin="round" d="M16.862 4.487l1.687-1.688a1.875 1.875 0 112.652 2.652L10.582 16.07a4.5 4.5 0 01-1.897 1.13L6 18l.8-2.685a4.5 4.5 0 011.13-1.897l8.932-8.931zm0 0L19.5 7.125M18 14v4.75A2.25 2.25 0 0115.75 21H5.25A2.25 2.25 0 013 18.75V8.25A2.25 2.25 0 015.25 6H10" />
  </svg>

  <svg v-else-if="$slots.default?.()[0]?.children === 'document'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" :width="size || 20" :height="size || 20" :class="$props.class">
    <path stroke-linecap="round" stroke-linejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z" />
  </svg>

  <!-- 操作图标 -->
  <svg v-else-if="$slots.default?.()[0]?.children === 'plus'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" :width="size || 20" :height="size || 20" :class="$props.class">
    <path stroke-linecap="round" stroke-linejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
  </svg>

  <svg v-else-if="$slots.default?.()[0]?.children === 'pencil'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" :width="size || 20" :height="size || 20" :class="$props.class">
    <path stroke-linecap="round" stroke-linejoin="round" d="M16.862 4.487l1.687-1.688a1.875 1.875 0 112.652 2.652L6.832 19.82a4.5 4.5 0 01-1.897 1.13l-2.685.8.8-2.685a4.5 4.5 0 011.13-1.897L16.863 4.487zm0 0L19.5 7.125" />
  </svg>

  <svg v-else-if="$slots.default?.()[0]?.children === 'trash'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" :width="size || 20" :height="size || 20" :class="$props.class">
    <path stroke-linecap="round" stroke-linejoin="round" d="M14.74 9l-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 01-2.244 2.077H8.084a2.25 2.25 0 01-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 00-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 013.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 00-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 00-7.5 0" />
  </svg>

  <svg v-else-if="$slots.default?.()[0]?.children === 'x-mark'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" :width="size || 20" :height="size || 20" :class="$props.class">
    <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
  </svg>

  <svg v-else-if="$slots.default?.()[0]?.children === 'chevron-down'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" :width="size || 20" :height="size || 20" :class="$props.class">
    <path stroke-linecap="round" stroke-linejoin="round" d="M19.5 8.25l-7.5 7.5-7.5-7.5" />
  </svg>

  <svg v-else-if="$slots.default?.()[0]?.children === 'chevron-up'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" :width="size || 20" :height="size || 20" :class="$props.class">
    <path stroke-linecap="round" stroke-linejoin="round" d="M4.5 15.75l7.5-7.5 7.5 7.5" />
  </svg>

  <svg v-else-if="$slots.default?.()[0]?.children === 'magnifying-glass'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" :width="size || 20" :height="size || 20" :class="$props.class">
    <path stroke-linecap="round" stroke-linejoin="round" d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z" />
  </svg>

  <svg v-else-if="$slots.default?.()[0]?.children === 'check'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" :width="size || 20" :height="size || 20" :class="$props.class">
    <path stroke-linecap="round" stroke-linejoin="round" d="M4.5 12.75l6 6 9-13.5" />
  </svg>

  <svg v-else-if="$slots.default?.()[0]?.children === 'arrow-path'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" :width="size || 20" :height="size || 20" :class="$props.class">
    <path stroke-linecap="round" stroke-linejoin="round" d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0l3.181 3.183a8.25 8.25 0 0013.803-3.7M4.031 9.865a8.25 8.25 0 0113.803-3.7l3.181 3.182m0-4.991v4.99" />
  </svg>

  <!-- 默认空 svg -->
  <svg v-else viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" :width="size || 20" :height="size || 20" :class="$props.class">
    <circle cx="12" cy="12" r="10" />
  </svg>
</template>
