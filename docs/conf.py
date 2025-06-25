project = 'Butty ODM'
copyright = '2025, Anton Ovsyannikov'
author = 'Anton Ovsyannikov'
release = '1.0.0'

templates_path = ['_templates']
exclude_patterns = ['_build', 'Thumbs.db', '.DS_Store']

html_theme = 'alabaster'
html_static_path = ['_static']

extensions = [
    'sphinx.ext.autodoc',
    'myst_parser',
]
source_suffix = ['.rst', '.md']
