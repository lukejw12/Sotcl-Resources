#version 330
#extension GL_ARB_separate_shader_objects : require

uniform sampler2D InSampler;
uniform sampler2D GelSampler;

layout(std140) uniform GelConfig {
    float Opacity;
};

layout(location = 0) in vec2 texCoord;

layout(location = 0) out vec4 fragColor;

void main() {
    vec3 scene = texture(InSampler, texCoord).rgb;
    vec2 screen = vec2(textureSize(InSampler, 0));
    ivec2 size = textureSize(GelSampler, 0);
    float widen = (screen.x / screen.y) / (float(size.x) / float(size.y));
    vec2 uv = vec2(0.5 + (texCoord.x - 0.5) * widen, 1.0 - texCoord.y);
    ivec2 cell = clamp(ivec2(floor(uv * vec2(size))), ivec2(0), size - ivec2(1));
    vec4 gel = texelFetch(GelSampler, cell, 0);
    fragColor = vec4(mix(scene, gel.rgb, gel.a * Opacity), 1.0);
}
