#!/usr/bin/env python3
"""
Logic for Wikimedia Unified Translation Workflow:
1. diff_and_update_custom: Compares extracted sources against upstream and updates translations-custom/.
2. merge_final: Overlays translations-custom/ onto translations-upstream/ to produce translations/.
3. Special handling for repos that merge (e.g., tutor-indigo-wikilearn → edx-platform):
   - At EXTRACTION: Compare with target repo and REMOVE duplicates (keep only truly custom strings)
   - At MERGE: Simple append (no duplicate checking needed since already filtered)
"""
import os
import json
import shutil
import argparse
from pathlib import Path
import polib

REPO_ROOT = Path(__file__).resolve().parent.parent
UPSTREAM_DIR = REPO_ROOT / "translations-upstream"
CUSTOM_DIR = REPO_ROOT / "translations-custom"
FINAL_DIR = REPO_ROOT / "translations"

# Configuration for repos that should be merged into other repos during final merge
REPO_MERGE_CONFIG = {
    "tutor-indigo-wikilearn": {
        "merge_into": "edx-platform",
        "description": "Indigo theme translations merged into edx-platform"
    }
}


def ensure_directory(path):
    if not os.path.exists(path):
        os.makedirs(path, exist_ok=True)


def get_msgids(po_file_path):
    """Get all msgids from a PO file, handling edge cases."""
    if not os.path.exists(po_file_path):
        return set()
    try:
        po = polib.pofile(po_file_path)
        # Filter out empty msgids and metadata entries
        return {entry.msgid for entry in po if entry.msgid and not entry.obsolete}
    except Exception as e:
        print(f"Error reading {po_file_path}: {e}")
        return set()


def get_supported_languages():
    """
    Determine all supported languages from upstream translations.
    Returns a list of language codes.
    """
    supported_langs = set()

    # Scan upstream for language directories
    for repo_dir in UPSTREAM_DIR.iterdir():
        if not repo_dir.is_dir():
            continue

        # Check for Django-style locale directories (including nested structures)
        for locale_dir in repo_dir.rglob("locale"):
            if locale_dir.is_dir():
                for lang_dir in locale_dir.iterdir():
                    if lang_dir.is_dir() and lang_dir.name != "en":
                        supported_langs.add(lang_dir.name)

        # Check for MFE-style i18n directories (src/i18n/messages/)
        for i18n_dir in repo_dir.rglob("i18n"):
            messages_dir = i18n_dir / "messages"
            if messages_dir.exists():
                for lang_file in messages_dir.glob("*.json"):
                    lang_code = lang_file.stem
                    if lang_code != "en":
                        supported_langs.add(lang_code)

    return sorted(list(supported_langs))


def should_merge_into_another_repo(repo_name):
    """Check if this repo should be merged into another repo instead of standalone."""
    return repo_name in REPO_MERGE_CONFIG


def get_merge_target_repo(repo_name):
    """Get the target repo name for merging."""
    if repo_name in REPO_MERGE_CONFIG:
        return REPO_MERGE_CONFIG[repo_name]["merge_into"]
    return None


