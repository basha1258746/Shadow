import json
import urllib.request
import urllib.parse

import settings as settings_store

# ---------------- Shadow ONLINE MODE ----------------
#
# Everything here touches the internet, so it
# lives behind one explicit voice switch
# ("online on" / "online off", default OFF).
# When the gate is closed, every route
# answers honestly instead of silently
# failing.
#
# No API keys, no accounts: weather comes
# from Open-Meteo (free for non-commercial
# use), encyclopedia lookups from Wikipedia,
# and general web search from DuckDuckGo's
# HTML endpoint. Only text goes out; nothing
# about his installation or his master.

DEFAULT_CITY = "MyCity"

ONLINE_ENABLED_KEY = "online_enabled"

ONLINE_CITY_KEY = "online_city"

REQUEST_TIMEOUT = 12

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "Shadow-local-assistant"
)


def is_online_enabled():
    return bool(
        settings_store.get_setting(
            ONLINE_ENABLED_KEY
        )
    )


def set_online_enabled(value):
    settings_store.set_setting(
        ONLINE_ENABLED_KEY, bool(value)
    )

    state = "ON" if value else "OFF"

    return (
        f"Online mode is now {state}, sir. "
        + (
            "I may reach the internet when "
            "you ask me to look something up."
            if value
            else "I will stay entirely on "
            "this laptop until you say "
            "'online on'."
        )
    )


def online_status_text():
    city = settings_store.get_setting(
        ONLINE_CITY_KEY
    ) or DEFAULT_CITY

    return (
        "Online mode: "
        + (
            "ON"
            if is_online_enabled()
            else "OFF (default - say 'online on' "
            "to let me reach the internet)"
        )
        + f"\nCity for weather: {city}"
        + "\nWhat I can do when ON:"
        + "\n- 'weather' / 'weather tomorrow'"
        + "\n- 'look up <topic>' - Wikipedia"
        + "\n- 'search the web for <topic>'"
    )


def _fetch_json(url):
    request = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT},
    )

    with urllib.request.urlopen(
        request, timeout=REQUEST_TIMEOUT
    ) as response:
        return json.loads(
            response.read().decode(
                "utf-8", errors="replace"
            )
        )


def _fetch_text(url):
    request = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT},
    )

    with urllib.request.urlopen(
        request, timeout=REQUEST_TIMEOUT
    ) as response:
        return response.read().decode(
            "utf-8", errors="replace"
        )


def _geocode(city):
    # Open-Meteo's free geocoder: name to
    # latitude/longitude.

    url = (
        "https://geocoding-api.open-meteo.com"
        "/v1/search?name="
        + urllib.parse.quote(city)
        + "&count=1&language=en&format=json"
    )

    data = _fetch_json(url)

    results = data.get("results") or []

    if not results:
        return None

    hit = results[0]

    return {
        "name": hit.get("name", city),
        "region": hit.get("admin1", ""),
        "country": hit.get("country", ""),
        "lat": hit["latitude"],
        "lon": hit["longitude"],
    }


