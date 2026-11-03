/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: {
          950: "#080c14",
          900: "#0d1220",
          850: "#111827",
          800: "#151d2e",
          700: "#1e293b",
        },
        brand: { 400: "#38bdf8", 500: "#0ea5e9", 600: "#0284c7" },
      },
      fontFamily: {
        sans: ["Inter", "Segoe UI", "system-ui", "sans-serif"],
        mono: ["JetBrains Mono", "Consolas", "monospace"],
      },
    },
  },
  plugins: [],
};
