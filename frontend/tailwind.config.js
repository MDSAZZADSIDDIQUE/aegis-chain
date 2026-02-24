/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./src/**/*.{js,ts,jsx,tsx,mdx}"],
  theme: {
    extend: {
      // ── Tactical Agritech Color System ──────────────────────────
      colors: {
        // Deep earthy canopy green — used for key data surfaces
        canopy: {
          950: "#011a12",
          900: "#022c22",
          800: "#064e3b",
        },
        // Hazard palette — NOAA threats and disruption indicators
        hazard: {
          extreme: "#dc2626", // red-600
          severe:  "#ea580c", // orange-600
          moderate:"#d97706", // amber-600
          minor:   "#ca8a04", // yellow-600
        },
      },

      // ── Typography ───────────────────────────────────────────────
      fontFamily: {
        sans: ["Inter", "-apple-system", "BlinkMacSystemFont", "Segoe UI", "sans-serif"],
        mono: ["JetBrains Mono", "Fira Code", "ui-monospace", "SFMono-Regular", "monospace"],
      },

      fontSize: {
        "2xs": ["0.625rem", { lineHeight: "0.875rem" }], // 10px
        "3xs": ["0.5625rem", { lineHeight: "0.75rem"  }], // 9px
      },

      // ── Spacing ──────────────────────────────────────────────────
      spacing: {
        "px": "1px",
        "0.5": "2px",
      },

      // ── Borders ──────────────────────────────────────────────────
      // Use rounded-sm (2px) max — no pill or bubble shapes
      borderRadius: {
        DEFAULT: "2px",
        sm:      "2px",
        md:      "3px",
        lg:      "4px",
        xl:      "4px",
        "2xl":   "4px", // override to prevent bubble look
        full:    "9999px", // only for status dots
      },

      // ── Keyframes for status pulse ───────────────────────────────
      keyframes: {
        blink: {
          "0%, 100%": { opacity: "1" },
          "50%":       { opacity: "0" },
        },
        scanline: {
          "0%":   { transform: "translateY(-100%)" },
          "100%": { transform: "translateY(100vh)" },
        },
      },
      animation: {
        blink:    "blink 1s step-end infinite",
        scanline: "scanline 8s linear infinite",
      },
    },
  },
  plugins: [],
};
