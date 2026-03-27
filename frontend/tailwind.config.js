import typography from '@tailwindcss/typography';

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
        primary: {
          50: '#f0f9ff',
          100: '#e0f2fe',
          200: '#bae6fd',
          300: '#7dd3fc',
          400: '#38bdf8',
          500: '#0ea5e9',
          600: '#0284c7',
          700: '#0369a1',
          800: '#075985',
          900: '#0c4a6e',
        },
        // 墨色灰度体系（暖灰）
        ink: {
          50: '#faf9f7',
          100: '#f0eee9',
          200: '#e0dbd3',
          300: '#c8c0b4',
          400: '#a89e90',
          500: '#8b8074',
          600: '#6b6560',
          700: '#4a4540',
          800: '#2c2c2c',
          900: '#1a1917',
        },
        // 纸张色体系
        parchment: {
          50: '#fefdfb',
          100: '#faf8f4',
          200: '#f7f4ed',
          300: '#f0ece3',
          400: '#eee9df',
          500: '#e5ded2',
          600: '#d4cbbe',
          700: '#b8ad9e',
          800: '#9a8e7e',
          900: '#7d7264',
        },
        // 强调色（暖靛紫）
        accent: {
          50: '#f5f3ff',
          100: '#ede9fe',
          200: '#ddd6fe',
          300: '#c4b5fd',
          400: '#a78bfa',
          500: '#7c6aad',
          600: '#6d5dab',
          700: '#5b4d91',
          800: '#4a3f77',
          900: '#3b325f',
        },
      },
      fontFamily: {
        body: ['Inter', '"PingFang SC"', '"Hiragino Sans GB"', '"Microsoft YaHei"', '"Segoe UI"', 'sans-serif'],
        heading: ['"Noto Serif SC"', '"Source Han Serif SC"', 'STSong', 'SimSun', '"PingFang SC"', 'serif'],
        serif: ['"Noto Serif SC"', '"Source Han Serif SC"', 'STSong', 'SimSun', '"PingFang SC"', 'serif'],
      },
    },
  },
  plugins: [
    typography,
  ],
}
