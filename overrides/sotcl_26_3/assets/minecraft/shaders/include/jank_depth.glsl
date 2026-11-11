#ifndef JANK_DEPTH_GLSL
#define JANK_DEPTH_GLSL

const vec3 JANK_MARK = vec3(254.0, 254.0, 253.0);
const float JANK_DEPTH_UNITS = 4.0;
const float JANK_DEPTH_SLOPE = 0.5;

bool jank_marked(vec4 color) {
    return all(lessThan(abs(color.rgb * 255.0 - JANK_MARK), vec3(0.6)));
}

float jank_toward_camera(mat4 proj) {
    vec4 nearP = proj * vec4(0.0, 0.0, -0.06, 1.0);
    vec4 farP = proj * vec4(0.0, 0.0, -1024.0, 1.0);
    return sign(nearP.z / nearP.w - farP.z / farP.w);
}

float jank_depth(float z, float slope, float dir) {
    float unit = exp2(floor(log2(max(z, 1e-30))) - 23.0);
    return clamp(z + dir * (JANK_DEPTH_UNITS * unit + JANK_DEPTH_SLOPE * slope), 0.0, 1.0);
}

#endif
