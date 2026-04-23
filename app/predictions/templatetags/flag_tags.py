from django import template

register = template.Library()

# Mapeo de codes FIFA (3 letras) a ISO-3166 alpha-2 (2 letras, minúsculas)
# Usado por flagcdn.com para renderizar banderas
FIFA_TO_ISO2 = {
    'MEX': 'mx', 'RSA': 'za', 'KOR': 'kr', 'CZE': 'cz',
    'CAN': 'ca', 'BIH': 'ba', 'QAT': 'qa', 'SUI': 'ch',
    'BRA': 'br', 'MAR': 'ma', 'HAI': 'ht', 'SCO': 'gb-sct',
    'USA': 'us', 'PAR': 'py', 'AUS': 'au', 'TUR': 'tr',
    'GER': 'de', 'CUW': 'cw', 'CIV': 'ci', 'ECU': 'ec',
    'NED': 'nl', 'JPN': 'jp', 'SWE': 'se', 'TUN': 'tn',
    'BEL': 'be', 'EGY': 'eg', 'IRN': 'ir', 'NZL': 'nz',
    'ESP': 'es', 'CPV': 'cv', 'KSA': 'sa', 'URU': 'uy',
    'FRA': 'fr', 'SEN': 'sn', 'IRQ': 'iq', 'NOR': 'no',
    'ARG': 'ar', 'ALG': 'dz', 'AUT': 'at', 'JOR': 'jo',
    'POR': 'pt', 'COD': 'cd', 'UZB': 'uz', 'COL': 'co',
    'ENG': 'gb-eng', 'CRO': 'hr', 'GHA': 'gh', 'PAN': 'pa',
}


@register.simple_tag
def flag_url(code, width=40):
    """Devuelve la URL de la bandera en flagcdn.com según el code FIFA."""
    iso2 = FIFA_TO_ISO2.get(code)
    if not iso2:
        return ''
    return f'https://flagcdn.com/w{width}/{iso2}.png'