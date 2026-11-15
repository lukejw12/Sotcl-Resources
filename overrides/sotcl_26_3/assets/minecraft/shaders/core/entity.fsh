#version 330
#extension GL_ARB_separate_shader_objects : require

#ifdef GLINT
#include <minecraft:globals.glsl>
#endif
#include <minecraft:fog.glsl>
#include <minecraft:dynamictransforms.glsl>
#include <minecraft:oit.glsl>
#include <minecraft:sotcl_nv.glsl>

// PlanePhysics ragdolls: skinned limbs from player heads (idea: Stable Player Display, CC0).
// A player head drawn 1024*n blocks below its item display is redrawn as limb n of the skin
// (1 right arm, 2 left arm, 3 torso, 4 right leg, 5 left leg) and moved back into place.
#if defined(ALPHA_CUTOUT) && !defined(EMISSIVE) && !defined(NO_OVERLAY) && !defined(APPLY_TEXTURE_MATRIX)
#define PLANEPHYS_RAGDOLL 1
#endif

uniform sampler2D Sampler0;

#ifdef DISSOLVE
uniform sampler2D DissolveMaskSampler;
#endif

#ifdef GLINT
uniform sampler2D GlintSampler;
#endif

layout(location = 0) in float sphericalVertexDistance;
layout(location = 1) in float cylindricalVertexDistance;
#ifdef PER_FACE_LIGHTING
layout(location = 2) in vec4 vertexPerFaceColorBack;
layout(location = 3) in vec4 vertexPerFaceColorFront;
#else
layout(location = 2) in vec4 vertexColor;
#endif

#ifndef EMISSIVE
layout(location = 4) in vec4 lightMapColor;
#endif

#ifndef NO_OVERLAY
layout(location = 5) in vec4 overlayColor;
#endif

layout(location = 6) in vec2 texCoord0;
#ifdef GLINT
layout(location = 7) in vec2 texCoordGlint;
#endif

#ifndef OIT_ALPHA_ONLY
layout(location = 0) out vec4 fragColor;
#endif

layout(location = 8) in float nvFactor;

#ifdef PLANEPHYS_RAGDOLL
layout(location = 9) in float ragdollPart;

#define RAGDOLL_FADE_RANGE 12.0
#define RAGDOLL_FADE_BIAS 8.0
#define RAGDOLL_MIN_ALPHA 0.25
const mat4 ragdollBayer = mat4( 0.0 / 16.0,  8.0 / 16.0,  2.0 / 16.0, 10.0 / 16.0,
                               12.0 / 16.0,  4.0 / 16.0, 14.0 / 16.0,  6.0 / 16.0,
                                3.0 / 16.0, 11.0 / 16.0,  1.0 / 16.0,  9.0 / 16.0,
                               15.0 / 16.0,  7.0 / 16.0, 13.0 / 16.0,  5.0 / 16.0);

// Box-UV rectangle (x, y, width, height in skin pixels) of one face of a cube whose texture
// starts at o and whose size is s = (width, height, depth). Faces: 0 top, 1 bottom, 2 right,
// 3 front, 4 left, 5 back (the standard skin layout).
vec4 ragdollFaceRect(vec2 o, vec3 s, int face) {
    if (face == 0) return vec4(o.x + s.z, o.y, s.x, s.z);
    if (face == 1) return vec4(o.x + s.z + s.x, o.y, s.x, s.z);
    if (face == 2) return vec4(o.x, o.y + s.z, s.z, s.y);
    if (face == 3) return vec4(o.x + s.z, o.y + s.z, s.x, s.y);
    if (face == 4) return vec4(o.x + s.z + s.x, o.y + s.z, s.z, s.y);
    return vec4(o.x + 2.0 * s.z + s.x, o.y + s.z, s.x, s.y);
}

// Which face of the 8x8x8 head cube a skin position lies on, and where inside it (0..1).
int ragdollHeadFace(vec2 px, out vec2 local) {
    vec2 p = vec2(mod(px.x, 32.0), px.y);   // the hat layer is the same layout 32px to the right
    int face = p.y < 8.0 ? (p.x < 16.0 ? 0 : 1) : (p.x < 8.0 ? 2 : (p.x < 16.0 ? 3 : (p.x < 24.0 ? 4 : 5)));
    vec4 r = ragdollFaceRect(vec2(0.0), vec3(8.0), face);
    local = clamp((p - r.xy) / r.zw, vec2(0.0), vec2(0.999));
    return face;
}

