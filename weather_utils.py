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

def get_weather(lat, lon):
    import requests
    url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&daily=temperature_2m_min,temperature_2m_max,precipitation_sum&current=weather_code,temperature_2m,relative_humidity_2m,apparent_temperature,wind_speed_10m,precipitation,cloudcover,&timezone=auto"
    data = requests.get(url).json()
    current_data = data['current']
    forecast_data = data['daily']
    return current_data, forecast_data