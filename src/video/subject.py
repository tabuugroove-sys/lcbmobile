"""Conservative metadata checks; these do not claim biometric identity verification."""
import re
import unicodedata


def plain(value: str) -> str:
    return re.sub(r'[^a-z0-9]+', ' ', unicodedata.normalize('NFKD', value).encode('ascii','ignore').decode().lower()).strip()


def matches_subject(artist: str | None, *metadata: str) -> bool:
    if not artist:
        return False
    name = plain(artist)
    text = ' ' + plain(' '.join(metadata)) + ' '
    if ' ' + name + ' ' not in text:
        return False
    excluded = {
        'leonardo': ('da vinci', 'jardim', 'dicaprio', 'di caprio', 'bonucci'),
        'joao gomes': ('cravinho', 'wolverhampton', 'wolves', 'futebol', 'flamengo', 'volante'),
        'roberto carlos': ('lateral', 'real madrid', 'futebol'),
    }
    return not any(' '+term+' ' in text for term in excluded.get(name, ()))
