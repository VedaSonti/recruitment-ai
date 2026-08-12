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
        sans: ["DM Sans", "ui-sans-serif", "system-ui", "sans-serif"],
        display: ["Bricolage Grotesque", "DM Sans", "ui-sans-serif", "sans-serif"],
        accent: ["Instrument Serif", "Georgia", "serif"],
      },
      colors: {
        brand: { DEFAULT: "#E31E24", light: "#F87171", dark: "#C01015", faint: "#FEF2F2" },
        crimson: {
          50: "#FEF2F2", 100: "#FEE2E2", 200: "#FECACA", 500: "#E31E24",
          600: "#D71920", 700: "#C01015", 800: "#150208", 900: "#0D0105",
        },
      },
      boxShadow: {
        soft: "0 1px 2px rgba(15, 23, 42, 0.04), 0 8px 24px rgba(15, 23, 42, 0.06)",
        lift: "0 18px 45px rgba(15, 23, 42, 0.10)",
      },
    },
  },
  plugins: [],
};

export default config;
