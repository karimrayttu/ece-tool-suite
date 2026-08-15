/** @type {import('tailwindcss').Config} */
export default {
  darkMode: "class",
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // "Rack edition" dark instrument palette — near-black chassis, neon accents.
        // Inspired by hardware-style plugin UIs (Kontakt / Diva / noisehead display shaders):
        // deep charcoal modules on a darker chassis, glowing signal colours, LED indicators.
        bg: "#0a0c10",         // app chassis (near-black, slightly blue)
        panel: "#14181f",      // module panel surface
        panel2: "#0e1116",     // recessed wells / sidebar / inputs
        line: "#222933",       // hairline borders between modules
        ink: "#e7ecf3",        // primary text
        muted: "#8b95a5",      // secondary text (AA on panel)
        accent: "#4f9dff",     // neon cyan — primary action / selection
        accent2: "#a78bfa",    // violet — secondary neon (spectrum, AI)
        sim: "#f59e0b",
        unverified: "#fb923c",
        verified: "#34d399",
        danger: "#fb7185",
        ks: "#26c6da",         // vendor chip teal, brightened for dark
        ksdark: "#0e7490",
        // instrument display surfaces (inset CRT-style screens)
        screen: "#04070b",
        screenline: "#152232",
        // scope channel trace colours — phosphor-bright for glow rendering
        ch1: "#fbbf24",
        ch2: "#34d399",
        ch3: "#38bdf8",
        ch4: "#f472b6",
      },
      borderRadius: { xl2: "12px" },
      fontFamily: {
        sans: ['Inter', 'ui-sans-serif', 'system-ui', '"Segoe UI"', 'Roboto', 'sans-serif'],
        mono: ['ui-monospace', '"Cascadia Code"', 'Consolas', 'monospace'],
      },
      boxShadow: {
        // module panels: faint top edge-light + deep drop into the chassis
        panel: "inset 0 1px 0 rgba(255,255,255,0.035), 0 1px 2px rgba(0,0,0,0.5), 0 8px 24px rgba(0,0,0,0.35)",
        raised: "inset 0 1px 0 rgba(255,255,255,0.05), 0 12px 32px rgba(0,0,0,0.5)",
        // inset displays (screens/wells)
        well: "inset 0 2px 8px rgba(0,0,0,0.6), inset 0 0 0 1px rgba(0,0,0,0.4)",
        // neon glows for LEDs / active elements
        "glow-cyan": "0 0 6px rgba(79,157,255,0.65), 0 0 18px rgba(79,157,255,0.22)",
        "glow-green": "0 0 6px rgba(52,211,153,0.7), 0 0 18px rgba(52,211,153,0.25)",
        "glow-amber": "0 0 6px rgba(251,191,36,0.7), 0 0 18px rgba(251,191,36,0.25)",
        "glow-red": "0 0 6px rgba(251,113,133,0.7), 0 0 18px rgba(251,113,133,0.25)",
      },
      keyframes: {
        "fade-up": {
          "0%": { opacity: "0", transform: "translateY(4px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        "led-breathe": {
          "0%, 100%": { opacity: "1" },
          "50%": { opacity: "0.55" },
        },
      },
      animation: {
        "fade-up": "fade-up 180ms ease-out",
        "led-breathe": "led-breathe 2.4s ease-in-out infinite",
      },
    },
  },
  plugins: [],
};
