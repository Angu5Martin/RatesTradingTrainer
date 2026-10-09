// Vite's ?raw imports: the guides in docs/ are bundled as text and rendered in the app (src/guide/).
declare module "*.md?raw" {
  const text: string;
  export default text;
}
