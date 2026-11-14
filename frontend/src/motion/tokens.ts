// Spring configs
export const SPRING_DEFAULT = { type: "spring" as const, duration: 0.25, bounce: 0.05 };
export const SPRING_SNAPPY  = { type: "spring" as const, duration: 0.2,  bounce: 0.02 };
export const SPRING_GENTLE  = { type: "spring" as const, duration: 0.3,  bounce: 0.08 };

// Easing (CSS-level animations only)
export const EASE_ENTRY    = [0.23, 1, 0.32, 1] as const;
export const EASE_MOVEMENT = [0.645, 0.045, 0.355, 1] as const;

// Common variant presets
export const FADE_SCALE_IN = {
  initial: { opacity: 0, scale: 0.96 },
  animate: { opacity: 1, scale: 1 },
  exit:    { opacity: 0, scale: 0.96 },
};
export const SLIDE_UP = {
  initial: { opacity: 0, y: 8 },
  animate: { opacity: 1, y: 0 },
  exit:    { opacity: 0, y: 8 },
};
export const SLIDE_RIGHT = {
  initial: { opacity: 0, x: 12 },
  animate: { opacity: 1, x: 0 },
  exit:    { opacity: 0, x: 12 },
};

// Reduced motion fallbacks
export const REDUCED_INSTANT = { duration: 0 };
export const REDUCED_FADE = {
  initial: { opacity: 0 },
  animate: { opacity: 1 },
  exit:    { opacity: 0, transition: { duration: 0 } },
};
