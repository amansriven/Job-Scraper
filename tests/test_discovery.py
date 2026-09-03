from scripts.discover_ats import detect_text


def test_detects_jibe_from_rendered_resources():
    result = detect_text(
        "https://example.com/careers",
        "https://careers.example.com/jobs",
        "<html></html>",
        ["https://app.jibecdn.com/prod/search/4.11/main.js"],
    )
    assert result["ats"] == "jibe"
    assert result["config"]["api_base"] == "https://careers.example.com"


def test_rejects_reserved_greenhouse_path():
    result = detect_text(
        "https://example.com/careers",
        "https://example.com/careers",
        '<a href="https://boards.greenhouse.io/embed">jobs</a>',
    )
    assert result is None


def test_detects_jobs2web_configuration_without_vendor_url():
    html = '''
      <form action="/en/search-jobs"></form>
      <section id="search-results" data-organization-ids="49841"></section>
    '''
    result = detect_text("https://example.com/careers", "https://careers.example.com/en", html)
    assert result["ats"] == "successfactors"
    assert result["config"]["organization_id"] == "49841"
