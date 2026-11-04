"""Amount in words (tafqeet) for printed checks - Arabic and English, no external dependency."""

# (singular, dual, plural 3-10) for the main unit and the sub unit of common currencies
ARABIC_CURRENCIES = {
    "EGP": (("جنيه", "جنيهان", "جنيهات"), ("قرش", "قرشان", "قروش")),
    "USD": (("دولار", "دولاران", "دولارات"), ("سنت", "سنتان", "سنتات")),
    "EUR": (("يورو", "يورو", "يورو"), ("سنت", "سنتان", "سنتات")),
    "GBP": (("جنيه إسترليني", "جنيهان إسترلينيان", "جنيهات إسترلينية"), ("بنس", "بنسان", "بنسات")),
    "SAR": (("ريال", "ريالان", "ريالات"), ("هللة", "هللتان", "هللات")),
    "AED": (("درهم", "درهمان", "دراهم"), ("فلس", "فلسان", "فلوس")),
    "KWD": (("دينار", "ديناران", "دنانير"), ("فلس", "فلسان", "فلوس")),
    "QAR": (("ريال", "ريالان", "ريالات"), ("درهم", "درهمان", "دراهم")),
    "BHD": (("دينار", "ديناران", "دنانير"), ("فلس", "فلسان", "فلوس")),
    "OMR": (("ريال", "ريالان", "ريالات"), ("بيسة", "بيستان", "بيسات")),
    "JOD": (("دينار", "ديناران", "دنانير"), ("قرش", "قرشان", "قروش")),
    "LYD": (("دينار", "ديناران", "دنانير"), ("درهم", "درهمان", "دراهم")),
    "IQD": (("دينار", "ديناران", "دنانير"), ("فلس", "فلسان", "فلوس")),
    "TND": (("دينار", "ديناران", "دنانير"), ("مليم", "مليمان", "مليمات")),
    "MAD": (("درهم", "درهمان", "دراهم"), ("سنتيم", "سنتيمان", "سنتيمات")),
    "LBP": (("ليرة", "ليرتان", "ليرات"), ("قرش", "قرشان", "قروش")),
}

_AR_UNITS = ["", "واحد", "اثنان", "ثلاثة", "أربعة", "خمسة", "ستة", "سبعة", "ثمانية", "تسعة", "عشرة",
             "أحد عشر", "اثنا عشر", "ثلاثة عشر", "أربعة عشر", "خمسة عشر", "ستة عشر", "سبعة عشر",
             "ثمانية عشر", "تسعة عشر"]
_AR_TENS = ["", "", "عشرون", "ثلاثون", "أربعون", "خمسون", "ستون", "سبعون", "ثمانون", "تسعون"]
_AR_HUNDREDS = ["", "مائة", "مائتان", "ثلاثمائة", "أربعمائة", "خمسمائة", "ستمائة", "سبعمائة", "ثمانمائة", "تسعمائة"]
# (singular, dual, plural 3-10)
_AR_SCALES = [None, ("ألف", "ألفان", "آلاف"), ("مليون", "مليونان", "ملايين"),
              ("مليار", "ملياران", "مليارات"), ("تريليون", "تريليونان", "تريليونات")]


def _ar_below_1000(n):
    hundreds, rest = divmod(n, 100)
    parts = []
    if hundreds:
        parts.append(_AR_HUNDREDS[hundreds])
    if rest:
        if rest < 20:
            parts.append(_AR_UNITS[rest])
        else:
            tens, unit = divmod(rest, 10)
            parts.append((_AR_UNITS[unit] + " و" + _AR_TENS[tens]) if unit else _AR_TENS[tens])
    return " و".join(parts)


def arabic_number(n):
    """Integer -> Arabic words (masculine)."""
    if n == 0:
        return "صفر"
    groups = []
    while n:
        n, group = divmod(n, 1000)
        groups.append(group)
    parts = []
    for index in range(len(groups) - 1, -1, -1):
        group = groups[index]
        if not group:
            continue
        if index == 0:
            parts.append(_ar_below_1000(group))
            continue
        singular, dual, plural = _AR_SCALES[index]
        if group == 1:
            parts.append(singular)
        elif group == 2:
            parts.append(dual)
        elif 3 <= group <= 10:
            parts.append(_AR_UNITS[group] + " " + plural)
        else:
            parts.append(_ar_below_1000(group) + " " + singular)
    return " و".join(parts)


def _ar_with_noun(n, forms):
    """'<number> <noun>' with the noun in the form the number requires."""
    singular, dual, plural = forms
    if n == 1:
        return singular + " واحد"
    if n == 2:
        return dual
    last = n % 100
    if 3 <= last <= 10:
        return "%s %s" % (arabic_number(n), plural)
    if 11 <= last <= 99:
        singular = _accusative(singular)
    return "%s %s" % (arabic_number(n), singular)


def _accusative(noun):
    """Tanween fatha of the counted noun after 11-99 (جنيه -> جنيهاً). Multi-word / invariable nouns are kept."""
    if " " in noun or noun[-1] in "اوىي":
        return noun
    return noun + ("\u064b" if noun[-1] == "ة" else "\u0627\u064b")


_EN_UNITS = ["", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven",
             "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen"]
_EN_TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]
_EN_SCALES = ["", "thousand", "million", "billion", "trillion"]


def _en_below_1000(n):
    parts = []
    hundreds, rest = divmod(n, 100)
    if hundreds:
        parts.append(_EN_UNITS[hundreds] + " hundred")
    if rest:
        if rest < 20:
            parts.append(_EN_UNITS[rest])
        else:
            tens, unit = divmod(rest, 10)
            parts.append(_EN_TENS[tens] + ("-" + _EN_UNITS[unit] if unit else ""))
    return " ".join(parts)


def english_number(n):
    if n == 0:
        return "zero"
    groups = []
    while n:
        n, group = divmod(n, 1000)
        groups.append(group)
    parts = []
    for index in range(len(groups) - 1, -1, -1):
        if groups[index]:
            parts.append((_en_below_1000(groups[index]) + " " + _EN_SCALES[index]).strip())
    return " ".join(parts)


def amount_to_words(amount, decimals, currency_code, unit_label, subunit_label, lang="ar"):
    """Full wording of an amount, e.g. 'ألف ومائتان وخمسون جنيه وخمسون قرشا'.

    :param decimals: number of decimals of the currency (0, 2, 3...)
    :param unit_label / subunit_label: English labels used when no Arabic label is known
    :param lang: 'ar' or 'en'
    """
    factor = 10 ** decimals
    total_minor = int(round(abs(amount) * factor))
    integral, fractional = divmod(total_minor, factor) if factor > 1 else (total_minor, 0)
    if lang == "ar":
        unit_forms, sub_forms = ARABIC_CURRENCIES.get(
            currency_code, ((unit_label,) * 3, (subunit_label or unit_label,) * 3))
        words = _ar_with_noun(integral, unit_forms) if integral else ""
        if fractional:
            frac = _ar_with_noun(fractional, sub_forms)
            words = ("%s و%s" % (words, frac)) if words else frac
        return words or "%s %s" % (arabic_number(0), unit_forms[0])
    # English
    unit = unit_label or currency_code
    if integral == 1 and unit.endswith("s"):
        unit = unit[:-1]
    words = "%s %s" % (english_number(integral), unit)
    if fractional:
        sub = subunit_label or "cents"
        if fractional == 1 and sub.endswith("s"):
            sub = sub[:-1]
        words += " and %s %s" % (english_number(fractional), sub)
    return " ".join(w if w == "and" else w.capitalize() for w in words.replace("-", "- ").split()).replace("- ", "-")
