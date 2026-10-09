import { type RefObject, useEffect, useState } from "react";

/** The pixel size of an element, kept current (charts draw to the space they are given instead of a fixed viewBox). */
export function useSize(ref: RefObject<HTMLElement>, fallback = { w: 300, h: 140 }): { w: number; h: number } {
  const [size, setSize] = useState(fallback);
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const read = () => { const r = el.getBoundingClientRect(); if (r.width > 0 && r.height > 0) setSize({ w: Math.round(r.width), h: Math.round(r.height) }); };
    read();
    const ro = new ResizeObserver(read);
    ro.observe(el);
    return () => ro.disconnect();
  }, [ref]);
  return size;
}
