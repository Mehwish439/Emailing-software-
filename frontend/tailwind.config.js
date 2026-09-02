/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        brand: {
          50: "#eef4ff",
          100: "#d9e6ff",
          200: "#b8cfff",
          300: "#8caeff",
          400: "#5f87ff",
          500: "#3d63f7",
          600: "#2b47dd",
          700: "#2437b3",
          800: "#22318d",
          900: "#212c6f",
        },
      },
      fontFamily: {
        sans: ["Inter", "ui-sans-serif", "system-ui", "sans-serif"],
      },
    },
  },
  plugins: [],
};
