"""English source text with an explicitly selected interface language."""
from functools import lru_cache
import json
from pathlib import Path

LANGUAGES = ('en', 'de')
_language = 'en'


def get_language():
    return _language


def set_language(language):
    global _language
    _language = language if language in LANGUAGES else 'en'


@lru_cache(maxsize=1)
def german_translations():
    return json.loads((Path(__file__).parent / 'locales' / 'de.json').read_text(encoding='utf-8'))


@lru_cache(maxsize=1)
def english_sources():
    return {translation: source for source, translation in german_translations().items()}


def tr(source, *arguments):
    text = german_translations().get(source, source) if _language == 'de' else source
    if text == source:
        for suffix in (' *', ' …'):
            if source.endswith(suffix):
                text = tr(source[:-len(suffix)]) + suffix
                break
    return text % arguments if arguments else text


def set_text(widget, source, setter='setText', *arguments):
    """Keep the source text on the widget so language changes preserve its state."""
    source = english_sources().get(source, source)
    bindings = widget.property('i18n_texts') or {}
    bindings[setter] = dict(source=source, arguments=list(arguments))
    widget.setProperty('i18n_texts', bindings)
    getattr(widget, setter)(tr(source, *arguments))


def retranslate(widget):
    for setter, binding in (widget.property('i18n_texts') or {}).items():
        getattr(widget, setter)(tr(binding['source'], *binding['arguments']))
    if hasattr(widget, 'updateGeometry'):
        widget.updateGeometry()
