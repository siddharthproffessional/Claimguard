/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ['"IBM Plex Sans"', "system-ui", "sans-serif"],
        mono: ['"IBM Plex Mono"', "ui-monospace", "monospace"],
      },
      colors: {
        navy: { 950: "#060d1a", 900: "#0b1628", 800: "#12213a", 700: "#1b2f4f", 600: "#2a4166" },
        accent: { DEFAULT: "#14b8a6", soft: "#ccfbf1", ink: "#0f766e" },
      },
      keyframes: { pulseRing: { "0%": { boxShadow: "0 0 0 0 rgba(20,184,166,.45)" }, "100%": { boxShadow: "0 0 0 8px rgba(20,184,166,0)" } } },
      animation: { pulseRing: "pulseRing 1.4s ease-out infinite" },
    },
  },
  plugins: [],
};