bool ragdollIsSlim() {
    int scale = max(textureSize(Sampler0, 0).x / 64, 1);   // HD skins: same layout, bigger pixels
    vec4 a = texelFetch(Sampler0, ivec2(54, 20) * scale, 0);
    vec4 b = texelFetch(Sampler0, ivec2(55, 20) * scale, 0);
    return a.a == 0.0 || (a.rgb == vec3(0.0) && b.rgb == vec3(0.0) && a.a == 1.0 && b.a == 1.0);
}

// Texture UV for ragdoll limb `id` (base layer in baseUV). Returns false if the fragment is dropped.
//  1-5   player skin: right arm, left arm, torso, right leg, left leg (outer layer, slim arms)
//  6-10  zombie/husk layout (left limbs mirror the right ones)
//  11-15 skeleton layout, 64x32, 2px limbs (left limbs mirrored)
//  16-17 creeper body / legs
//  21-25 drowned layout (player-style separate left limbs)
bool ragdollUV(vec2 headUV, int id, out vec2 uv, out vec2 baseUV) {
    ivec2 sz = textureSize(Sampler0, 0);
    vec2 texLayout = vec2(64.0, 64.0 * float(sz.y) / float(sz.x));
    vec2 px = headUV * texLayout;
    bool outerLayer = px.x >= 32.0;
    vec2 local;
    int face = ragdollHeadFace(px, local);
    vec3 size;
    vec2 base;
    vec2 outer = vec2(-1.0);
    bool mirror = false;
    if (id <= 5) {
        int limb = id - 1;
        size = limb == 2 ? vec3(8.0, 12.0, 4.0) : ((limb <= 1 && ragdollIsSlim()) ? vec3(3.0, 12.0, 4.0) : vec3(4.0, 12.0, 4.0));
        base  = limb == 0 ? vec2(40.0, 16.0) : (limb == 1 ? vec2(32.0, 48.0) : (limb == 2 ? vec2(16.0, 16.0) : (limb == 3 ? vec2(0.0, 16.0) : vec2(16.0, 48.0))));
        outer = limb == 0 ? vec2(40.0, 32.0) : (limb == 1 ? vec2(48.0, 48.0) : (limb == 2 ? vec2(16.0, 32.0) : (limb == 3 ? vec2(0.0, 32.0) : vec2(0.0, 48.0))));
    } else if (id >= 21) {
        int limb = id - 21;
        size = limb == 2 ? vec3(8.0, 12.0, 4.0) : vec3(4.0, 12.0, 4.0);
        base = limb == 0 ? vec2(40.0, 16.0) : (limb == 1 ? vec2(32.0, 48.0) : (limb == 2 ? vec2(16.0, 16.0) : (limb == 3 ? vec2(0.0, 16.0) : vec2(16.0, 48.0))));
    } else if (id >= 16) {
        size = id == 16 ? vec3(8.0, 12.0, 4.0) : vec3(4.0, 6.0, 4.0);
        base = id == 16 ? vec2(16.0, 16.0) : vec2(0.0, 16.0);
    } else {
        int limb = id >= 11 ? id - 11 : id - 6;
        float w = id >= 11 ? 2.0 : 4.0;
        size = limb == 2 ? vec3(8.0, 12.0, 4.0) : vec3(w, 12.0, w);
        base = limb <= 1 ? vec2(40.0, 16.0) : (limb == 2 ? vec2(16.0, 16.0) : vec2(0.0, 16.0));
        mirror = limb == 1 || limb == 4;
    }
    if (outerLayer && outer.x < 0.0) {
        return false;   // mob limbs have no outer layer
    }
    if (mirror) {
        face = face == 2 ? 4 : (face == 4 ? 2 : face);
        local.x = 1.0 - local.x;
    }
    vec4 rb = ragdollFaceRect(base, size, face);
    baseUV = (rb.xy + local * rb.zw) / texLayout;
    if (outerLayer) {
        vec4 ro = ragdollFaceRect(outer, size, face);
        uv = (ro.xy + local * ro.zw) / texLayout;
    } else {
        uv = baseUV;
    }
    return true;
}
#endif

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

