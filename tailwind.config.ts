import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: ["Inter", "ui-sans-serif", "system-ui", "sans-serif"],
      },
      colors: {
        crimson: {
          50: "#fff1f3",
          100: "#ffe1e6",
          200: "#e8cfd6",
          500: "#b70735",
          600: "#970a34",
          700: "#8b0834",
          800: "#7B1111",
          900: "#610b23",
        },
      },
      boxShadow: {
        soft: "0 1px 3px rgba(16, 24, 40, 0.12)",
      },
    },
  },
  plugins: [],
};

export default config;
