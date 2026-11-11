#version 330
#extension GL_ARB_separate_shader_objects : require

#ifdef GLINT
#include <minecraft:globals.glsl>
#endif
#include <minecraft:fog.glsl>
#include <minecraft:dynamictransforms.glsl>
#include <minecraft:oit.glsl>
#include <minecraft:sotcl_nv.glsl>
#include <minecraft:projection.glsl>
#include <minecraft:jank_depth.glsl>

uniform sampler2D Sampler0;

#ifdef GLINT
uniform sampler2D GlintSampler;
#endif

#ifndef OIT_ALPHA_ONLY
layout(location = 0) in float sphericalVertexDistance;
layout(location = 1) in float cylindricalVertexDistance;
#endif
layout(location = 2) in vec4 vertexColor;
#ifndef OIT_ALPHA_ONLY
layout(location = 3) in vec4 lightMapColor;
layout(location = 4) in vec4 overlayColor;
#endif
layout(location = 5) in vec2 texCoord0;
layout(location = 11) in float jankDepthDir;
#ifdef GLINT
layout(location = 6) in vec2 texCoordGlint;
#endif

#ifndef OIT_ALPHA_ONLY
layout(location = 0) out vec4 fragColor;
layout(location = 8) in float nvFactor;
#endif

#ifndef OIT_ALPHA_ONLY
// ============================================================ Hyper Emissive ==
// Separate from the emissive trims (alpha 254). On atlas-sized textures:
//   alpha 252 = hyper core : full-bright, over-bright toward white-hot, cuts through biome fog
//   alpha 251 = hyper halo : partly bright, softer - paint it around a core so the light seems to spill
// Core shaders can't blur across the screen (that needs a post pass), so the "bloom" is the
// over-bright core + baked halo + glowing harder the thicker the fog is around it.
const float HYPER_GAIN       = 1.45;  // core: how much brighter than the texture
const float HYPER_WHITE      = 0.30;  // core: how far bright texels push toward white-hot
const float HALO_STRENGTH    = 0.55;  // halo: 0 = lit like normal, 1 = full-bright
const float HALO_GAIN        = 1.15;  // halo: extra brightness
const float HYPER_FOG_REACH  = 4.0;   // core stays visible this many times deeper into biome fog
const float HALO_FOG_REACH   = 2.5;   // halo reach
const float HYPER_FOG_GLOW   = 0.45;  // extra glow as the surrounding fog thickens (light in haze)
// 0 = normal | 1 = paint core texels green and halo texels blue (checks the markers survive in-game)
const int   HYPER_DEBUG      = 0;

int hyperLevel(vec4 texel, vec2 texSize) {
    if (texSize.x < 256.0) return 0;
    if (texel.a > 251.5 / 255.0 && texel.a < 252.5 / 255.0) return 2;
    if (texel.a > 250.5 / 255.0 && texel.a < 251.5 / 255.0) return 1;
    return 0;
}

float hyperFogLinear(float d, float start, float end) {
    return clamp((d - start) / max(end - start, 0.0001), 0.0, 1.0);
}

vec3 hyperBoost(vec3 rgb, int level) {
    if (level == 2) {
        rgb = min(rgb * HYPER_GAIN, vec3(1.0));
        float l = dot(rgb, vec3(0.299, 0.587, 0.114));
        return mix(rgb, vec3(1.0), HYPER_WHITE * l);
    }
    return min(rgb * HALO_GAIN, vec3(1.0));
}

vec4 hyperFog(vec4 color, int level, float sphDist, float cylDist, vec4 fogColor) {
    float reach = level == 2 ? HYPER_FOG_REACH : HALO_FOG_REACH;
    float envStart = FogEnvironmentalStart;
    float envEnd = FogEnvironmentalEnd;
    sotcl_nv_fog_bounds(nvFactor, envStart, envEnd);
    float envNormal = hyperFogLinear(sphDist, envStart, envEnd);
    float envHyper  = hyperFogLinear(sphDist, envStart, envStart + (envEnd - envStart) * reach);
    float rdFog     = hyperFogLinear(cylDist, FogRenderDistanceStart, FogRenderDistanceEnd);
    color.rgb = min(color.rgb * (1.0 + HYPER_FOG_GLOW * envNormal * (level == 2 ? 1.0 : 0.5)), vec3(1.0));
    float f = max(envHyper, rdFog) * fogColor.a;
    return vec4(mix(color.rgb, fogColor.rgb, f), color.a);
}

vec4 hyperDebug(vec4 c, int level) {
    if (HYPER_DEBUG == 1 && level > 0) return level == 2 ? vec4(0.0, 1.0, 0.0, 1.0) : vec4(0.0, 0.3, 1.0, 1.0);
    return c;
}
// ==============================================================================

vec4 calculateFinalColor(vec4 color, int hyper) {
    color.rgb = mix(overlayColor.rgb, color.rgb, overlayColor.a);
    if (hyper == 2) {
    } else if (hyper == 1) {
        color *= mix(lightMapColor, vec4(1.0), HALO_STRENGTH);
    } else {
        color *= lightMapColor;
    }

    #ifdef GLINT
    vec4 glintColor = GlintAlpha * texture(GlintSampler, texCoordGlint);// Glint color modulator?
    // Matches BlendFuntion.GLINT
    color.rgb += glintColor.rgb * glintColor.rgb;
    #endif

    #ifdef OIT_ACCUMULATE
    color = sampleColorForAccumulation(color);
    vec4 fogColor = vec4(FogColor.rgb * color.a, FogColor.a);
    #else
    vec4 fogColor = FogColor;
    #endif

    if (hyper > 0) {
        color.rgb = hyperBoost(color.rgb, hyper);
        return hyperDebug(hyperFog(color, hyper, sphericalVertexDistance, cylindricalVertexDistance, fogColor), hyper);
    }
    float envStart = FogEnvironmentalStart;
    float envEnd = FogEnvironmentalEnd;
    sotcl_nv_fog_bounds(nvFactor, envStart, envEnd);
    return apply_fog(color, sphericalVertexDistance, cylindricalVertexDistance, envStart, envEnd, FogRenderDistanceStart, FogRenderDistanceEnd, fogColor);
}
#endif

void main() {
    float jankSlope = max(abs(dFdx(gl_FragCoord.z)), abs(dFdy(gl_FragCoord.z)));
    float jankZ = jankDepthDir != 0.0 ? jank_depth(gl_FragCoord.z, jankSlope, jankDepthDir) : gl_FragCoord.z;
    gl_FragDepth = jankZ;
    vec4 color = texture(Sampler0, texCoord0);
    #ifndef OIT_ALPHA_ONLY
    // markers are read from the full-resolution texel, so distant mipmaps can't blur them away
    vec4 hyperTexel = textureLod(Sampler0, texCoord0, 0.0);
    int hyper = hyperLevel(hyperTexel, vec2(textureSize(Sampler0, 0)));
    // GUI icons (orthographic projection) are left alone
    if (abs(ProjMat[2][3]) < 1e-5) hyper = 0;
    if (hyper > 0) color = vec4(hyperTexel.rgb, 1.0);
    #endif
    #ifdef ALPHA_CUTOUT
    if (color.a < ALPHA_CUTOUT) {
        discard;
    }
    #endif

    color *= vertexColor * ColorModulator;

    #ifdef GLINT
    color.a = max(color.a, GlintAlpha);
    #endif

    #ifdef OIT_ALPHA_ONLY
    executeAlphaOnlyPhase(jankZ, color.a);
    #else
    fragColor = calculateFinalColor(color, hyper);
    #endif
}