def update_custom_layer(extracted_dir):
    """
    Step 3: Update translations-custom based on diff between extracted and upstream.
    Always maintains existing translations.
    Creates placeholders for all languages.
    Handles BOTH django.po and djangojs.po files.

    Special handling for repos in REPO_MERGE_CONFIG:
    - Compare with TARGET repo (not upstream source repo)
    - Remove duplicates at extraction time
    - Also compare against extracted target repo files (covers case where
      upstream English source files are unavailable)
    - Rebuild custom files for merge-target repos to remove stale duplicates
    """
    print(f"--- Updating Custom Layer from {extracted_dir} ---")
    extracted_path = Path(extracted_dir)

    # 1. Determine all supported languages from upstream
    supported_langs = get_supported_languages()
    print(f"Found {len(supported_langs)} supported languages in upstream: {', '.join(supported_langs[:10])}...")

    # 2. Collect all extracted files, then sort so that target repos
    #    (e.g. edx-platform) are processed BEFORE repos that merge into them
    #    (e.g. tutor-indigo-wikilearn). This ensures the target repo's custom
    #    file is up-to-date before dependent repos compare against it.
    merge_source_repos = set(REPO_MERGE_CONFIG.keys())

    all_extracted = []
    for ext in ["**/*.po", "**/*.json"]:
        for extracted_file in extracted_path.glob(ext):
            rel_path = extracted_file.relative_to(extracted_path)
            repo_name = rel_path.parts[0]
            all_extracted.append((extracted_file, rel_path, repo_name))

    # Sort: non-merge-source repos first, merge-source repos last
    all_extracted.sort(key=lambda x: (1 if x[2] in merge_source_repos else 0, str(x[1])))

    # 3. Process each extracted file
    for extracted_file, rel_path, repo_name in all_extracted:
        # Check if this repo will be merged into another
        target_repo = get_merge_target_repo(repo_name)
        if target_repo:
            print(f"Note: {repo_name} will be merged into {target_repo} - filtering duplicates at extraction")

        # Find corresponding upstream source file
        upstream_source = UPSTREAM_DIR / rel_path
        upstream_repo_dir = UPSTREAM_DIR / rel_path.parts[0]

        # Identify file type for logging
        file_type = "unknown"
        if "djangojs.po" in str(rel_path):
            file_type = "djangojs.po (JavaScript)"
        elif "django.po" in str(rel_path):
            file_type = "django.po (Templates/Python)"
        elif "transifex_input.json" in str(rel_path):
            file_type = "transifex_input.json (MFE source)"
        elif ".json" in str(rel_path):
            file_type = "JSON (MFE)"

        print(
            f"Processing: {rel_path} [{file_type}] (Upstream repo exists: {upstream_repo_dir.exists()}, Source exists: {upstream_source.exists()})")

        # Determine what to compare against for duplicate filtering
        is_merge_source = False
        if target_repo:
            is_merge_source = True
            # This repo merges into another - compare with TARGET repo to filter duplicates
            # Rewrite path to target repo
            rel_path_parts = list(rel_path.parts)
            rel_path_parts[0] = target_repo
            target_path = Path(*rel_path_parts)

            # Check target repo in upstream, custom, AND extracted sources
            comparison_source = UPSTREAM_DIR / target_path
            comparison_custom = CUSTOM_DIR / target_path
            comparison_extracted = extracted_path / target_path

            print(f"  Comparing with target repo {target_repo} to filter duplicates...")
        elif not upstream_repo_dir.exists():
            # New repo not in upstream AND not in merge config - treat all as custom
            print(f"New repo detected: {rel_path.parts[0]}. Treating all content as custom.")

            # Copy English source to custom
            custom_file_path = CUSTOM_DIR / rel_path
            ensure_directory(custom_file_path.parent)
            shutil.copy(extracted_file, custom_file_path)
            print(f"  -> Copied to custom: {custom_file_path}")

            # Create/update placeholders for other languages
            if extracted_file.suffix == ".po":
                create_or_update_po_placeholders(extracted_file, rel_path, supported_langs)
            elif extracted_file.suffix == ".json":
                create_or_update_json_placeholders(extracted_file, rel_path, supported_langs)
            continue
        else:
            # Normal case - compare with upstream source
            comparison_source = upstream_source
            comparison_custom = None
            comparison_extracted = None

        # Process based on file type
        if extracted_file.suffix == ".po":
            process_po_diff(extracted_file, comparison_source, comparison_custom,
                            rel_path, supported_langs, comparison_extracted, is_merge_source)
        elif extracted_file.suffix == ".json":
            process_json_diff(extracted_file, comparison_source, comparison_custom,
                              rel_path, supported_langs, comparison_extracted, is_merge_source)


