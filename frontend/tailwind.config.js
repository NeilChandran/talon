/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        talon: {
          red: "#D90429",
          "red-hover": "#B8031F",
          "red-light": "#FFF0F2",
          "red-mid": "#FFD6DC",
        },
        // Zoom-like light surfaces
        surface: {
          DEFAULT: "#F5F5F7",
          white: "#FFFFFF",
          hover: "#F0F0F2",
          active: "#E8E8EB",
          border: "#E2E2E6",
          "border-dark": "#C8C8CE",
        },
        // Text scale matching Zoom's palette
        ink: {
          DEFAULT: "#1D1D1F",
          2: "#3D3D40",
          3: "#6E6E73",
          4: "#98989D",
          5: "#C7C7CC",
        },
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "-apple-system", "sans-serif"],
      },
      fontSize: {
        "2xs": ["0.65rem", { lineHeight: "1rem" }],
      },
      boxShadow: {
        card: "0 1px 3px rgba(0,0,0,0.08), 0 1px 2px rgba(0,0,0,0.04)",
        "card-md": "0 4px 12px rgba(0,0,0,0.08), 0 2px 4px rgba(0,0,0,0.04)",
        "btn-red": "0 1px 3px rgba(217,4,41,0.3)",
      },
      animation: {
        "fade-in": "fadeIn 0.15s ease-out",
        "slide-up": "slideUp 0.2s ease-out",
      },
      keyframes: {
        fadeIn: { "0%": { opacity: "0" }, "100%": { opacity: "1" } },
        slideUp: {
          "0%": { opacity: "0", transform: "translateY(6px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
      },
    },
  },
  plugins: [],
};
