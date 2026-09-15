from envagent.recipes.registry import Recipe, resolve_doc_url


def test_resolve_doc_url_passes_through_a_plain_string():
    recipe = Recipe(name="flutter", aliases=["flutter"], doc_url="https://example.com/install")
    assert resolve_doc_url(recipe, "macos") == "https://example.com/install"
    assert resolve_doc_url(recipe, "linux") == "https://example.com/install"


def test_resolve_doc_url_picks_the_matching_os_from_a_dict():
    recipe = Recipe(
        name="docker",
        aliases=["docker"],
        doc_url={"macos": "https://example.com/mac", "linux": "https://example.com/ubuntu"},
    )
    assert resolve_doc_url(recipe, "macos") == "https://example.com/mac"
    assert resolve_doc_url(recipe, "linux") == "https://example.com/ubuntu"


def test_resolve_doc_url_returns_none_for_an_uncovered_os():
    recipe = Recipe(
        name="docker",
        aliases=["docker"],
        doc_url={"macos": "https://example.com/mac", "linux": "https://example.com/ubuntu"},
    )
    assert resolve_doc_url(recipe, "windows") is None
