/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  // Dark mode requires "dark" class on <html> — won't activate from OS preference alone.
  // Enable theme toggle later to add/remove the class.
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        brand: {
          50: "#EFF6FF",
          100: "#DBEAFE",
          500: "#3B82F6",
          600: "#2563EB",
          700: "#1D4ED8",
          900: "#1E3A5F",
        },
      },
    },
  },
  plugins: [],
};
