import type { Config } from "tailwindcss";

const config: Config = {
  darkMode: "class",
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./lib/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: ["var(--font-inter)", "system-ui", "sans-serif"],
      },
      colors: {
        // Near-black charcoal — primary text and primary buttons.
        ink: {
          DEFAULT: "#15172e",
          50: "#f5f5f8",
          100: "#e7e8ee",
          900: "#1c1f3a",
          950: "#15172e",
        },
        // Dark band + footer surface.
        navy: {
          DEFAULT: "#0f1b2e",
          900: "#13233b",
          950: "#0f1b2e",
        },
        // Signature accent — a soft periwinkle / cornflower. Full scale so every
        // shade the accent utilities use has a faithful periwinkle counterpart.
        brand: {
          DEFAULT: "#6b7cf0",
          50: "#eef0fe",
          100: "#e0e3fd",
          200: "#c6cbfb",
          300: "#a3acf7",
          400: "#8b97f5",
          500: "#6b7cf0",
          600: "#5b6cf0",
          700: "#4c59d6",
          800: "#3f4aad",
          900: "#363f88",
          950: "#222650",
        },
      },
      boxShadow: {
        card: "0 1px 2px 0 rgb(0 0 0 / 0.04), 0 1px 3px 0 rgb(0 0 0 / 0.03)",
        "card-hover":
          "0 2px 4px 0 rgb(0 0 0 / 0.05), 0 4px 12px 0 rgb(0 0 0 / 0.05)",
      },
      keyframes: {
        "fade-in": {
          from: { opacity: "0", transform: "translateY(4px)" },
          to: { opacity: "1", transform: "translateY(0)" },
        },
        shimmer: {
          "100%": { transform: "translateX(100%)" },
        },
      },
      animation: {
        "fade-in": "fade-in 0.2s ease-out",
        shimmer: "shimmer 1.6s infinite",
      },
    },
  },
  plugins: [],
};

export default config;
