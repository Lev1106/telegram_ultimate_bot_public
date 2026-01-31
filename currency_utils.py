def currency_to_currency(value, cur1, cur2):
    import requests
    url = f"https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@latest/v1/currencies/{cur1}.json"
    data = requests.get(url).json()
    return round(value * float(data[cur1][cur2]), 3)

def check_for_currency(text):
    import re
    text = text.lower()
    text = text.strip()
    text = text.replace(' ', '')
    text = text.replace('\t', '')
    text = text.replace('\n', '')
    text = text.replace(',', '.')
    value = "".join([char for char in text if char.isdigit() or char == '.'])
    result = ''
    if value == "":
        value = "1"
        # if 'kzt' in text or 'тг' in text or 'тенге' in text or '₸' in text:
        #     result += f"• {value:,} ₸\n"
        #     result += f"• {currency_to_currency(value, 'kzt', 'rub'):,} ₽\n"
        #     result += f"• {currency_to_currency(value, 'kzt', 'usd'):,} $\n"
        #     result += f"• {currency_to_currency(value, 'kzt', 'eur'):,} €\n"

    value = float(value)
    print(value)

    if re.search(r'\dkkk', text) or re.search(r'\dккк', text) or re.search(r'\dмлрд', text) or re.search(r'\dлярд', text) or re.search(r'\dмиллиард', text):
        value *= 1000000000
    elif re.search(r'\dkk', text) or re.search(r'\dкк', text) or re.search(r'\dмлн', text) or re.search(r'\dлям', text) or re.search(r'\dмиллион', text):
        value *= 1000000
    elif re.search(r'\dk', text) or re.search(r'\dк', text) or re.search(r'\dтысяч', text) or re.search(r'\dthousand', text):
        value *= 1000

    if 'rub' in text or 'руб' in text or '₽' in text:
        result += f"• {value:,} ₽\n"
        result += f"• {currency_to_currency(value, 'rub', 'kzt'):,} ₸\n"
        result += f"• {currency_to_currency(value, 'rub', 'usd'):,} $\n"
        result += f"• {currency_to_currency(value, 'rub', 'eur'):,} €\n"
    elif 'usd' in text or 'доллар' in text or 'длр' in text or '$' in text:
        result += f"• {value:,} $\n"
        result += f"• {currency_to_currency(value, 'usd', 'kzt'):,} ₸\n"
        result += f"• {currency_to_currency(value, 'usd', 'rub'):,} ₽\n"
        result += f"• {currency_to_currency(value, 'usd', 'eur'):,} €\n"
    elif 'eur' in text or 'евро' in text or 'евро' in text or '€' in text:
        result += f"• {value:,} €\n"
        result += f"• {currency_to_currency(value, 'eur', 'kzt'):,} ₸\n"
        result += f"• {currency_to_currency(value, 'eur', 'rub'):,} ₽\n"
        result += f"• {currency_to_currency(value, 'eur', 'usd'):,} $\n"
    else:
        if 'kzt' in text or 'тг' in text or 'тенге' in text or '₸' in text:
            result += f"• {value:,} ₸\n"
            result += f"• {currency_to_currency(value, 'kzt', 'rub'):,} ₽\n"
            result += f"• {currency_to_currency(value, 'kzt', 'usd'):,} $\n"
            result += f"• {currency_to_currency(value, 'kzt', 'eur'):,} €\n"
    return result

# print(check_for_currency("2ккк"))