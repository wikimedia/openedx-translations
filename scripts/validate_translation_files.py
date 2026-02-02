"""
Validate translation files using GNU gettext `msgfmt` command.
"""

import argparse
import os
import os.path
import subprocess
import sys
import textwrap
import traceback

import i18n.validate

# Languages to exclude from validation
EXCLUDE_LANGUAGES = {'qqq'}

def get_translation_files(translation_directory):
    """
    List all translations '*.po' files in the specified directory.
    Excludes English source files and excluded language codes.
    """
    po_files = []
    for root, _dirs, files in os.walk(translation_directory):
        for file_name in files:
            pofile_path = os.path.join(root, file_name)

            # Skip English source files
            if file_name.endswith('.po') and '/en/LC_MESSAGES/' not in pofile_path:
                # Skip excluded languages (qqq, etc.)
                skip = False
                for lang in EXCLUDE_LANGUAGES:
                    if f'/{lang}/LC_MESSAGES/' in pofile_path:
                        skip = True
                        break

                if not skip:
                    po_files.append(pofile_path)

    return po_files


def validate_translation_file(po_file):
    """
    Validate a translation file and return errors if any.

    This function combines both stderr and stdout output of the `msgfmt` in a
    single variable.
    """
    valid = True
    output = ""

    completed_process = subprocess.run(
        ['msgfmt', '-v', '--strict', '--check', po_file],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    if completed_process.returncode != 0:
        valid = False

    msgfmt_stdout = completed_process.stdout.decode(encoding='utf-8', errors='replace')
    msgfmt_stderr = completed_process.stderr.decode(encoding='utf-8', errors='replace')
    output += f'{msgfmt_stdout}\n{msgfmt_stderr}\n'

    try:
      problems = i18n.validate.check_messages(po_file)
    except Exception as e:
      output += f'{e} {traceback.format_exc()}'
      valid = False
      problems = []
    if problems:
        valid = False

    id_filler = textwrap.TextWrapper(width=79, initial_indent="  msgid: ", subsequent_indent=" " * 9)
    tx_filler = textwrap.TextWrapper(width=79, initial_indent="  -----> ", subsequent_indent=" " * 9)
    for problem in problems:
        desc, msgid = problem[:2]
        output += f"{desc}\n{id_filler.fill(msgid)}\n"
        for translation in problem[2:]:
            output += f"{tx_filler.fill(translation)}\n"
        output += "\n"

    return {
        'valid': valid,
        'output': output,
    }


def validate_directory(translations_dir):
    """
    Validate all translation files in a single directory.
    Returns tuple: (all_valid, invalid_lines)
    """
    translations_valid = True

    invalid_lines = []

    po_files = get_translation_files(translations_dir)

    if not po_files:
        print(f'No translation files found in: {translations_dir}')
        return translations_valid, invalid_lines

    print(f'\n{"=" * 60}')
    print(f'Validating: {translations_dir}')
    print(f'{"=" * 60}\n')

    for po_file in po_files:
        result = validate_translation_file(po_file)

        if result['valid']:
            print('VALID: ' + po_file)
            print(result['output'], '\n' * 2)
        else:
            invalid_lines.append('INVALID: ' + po_file)
            invalid_lines.append(result['output'] + '\n' * 2)
            translations_valid = False

    return translations_valid, invalid_lines


def validate_translation_files(
    translations_dirs=None,
):
    """
    Run GNU gettext `msgfmt` and print errors to stderr.

    Returns integer OS Exit code:

      return 0 for valid translation.
      return 1 for invalid translations.
    """
    if translations_dirs is None:
        translations_dirs = ['translations', 'translations-custom', 'translations-upstream']

    all_valid = True
    all_invalid_lines = []

    for translations_dir in translations_dirs:
        if not os.path.exists(translations_dir):
            print(f'Directory not found, skipping: {translations_dir}')
            continue

        dir_valid, invalid_lines = validate_directory(translations_dir)

        if not dir_valid:
            all_valid = False
            all_invalid_lines.extend(invalid_lines)

    # Print validation errors in the bottom for easy reading
    if all_invalid_lines:
        print('\n'.join(all_invalid_lines), file=sys.stderr)

    if all_valid:
        print('-----------------------------------------')
        print('SUCCESS: All translation files are valid.')
        print('-----------------------------------------')
        exit_code = 0
    else:
        print('---------------------------------------', file=sys.stderr)
        print('FAILURE: Some translations are invalid.', file=sys.stderr)
        print('---------------------------------------', file=sys.stderr)
        exit_code = 1

    return exit_code


def main():  # pragma: no cover
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--dirs',
        action='store',
        type=str,
        default='translations,translations-custom,translations-upstream',
        help='Comma-separated list of directories to validate (default: translations,translations-custom,translations-upstream)'
    )
    args = parser.parse_args()

    # Split comma-separated directories
    translations_dirs = [d.strip() for d in args.dirs.split(',')]

    sys.exit(validate_translation_files(
        translations_dirs=translations_dirs,
    ))


if __name__ == '__main__':
    main()  # pragma: no cover