def create_or_update_po_placeholders(extracted_file, rel_path, supported_langs):
    """
    Create NEW PO files OR update EXISTING ones with new strings for all supported languages.
    Handles both django.po and djangojs.po files.
    Supports nested repo structures.
    """
    print(f"  Creating/updating PO placeholders for {len(supported_langs)} languages...")

    try:
        po = polib.pofile(extracted_file)
        en_entries = {e.msgid: e for e in po if e.msgid and not e.obsolete}
    except Exception as e:
        print(f"  WARNING: Cannot read extracted file for placeholders: {e}")
        return

    created = 0
    updated = 0
    skipped = 0

    for lang in supported_langs:
        parts = list(rel_path.parts)

        try:
            # Find 'en' in the path - it should be in locale/en pattern
            en_index = parts.index("en")

            # Verify this is a locale/en pattern
            if en_index > 0 and parts[en_index - 1] == "locale":
                parts[en_index] = lang
                p_path = CUSTOM_DIR / Path(*parts)

                if p_path.exists():
                    # File exists - update it with new strings
                    try:
                        existing_po = polib.pofile(p_path)
                        existing_msgids = {e.msgid for e in existing_po}

                        added = 0
                        for msgid, entry in en_entries.items():
                            if msgid not in existing_msgids:
                                existing_po.append(polib.POEntry(
                                    msgid=msgid,
                                    msgstr="",
                                    occurrences=entry.occurrences
                                ))
                                added += 1

                        if added > 0:
                            existing_po.save(p_path)
                            updated += 1
                            print(f"    ✅ Updated {lang}: +{added} strings")
                        else:
                            skipped += 1
                    except Exception as e:
                        print(f"    ❌ ERROR updating {lang}: {e}")
                else:
                    # File doesn't exist - create it
                    ensure_directory(p_path.parent)
                    new_po = polib.POFile()
                    new_po.metadata = po.metadata.copy()

                    # Preserve Domain metadata for djangojs.po files
                    if "djangojs" in str(rel_path):
                        new_po.metadata['Domain'] = 'djangojs'

                    for entry in po:
                        if entry.msgid:
                            new_po.append(polib.POEntry(
                                msgid=entry.msgid,
                                msgstr="",
                                occurrences=entry.occurrences
                            ))
                    new_po.save(p_path)
                    created += 1
                    print(f"    ✅ Created {lang}: {len(en_entries)} strings")
        except ValueError:
            print(f"  WARNING: Could not find 'en' in path for {rel_path}, skipping placeholder creation")
            continue

    print(f"  Summary: Created {created}, Updated {updated}, Already synced {skipped}")


def create_or_update_json_placeholders(extracted_file, rel_path, supported_langs):
    """
    Create NEW JSON files OR update EXISTING ones for all supported languages (MFE pattern).
    Handles both transifex_input.json and direct message files.
    """
    print(f"  Creating/updating JSON placeholders for {len(supported_langs)} languages...")

    try:
        with open(extracted_file, "r", encoding="utf-8") as f:
            en_data = json.load(f)
    except json.JSONDecodeError as e:
        print(f"  WARNING: Malformed JSON in {extracted_file}: {e}")
        return
    except Exception as e:
        print(f"  ERROR reading {extracted_file}: {e}")
        return

    # Determine messages directory based on extracted file location
    repo_name = rel_path.parts[0]
    messages_dir = CUSTOM_DIR / repo_name / "src" / "i18n" / "messages"
    messages_dir.mkdir(parents=True, exist_ok=True)

    created = 0
    updated = 0
    skipped = 0

    # Create/update placeholder for each language
    for lang in supported_langs:
        lang_path = messages_dir / f"{lang}.json"

        if lang_path.exists():
            # File exists - update with new keys
            try:
                with open(lang_path, "r", encoding="utf-8") as f:
                    existing_data = json.load(f)
            except:
                existing_data = {}

            new_keys = {k: "" for k in en_data.keys() if k not in existing_data}

            if new_keys:
                existing_data.update(new_keys)
                with open(lang_path, "w", encoding="utf-8") as f:
                    json.dump(existing_data, f, indent=2, sort_keys=True, ensure_ascii=False)
                updated += 1
                print(f"    ✅ Updated {lang}: +{len(new_keys)} keys")
            else:
                skipped += 1
        else:
            # File doesn't exist - create it
            placeholder_data = {key: "" for key in en_data.keys()}
            with open(lang_path, "w", encoding="utf-8") as f:
                json.dump(placeholder_data, f, indent=2, sort_keys=True, ensure_ascii=False)
            created += 1
            print(f"    ✅ Created {lang}: {len(en_data)} keys")

    print(f"  Summary: Created {created}, Updated {updated}, Already synced {skipped}")


