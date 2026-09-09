/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{vue,ts}"],
  theme: {
    extend: {},
  },
  // 关闭 preflight：原型的手写 CSS 是布局基准，避免被 Tailwind 重置样式覆盖
  corePlugins: {
    preflight: false,
  },
  plugins: [],
};
