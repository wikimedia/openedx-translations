"""
Tests for English source-template normalization.

Regression cover for the translatewiki.net "empty message group" bug: the
Translate extension only reads source strings from msgid when the header entry
carries the fuzzy flag, so an English .po that loses the flag renders as an empty
group. The unified sync used to copy extractor output verbatim for repos that do
not exist upstream, which silently dropped the flag.
"""
import polib
import pytest

from ..validate_translation_files import (
    EN_SOURCE_TEMPLATE_DIRS,
    get_en_source_templates,
    validate_directory,
    validate_en_source_template,
)
from ..wikimedia_workflow_logic import (
    is_en_source_template,
    normalize_en_source_templates,
)

# A minimal English source template, as xgettext emits it (no fuzzy flag).
EN_PO_WITHOUT_FUZZY = '''# Translation file.
msgid ""
msgstr ""
"Project-Id-Version: 0.1a\\n"
"Language: en\\n"
"MIME-Version: 1.0\\n"
"Content-Type: text/plain; charset=UTF-8\\n"

msgid "Hello"
msgstr ""
'''

# A translation file. Must never be flagged as a template.
AR_PO = '''# Translation file.
msgid ""
msgstr ""
"Project-Id-Version: 0.1a\\n"
"Language: ar\\n"
"MIME-Version: 1.0\\n"
"Content-Type: text/plain; charset=UTF-8\\n"
"Plural-Forms: nplurals=6; plural=(n==0 ? 0 : n==1 ? 1 : 2);\\n"

msgid "Hello"
msgstr "مرحبا"
'''


def write_po(base, rel_path, content):
    path = base / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


@pytest.mark.parametrize("rel_path, expected", [
    ("repo/conf/locale/en/LC_MESSAGES/django.po", True),
    ("repo/conf/locale/en/LC_MESSAGES/djangojs.po", True),
    ("repo/nested/pkg/conf/locale/en/LC_MESSAGES/djangojs.po", True),
    # Not English source templates:
    ("repo/conf/locale/ar/LC_MESSAGES/django.po", False),
    ("repo/conf/locale/en_GB/LC_MESSAGES/django.po", False),
    ("repo/conf/locale/qqq/LC_MESSAGES/django.po", False),
    # 'en' must be the locale dir, not just any path segment:
    ("en/conf/locale/ar/LC_MESSAGES/django.po", False),
    ("repo/conf/locale/en/LC_MESSAGES/django.mo", False),
])
def test_is_en_source_template(rel_path, expected):
    assert is_en_source_template(rel_path) is expected


def test_adds_missing_fuzzy_flag(tmp_path):
    """The core regression: an unmarked English file gets the flag back."""
    po_path = write_po(tmp_path, "repo/conf/locale/en/LC_MESSAGES/djangojs.po",
                       EN_PO_WITHOUT_FUZZY)
    assert not polib.pofile(po_path).metadata_is_fuzzy

    assert normalize_en_source_templates(tmp_path) == 1

    po = polib.pofile(po_path)
    assert po.metadata_is_fuzzy == ["fuzzy"]
    assert po.metadata["Plural-Forms"] == "nplurals=2; plural=(n != 1);"
    # Content must survive untouched.
    assert po.find("Hello") is not None


def test_never_touches_translations(tmp_path):
    """Flagging a translation fuzzy would mark its strings unreviewed."""
    ar_path = write_po(tmp_path, "repo/conf/locale/ar/LC_MESSAGES/django.po", AR_PO)
    before = ar_path.read_bytes()

    assert normalize_en_source_templates(tmp_path) == 0

    assert ar_path.read_bytes() == before
    po = polib.pofile(ar_path)
    assert not po.metadata_is_fuzzy
    # The Arabic plural rule must not be overwritten with the English one.
    assert "nplurals=6" in po.metadata["Plural-Forms"]


def test_is_idempotent(tmp_path):
    """A second run must be a no-op, so the sync does not churn the diff."""
    po_path = write_po(tmp_path, "repo/conf/locale/en/LC_MESSAGES/django.po",
                       EN_PO_WITHOUT_FUZZY)

    assert normalize_en_source_templates(tmp_path) == 1
    after_first = po_path.read_bytes()

    assert normalize_en_source_templates(tmp_path) == 0
    assert po_path.read_bytes() == after_first


def test_resolves_placeholder_plural_forms(tmp_path):
    """xgettext leaves an INTEGER placeholder that Translate rejects."""
    content = EN_PO_WITHOUT_FUZZY.replace(
        '"Language: en\\n"',
        '"Language: en\\n"\n"Plural-Forms: nplurals=INTEGER; plural=EXPRESSION;\\n"',
    )
    po_path = write_po(tmp_path, "repo/conf/locale/en/LC_MESSAGES/django.po", content)

    assert normalize_en_source_templates(tmp_path) == 1
    assert polib.pofile(po_path).metadata["Plural-Forms"] == "nplurals=2; plural=(n != 1);"


def test_survives_unreadable_file(tmp_path):
    """One malformed file must not abort the whole sweep."""
    write_po(tmp_path, "repo/conf/locale/en/LC_MESSAGES/django.po", "this is not a po file{")
    good = write_po(tmp_path, "other/conf/locale/en/LC_MESSAGES/django.po",
                    EN_PO_WITHOUT_FUZZY)

    normalize_en_source_templates(tmp_path)

    assert polib.pofile(good).metadata_is_fuzzy == ["fuzzy"]


# --- validator ---------------------------------------------------------------

def test_validator_flags_missing_fuzzy(tmp_path):
    po_path = write_po(tmp_path, "repo/conf/locale/en/LC_MESSAGES/djangojs.po",
                       EN_PO_WITHOUT_FUZZY)

    result = validate_en_source_template(str(po_path))

    assert result['valid'] is False
    assert 'fuzzy' in result['output']


def test_validator_accepts_normalized_file(tmp_path):
    po_path = write_po(tmp_path, "repo/conf/locale/en/LC_MESSAGES/djangojs.po",
                       EN_PO_WITHOUT_FUZZY)
    normalize_en_source_templates(tmp_path)

    assert validate_en_source_template(str(po_path))['valid'] is True


def test_en_check_is_off_by_default(tmp_path):
    """
    Upstream passthrough must not fail the build.

    translations/ is mostly Atlas output and 26 of its English templates
    legitimately lack the flag, so the check has to stay opt-in per directory.
    """
    write_po(tmp_path, "repo/conf/locale/en/LC_MESSAGES/django.po", EN_PO_WITHOUT_FUZZY)

    valid, _lines = validate_directory(str(tmp_path))
    assert valid is True, "unmarked English file must not fail an unchecked directory"

    valid, lines = validate_directory(str(tmp_path), check_en_templates=True)
    assert valid is False
    assert any('fuzzy' in line for line in lines)


def test_custom_layer_is_checked_but_not_upstream():
    assert 'translations-custom' in EN_SOURCE_TEMPLATE_DIRS
    assert 'translations' not in EN_SOURCE_TEMPLATE_DIRS


def test_validator_collects_only_en_files(tmp_path):
    write_po(tmp_path, "repo/conf/locale/en/LC_MESSAGES/django.po", EN_PO_WITHOUT_FUZZY)
    write_po(tmp_path, "repo/conf/locale/ar/LC_MESSAGES/django.po", AR_PO)

    found = get_en_source_templates(str(tmp_path))

    assert len(found) == 1
    assert found[0].endswith("en/LC_MESSAGES/django.po")
