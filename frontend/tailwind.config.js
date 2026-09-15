import typography from '@tailwindcss/typography';

/**
 * 主题系统并轨（docs/design/theme-system/01-theme-architecture.md §8）：
 * ink/parchment/accent 三族色板全部映射 CSS 变量——类名不随主题漂移、值随 token 换肤。
 * ⚠ var()/color-mix() 值下 Tailwind 的透明度修饰符（bg-accent-500/50）不生效，
 * 新样式需要透明度一律走组件 style 的 color-mix。
 * primary 天蓝板 2026-09-15 验证零引用后删除。
 */
/** @type {import('tailwindcss').Config} */
export default {
  darkMode: 'class',
  content: [
    "./index.html",
    "./src/**/*.{vue,js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        // 墨色灰度体系（暖灰）→ 语义 token
        ink: {
          50: 'var(--bg-canvas)',
          100: 'var(--bg-tertiary)',
          200: 'var(--border-color)',
          300: 'var(--scrollbar-thumb)',
          400: 'var(--text-faint)',
          500: 'var(--text-muted)',
          600: 'var(--text-secondary)',
          700: 'var(--text-secondary)',
          800: 'var(--text-primary)',
          900: 'var(--text-primary)',
        },
        // 纸张色体系 → 语义 token
        parchment: {
          50: 'var(--paper-bg)',
          100: 'var(--bg-secondary)',
          200: 'var(--bg-primary)',
          300: 'var(--bg-tertiary)',
          400: 'var(--hover-bg)',
          500: 'var(--border-color)',
        },
        // 强调色（暖靛紫，随主题换值）
        accent: {
          50: 'color-mix(in srgb, var(--accent-500) 8%, var(--bg-canvas))',
          100: 'color-mix(in srgb, var(--accent-500) 14%, var(--bg-canvas))',
          200: 'color-mix(in srgb, var(--accent-500) 24%, var(--bg-canvas))',
          300: 'color-mix(in srgb, var(--accent-500) 40%, var(--bg-canvas))',
          400: 'var(--accent-400)',
          500: 'var(--accent-500)',
          600: 'var(--accent-600)',
          700: 'var(--accent-600)',
          800: 'var(--accent-600)',
          900: 'var(--accent-600)',
        },
        // 线阶三档（05-visual-modernization-plan §7.5；--line === --border-color 现值）
        line: 'var(--line)',
        'line-faint': 'var(--line-faint)',
        'line-strong': 'var(--line-strong)',
        // 表面阶梯五档（P0 alias 期映射现值，P1 按主题调值）
        surface: {
          base: 'var(--surface-base)',
          sunken: 'var(--surface-sunken)',
          raised: 'var(--surface-raised)',
          overlay: 'var(--surface-overlay)',
          float: 'var(--surface-float)',
        },
      },
      fontFamily: {
        body: ['Inter', '"PingFang SC"', '"Hiragino Sans GB"', '"Microsoft YaHei"', '"Segoe UI"', 'sans-serif'],
        heading: ['var(--font-heading)'],
        serif: ['var(--font-heading)'],
      },
      // Elevation 三档（05 §7.2；与 style.css .elev-1/2/3 同源，走 shadow token 即主题自适应）
      boxShadow: {
        e1: 'var(--shadow-sm)',
        e2: 'var(--shadow-md)',
        e3: 'var(--shadow-lg)',
      },
    },
  },
  plugins: [
    typography,
  ],
}
