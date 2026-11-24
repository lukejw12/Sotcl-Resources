#ifndef JANK_DEPTH_GLSL
#define JANK_DEPTH_GLSL

// Jank display models carry a constant tint. 254,254,253 is the older bake, 254,254,252 the bake
// whose faces sit JANK_FACE_PUSH outside the block.
const vec3 JANK_MARK = vec3(254.0, 254.0, 253.0);
const vec3 JANK_MARK_PUSHED = vec3(254.0, 254.0, 252.0);
const float JANK_FACE_PUSH = 0.02 / 16.0;

// Jank models are drawn this share of their distance closer to the camera, plus a part that grows
// with the distance squared so they stay ahead of the depth buffer's precision far away.
// Block cracks are pulled further so they still show on top.
const float JANK_PULL = 1.0 / 2048.0;
const float JANK_PULL_CRACK = 1.0 / 512.0;
const float JANK_PULL_FAR = 7.0e-6;

int jank_mark(vec4 color) {
    vec3 c = color.rgb * 255.0;
    if (all(lessThan(abs(c - JANK_MARK_PUSHED), vec3(0.4)))) return 2;
    if (all(lessThan(abs(c - JANK_MARK), vec3(0.4)))) return 1;
    return 0;
}

// Moves a view-space position along its own view ray, so it lands on the same pixel, only nearer.
vec4 jank_pull(vec4 viewPos, float share) {
    float d = length(viewPos.xyz);
    viewPos.xyz *= max(1.0 - share - JANK_PULL_FAR * d, 0.5);
    return viewPos;
}

bool jank_perspective(mat4 proj) {
    return abs(proj[2][3]) > 1e-5;
}

#endif
