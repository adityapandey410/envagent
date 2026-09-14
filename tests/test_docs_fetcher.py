from envagent.docs.fetcher import extract_os_section

SAMPLE_DOC = """\
# Install Flutter manually

Choose your platform below.

 1. Install Git for Windows
 1. Set up an editor

{: .steps .windows-only}

 1. Install Xcode command-line tools
 1. Set up an editor

{: .steps .macos-only}

 1. Install prerequisite packages with apt-get
 1. Set up an editor

{: .steps .linux-only}

## Verify your installation

Run `flutter doctor` to check your setup.
"""


def test_extract_os_section_isolates_macos_content():
    section = extract_os_section(SAMPLE_DOC, "macos")
    assert "Xcode" in section
    assert "apt-get" not in section
    assert "Git for Windows" not in section


def test_extract_os_section_isolates_windows_content():
    section = extract_os_section(SAMPLE_DOC, "windows")
    assert "Git for Windows" in section
    assert "Xcode" not in section
    assert "apt-get" not in section


def test_extract_os_section_isolates_linux_content():
    section = extract_os_section(SAMPLE_DOC, "linux")
    assert "apt-get" in section
    assert "Xcode" not in section
    assert "Git for Windows" not in section


def test_extract_os_section_keeps_shared_trailing_content_for_every_os():
    for os_key in ("macos", "windows", "linux"):
        section = extract_os_section(SAMPLE_DOC, os_key)
        assert "Verify your installation" in section


def test_extract_os_section_returns_input_unchanged_when_no_markers_present():
    plain = "# Just a normal doc page\n\nNo OS tabs here."
    assert extract_os_section(plain, "macos") == plain