def process_po_diff(extracted_file, comparison_source, comparison_custom, rel_path,
                    supported_langs, comparison_extracted=None, is_merge_source=False):
    """
    Process PO file diff and update custom layer.
    Updates existing placeholder files with new custom strings.

    Compares against comparison_source, comparison_custom, and comparison_extracted
    to filter duplicates.

    When is_merge_source=True (repo merges into another), the custom file is rebuilt
    from scratch to remove stale entries from previous runs.
    """
    # Get msgids from all comparison sources
    comparison_ids = get_msgids(comparison_source)

    # Also check custom layer if provided (for target repo merging)
    if comparison_custom and comparison_custom.exists():
        comparison_ids.update(get_msgids(comparison_custom))

    # Also check extracted target repo files (critical fallback when upstream
    # English source files are not available, e.g. if Atlas doesn't pull them)
    if comparison_extracted and comparison_extracted.exists():
        comparison_ids.update(get_msgids(comparison_extracted))

    if is_merge_source:
        print(f"  Found {len(comparison_ids)} msgids in target repo to filter out")

    try:
        extracted_po = polib.pofile(extracted_file)
    except Exception as e:
        print(f"  ERROR: Cannot read extracted PO file {rel_path}: {e}")
        return

    # Filter out empty msgids, metadata, and duplicates
    custom_entries = [e for e in extracted_po if e.msgid and not e.obsolete and e.msgid not in comparison_ids]

    if not custom_entries:
        print(f"  No unique custom PO strings found for {rel_path}")
        # If this is a merge-source repo and we found no unique strings,
        # remove the stale custom file if it exists
        if is_merge_source:
            custom_en_path = CUSTOM_DIR / rel_path
            if custom_en_path.exists():
                custom_en_path.unlink()
                print(f"  Removed stale custom file: {custom_en_path}")
        return

    print(f"  Found {len(custom_entries)} unique custom strings for {rel_path}")

    # Update English Custom File
    custom_en_path = CUSTOM_DIR / rel_path
    ensure_directory(custom_en_path.parent)

    if is_merge_source:
        # For merge-source repos, REBUILD from scratch to remove stale entries
        custom_en_po = polib.POFile()
        custom_en_po.metadata = extracted_po.metadata.copy()
        for entry in custom_entries:
            custom_en_po.append(entry)
        custom_en_po.save(custom_en_path)
        print(f"  Rebuilt custom file with {len(custom_entries)} filtered strings: {custom_en_path}")
    else:
        # For normal repos, append new entries (preserves manually-added translations)
        if custom_en_path.exists():
            try:
                custom_en_po = polib.pofile(custom_en_path)
                existing_custom_ids = {e.msgid for e in custom_en_po}
            except Exception as e:
                print(f"  WARNING: Cannot read existing custom file, creating new: {e}")
                custom_en_po = polib.POFile()
                custom_en_po.metadata = extracted_po.metadata.copy()
                existing_custom_ids = set()
        else:
            custom_en_po = polib.POFile()
            custom_en_po.metadata = extracted_po.metadata.copy()
            existing_custom_ids = set()

        new_count = 0
        for entry in custom_entries:
            if entry.msgid not in existing_custom_ids:
                custom_en_po.append(entry)
                new_count += 1

        if new_count > 0:
            custom_en_po.save(custom_en_path)
            print(f"  Added {new_count} new custom strings to {custom_en_path}")

    # Update Placeholders for ALL other languages
    print(f"  Updating placeholders for {len(supported_langs)} languages...")

    updated_count = 0
    for lang in supported_langs:
        parts = list(rel_path.parts)
        try:
            # Find 'en' in the path - it should be in locale/en pattern
            en_index = parts.index("en")

            # Verify this is actually a locale directory
            if en_index > 0 and parts[en_index - 1] == "locale":
                parts[en_index] = lang
                custom_lang_path = CUSTOM_DIR / Path(*parts)
                ensure_directory(custom_lang_path.parent)

                if custom_lang_path.exists():
                    try:
                        custom_lang_po = polib.pofile(custom_lang_path)
                    except Exception as e:
                        print(f"  WARNING: Cannot read existing placeholder for {lang}, creating new: {e}")
                        custom_lang_po = polib.POFile()
                        custom_lang_po.metadata = extracted_po.metadata.copy()
                else:
                    custom_lang_po = polib.POFile()
                    custom_lang_po.metadata = extracted_po.metadata.copy()

                if is_merge_source:
                    # Rebuild: keep only entries whose msgid is in custom_entries,
                    # preserving existing translations (msgstr)
                    existing_translations = {e.msgid: e.msgstr for e in custom_lang_po
                                             if e.msgid and e.msgstr}
                    rebuilt_po = polib.POFile()
                    rebuilt_po.metadata = custom_lang_po.metadata.copy() if custom_lang_po.metadata else extracted_po.metadata.copy()
                    for entry in custom_entries:
                        rebuilt_po.append(polib.POEntry(
                            msgid=entry.msgid,
                            msgstr=existing_translations.get(entry.msgid, ""),
                            occurrences=entry.occurrences
                        ))
                    rebuilt_po.save(custom_lang_path)
                    updated_count += 1
                else:
                    # Normal: add new entries
                    existing_lang_map = {e.msgid: e for e in custom_lang_po}
                    added = 0
                    for entry in custom_entries:
                        if entry.msgid not in existing_lang_map:
                            new_entry = polib.POEntry(msgid=entry.msgid, msgstr="", occurrences=entry.occurrences)
                            custom_lang_po.append(new_entry)
                            added += 1

                    if added > 0:
                        custom_lang_po.save(custom_lang_path)
                        updated_count += 1
        except ValueError:
            print(f"  WARNING: Could not find 'en' in path for {rel_path}, skipping language {lang}")
            continue

    if updated_count > 0:
        print(f"  Updated {updated_count} language placeholder files")