bool isTrim() {
    vec2 texSize = vec2(textureSize(Sampler0, 0));
    float a = textureLod(Sampler0, texCoord0, 0.0).a;
    bool trimSized = texSize.x >= 256.0 || texSize.x == 2.0 * texSize.y;
    return trimSized && a > 253.2/255.0 && a < 254.8/255.0;
}

vec4 calculateFinalColor(vec4 color, int hyper) {
    #ifndef NO_OVERLAY
    color.rgb = mix(overlayColor.rgb, color.rgb, overlayColor.a);
    #endif

    #ifndef EMISSIVE
    if (isTrim() || hyper == 2) {
	} else if (hyper == 1) {
		color *= mix(lightMapColor, vec4(1.0), HALO_STRENGTH);
	} else {
		color *= lightMapColor;
	}
    #endif

    #ifdef GLINT
    vec4 glintColor = GlintAlpha * texture(GlintSampler, texCoordGlint);
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

void main() {
    vec2 uv0 = texCoord0;
#ifdef PLANEPHYS_RAGDOLL
    vec2 ragdollUnderUV = texCoord0;
    if (ragdollPart > 0.5) {
        if (!ragdollUV(texCoord0, int(ragdollPart + 0.5), uv0, ragdollUnderUV)) {
            discard;
        }
    }
#endif
    vec4 color = texture(Sampler0, uv0);
    // markers are read from the full-resolution texel, so distant mipmaps can't blur them away
    vec4 hyperTexel = textureLod(Sampler0, uv0, 0.0);
    int hyper = hyperLevel(hyperTexel, vec2(textureSize(Sampler0, 0)));
    if (hyper > 0) color = vec4(hyperTexel.rgb, 1.0);

    #ifdef OIT_ADDITIVE
    color.a = min(0.99, color.a);
    #endif

    #ifdef ALPHA_CUTOUT
    if (color.a < ALPHA_CUTOUT) {
        discard;
    }
    #endif

    #ifdef PER_FACE_LIGHTING
    vec4 faceVertexColor = gl_FrontFacing ? vertexPerFaceColorFront : vertexPerFaceColorBack;
    #else
    vec4 faceVertexColor = vertexColor;
    #endif

    #ifdef DISSOLVE
    if (faceVertexColor.a < texture(DissolveMaskSampler, texCoord0).a) {
        discard;
    }
    // The dissolve effect entirely replaces translucency
    faceVertexColor.a = 1.0;
    #endif

    color *= faceVertexColor * ColorModulator;

    #ifdef GLINT
    color.a = max(color.a, GlintAlpha);
    #endif

    #ifdef OIT_ALPHA_ONLY
    executeAlphaOnlyPhase(gl_FragCoord.z, color.a);
    #else
    fragColor = calculateFinalColor(color, hyper);
    #ifdef PLANEPHYS_RAGDOLL
    // fade the semi-transparent outer skin layer into the layer under it, like up-close player models
    if (ragdollPart > 0.5 && fragColor.a < 1.0) {
        fragColor.a = max(fragColor.a, RAGDOLL_MIN_ALPHA);
        vec3 underCol = texture(Sampler0, ragdollUnderUV).rgb;
        vec3 trueMix = mix(underCol, fragColor.rgb, fragColor.a);
        float fade = mix(fragColor.a, 1.0, clamp((cylindricalVertexDistance - RAGDOLL_FADE_BIAS) / (RAGDOLL_FADE_RANGE - RAGDOLL_FADE_BIAS), 0.0, 1.0));
        fragColor = vec4((trueMix - (1.0 - fade) * underCol) / fade, fade);
        if (fragColor.a < ragdollBayer[int(gl_FragCoord.x) % 4][int(gl_FragCoord.y) % 4] + (0.5 / 16.0)) {
            discard;
        }
        fragColor.a = 1.0;
    }
    #endif
    #endif
}
