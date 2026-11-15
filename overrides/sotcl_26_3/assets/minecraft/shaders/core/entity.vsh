#version 330
#extension GL_ARB_separate_shader_objects : require

#if defined(PER_FACE_LIGHTING) || !defined(NO_CARDINAL_LIGHTING)
#include <minecraft:light.glsl>
#endif
#include <minecraft:fog.glsl>
#include <minecraft:dynamictransforms.glsl>
#include <minecraft:projection.glsl>
#include <minecraft:sample_lightmap.glsl>
#include <minecraft:sotcl_nv.glsl>

#if defined(ALPHA_CUTOUT) && !defined(EMISSIVE) && !defined(NO_OVERLAY) && !defined(APPLY_TEXTURE_MATRIX)
#define PLANEPHYS_RAGDOLL 1
#endif

layout(location = 0) in vec3 Position;
layout(location = 1) in vec4 Color;
layout(location = 2) in vec2 UV0;
layout(location = 3) in ivec2 UV1;
layout(location = 4) in ivec2 UV2;
layout(location = 5) in vec3 Normal;

#if !defined(NO_OVERLAY) && !defined(OIT_ALPHA_ONLY)
uniform sampler2D Sampler1;
#endif

#ifdef PLANEPHYS_RAGDOLL
uniform sampler2D Sampler0;
#define RAGDOLL_SPACING 1024.0
#define RAGDOLL_MAXRANGE 512.0
#endif

#if !defined(EMISSIVE) && !defined(OIT_ALPHA_ONLY)
uniform sampler2D Sampler2;
#endif

layout(location = 0) out float sphericalVertexDistance;
layout(location = 1) out float cylindricalVertexDistance;

#ifdef PER_FACE_LIGHTING
layout(location = 2) out vec4 vertexPerFaceColorBack;
layout(location = 3) out vec4 vertexPerFaceColorFront;
#else
layout(location = 2) out vec4 vertexColor;
#endif

#ifndef EMISSIVE
layout(location = 4) out vec4 lightMapColor;
#endif

#ifndef NO_OVERLAY
layout(location = 5) out vec4 overlayColor;
#endif

layout(location = 6) out vec2 texCoord0;
layout(location = 8) out float nvFactor;
#ifdef PLANEPHYS_RAGDOLL
layout(location = 9) out float ragdollPart;
#endif
#ifdef GLINT
layout(location = 7) out vec2 texCoordGlint;
#endif

void main() {
    gl_Position = ProjMat * ModelViewMat * vec4(Position, 1.0);

    sphericalVertexDistance = fog_spherical_distance(Position);
    cylindricalVertexDistance = fog_cylindrical_distance(Position);

#ifdef PER_FACE_LIGHTING
    vec2 light = minecraft_compute_light(Light0_Direction, Light1_Direction, Normal);
    vertexPerFaceColorBack = minecraft_mix_light_separate(-light, Color);
    vertexPerFaceColorFront = minecraft_mix_light_separate(light, Color);
#elif defined(NO_CARDINAL_LIGHTING)
    vertexColor = Color;
#else
    vertexColor = minecraft_mix_light(Light0_Direction, Light1_Direction, Normal, Color);
#endif

#if !defined(EMISSIVE) && !defined(OIT_ALPHA_ONLY)
    lightMapColor = sample_lightmap(Sampler2, UV2);
    nvFactor = sotcl_nv_factor(Sampler2);
#else
    nvFactor = 0.0;
#endif

#if !defined(NO_OVERLAY) && !defined(OIT_ALPHA_ONLY)
    overlayColor = texelFetch(Sampler1, UV1, 0);
#endif

    texCoord0 = UV0;

#ifdef APPLY_TEXTURE_MATRIX
    texCoord0 = (TextureMat * vec4(UV0, 0.0, 1.0)).xy;
#endif

#ifdef GLINT
    texCoordGlint = (TextureMat * vec4(UV0, 0.0, 1.0)).xy;
#endif

#ifdef PLANEPHYS_RAGDOLL
    ragdollPart = 0.0;
    {
        ivec2 skinSize = textureSize(Sampler0, 0);
        // world view (not the GUI) and a skin or mob texture: 64x64 / 64x32 or HD multiples of them
        if (abs(ProjMat[2][3]) > 1e-5 && skinSize.x >= 64 && (skinSize.x % 64) == 0 && (skinSize.y == skinSize.x || skinSize.y * 2 == skinSize.x)) {
            int limb = -int((Position.y - RAGDOLL_MAXRANGE) / RAGDOLL_SPACING);
            if (limb >= 1 && limb <= 25) {
                ragdollPart = float(limb);
                vec3 wpos = Position + vec3(0.0, RAGDOLL_SPACING * float(limb), 0.0);
                gl_Position = ProjMat * ModelViewMat * vec4(wpos, 1.0);
                sphericalVertexDistance = fog_spherical_distance(wpos);
                cylindricalVertexDistance = fog_cylindrical_distance(wpos);
            }
        }
    }
#endif
}