def process_json_diff(extracted_file, comparison_source, comparison_custom, rel_path,
                      supported_langs, comparison_extracted=None, is_merge_source=False):
    """
    Process JSON diff for MFE transifex_input.json files.
    Only keeps keys that don't exist in comparison source(s).
    Updates existing placeholder files with new keys.

    When is_merge_source=True, rebuilds the custom file to remove stale entries.
    """
    try:
        with open(extracted_file, "r", encoding="utf-8") as f:
            extracted_data = json.load(f)
    except json.JSONDecodeError as e:
        print(f"  ERROR: Malformed extracted JSON {rel_path}: {e}")
        return
    except Exception as e:
        print(f"  ERROR reading extracted JSON {rel_path}: {e}")
        return

    # Get keys from all comparison sources
    comparison_keys = set()

    if comparison_source.exists():
        try:
            with open(comparison_source, "r", encoding="utf-8") as f:
                data = json.load(f)
                comparison_keys.update(data.keys())
        except Exception:
            pass

    # Also check custom layer if provided (for target repo merging)
    if comparison_custom and comparison_custom.exists():
        try:
            with open(comparison_custom, "r", encoding="utf-8") as f:
                data = json.load(f)
                comparison_keys.update(data.keys())
        except Exception:
            pass

    # Also check extracted target repo files (fallback for missing upstream)
    if comparison_extracted and comparison_extracted.exists():
        try:
            with open(comparison_extracted, "r", encoding="utf-8") as f:
                data = json.load(f)
                comparison_keys.update(data.keys())
        except Exception:
            pass

    if is_merge_source:
        print(f"  Found {len(comparison_keys)} keys in target repo to filter out")

    # Only keep keys that are NOT in comparison set
    custom_data = {k: v for k, v in extracted_data.items() if k not in comparison_keys}

    if not custom_data:
        print(f"  No unique custom JSON strings for {rel_path}")
        return

    print(f"  Found {len(custom_data)} unique custom JSON keys for {rel_path}")

    custom_path = CUSTOM_DIR / rel_path
    ensure_directory(custom_path.parent)

    if is_merge_source:
        # Rebuild from scratch for merge-source repos
        try:
            with open(custom_path, "w", encoding="utf-8") as f:
                json.dump(custom_data, f, indent=2, sort_keys=True, ensure_ascii=False)
            print(f"  Rebuilt custom JSON with {len(custom_data)} filtered keys: {custom_path}")
        except Exception as e:
            print(f"  ERROR writing custom JSON {custom_path}: {e}")
            return
    else:
        if custom_path.exists():
            try:
                with open(custom_path, "r", encoding="utf-8") as f:
                    existing_custom = json.load(f)
            except Exception:
                existing_custom = {}
        else:
            existing_custom = {}

        # Merge new custom keys while preserving existing ones
        new_keys = {k: v for k, v in custom_data.items() if k not in existing_custom}
        existing_custom.update(new_keys)

        try:
            with open(custom_path, "w", encoding="utf-8") as f:
                json.dump(existing_custom, f, indent=2, sort_keys=True, ensure_ascii=False)

            print(f"  Added {len(new_keys)} new custom JSON keys to {custom_path}")
        except Exception as e:
            print(f"  ERROR writing custom JSON {custom_path}: {e}")
            return

    # Update MFE localized placeholders
    if "transifex_input.json" in str(rel_path):
        update_mfe_localized_placeholders(custom_data, rel_path, supported_langs)


