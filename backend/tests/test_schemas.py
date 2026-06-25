import pytest
from pydantic import ValidationError

from youvsmany.contracts import Cast, Character, ShowBrief
from youvsmany.contracts.enums import Role, Stance


def test_brief_duration_bounds():
    with pytest.raises(ValidationError):
        ShowBrief(topic="x", target_duration_s=30)
    ShowBrief(topic="Pineapple belongs on pizza", target_duration_s=90)


def _char(cid, role, stance, tag):
    return Character(
        character_id=cid,
        display_name=cid.title(),
        role=role,
        stance=stance,
        core_contention=f"{tag} matters",
        contention_tag=tag,
        supporting_points=["a", "b"],
    )


def test_cast_requires_challenger_and_lookup():
    cast = Cast(
        protagonist=_char("protagonist", Role.PROTAGONIST, Stance.FOR, "thesis"),
        challengers=[_char("challenger_texture", Role.CHALLENGER, Stance.AGAINST, "texture")],
        moderator=_char("moderator", Role.MODERATOR, Stance.NEUTRAL, "control"),
    )
    assert cast.by_id("challenger_texture").contention_tag == "texture"
    with pytest.raises(ValidationError):
        Cast(
            protagonist=cast.protagonist,
            challengers=[],
            moderator=cast.moderator,
        )
