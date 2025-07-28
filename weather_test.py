import requests

lat, lon = 43.202273, 76.900151  # Алматы
# lat, lon = 42.713552, 27.763397
# url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current=temperature_2m,relative_humidity_2m,apparent_temperature,precipitation,cloudcover,wind_speed_10m&timezone=auto"
url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&daily=temperature_2m_min,temperature_2m_max,precipitation_sum&timezone=Europe/Moscow"
response = requests.get(url)
data = response.json()

current = data
print(current)
print(f"{current['time']}: {current['temperature_2m']}°C, влажность {current['relative_humidity_2m']}%")
