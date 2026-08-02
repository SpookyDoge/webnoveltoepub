from __future__ import annotations

from app.sanitize import html_to_text, sanitize_html


def test_drops_scripts_and_styles():
    result = sanitize_html("<div><p>Tekst</p><script>alert(1)</script><style>p{}</style></div>")
    assert "script" not in result
    assert "alert" not in result
    assert "<p>Tekst</p>" in result


def test_unwraps_unknown_tags_but_keeps_text():
    result = sanitize_html("<p>Ala <mark>ma</mark> kota</p>")
    assert "<mark>" not in result
    assert "ma" in result


def test_strips_disallowed_attributes():
    result = sanitize_html('<p class="x" onclick="hack()" style="color:red">Hej</p>')
    assert "onclick" not in result
    assert "class" not in result
    assert "style" not in result


def test_removes_inline_hidden_elements():
    result = sanitize_html('<div><p>widoczne</p><p style="display:none">pulapka</p></div>')
    assert "pulapka" not in result
    assert "widoczne" in result


def test_removes_elements_hidden_by_stylesheet():
    html = """
    <div>
      <style>.trap { display: none; }</style>
      <p>prawdziwy tekst</p>
      <p class="trap">tekst-pulapka anty-scrapingowa</p>
    </div>
    """
    result = sanitize_html(html)
    assert "pulapka" not in result
    assert "prawdziwy tekst" in result


def test_removes_html_comments():
    """Komentarze sa wypisywane doslownie przez decode() - musza zniknac."""
    result = sanitize_html("<div><p>tekst</p><!-- notatka redakcyjna --></div>")
    assert "notatka" not in result
    assert "<!--" not in result


def test_removes_commented_out_ad_markup():
    """Serwisy trzymaja w komentarzach wylaczony kod reklam."""
    html = """
    <div>
      <p>tresc rozdzialu</p>
      <!--bg-->
      <!--<script async src="https://platform.example/ad.js"></script>-->
      <!--bg end-->
    </div>
    """
    result = sanitize_html(html)
    assert "<script" not in result
    assert "ad.js" not in result
    assert "tresc rozdzialu" in result


def test_images_dropped_by_default_and_kept_on_demand():
    html = '<p>tekst<img src="/a.jpg" alt="x"></p>'
    assert "<img" not in sanitize_html(html)
    assert "<img" in sanitize_html(html, keep_images=True)


def test_relative_links_become_absolute():
    result = sanitize_html('<p><a href="/next">dalej</a></p>', base_url="https://x.test/a/b")
    assert 'href="https://x.test/next"' in result


def test_html_to_text_collapses_whitespace_and_truncates():
    assert html_to_text("<p>a   b</p><p>c</p>") == "a b c"
    assert html_to_text("<p>abcdef</p>", limit=3).startswith("abc")
