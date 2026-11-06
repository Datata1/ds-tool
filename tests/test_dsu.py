import httpx
import pytest
import respx

from ap_planner.dsu import DsuClient, DsuLinkError, parse_link

KEY_E = "e" * 40
KEY_S = "S" * 40
EDIT = f"https://ds-ultimate.de/tools/attackPlanner/123/edit/{KEY_E}"
SHOW = f"https://ds-ultimate.de/tools/attackPlanner/123/show/{KEY_S}"
EDIT_PAGE = (
    '<b id="title-show" class="h3 card-title">OP | Ziel 480|529</b>'
    f'<input id="link-show" type="text" class="x" value="{SHOW}" />'
)


def test_parse_link() -> None:
    assert parse_link(f"  {EDIT}  ") == (123, "edit", KEY_E)
    with pytest.raises(DsuLinkError):
        parse_link(EDIT[:-1])  # one character missing
    with pytest.raises(DsuLinkError):
        parse_link("https://ds-ultimate.de/tools/attackPlanner/123/show/abc")


@respx.mock
def test_inspect_edit_link() -> None:
    respx.get(EDIT).mock(return_value=httpx.Response(200, text=EDIT_PAGE))
    respx.get(url__regex=r".*/attackListItem/data/123/S+.*").mock(
        return_value=httpx.Response(200, json={"recordsTotal": 5, "data": []})
    )
    info = DsuClient().inspect(EDIT)
    assert info.plan_id == 123
    assert info.show_link == SHOW
    assert info.edit_link == EDIT
    assert info.title == "OP | Ziel 480|529"
    assert info.has_title
    assert info.item_count == 5


@respx.mock
def test_inspect_wrong_key() -> None:
    respx.get(EDIT).mock(return_value=httpx.Response(403))
    with pytest.raises(DsuLinkError, match="Schlüssel"):
        DsuClient().inspect(EDIT)
