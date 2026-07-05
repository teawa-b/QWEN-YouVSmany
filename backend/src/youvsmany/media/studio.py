"""The one canonical studio-room description shared by every media prompt.

Research note (Qwen image-edit + Wan-family video prompting): the models keep
scenes consistent across independent generations only when the environment is
described the same way every time. Every image-edit prompt, video-edit prompt
and character-identity prompt therefore embeds this exact scene line, so all
characters and shots land in the same room.

The wording matches the look of the already-generated realistic bank
(frontend/assets/reference/realistic-v1): layered deep-blue backlit panels,
dark rig ceiling, warm walnut desk. The screens are explicitly described as
blank because earlier generations invented garbled broadcast logos.

Keep the JS mirror in frontend/index.html (STUDIO_SCENE) byte-identical —
tests/test_character_bank.py asserts the two stay in sync.
"""

STUDIO_SCENE = (
    "the same modern television debate studio: layered deep-blue backlit wall "
    "panels, a dark ceiling with a visible studio lighting rig, a long warm "
    "walnut debate desk with slim microphones, cool blue ambient light with a "
    "soft warm key light, and plain glowing screen panels with no writing on them"
)
