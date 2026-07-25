from backend.analyzer import _parse_html

SAMPLE_HTML = """
<html>
<head>
  <title>  Widgets For Sale Online  </title>
  <meta name="description" content="Buy quality widgets. Free shipping on orders over fifty dollars, worldwide.">
</head>
<body>
  <h1>Our Widgets</h1>
  <p>We sell the finest widgets known to humankind. Widgets for every occasion.</p>
  <img src="/hero.png" alt="A row of colorful widgets">
  <img src="/spacer.gif">
  <img src="/icon.png" alt="">
  <script>console.log("this should not count as words on the page");</script>
  <style>.h1 { color: red; }</style>
</body>
</html>
"""

NO_TITLE_HTML = "<html><body><p>Just some text, no head tags at all.</p></body></html>"

MULTI_H1_HTML = "<html><body><h1>First</h1><h1>Second</h1><p>Text</p></body></html>"


def test_extracts_title_and_trims_whitespace():
    result = _parse_html(SAMPLE_HTML)
    assert result["title"] == "Widgets For Sale Online"


def test_extracts_meta_description():
    result = _parse_html(SAMPLE_HTML)
    assert "Buy quality widgets" in result["meta_description"]


def test_h1_count():
    result = _parse_html(SAMPLE_HTML)
    assert result["h1_count"] == 1
    assert _parse_html(MULTI_H1_HTML)["h1_count"] == 2


def test_images_missing_alt_counts_both_absent_and_empty_alt():
    result = _parse_html(SAMPLE_HTML)
    # spacer.gif has no alt attr at all, icon.png has alt="" (empty) -- both count as missing
    assert result["images_total"] == 3
    assert result["images_missing_alt"] == 2
    assert any("spacer.gif" in src for src in result["images_missing_alt_examples"])
    assert any("icon.png" in src for src in result["images_missing_alt_examples"])


def test_script_and_style_excluded_from_word_count():
    result = _parse_html(SAMPLE_HTML)
    assert "console" not in str(result["word_count"])
    # sanity: word count should be small (the visible <p> + <h1> text only),
    # not inflated by the script/style content
    assert result["word_count"] < 20


def test_missing_title_and_meta_return_none_not_crash():
    result = _parse_html(NO_TITLE_HTML)
    assert result["title"] is None
    assert result["meta_description"] is None
    assert result["h1_count"] == 0


def test_malformed_html_does_not_raise():
    # BeautifulSoup with lxml is lenient; unclosed tags shouldn't crash us.
    broken = "<html><body><h1>Oops<p>no closing tags<img src=x.png"
    result = _parse_html(broken)
    assert result["h1_count"] == 1
