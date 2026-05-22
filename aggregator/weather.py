"""Open-Meteo 台北天氣，免 API key。"""
import httpx

TAIPEI_LAT = 25.0330
TAIPEI_LON = 121.5654

_WMO_CODE = {
    0: "晴", 1: "大致晴", 2: "局部多雲", 3: "陰",
    45: "霧", 48: "霧凇",
    51: "毛毛雨", 53: "毛毛雨", 55: "毛毛雨",
    61: "小雨", 63: "中雨", 65: "大雨",
    66: "凍雨", 67: "凍雨",
    71: "小雪", 73: "中雪", 75: "大雪", 77: "雪粒",
    80: "陣雨", 81: "陣雨", 82: "強陣雨",
    85: "陣雪", 86: "陣雪",
    95: "雷雨", 96: "雷雨夾冰雹", 99: "強雷雨",
}


async def fetch_taipei_weather() -> str:
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": TAIPEI_LAT,
        "longitude": TAIPEI_LON,
        "current": "temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m",
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
        "timezone": "Asia/Taipei",
        "forecast_days": 2,
    }
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()

    cur = data["current"]
    daily = data["daily"]
    cur_desc = _WMO_CODE.get(cur["weather_code"], "未知")
    today_desc = _WMO_CODE.get(daily["weather_code"][0], "未知")
    tmr_desc = _WMO_CODE.get(daily["weather_code"][1], "未知")

    return (
        f"🌤 *台北天氣*\n"
        f"現在：{cur['temperature_2m']}°C，{cur_desc}，濕度 {cur['relative_humidity_2m']}%\n"
        f"今日：{daily['temperature_2m_min'][0]}–{daily['temperature_2m_max'][0]}°C，"
        f"{today_desc}，降雨機率 {daily['precipitation_probability_max'][0]}%\n"
        f"明日：{daily['temperature_2m_min'][1]}–{daily['temperature_2m_max'][1]}°C，"
        f"{tmr_desc}，降雨機率 {daily['precipitation_probability_max'][1]}%"
    )
