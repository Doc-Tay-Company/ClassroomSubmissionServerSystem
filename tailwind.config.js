/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./templates/**/*.html", "./static/js/**/*.js"],
  theme: { extend: { colors: { brand: { 50: '#eff6ff', 600: '#2563eb', 700: '#1d4ed8', 900: '#1e3a8a' } } } },
  plugins: []
};