def update_mfe_localized_placeholders(custom_data, rel_path, supported_langs):
    """
    Create/update localized JSON placeholders for MFE custom strings.
    Converts transifex_input.json custom keys -> src/i18n/messages/{lang}.json
    """
    parts = list(rel_path.parts)
    repo_name = parts[0]
    messages_base = CUSTOM_DIR / repo_name / "src" / "i18n" / "messages"
    ensure_directory(messages_base)

    print(f"  Updating MFE localized files for {len(supported_langs)} languages...")

    updated_count = 0
    for lang in supported_langs:
        lang_file = messages_base / f"{lang}.json"

        try:
            if lang_file.exists():
                with open(lang_file, "r", encoding="utf-8") as f:
                    existing_data = json.load(f)
            else:
                existing_data = {}
        except:
            existing_data = {}

        # Add placeholders for custom keys that don't exist
        new_keys = 0
        for key in custom_data.keys():
            if key not in existing_data:
                existing_data[key] = ""
                new_keys += 1

        if new_keys > 0:
            try:
                with open(lang_file, "w", encoding="utf-8") as f:
                    json.dump(existing_data, f, indent=2, sort_keys=True, ensure_ascii=False)
                updated_count += 1
            except Exception as e:
                print(f"    ❌ ERROR writing {lang}: {e}")

    if updated_count > 0:
        print(f"    Updated {updated_count} MFE language files")


