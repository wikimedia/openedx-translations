openedx-translations
####################

Wikimedia Open edX Translations
===============================

Custom translations for the Wikimedia Open edX Platform (Teak release).
This is a fork of the standard
`openedx/openedx-translations <https://github.com/openedx/openedx-translations/>`_
repository with Wikimedia-specific customizations.


Overview
========

This repository uses a **unified translation workflow** that:

- Pulls upstream translations from the official Open edX translations repository
- Extracts custom strings from Wikimedia's forked and custom repositories
- Automatically identifies and isolates Wikimedia-specific translations
- Generates placeholder files for all supported languages
- Merges upstream and custom translations into a production-ready bundle


Directory Structure
===================

::

   openedx-translations/
   ├── translations-custom/       # Wikimedia-specific custom translations only
   └── translations/              # Final merged translations (used in production)


How It Works
============

Automated Workflow
------------------

The translation sync runs automatically via GitHub Actions:

1. **Pull Upstream**
   Gets latest translations from Open edX (``release/teak``)

2. **Extract Custom**
   Pulls English source strings from Wikimedia's custom repositories

3. **Isolate Differences**
   Identifies only the strings unique to Wikimedia

4. **Generate Placeholders**
   Creates empty translation files for all languages

5. **Merge**
   Combines upstream with Wikimedia custom translations


Running the Workflow
--------------------

To sync translations:

1. Go to the **Actions** tab in GitHub
2. Click **Wikimedia Translation Workflow**
3. Click **Run workflow**
4. Select branch: ``release/teak``
5. Click **Run workflow**

The workflow will automatically create a pull request with updated translations
and merge it if successful.


Adding Translations
==================

For Translators
---------------

If you're translating content, work in the ``translations-custom/`` directory.

Python Repositories
~~~~~~~~~~~~~~~~~~~

For Python repositories such as *edx-platform* and themes:

- Navigate to::

     translations-custom/{repository-name}/conf/locale/{language-code}/LC_MESSAGES/

- Edit the ``.po`` files:

  - ``django.po`` for templates
  - ``djangojs.po`` for JavaScript

**Example**::

   translations-custom/tutor-indigo-wikilearn/conf/locale/ar/LC_MESSAGES/django.po


Frontend Applications (MFEs)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

For frontend applications:

- Navigate to::

     translations-custom/{repository-name}/src/i18n/messages/

- Edit the language JSON file (for example ``ar.json``)

**Example**::

   translations-custom/frontend-app-messenger/src/i18n/messages/ar.json


After Making Changes
~~~~~~~~~~~~~~~~~~~~

1. Save your files
2. Commit the changes
3. Create a pull request
4. Once merged, run the workflow again to update the final ``translations/`` directory


Translation File Formats
========================

Python Repositories (``.po`` files)
-----------------------------------

These are text files with the following format::

   msgid "Welcome"
   msgstr "مرحبا"

   msgid "Sign In"
   msgstr "تسجيل الدخول"

- ``msgid``: The English source text (do not change)
- ``msgstr``: Your translation


MFE Repositories (``.json`` files)
----------------------------------

These are JSON files with the following format::

   {
     "welcome.message": "مرحبا",
     "signin.button": "تسجيل الدخول"
   }

- **Key** (left side): Do not change
- **Value** (right side): Add your translation


Using in Tutor
==============

To use these translations in your Tutor installation, configure::


   ATLAS_REPOSITORY: wikimedia/openedx-translations
   ATLAS_REVISION: release/teak

Then rebuild and redeploy.
