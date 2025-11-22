def code_to_weather(x):
    if x == 0:
        return "Ясно ☀️"
    elif x == 1:
        return "Преимущественно ясно 🌤"
    elif x == 2:
        return "Переменная облачность ⛅️"
    elif x == 3:
        return "Пасмурно ☁️"
    elif x == 45:
        return "Туман 🌫"
    elif x == 48:
        return "Туман с изморозью 🌫"
    elif 51 <= x <= 55:
        return "Небольшой дождь 🌦"
    elif 56 <= x <= 57:
        return "Небольшой ледяной дождь 🌦"
    elif 61 <= x <= 65:
        return "Дождь 🌧"
    elif 66 <= x <= 67:
        return "Ледяной дождь 🌧"
    elif 71 <= x <= 75:
        return "Снег 🌨"
    elif x == 77:
        return "Снежные зёрна 🌨"
    elif 80 <= x <= 82:
        return "Ливни 🌧"
    elif 85 <= x <= 86:
        return "Дождь со снегом 🌨"
    elif x == 95:
        return "Гроза 🌩"
    else:
        return "Гроза с градом ⛈"