def merge_final():
    """
    Step 4: Combine Upstream and Custom Layer.
    Handles languages that exist in custom but not in upstream.
    Excludes dummy/test locales (qqq) from custom overlay only.
    Special handling: Repos in REPO_MERGE_CONFIG are merged into their target repos during this step.
    """
    print("--- Merging Final Layer (Step 4) ---")
    print(f"Merge configuration: {json.dumps(REPO_MERGE_CONFIG, indent=2)}")

    # Languages to exclude from custom overlay (keep in upstream as-is)
    exclude_langs = {'qqq'}

    if FINAL_DIR.exists():
        shutil.rmtree(FINAL_DIR)

    # Start with upstream (includes qqq from upstream)
    shutil.copytree(UPSTREAM_DIR, FINAL_DIR)

    # Overlay custom - skip excluded languages and handle repo merging
    for ext in ["**/*.po", "**/*.json"]:
        for custom_file in CUSTOM_DIR.glob(ext):
            rel_path = custom_file.relative_to(CUSTOM_DIR)

            # Skip excluded languages from custom
            skip = False
            for lang in exclude_langs:
                if f"/{lang}/" in str(rel_path) or f"/{lang}.json" in str(rel_path):
                    skip = True
                    break

            if skip:
                continue

            # Check if this repo should be merged into another repo
            repo_name = rel_path.parts[0]
            target_repo = get_merge_target_repo(repo_name)

            if target_repo:
                # Rewrite path to merge into target repo
                rel_path_parts = list(rel_path.parts)
                rel_path_parts[0] = target_repo
                final_path = Path(*rel_path_parts)
                final_file = FINAL_DIR / final_path
                print(f"  Merging {repo_name} → {target_repo}: {rel_path} → {final_path}")
            else:
                final_file = FINAL_DIR / rel_path

            if not final_file.exists():
                # New file (could be new repo, new language, or both)
                ensure_directory(final_file.parent)
                shutil.copy(custom_file, final_file)
                if target_repo:
                    print(f"  Created new merged file: {final_path}")
                else:
                    print(f"  Copied new custom file: {rel_path}")
                continue

            # Merge contents for existing files
            if custom_file.suffix == ".po":
                try:
                    final_po = polib.pofile(final_file)
                    custom_po = polib.pofile(custom_file)

                    added = 0
                    for entry in custom_po:
                        if entry.msgid and not entry.obsolete:
                            final_po.append(entry)
                            added += 1

                    final_po.save(final_file)

                    if added > 0:
                        merge_target = f"{final_path}" if target_repo else f"{rel_path}"
                        print(f"  Merged PO {merge_target}: +{added} custom strings appended")

                except Exception as e:
                    print(f"  ERROR merging PO {rel_path}: {e}")
                    print(f"  Skipping malformed file and using custom version")
                    shutil.copy(custom_file, final_file)

            elif custom_file.suffix == ".json":
                try:
                    with open(final_file, "r", encoding="utf-8") as f:
                        final_data = json.load(f)
                except json.JSONDecodeError as e:
                    print(f"  WARNING: Malformed upstream JSON {rel_path}: {e}")
                    print(f"  Using custom file as base instead")
                    shutil.copy(custom_file, final_file)
                    continue
                except Exception as e:
                    print(f"  ERROR reading upstream JSON {rel_path}: {e}")
                    shutil.copy(custom_file, final_file)
                    continue

                try:
                    with open(custom_file, "r", encoding="utf-8") as f:
                        custom_data = json.load(f)
                except json.JSONDecodeError as e:
                    print(f"  WARNING: Malformed custom JSON {rel_path}: {e}")
                    print(f"  Skipping custom overlay for this file")
                    continue
                except Exception as e:
                    print(f"  ERROR reading custom JSON {rel_path}: {e}")
                    continue

                try:
                    final_data.update(custom_data)
                    added = len(custom_data)

                    with open(final_file, "w", encoding="utf-8") as f:
                        json.dump(final_data, f, indent=2, sort_keys=True, ensure_ascii=False)

                    if added > 0:
                        merge_target = f"{final_path}" if target_repo else f"{rel_path}"
                        print(f"  Merged JSON {merge_target}: +{added} custom keys appended")
                except Exception as e:
                    print(f"  ERROR writing merged JSON {rel_path}: {e}")

    # Print summary of merged repos
    merged_repos = [f"{src} → {config['merge_into']}" for src, config in REPO_MERGE_CONFIG.items()]
    if merged_repos:
        print(f"\nMerged repos: {', '.join(merged_repos)}")

    print("--- Merge Complete ---")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")

    p_update = subparsers.add_parser("update_custom")
    p_update.add_argument("--extracted-dir", required=True)

    p_merge = subparsers.add_parser("merge_final")

    args = parser.parse_args()

    if args.command == "update_custom":
        print(f"Base Directory: {REPO_ROOT}")
        print(f"Upstream Directory: {UPSTREAM_DIR}")
        print(f"Custom Directory: {CUSTOM_DIR}")
        update_custom_layer(args.extracted_dir)
    elif args.command == "merge_final":
        merge_final()
