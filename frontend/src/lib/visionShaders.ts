// GPU post-processing fragment shaders for Cesium PostProcessStage.
// Each runs on the RTX GPU over the full framebuffer. WorldView-style vision modes.

export const NVG_FRAGMENT = `
uniform sampler2D colorTexture;
in vec2 v_textureCoordinates;

float hash(vec2 p) {
  return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453);
}

void main() {
  vec2 uv = v_textureCoordinates;
  vec4 color = texture(colorTexture, uv);
  // Luminance -> phosphor green amplification
  float lum = dot(color.rgb, vec3(0.299, 0.587, 0.114));
  lum = pow(lum, 0.65) * 1.6;
  vec3 nvg = vec3(0.05, 1.0, 0.25) * lum;
  // Animated sensor noise
  float n = hash(uv * 800.0 + fract(czm_frameNumber * 0.01)) * 0.12;
  nvg += n * vec3(0.0, 1.0, 0.2);
  // Vignette
  vec2 d = uv - 0.5;
  float vig = smoothstep(0.85, 0.25, dot(d, d) * 2.2);
  nvg *= vig;
  out_FragColor = vec4(nvg, 1.0);
}
`;

export const THERMAL_FRAGMENT = `
uniform sampler2D colorTexture;
in vec2 v_textureCoordinates;

vec3 thermal(float t) {
  // black -> purple -> red -> orange -> yellow -> white
  vec3 c;
  c = mix(vec3(0.0, 0.0, 0.1), vec3(0.5, 0.0, 0.5), smoothstep(0.0, 0.25, t));
  c = mix(c, vec3(0.9, 0.0, 0.0), smoothstep(0.25, 0.5, t));
  c = mix(c, vec3(1.0, 0.6, 0.0), smoothstep(0.5, 0.75, t));
  c = mix(c, vec3(1.0, 1.0, 0.8), smoothstep(0.75, 1.0, t));
  return c;
}

void main() {
  vec2 uv = v_textureCoordinates;
  vec4 color = texture(colorTexture, uv);
  float lum = dot(color.rgb, vec3(0.299, 0.587, 0.114));
  lum = pow(lum, 0.8);
  out_FragColor = vec4(thermal(lum), 1.0);
}
`;

export const CRT_FRAGMENT = `
uniform sampler2D colorTexture;
uniform float aberration;
in vec2 v_textureCoordinates;

void main() {
  vec2 uv = v_textureCoordinates;
  // Chromatic aberration
  vec2 dir = uv - 0.5;
  float amt = aberration * 0.004;
  float r = texture(colorTexture, uv - dir * amt).r;
  float g = texture(colorTexture, uv).g;
  float b = texture(colorTexture, uv + dir * amt).b;
  vec3 col = vec3(r, g, b);
  // Scanlines
  float scan = sin(uv.y * 1400.0) * 0.06;
  col -= scan;
  // Slight green CRT tint + vignette
  col *= vec3(0.92, 1.05, 0.95);
  float vig = smoothstep(1.1, 0.3, length(dir) * 1.6);
  col *= vig;
  out_FragColor = vec4(col, 1.0);
}
`;

export const NIGHT_FRAGMENT = `
uniform sampler2D colorTexture;
in vec2 v_textureCoordinates;

void main() {
  vec2 uv = v_textureCoordinates;
  vec4 color = texture(colorTexture, uv);
  float lum = dot(color.rgb, vec3(0.299, 0.587, 0.114));
  // Cool desaturated blue night optics
  vec3 night = mix(vec3(lum), vec3(0.2, 0.45, 0.9) * lum, 0.6);
  night = pow(night, vec3(0.9));
  out_FragColor = vec4(night, 1.0);
}
`;

export type VisionMode = 'normal' | 'nvg' | 'thermal' | 'crt' | 'night';

export const VISION_MODES: { id: VisionMode; label: string }[] = [
  { id: 'normal', label: 'OPTICAL' },
  { id: 'nvg', label: 'NVG' },
  { id: 'thermal', label: 'THERMAL' },
  { id: 'crt', label: 'CRT' },
  { id: 'night', label: 'NIGHT' },
];