def _wind_direction(degrees):
    try:
        degrees = int(degrees) % 360

    except (TypeError, ValueError):
        return ""

    compass = (
        "N", "NE", "E", "SE",
        "S", "SW", "W", "NW",
    )

    return compass[
        int((degrees + 22) // 45) % 8
    ]


WEATHER_CODES = {
    0: "clear sky",
    1: "mostly clear",
    2: "partly cloudy",
    3: "overcast",
    45: "fog",
    48: "freezing fog",
    51: "light drizzle",
    53: "drizzle",
    55: "heavy drizzle",
    61: "light rain",
    63: "rain",
    65: "heavy rain",
    71: "light snow",
    73: "snow",
    75: "heavy snow",
    80: "rain showers",
    81: "rain showers",
    82: "violent rain showers",
    95: "a thunderstorm",
    96: "a thunderstorm with hail",
    99: "a thunderstorm with hail",
}


def _weather_for(place, daily):
    lat = place["lat"]

    lon = place["lon"]

    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}&longitude={lon}"
        "&current=temperature_2m,"
        "relative_humidity_2m,"
        "apparent_temperature,"
        "weather_code,wind_speed_10m,"
        "wind_direction_10m"
    )

    if daily:
        url += (
            "&daily=temperature_2m_max,"
            "temperature_2m_min,"
            "precipitation_probability_max,"
            "weather_code"
            "&forecast_days=2"
        )

    data = _fetch_json(url)

    if daily:
        day = data["daily"]

        code = day["weather_code"][1]

        return (
            f"Tomorrow in {place['name']}: "
            f"{WEATHER_CODES.get(code, 'changing skies')}, "
            f"between "
            f"{round(day['temperature_2m_min'][1])} "
            f"and "
            f"{round(day['temperature_2m_max'][1])} "
            "degrees, with a "
            f"{day['precipitation_probability_max'][1]} "
            "percent chance of rain."
        )

    current = data["current"]

    code = current["weather_code"]

    wind_dir = _wind_direction(
        current.get("wind_direction_10m")
    )

    return (
        f"Right now in {place['name']}: "
        f"{WEATHER_CODES.get(code, 'changing skies')}, "
        f"{round(current['temperature_2m'])} degrees "
        f"(feels like "
        f"{round(current['apparent_temperature'])}), "
        "humidity "
        f"{current['relative_humidity_2m']} percent, "
        "wind "
        f"{round(current['wind_speed_10m'])} "
        f"kilometers per hour"
        + (f" from the {wind_dir}" if wind_dir else "")
        + "."
    )


def weather_text(suffix):
    if not is_online_enabled():
        return (
            "Online mode is off, sir. Say "
            "'online on' and I will fetch the "
            "sky for you."
        )

    city = settings_store.get_setting(
        ONLINE_CITY_KEY
    ) or DEFAULT_CITY

    asking_tomorrow = "tomorrow" in suffix

    asked_place = (
        suffix.replace("tomorrow", "")
        .replace("in", " ", 1)
        if suffix.startswith("in ")
        else suffix.replace("tomorrow", "")
    )

    asked_place = asked_place.strip()

    place_name = asked_place or city

    try:
        place = _geocode(place_name)

        if place is None:
            return (
                f"I could not find '{place_name}' "
                "on the map, sir. Say 'set my city "
                "to <name>' and try again."
            )

        return _weather_for(
            place, daily=asking_tomorrow
        )

    except Exception:
        return (
            "The weather service is not "
            "answering, sir. Try again in a "
            "few minutes."
        )


WIKI_STOP_LENGTH = 300


def _clean_html(html):
    # Very small, dependency-free tag
    # stripper for one known-shaped page.

    import re

    text = re.sub(
        r"<script.*?</script>|<style.*?</style>",
        " ",
        html,
        flags=re.S | re.I,
    )

    text = re.sub(r"<[^>]+>", " ", text)

    text = re.sub(r"\s+", " ", text)

    return text.strip()


def wiki_lookup(topic):
    if not is_online_enabled():
        return (
            "Online mode is off, sir. Say "
            "'online on' if you want me to "
            "look that up."
        )

    topic = topic.strip()

    if not topic:
        return (
            "What shall I look up, sir? Say "
            "'look up' and the topic."
        )

    # Resolve the title with the opensearch
    # API, then take the clean summary from
    # the REST API - no HTML scraping, no
    # nav boilerplate.

    try:
        search_url = (
            "https://en.wikipedia.org/w/api.php"
            "?action=opensearch&search="
            + urllib.parse.quote(topic)
            + "&limit=1&format=json"
        )

        results = _fetch_json(search_url)

        titles = results[1] if (
            isinstance(results, list)
            and len(results) > 1
        ) else []

        if not titles:
            return (
                f"Wikipedia had nothing on "
                f"'{topic}', sir."
            )

        title = titles[0]

        summary_url = (
            "https://en.wikipedia.org/api/"
            "rest_v1/page/summary/"
            + urllib.parse.quote(
                title.replace(" ", "_")
            )
        )

        data = _fetch_json(summary_url)

    except Exception:
        return (
            "I could not reach Wikipedia, sir. "
            "Try again in a bit."
        )

    extract = (
        data.get("extract") or ""
    ).strip()

    if not extract:
        return (
            f"Wikipedia had nothing useful on "
            f"'{topic}', sir."
        )

    snippet = extract[:WIKI_STOP_LENGTH]

    cut = snippet.rfind(" ")

    if cut > 150:
        snippet = snippet[:cut]

    return f"On '{title}', sir: {snippet}"


