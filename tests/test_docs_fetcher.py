from envagent.docs.fetcher import extract_os_section, extract_section

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


SAMPLE_README = """\
# Some Tool

Badges and a table of contents go here, not what we want.

## Install & Update Script

Run this:

    curl -o- https://example.com/install.sh | bash

### Troubleshooting

Nested subsection content that belongs to the install section.

## Usage

This is a completely different section that should not be included.
"""


def test_extract_section_isolates_the_named_heading():
    section = extract_section(SAMPLE_README, "Install & Update Script")
    assert "curl -o-" in section
    assert "Troubleshooting" in section  # nested subsection stays in
    assert "Badges and a table of contents" not in section
    assert "This is a completely different section" not in section


def test_extract_section_is_case_insensitive():
    section = extract_section(SAMPLE_README, "install & update script")
    assert "curl -o-" in section


def test_extract_section_returns_input_unchanged_when_heading_not_found():
    assert extract_section(SAMPLE_README, "Nonexistent Heading") == SAMPLE_README


SAMPLE_README_WITH_CODE_COMMENTS = """\
## Install & Update Script

Run this:

```sh
# Use bash for the shell
curl -o- https://example.com/install.sh | bash
```

#### Additional Notes

More real prose that belongs to the install section.

## Usage

A different section.
"""


def test_extract_section_ignores_hash_comments_inside_fenced_code_blocks():
    # Regression test: a bash comment like "# Use bash for the shell" inside a
    # ```sh fence was previously mistaken for a level-1 Markdown heading,
    # cutting the section off after only a couple of lines. Found live
    # against the real nvm README, which has exactly this shape.
    section = extract_section(SAMPLE_README_WITH_CODE_COMMENTS, "Install & Update Script")
    assert "Additional Notes" in section
    assert "More real prose" in section
    assert "A different section" not in section
