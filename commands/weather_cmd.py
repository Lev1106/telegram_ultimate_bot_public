from imports import *
from weather_utils import *
from config import *

async def weather(update: Update, context):
    result = ""

    for coord in cities:
        lat, lon = coord[1], coord[2]
        current_data, forecast_data = get_weather(lat, lon)

        result += f"<b>{coord[0]}</b>\n"
        result += f"• {code_to_weather(current_data['weather_code'])}\n"
        result += f"• Температура: <u>{current_data['temperature_2m']}°C</u> (ощущается как <u>{current_data['apparent_temperature']}°C</u>)\n"
        result += f"• Влажность: <u>{current_data['relative_humidity_2m']}%</u>\n"
        result += f"• Ветер: <u>{current_data['wind_speed_10m']} км/ч</u>\n"
        result += f"• Осадки: <u>{current_data['precipitation']} мм/ч</u>\n"
        result += f"• Облачность: <u>{current_data['cloudcover']}%</u>\n"

        result += "<blockquote expandable>"
        for day in range(len(forecast_data['time'])):
            result += ""
            date = forecast_data['time'][day]
            date_dd_mm = date[8] + date[9] + '.' + date[5] + date[6]
            result += date_dd_mm
            if day == 0:
                result += " (сегодня)"
            elif day == 1:
                result += " (завтра)"
            elif day == 2:
                result += " (послезавтра)"
            result += f": <u>{forecast_data['temperature_2m_min'][day]}°C</u> — <u>{forecast_data['temperature_2m_max'][day]}°C</u>, "
            result += f"осадки <u>{forecast_data['precipitation_sum'][day]} мм</u>\n"
        result += "</blockquote>\n"

    await update.message.reply_text(result, parse_mode='HTML')