DDG_STOP_LENGTH = 700


def web_search_text(topic):
    if not is_online_enabled():
        return (
            "Online mode is off, sir. Say "
            "'online on' if you want me to "
            "search the web."
        )

    topic = topic.strip()

    if not topic:
        return (
            "What shall I search for, sir? "
            "Say 'search the web for' and "
            "the topic."
        )

    # DuckDuckGo's Instant Answer API:
    # keyless, JSON, and friendly to small
    # scripts (their HTML endpoint fights
    # bots). When it has no instant answer
    # we fall back to Wikipedia and say so.

    url = (
        "https://api.duckduckgo.com/?q="
        + urllib.parse.quote(topic)
        + "&format=json&no_html=1"
        "&skip_disambig=1"
    )

    abstract = ""

    source = ""

    try:
        data = _fetch_json(url)

        abstract = (
            data.get("AbstractText") or ""
        ).strip()

        source = (
            data.get("AbstractSource") or ""
        )

        if not abstract and data.get(
                "RelatedTopics"):
            for related in data[
                    "RelatedTopics"][:1]:
                text = related.get("Text")

                if text:
                    abstract = text.strip()

                    source = "DuckDuckGo"

    except Exception:
        pass

    if abstract:
        snippet = abstract[:DDG_STOP_LENGTH]

        cut = snippet.rfind(" ")

        if cut > 150:
            snippet = snippet[:cut]

        return (
            f"From {source or 'the web'}, sir: "
            f"{snippet}"
        )

    # Fallback: the encyclopedia route.

    wiki_reply = wiki_lookup(topic)

    if "nothing" in wiki_reply or (
            "could not reach" in wiki_reply):
        return (
            "The web search came back empty, "
            "sir, and Wikipedia had nothing "
            f"on '{topic}' either."
        )

    return (
        "No instant web answer, sir, but "
        + wiki_reply
    )


def briefing_weather_line():
    # The morning briefing's weather sentence.
    # Gate-respecting by contract: when he is
    # gated or the sky is unreachable, this
    # returns None and the briefing simply
    # says nothing about weather - it never
    # opens the gate by itself.

    if not is_online_enabled():
        return None

    try:
        city = settings_store.get_setting(
            ONLINE_CITY_KEY
        ) or DEFAULT_CITY

        place = _geocode(city)

        if place is None:
            return None

        url = (
            "https://api.open-meteo.com/v1/forecast"
            f"?latitude={place['lat']}"
            f"&longitude={place['lon']}"
            "&daily=temperature_2m_max,"
            "temperature_2m_min,"
            "precipitation_probability_max,"
            "weather_code"
            "&forecast_days=2"
        )

        data = _fetch_json(url)

        day = data["daily"]

        code = day["weather_code"][1]

        return (
            f"The sky over {place['name']} "
            "tomorrow: "
            f"{WEATHER_CODES.get(code, 'changing skies')}, "
            f"between "
            f"{round(day['temperature_2m_min'][1])} "
            f"and "
            f"{round(day['temperature_2m_max'][1])} "
            "degrees, with a "
            f"{day['precipitation_probability_max'][1]} "
            "percent chance of rain."
        )

    except Exception:
        return None


def set_city_text(new_city):
    new_city = new_city.strip()

    if not new_city:
        return (
            "Which city, sir? Say 'set my city "
            "to' followed by the name."
        )

    if not is_online_enabled():
        settings_store.set_setting(
            ONLINE_CITY_KEY, new_city
        )

        return (
            f"City saved as {new_city}, sir. I "
            "will use it once online mode is "
            "on."
        )

    place = None

    try:
        place = _geocode(new_city)

    except Exception:
        pass

    if place is None:
        return (
            f"I could not find '{new_city}' on "
            "the map, sir - check the spelling?"
        )

    settings_store.set_setting(
        ONLINE_CITY_KEY, place["name"]
    )

    return (
        f"City set to {place['name']}, sir. "
        "Weather will use it from now on."
    )
